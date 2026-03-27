# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Git Workflow — Required

**After completing any task or logical unit of work, always commit and push to GitHub immediately.**
- Use `git add <specific files>` (never `git add -A` or `git add .`)
- Write a clear, concise commit message describing *what* and *why*
- Run `git push` after every commit — never leave committed work un-pushed
- Always syntax-check Python files before committing: `python -m py_compile <file> && echo "OK"`
- Never use `--no-verify`, `--amend` on published commits, or force-push

This ensures work is never lost between sessions.

## Project Overview

A multi-persona AI cycling coach that integrates Strava ride data with Claude AI coaching and Telegram delivery. Supports single-user mode (standalone scripts) and multi-tenant mode (per-user config dirs under `~/.config/strava/users/{chat_id}/`).

## Commands

### Running the bot
```bash
python3 scripts/telegram_bot.py --loop       # Continuous long-polling
python3 scripts/telegram_bot.py --once       # Single poll and exit
python3 scripts/telegram_bot.py --notify     # Send nightly prep reminders (run via cron at 20:00)
```

### Running analysis scripts
```bash
python3 scripts/analyze_ride.py <ride_id> [--persona badger]
python3 scripts/analyze_rides.py --days 90 --ftp 240
python3 scripts/get_latest_ride.py
python3 scripts/training_plan.py --interactive
python3 scripts/training_plan.py --goal ftp --weeks 12 --ftp 220
```

### Web onboarding service
```bash
cd onboarding && python3 app.py              # Dev (auto-reload)
gunicorn -w 2 -b 0.0.0.0:5000 app:app       # Production
```

### Webhook server
```bash
python3 scripts/webhook.py serve --port 8421
python3 scripts/webhook.py subscribe --url https://yourhost.com/webhook
```

### Docker
```bash
docker build -t strava-coach:latest .
docker-compose up -d
docker-compose logs -f bot
```

### Validation
```bash
python3 scripts/healthcheck.py              # Validate all system connectivity
python3 -m py_compile scripts/*.py onboarding/app.py  # Syntax check
```

## Architecture

### Component Map

- **[scripts/telegram_bot.py](scripts/telegram_bot.py)** — Core engine (~3800 lines). Handles all Telegram commands and inline button callbacks, Claude AI integration, Whisper voice transcription, per-user rate limiting, demo quota enforcement, query history logging to SQLite, nightly notifications, and admin commands. Every user interaction (commands, button presses, text input) is logged to `history.db`.
- **[scripts/personas.py](scripts/personas.py)** — Coaching persona definitions for Nino, Pogi, Badger, and Cannibal. Each has unique coaching voice, zone feedback, and training philosophy injected into all AI prompts.
- **[scripts/training_plan.py](scripts/training_plan.py)** — TSS-based periodized plan generator. Supports 7 goal types (including `strava_auto` which analyses ride history), 8 workout types, 3-build/1-recovery week cycles, optional Claude-generated custom plans, and `analyse_rides_for_plan()` for Strava data-driven goal suggestion.
- **[scripts/strava_api.py](scripts/strava_api.py)** — Strava OAuth 2.0 (auto-refresh), activity fetching, and metric extraction.
- **[scripts/strava_cache.py](scripts/strava_cache.py)** — Local JSON cache of ride data (50-activity batches) to reduce API calls.
- **[scripts/webhook.py](scripts/webhook.py)** — Strava webhook server: receives new ride events, auto-analyzes, and sends Telegram summary.
- **[onboarding/app.py](onboarding/app.py)** — Flask web service. Handles Strava OAuth for new users, nonce-based Telegram-linked onboarding (`/tg/callback`), admin dashboard (`/admin`), per-user query history viewer (`/admin/<chat_id>`), quota management, and Strava webhook events.

### Telegram Commands

| Command | Description |
|---|---|
| `/start`, `/help` | Show command list |
| `/coach [name]` | Show or switch active persona |
| `/ride` | Analyze latest Strava ride |
| `/voice` | Hear coach speak (TTS via Piper/espeak) |
| `/today`, `/plan` | Today's planned workout |
| `/tomorrow` | Tomorrow's planned workout |
| `/week` | This week's training plan |
| `/nextweek` | Next week's plan |
| `/nextmonth` | Next 4 weeks |
| `/fullplan` | Entire training plan |
| `/newplan` | Create a new plan (7-step wizard) |
| `/deleteplan` | Archive current plan |
| `/stats [days]` | Ride summary (default 7 days, inline period picker) |
| `/trends [days]` | Week-by-week trend analysis |
| `/quota` | Check AI usage and allowance |
| `/notify` | Toggle post-ride notifications |
| `/notifyplan` | Toggle next-day training reminders (20:00 nightly) |
| `/leave` | Revoke Strava access and delete data |
| `/contact` | Get support contact |
| `/admin` | Admin panel (admin only) |

### Admin Features (Telegram)

- `/admin` — inline panel with Stats, Users, Quotas, List, Set quota, Delete, Web panel
- `/admin stats` — global usage summary
- `/admin users` — user count and Strava auth status
- `/admin quotas` — per-user quota bars
- `/admin list` — full user list with quota/spend
- `/admin quota <chat_id> [amount|+amount|off]` — set or top up allowance
- `/admin delete <chat_id>` — delete user (with inline confirm)
- `/admin invite <chat_id>` — generate one-time Strava OAuth link for athlete onboarding without Telegram wizard

