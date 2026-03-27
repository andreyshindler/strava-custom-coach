#!/usr/bin/env python3
"""
telegram_bot.py — Telegram command bot for strava-custom-coach.
Listens for commands and responds with coaching actions.

Commands:
  /coach          — Show current coach + list all options
  /coach nino     — Switch to Nino Schurter
  /coach pogi     — Switch to Tadej Pogačar
  /coach badger   — Switch to Bernard Hinault
  /coach cannibal — Switch to Eddy Merckx
  /ride           — Analyze latest ride
  /plan           — Show today's planned workout
  /week           — Show this week's plan
  /stats          — Last 7 days summary
  /help           — Show all commands

Usage:
    # Run once (poll for pending messages then exit)
    ./scripts/telegram_bot.py --once

    # Run continuously (long-polling loop)
    ./scripts/telegram_bot.py --loop

    # Add to crontab for lightweight polling every 5 min:
    # */5 * * * * /path/to/scripts/telegram_bot.py --once
"""

import fcntl
import json
import logging
import logging.handlers
import os
import sqlite3
import sys
import time
import urllib.request
import urllib.parse
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timedelta

try:
    import whisper as _whisper
    _WHISPER_AVAILABLE = True
except ImportError:
    _whisper = None
    _WHISPER_AVAILABLE = False

sys.path.insert(0, os.path.dirname(__file__))
from personas import PERSONAS, load_active_persona, get_persona, save_active_persona, pick_feedback
from strava_api import get_activities, load_config, meters_to_km, seconds_to_hm, estimate_tss, urlopen_with_retry

CONFIG_DIR   = Path.home() / ".config" / "strava"
OFFSET_FILE  = CONFIG_DIR / "telegram_update_offset.txt"
CONFIG_FILE  = CONFIG_DIR / "config.json"
LOG_FILE     = CONFIG_DIR / "bot.log"
PUBLIC_URL   = os.environ.get("PUBLIC_URL", "http://localhost:5000")


def _init_strava_config():
    """Seed config.json from env vars on startup (Docker env → file)."""
    cfg = json.loads(CONFIG_FILE.read_text()) if CONFIG_FILE.exists() else {}
    if os.environ.get("STRAVA_CLIENT_ID"):
        cfg["client_id"] = os.environ["STRAVA_CLIENT_ID"]
    if os.environ.get("STRAVA_CLIENT_SECRET"):
        cfg["client_secret"] = os.environ["STRAVA_CLIENT_SECRET"]
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))

_init_strava_config()


# ── Per-user data dir ─────────────────────────────────────────────────────────
# In Docker per-user mode (STRAVA_TELEGRAM_CHAT_ID set), the mounted dir IS the
# user's config dir, so we use CONFIG_DIR directly.
# In multi-tenant mode, each user gets CONFIG_DIR/users/{chat_id}/.

_UDIR: Path = CONFIG_DIR  # updated per-message in handle_message


def get_user_dir(chat_id: str) -> Path:
    if os.environ.get("STRAVA_TELEGRAM_CHAT_ID"):
        return CONFIG_DIR          # Docker: already mounted per-user
    p = CONFIG_DIR / "users" / chat_id
    p.mkdir(parents=True, exist_ok=True)
    return p


# ── Per-user demo quota (dollar-based) ───────────────────────────────────────
# Stored in <user_dir>/demo_quota.json:
#   {"allowance_usd": 2.00, "spent_usd": 0.0012}
# allowance_usd=null means unlimited (no quota).
# Only Anthropic API calls cost money; Strava/Telegram are free.
#
# Pricing: claude-sonnet-4-x  $3/MTok input  $15/MTok output
_AI_INPUT_COST_PER_TOKEN  = 3.00  / 1_000_000
_AI_OUTPUT_COST_PER_TOKEN = 15.00 / 1_000_000

def _quota_file(user_dir: Path) -> Path:
    return user_dir / "demo_quota.json"

def get_demo_quota(user_dir: Path) -> dict:
    """Return {"allowance_usd": float|None, "spent_usd": float}."""
    f = _quota_file(user_dir)
    if not f.exists():
        return {"allowance_usd": None, "spent_usd": 0.0}
    try:
        return json.loads(f.read_text())
    except Exception:
        return {"allowance_usd": None, "spent_usd": 0.0}

def set_demo_allowance(user_dir: Path, allowance_usd: float | None):
    """Set or remove the dollar allowance for a user. Preserves current spend."""
    quota = get_demo_quota(user_dir)
    quota["allowance_usd"] = allowance_usd
    user_dir.mkdir(parents=True, exist_ok=True)
    _quota_file(user_dir).write_text(json.dumps(quota))

def record_ai_cost(user_dir: Path, input_tokens: int, output_tokens: int) -> float:
    """Add the cost of one Anthropic call to the user's spend. Returns cost in USD."""
    cost = (input_tokens  * _AI_INPUT_COST_PER_TOKEN +
            output_tokens * _AI_OUTPUT_COST_PER_TOKEN)
    quota = get_demo_quota(user_dir)
    quota["spent_usd"] = round(quota.get("spent_usd", 0.0) + cost, 8)
    _quota_file(user_dir).write_text(json.dumps(quota))
    # Track for query logger (reset each message)
    _ai_usage["input_tokens"]  += input_tokens
    _ai_usage["output_tokens"] += output_tokens
    _ai_usage["cost_usd"]      += cost
    return cost


# Per-message AI usage accumulator — reset at start of each handle_message call
_ai_usage: dict = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}


# ── Per-user query history (SQLite) ───────────────────────────────────────────

def _db_path(user_dir: Path) -> Path:
    return user_dir / "history.db"


def _db_init(user_dir: Path):
    """Create the queries table if it doesn't exist."""
    with sqlite3.connect(_db_path(user_dir)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS queries (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp    TEXT    NOT NULL,
                user_id      TEXT    NOT NULL,
                user_name    TEXT    NOT NULL,
                query        TEXT    NOT NULL,
                tokens_used  INTEGER NOT NULL DEFAULT 0,
                cost_usd     REAL    NOT NULL DEFAULT 0.0,
                response     TEXT    NOT NULL
            )
        """)


def log_query(user_dir: Path, user_id: str, user_name: str,
              query: str, response: str,
              tokens_used: int = 0, cost_usd: float = 0.0):
    """Append one row to the user's query history database."""
    try:
        _db_init(user_dir)
        with sqlite3.connect(_db_path(user_dir)) as conn:
            conn.execute(
                "INSERT INTO queries (timestamp, user_id, user_name, query, tokens_used, cost_usd, response) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    datetime.utcnow().isoformat(timespec="seconds"),
                    user_id,
                    user_name,
                    query,
                    tokens_used,
                    round(cost_usd, 8),
                    response[:4000],  # cap to avoid huge rows
                )
            )
    except Exception as e:
        log.warning(f"[history] Failed to log query for {user_id}: {e}")

def cmd_notify(user_dir: Path, args: list, token: str = "", chat_id: str = "") -> str:
    """Toggle or show automatic ride notification setting."""
    cfg_file = user_dir / "config.json"
    cfg = json.loads(cfg_file.read_text()) if cfg_file.exists() else {}
    current = cfg.get("auto_notify", True)

    if not args:
        status = "🟢 ON" if current else "🔴 OFF"
        if token and chat_id:
            tg_api_json(token, "sendMessage", {
                "chat_id":    chat_id,
                "text":       f"*Ride notifications:* {status}\n\nI'll {'automatically send you a summary after every ride' if current else 'stay quiet — use /ride to check manually'}.",
                "parse_mode": "Markdown",
                "reply_markup": {"inline_keyboard": [[
                    {"text": "🟢 Turn ON",  "callback_data": "notify_on"},
                    {"text": "🔴 Turn OFF", "callback_data": "notify_off"},
                ]]},
            })
            return None
        return f"*Ride notifications:* {status}\n\nToggle with `/notify on` or `/notify off`"

    arg = args[0].lower()
    if arg == "on":
        cfg["auto_notify"] = True
        cfg_file.write_text(json.dumps(cfg, indent=2))
        return "🟢 *Ride notifications ON*\n\nI'll message you automatically after every ride."
    elif arg == "off":
        cfg["auto_notify"] = False
        cfg_file.write_text(json.dumps(cfg, indent=2))
        return "🔴 *Ride notifications OFF*\n\nUse /ride anytime to check your latest ride manually."
    else:
        return "Usage: `/notify on` or `/notify off`"


def cmd_quota(user_dir: Path) -> str:
    """Show the user their current AI usage and quota."""
    _, spent, allowance = check_demo_quota(user_dir)
    if allowance is None:
        return (
            f"*Your coaching credits:*\n\n"
            f"♾️ Unlimited access"
        )
    pct_used = (spent / allowance * 100) if allowance > 0 else 100
    pct_left  = max(0.0, 100 - pct_used)
    bar_filled = int(pct_used / 10)
    bar = "█" * bar_filled + "░" * (10 - bar_filled)
    if pct_left == 0:
        status = "🔴 Credits used up — contact admin to top up"
    elif pct_left < 20:
        status = "🟡 Running low — contact admin to top up"
    else:
        status = "🟢 Active"
    return (
        f"*Your coaching credits:*\n\n"
        f"{bar} {pct_left:.0f}% remaining\n\n"
        f"Status: {status}"
    )


def check_demo_quota(user_dir: Path) -> tuple[bool, float, float | None]:
    """Return (allowed, spent_usd, allowance_usd). allowed=True when under quota or unlimited."""
    quota      = get_demo_quota(user_dir)
    allowance  = quota.get("allowance_usd")
    spent      = quota.get("spent_usd", 0.0)
    if allowance is None:
        return True, spent, None
    return spent < allowance, spent, allowance


# ── Onboarding wizard (in-bot Strava auth flow) ───────────────────────────────

def _onboard_state_file(udir: Path) -> Path:
    return udir / "onboard_state.json"

def load_onboard_state(udir: Path) -> dict:
    f = _onboard_state_file(udir)
    if f.exists():
        try:
            return json.loads(f.read_text())
        except Exception as e:
            log.warning(f"Onboarding state corrupted at {f} ({e}) — resetting")
    return {}

def save_onboard_state(udir: Path, state: dict):
    udir.mkdir(parents=True, exist_ok=True)
    _onboard_state_file(udir).write_text(json.dumps(state, indent=2))

def clear_onboard_state(udir: Path):
    f = _onboard_state_file(udir)
    if f.exists():
        f.unlink()

def _build_strava_auth_url(nonce: str) -> str:
    import urllib.parse as _up
    cfg = json.loads(CONFIG_FILE.read_text()) if CONFIG_FILE.exists() else {}
    client_id = cfg.get("client_id", os.environ.get("STRAVA_CLIENT_ID", ""))
    callback  = f"{PUBLIC_URL}/tg/callback"
    params = _up.urlencode({
        "client_id":       client_id,
        "response_type":   "code",
        "redirect_uri":    callback,
        "approval_prompt": "force",
        "scope":           "read,activity:read_all",
        "state":           nonce,
    })
    return f"https://www.strava.com/oauth/authorize?{params}"

def handle_onboarding(token: str, chat_id: str, text: str, udir: Path):
    """Run the onboarding wizard for users who haven't connected Strava yet."""
    import secrets as _secrets
    text = text.strip()
    state = load_onboard_state(udir)

    if text.lower() in ("/start", "/setup") or not state:
        save_onboard_state(udir, {"step": "name"})
        send_message(token, chat_id,
            "👋 *Welcome to Strava Custom Coach!*\n\n"
            "Let's get you set up in 3 quick steps.\n\n"
            "*What's your name?*\n\n"
            "📋 [Privacy Policy](https://srv1515969.hstgr.cloud/privacy)"
        )
        return

    if text.lower() in ("/cancel", "/restart"):
        clear_onboard_state(udir)
        send_message(token, chat_id, "Setup cancelled. Send /start to begin again.")
        return

    step = state.get("step")

    if step == "name":
        name = text.strip()
        if not name or len(name) < 2:
            send_message(token, chat_id, "❌ Please enter your name (at least 2 characters).")
            return
        save_onboard_state(udir, {"step": "weight", "name": name})
        send_message(token, chat_id,
            f"Nice to meet you, *{name}*! 💪\n\n"
            "*What is your weight in kg?*\n\n"
            "_(e.g. 75)_"
        )
        return

    if step == "weight":
        try:
            weight_kg = float(text.replace(",", "."))
            if not 30 <= weight_kg <= 250:
                raise ValueError
        except ValueError:
            send_message(token, chat_id, "❌ Please enter a valid weight between 30 and 250 kg.")
            return
        save_onboard_state(udir, {**state, "step": "ftp", "weight_kg": weight_kg})
        send_message(token, chat_id,
            f"✅ Weight set to *{weight_kg} kg*\n\n"
            "*What is your FTP (Functional Threshold Power)?*\n\n"
            "This is the max power you can hold for ~1 hour.\n"
            "• Beginner: 100–180 W\n"
            "• Recreational: 180–250 W\n"
            "• Advanced: 250 W+\n\n"
            "Send your FTP in watts, or *0* if unknown (I'll use 200 W)."
        )
        return

    if step == "ftp":
        try:
            ftp = int(text)
            if not 0 <= ftp <= 600:
                raise ValueError
        except ValueError:
            send_message(token, chat_id, "❌ Please send a number between 0 and 600.")
            return
        if ftp == 0:
            ftp = 200

        name      = state.get("name", chat_id)
        weight_kg = state.get("weight_kg", 75)

        nonce = _secrets.token_urlsafe(16)
        save_onboard_state(udir, {"step": "awaiting_oauth", "name": name, "weight_kg": weight_kg, "ftp": ftp, "nonce": nonce})

        # Also write nonce → chat_id mapping for the OAuth callback
        # Must be under CONFIG_DIR so it's on the shared volume with the web container.
        nonce_dir = CONFIG_DIR / "nonces"
        nonce_dir.mkdir(parents=True, exist_ok=True)
        (nonce_dir / f"{nonce}.json").write_text(json.dumps({
            "chat_id":   chat_id,
            "name":      name,
            "weight_kg": weight_kg,
            "ftp":       ftp,
        }))

        auth_url = _build_strava_auth_url(nonce)
        send_message(token, chat_id,
            f"✅ FTP set to *{ftp} W*\n\n"
            "Now connect your Strava account:\n\n"
            f"👉 [Authorize Strava]({auth_url})\n\n"
            "_After you authorize, your coaching bot will start automatically._"
        )

    elif step == "awaiting_oauth":
        send_message(token, chat_id,
            "⏳ *Waiting for your Strava authorization...*\n\n"
            "Please click the Strava link I sent you.\n\n"
            "Send /start to get a fresh link."
        )

# ── Logging with rotation ─────────────────────────────────────────────────────
# Rotates bot.log at 1 MB, keeps 3 backups: bot.log, bot.log.1, bot.log.2, bot.log.3
# Total max disk usage: ~4 MB regardless of how long the bot runs.
# Logs go to both the file AND stdout (so docker logs still works).

