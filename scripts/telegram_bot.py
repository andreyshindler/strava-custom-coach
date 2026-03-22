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
import sys
import time
import urllib.request
import urllib.parse
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime

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
    return cost

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
            "*What's your name?*"
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
    "planxco":   "local_only",
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


def handle_callback(token, callback_query):
    """Handle inline button presses."""
    chat_id  = str(callback_query.get("message", {}).get("chat", {}).get("id", ""))
    data     = callback_query.get("data", "")
    query_id = callback_query.get("id", "")

    # Acknowledge the button press
    tg_api_json(token, "answerCallbackQuery", {"callback_query_id": query_id})

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
        f"  /plan — today's planned workout\n"
        f"  /planxco — today's XCO strength session 💪\n"
        f"  /week — this week's training plan\n"
        f"  /nextweek — next week's plan\n"
        f"  /nextmonth — next 4 weeks\n"
        f"  /fullplan — entire training plan\n"
        f"  /stats — last 7 days summary\n"
        f"  /stats 30 — last 30 days summary (or /stats30)\n"
        f"  /trends — week-by-week trend analysis (30 days)\n"
        f"  /trends 90 — trends for last N days\n"
        f"  /help — this message"
    )


def cmd_coach(args, persona):
    """Show current coach or switch to a new one."""
    if not args:
        lines = [f"*Current coach:* {persona['name']}\n\n*Available coaches:*"]
        for pid, p in PERSONAS.items():
            marker = " ✅" if pid == persona["id"] else ""
            lines.append(f"  `{pid}` — {p['name']}{marker}\n  _{p['tagline']}_")
        lines.append("\nSwitch with: `/coach nino` (or pogi / badger / cannibal)")
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
                # Voice: just first sentence of description
                voice = desc.split('\n')[0]
                return text, voice

    return (
        f"😴 *No gym session today* ({today})\n\n"
        f"Today is a bike or rest day. Use /plan for your cycling session.\n\n"
        f"— {persona['name']}"
    ), None


def cmd_plan(persona):
    """Show today's planned workout from the saved training plan."""
    plan_file = _UDIR / "training_plan.json"
    if not plan_file.exists():
        return (
            f"📋 *No training plan active yet.*\n\n"
            f"Use /newplan to build one — I'll guide you step by step.\n\n"
            f"— {persona['name']}"
        )

    plan  = load_plan_safe()
    today = datetime.today().strftime("%Y-%m-%d")

    for week in plan.get("weekly_plans", []):
        for day in week.get("days", []):
            if day.get("date") == today:
                w = day["name"]
                d = day["description"]
                t = day["tss"]
                dtype = day.get("type", "")
                zone  = day.get("zone", 0)
                if dtype == "gym":
                    z = "💪 Gym"
                    emoji = "🏋️"
                elif zone and int(zone) > 0:
                    z = f"Zone {zone}"
                    emoji = "🚴"
                elif day.get("workout") == "rest":
                    z = "Rest"
                    emoji = "😴"
                else:
                    z = "Ride"
                    emoji = "🚴"
                text = (
                    f"📋 *Today's Workout* ({today})\n\n"
                    f"{emoji} *{w}* — {z}\n"
                    f"Duration: {day.get('duration_min', '?')} min  |  TSS: {t}\n\n"
                    f"_{d}_\n\n"
                    f"— {persona['name']}"
                )
                return text, d

    return f"No workout scheduled for today ({today}) in your current plan.", None


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

    return "Couldn't find the current week in your plan. The plan may have ended."


