#!/usr/bin/env python3
"""
Custom Coach — Customer Onboarding Web App (Secured)
Each customer gets their own isolated Docker container with their own bot.

Security measures applied:
  1. HTTPS enforced via ProxyFix (nginx + certbot handles TLS termination)
  2. Admin page protected by HTTP Basic Auth
  3. Rate limiting on onboard endpoint (flask-limiter)
  4. Strong session secret enforced — app refuses to start without it
  5. Input sanitization — username stripped to safe characters, path traversal blocked
  6. Docker containers resource-limited (RAM + CPU)
"""

import hashlib
import hmac
import json
import sqlite3
import os
import re
import secrets
import subprocess
import sys
import urllib.parse
import urllib.request
from functools import wraps
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

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
    @limiter.limit("30 per minute; 5 per second")
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
    import sqlite3 as _sqlite3
    users_dir = Path.home() / ".config" / "strava" / "users"
    users = []
    total_spent_all = 0.0
    if users_dir.exists():
        for d in sorted(users_dir.iterdir()):
            if not d.is_dir():
                continue
            cfg_file    = d / "config.json"
            tokens_file = d / "tokens.json"
            quota_file  = d / "demo_quota.json"
            db_file     = d / "history.db"

            cfg    = json.loads(cfg_file.read_text())    if cfg_file.exists()    else {}
            tokens = json.loads(tokens_file.read_text()) if tokens_file.exists() else {}
            quota  = json.loads(quota_file.read_text())  if quota_file.exists()  else {}

            athlete     = tokens.get("athlete", {})
            strava_name = f"{athlete.get('firstname','')} {athlete.get('lastname','')}".strip()
            name        = strava_name or cfg.get("name", d.name)
            allowance   = quota.get("allowance_usd")
            spent       = quota.get("spent_usd", 0.0)
            pct         = round(spent / allowance * 100, 1) if allowance else None
            total_spent_all += spent

            # Query history stats
            queries = 0
            last_query = None
            total_cost = 0.0
            if db_file.exists():
                try:
                    with _sqlite3.connect(db_file) as conn:
                        row = conn.execute("SELECT COUNT(*), SUM(cost_usd), MAX(timestamp) FROM queries").fetchone()
                        queries, total_cost, last_query = row[0], row[1] or 0.0, row[2]
                except Exception:
                    pass

            users.append({
                "chat_id":    d.name,
                "name":       name,
                "strava":     tokens_file.exists(),
                "ftp":        cfg.get("ftp", "—"),
                "weight":     cfg.get("weight_kg", "—"),
                "notify":     cfg.get("auto_notify", True),
                "allowance":  allowance,
                "spent":      spent,
                "pct":        pct,
                "queries":    queries,
                "total_cost": round(total_cost, 4),
                "last_query": last_query or "",
            })
    total   = len(users)
    strava  = sum(1 for u in users if u["strava"])
    pending = total - strava
    over    = sum(1 for u in users if u["allowance"] and u["spent"] >= u["allowance"])
    return render_template("admin.html", users=users, total=total, strava=strava,
                           pending=pending, over=over,
                           total_spent=round(total_spent_all, 4))


@app.route("/admin/delete/<chat_id>", methods=["POST"])
@require_admin
def admin_delete_user(chat_id: str):
    """Delete a user and all their data."""
    import shutil
    if not re.match(r"^-?\d+$", chat_id):
        return "Invalid chat_id", 400
    user_dir = USERS_DIR / chat_id
    if not user_dir.exists():
        return "User not found", 404
    # Notify user before deleting
    bot_token = os.environ.get("STRAVA_TELEGRAM_BOT_TOKEN", "")
    if bot_token:
        try:
            _tg_send_msg(chat_id,
                "⛔ *Your account has been removed.*\n\n"
                "Your data has been deleted by the admin.\n"
                "Contact [@SuperMariooo](https://t.me/SuperMariooo) for more info.",
                bot_token)
        except Exception as e:
            print(f"[admin_delete] Failed to notify user {chat_id}: {e}")
    shutil.rmtree(user_dir, ignore_errors=True)
    return redirect("/admin")