def _setup_logging():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter(
        fmt="[%(asctime)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Rotating file handler — 1 MB max, 3 backups
    fh = logging.handlers.RotatingFileHandler(
        LOG_FILE,
        maxBytes=1 * 1024 * 1024,   # 1 MB
        backupCount=3,
        encoding="utf-8",
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # Stream handler — keeps docker logs / terminal output working
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root.addHandler(sh)

_setup_logging()
log = logging.getLogger(__name__)

# ── Per-user rate limiting ────────────────────────────────────────────────────
# Tracks last-used timestamp per (chat_id, command) in memory.
# No external dependencies — resets when the process restarts (fine for --once loop).
#
# RATE LIMITS per command group:
#   expensive  — calls Strava API + Claude AI  → max 1 per 30s
#   moderate   — calls Strava API only         → max 1 per 15s
#   cheap      — local only, no external calls → max 1 per 3s
#   free       — always allowed (help, coach)
#
# Why this matters: one user spamming /ride every second triggers a Strava
# API call AND a Claude API call on every cycle, draining your quota fast.

import collections

_rate_limit_store: dict = collections.defaultdict(dict)
# { chat_id: { cmd_group: last_used_timestamp } }

# Rate limit groups based on actual API usage:
#
#   ai_and_strava — calls BOTH Anthropic API + Strava API  → 60s cooldown
#                   /trends
#
#   ai_only       — calls Anthropic API only               → 30s cooldown
#                   plain-text chat messages
#
#   strava_only   — calls Strava API only, no Claude cost  → 15s cooldown
#                   /ride, /stats, /voice, /fullplan
#
#   local_only    — no external API calls, just reads files → 5s cooldown
#                   /plan, /planxco, /newplan, /week, /nextweek, /nextmonth
#
#   free          — always instant, zero cost              → 0s
#                   /help, /coach, /deleteplan

RATE_LIMITS = {
    "ai_and_strava": 60,   # Anthropic + Strava — most expensive
    "ai_only":       30,   # Anthropic only — costs money
    "strava_only":   15,   # Strava only — no Claude cost
    "local_only":     5,   # reads local files only
    "free":           0,   # always allowed
}

CMD_GROUPS = {
    # ai_and_strava: calls both Anthropic AND Strava API
    "trends":    "ai_and_strava",

    # ai_only: calls Anthropic API only (no Strava)
    "_chat":     "ai_only",     # plain-text AI chat messages

    # strava_only: calls Strava API, no Anthropic cost
    "ride":      "strava_only",
    "stats":     "strava_only",
    "stats30":   "strava_only",
    "month":     "strava_only",
    "voice":     "strava_only",
    "fullplan":  "strava_only",
    "allplan":   "strava_only",
    "myplan":    "strava_only",

    # local_only: reads local files only, no external API
    "plan":      "local_only",
    "today":     "local_only",
    "tomorrow":  "local_only",
    "planxco":   "local_only",
    "gym":       "local_only",
    "week":      "local_only",
    "nextweek":  "local_only",
    "nextmonth": "local_only",
    "newplan":   "local_only",

    # free: no API calls, instant always
    "help":      "free",
    "coach":     "free",
    "deleteplan":"free",
    "start":     "free",
    "setup":     "free",
    "quota":     "free",
    "contact":   "free",
    "notify":    "free",
    "leave":     "free",
    "admin":     "free",
}


def check_rate_limit(chat_id: str, cmd: str) -> tuple[bool, int]:
    """Check if this user is allowed to run this command right now.
    Returns (allowed: bool, seconds_remaining: int).
    """
    group = CMD_GROUPS.get(cmd, "ai_and_strava")  # default most restrictive for unknown cmds
    cooldown = RATE_LIMITS[group]
    if cooldown == 0:
        return True, 0

    now = time.time()
    last_used = _rate_limit_store[chat_id].get(group, 0)
    elapsed = now - last_used
    remaining = int(cooldown - elapsed)

    if elapsed >= cooldown:
        return True, 0
    return False, remaining


def record_command_use(chat_id: str, cmd: str):
    """Record that this user just used this command."""
    group = CMD_GROUPS.get(cmd, "expensive")
    _rate_limit_store[chat_id][group] = time.time()

# ── Telegram helpers ──────────────────────────────────────────────────────────

def get_token():
    token = os.environ.get("STRAVA_TELEGRAM_BOT_TOKEN", "")
    if not token and CONFIG_FILE.exists():
        cfg = json.loads(CONFIG_FILE.read_text())
        token = cfg.get("telegram_bot_token", "")
    if not token:
        raise RuntimeError(
            "No Telegram bot token found. "
            "Set STRAVA_TELEGRAM_BOT_TOKEN or add 'telegram_bot_token' to ~/.config/strava/config.json"
        )
    return token


def get_chat_id():
    chat_id = os.environ.get("STRAVA_TELEGRAM_CHAT_ID", "")
    if not chat_id and CONFIG_FILE.exists():
        cfg = json.loads(CONFIG_FILE.read_text())
        chat_id = str(cfg.get("telegram_chat_id", ""))
    return chat_id


def tg_api(token, method, params=None):
    url  = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(params or {}).encode() if params else None
    req  = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    return json.loads(urlopen_with_retry(req, timeout=30))


def tg_api_json(token, method, payload):
    """POST JSON body to Telegram API."""
    url  = f"https://api.telegram.org/bot{token}/{method}"
    data = json.dumps(payload).encode()
    req  = urllib.request.Request(url, data=data,
                                   headers={"Content-Type": "application/json"},
                                   method="POST")
    return json.loads(urlopen_with_retry(req, timeout=30))


def send_typing(token, chat_id):
    """Show 'typing...' indicator in Telegram."""
    try:
        tg_api(token, "sendChatAction", {"chat_id": chat_id, "action": "typing"})
    except Exception:
        pass


def send_error_alert(error_type: str, detail: str, consecutive: int = 1):
    """Send an error alert to the user via Telegram.
    Only alerts on the 1st occurrence and every 10th after that,
    to avoid spamming the user during prolonged outages.
    """
    # Only alert on 1st, 10th, 20th, ... consecutive error
    if consecutive != 1 and consecutive % 10 != 0:
        return
    try:
        token   = get_token()
        chat_id = get_chat_id()
        if not chat_id:
            return
        ts  = datetime.now().strftime("%H:%M:%S")
        msg = (
            f"\u26a0\ufe0f *Bot Error Alert*\n"
            f"\n"
            f"*Type:* {error_type}\n"
            f"*Detail:* `{str(detail)[:200]}`\n"
            f"*Time:* {ts}\n"
            f"*Consecutive errors:* {consecutive}\n"
            f"\n"
            f"_The bot will keep retrying automatically._"
        )
        send_message(token, chat_id, msg)
    except Exception:
        # Never let the alert itself crash the bot
        pass


def send_message(token, chat_id, text):
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    for chunk in chunks:
        tg_api(token, "sendMessage", {
            "chat_id":    chat_id,
            "text":       chunk,
            "parse_mode": "Markdown",
        })


def send_message_with_voice_btn(token, chat_id, text, voice_text):
    """Send message with a 🔊 Hear coach button that triggers voice on tap."""
    # Save the voice text so callback can retrieve it
    vf = _UDIR / "pending_voice.txt"
    _UDIR.mkdir(parents=True, exist_ok=True)
    vf.write_text(voice_text)

    payload = {
        "chat_id":    chat_id,
        "text":       text[:4000],
        "parse_mode": "Markdown",
        "reply_markup": {
            "inline_keyboard": [[
                {"text": "🔊 Hear coach", "callback_data": "voice"}
            ]]
        }
    }
    tg_api_json(token, "sendMessage", payload)


def extract_coaching_note(text):
    """Extract just the coach's spoken line from a formatted message."""
    import re
    # Strip markdown bold/italic markers
    clean = re.sub(r'[*_`]', '', text)
    # Try to find lines after "Says" or "—" (coach signature lines)
    lines = [l.strip() for l in clean.split('\n') if l.strip()]
    # Find coaching note — lines after "Says" label or after em-dash signature
    for i, line in enumerate(lines):
        if 'Says' in line or ('—' in line and i < len(lines) - 1):
            rest = ' '.join(lines[i+1:])
            if rest:
                return rest[:500]
    # Fallback: last non-empty paragraph
    paras = [p.strip() for p in clean.split('\n\n') if p.strip()]
    return paras[-1][:500] if paras else clean[:300]


def _admin_user_picker(action: str) -> list:
    """Return inline keyboard rows listing all users for a given action (pick_quota / pick_delete)."""
    users_dir = CONFIG_DIR / "users"
    rows = []
    if not users_dir.exists():
        return rows
    for udir in sorted(users_dir.iterdir()):
        if not udir.is_dir():
            continue
        uid = udir.name
        name = uid
        try:
            t = json.loads((udir / "tokens.json").read_text())
            a = t.get("athlete", {})
            sn = f"{a.get('firstname','')} {a.get('lastname','')}".strip()
            if sn:
                name = sn
        except Exception:
            try:
                name = json.loads((udir / "config.json").read_text()).get("name", uid)
            except Exception:
                pass
        rows.append([{"text": name, "callback_data": f"{action}_{uid}"}])
    return rows


def handle_callback(token, callback_query):
    """Handle inline button presses."""
    global _UDIR
    chat_id  = str(callback_query.get("message", {}).get("chat", {}).get("id", ""))
    data     = callback_query.get("data", "")
    query_id = callback_query.get("id", "")

    # Acknowledge the button press
    tg_api_json(token, "answerCallbackQuery", {"callback_query_id": query_id})

    if data in ("newplan_replace_yes", "newplan_replace_no"):
        if data == "newplan_replace_no":
            send_message(token, chat_id, "👍 Your current plan is kept. Use /week to view it.")
            return
        udir = get_user_dir(chat_id)
        _archive_plan(udir)
        (udir / "plan_wizard_state.json").unlink(missing_ok=True)
        _prev = _UDIR; _UDIR = udir
        try:
            persona = load_active_persona(udir / "config.json")
            cmd_newplan(persona, token=token, chat_id=chat_id)
        finally:
            _UDIR = _prev
        return

    if data in ("deleteplan_confirm", "deleteplan_cancel"):
        udir = get_user_dir(chat_id)
        df = udir / "pending_delete.txt"
        df.unlink(missing_ok=True)
        if data == "deleteplan_cancel":
            send_message(token, chat_id, "👍 Cancelled. Your plan is safe.")
            return
        _archive_plan(udir)
        wf = udir / "plan_wizard_state.json"
        wf.unlink(missing_ok=True)
        send_message(token, chat_id, "🗑️ Training plan archived.\n\nUse /newplan to create a new one.")
        return

    if data.startswith("wizard_"):
        udir = get_user_dir(chat_id)
        # Map callback data to equivalent text input
        mapping = {
            "wizard_goal_1": "1", "wizard_goal_2": "2", "wizard_goal_3": "3",
            "wizard_goal_4": "4", "wizard_goal_5": "5",
            "wizard_xco_yes": "y", "wizard_xco_no": "n",
            "wizard_plan_classic": "classic", "wizard_plan_ai": "ai",
            "wizard_confirm_yes": "yes", "wizard_confirm_no": "no",
            "wizard_ftp_confirm_yes": "yes", "wizard_ftp_confirm_no": "no",
            "wizard_target_ftp_confirm_yes": "yes", "wizard_target_ftp_confirm_no": "no",
        }
        if data.startswith("wizard_weeks_"):
            equivalent = data[len("wizard_weeks_"):]
        else:
            equivalent = mapping.get(data)
        if not equivalent:
            return
        with _wizard_lock(udir):
            # Temporarily set _UDIR for wizard helpers that rely on it
            _prev_udir = _UDIR
            _UDIR = udir
            try:
                wizard = load_wizard()
                if not wizard:
                    send_message(token, chat_id, "No active wizard. Use /newplan to start.")
                    return
                persona = load_active_persona(udir / "config.json")
                reply, done = handle_wizard(wizard, equivalent, persona)
                if done:
                    clear_wizard()
                    if reply:
                        send_message(token, chat_id, reply)
                else:
                    current_state = load_wizard()
                    _wizard_send(token, chat_id, reply, current_state)
            finally:
                _UDIR = _prev_udir
        return

    if data.startswith("coach_"):
        new_id = data[len("coach_"):]
        udir = get_user_dir(chat_id)
        if new_id not in PERSONAS:
            send_message(token, chat_id, "Unknown coach.")
            return
        save_active_persona(new_id, udir / "config.json")
        p = PERSONAS[new_id]
        send_message(token, chat_id, f"✅ *Coach switched to {p['name']}*\n\n{p['greeting']}")
        return

    if data in ("notify_on", "notify_off"):
        udir = get_user_dir(chat_id)
        reply = cmd_notify(udir, [data[len("notify_"):]])
        if reply:
            send_message(token, chat_id, reply)
        return

    if data in ("admin_pick_quota", "admin_pick_delete"):
        if not _is_admin(chat_id):
            return
        action = "quota_pick" if data == "admin_pick_quota" else "delete_pick"
        label  = "Set quota for:" if data == "admin_pick_quota" else "Delete user:"
        rows   = _admin_user_picker(action)
        if not rows:
            send_message(token, chat_id, "No users found.")
            return
        tg_api_json(token, "sendMessage", {
            "chat_id":    chat_id,
            "text":       label,
            "parse_mode": "Markdown",
            "reply_markup": {"inline_keyboard": rows},
        })
        return

    if data.startswith("delete_pick_"):
        if not _is_admin(chat_id):
            return
        target_id  = data[len("delete_pick_"):]
        target_dir = CONFIG_DIR / "users" / target_id
        target_name = target_id
        try:
            t = json.loads((target_dir / "tokens.json").read_text())
            a = t.get("athlete", {})
            sn = f"{a.get('firstname','')} {a.get('lastname','')}".strip()
            if sn:
                target_name = sn
        except Exception:
            pass
        confirm_file = CONFIG_DIR / f"_delete_confirm_{chat_id}.json"
        confirm_file.write_text(json.dumps({"target_id": target_id, "target_name": target_name}))
        tg_api_json(token, "sendMessage", {
            "chat_id":    chat_id,
            "text":       f"⚠️ Are you sure you want to delete *{target_name}* (`{target_id}`)?",
            "parse_mode": "Markdown",
            "reply_markup": {"inline_keyboard": [[
                {"text": "✅ Yes, delete", "callback_data": f"admin_delete_yes_{target_id}"},
                {"text": "❌ No, cancel",  "callback_data": "admin_delete_no"},
            ]]},
        })
        return

    if data.startswith("quota_pick_"):
        if not _is_admin(chat_id):
            return
        target_id  = data[len("quota_pick_"):]
        target_dir = CONFIG_DIR / "users" / target_id
        target_name = target_id
        try:
            t = json.loads((target_dir / "tokens.json").read_text())
            a = t.get("athlete", {})
            sn = f"{a.get('firstname','')} {a.get('lastname','')}".strip()
            if sn:
                target_name = sn
        except Exception:
            pass
        q        = get_demo_quota(target_dir)
        current  = q.get("allowance_usd")
        cur_str  = "unlimited" if current is None else f"${current:.2f}"
        # Store pending quota target so next text message sets the amount
        (CONFIG_DIR / f"_quota_pending_{chat_id}.json").write_text(
            json.dumps({"target_id": target_id, "target_name": target_name})
        )
        send_message(token, chat_id,
            f"💰 Set quota for *{target_name}* (current: {cur_str})\n\n"
            f"Reply with the amount in USD (e.g. `2.50`), or `off` for unlimited."
        )
        return

    if data in ("admin_stats", "admin_users", "admin_quotas", "admin_list", "admin_web"):
        if not _is_admin(chat_id):
            send_message(token, chat_id, "⛔ Admin only.")
            return
        sub = data[len("admin_"):]
        if sub == "web":
            web_url = os.environ.get("WEB_URL", "")
            send_message(token, chat_id, f"🌐 [Open web panel]({web_url})" if web_url else "WEB_URL not configured.")
            return
        reply = cmd_admin(chat_id, [sub])
        if reply:
            send_message(token, chat_id, reply)
        return

    if data.startswith("admin_delete_yes_") or data == "admin_delete_no":
        confirm_file = CONFIG_DIR / f"_delete_confirm_{chat_id}.json"
        confirm_file.unlink(missing_ok=True)
        if data == "admin_delete_no":
            send_message(token, chat_id, "👍 Deletion cancelled.")
            return
        target_id = data[len("admin_delete_yes_"):]
        target_dir = CONFIG_DIR / "users" / target_id
        # Resolve name
        target_name = target_id
        try:
            t = json.loads((target_dir / "tokens.json").read_text())
            a = t.get("athlete", {})
            sn = f"{a.get('firstname','')} {a.get('lastname','')}".strip()
            if sn:
                target_name = sn
        except Exception:
            pass
        # Notify user
        try:
            send_message(token, target_id,
                "⛔ *Your account has been removed.*\n\n"
                "Your data has been deleted by the admin.\n"
                "Contact [@SuperMariooo](https://t.me/SuperMariooo) for more info."
            )
        except Exception:
            pass
        import shutil
        shutil.rmtree(target_dir, ignore_errors=True)
        send_message(token, chat_id, f"🗑️ *{target_name}* (`{target_id}`) has been deleted.")
        return

    if data == "voice":
        udir = get_user_dir(chat_id)
        persona = load_active_persona(udir / "config.json")
        vf = udir / "pending_voice.txt"
        if vf.exists():
            voice_text = vf.read_text().strip()
        else:
            quotes = {
                "nino":    "Every race is like training and preparation. Sleep well, eat well.",
                "pogi":    "Keep having fun. That is the most important thing.",
                "badger":  "As long as you breathe, attack.",
                "cannibal":"Ride as much or as little as you feel. But ride.",
            }
            voice_text = quotes.get(persona["id"], "Get on the bike.")

        ok, result = send_voice(token, chat_id, voice_text, persona["id"])
        if not ok:
            send_message(token, chat_id, f"⚠️ Could not generate voice: {result}")


def load_offset():
    if OFFSET_FILE.exists():
        try:
            return int(OFFSET_FILE.read_text().strip())
        except ValueError:
            pass
    return 0


def save_offset(offset):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    OFFSET_FILE.write_text(str(offset))


def get_updates(token, offset=0, timeout=0):
    params = {"offset": offset, "timeout": timeout,
              "allowed_updates": '["message","callback_query"]'}
    result = tg_api(token, "getUpdates", params)
    return result.get("result", [])

# ── Command handlers ──────────────────────────────────────────────────────────

def cmd_help(persona):
    p = persona
    return (
        f"*{p['name']} Coaching Bot* 🚴\n\n"
        f"Commands:\n"
        f"  /coach — show current coach\n"
        f"  /coach `nino|pogi|badger|cannibal` — switch coach\n"
        f"  /ride — analyze your latest ride\n"
        f"  /voice — hear your coach speak 🔊\n"
        f"  /newplan — create a new training plan 🗓\n"
        f"  /deleteplan — delete current training plan 🗑\n"
        f"  /today — today's planned workout\n"
        f"  /tomorrow — tomorrow's planned workout\n"
        f"  /gym — today's XCO strength session 💪\n"
        f"  /week — this week's training plan\n"
        f"  /nextweek — next week's plan\n"
        f"  /nextmonth — next 4 weeks\n"
        f"  /fullplan — entire training plan\n"
        f"  /stats — last 7 days summary\n"
        f"  /stats 30 — last 30 days summary (or /stats30)\n"
        f"  /trends — week-by-week trend analysis (30 days)\n"
        f"  /trends 90 — trends for last N days\n"
        f"  /quota — check your AI usage & limit\n"
        f"  /contact — get in touch with support\n"
        f"  /help — this message"
    )


def cmd_coach(args, persona, token: str = "", chat_id: str = "") -> str:
    """Show current coach or switch to a new one."""
    if not args:
        if token and chat_id:
            buttons = []
            for pid, p in PERSONAS.items():
                label = f"✅ {p['name']}" if pid == persona["id"] else p["name"]
                buttons.append([{"text": label, "callback_data": f"coach_{pid}"}])
            tg_api_json(token, "sendMessage", {
                "chat_id":    chat_id,
                "text":       f"*Current coach:* {persona['name']}\n\nPick a coach:",
                "parse_mode": "Markdown",
                "reply_markup": {"inline_keyboard": buttons},
            })
            return None
        lines = [f"*Current coach:* {persona['name']}\n\n*Available coaches:*"]
        for pid, p in PERSONAS.items():
            marker = " ✅" if pid == persona["id"] else ""
            lines.append(f"  `{pid}` — {p['name']}{marker}\n  _{p['tagline']}_")
        return "\n".join(lines)

    new_id = args[0].lower()
    if new_id not in PERSONAS:
        return f"Unknown coach `{new_id}`. Options: `nino` | `pogi` | `badger` | `cannibal`"

    save_active_persona(new_id, _UDIR / "config.json")
    p = PERSONAS[new_id]
    return (
        f"✅ *Coach switched to {p['name']}*\n\n"
        f"{p['greeting']}"
    )


def cmd_ride(persona):
    """Analyze the latest Strava ride."""
    config = load_config(_UDIR)
    ftp    = config.get("ftp", 220)

    activities = get_activities(days=30, limit=10, activity_type=None, user_dir=_UDIR)
    if not activities:
        return "No rides found in the last 30 days. Get out there! 🚴"
    activities.sort(key=lambda a: a.get("start_date", ""), reverse=True)

    a    = activities[0]
    name = a.get("name", "Untitled")
    date = a.get("start_date_local", "")[:10]
    dist = meters_to_km(a.get("distance", 0))
    dur  = seconds_to_hm(a.get("moving_time", 0))
    elev = int(a.get("total_elevation_gain", 0))
    spd  = round(a.get("average_speed", 0) * 3.6, 1)
    pwr  = a.get("average_watts")
    hr   = a.get("average_heartrate")
    cad  = a.get("average_cadence")
    tss  = estimate_tss(a, ftp)

    lines = [f"🚴 *{name}*", f"_{date}_\n"]
    lines.append(f"📍 {dist} km  |  {dur}  |  ↑{elev}m  |  {spd} km/h")
    if pwr:
        lines.append(f"⚡ {int(pwr)}W avg  |  TSS ~{tss}")
    if hr:
        lines.append(f"❤️  {int(hr)} bpm avg")
    if cad:
        lines.append(f"🔄 {int(cad)} rpm avg cadence")

    # Persona coaching note
    zf = persona["zone_feedback"]
    if_ = None
    if pwr and ftp:
        if_ = (pwr * 1.05) / ftp

    lines.append(f"\n{persona['coach_label']}")
    if if_ is not None:
        if   if_ < 0.65: note = pick_feedback(zf, "z1")
        elif if_ < 0.80: note = pick_feedback(zf, "z2")
        elif if_ < 0.95: note = pick_feedback(zf, "z3")
        elif if_ < 1.05: note = pick_feedback(zf, "z4")
        else:             note = pick_feedback(zf, "z5")
        lines.append(f"_{note}_")
    else:
        note = pick_feedback(zf, "no_ftp")
        lines.append(f"_{note}_")

    return "\n".join(lines), note


def cmd_plan_xco(persona):
    """Show today's XCO power session from the saved plan."""
    plan_file = _UDIR / "training_plan.json"
    if not plan_file.exists():
        return (
            f"💪 *No training plan active yet.*\n\n"
            f"Use /newplan to build one. When asked about XCO power training, answer *yes*.\n\n"
            f"— {persona['name']}"
        )

    plan = load_plan_safe()

    if not plan.get("xco_power"):
        return (
            f"💪 *Your current plan doesn't include XCO power training.*\n\n"
            f"Use /newplan to create a new plan and answer *yes* when asked about XCO power training.\n\n"
            f"— {persona['name']}"
        )

    today = datetime.today().strftime("%Y-%m-%d")
    for week in plan.get("weekly_plans", []):
        for day in week.get("days", []):
            if day.get("date") == today and day.get("type") == "gym":
                desc = day['description']
                text = (
                    f"💪 *XCO Power Session — Today* ({today})\n\n"
                    f"*{day['name']}*\n\n"
                    f"{desc}\n\n"
                    f"— {persona['name']}"
                )
                voice = desc.split('\n')[0]
                return text, voice

    # No gym today — find the next gym session
    next_gym = None
    for week in plan.get("weekly_plans", []):
        for day in week.get("days", []):
            if day.get("date", "") > today and day.get("type") == "gym":
                next_gym = day
                break
        if next_gym:
            break

    if next_gym:
        return (
            f"😴 *No gym session today* ({today})\n\n"
            f"Next gym session: *{next_gym['date']}* — {next_gym['name']}\n\n"
            f"— {persona['name']}"
        ), None

    return (
        f"😴 *No gym session today* ({today})\n\n"
        f"No upcoming gym sessions found in your plan.\n\n"
        f"— {persona['name']}"
    ), None


def _format_day_workout(day, label, persona):
    """Format a single day's workout into a reply string. Returns (text, voice_text)."""
    w     = day["name"]
    d     = day["description"]
    t     = day["tss"]
    dtype = day.get("type", "")
    zone  = day.get("zone", 0)
    if dtype == "gym":
        z = "💪 Gym"; emoji = "🏋️"
    elif zone and int(zone) > 0:
        z = f"Zone {zone}"; emoji = "🚴"
    elif day.get("workout") == "rest":
        z = "Rest"; emoji = "😴"
    else:
        z = "Ride"; emoji = "🚴"
    text = (
        f"📋 *{label}* ({day['date']})\n\n"
        f"{emoji} *{w}* — {z}\n"
        f"Duration: {day.get('duration_min', '?')} min  |  TSS: {t}\n\n"
        f"_{d}_\n\n"
        f"— {persona['name']}"
    )
    return text, d


def cmd_today(persona):
    """Show today's planned workout from the saved training plan."""
    plan_file = _UDIR / "training_plan.json"
    if not plan_file.exists():
        return (
            f"📋 *No training plan active yet.*\n\n"
            f"Use /newplan to build one — I'll guide you step by step.\n\n"
            f"— {persona['name']}"
        ), None

    plan  = load_plan_safe()
    today = datetime.today().strftime("%Y-%m-%d")

    for week in plan.get("weekly_plans", []):
        for day in week.get("days", []):
            if day.get("date") == today:
                return _format_day_workout(day, "Today's Workout", persona)

    return f"No workout scheduled for today ({today}) in your current plan.", None


def cmd_tomorrow(persona):
    """Show tomorrow's planned workout from the saved training plan."""
    plan_file = _UDIR / "training_plan.json"
    if not plan_file.exists():
        return (
            f"📋 *No training plan active yet.*\n\n"
            f"Use /newplan to build one — I'll guide you step by step.\n\n"
            f"— {persona['name']}"
        ), None

    plan     = load_plan_safe()
    tomorrow = (datetime.today() + timedelta(days=1)).strftime("%Y-%m-%d")

    for week in plan.get("weekly_plans", []):
        for day in week.get("days", []):
            if day.get("date") == tomorrow:
                return _format_day_workout(day, "Tomorrow's Workout", persona)

    return f"No workout scheduled for tomorrow ({tomorrow}) in your current plan.", None


def cmd_week(persona):
    """Show this week's training plan."""
    plan_file = _UDIR / "training_plan.json"
    if not plan_file.exists():
        return (
            f"📅 *No training plan active yet.*\n\n"
            f"Use /newplan to build one — I'll guide you step by step.\n\n"
            f"— {persona['name']}"
        )

    plan  = load_plan_safe()
    today = datetime.today().strftime("%Y-%m-%d")

    for week in plan.get("weekly_plans", []):
        days = week.get("days", [])
        dates = [d["date"] for d in days]
        if not dates:
            continue
        if dates[0] <= today <= dates[-1]:
            lines = [
                f"📅 *Week {week['week']} — {week['phase'].upper()}*",
                f"TSS target: {week['total_tss']}\n"
            ]
            for day in days:
                marker = " ← today" if day["date"] == today else ""
                if day["workout"] == "rest":
                    lines.append(f"  {day['day'][:3]}: 😴 REST{marker}")
                elif day.get("type") == "gym":
                    lines.append(f"  {day['day'][:3]}: 🏋️ *{day['name']}* (TSS {day['tss']}){marker}")
                else:
                    lines.append(f"  {day['day'][:3]}: 🚴 *{day['name']}* (TSS {day['tss']}){marker}")
            lines.append(f"\n_{persona['header_quote']}_")
            return "\n".join(lines)

    # Check if plan hasn't started yet
    first_week = plan.get("weekly_plans", [{}])[0]
    first_date = (first_week.get("days") or [{}])[0].get("date", "")
    if first_date and today < first_date:
        return (
            f"📅 *Your plan starts on {first_date}.*\n\n"
            f"Nothing to show yet — come back when the plan begins!\n\n"
            f"— {persona['name']}"
        )
    return f"📅 *Your plan has ended.*\n\nUse /newplan to create a new one.\n\n— {persona['name']}"


def send_voice(token, chat_id, text, persona_id="nino"):
    """Generate speech with Piper TTS and send as Telegram voice message."""
    import subprocess
    import os

    model = os.path.expanduser("~/.local/share/piper/en_US-ryan-medium.onnx")
    wav_file = "/tmp/coach_voice.wav"

    # Generate WAV with Piper
    proc = subprocess.run(
        ["piper", "--model", model, "--output_file", wav_file],
        input=text.encode(),
        capture_output=True
    )
    if proc.returncode != 0 or not os.path.exists(wav_file):
        # Fallback to espeak-ng if piper fails
        subprocess.run(["espeak-ng", text, "-w", wav_file], capture_output=True)

    if not os.path.exists(wav_file):
        return False, "TTS generation failed"

    # Send to Telegram
    with open(wav_file, "rb") as f:
        file_data = f.read()
        boundary = "----TelegramBoundary"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="chat_id"\r\n\r\n'
            f"{chat_id}\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="audio"; filename="coach.wav"\r\n'
            f"Content-Type: audio/wav\r\n\r\n"
        ).encode() + file_data + f"\r\n--{boundary}--\r\n".encode()

        import urllib.request
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendAudio",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST"
        )
        result = json.loads(urlopen_with_retry(req, timeout=30))
        return result.get("ok", False), result