def send_voice(token, chat_id, text, persona_id="nino"):
    """Generate speech with Piper TTS and send as Telegram voice message."""
    import subprocess
    import os

    model = os.path.expanduser("~/.local/share/piper/en_US-lessac-high.onnx")
    wav_file = "/tmp/coach_voice.wav"

    # Generate WAV with Piper
    proc = subprocess.run(
        ["piper", "--model", model, "--output_file", wav_file],
        input=text.encode(),
        capture_output=True
    )
    if proc.returncode != 0 or not os.path.exists(wav_file):
        # Fallback to espeak if piper fails
        subprocess.run(["espeak", text, "-w", wav_file], capture_output=True)

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

    system = (
        f"You are a cycling coach. You speak exactly like {persona['name']}.\n"
        f"Persona: {persona['tagline']}\n"
        f"Voice: {persona.get('header_quote', '')}\n\n"
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

def cmd_newplan(persona):
    """Start a new plan creation wizard."""
    save_wizard({"step": "goal", "persona": persona["id"]})
    return (
        f"🗓 *New Training Plan — {persona['name']}*\n\n"
        f"Let's build your plan step by step.\n\n"
        f"*STEP 1: What is your primary goal?*\n\n"
        f"1️⃣ Improve FTP — get faster, raise your power threshold\n"
        f"2️⃣ Event prep — train toward a specific race or event\n"
        f"3️⃣ Distance target — build weekly volume\n"
        f"4️⃣ Weight loss — more Zone 2, longer rides\n"
        f"5️⃣ General fitness — balanced all-round plan\n\n"
        f"Reply with a number *1–5*"
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
        try:
            ftp = int(text.strip())
        except ValueError:
            return "Please reply with a number (your FTP in watts, or 0 if unknown)", False
        if ftp == 0:
            ftp = 200
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
        state["step"] = "xco"
        save_wizard(state)
        return (
            f"✅ Duration: *{weeks} weeks*\n\n"
            f"*STEP 4: Include XCO Power Training?*\n\n"
            f"Adds 2 gym sessions/week specifically for cross-country MTB:\n\n"
            f"💪 *Gym:* Max strength, explosive power, core & coordination\n"
            f"🚴 *Bike:* Torque intervals, sprint power, micro-bursts\n\n"
            f"Recommended if you race XCO or want explosive power.\n\n"
            f"Reply *y* for yes or *n* for no"
        ), False

    # ── XCO ───────────────────────────────────────────────────────────────────
    elif step == "xco":
        xco = text.strip().lower() in ("y", "yes")
        state["xco"] = xco
        goal = state.get("goal")

        if goal == "event":
            state["step"] = "event_name"
            save_wizard(state)
            return (
                f"✅ XCO training: *{'Yes' if xco else 'No'}*\n\n"
                f"*STEP 5: Event name*\n\n"
                f"What is the name of your target event?\n"
                f"_(e.g. 'XCO Regional Champs', 'Cape Epic', 'Gran Fondo')_"
            ), False
        elif goal == "ftp":
            state["step"] = "target_ftp"
            save_wizard(state)
            ftp = state.get("ftp", 220)
            return (
                f"✅ XCO training: *{'Yes' if xco else 'No'}*\n\n"
                f"*STEP 5: Target FTP*\n\n"
                f"Current FTP: *{ftp}W*\n"
                f"Realistic gain in {state.get('weeks',8)} weeks: +10 to +30W\n\n"
                f"What FTP do you want to reach?\n"
                f"_(reply with target watts, e.g. {ftp+20})_"
            ), False
        elif goal == "distance":
            state["step"] = "target_km"
            save_wizard(state)
            return (
                f"✅ XCO training: *{'Yes' if xco else 'No'}*\n\n"
                f"*STEP 5: Weekly distance target*\n\n"
                f"• 100 km/week — recreational\n"
                f"• 150 km/week — enthusiast\n"
                f"• 200 km/week — dedicated\n\n"
                f"Reply with your target in km"
            ), False
        elif goal == "weight-loss":
            state["step"] = "target_kg"
            save_wizard(state)
            return (
                f"✅ XCO training: *{'Yes' if xco else 'No'}*\n\n"
                f"*STEP 5: Target weight*\n\n"
                f"What is your target body weight in kg?\n"
                f"_(reply with number, or 0 to skip)_"
            ), False
        else:
            # General fitness — go straight to confirm
            state["step"] = "confirm"
            save_wizard(state)
            return build_confirm_message(state), False

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
        state["step"] = "confirm"
        save_wizard(state)
        return build_confirm_message(state), False

    # ── TARGET FTP ────────────────────────────────────────────────────────────
    elif step == "target_ftp":
        try:
            state["target_ftp"] = int(text.strip())
        except ValueError:
            return "Please reply with a number (target FTP in watts)", False
        state["step"] = "confirm"
        save_wizard(state)
        return build_confirm_message(state), False

    # ── TARGET KM ─────────────────────────────────────────────────────────────
    elif step == "target_km":
        try:
            state["target_km"] = int(text.strip())
        except ValueError:
            return "Please reply with a number (km per week)", False
        state["step"] = "confirm"
        save_wizard(state)
        return build_confirm_message(state), False

    # ── TARGET KG ─────────────────────────────────────────────────────────────
    elif step == "target_kg":
        try:
            state["target_kg"] = float(text.strip())
        except ValueError:
            return "Please reply with a number (target kg, or 0 to skip)", False
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
        lines.append(f"📈 Target FTP: *{state['target_ftp']}W*")
    if state.get("target_km"):
        lines.append(f"🛣 Distance target: *{state['target_km']} km/week*")
    if state.get("target_kg"):
        lines.append(f"⚖️ Target weight: *{state['target_kg']} kg*")
    lines.append("\nReply *y* to build this plan or *n* to cancel")
    return "\n".join(lines)


def generate_plan_from_wizard(state, persona):
    """Build and save the plan from wizard state."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from training_plan import build_plan, build_xco_plan

    goal   = state.get("goal", "general")
    ftp    = state.get("ftp", 220)
    weeks  = state.get("weeks", 8)
    xco    = state.get("xco", False)

    kwargs = dict(
        goal=goal, weeks=weeks, ftp=ftp, persona=persona,
        event_name=state.get("event_name"),
        event_date=state.get("event_date"),
        target_ftp=state.get("target_ftp"),
        target_km=state.get("target_km"),
        target_kg=state.get("target_kg"),
    )

    try:
        if xco:
            plan = build_xco_plan(**{k: v for k, v in kwargs.items() if k not in ("target_km","target_kg")})
        else:
            plan = build_plan(**kwargs)

        _UDIR.mkdir(parents=True, exist_ok=True)
        (_UDIR / "training_plan.json").write_text(json.dumps(plan, indent=2))
        clear_wizard()

        # Show first week preview
        first_week = plan["weekly_plans"][0] if plan.get("weekly_plans") else {}
        lines = [
            f"✅ *Plan created and saved!*\n",
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

        lines.append(f"\nUse /plan for today's session and /week for the full week.")
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
    stable_block = (
        f"You are {persona['name']}, a world-class cycling coach. "
        f"{persona.get('tagline', '')} "
        f"Philosophy: {persona.get('beliefs', ['train smart, recover well'])[0] if persona.get('beliefs') else 'train consistently'}. "
        f"Speak in first person, in your authentic voice. Be direct, motivating, specific. "
        f"Reply in under 120 words. No bullet points — talk like a coach, not a listicle."
    )
    dynamic_block = f"Athlete FTP: {ftp}W\n{strava_ctx}{plan_ctx}".strip()

    payload = json.dumps({
        "model": "claude-sonnet-4-5",
        "max_tokens": 250,
        "system": [
            {
                "type": "text",
                "text": stable_block,
                "cache_control": {"type": "ephemeral"},
            },
            {
                "type": "text",
                "text": dynamic_block,
            },
        ],
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
        return (
            "*Admin commands:*\n"
            "`/admin quota <id> <$>` — set demo allowance\n"
            "`/admin quota <id>` — check a user's quota\n"
            "`/admin quotas` — list all users with quotas"
        )

    sub = args[0].lower()

    if sub == "quotas":
        users_dir = CONFIG_DIR / "users"
        if not users_dir.exists():
            return "No users directory found."
        rows = []
        for udir in sorted(users_dir.iterdir()):
            f = udir / "demo_quota.json"
            if f.exists():
                try:
                    q = json.loads(f.read_text())
                    allowance = q.get("allowance_usd")
                    spent     = q.get("spent_usd", 0.0)
                    if allowance is None:
                        rows.append(f"`{udir.name}` — unlimited (spent ${spent:.4f})")
                    else:
                        rows.append(f"`{udir.name}` — ${spent:.4f} / ${allowance:.2f}")
                except Exception:
                    pass
        return ("*Users with quotas:*\n" + "\n".join(rows)) if rows else "No quotas set."

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
        if new_allowance is None:
            return f"✅ User `{target_id}` quota removed — unlimited access."
        return f"✅ User `{target_id}` demo allowance set to ${new_allowance:.2f}."

    return f"Unknown admin sub-command `{sub}`. Try `/admin` for help."


def _delete_confirm_file():
    return _UDIR / "pending_delete.txt"


def cmd_deleteplan(persona):
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

    # Save pending state
    _UDIR.mkdir(parents=True, exist_ok=True)
    _delete_confirm_file().write_text("pending")

    return (
        f"🗑 *Delete Training Plan?*\n\n"
        f"Current plan:\n"
        f"  🎯 Goal: *{goal}{event}*\n"
        f"  📅 Duration: *{weeks} weeks* (started {start})\n"
        f"  💪 {xco}\n\n"
        f"⚠️ This cannot be undone.\n\n"
        f"Reply *yes* to confirm or *no* to cancel."
    ), None


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

    # ── Per-user dir ──────────────────────────────────────────────────────────
    _UDIR = get_user_dir(chat_id)

    # ── Docker per-user guard (STRAVA_TELEGRAM_CHAT_ID set) ───────────────────
    allowed_chat_id = get_chat_id()
    if allowed_chat_id and chat_id != allowed_chat_id:
        log.warning(f"Rejected message from unknown chat_id={chat_id}")
        return

    # ── Onboarding: no tokens yet → run setup wizard ──────────────────────────
    if not (_UDIR / "tokens.json").exists():
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

    # ── Per-user rate limiting ────────────────────────────────────────────────
    # Determine the command key for rate limiting before full dispatch.
    # Plain-text messages (AI chat) use the "_chat" key.
    if text.startswith("/"):
        _rate_cmd = text.lstrip("/").split()[0].lower().split("@")[0]
    else:
        _rate_cmd = "_chat"

    _allowed, _wait = check_rate_limit(chat_id, _rate_cmd)
    if not _allowed:
        group = CMD_GROUPS.get(_rate_cmd, "ai_and_strava")
        send_message(token, chat_id,
            f"⏳ *Slow down!*\n\n"
            f"The `/{_rate_cmd}` command is rate limited. "
            f"Please wait *{_wait}s* before trying again.\n\n"
            f"_This keeps the bot running smoothly for everyone._"
        )
        return

    # Record this command use (before execution so re-entrant calls are also limited)
    record_command_use(chat_id, _rate_cmd)

    # ── Demo quota check (AI commands only) ───────────────────────────────────
    _ai_group = CMD_GROUPS.get(_rate_cmd, "free")
    if _ai_group in ("ai_and_strava", "ai_only"):
        _quota_ok, _spent, _allowance = check_demo_quota(_UDIR)
        if not _quota_ok:
            send_message(token, chat_id,
                f"🎟 *Demo limit reached*\n\n"
                f"You've used ${_spent:.4f} of your ${_allowance:.2f} demo credit.\n\n"
                f"Contact the admin to upgrade your account and unlock full access."
            )
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
            return

    # ── Check if awaiting delete confirmation ─────────────────────────────────
    if _delete_confirm_file().exists() and not text.startswith("/"):
        if text.strip().lower() in ("yes", "y"):
            plan_file = _UDIR / "training_plan.json"
            if plan_file.exists():
                plan_file.unlink()
            _delete_confirm_file().unlink()
            send_message(token, chat_id,
                f"✅ *Training plan deleted.*\n\n"
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

    if cmd in ("start", "setup"):
        reply = cmd_help(persona)
    elif cmd == "help":
        reply = cmd_help(persona)
    elif cmd == "coach":
        reply = cmd_coach(args, persona)
        persona = load_active_persona(_UDIR / "config.json")
    elif cmd == "ride":
        result = cmd_ride(persona)
        reply, voice_text = result if isinstance(result, tuple) else (result, None)
    elif cmd == "voice":
        reply = cmd_voice(persona, chat_id, token)
    elif cmd == "plan":
        if args and args[0].lower() == "xco":
            result = cmd_plan_xco(persona)
        else:
            result = cmd_plan(persona)
        reply, voice_text = result if isinstance(result, tuple) else (result, None)
    elif cmd == "planxco":
        result = cmd_plan_xco(persona)
        reply, voice_text = result if isinstance(result, tuple) else (result, None)
    elif cmd == "newplan":
        with _wizard_lock(_UDIR):
            clear_wizard()
            reply = cmd_newplan(persona)
    elif cmd == "deleteplan":
        result = cmd_deleteplan(persona)
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
            reply = cmd_stats(persona, days=7)
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