@app.route("/admin/quota/<chat_id>", methods=["POST"])
@require_admin
def admin_set_quota(chat_id: str):
    """Set demo allowance for a user from the admin panel."""
    if not re.match(r"^-?\d+$", chat_id):
        return "Invalid chat_id", 400
    raw = request.form.get("allowance", "").strip().lower()
    user_dir = USERS_DIR / chat_id
    if not user_dir.exists():
        return "User not found", 404
    quota_file = user_dir / "demo_quota.json"
    quota = json.loads(quota_file.read_text()) if quota_file.exists() else {}
    prev_allowance = quota.get("allowance_usd")
    adding = raw.startswith("+")
    if raw in ("", "off", "unlimited"):
        quota["allowance_usd"] = None
    else:
        try:
            amount = float(raw.lstrip("+"))
            if adding:
                quota["allowance_usd"] = round((prev_allowance or 0.0) + amount, 2)
            else:
                quota["allowance_usd"] = amount
        except ValueError:
            return "Invalid amount", 400
    quota_file.write_text(json.dumps(quota, indent=2))

    # Notify user via Telegram
    bot_token = os.environ.get("STRAVA_TELEGRAM_BOT_TOKEN", "")
    if bot_token:
        new_allowance = quota.get("allowance_usd")
        if new_allowance is None or new_allowance > 0:
            spent = quota.get("spent_usd", 0.0)
            def _bar(allowance, s):
                pu = (s / allowance * 100) if allowance > 0 else 0
                pl = max(0.0, 100 - pu)
                return f"`{'█' * int(pu/10)}{'░' * (10 - int(pu/10))}` {pl:.0f}% remaining"
            if not (prev_allowance and prev_allowance > 0):
                msg = (
                    "✅ *Your account has been activated!*\n\n"
                    "You now have access to your AI coach.\n"
                    "Ask me anything or use /help to see what I can do."
                )
            elif adding or (new_allowance is not None and new_allowance >= prev_allowance):
                msg = (
                    f"💰 *Your allowance has been topped up!*\n\n"
                    f"{_bar(new_allowance, spent)}\n\n"
                    f"Keep coaching! Use /help to see what I can do."
                )
            else:
                msg = (
                    f"ℹ️ *Your allowance has been adjusted.*\n\n"
                    f"{_bar(new_allowance, spent)}\n\n"
                    f"Contact [@SuperMariooo](https://t.me/SuperMariooo) if you have questions."
                )
        else:
            msg = (
                "⛔ *Your demo access has been paused.*\n\n"
                "Contact [@SuperMariooo](https://t.me/SuperMariooo) to top up your account."
            )
        if msg:
            try:
                _tg_send_msg(chat_id, msg, bot_token)
            except Exception as e:
                print(f"[admin] Failed to notify user {chat_id}: {e}")

    return redirect("/admin")


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
        "name":                           athlete_name or name,
        "strava_name":                    athlete_name,
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
        _tg_send_msg(to_chat_id, text, bot_token)

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
                f"🔔 *New user quota alert*\n\n"
                f"User *{athlete_name}* (`{chat_id}`) has been created\n\n"
                f"Use `/admin quota {chat_id} <amount>` to top them up."
            )

    return render_template("success.html",
        username=athlete_name,
        athlete_name=athlete_name,
        bot_username="",
        container_ok=True,
    )


def _tg_send_msg(to_chat_id, text, bot_token=None):
    """Send a Telegram message. Uses STRAVA_TELEGRAM_BOT_TOKEN if bot_token not provided."""
    if bot_token is None:
        bot_token = os.environ.get("STRAVA_TELEGRAM_BOT_TOKEN", "")
    if not bot_token:
        return
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
        print(f"[tg_send] Telegram send error to {to_chat_id}: {e}")


# ── Strava Webhook ────────────────────────────────────────────────────────────
# Strava POSTs activity events here. We look up the user by their Strava
# athlete ID (owner_id in the event), then send them a ride analysis.

USERS_DIR          = Path.home() / ".config" / "strava" / "users"
WEBHOOK_VERIFY_TOK = os.environ.get("WEBHOOK_VERIFY_TOKEN", "strava-coach")


def _find_user_by_strava_id(owner_id: int) -> Path | None:
    """Scan all user dirs and return the one whose tokens.json athlete.id matches."""
    if not USERS_DIR.exists():
        return None
    for d in USERS_DIR.iterdir():
        if not d.is_dir():
            continue
        tf = d / "tokens.json"
        if not tf.exists():
            continue
        try:
            tokens = json.loads(tf.read_text())
            if tokens.get("athlete", {}).get("id") == owner_id:
                return d
        except Exception:
            continue
    return None