def cmd_voice(persona, chat_id, token):
    """Speak only the coaching note as a Telegram voice message."""
    config = load_config(_UDIR)
    ftp    = config.get("ftp", 220)

    try:
        activities = get_activities(days=30, limit=10, user_dir=_UDIR)
        activities.sort(key=lambda a: a.get("start_date", ""), reverse=True)
    except Exception:
        activities = []

    if activities:
        a   = activities[0]
        pwr = a.get("average_watts")
        if_ = (pwr * 1.05) / ftp if pwr and ftp else None
        zf  = persona["zone_feedback"]
        if if_ is not None:
            if   if_ < 0.65: text = pick_feedback(zf, "z1")
            elif if_ < 0.80: text = pick_feedback(zf, "z2")
            elif if_ < 0.95: text = pick_feedback(zf, "z3")
            elif if_ < 1.05: text = pick_feedback(zf, "z4")
            else:             text = pick_feedback(zf, "z5")
        else:
            text = pick_feedback(zf, "no_ftp")
    else:
        quotes = {
            "nino":    "Every race is like training and preparation. Sleep well, eat well. Stay consistent.",
            "pogi":    "Keep having fun. That is the most important thing. Get out and ride today.",
            "badger":  "As long as you breathe, attack. Get on the bike. No excuses.",
            "cannibal":"Ride as much or as little as you feel. But ride.",
        }
        text = quotes.get(persona["id"], "Get on the bike. Every day counts.")

    ok, result = send_voice(token, chat_id, text, persona["id"])
    if ok:
        return None
    else:
        return f"⚠️ Could not generate voice: {result}"


