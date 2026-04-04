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

A multi-persona AI cycling coach that integrates Strava ride data with Claude AI coaching and Telegram delivery. Version 2.0.0. Supports single-user mode (standalone scripts) and multi-tenant mode (per-user config dirs under `~/.config/strava/users/{chat_id}/`).

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
python3 scripts/training_plan.py --persona cannibal --goal event --event-name "Gran Fondo 120km" --event-date 2026-06-15
python3 scripts/training_plan.py --list-personas
python3 scripts/training_plan.py --show
python3 scripts/set_persona.py              # interactive chooser
python3 scripts/set_persona.py pogi         # set directly by id
python3 scripts/set_persona.py --list       # list all personas
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
python3 scripts/webhook.py list
python3 scripts/webhook.py delete <subscription_id>
```

### Docker
```bash
docker build -t strava-coach:latest .
docker-compose up -d
docker-compose logs -f bot
```

### Validation
```bash
python3 scripts/healthcheck.py              # Validate bot + containers; auto-restarts on failure
python3 scripts/healthcheck.py --dry-run    # Check only, no restarts or alerts
python3 scripts/healthcheck.py --install-cron  # Install cron job to run every 5 minutes
python3 -m py_compile scripts/*.py onboarding/app.py  # Syntax check
```

### One-time setup
```bash
./scripts/setup.sh                           # Interactive initial configuration
python3 scripts/complete_auth.py YOUR_CODE   # Complete Strava OAuth handshake
```

## Architecture

### Component Map

- **[scripts/telegram_bot.py](scripts/telegram_bot.py)** — Core engine (~3851 lines). Handles all Telegram commands and inline button callbacks, Claude AI integration (chat, stats analysis, trends), Whisper voice transcription, per-user rate limiting (5 groups: `ai_and_strava`, `ai_only`, `strava_only`, `local_only`, `free`), demo quota enforcement, query history logging to SQLite, nightly notifications, and admin commands. Every user interaction (commands, button presses, text input) is logged to `history.db`. Uses `fcntl` file locking for wizard state in multi-process scenarios.
- **[scripts/personas.py](scripts/personas.py)** — Coaching persona definitions (~1030 lines) for Nino, Pogi, Badger, and Cannibal. Each has unique coaching voice, zone feedback, workout descriptions, and training philosophy injected into all AI prompts.
- **[scripts/training_plan.py](scripts/training_plan.py)** — TSS-based periodized plan generator (~1441 lines). Supports 7 goal types (including `strava_auto` which analyses ride history), 8 workout types, 3-build/1-recovery week cycles, XCO-specific plans, optional Claude-generated custom plans (uses `claude-haiku-4-5-20251001`), and `analyse_rides_for_plan()` for Strava data-driven goal suggestion.
- **[scripts/strava_api.py](scripts/strava_api.py)** — Strava OAuth 2.0 (auto-refresh), activity fetching, and metric extraction. Provides `urlopen_with_retry()` used across the codebase.
- **[scripts/strava_cache.py](scripts/strava_cache.py)** — Local JSON cache of ride data (stores up to 500 activities) at `~/.cache/strava/activities.json` to reduce API calls.
- **[scripts/webhook.py](scripts/webhook.py)** — Strava webhook server (~405 lines): receives new ride events, auto-analyzes, and sends Telegram summary. Also manages webhook subscriptions (subscribe/list/delete).
- **[scripts/healthcheck.py](scripts/healthcheck.py)** — Bot process + Docker container health monitor. Checks native VPS bot and all `strava-coach-*` containers. Auto-restarts on failure and sends Telegram alerts to both owner and affected user.
- **[onboarding/app.py](onboarding/app.py)** — Flask web service (~913 lines). Handles Strava OAuth for new users, nonce-based Telegram-linked onboarding (`/tg/callback`), admin dashboard (`/admin`), per-user query history viewer (`/admin/<chat_id>` and `/admin/history/<chat_id>`), quota management, and Strava webhook events. Spawns per-user Docker containers via a least-privilege `dockerproxy` service.

### Coaching Personas

| ID | Persona | Description |
|---|---|---|
| `nino` | Nino Schurter | Default. Calm, precise, Swiss directness. 10x XCO World Champion. |
| `pogi` | Tadej Pogačar | Joyful, electric, relentlessly positive. 4x Tour de France. |
| `badger` | Bernard Hinault | Fierce, blunt, uncompromising. 5x Tour de France. |
| `cannibal` | Eddy Merckx | Authoritative, historically grounded. 525 career wins. |

Pass `--persona <id>` to any script for a one-off override without changing the saved setting.

### Claude AI Models Used

| Context | Model | Location |
|---|---|---|
| Free-text chat messages | `claude-sonnet-4-5` (with prompt caching) | `telegram_bot.py:cmd_chat()` |
| `/trends` analysis (stats) | `claude-sonnet-4-20250514` | `telegram_bot.py:cmd_trends()` |
| AI-generated training plans (`/newplan` AI mode) | `claude-haiku-4-5-20251001` | `telegram_bot.py:_generate_ai_plan()` |

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
| `/trends [days]` | Week-by-week trend analysis (uses Claude AI) |
| `/quota` | Check AI usage and allowance |
| `/notify` | Toggle post-ride notifications |
| `/notifyplan` | Toggle next-day training reminders (20:00 nightly) |
| `/leave` | Revoke Strava access and delete data |
| `/contact` | Get support contact |
| `/admin` | Admin panel (admin only) |

### Rate Limiting

Per-user, in-memory rate limits (reset on process restart):

| Group | Cooldown | Commands |
|---|---|---|
| `ai_and_strava` | 60s | `/trends` |
| `ai_only` | 30s | plain-text chat |
| `strava_only` | 15s | `/ride`, `/stats`, `/voice`, `/fullplan` |
| `local_only` | 5s | `/plan`, `/today`, `/tomorrow`, `/week`, `/nextweek`, `/nextmonth`, `/newplan` |
| `free` | 0s | `/help`, `/coach`, `/deleteplan`, `/start`, `/quota`, `/notify`, `/leave`, `/admin` |

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
- Per-user query history at `/admin/<chat_id>` and `/admin/history/<chat_id>` (paginated, filterable, browser local time)
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
  → optional Claude API (claude-haiku-4-5-20251001, AI-generated plan) → training_plan.py (save JSON)
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

### Docker Architecture

The `docker-compose.yml` defines three services:
- **`bot`** — runs `telegram_bot.py --loop` (the main bot process)
- **`web`** — runs Flask onboarding app via gunicorn on port 5000
- **`dockerproxy`** (`tecnativa/docker-socket-proxy`) — least-privilege Docker API proxy; the web service spawns per-user containers through this instead of the raw Docker socket

### Multi-Tenant Model
- `onboarding/app.py` handles new user onboarding (web flow or Telegram invite link)
- Per-user data lives in `~/.config/strava/users/{chat_id}/`
- `telegram_bot.py` runs in multi-tenant mode reading from per-user dirs
- In Docker single-user mode (`STRAVA_TELEGRAM_CHAT_ID` set), the mounted dir IS the user config dir

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
│   ├── wizard.lock                # fcntl lock file for /newplan wizard
│   └── history.db                 # SQLite: id, timestamp (UTC+Z), query, tokens_used, cost_usd, response, prompt (AI chat only)
~/.cache/strava/
├── activities.json       # Local cache of Strava activities (up to 500)
└── last_sync.txt         # Timestamp of last cache update
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
- `prompt` column stores the full system prompt + context + user message for AI chat rows; `NULL` for commands/buttons. Visible in the admin history page.

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
STRAVA_TELEGRAM_CHAT_ID=987654       # Single-user / Docker per-user mode
ADMIN_CHAT_ID=987654                 # Admin Telegram ID (receives new-user notifications)
PUBLIC_URL=https://yourserver.com    # OAuth redirect base URL
WEB_URL=https://yourserver.com       # Web admin panel URL (shown in /admin web button)
ADMIN_USER=admin                     # Web admin panel HTTP Basic Auth username
ADMIN_PASSWORD=yourpass              # Web admin panel HTTP Basic Auth password
WEBHOOK_VERIFY_TOKEN=strava-coach
CODE_DIR=/opt/strava-coach/code      # Multi-tenant: host path to scripts (for Docker spawning)
USERS_BASE_DIR=/data/users           # Multi-tenant: base dir for user configs
DOCKER_HOST=tcp://dockerproxy:2375   # Set automatically in docker-compose for the web service
```

## Key Design Decisions

- **Personas are injected at prompt time** — `personas.py` is not LLM-called; it's a static library of coaching voice text injected into Claude system prompts.
- **Cost tracking is per-message** — `_ai_usage` accumulates tokens/cost during each `handle_message` call; `demo_quota.json` persists the running total per user.
- **Quota notifications** — users receive a `█░` percentage bar message when their allowance is activated, topped up, or decreased. Dollar amounts are never shown to users.
- **Nonce-based onboarding** — `/admin invite` creates a `nonces/{nonce}.json` file; `/tg/callback` consumes it one-time. No session state needed.
- **UTC timestamps** — all `history.db` timestamps are stored as `YYYY-MM-DDTHH:MM:SSZ`. The admin web UI converts to browser local time via JS (`new Date(datetime)` on `<time class="localtime">` elements).
- **No test suite** — validation is done via `healthcheck.py` and `py_compile`.
- **Admin access** uses both Telegram chat ID (`ADMIN_CHAT_ID`) and HTTP Basic Auth (for the web admin panel at `/admin`). Admin commands are also logged to the admin's own `history.db`.
- **Rate limits are in-memory only** — stored in `_rate_limit_store` (a `defaultdict`). Reset when the `--once` loop process restarts, which is acceptable since the bot polls every 5 seconds.
- **`strava_api.urlopen_with_retry()`** is used throughout the codebase for all HTTP calls (Strava, Telegram, Anthropic) — provides 3-retry exponential backoff.
- **Wizard locking** — `/newplan` wizard state uses `fcntl.flock()` exclusive lock (`wizard.lock` file per user dir) to prevent race conditions in multi-process environments.
- **Activity cache limit** — `strava_cache.py` keeps up to 500 activities in `activities.json`; older entries are dropped.
- **AI plan generation** uses `claude-haiku-4-5-20251001` (fast, cheap) for structured JSON plan output; free-text chat uses `claude-sonnet-4-5` with prompt caching for quality.
- **No `pyrightconfig.json`** — imports like `from personas import ...` work because `PYTHONPATH=/app/scripts` is set in Docker and `sys.path.insert(0, os.path.dirname(__file__))` is used in scripts.