def _build_ride_message(activity, ftp, weight_kg, persona) -> str:
    """Build the Telegram-friendly ride summary."""
    from strava_api import meters_to_km, seconds_to_hm, estimate_tss, CYCLING_TYPES
    from personas import pick_feedback

    name  = activity.get("name", "Untitled")
    date  = activity.get("start_date_local", "")[:10]
    dist  = meters_to_km(activity.get("distance", 0))
    dur   = seconds_to_hm(activity.get("moving_time", 0))
    elev  = int(activity.get("total_elevation_gain", 0))
    speed = round(activity.get("average_speed", 0) * 3.6, 1)
    pwr   = activity.get("average_watts")
    max_pwr = activity.get("max_watts")
    hr    = activity.get("average_heartrate")
    max_hr = activity.get("max_heartrate")
    cad   = activity.get("average_cadence")
    cals  = activity.get("calories")
    tss   = estimate_tss(activity, ftp)
    w_per_kg = round(pwr / weight_kg, 2) if pwr and weight_kg else None
    intensity_factor = round((pwr * 1.05) / ftp, 2) if pwr and ftp else None

    p = persona
    lines = [
        f"🚴 *New ride — {name}*",
        f"_{date}   Coach: {p['name']}_",
        "",
        f"📍 {dist} km  |  {dur}  |  ↑{elev}m  |  {speed} km/h",
    ]
    if pwr:
        pwr_line = f"⚡ {int(pwr)}W avg"
        if max_pwr:
            pwr_line += f"  (max {int(max_pwr)}W)"
        if w_per_kg:
            pwr_line += f"  |  {w_per_kg} W/kg"
        lines.append(pwr_line)
        if intensity_factor:
            lines.append(f"   IF: {intensity_factor}  TSS: {tss}")
    if hr:
        hr_line = f"❤️  {int(hr)} bpm avg"
        if max_hr:
            hr_line += f"  (max {int(max_hr)})"
        lines.append(hr_line)
    if cad:
        lines.append(f"🔄 {int(cad)} rpm avg cadence")
    if cals:
        lines.append(f"🔥 {int(cals)} kcal")

    # Segment PRs
    prs = [s for s in activity.get("segment_efforts", []) if s.get("pr_rank") == 1]
    if prs:
        lines.append(f"\n🏆 *PRs ({len(prs)})*")
        for s in prs[:5]:
            lines.append(f"  · {s['name']} — {seconds_to_hm(s.get('elapsed_time', 0))}")

    # Coaching note
    zf = p["zone_feedback"]
    lines.append(f"\n{p['coach_label']}")
    if intensity_factor:
        if   intensity_factor < 0.65: note = pick_feedback(zf, "z1")
        elif intensity_factor < 0.80: note = pick_feedback(zf, "z2")
        elif intensity_factor < 0.95: note = pick_feedback(zf, "z3")
        elif intensity_factor < 1.05: note = pick_feedback(zf, "z4")
        else:                          note = pick_feedback(zf, "z5")
    else:
        note = pick_feedback(zf, "no_ftp")
    lines.append(f"_{note}_")
    return "\n".join(lines)


@app.route("/webhook", methods=["GET"])
def webhook_verify():
    """Strava sends a GET to validate the subscription."""
    mode      = request.args.get("hub.mode")
    challenge = request.args.get("hub.challenge")
    verify    = request.args.get("hub.verify_token")
    if mode == "subscribe" and verify == WEBHOOK_VERIFY_TOK:
        return jsonify({"hub.challenge": challenge})
    return Response("Forbidden", 403)


@app.route("/webhook", methods=["POST"])
def webhook_event():
    """Handle incoming Strava activity events (multi-tenant)."""
    from strava_api import get_activity, CYCLING_TYPES
    from personas import load_active_persona

    # Verify HMAC signature
    body = request.get_data()
    sig  = request.headers.get("X-Hub-Signature", "")
    if sig.startswith("sha256="):
        secret   = WEBHOOK_VERIFY_TOK.encode()
        expected = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return Response("Forbidden", 403)

    event = request.get_json(force=True, silent=True) or {}
    print(f"[webhook] Event: {event}")

    # Acknowledge immediately (Strava requires 200 within 2s)
    # We process synchronously here — acceptable for low traffic
    if event.get("object_type") != "activity" or event.get("aspect_type") == "delete":
        return Response("EVENT_RECEIVED", 200)

    owner_id    = event.get("owner_id")
    activity_id = event.get("object_id")

    if not isinstance(owner_id, int):
        return Response("EVENT_RECEIVED", 200)

    user_dir = _find_user_by_strava_id(owner_id)
    if not user_dir:
        print(f"[webhook] No user found for Strava owner_id={owner_id}")
        return Response("EVENT_RECEIVED", 200)

    try:
        activity = get_activity(activity_id, user_dir=user_dir)
    except Exception as e:
        print(f"[webhook] Failed to fetch activity {activity_id}: {e}")
        return Response("EVENT_RECEIVED", 200)

    sport = activity.get("sport_type") or activity.get("type", "")
    if sport not in CYCLING_TYPES:
        print(f"[webhook] Skipping non-cycling activity ({sport})")
        return Response("EVENT_RECEIVED", 200)

    try:
        cfg      = json.loads((user_dir / "config.json").read_text())
        if not cfg.get("auto_notify", True):
            print(f"[webhook] Notifications disabled for owner_id={owner_id} — skipping")
            return Response("EVENT_RECEIVED", 200)
        ftp      = cfg.get("ftp", 220)
        weight   = cfg.get("weight_kg", 75)
        chat_id  = str(cfg.get("telegram_chat_id", ""))
        persona  = load_active_persona(user_dir / "config.json")
        msg      = _build_ride_message(activity, ftp, weight, persona)
        bot_token = os.environ.get("STRAVA_TELEGRAM_BOT_TOKEN", "")
        if bot_token and chat_id:
            _tg_send_msg(chat_id, msg, bot_token)
            print(f"[webhook] Notified {chat_id} for activity {activity_id}")
    except Exception as e:
        print(f"[webhook] Error processing activity {activity_id}: {e}")

    return Response("EVENT_RECEIVED", 200)