def cmd_stats(persona, days=7):
    """Training summary for last N days (default 7)."""
    config = load_config(_UDIR)
    ftp    = config.get("ftp", 220)

    activities = get_activities(days=days, limit=60, user_dir=_UDIR)
    if not activities:
        return f"No rides in the last {days} days. Time to get on the bike! 🚴"

    total_dist = sum(a.get("distance", 0) for a in activities)
    total_time = sum(a.get("moving_time", 0) for a in activities)
    total_elev = sum(a.get("total_elevation_gain", 0) for a in activities)
    total_tss  = sum(estimate_tss(a, ftp) for a in activities)
    pwr_list   = [a["average_watts"] for a in activities if a.get("average_watts")]

    lines = [
        f"📊 *Last {days} Days* — {len(activities)} rides\n",
        f"🚴 {meters_to_km(total_dist)} km  |  {seconds_to_hm(total_time)}  |  ↑{int(total_elev)}m",
        f"💥 Total TSS: {total_tss}  (avg {int(total_tss/days)}/day)",
    ]
    if pwr_list:
        lines.append(f"⚡ Avg power: {int(sum(pwr_list)/len(pwr_list))}W")

    lines.append(f"\n_{persona['coach_label'].replace('💬 ','')}: Keep building._")
    return "\n".join(lines)


def cmd_trends(persona, days=30):
    """Week-by-week trend analysis — mirrors analyze_rides.py for the bot."""
    config = load_config(_UDIR)
    ftp    = config.get("ftp", 220)

    activities = get_activities(days=days, limit=60, user_dir=_UDIR)
    if not activities:
        return f"📊 No rides in the last {days} days."

    total_dist = sum(a.get("distance", 0) for a in activities)
    total_time = sum(a.get("moving_time", 0) for a in activities)
    total_elev = sum(a.get("total_elevation_gain", 0) for a in activities)
    total_tss  = sum(estimate_tss(a, ftp) for a in activities)
    pwr_list   = [a["average_watts"] for a in activities if a.get("average_watts")]
    hr_list    = [a["average_heartrate"] for a in activities if a.get("average_heartrate")]

    lines = [
        f"📈 *Trend Analysis — Last {days} Days* ({len(activities)} rides)\n",
        f"🚴 {meters_to_km(total_dist)} km  |  {seconds_to_hm(total_time)}  |  ↑{int(total_elev)}m",
        f"💥 Total TSS: {total_tss}  (avg {int(total_tss / (days / 7))}/week)",
    ]
    if pwr_list:
        lines.append(f"⚡ Avg power: {int(sum(pwr_list)/len(pwr_list))}W  |  Best: {int(max(pwr_list))}W")
    if hr_list:
        lines.append(f"❤️  Avg HR: {int(sum(hr_list)/len(hr_list))} bpm")

    # Week-by-week breakdown
    weeks = {}
    for a in activities:
        date_str = a.get("start_date_local", "")[:10]
        if not date_str:
            continue
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        wk = dt.strftime("%Y-W%W")
        if wk not in weeks:
            weeks[wk] = {"rides": 0, "dist": 0, "tss": 0, "time": 0}
        weeks[wk]["rides"] += 1
        weeks[wk]["dist"]  += a.get("distance", 0)
        weeks[wk]["tss"]   += estimate_tss(a, ftp)
        weeks[wk]["time"]  += a.get("moving_time", 0)

    lines.append("\n*Week by week:*")
    for wk, d in sorted(weeks.items())[-8:]:
        lines.append(
            f"  `{wk}` {d['rides']} rides  "
            f"{meters_to_km(d['dist'])}km  "
            f"{seconds_to_hm(d['time'])}  "
            f"TSS {d['tss']}"
        )

    lines.append(f"\n_{persona['coach_label'].replace('💬 ','')}: The trend tells the story._")
    return "\n".join(lines)
    """Answer a plain text question in the coach's voice using Claude API."""
    import json as _json

    _zf = persona.get("zone_feedback", {})
    _voice_samples = []
    for _v in list(_zf.values())[:3]:
        if isinstance(_v, list):
            _voice_samples.append(_v[0])
        elif isinstance(_v, str) and _v != _zf.get("no_ftp", ""):
            _voice_samples.append(_v)
    _voice_hint = " | ".join(_voice_samples[:2]) if _voice_samples else persona.get("header_quote", "")

    system = (
        f"You are {persona['name']}, a cycling coach. {persona['tagline']}\n"
        f"Speak in first person, in your authentic voice — exactly like these examples: {_voice_hint}\n\n"
        f"Answer the athlete's question in character. Be direct, specific, and brief. "
        f"Max 3-4 sentences. No bullet points. Sound like a real coach talking to an athlete."
    )

    try:
        # SECURITY: API key read from env var (injected by Docker -e flag at runtime).
        # It is never stored in config.json on disk, so customers cannot access it.
        config = load_config(_UDIR)
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            auth_file = Path.home() / ".openclaw/agents/main/agent/auth-profiles.json"
            if auth_file.exists():
                auth = _json.loads(auth_file.read_text())
                for v in auth.values():
                    if isinstance(v, dict) and v.get("provider") == "anthropic":
                        api_key = v.get("token", "")
                        break

        if not api_key:
            return f"_{persona['name']}: Ask me anything about training — I'm here. (Set anthropic_api_key in config to enable AI answers.)_"

        payload = _json.dumps({
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 300,
            "system": system,
            "messages": [{"role": "user", "content": question}]
        }).encode()

        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "Content-Type":      "application/json",
                "anthropic-version": "2023-06-01",
                "x-api-key":         api_key,
            },
            method="POST"
        )

        data   = _json.loads(urlopen_with_retry(req, timeout=15))
        usage  = data.get("usage", {})
        record_ai_cost(_UDIR, usage.get("input_tokens", 0), usage.get("output_tokens", 0))
        answer = data["content"][0]["text"]
        return f"_{persona['name']}: {answer}_"

    except Exception as e:
        return f"_{persona['name']}: Focus on the basics — train consistently, recover well, trust the process._"


def _archive_plan(udir: Path):
    """Rename training_plan.json to training_plan_vN.json (next available version)."""
    current = udir / "training_plan.json"
    if not current.exists():
        return
    n = 1
    while (udir / f"training_plan_v{n}.json").exists():
        n += 1
    current.rename(udir / f"training_plan_v{n}.json")


def load_plan_safe():
    """Load training_plan.json safely. Returns {} on missing or corrupted file."""
    plan_file = _UDIR / "training_plan.json"
    if not plan_file.exists():
        return {}
    try:
        return json.loads(plan_file.read_text())
    except Exception as e:
        log.warning(f"training_plan.json corrupted ({e}) — use /deleteplan then /newplan to recover")

