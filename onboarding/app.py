#!/usr/bin/env python3
"""
Strava Custom Coach — Customer Onboarding Web App (Secured)
Each customer gets their own isolated Docker container with their own bot.

Security measures applied:
  1. HTTPS enforced via ProxyFix (nginx + certbot handles TLS termination)
  2. Admin page protected by HTTP Basic Auth
  3. Rate limiting on onboard endpoint (flask-limiter)
  4. Strong session secret enforced — app refuses to start without it
  5. Input sanitization — username stripped to safe characters, path traversal blocked
  6. Docker containers resource-limited (RAM + CPU)
"""

import json
import os
import re
import secrets
import subprocess
import urllib.parse
import urllib.request
from functools import wraps
from pathlib import Path

from flask import Flask, render_template, request, redirect, session, jsonify, Response
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)

# ── SECURITY FIX 1: Strong session secret ─────────────────────────────────────
# The app refuses to start if FLASK_SECRET is missing or still the default.
# Without a strong secret, anyone can forge session cookies and impersonate users.
_secret = os.environ.get("FLASK_SECRET", "")
if not _secret or _secret == "change-me-in-production":
    raise RuntimeError(
        "\n\n🔴 FLASK_SECRET is not set or is using the default value.\n"
        "   Generate one with:  python3 -c \"import secrets; print(secrets.token_hex(32))\"\n"
        "   Then set:           export FLASK_SECRET=<that value>\n"
    )
app.secret_key = _secret

# ── SECURITY FIX 2: ProxyFix + secure cookies for HTTPS ───────────────────────
# When nginx sits in front and handles TLS, Flask sees plain HTTP internally.
# ProxyFix tells Flask to trust the X-Forwarded-Proto header from nginx so that
# redirects and secure cookies work correctly over HTTPS.
# Secure cookies are only sent over HTTPS and not accessible from JavaScript.
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.config["SESSION_COOKIE_SECURE"]   = True   # only sent over HTTPS
app.config["SESSION_COOKIE_HTTPONLY"] = True    # JS cannot read session cookie
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"  # basic CSRF protection

# ── SECURITY FIX 3: Rate limiting ─────────────────────────────────────────────
# Without rate limiting, anyone could spam /onboard and spin up hundreds of
# containers, exhausting your VPS resources and Anthropic API quota.
# - /onboard: max 10 signups per IP per hour
# - /status:  max 30 requests per minute
# - Global:   200 per day, 50 per hour
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://",
)

# ── Config ────────────────────────────────────────────────────────────────────

BASE_DIR        = Path(os.environ.get("USERS_BASE_DIR", Path.home() / "strava-coach" / "users"))
CODE_DIR        = Path(os.environ.get("CODE_DIR",       Path.home() / "strava-coach" / "code"))
PUBLIC_URL      = os.environ.get("PUBLIC_URL", "http://localhost:5000")
STRAVA_REDIRECT = f"{PUBLIC_URL}/strava/callback"

# Admin credentials — set as environment variables, never hardcoded
ADMIN_USER     = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")


# ── SECURITY FIX 4: Input sanitization + path traversal prevention ────────────
# Usernames are used to build Docker container names AND filesystem paths.
# Without sanitization, "../../etc/passwd" could read system files,
# or "--rm" could interfere with Docker commands.
# We enforce: lowercase alphanumeric + hyphens only, no leading/trailing hyphens.

def slug(name: str) -> str:
    """Turn a display name into a safe container/folder name."""
    cleaned = re.sub(r"[^a-z0-9]", "-", name.lower().strip())
    cleaned = cleaned.strip("-")
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    return cleaned[:30]


def safe_username(raw: str) -> str | None:
    """Validate and sanitize username. Returns None if invalid."""
    if not raw or not raw.strip():
        return None
    s = slug(raw)
    if len(s) < 2:
        return None
    return s


def validate_container_name(name: str) -> bool:
    """Ensure container name matches expected pattern before passing to Docker.
    Prevents command injection via container name argument."""
    return bool(re.match(r"^strava-coach-[a-z0-9][a-z0-9-]{1,28}$", name))