# ── Admin history API ─────────────────────────────────────────────────────────

def _history_db(chat_id: str) -> Path:
    return USERS_DIR / chat_id / "history.db"


def _query_history(chat_id: str, limit: int = 50, offset: int = 0) -> list[dict]:
    db = _history_db(chat_id)
    if not db.exists():
        return []
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM queries ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset)
        ).fetchall()
    return [dict(r) for r in rows]


@app.route("/admin/history")
@require_admin
def history_index():
    """List all users with their query counts."""
    if not USERS_DIR.exists():
        return jsonify([])
    result = []
    for d in sorted(USERS_DIR.iterdir()):
        if not d.is_dir():
            continue
        db = d / "history.db"
        count = 0
        total_cost = 0.0
        last_query = None
        if db.exists():
            with sqlite3.connect(db) as conn:
                row = conn.execute("SELECT COUNT(*), SUM(cost_usd), MAX(timestamp) FROM queries").fetchone()
                count, total_cost, last_query = row[0], row[1] or 0.0, row[2]
        # Resolve name
        name = d.name
        tf = d / "tokens.json"
        if tf.exists():
            try:
                t = json.loads(tf.read_text())
                a = t.get("athlete", {})
                sn = f"{a.get('firstname','')} {a.get('lastname','')}".strip()
                if sn:
                    name = sn
            except Exception:
                pass
        result.append({
            "chat_id":    d.name,
            "name":       name,
            "queries":    count,
            "total_cost": round(total_cost, 6),
            "last_query": last_query,
        })
    return jsonify(result)


@app.route("/admin/history/<chat_id>")
@require_admin
def history_user(chat_id: str):
    """Return query history for one user. Supports ?limit=50&offset=0."""
    limit  = min(int(request.args.get("limit",  50)), 500)
    offset = int(request.args.get("offset", 0))
    rows   = _query_history(chat_id, limit=limit, offset=offset)
    if not rows and not _history_db(chat_id).exists():
        return jsonify({"error": f"No history found for {chat_id}"}), 404
    # Count total
    db = _history_db(chat_id)
    total = 0
    if db.exists():
        with sqlite3.connect(db) as conn:
            total = conn.execute("SELECT COUNT(*) FROM queries").fetchone()[0]
    return jsonify({
        "chat_id": chat_id,
        "total":   total,
        "limit":   limit,
        "offset":  offset,
        "rows":    rows,
    })



@app.route("/admin/<chat_id>")
@require_admin
def admin_user_history(chat_id: str):
    """HTML page — query history for one user."""
    import sqlite3 as _sqlite3
    limit  = min(int(request.args.get("limit", 50)), 500)
    offset = int(request.args.get("offset", 0))

    # Resolve name
    name = chat_id
    tf = USERS_DIR / chat_id / "tokens.json"
    if tf.exists():
        try:
            t = json.loads(tf.read_text())
            a = t.get("athlete", {})
            sn = f"{a.get('firstname','')} {a.get('lastname','')}".strip()
            if sn:
                name = sn
        except Exception:
            pass

    db = _history_db(chat_id)
    rows, total = [], 0
    if db.exists():
        try:
            with _sqlite3.connect(db) as conn:
                conn.row_factory = _sqlite3.Row
                total = conn.execute("SELECT COUNT(*) FROM queries").fetchone()[0]
                raw = conn.execute(
                    "SELECT * FROM queries ORDER BY id DESC LIMIT ? OFFSET ?",
                    (limit, offset)
                ).fetchall()
                rows = [dict(r) for r in raw]
        except Exception:
            pass

    return render_template("history_user.html",
                           chat_id=chat_id, name=name,
                           rows=rows, total=total,
                           limit=limit, offset=offset)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