@contextmanager
def _wizard_lock(udir):
    """Inter-process exclusive lock for wizard state in a given user directory."""
    udir.mkdir(parents=True, exist_ok=True)
    with open(udir / "wizard.lock", "w") as _lf:
        fcntl.flock(_lf, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(_lf, fcntl.LOCK_UN)


def load_wizard():
    f = _UDIR / "plan_wizard_state.json"
    if f.exists():
        try:
            return json.loads(f.read_text())
        except Exception as e:
            log.warning(f"Wizard state corrupted at {f} ({e}) — resetting")
    return {}

def save_wizard(state):
    _UDIR.mkdir(parents=True, exist_ok=True)
    (_UDIR / "plan_wizard_state.json").write_text(json.dumps(state, indent=2))

def clear_wizard():
    f = _UDIR / "plan_wizard_state.json"
    if f.exists():
        f.unlink()

def _realistic_ftp_gain(ftp: int, weeks: int):
    """Return (lo, hi, level, label_str) for realistic FTP gain."""
    if ftp < 200:
        level, lo_pct, hi_pct = "beginner", 0.05, 0.08
    elif ftp < 280:
        level, lo_pct, hi_pct = "intermediate", 0.02, 0.04
    else:
        level, lo_pct, hi_pct = "advanced", 0.01, 0.02
    scale = weeks / 8.0
    lo = max(1, round(ftp * lo_pct * scale))
    hi = max(2, round(ftp * hi_pct * scale))
    return lo, hi, level, f"+{lo}–{hi}W ({level}, {weeks} weeks)"


def _wizard_send(token, chat_id, reply, state):
    """Send a wizard step reply — buttons for discrete steps, plain text for open inputs."""
    if reply is None:
        return
    step = state.get("step") if isinstance(state, dict) else None
    if isinstance(state, dict) and state.get("ftp_confirm_pending"):
        tg_api_json(token, "sendMessage", {
            "chat_id": chat_id, "text": reply, "parse_mode": "Markdown",
            "reply_markup": {"inline_keyboard": [[
                {"text": "✅ Yes, that's correct", "callback_data": "wizard_ftp_confirm_yes"},
                {"text": "❌ No, re-enter",        "callback_data": "wizard_ftp_confirm_no"},
            ]]},
        })
        return
    if isinstance(state, dict) and state.get("target_ftp_confirm_pending"):
        tg_api_json(token, "sendMessage", {
            "chat_id": chat_id, "text": reply, "parse_mode": "Markdown",
            "reply_markup": {"inline_keyboard": [[
                {"text": "✅ Yes, set it anyway", "callback_data": "wizard_target_ftp_confirm_yes"},
                {"text": "❌ No, re-enter",       "callback_data": "wizard_target_ftp_confirm_no"},
            ]]},
        })
        return
    if step == "goal":
        tg_api_json(token, "sendMessage", {
            "chat_id": chat_id, "text": reply, "parse_mode": "Markdown",
            "reply_markup": {"inline_keyboard": [
                [{"text": "1️⃣ Improve FTP",      "callback_data": "wizard_goal_1"}],
                [{"text": "2️⃣ Event prep",        "callback_data": "wizard_goal_2"}],
                [{"text": "3️⃣ Distance target",   "callback_data": "wizard_goal_3"}],
                [{"text": "4️⃣ Weight loss",       "callback_data": "wizard_goal_4"}],
                [{"text": "5️⃣ General fitness",   "callback_data": "wizard_goal_5"}],
            ]},
        })
    elif step == "weeks":
        tg_api_json(token, "sendMessage", {
            "chat_id": chat_id, "text": reply, "parse_mode": "Markdown",
            "reply_markup": {"inline_keyboard": [
                [{"text": "4 weeks",  "callback_data": "wizard_weeks_4"},
                 {"text": "8 weeks",  "callback_data": "wizard_weeks_8"}],
                [{"text": "12 weeks", "callback_data": "wizard_weeks_12"},
                 {"text": "16 weeks", "callback_data": "wizard_weeks_16"}],
                [{"text": "20 weeks", "callback_data": "wizard_weeks_20"},
                 {"text": "24 weeks", "callback_data": "wizard_weeks_24"}],
            ]},
        })
    elif step == "xco":
        tg_api_json(token, "sendMessage", {
            "chat_id": chat_id, "text": reply, "parse_mode": "Markdown",
            "reply_markup": {"inline_keyboard": [[
                {"text": "✅ Yes", "callback_data": "wizard_xco_yes"},
                {"text": "❌ No",  "callback_data": "wizard_xco_no"},
            ]]},
        })
    elif step == "plan_type":
        tg_api_json(token, "sendMessage", {
            "chat_id": chat_id, "text": reply, "parse_mode": "Markdown",
            "reply_markup": {"inline_keyboard": [[
                {"text": "📋 Classic (free)", "callback_data": "wizard_plan_classic"},
                {"text": "🤖 AI-generated",   "callback_data": "wizard_plan_ai"},
            ]]},
        })
    elif step == "confirm":
        tg_api_json(token, "sendMessage", {
            "chat_id": chat_id, "text": reply, "parse_mode": "Markdown",
            "reply_markup": {"inline_keyboard": [[
                {"text": "✅ Yes, build it!", "callback_data": "wizard_confirm_yes"},
                {"text": "❌ Cancel",         "callback_data": "wizard_confirm_no"},
            ]]},
        })
    else:
        send_message(token, chat_id, reply)


def cmd_newplan(persona, token: str = "", chat_id: str = "") -> str:
    """Start a new plan creation wizard."""
    # Block if user has no quota set or is over limit
    quota_ok, _, allowance = check_demo_quota(_UDIR)
    if allowance is not None and not quota_ok:
        return (
            "🎟 *You are out of demo allowance*\n\n"
            "Contact the admin to upgrade your account and unlock full access.\n"
            "[@SuperMariooo](https://t.me/SuperMariooo)"
        )
    if allowance == 0:
        return (
            "🎟 *No quota assigned yet*\n\n"
            "Contact the admin to activate your account.\n"
            "[@SuperMariooo](https://t.me/SuperMariooo)"
        )

    # If an active plan exists and no override flag, ask for confirmation first
    plan_file = _UDIR / "training_plan.json"
    if plan_file.exists() and token and chat_id:
        plan = load_plan_safe()
        goal  = plan.get("goal", "unknown")
        weeks = plan.get("weeks", "?")
        start = plan.get("start_date", "?")
        event = f" — {plan['event_name']}" if plan.get("event_name") else ""
        tg_api_json(token, "sendMessage", {
            "chat_id": chat_id,
            "text": (
                f"⚠️ *You already have an active training plan.*\n\n"
                f"  🎯 Goal: *{goal}{event}*\n"
                f"  📅 {weeks} weeks, started {start}\n\n"
                f"Creating a new plan will *delete your current one*.\n"
                f"Are you sure?"
            ),
            "parse_mode": "Markdown",
            "reply_markup": {"inline_keyboard": [[
                {"text": "✅ Yes, replace it", "callback_data": "newplan_replace_yes"},
                {"text": "❌ No, keep it",     "callback_data": "newplan_replace_no"},
            ]]},
        })
        return None

    state = {"step": "goal", "persona": persona["id"]}
    save_wizard(state)
    reply = (
        f"🗓 *New Training Plan — {persona['name']}*\n\n"
        f"Let's build your plan step by step.\n\n"
        f"*STEP 1: What is your primary goal?*"
    )
    if token and chat_id:
        _wizard_send(token, chat_id, reply, state)
        return None
    return reply + (
        "\n\n1️⃣ Improve FTP\n2️⃣ Event prep\n3️⃣ Distance target\n"
        "4️⃣ Weight loss\n5️⃣ General fitness\n\nReply with a number *1–5*"
    )

def handle_wizard(state, text, persona):
    """Handle a wizard reply. Returns (reply, done)."""
    step = state.get("step")

    # ── GOAL ──────────────────────────────────────────────────────────────────
    if step == "goal":
        goals = {"1":"ftp","2":"event","3":"distance","4":"weight-loss","5":"general"}
        goal  = goals.get(text.strip())
        if not goal:
            return "Please reply with a number *1–5*", False
        state["goal"] = goal
        state["step"] = "ftp"
        save_wizard(state)
        return (
            f"✅ Goal: *{goal}*\n\n"
            f"*STEP 2: What is your current FTP?*\n\n"
            f"FTP = the max power you can sustain for ~1 hour.\n"
            f"It sets all your training zones.\n\n"
            f"Typical ranges:\n"
            f"• Beginner: 100–180W\n"
            f"• Recreational: 180–250W\n"
            f"• Enthusiast: 250–320W\n"
            f"• Advanced: 320W+\n\n"
            f"Reply with your FTP in watts, or *0* if unknown (we'll use 200W)"
        ), False

    # ── FTP ───────────────────────────────────────────────────────────────────
    elif step == "ftp":
        # Handling confirmation of high FTP
        if state.get("ftp_confirm_pending"):
            if text.strip().lower() in ("y", "yes"):
                ftp = state["ftp_confirm_pending"]
                del state["ftp_confirm_pending"]
                state["ftp"] = ftp
                state["step"] = "weeks"
                save_wizard(state)
                return (
                    f"✅ FTP: *{ftp}W* confirmed.\n\n"
                    f"*STEP 3: How many weeks?*\n\n"
                    f"• 4 weeks — quick fitness boost\n"
                    f"• 8 weeks — standard block _(recommended)_\n"
                    f"• 12 weeks — full periodized build\n"
                    f"• 16 weeks — serious event preparation\n"
                    f"• 20–24 weeks — full season\n\n"
                    f"Structure: 3 build weeks + 1 recovery week, repeating.\n\n"
                    f"Reply with number of weeks *(4–24)*"
                ), False
            else:
                del state["ftp_confirm_pending"]
                save_wizard(state)
                return "No problem — please re-enter your FTP in watts:", False

        try:
            ftp = int(text.strip())
        except ValueError:
            return "Please reply with a number (your FTP in watts, or 0 if unknown)", False
        if ftp == 0:
            ftp = 200

        # Sanity check: above 400W is very unusual — confirm
        if ftp > 400:
            state["ftp_confirm_pending"] = ftp
            save_wizard(state)
            return (
                f"⚠️ *{ftp}W is exceptionally high* — only world-class pros sustain that.\n\n"
                f"Are you sure this is correct?",
                False
            )

        state["ftp"] = ftp
        state["step"] = "weeks"
        save_wizard(state)
        return (
            f"✅ FTP: *{ftp}W*\n\n"
            f"*STEP 3: How many weeks?*\n\n"
            f"• 4 weeks — quick fitness boost\n"
            f"• 8 weeks — standard block _(recommended)_\n"
            f"• 12 weeks — full periodized build\n"
            f"• 16 weeks — serious event preparation\n"
            f"• 20–24 weeks — full season\n\n"
            f"Structure: 3 build weeks + 1 recovery week, repeating.\n\n"
            f"Reply with number of weeks *(4–24)*"
        ), False

    # ── WEEKS ─────────────────────────────────────────────────────────────────
    elif step == "weeks":
        try:
            weeks = int(text.strip())
            if not 2 <= weeks <= 52:
                raise ValueError
        except ValueError:
            return "Please reply with a number between 4 and 24", False
        state["weeks"] = weeks
        goal = state.get("goal")
        save_wizard(state)

        # Step 4: goal-specific question (before XCO)
        if goal == "event":
            state["step"] = "event_name"
            save_wizard(state)
            return (
                f"✅ Duration: *{weeks} weeks*\n\n"
                f"*STEP 4: Event name*\n\n"
                f"What is the name of your target event?\n"
                f"_(e.g. 'XCO Regional Champs', 'Cape Epic', 'Gran Fondo')_"
            ), False
        elif goal == "ftp":
            state["step"] = "target_ftp"
            save_wizard(state)
            ftp = state.get("ftp", 220)
            return (
                f"✅ Duration: *{weeks} weeks*\n\n"
                f"*STEP 4: Target FTP*\n\n"
                f"Current FTP: *{ftp}W*\n"
                f"Realistic gain: {_realistic_ftp_gain(ftp, weeks)[3]}\n\n"
                f"What FTP do you want to reach?\n"
                f"_(reply with target watts, e.g. {ftp+20})_"
            ), False
        elif goal == "distance":
            state["step"] = "target_km"
            save_wizard(state)
            return (
                f"✅ Duration: *{weeks} weeks*\n\n"
                f"*STEP 4: Weekly distance target*\n\n"
                f"• 100 km/week — recreational\n"
                f"• 150 km/week — enthusiast\n"
                f"• 200 km/week — dedicated\n\n"
                f"Reply with your target in km"
            ), False
        elif goal == "weight-loss":
            state["step"] = "target_kg"
            save_wizard(state)
            return (
                f"✅ Duration: *{weeks} weeks*\n\n"
                f"*STEP 4: Target weight*\n\n"
                f"What is your target body weight in kg?\n"
                f"_(reply with number, or 0 to skip)_"
            ), False
        else:
            # General fitness — go straight to XCO
            state["step"] = "xco"
            save_wizard(state)
            return (
                f"✅ Duration: *{weeks} weeks*\n\n"
                f"*STEP 4: Include XCO Power Training?*\n\n"
                f"Adds 2 gym sessions/week specifically for cross-country MTB:\n\n"
                f"💪 *Gym:* Max strength, explosive power, core & coordination\n"
                f"🚴 *Bike:* Torque intervals, sprint power, micro-bursts\n\n"
                f"Recommended if you race XCO or want explosive power."
            ), False

    # ── EVENT NAME ────────────────────────────────────────────────────────────
    elif step == "event_name":
        state["event_name"] = text.strip()
        state["step"] = "event_date"
        save_wizard(state)
        return (
            f"✅ Event: *{state['event_name']}*\n\n"
            f"*When is the event?*\n\n"
            f"Reply with the date in format: *YYYY-MM-DD*\n"
            f"_(e.g. 2026-06-15)_"
        ), False

    # ── EVENT DATE ────────────────────────────────────────────────────────────
    elif step == "event_date":
        try:
            datetime.strptime(text.strip(), "%Y-%m-%d")
        except ValueError:
            return "Please use the format *YYYY-MM-DD* (e.g. 2026-06-15)", False
        state["event_date"] = text.strip()
        state["step"] = "xco"
        save_wizard(state)
        return (
            f"✅ Event date: *{state['event_date']}*\n\n"
            f"*STEP 5: Include XCO Power Training?*\n\n"
            f"Adds 2 gym sessions/week specifically for cross-country MTB:\n\n"
            f"💪 *Gym:* Max strength, explosive power, core & coordination\n"
            f"🚴 *Bike:* Torque intervals, sprint power, micro-bursts\n\n"
            f"Recommended if you race XCO or want explosive power."
        ), False

    # ── TARGET FTP ────────────────────────────────────────────────────────────
    elif step == "target_ftp":
        # Confirm if previously flagged as ambitious
        if state.get("target_ftp_confirm_pending"):
            if text.strip().lower() in ("y", "yes"):
                state["target_ftp"] = state.pop("target_ftp_confirm_pending")
                state["target_ftp_override"] = True
            else:
                del state["target_ftp_confirm_pending"]
                save_wizard(state)
                return "No problem — please re-enter your target FTP in watts:", False
            state["step"] = "xco"
            save_wizard(state)
            return (
                f"✅ Target FTP: *{state['target_ftp']}W* confirmed.\n\n"
                f"*STEP 5: Include XCO Power Training?*\n\n"
                f"Adds 2 gym sessions/week specifically for cross-country MTB:\n\n"
                f"💪 *Gym:* Max strength, explosive power, core & coordination\n"
                f"🚴 *Bike:* Torque intervals, sprint power, micro-bursts\n\n"
                f"Recommended if you race XCO or want explosive power."
            ), False

        try:
            target = int(text.strip())
        except ValueError:
            return "Please reply with a number (target FTP in watts)", False

        current_ftp = state.get("ftp", 220)
        weeks       = state.get("weeks", 8)
        _, hi, _, label = _realistic_ftp_gain(current_ftp, weeks)
        realistic_max   = current_ftp + hi

        if target > realistic_max:
            state["target_ftp_confirm_pending"] = target
            save_wizard(state)
            return (
                f"⚠️ *{target}W is above the realistic upper bound* for {weeks} weeks.\n\n"
                f"Based on your current FTP ({current_ftp}W), the realistic ceiling is *{realistic_max}W* ({label}).\n\n"
                f"Setting an unrealistic target won't make the plan harder — it may just miscalibrate your zones.\n\n"
                f"Are you sure you want to set *{target}W* as your target?",
                False
            )

        state["target_ftp"] = target
        state["step"] = "xco"
        save_wizard(state)
        return (
            f"✅ Target FTP: *{target}W*\n\n"
            f"*STEP 5: Include XCO Power Training?*\n\n"
            f"Adds 2 gym sessions/week specifically for cross-country MTB:\n\n"
            f"💪 *Gym:* Max strength, explosive power, core & coordination\n"
            f"🚴 *Bike:* Torque intervals, sprint power, micro-bursts\n\n"
            f"Recommended if you race XCO or want explosive power."
        ), False

    # ── TARGET KM ─────────────────────────────────────────────────────────────
    elif step == "target_km":
        try:
            state["target_km"] = int(text.strip())
        except ValueError:
            return "Please reply with a number (km per week)", False
        state["step"] = "xco"
        save_wizard(state)
        return (
            f"✅ Distance target: *{state['target_km']} km/week*\n\n"
            f"*STEP 5: Include XCO Power Training?*\n\n"
            f"Adds 2 gym sessions/week specifically for cross-country MTB:\n\n"
            f"💪 *Gym:* Max strength, explosive power, core & coordination\n"
            f"🚴 *Bike:* Torque intervals, sprint power, micro-bursts\n\n"
            f"Recommended if you race XCO or want explosive power."
        ), False

    # ── TARGET KG ─────────────────────────────────────────────────────────────
    elif step == "target_kg":
        try:
            state["target_kg"] = float(text.strip())
        except ValueError:
            return "Please reply with a number (target kg, or 0 to skip)", False
        state["step"] = "xco"
        save_wizard(state)
        return (
            f"✅ Target weight: *{state['target_kg']} kg*\n\n"
            f"*STEP 5: Include XCO Power Training?*\n\n"
            f"Adds 2 gym sessions/week specifically for cross-country MTB:\n\n"
            f"💪 *Gym:* Max strength, explosive power, core & coordination\n"
            f"🚴 *Bike:* Torque intervals, sprint power, micro-bursts\n\n"
            f"Recommended if you race XCO or want explosive power."
        ), False

    # ── XCO ───────────────────────────────────────────────────────────────────
    elif step == "xco":
        xco = text.strip().lower() in ("y", "yes")
        state["xco"] = xco
        state["step"] = "plan_type"
        save_wizard(state)
        return _build_plan_type_message(state), False

    # ── PLAN TYPE ─────────────────────────────────────────────────────────────
    elif step == "plan_type":
        choice = text.strip().lower()
        if choice not in ("classic", "ai"):
            return "Choose *Classic* or *AI-generated*.", False
        state["plan_type"] = choice
        state["step"] = "confirm"
        save_wizard(state)
        return build_confirm_message(state), False

    # ── CONFIRM ───────────────────────────────────────────────────────────────
    elif step == "confirm":
        if text.strip().lower() in ("y", "yes"):
            return generate_plan_from_wizard(state, persona), True
        elif text.strip().lower() in ("n", "no", "cancel"):
            clear_wizard()
            return "❌ Plan creation cancelled. Send /newplan to start again.", True
        else:
            return "Reply *y* to create the plan or *n* to cancel", False

    return "Something went wrong. Send /newplan to start again.", True


_AI_PLAN_COST_USD = 0.05  # estimated cost per AI plan generation (Haiku)

def _build_plan_type_message(state):
    _, spent, allowance = check_demo_quota(_UDIR)
    if allowance is not None:
        rem_after = max(0, allowance - spent - _AI_PLAN_COST_USD)
        pct_after = round(rem_after / allowance * 100)
        filled_after = int(rem_after / allowance * 10)
        bar_after = "█" * filled_after + "░" * (10 - filled_after)
        ai_line = (
            f"🤖 *AI-generated* — `{bar_after}` {pct_after}% remaining\n"
            f"  Personalized by {state.get('persona','your coach')}, adaptive periodization"
        )
    else:
        ai_line = (
            f"🤖 *AI-generated* ♾️\n"
            f"  Personalized by {state.get('persona','your coach')}, adaptive periodization"
        )
    return (
        f"*How would you like to generate your plan?*\n\n"
        f"📋 *Classic* — instant, rule-based, free\n\n"
        f"{ai_line}"
    )


def build_confirm_message(state):
    lines = [
        "✅ *Plan Summary — confirm to build*\n",
        f"🎯 Goal: *{state.get('goal','general')}*",
        f"⚡ FTP: *{state.get('ftp', 220)}W*",
        f"📅 Duration: *{state.get('weeks', 8)} weeks*",
        f"💪 XCO Power: *{'Yes' if state.get('xco') else 'No'}*",
    ]
    if state.get("event_name"):
        lines.append(f"🏁 Event: *{state['event_name']}* on {state.get('event_date','')}")
    if state.get("target_ftp"):
        ftp_note = " _(above recommended)_" if state.get("target_ftp_override") else ""
        lines.append(f"📈 Target FTP: *{state['target_ftp']}W*{ftp_note}")
    if state.get("target_km"):
        lines.append(f"🛣 Distance target: *{state['target_km']} km/week*")
    if state.get("target_kg"):
        lines.append(f"⚖️ Target weight: *{state['target_kg']} kg*")
    plan_type = state.get("plan_type", "classic")
    lines.append(f"🔧 Generation: *{'🤖 AI-generated' if plan_type == 'ai' else '📋 Classic'}*")
    lines.append("\nReply *y* to build this plan or *n* to cancel")
    return "\n".join(lines)


def _generate_ai_plan(state, persona):
    """Call Claude Haiku to generate a personalized training plan JSON."""
    import urllib.request, urllib.error
    from datetime import datetime, timedelta

    goal       = state.get("goal", "general")
    ftp        = state.get("ftp", 220)
    weeks      = state.get("weeks", 8)
    xco        = state.get("xco", False)
    target_ftp = state.get("target_ftp")
    target_km  = state.get("target_km")
    target_kg  = state.get("target_kg")
    event_name = state.get("event_name")
    event_date = state.get("event_date")

    # Compute start date (next Sunday)
    today = datetime.today()
    days_to_sunday = (6 - today.weekday()) % 7
    start = today + timedelta(days=days_to_sunday)
    start_str = start.strftime("%Y-%m-%d")

    extras = []
    if target_ftp: extras.append(f"Target FTP: {target_ftp}W")
    if target_km:  extras.append(f"Target distance: {target_km} km/week")
    if target_kg:  extras.append(f"Target weight: {target_kg} kg")
    if event_name: extras.append(f"Event: {event_name} on {event_date}")
    if xco:        extras.append("Include XCO gym sessions (2/week: strength + bike power)")
    extras_str = "\n".join(extras) if extras else "No additional targets."

    workout_types = "rest, z2_base, long_ride, sweet_spot, threshold_2x20, vo2_intervals, recovery, tempo"
    if xco:
        workout_types += ", gym_strength, gym_power"

    prompt = (
        f"Generate a {weeks}-week cycling training plan as JSON.\n\n"
        f"Athlete: FTP {ftp}W, Goal: {goal}\n"
        f"{extras_str}\n\n"
        f"Plan starts: {start_str} (Sunday)\n\n"
        f"Rules:\n"
        f"- 7 days per week, Sunday to Saturday\n"
        f"- Use only these workout types: {workout_types}\n"
        f"- Week 4, 8, 12, etc. are recovery weeks (easier)\n"
        f"- Vary sessions week to week for progression\n"
        f"- Write description in first person as {persona['name']} speaking to the athlete (1-2 sentences, coaching voice)\n\n"
        f"Output ONLY valid JSON, no extra text:\n"
        f'{{"weekly_plans": [{{"week": 1, "phase": "build", "week_start": "YYYY-MM-DD", "total_tss": 0, "days": ['
        f'{{"day": "Sunday", "date": "YYYY-MM-DD", "workout": "rest", "name": "Rest Day", "description": "...", "duration_min": 0, "tss": 0, "zone": 0}}'
        f']}}]}}'
    )

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    payload = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 8000,
        "system": f"You are {persona['name']}, a world-class cycling coach. {persona.get('tagline','')} Output only valid JSON.",
        "messages": [{"role": "user", "content": prompt}],
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())

    usage = data.get("usage", {})
    record_ai_cost(_UDIR, usage.get("input_tokens", 0), usage.get("output_tokens", 0))

    raw = data["content"][0]["text"].strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    plan_data = json.loads(raw.strip())

    weekly_plans = plan_data.get("weekly_plans", [])
    if not weekly_plans or len(weekly_plans) < weeks:
        raise ValueError(f"AI returned incomplete plan ({len(weekly_plans)}/{weeks} weeks). Try again.")

    # Merge into full plan structure
    plan = {
        "goal": goal, "weeks": weeks, "ftp": ftp,
        "persona": persona["id"],
        "start_date": start_str,
        "created_at": datetime.now().isoformat(),
        "event_name": event_name, "event_date": event_date,
        "target_ftp": target_ftp, "target_km": target_km, "target_kg": target_kg,
        "ai_generated": True,
        "weekly_plans": weekly_plans,
    }
    return plan


