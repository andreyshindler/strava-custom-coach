strava-custom-coach v2.1
========================

Multi-persona AI cycling coach that integrates Strava ride data with
Claude AI coaching and Telegram delivery. Supports single-user mode
(standalone scripts) and multi-tenant mode (per-user config dirs).

Four coaching voices: Nino Schurter (default), Tadej Pogačar, Bernard
Hinault, Eddy Merckx.

QUICK START (Single User)
--------------------------
1. Run setup:
   ./scripts/setup.sh

2. Complete OAuth authorization:
   python3 scripts/complete_auth.py YOUR_CODE_HERE

3. Choose your coach (optional, default is Nino):
   python3 scripts/set_persona.py

4. Start the bot:
   python3 scripts/telegram_bot.py --loop

5. (Optional) Healthcheck cron — restarts bot if it goes silent:
   python3 scripts/healthcheck.py --install-cron

DOCKER (Recommended for Production)
-------------------------------------
   docker-compose up -d
   docker-compose logs -f bot

  Requires .env with: STRAVA_TELEGRAM_BOT_TOKEN, ANTHROPIC_API_KEY,
  STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET, FLASK_SECRET, PUBLIC_URL,
  ADMIN_CHAT_ID, ADMIN_USER, ADMIN_PASSWORD

COACHING PERSONAS
-----------------
  nino     — Nino Schurter. Calm, precise. 10x XCO World Champion. (default)
  pogi     — Tadej Pogačar. Joyful, electric. 4x Tour de France.
  badger   — Bernard Hinault. Fierce, blunt. 5x Tour de France.
  cannibal — Eddy Merckx. Authoritative. 525 career wins.

  python3 scripts/set_persona.py              # interactive chooser
  python3 scripts/set_persona.py pogi         # set directly
  python3 scripts/set_persona.py --list       # list all
  python3 scripts/analyze_ride.py <id> --persona badger  # one-off override

SCRIPTS
-------
  setup.sh                  — First-time Strava API setup
  complete_auth.py          — Finish OAuth flow
  set_persona.py            — Choose coaching persona
  get_latest_ride.py        — Show most recent ride
  analyze_ride.py <id>      — Deep-analyze a specific ride
  analyze_rides.py          — Trend analysis across recent rides
  training_plan.py          — Generate training plans (interactive or CLI)
  telegram_bot.py           — Telegram bot (--once / --loop / --notify)
  webhook.py                — Strava webhook server (serve/subscribe/list/delete)
  healthcheck.py            — Bot + Docker container health monitor
  auto_analyze_new_rides.sh — Cron-compatible monitor with Telegram
  monitor_rides.sh          — Interactive background monitor

TRAINING PLAN USAGE
--------------------
  python3 scripts/training_plan.py --interactive
  python3 scripts/training_plan.py --goal ftp --weeks 12 --ftp 220
  python3 scripts/training_plan.py --goal event \
      --event-name "Gran Fondo 120km" --event-date 2026-06-15
  python3 scripts/training_plan.py --show
  python3 scripts/training_plan.py --list-personas

TRAINING PLAN GOALS
-------------------
  ftp          — Improve FTP (power output)
  event        — Prepare for a specific race or gran fondo
  distance     — Hit a weekly distance target
  weight-loss  — Weight loss + base fitness
  general      — General fitness maintenance
  xco          — XCO-specific periodized plan
  strava_auto  — Auto-detect goal from your ride history