def user_dir(username: str) -> Path:
    """Build user config path and verify it stays within BASE_DIR.
    This is the final guard against path traversal attacks."""
    p = (BASE_DIR / slug(username) / "config").resolve()
    if not str(p).startswith(str(BASE_DIR.resolve())):
        raise ValueError(f"Path traversal detected for username: {username}")
    return p


# ── SECURITY FIX 5: Admin HTTP Basic Auth ─────────────────────────────────────
# /admin shows all users, container status, and partial bot tokens.
# Without auth, any visitor who finds the URL sees your full user list.
# secrets.compare_digest prevents timing attacks (comparing char-by-char
# would leak info about how many characters matched).

def check_admin_auth(username: str, password: str) -> bool:
    if not ADMIN_PASSWORD:
        return False  # If password not set, block all admin access
    user_ok = secrets.compare_digest(username, ADMIN_USER)
    pass_ok = secrets.compare_digest(password, ADMIN_PASSWORD)
    return user_ok and pass_ok


def require_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_admin_auth(auth.username, auth.password):
            return Response(
                "Admin access required.",
                401,
                {"WWW-Authenticate": 'Basic realm="Strava Coach Admin"'},
            )
        return f(*args, **kwargs)
    return decorated


# ── Helpers ───────────────────────────────────────────────────────────────────

def write_config(username: str, data: dict):
    d = user_dir(username)
    d.mkdir(parents=True, exist_ok=True)
    (d / "config.json").write_text(json.dumps(data, indent=2))


def read_config(username: str) -> dict:
    p = user_dir(username) / "config.json"
    return json.loads(p.read_text()) if p.exists() else {}


def save_tokens(username: str, tokens: dict):
    d = user_dir(username)
    d.mkdir(parents=True, exist_ok=True)
    (d / "tokens.json").write_text(json.dumps(tokens, indent=2))


def container_name(username: str) -> str:
    return f"strava-coach-{slug(username)}"


def container_running(name: str) -> bool:
    if not validate_container_name(name):
        return False
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Running}}", name],
        capture_output=True, text=True
    )
    return result.stdout.strip() == "true"


def start_container(username: str, chat_id: str = ""):
    name = container_name(username)
    if not validate_container_name(name):
        raise ValueError(f"Invalid container name: {name}")

    cfg_dir = str(user_dir(username))
    ws_dir  = str(CODE_DIR.resolve())
    bot_token = os.environ.get("STRAVA_TELEGRAM_BOT_TOKEN", "")

    subprocess.run(["docker", "rm", "-f", name], capture_output=True)

    subprocess.run([
        "docker", "run", "-d",
        "--name",    name,
        "--restart", "unless-stopped",
        "--memory",  "256m",
        "--cpus",    "0.5",
        "--network", "bridge",
        "--read-only",
        "--tmpfs",   "/tmp",
        "-e", f"ANTHROPIC_API_KEY={os.environ.get('ANTHROPIC_API_KEY', '')}",
        "-e", f"STRAVA_TELEGRAM_BOT_TOKEN={bot_token}",
        "-e", f"STRAVA_TELEGRAM_CHAT_ID={chat_id}",
        "-e", f"PUBLIC_URL={os.environ.get('PUBLIC_URL', '')}",
        "-v", f"{ws_dir}:/workspace:ro",
        "-v", f"{cfg_dir}:/root/.config/strava",
        "-w", "/workspace",
        "python:3.11-slim",
        "bash", "-c",
        "while true; do python3 /workspace/scripts/telegram_bot.py --once; sleep 5; done"
    ], check=True)