def generate_plan_from_wizard(state, persona):
    """Build and save the plan from wizard state."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from training_plan import build_plan, build_xco_plan

    goal      = state.get("goal", "general")
    ftp       = state.get("ftp", 220)
    weeks     = state.get("weeks", 8)
    xco       = state.get("xco", False)
    use_ai    = state.get("plan_type") == "ai"

    kwargs = dict(
        goal=goal, weeks=weeks, ftp=ftp, persona=persona,
        event_name=state.get("event_name"),
        event_date=state.get("event_date"),
        target_ftp=state.get("target_ftp"),
        target_km=state.get("target_km"),
        target_kg=state.get("target_kg"),
    )

    try:
        if use_ai:
            plan = _generate_ai_plan(state, persona)
        elif xco:
            plan = build_xco_plan(**{k: v for k, v in kwargs.items() if k not in ("target_km","target_kg")})
        else:
            plan = build_plan(**kwargs)

        _UDIR.mkdir(parents=True, exist_ok=True)
        _archive_plan(_UDIR)
        (_UDIR / "training_plan.json").write_text(json.dumps(plan, indent=2))
        clear_wizard()

        # Show first week preview
        first_week = plan["weekly_plans"][0] if plan.get("weekly_plans") else {}
        gen_label = "🤖 AI-generated" if use_ai else "📋 Classic"
        lines = [
            f"✅ *Plan created and saved!* ({gen_label})\n",
            f"📅 {weeks} weeks starting {plan['start_date']}",
            f"{'💪 XCO Power included' if xco else '🚴 Cycling only'}",
            f"\n*Week 1 preview:*",
        ]
        for day in first_week.get("days", []):
            if day.get("workout") == "rest":
                lines.append(f"  {day['day'][:3]}: REST")
            else:
                icon = "💪" if day.get("type") == "gym" else "🚴"
                lines.append(f"  {day['day'][:3]}: {icon} {day['name']}")

        lines.append(f"\nUse /today for today's session and /week for the full week.")
        lines.append(f"\n— {persona['name']}")
        return "\n".join(lines)

    except Exception as e:
        clear_wizard()
        return f"⚠️ Error building plan: {e}\n\nTry again with /newplan"


# ── Main loop ─────────────────────────────────────────────────────────────────

def cmd_nextweek(persona):
    """Show next week's training plan."""
    plan_file = _UDIR / "training_plan.json"
    if not plan_file.exists():
        return f"📅 *No training plan active.* Use /newplan to create one.\n\n— {persona['name']}"

    plan  = load_plan_safe()
    today = datetime.today().strftime("%Y-%m-%d")
    weeks = plan.get("weekly_plans", [])

    for i, week in enumerate(weeks):
        days  = week.get("days", [])
        dates = [d["date"] for d in days]
        if not dates:
            continue
        if dates[0] <= today <= dates[-1]:
            # Found current week — return next one
            if i + 1 < len(weeks):
                nw   = weeks[i + 1]
                ndays = nw.get("days", [])
                lines = [
                    f"📅 *Week {nw['week']} (next week) — {nw['phase'].upper()}*",
                    f"TSS target: {nw['total_tss']}\n"
                ]
                for day in ndays:
                    if day["workout"] == "rest":
                        lines.append(f"  {day['day'][:3]}: 😴 REST")
                    elif day.get("type") == "gym":
                        lines.append(f"  {day['day'][:3]}: 🏋️ *{day['name']}* (TSS {day['tss']})")
                    else:
                        lines.append(f"  {day['day'][:3]}: 🚴 *{day['name']}* (TSS {day['tss']})")
                lines.append(f"\n_{persona['header_quote']}_")
                return "\n".join(lines)
            else:
                return "You're on the last week of your plan! Use /newplan to create a new one."

    # Plan hasn't started yet — show week 1 as "next week"
    first_week = weeks[0] if weeks else None
    if first_week:
        first_date = (first_week.get("days") or [{}])[0].get("date", "")
        if first_date and today < first_date:
            ndays = first_week.get("days", [])
            lines = [
                f"📅 *Week 1 (starts {first_date}) — {first_week['phase'].upper()}*",
                f"TSS target: {first_week['total_tss']}\n"
            ]
            for day in ndays:
                if day["workout"] == "rest":
                    lines.append(f"  {day['day'][:3]}: 😴 REST")
                elif day.get("type") == "gym":
                    lines.append(f"  {day['day'][:3]}: 🏋️ *{day['name']}* (TSS {day['tss']})")
                else:
                    lines.append(f"  {day['day'][:3]}: 🚴 *{day['name']}* (TSS {day['tss']})")
            lines.append(f"\n_{persona['header_quote']}_")
            return "\n".join(lines)

    return "Couldn't locate the current week in your plan."


def cmd_nextmonth(persona):
    """Show next 4 weeks of the training plan."""
    plan_file = _UDIR / "training_plan.json"
    if not plan_file.exists():
        return f"📅 *No training plan active.* Use /newplan to create one.\n\n— {persona['name']}"

    plan  = load_plan_safe()
    today = datetime.today().strftime("%Y-%m-%d")
    weeks = plan.get("weekly_plans", [])

    current_idx = None
    for i, week in enumerate(weeks):
        days  = week.get("days", [])
        dates = [d["date"] for d in days]
        if dates and dates[0] <= today <= dates[-1]:
            current_idx = i
            break

    start = (current_idx + 1) if current_idx is not None else 0
    upcoming = weeks[start:start + 4]

    if not upcoming:
        return "No upcoming weeks found in your plan. Use /newplan to extend it."

    lines = [f"📆 *Next month — weeks {upcoming[0]['week']}–{upcoming[-1]['week']}*\n"]
    for week in upcoming:
        lines.append(f"*Week {week['week']} — {week['phase'].upper()}* (TSS {week['total_tss']})")
        for day in week.get("days", []):
            if day["workout"] == "rest":
                lines.append(f"  {day['day'][:3]}: 😴 REST")
            elif day.get("type") == "gym":
                lines.append(f"  {day['day'][:3]}: 🏋️ {day['name']} ({day.get('duration_min', '?')} min)")
            else:
                lines.append(f"  {day['day'][:3]}: 🚴 {day['name']} ({day.get('duration_min', '?')} min)")
        lines.append("")

    lines.append(f"_{persona['header_quote']}_")
    return "\n".join(lines)


def cmd_fullplan(persona):
    """Show the entire training plan summary."""
    plan_file = _UDIR / "training_plan.json"
    if not plan_file.exists():
        return f"📅 *No training plan active.* Use /newplan to create one.\n\n— {persona['name']}"

    plan  = load_plan_safe()
    today = datetime.today().strftime("%Y-%m-%d")
    weeks = plan.get("weekly_plans", [])

    goal = plan.get("goal", "general")
    total_weeks = len(weeks)
    lines = [f"🗓 *Full Training Plan — {goal.upper()} ({total_weeks} weeks)*\n"]

    for week in weeks:
        days  = week.get("days", [])
        dates = [d["date"] for d in days]
        marker = " ← current" if dates and dates[0] <= today <= dates[-1] else ""
        lines.append(f"*Week {week['week']} ({week['phase'].upper()})* — TSS {week['total_tss']}{marker}")
        for day in days:
            today_m = " ← today" if day["date"] == today else ""
            if day["workout"] == "rest":
                lines.append(f"  {day['day'][:3]} {day['date'][5:]}: 😴 REST{today_m}")
            elif day.get("type") == "gym":
                lines.append(f"  {day['day'][:3]} {day['date'][5:]}: 🏋️ {day['name']} (TSS {day['tss']}){today_m}")
            else:
                lines.append(f"  {day['day'][:3]} {day['date'][5:]}: 🚴 {day['name']} (TSS {day['tss']}){today_m}")
        lines.append("")

    lines.append(f"_{persona['header_quote']}_")
    return "\n".join(lines)


_ACTIVITY_CACHE_FILE = Path("/tmp/strava_chat_cache.json")
_ACTIVITY_CACHE_TTL  = 300  # seconds


def _get_cached_activities():
    """Return recent activities from a local file cache (5-min TTL)."""
    try:
        if _ACTIVITY_CACHE_FILE.exists():
            raw  = json.loads(_ACTIVITY_CACHE_FILE.read_text())
            age  = time.time() - raw.get("ts", 0)
            if age < _ACTIVITY_CACHE_TTL:
                return raw.get("activities", [])
        activities = get_activities(days=14, limit=5, activity_type=None, user_dir=_UDIR)
        if activities:
            activities.sort(key=lambda a: a.get("start_date", ""), reverse=True)
        _ACTIVITY_CACHE_FILE.write_text(json.dumps({"ts": time.time(), "activities": activities or []}))
        return activities or []
    except Exception:
        return []


def cmd_chat(user_message, persona):
    """Send a plain text message to Claude API with persona + Strava context."""
    config  = load_config(_UDIR)
    ftp     = config.get("ftp", 220)
    # SECURITY: env var is the primary source; config.json fallback removed.
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    if not api_key:
        return (
            f"💬 *{persona['name']} would answer, but no Anthropic API key is set.*\n\n"
            f"Add it to ~/.config/strava/config.json:\n"
            f"Contact your administrator to configure the API key."
        )

    # ── Strava context (cached, max 3 rides, compact) ─────────────────────────
    strava_ctx = ""
    try:
        activities = _get_cached_activities()
        if activities:
            lines = []
            for a in activities[:3]:
                dist = meters_to_km(a.get("distance", 0))
                pwr  = f"{int(a['average_watts'])}W" if a.get("average_watts") else "?"
                date = a.get("start_date_local", "")[:10]
                lines.append(f"{date}: {dist}km {pwr}")
            strava_ctx = "Last rides: " + " | ".join(lines) + "\n"
    except Exception:
        pass

    # ── Plan context (today only + current week summary, no descriptions) ──────
    plan_ctx = ""
    try:
        plan_file = _UDIR / "training_plan.json"
        if plan_file.exists():
            plan  = load_plan_safe()
            today = datetime.today().strftime("%Y-%m-%d")
            for week in plan.get("weekly_plans", []):
                days  = week.get("days", [])
                dates = [d["date"] for d in days]
                if not dates or not (dates[0] <= today <= dates[-1]):
                    continue
                # Today's detail
                today_detail = ""
                for d in days:
                    if d["date"] == today and d["workout"] != "rest":
                        today_detail = f"Today: {d['name']} — {d.get('description','')[:120]}"
                        break
                # Week summary — names only
                week_summary = ", ".join(
                    d["name"] if d["workout"] != "rest" else "rest"
                    for d in days
                )
                plan_ctx = (
                    f"Plan week {week['week']} ({week['phase']}, TSS {week['total_tss']}): {week_summary}\n"
                    + (today_detail + "\n" if today_detail else "")
                )
                break
    except Exception:
        pass

    # ── Prompt caching: stable persona block + small dynamic block ─────────────
    _zf = persona.get("zone_feedback", {})
    _voice_samples = [pick_feedback(_zf, z) for z in ("z1", "z2", "z3") if _zf.get(z)]
    _voice_hint = " | ".join(_voice_samples[:2]) if _voice_samples else ""

    stable_block = (
        f"You are {persona['name']}, a world-class cycling coach. "
        f"{persona.get('tagline', '')} "
        f"Speak in first person, in your authentic voice — exactly like these examples: {_voice_hint} "
        f"Be direct, motivating, specific. "
        f"Reply in under 120 words. No bullet points — talk like a coach, not a listicle."
    )
    dynamic_block = f"Athlete FTP: {ftp}W\n{strava_ctx}{plan_ctx}".strip()

    system_blocks = [
        {
            "type": "text",
            "text": stable_block,
            "cache_control": {"type": "ephemeral"},
        },
    ]
    if dynamic_block:
        system_blocks.append({"type": "text", "text": dynamic_block})

    payload = json.dumps({
        "model": "claude-sonnet-4-5",
        "max_tokens": 250,
        "system": system_blocks,
        "messages": [{"role": "user", "content": user_message}]
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type":         "application/json",
            "x-api-key":            api_key,
            "anthropic-version":    "2023-06-01",
            "anthropic-beta":       "prompt-caching-2024-07-31",
        },
        method="POST"
    )
    try:
        data  = json.loads(urlopen_with_retry(req, timeout=30))
        usage = data.get("usage", {})
        record_ai_cost(_UDIR, usage.get("input_tokens", 0), usage.get("output_tokens", 0))
        reply = data["content"][0]["text"].strip()
        return f"_{reply}_\n\n— {persona['name']}"
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        log.error(f"Anthropic API {e.code}: {body}")
        return f"⚠️ Coach is unavailable right now: {e}"
    except Exception as e:
        return f"⚠️ Coach is unavailable right now: {e}"

def _is_admin(chat_id: str) -> bool:
    """Admin = ADMIN_CHAT_ID env var, or telegram_chat_id from owner config."""
    admin = os.environ.get("ADMIN_CHAT_ID", "")
    if not admin and CONFIG_FILE.exists():
        try:
            admin = str(json.loads(CONFIG_FILE.read_text()).get("telegram_chat_id", ""))
        except Exception:
            pass
    return bool(admin) and chat_id == admin