### Admin Web Panel (`/admin`)

- User table with Strava status, FTP, quota bars, query counts, total cost, last active
- Per-user query history at `/admin/<chat_id>` (paginated, filterable, browser local time)
- Quota Set + +Add buttons per user row
- Delete button per user row
- Filter by: name/ID, Strava status, quota status, notify status, activity recency

### Data Flow: Ride → Notification
```
Strava ride upload → webhook.py or onboarding/app.py (HMAC-validated POST)
  → strava_api.py (fetch + cache) → persona zone feedback
  → Telegram Bot API (message)
```

### Data Flow: /newplan Command
```
Telegram /newplan → 7-step wizard (goal, weeks, FTP, XCO?, classic/AI, confirm)
  → goal 7 (strava_auto): analyse_rides_for_plan() → pre-fill wizard from ride data
  → optional Claude API (AI-generated plan) → training_plan.py (save JSON)
  → Telegram (plan summary + confirm buttons)
```

### Data Flow: Athlete Onboarding via Invite Link
```
Admin: /admin invite <chat_id>
  → nonce written to CONFIG_DIR/nonces/{nonce}.json
  → admin shares [Authorize Strava](url) link with athlete
  → athlete authorizes on strava.com
  → onboarding/app.py /tg/callback: exchange code, write config.json + tokens.json
  → demo_quota set to $0, admin notified via Telegram
  → admin: /admin quota <chat_id> <amount> to activate
```

### Multi-Tenant Model
- `onboarding/app.py` handles new user onboarding (web flow or Telegram invite link)
- Per-user data lives in `~/.config/strava/users/{chat_id}/`
- `telegram_bot.py` runs in multi-tenant mode reading from per-user dirs

### Key State Files
```
~/.config/strava/
├── config.json           # Strava credentials, FTP, weight, active persona
├── tokens.json           # OAuth tokens (auto-refreshed)
├── nonces/               # One-time OAuth nonces for Telegram-linked onboarding
├── users/{chat_id}/      # Per-user data
│   ├── config.json       # Per-user config (same structure)
│   ├── tokens.json       # Per-user OAuth tokens
│   ├── training_plan.json         # Active training plan
│   ├── training_plan_vN.json      # Archived plans
│   ├── demo_quota.json            # {allowance_usd, spent_usd}
│   └── history.db                 # SQLite: id, timestamp (UTC+Z), query, tokens_used, cost_usd, response
~/.cache/strava/
└── activities.json       # Local cache of Strava activities
```

### History Logging

Every user interaction is logged to `history.db` via `log_query()`:
- All slash commands (response text logged)
- All inline button presses (logged as `[action_name]`)
- Plain text AI chat (tokens + cost logged)
- `/newplan` wizard steps (each button press logged as `[wizard:callback_data]`)
- `/voice` (logged with filename + file size in KB)
- Admin actions (logged to admin's own history.db)
- Timestamps stored as UTC ISO 8601 with `Z` suffix; browser JS converts to local time in the admin UI

## Environment Variables

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...
STRAVA_TELEGRAM_BOT_TOKEN=123:ABC...
FLASK_SECRET=<32-byte hex>           # Web service only

# Strava OAuth (can also be in config.json)
STRAVA_CLIENT_ID=123456
STRAVA_CLIENT_SECRET=abc123...

# Optional
STRAVA_TELEGRAM_CHAT_ID=987654       # Single-user mode
ADMIN_CHAT_ID=987654                 # Admin Telegram ID (receives new-user notifications)
PUBLIC_URL=https://yourserver.com    # OAuth redirect base URL
WEB_URL=https://yourserver.com       # Web admin panel URL (shown in /admin web button)
ADMIN_USER=admin                     # Web admin panel HTTP Basic Auth username
ADMIN_PASSWORD=yourpass              # Web admin panel HTTP Basic Auth password
WEBHOOK_VERIFY_TOKEN=strava-coach
CODE_DIR=/opt/strava-coach/code      # Multi-tenant: host path to scripts
USERS_BASE_DIR=/data/users           # Multi-tenant: base dir for user configs
```

## Key Design Decisions

- **Personas are injected at prompt time** — `personas.py` is not LLM-called; it's a static library of coaching voice text injected into Claude system prompts.
- **Cost tracking is per-message** — `_ai_usage` accumulates tokens/cost during each `handle_message` call; `demo_quota.json` persists the running total per user.
- **Quota notifications** — users receive a `█░` percentage bar message when their allowance is activated, topped up, or decreased. Dollar amounts are never shown to users.
- **Nonce-based onboarding** — `/admin invite` creates a `nonces/{nonce}.json` file; `/tg/callback` consumes it one-time. No session state needed.
- **UTC timestamps** — all `history.db` timestamps are stored as `YYYY-MM-DDTHH:MM:SSZ`. The admin web UI converts to browser local time via JS (`new Date(datetime)` on `<time class="localtime">` elements).
- **No test suite** — validation is done via `healthcheck.py` and `py_compile`.
- **Admin access** uses both Telegram chat ID (`ADMIN_CHAT_ID`) and HTTP Basic Auth (for the web admin panel at `/admin`). Admin commands are also logged to the admin's own `history.db`.
- **`pyrightconfig.json`** at project root adds `scripts/` to Pylance's `extraPaths` so imports like `strava_api` resolve without errors.