def exchange_strava_code(code: str, config: dict) -> dict:
    data = urllib.parse.urlencode({
        "client_id":     config["client_id"],
        "client_secret": config["client_secret"],
        "code":          code,
        "grant_type":    "authorization_code",
    }).encode()
    req = urllib.request.Request(
        "https://www.strava.com/oauth/token", data=data, method="POST"
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/onboard", methods=["POST"])
@limiter.limit("10 per hour")
def onboard():
    client_id = os.environ.get("STRAVA_CLIENT_ID", "")
    if not client_id:
        return render_template("index.html", error="Server configuration error. Please contact the admin.")

    strava_url = (
        "https://www.strava.com/oauth/authorize"
        f"?client_id={client_id}"
        "&response_type=code"
        f"&redirect_uri={urllib.parse.quote(STRAVA_REDIRECT)}"
        "&approval_prompt=force"
        "&scope=read,activity:read_all"
    )
    return redirect(strava_url)


@app.route("/strava/callback")
def strava_callback():
    code  = request.args.get("code")
    error = request.args.get("error")

    if error or not code:
        return render_template("error.html", message="Strava authorization was denied.")

    # Re-validate username from session — never trust raw session data blindly
    username = safe_username(session.get("username", ""))
    if not username:
        return render_template("error.html", message="Session expired. Please start again.")

    config = read_config(username)
    if not config:
        return render_template("error.html", message="Config not found. Please start again.")

    try:
        tokens = exchange_strava_code(code, config)
    except Exception as e:
        return render_template("error.html", message=f"Strava token exchange failed: {e}")

    save_tokens(username, tokens)

    athlete      = tokens.get("athlete", {})
    athlete_name = f"{athlete.get('firstname', '')} {athlete.get('lastname', '')}".strip()

    try:
        start_container(username)
        container_ok = True
    except Exception as e:
        container_ok = False
        print(f"[onboard] Docker error for {username}: {e}")

    return render_template("success.html",
        username=username,
        athlete_name=athlete_name,
        bot_username=session.get("bot_username", ""),
        container_ok=container_ok,
    )


@app.route("/status/<username>")
@limiter.limit("30 per minute")
def status(username):
    username = safe_username(username)
    if not username:
        return jsonify({"error": "invalid username"}), 400
    name    = container_name(username)
    running = container_running(name)
    cfg     = read_config(username)
    tokens  = (user_dir(username) / "tokens.json").exists()
    return jsonify({
        "username":   username,
        "container":  name,
        "running":    running,
        "configured": bool(cfg),
        "authorized": tokens,
    })


@app.route("/admin")
@require_admin
def admin():
    users = []
    if BASE_DIR.exists():
        for d in sorted(BASE_DIR.iterdir()):
            if d.is_dir():
                cfg_dir = d / "config"
                cfg = json.loads((cfg_dir / "config.json").read_text()) if (cfg_dir / "config.json").exists() else {}
                name = container_name(d.name)
                users.append({
                    "folder":    d.name,
                    "container": name,
                    "running":   container_running(name),
                    "bot":       cfg.get("telegram_bot_token", "")[:20] + "..." if cfg.get("telegram_bot_token") else "—",
                    "ftp":       cfg.get("ftp", "—"),
                })
    return render_template("admin.html", users=users)


@app.route("/tg/callback")
def tg_callback():
    """Handle Strava OAuth callback for Telegram-initiated onboarding flows."""
    code  = request.args.get("code")
    nonce = request.args.get("state")
    error = request.args.get("error")

    if error or not code or not nonce:
        return render_template("error.html", message="Strava authorization was denied or link is invalid.")

    # Look up chat_id + user data from nonce
    # Nonces are written by the bot under CONFIG_DIR/nonces/ (shared volume).
    nonce_dir  = Path.home() / ".config" / "strava" / "nonces"
    nonce_file = nonce_dir / f"{nonce}.json"
    if not nonce_file.exists():
        return render_template("error.html", message="Link expired or already used. Send /start to the bot again.")

    try:
        nonce_data = json.loads(nonce_file.read_text())
        chat_id   = nonce_data["chat_id"]
        ftp       = nonce_data.get("ftp", 200)
        weight_kg = nonce_data.get("weight_kg", 75)
        name      = nonce_data.get("name", "")
    except Exception:
        return render_template("error.html", message="Invalid onboarding state. Please start again.")

    # Owner's Strava app credentials (shared by all customers)
    owner_config_file = Path.home() / ".config" / "strava" / "config.json"
    if not owner_config_file.exists():
        return render_template("error.html", message="Server misconfigured — owner Strava config missing.")
    owner_cfg = json.loads(owner_config_file.read_text())
    client_id     = owner_cfg.get("client_id", "")
    client_secret = owner_cfg.get("client_secret", "")

    if not all([client_id, client_secret]):
        return render_template("error.html", message="Server misconfigured — Strava credentials missing.")

    # Per-user dir: ~/.config/strava/users/{chat_id}/
    # This matches what telegram_bot.py expects in multi-tenant mode.
    per_user_dir = Path.home() / ".config" / "strava" / "users" / chat_id
    per_user_dir.mkdir(parents=True, exist_ok=True)

    # Exchange Strava code for tokens
    config = {"client_id": client_id, "client_secret": client_secret}
    try:
        tokens = exchange_strava_code(code, config)
    except Exception as e:
        return render_template("error.html", message=f"Strava token exchange failed: {e}")

    athlete      = tokens.get("athlete", {})
    athlete_name = f"{athlete.get('firstname', '')} {athlete.get('lastname', '')}".strip() or chat_id

    # Write per-user config.json and tokens.json directly to per_user_dir
    (per_user_dir / "config.json").write_text(json.dumps({
        "client_id":                      client_id,
        "client_secret":                  client_secret,
        "telegram_bot_token":             os.environ.get("STRAVA_TELEGRAM_BOT_TOKEN", ""),
        "telegram_chat_id":               chat_id,
        "name":                           name,
        "ftp":                            ftp,
        "weight_kg":                      weight_kg,
        "monitoring_frequency_minutes":   30,
        "training_plan_active":           False,
        "notification_on_plan_deviation": True,
        "persona":                        "pogi",
        "webhook_verify_token":           os.environ.get("WEBHOOK_VERIFY_TOKEN", "strava-coach"),
    }, indent=2))
    (per_user_dir / "tokens.json").write_text(json.dumps(tokens, indent=2))

    # Set $0 quota — admin must manually grant demo allowance
    (per_user_dir / "demo_quota.json").write_text(json.dumps({
        "allowance_usd": 0.00,
        "spent_usd": 0.0,
    }, indent=2))

    # Clean up nonce file
    try:
        nonce_file.unlink(missing_ok=True)
    except Exception:
        pass

    bot_token = os.environ.get("STRAVA_TELEGRAM_BOT_TOKEN", "")
    admin_id  = os.environ.get("ADMIN_CHAT_ID", "")

    def _tg_send(to_chat_id, text):
        try:
            data = urllib.parse.urlencode({
                "chat_id":    to_chat_id,
                "text":       text,
                "parse_mode": "Markdown",
            }).encode()
            req = urllib.request.Request(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                data=data, method="POST"
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp.read()
        except Exception as e:
            print(f"[tg_callback] Telegram send error to {to_chat_id}: {e}")

    if bot_token:
        # Confirm to user
        _tg_send(chat_id,
            f"✅ *You're all set, {athlete_name}!*\n\n"
            f"Your account is connected. The admin will activate your access shortly.\n\n"
            f"You'll be notified as soon as your demo is ready."
        )
        # Notify admin
        if admin_id:
            _tg_send(admin_id,
                f"🆕 *New user registered!*\n\n"
                f"👤 Name: *{name or athlete_name}*\n"
                f"🆔 Chat ID: `{chat_id}`\n"
                f"⚖️ Weight: {weight_kg} kg\n"
                f"⚡ FTP: {ftp} W\n\n"
                f"Grant demo access:\n"
                f"`/admin quota {chat_id} 1.00`"
            )

    return render_template("success.html",
        username=athlete_name,
        athlete_name=athlete_name,
        bot_username="",
        container_ok=True,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