def cmd_admin(chat_id: str, args: list) -> str:
    """Admin commands — only accessible to the bot owner.

    Usage:
      /admin quota <user_chat_id> <amount_usd>   — set demo allowance (0 = block, "off" = unlimited)
      /admin quota <user_chat_id>                — show current quota for a user
      /admin quotas                              — list all users with active quotas
    """
    if not _is_admin(chat_id):
        return "⛔ Admin only."

    if not args:
        token = os.environ.get("STRAVA_TELEGRAM_BOT_TOKEN", "")
        tg_api_json(token, "sendMessage", {
            "chat_id":    chat_id,
            "text":       "*Admin panel:*",
            "parse_mode": "Markdown",
            "reply_markup": {"inline_keyboard": [
                [
                    {"text": "📊 Stats",     "callback_data": "admin_stats"},
                    {"text": "👥 Users",     "callback_data": "admin_users"},
                ],
                [
                    {"text": "📋 Quotas",   "callback_data": "admin_quotas"},
                    {"text": "📜 List",     "callback_data": "admin_list"},
                ],
                [
                    {"text": "💰 Set quota", "callback_data": "admin_pick_quota"},
                    {"text": "🗑️ Delete",    "callback_data": "admin_pick_delete"},
                ],
                [
                    {"text": "🌐 Web panel", "callback_data": "admin_web"},
                ],
            ]},
        })
        return None

    sub = args[0].lower()

    if sub == "stats":
        users_dir = CONFIG_DIR / "users"
        if not users_dir.exists():
            return "No users yet."
        total_spent = 0.0
        total_allowance = 0.0
        user_count = 0
        over_limit = 0
        for udir in users_dir.iterdir():
            if not udir.is_dir():
                continue
            user_count += 1
            q = get_demo_quota(udir)
            spent     = q.get("spent_usd", 0.0)
            allowance = q.get("allowance_usd")
            total_spent += spent
            if allowance:
                total_allowance += allowance
                if spent >= allowance:
                    over_limit += 1
        # Include admin's own usage
        admin_dir = CONFIG_DIR / "users" / chat_id
        admin_q   = get_demo_quota(admin_dir)
        admin_spent = admin_q.get("spent_usd", 0.0)

        return (
            f"*Global usage summary:*\n\n"
            f"👥 Total users: {user_count}\n"
            f"💸 Total spent: ${total_spent:.4f}\n"
            f"🎯 Total allowances: ${total_allowance:.2f}\n"
            f"🔴 Over limit: {over_limit} user(s)\n\n"
            f"*Your usage (admin):* ${admin_spent:.4f}"
        )

    if sub == "quotas":
        users_dir = CONFIG_DIR / "users"
        if not users_dir.exists():
            return "No users directory found."
        rows = []
        for udir in sorted(users_dir.iterdir()):
            if not udir.is_dir():
                continue
            # Pending — no Strava auth yet
            if not (udir / "tokens.json").exists():
                cfg_name = udir.name
                try:
                    cfg_name = json.loads((udir / "config.json").read_text()).get("name", udir.name)
                except Exception:
                    pass
                rows.append(f"⏳ *{cfg_name}*\n   `{udir.name}` — pending Strava authorization")
                continue

            # Resolve Strava name
            name = udir.name
            try:
                t = json.loads((udir / "tokens.json").read_text())
                a = t.get("athlete", {})
                sn = f"{a.get('firstname','')} {a.get('lastname','')}".strip()
                if sn:
                    name = sn
            except Exception:
                pass

            q         = get_demo_quota(udir)
            allowance = q.get("allowance_usd")
            spent     = q.get("spent_usd", 0.0)
            if allowance is None:
                rows.append(f"♾️ *{name}*\n   `{udir.name}` — unlimited (${spent:.4f} spent)")
            elif allowance == 0:
                rows.append(f"🆕 *{name}*\n   `{udir.name}` — no quota set yet")
            else:
                pct       = (spent / allowance * 100) if allowance > 0 else 100
                bar       = "█" * int(pct / 10) + "░" * (10 - int(pct / 10))
                remaining = max(0.0, allowance - spent)
                icon      = "🔴" if spent >= allowance else ("🟡" if pct >= 80 else "🟢")
                rows.append(
                    f"{icon} *{name}*\n"
                    f"   `{udir.name}`\n"
                    f"   {bar} {pct:.0f}%\n"
                    f"   ${spent:.4f} / ${allowance:.2f}  (${remaining:.4f} left)"
                )
        return ("*All users — quotas:*\n\n" + "\n\n".join(rows)) if rows else "No users found."

    if sub == "quota":
        if len(args) < 2:
            return "Usage: `/admin quota <user_chat_id> [amount_usd|off]`"

        target_id = args[1]
        target_dir = CONFIG_DIR / "users" / target_id

        if len(args) == 2:
            # Show current quota
            if not target_dir.exists():
                return f"User `{target_id}` not found."
            _, spent, allowance = check_demo_quota(target_dir)
            if allowance is None:
                return f"User `{target_id}`: unlimited (spent ${spent:.4f})"
            if allowance == 0:
                return f"🆕 User `{target_id}`: no quota set yet (spent ${spent:.4f})"
            remaining = max(0.0, allowance - spent)
            return (
                f"User `{target_id}`:\n"
                f"  Allowance: ${allowance:.2f}\n"
                f"  Spent:     ${spent:.4f}\n"
                f"  Remaining: ${remaining:.4f}"
            )

        # Set quota
        raw = args[2].lower()
        if raw == "off":
            new_allowance = None
        else:
            try:
                new_allowance = float(raw)
                if new_allowance < 0:
                    return "Allowance must be >= 0."
            except ValueError:
                return f"Invalid amount `{raw}`. Use a number (e.g. `2.00`) or `off`."

        target_dir.mkdir(parents=True, exist_ok=True)
        set_demo_allowance(target_dir, new_allowance)

        # Resolve display name
        target_name = target_id
        try:
            t = json.loads((target_dir / "tokens.json").read_text())
            a = t.get("athlete", {})
            sn = f"{a.get('firstname','')} {a.get('lastname','')}".strip()
            if sn:
                target_name = sn
        except Exception:
            pass

        # Notify the user
        token = os.environ.get("STRAVA_TELEGRAM_BOT_TOKEN", "")
        if token:
            if new_allowance is None or new_allowance > 0:
                user_msg = (
                    "✅ *Your account has been activated!*\n\n"
                    "You now have access to your AI coach.\n"
                    "Ask me anything or use /help to see what I can do."
                )
            else:
                user_msg = (
                    "⛔ *Your demo access has been paused.*\n\n"
                    "Contact [@SuperMariooo](https://t.me/SuperMariooo) to top up your account."
                )
            try:
                send_message(token, target_id, user_msg)
            except Exception:
                pass

        if new_allowance is None:
            return f"✅ *{target_name}* (`{target_id}`) quota removed — unlimited access."
        return f"✅ *{target_name}* (`{target_id}`) demo allowance set to ${new_allowance:.2f}."

    if sub == "users":
        users_dir = CONFIG_DIR / "users"
        if not users_dir.exists():
            return "No users yet."
        total = strava = pending = 0
        for udir in users_dir.iterdir():
            if not udir.is_dir():
                continue
            total += 1
            if (udir / "tokens.json").exists():
                strava += 1
            else:
                pending += 1
        return (
            f"*User counts:*\n\n"
            f"👥 Total: {total}\n"
            f"✅ Strava connected: {strava}\n"
            f"⏳ Pending (no Strava auth): {pending}"
        )

    if sub == "list":
        users_dir = CONFIG_DIR / "users"
        if not users_dir.exists():
            return "No users yet."
        rows = []
        for udir in sorted(users_dir.iterdir()):
            if not udir.is_dir():
                continue
            cfg_file = udir / "config.json"
            name = "—"
            # Prefer Strava name from tokens.json (most reliable)
            if (udir / "tokens.json").exists():
                try:
                    t = json.loads((udir / "tokens.json").read_text())
                    a = t.get("athlete", {})
                    strava_name = f"{a.get('firstname','')} {a.get('lastname','')}".strip()
                    if strava_name:
                        name = strava_name
                except Exception:
                    pass
            # Fallback to config.json name
            if name == "—" and cfg_file.exists():
                try:
                    cfg  = json.loads(cfg_file.read_text())
                    name = cfg.get("strava_name") or cfg.get("name", "—")
                except Exception:
                    pass
            connected = "✅" if (udir / "tokens.json").exists() else "⏳"
            q = get_demo_quota(udir)
            spent     = q.get("spent_usd", 0.0)
            allowance = q.get("allowance_usd")
            quota_str = f"${spent:.3f}/${allowance:.2f}" if allowance is not None else f"${spent:.3f}/∞"
            rows.append(f"{connected} *{name}* `{udir.name}`\n    {quota_str}")
        if not rows:
            return "No users found."
        return "*All users:*\n\n" + "\n".join(rows)

    if sub == "delete":
        if len(args) < 2:
            return "Usage: `/admin delete <user_chat_id>`"
        target_id  = args[1]
        target_dir = CONFIG_DIR / "users" / target_id
        if not target_dir.exists():
            return f"User `{target_id}` not found."

        # Resolve name
        target_name = target_id
        try:
            t = json.loads((target_dir / "tokens.json").read_text())
            a = t.get("athlete", {})
            sn = f"{a.get('firstname','')} {a.get('lastname','')}".strip()
            if sn:
                target_name = sn
        except Exception:
            try:
                target_name = json.loads((target_dir / "config.json").read_text()).get("name", target_id)
            except Exception:
                pass

        # Check for pending confirmation
        confirm_file = CONFIG_DIR / f"_delete_confirm_{chat_id}.json"
        pending = {}
        if confirm_file.exists():
            try:
                pending = json.loads(confirm_file.read_text())
            except Exception:
                pass

        # Store pending confirmation and ask with inline buttons
        confirm_file.write_text(json.dumps({"target_id": target_id, "target_name": target_name}))
        token = os.environ.get("STRAVA_TELEGRAM_BOT_TOKEN", "")
        tg_api_json(token, "sendMessage", {
            "chat_id":    chat_id,
            "text":       f"⚠️ Are you sure you want to delete *{target_name}* (`{target_id}`)?",
            "parse_mode": "Markdown",
            "reply_markup": {"inline_keyboard": [[
                {"text": "✅ Yes, delete", "callback_data": f"admin_delete_yes_{target_id}"},
                {"text": "❌ No, cancel",  "callback_data": "admin_delete_no"},
            ]]},
        })
        return None

    return f"Unknown admin sub-command `{sub}`. Try `/admin` for help."


def _delete_confirm_file():
    return _UDIR / "pending_delete.txt"


def _leave_confirm_file():
    return _UDIR / "pending_leave.txt"


def cmd_leave():
    """Ask for confirmation before revoking Strava access and deleting all data."""
    _UDIR.mkdir(parents=True, exist_ok=True)
    _leave_confirm_file().write_text("pending")
    return (
        "⚠️ *Are you sure you want to leave?*\n\n"
        "This will:\n"
        "— Revoke your Strava authorization\n"
        "— Delete all your data from this bot\n"
        "— Stop all coaching and notifications\n\n"
        "This *cannot be undone*.\n\n"
        "Reply *yes* to confirm or *no* to cancel."
    )


def _do_leave(token: str, chat_id: str):
    """Revoke Strava token and delete all user data."""
    import shutil

    # Revoke Strava token
    tf = _UDIR / "tokens.json"
    if tf.exists():
        try:
            tokens     = json.loads(tf.read_text())
            access_tok = tokens.get("access_token", "")
            if access_tok:
                data = urllib.parse.urlencode({"access_token": access_tok}).encode()
                req  = urllib.request.Request(
                    "https://www.strava.com/oauth/deauthorize", data=data, method="POST"
                )
                urllib.request.urlopen(req, timeout=10)
        except Exception as e:
            log.warning(f"Strava deauth failed for {chat_id}: {e}")

    # Get user name before deleting — prefer Strava full name
    user_name = chat_id
    tokens_file = _UDIR / "tokens.json"
    if tokens_file.exists():
        try:
            t = json.loads(tokens_file.read_text())
            a = t.get("athlete", {})
            strava_name = f"{a.get('firstname','')} {a.get('lastname','')}".strip()
            if strava_name:
                user_name = strava_name
        except Exception:
            pass
    if user_name == chat_id:
        cfg_file = _UDIR / "config.json"
        if cfg_file.exists():
            try:
                user_name = json.loads(cfg_file.read_text()).get("name", chat_id)
            except Exception:
                pass

    # Delete all user data
    try:
        shutil.rmtree(_UDIR)
    except Exception as e:
        log.warning(f"Failed to delete user dir for {chat_id}: {e}")

    # Notify admin
    admin_id = os.environ.get("ADMIN_CHAT_ID", "")
    if admin_id and admin_id != chat_id:
        try:
            send_message(token, admin_id,
                f"👋 *User left*\n\n"
                f"*{user_name}* (`{chat_id}`) has unsubscribed and revoked Strava access."
            )
        except Exception:
            pass

    return (
        "✅ *Done. You've been unsubscribed.*\n\n"
        "Your Strava authorization has been revoked and all your data deleted.\n\n"
        "If you ever want to come back, just send /start."
    )


def cmd_deleteplan(persona, token: str = "", chat_id: str = ""):
    """Ask for confirmation before deleting."""
    plan_file = _UDIR / "training_plan.json"
    if not plan_file.exists():
        return f"🗑 No active plan to delete.\n\nUse /newplan to create one.", None

    plan  = load_plan_safe()
    goal  = plan.get("goal", "unknown")
    weeks = plan.get("weeks", "?")
    start = plan.get("start_date", "?")
    xco   = "✅ XCO included" if plan.get("xco_power") else "🚴 Cycling only"
    event = f" — {plan['event_name']}" if plan.get("event_name") else ""

    _UDIR.mkdir(parents=True, exist_ok=True)
    _delete_confirm_file().write_text("pending")

    msg = (
        f"🗑 *Delete Training Plan?*\n\n"
        f"Current plan:\n"
        f"  🎯 Goal: *{goal}{event}*\n"
        f"  📅 Duration: *{weeks} weeks* (started {start})\n"
        f"  💪 {xco}\n\n"
        f"⚠️ This cannot be undone."
    )

    if token and chat_id:
        tg_api_json(token, "sendMessage", {
            "chat_id": chat_id, "text": msg, "parse_mode": "Markdown",
            "reply_markup": {"inline_keyboard": [[
                {"text": "✅ Yes, delete", "callback_data": "deleteplan_confirm"},
                {"text": "❌ Cancel",       "callback_data": "deleteplan_cancel"},
            ]]},
        })
        return None, None

    return msg + "\n\nReply *yes* to confirm or *no* to cancel.", None


def transcribe_voice(token, file_id):
    """Download a Telegram voice/audio file and transcribe it with Whisper."""
    if not _WHISPER_AVAILABLE:
        log.warning("Whisper not installed — voice transcription unavailable (pip install openai-whisper)")
        return None

    try:
        import tempfile

        # Get file path from Telegram
        url = f"https://api.telegram.org/bot{token}/getFile?file_id={file_id}"
        data = json.loads(urlopen_with_retry(urllib.request.Request(url), timeout=10))
        if not data.get("ok"):
            return None
        file_path = data["result"]["file_path"]

        # Download the file
        dl_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
        ext = file_path.split(".")[-1] if "." in file_path else "ogg"
        with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp:
            tmp_path = tmp.name
            tmp.write(urlopen_with_retry(urllib.request.Request(dl_url), timeout=30))

        # Transcribe
        model = _whisper.load_model("base")
        result = model.transcribe(tmp_path, language="en")
        os.unlink(tmp_path)
        return result.get("text", "").strip()
    except Exception as e:
        log.warning(f"Whisper transcription error: {e}")
        return None