TELEGRAM BOT COMMANDS
---------------------
  /coach                             — Show current coach + list all
  /coach nino|pogi|badger|cannibal   — Switch coach persona
  /ride                              — Analyze latest Strava ride
  /voice                             — Hear your coach speak (TTS)
  /today  /plan                      — Today's planned workout
  /tomorrow                          — Tomorrow's planned workout
  /week                              — This week's full schedule
  /nextweek                          — Next week's schedule
  /nextmonth                         — Next 4 weeks overview
  /fullplan                          — Entire training plan
  /newplan                           — Create a training plan (7-step wizard)
  /deleteplan                        — Archive current training plan
  /stats                             — Last 7 days summary
  /stats 30                          — Last N days summary
  /trends                            — Week-by-week AI trend analysis
  /quota                             — Check AI usage and allowance
  /notify                            — Toggle post-ride notifications
  /notifyplan                        — Toggle next-day training reminders
  /leave                             — Revoke Strava access and delete data
  /contact                           — Get support contact
  /help                              — All commands

  Plain text message                 — AI coaching chat (Claude)
  Voice note                         — Transcribed via Whisper → AI coaching chat

  # Run bot continuously
  python3 scripts/telegram_bot.py --loop

  # Run once (for cron every 5 min)
  */5 * * * * python3 /path/to/scripts/telegram_bot.py --once

  # Send nightly prep reminders (run at 20:00 via cron)
  0 20 * * * python3 /path/to/scripts/telegram_bot.py --notify

WEBHOOK SERVER
--------------
  python3 scripts/webhook.py serve --port 8421
  python3 scripts/webhook.py subscribe --url https://yourserver.com/webhook
  python3 scripts/webhook.py list
  python3 scripts/webhook.py delete <subscription_id>

WEB ONBOARDING SERVICE
-----------------------
  cd onboarding && python3 app.py              # dev
  gunicorn -w 2 -b 0.0.0.0:5000 app:app       # production

  Routes:
    /              — Onboarding landing page
    /strava/callback — OAuth callback
    /tg/callback   — Telegram invite link callback (nonce-based)
    /admin         — Admin dashboard (HTTP Basic Auth)
    /admin/<id>    — Per-user query history

HEALTHCHECK
-----------
  python3 scripts/healthcheck.py              # check + auto-restart on failure
  python3 scripts/healthcheck.py --dry-run    # check only, no restarts
  python3 scripts/healthcheck.py --install-cron  # add to crontab (every 5 min)

ENVIRONMENT VARIABLES
---------------------
  # Required
  ANTHROPIC_API_KEY          — Claude API key
  STRAVA_TELEGRAM_BOT_TOKEN  — Telegram bot token
  FLASK_SECRET               — Web service session secret (32-byte hex)

  # Strava OAuth (or set in config.json)
  STRAVA_CLIENT_ID
  STRAVA_CLIENT_SECRET

  # Optional
  STRAVA_TELEGRAM_CHAT_ID    — Single-user / Docker per-user mode
  ADMIN_CHAT_ID              — Admin Telegram ID
  PUBLIC_URL                 — OAuth redirect base URL
  WEB_URL                    — Web admin panel URL
  ADMIN_USER                 — Web admin HTTP Basic Auth username
  ADMIN_PASSWORD             — Web admin HTTP Basic Auth password
  WEBHOOK_VERIFY_TOKEN       — Strava webhook verify token (default: strava-coach)
  CODE_DIR                   — Multi-tenant: host path to scripts
  USERS_BASE_DIR             — Multi-tenant: base dir for user configs

CONFIG FILES
------------
  ~/.config/strava/config.json              — Settings and credentials
  ~/.config/strava/tokens.json              — Strava OAuth tokens (auto-managed)
  ~/.config/strava/users/{chat_id}/         — Per-user data (multi-tenant)
    config.json                             — Per-user config
    tokens.json                             — Per-user OAuth tokens
    training_plan.json                      — Active training plan
    demo_quota.json                         — AI usage quota
    history.db                              — Interaction history (SQLite)
  ~/.cache/strava/activities.json           — Local ride cache (up to 500)

DEPENDENCIES
------------
  pip install flask flask-limiter gunicorn   # web onboarding service
  pip install openai-whisper                 # voice note transcription (optional)
  ffmpeg                                     # required by Whisper (system package)
  piper                                      # TTS for /voice (optional)

SUPPORTED ACTIVITY TYPES
-------------------------
  Ride, VirtualRide, MountainBikeRide, GravelRide,
  EBikeRide, EMountainBikeRide, Handcycle, Velomobile

REPOSITORY
----------
  https://github.com/andreyshindler/strava-custom-coach