def handle_message(token, message):
    global _UDIR
    chat_id = str(message.get("chat", {}).get("id", ""))
    text    = message.get("text", "").strip()

    # Reset per-message AI usage tracker
    _ai_usage["input_tokens"]  = 0
    _ai_usage["output_tokens"] = 0
    _ai_usage["cost_usd"]      = 0.0

    # ── Per-user dir ──────────────────────────────────────────────────────────
    _UDIR = get_user_dir(chat_id)

    # ── Docker per-user guard (STRAVA_TELEGRAM_CHAT_ID set) ───────────────────
    allowed_chat_id = get_chat_id()
    if allowed_chat_id and chat_id != allowed_chat_id:
        log.warning(f"Rejected message from unknown chat_id={chat_id}")
        return

    # ── Onboarding: no tokens yet → run setup wizard ──────────────────────────
    if not (_UDIR / "tokens.json").exists():
        _raw_cmd = text.lstrip("/").split()[0].lower().split("@")[0] if text.startswith("/") else ""
        _has_pending_confirm = (CONFIG_DIR / f"_delete_confirm_{chat_id}.json").exists()
        _has_quota_pending   = (CONFIG_DIR / f"_quota_pending_{chat_id}.json").exists()
        _is_free_cmd = CMD_GROUPS.get(_raw_cmd, "ai_and_strava") == "free"
        # Admin can use free commands and respond to pending confirmations without Strava
        if _is_admin(chat_id) and (_is_free_cmd or _has_pending_confirm or _has_quota_pending):
            pass  # fall through to command dispatch
        else:
            handle_onboarding(token, chat_id, text, _UDIR)
            return

    # Show typing indicator immediately
    send_typing(token, chat_id)

    # ── Voice/audio message — transcribe with Whisper ────────────────────────
    if not text:
        voice = message.get("voice") or message.get("audio")
        if voice:
            file_id = voice.get("file_id")
            if file_id:
                log.info(f"  🎙️  Voice message received, transcribing...")
                transcribed = transcribe_voice(token, file_id)
                if transcribed:
                    log.info(f"  📝 Transcribed: {transcribed}")
                    text = transcribed
                else:
                    send_message(token, chat_id, "🎙️ Sorry, I couldn't transcribe that voice message. Try typing your question!")
                    return
        if not text:
            return

    persona = load_active_persona(_UDIR / "config.json")

    # ── Admin quota amount reply ──────────────────────────────────────────────
    _quota_pending_file = CONFIG_DIR / f"_quota_pending_{chat_id}.json"
    if _quota_pending_file.exists() and not text.startswith("/") and _is_admin(chat_id):
        pending = {}
        try:
            pending = json.loads(_quota_pending_file.read_text())
        except Exception:
            pass
        _quota_pending_file.unlink(missing_ok=True)
        target_id   = pending.get("target_id", "")
        target_name = pending.get("target_name", target_id)
        if target_id:
            raw = text.strip().lower()
            if raw == "off":
                new_allowance = None
            else:
                try:
                    new_allowance = float(raw)
                    if new_allowance < 0:
                        send_message(token, chat_id, "Allowance must be >= 0.")
                        return
                except ValueError:
                    send_message(token, chat_id, f"Invalid amount `{raw}`. Use a number or `off`.")
                    return
            target_dir = CONFIG_DIR / "users" / target_id
            target_dir.mkdir(parents=True, exist_ok=True)
            set_demo_allowance(target_dir, new_allowance)
            if new_allowance is None or new_allowance > 0:
                user_msg = (
                    "✅ *Your account has been activated!*\n\n"
                    "You now have access to your AI coach.\n"
                    "Ask me anything or use /help to see what I can do."
                )
            else:
                user_msg = (
                    "⛔ *Your demo access has been paused.*\n\n"
                    "Contact [@SuperMariooo](https://t.me/SuperMariooo) to top up your account."
                )
            try:
                send_message(token, target_id, user_msg)
            except Exception:
                pass
            label = "unlimited" if new_allowance is None else f"${new_allowance:.2f}"
            send_message(token, chat_id, f"✅ *{target_name}* (`{target_id}`) quota set to {label}.")
        return

    # ── Admin delete confirmation ─────────────────────────────────────────────
    _admin_del_confirm = CONFIG_DIR / f"_delete_confirm_{chat_id}.json"
    if _admin_del_confirm.exists() and not text.startswith("/"):
        pending = {}
        try:
            pending = json.loads(_admin_del_confirm.read_text())
        except Exception:
            pass
        _admin_del_confirm.unlink(missing_ok=True)
        if text.strip().lower() in ("yes", "y") and pending.get("target_id"):
            target_id   = pending["target_id"]
            target_name = pending.get("target_name", target_id)
            target_dir  = CONFIG_DIR / "users" / target_id
            bot_token   = os.environ.get("STRAVA_TELEGRAM_BOT_TOKEN", "")
            if bot_token:
                try:
                    send_message(bot_token, target_id,
                        "⛔ *Your account has been removed.*\n\n"
                        "Your data has been deleted by the admin.\n"
                        "Contact [@SuperMariooo](https://t.me/SuperMariooo) for more info."
                    )
                except Exception:
                    pass
            import shutil
            shutil.rmtree(target_dir, ignore_errors=True)
            send_message(token, chat_id, f"🗑️ *{target_name}* (`{target_id}`) has been deleted.")
        else:
            send_message(token, chat_id, "👍 Deletion cancelled.")
        return

    # ── Leave confirmation — must run before quota/auth checks ────────────────
    if _leave_confirm_file().exists() and not text.startswith("/"):
        if text.strip().lower() in ("yes", "y"):
            reply = _do_leave(token, chat_id)
            send_message(token, chat_id, reply)
        else:
            _leave_confirm_file().unlink()
            send_message(token, chat_id, "👍 Cancelled. You're still here!")
        return

    # ── Per-user rate limiting ────────────────────────────────────────────────
    # Determine the command key for quota check.
    # Plain-text messages (AI chat) use the "_chat" key.
    if text.startswith("/"):
        _rate_cmd = text.lstrip("/").split()[0].lower().split("@")[0]
    else:
        _rate_cmd = "_chat"

    # ── Block non-free commands until Strava is authorized ────────────────────
    _cmd_group = CMD_GROUPS.get(_rate_cmd, "ai_and_strava")
    if _cmd_group != "free" and not (_UDIR / "tokens.json").exists():
        send_message(token, chat_id,
            "⛔ *Strava not connected yet.*\n\n"
            "Please complete the Strava authorization first.\n"
            "Contact the admin if you need the link again."
        )
        return

    # ── Demo quota check (AI commands only) ───────────────────────────────────
    _ai_group = CMD_GROUPS.get(_rate_cmd, "free")
    if _ai_group in ("ai_and_strava", "ai_only"):
        _quota_ok, _spent, _allowance = check_demo_quota(_UDIR)
        if not _quota_ok:
            send_message(token, chat_id,
                f"🎟 *You are out of demo allowance*\n\n"
                f"Contact the admin to upgrade your account and unlock full access.\n"
                f"[@SuperMariooo](https://t.me/SuperMariooo)"
            )
            # Notify admin
            admin_id = os.environ.get("ADMIN_CHAT_ID", "")
            if not admin_id and CONFIG_FILE.exists():
                try:
                    admin_id = str(json.loads(CONFIG_FILE.read_text()).get("telegram_chat_id", ""))
                except Exception:
                    pass
            if admin_id and admin_id != chat_id:
                try:
                    user_cfg  = _UDIR / "config.json"
                    user_name = json.loads(user_cfg.read_text()).get("name", chat_id) if user_cfg.exists() else chat_id
                    send_message(token, admin_id,
                        f"🔔 *Quota alert*\n\n"
                        f"User *{user_name}* (`{chat_id}`) has reached their demo limit "
                        f"(${_spent:.4f} / ${_allowance:.2f}).\n\n"
                        f"Use `/admin quota {chat_id} <amount>` to top them up."
                    )
                except Exception:
                    pass
            return

    # ── Check if user is mid-wizard ───────────────────────────────────────────
    with _wizard_lock(_UDIR):
        wizard = load_wizard()
        if wizard and not text.startswith("/"):
            reply, done = handle_wizard(wizard, text, persona)
            if done:
                clear_wizard()
                if reply is not None:
                    send_message(token, chat_id, reply)
            else:
                current_state = load_wizard()
                _wizard_send(token, chat_id, reply, current_state)
            return

    # ── Check if awaiting delete confirmation ─────────────────────────────────
    if _delete_confirm_file().exists() and not text.startswith("/"):
        if text.strip().lower() in ("yes", "y"):
            _archive_plan(_UDIR)
            _delete_confirm_file().unlink()
            send_message(token, chat_id,
                f"✅ *Training plan archived.*\n\n"
                f"Use /newplan whenever you're ready to build a new one.\n\n"
                f"— {persona['name']}")
        else:
            _delete_confirm_file().unlink()
            send_message(token, chat_id, "👍 Deletion cancelled. Your plan is safe.")
        return

    # ── Plain text — AI coaching chat ─────────────────────────────────────────
    if not text.startswith("/"):
        send_typing(token, chat_id)  # refresh typing before slow Claude call
        reply = cmd_chat(text, persona)
        if reply:
            send_message(token, chat_id, reply)
        return

    parts = text.lstrip("/").split()
    cmd   = parts[0].lower().split("@")[0]
    args  = parts[1:]

    log.info(f"  → /{cmd} {args}")

    voice_text = None

    if cmd == "contact":
        reply = (
            "📬 *Need help or have a question?*\n\n"
            "Reach out to the admin directly on Telegram:\n"
            "👉 @SuperMariooo"
        )
    elif cmd in ("start", "setup"):
        reply = cmd_help(persona)
    elif cmd == "quota":
        reply = cmd_quota(_UDIR)
    elif cmd == "notify":
        reply = cmd_notify(_UDIR, args, token=token, chat_id=chat_id)
    elif cmd == "leave":
        reply = cmd_leave()
    elif cmd == "help":
        reply = cmd_help(persona)
    elif cmd == "coach":
        reply = cmd_coach(args, persona, token=token, chat_id=chat_id)
        persona = load_active_persona(_UDIR / "config.json")
    elif cmd == "ride":
        result = cmd_ride(persona)
        reply, voice_text = result if isinstance(result, tuple) else (result, None)
    elif cmd == "voice":
        reply = cmd_voice(persona, chat_id, token)
    elif cmd in ("plan", "today"):
        if args and args[0].lower() == "xco":
            result = cmd_plan_xco(persona)
        else:
            result = cmd_today(persona)
        reply, voice_text = result if isinstance(result, tuple) else (result, None)
    elif cmd == "tomorrow":
        result = cmd_tomorrow(persona)
        reply, voice_text = result if isinstance(result, tuple) else (result, None)
    elif cmd in ("planxco", "gym"):
        result = cmd_plan_xco(persona)
        reply, voice_text = result if isinstance(result, tuple) else (result, None)
    elif cmd == "newplan":
        with _wizard_lock(_UDIR):
            clear_wizard()
            reply = cmd_newplan(persona, token=token, chat_id=chat_id)
    elif cmd == "deleteplan":
        result = cmd_deleteplan(persona, token=token, chat_id=chat_id)
        reply, voice_text = result if isinstance(result, tuple) else (result, None)
    elif cmd == "week":
        reply = cmd_week(persona)
    elif cmd == "nextweek":
        reply = cmd_nextweek(persona)
    elif cmd == "nextmonth":
        reply = cmd_nextmonth(persona)
    elif cmd in ("fullplan", "allplan", "myplan"):
        reply = cmd_fullplan(persona)
    elif cmd == "stats":
        if args and args[0].isdigit():
            reply = cmd_stats(persona, days=int(args[0]))
        else:
            tg_api_json(token, "sendMessage", {
                "chat_id": chat_id, "text": "📊 *Stats — select period:*",
                "parse_mode": "Markdown",
                "reply_markup": {"inline_keyboard": [
                    [{"text":  "7 days", "callback_data": "stats_7"},
                     {"text": "14 days", "callback_data": "stats_14"},
                     {"text": "21 days", "callback_data": "stats_21"}],
                    [{"text": "30 days", "callback_data": "stats_30"},
                     {"text": "45 days", "callback_data": "stats_45"},
                     {"text": "60 days", "callback_data": "stats_60"}],
                    [{"text": "75 days", "callback_data": "stats_75"},
                     {"text": "90 days", "callback_data": "stats_90"}],
                ]},
            })
            reply = None
    elif cmd in ("stats30", "month"):
        reply = cmd_stats(persona, days=30)
    elif cmd == "trends":
        if args and args[0].isdigit():
            reply = cmd_trends(persona, days=int(args[0]))
        else:
            reply = cmd_trends(persona, days=30)
    elif cmd == "admin":
        reply = cmd_admin(chat_id, args)
    else:
        reply = f"Unknown command `/{cmd}`. Try /help"

    if reply is not None:
        # Resolve display name
        _user_name = message.get("from", {}).get("first_name", "") or chat_id
        log_query(
            _UDIR, chat_id, _user_name, text, reply,
            tokens_used=_ai_usage["input_tokens"] + _ai_usage["output_tokens"],
            cost_usd=_ai_usage["cost_usd"],
        )
        if voice_text:
            send_message_with_voice_btn(token, chat_id, reply, voice_text)
        else:
            send_message(token, chat_id, reply)


def run(loop=False):
    token  = get_token()
    offset = load_offset()

    log.info(f"🤖 Strava Custom Coach Bot — {'polling loop' if loop else 'one-shot'}")

    # Consecutive error counters — reset to 0 on success
    network_errors     = 0
    update_errors      = 0
    msg_errors         = 0
    callback_errors    = 0

    while True:
        timeout = 30 if loop else 0
        try:
            updates = get_updates(token, offset=offset, timeout=timeout)
            # Successful poll — reset network/update error counters
            network_errors = 0
            update_errors  = 0

        except TimeoutError:
            # Normal for long-poll — just retry immediately, not an error
            continue

        except OSError as e:
            network_errors += 1
            log.warning(f"Network error #{network_errors}: {e} — retrying in 5s")
            send_error_alert("Network error", e, network_errors)
            time.sleep(5)
            continue

        except Exception as e:
            update_errors += 1
            log.warning(f"getUpdates error #{update_errors}: {e} — retrying in 10s")
            send_error_alert("Telegram API error", e, update_errors)
            time.sleep(10)
            continue

        for update in updates:
            uid = update.get("update_id", 0)
            offset = uid + 1
            save_offset(offset)

            msg = update.get("message")
            if msg:
                try:
                    handle_message(token, msg)
                    msg_errors = 0   # reset on success
                except Exception as e:
                    msg_errors += 1
                    user = msg.get("from", {}).get("username", "unknown")
                    text = msg.get("text", "")[:50]
                    log.warning(f"Message handler error #{msg_errors} "
                          f"(user={user}, text={text!r}): {e}")
                    send_error_alert(
                        "Message handler crashed",
                        f"user={user} cmd={text!r} err={e}",
                        msg_errors
                    )

            cbq = update.get("callback_query")
            if cbq:
                try:
                    handle_callback(token, cbq)
                    callback_errors = 0   # reset on success
                except Exception as e:
                    callback_errors += 1
                    data = cbq.get("data", "")
                    log.warning(f"Callback error #{callback_errors} "
                          f"(data={data!r}): {e}")
                    send_error_alert(
                        "Callback handler crashed",
                        f"data={data!r} err={e}",
                        callback_errors
                    )

        if not loop:
            break

        time.sleep(1)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Strava Custom Coach Telegram bot")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="Poll once then exit (for cron)")
    mode.add_argument("--loop", action="store_true", help="Long-poll continuously")
    args = parser.parse_args()

    run(loop=args.loop)


if __name__ == "__main__":
    main()