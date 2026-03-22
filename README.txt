strava-custom-coach v2.1
========================

Track cycling performance from Strava, analyze rides, and generate
personalized training plans based on your goals. Includes a Telegram
bot with AI coaching chat, voice input, and training plan wizard.

QUICK START
-----------
1. Run setup:
   ./scripts/setup.sh

2. Complete OAuth authorization:
   ./scripts/complete_auth.py YOUR_CODE_HERE

3. Add Telegram + Anthropic keys to ~/.config/strava/config.json:
   "telegram_bot_token": "...",
   "telegram_chat_id":   "...",
   "anthropic_api_key":  "sk-ant-..."

4. Start the bot:
   ./scripts/telegram_bot.py --loop

5. (Optional) Cron monitor for new ride auto-analysis:
   crontab -e
   # Add: */30 * * * * /path/to/scripts/auto_analyze_new_rides.sh

SCRIPTS
-------
setup.sh                  — First-time Strava API setup
complete_auth.py          — Finish OAuth flow
get_latest_ride.py        — Show most recent ride
analyze_ride.py <id>      — Deep-analyze a specific ride
analyze_rides.py          — Trend analysis across recent rides
training_plan.py          — Generate training plans (interactive or CLI)
telegram_bot.py           — Telegram bot (--once for cron, --loop for daemon)
auto_analyze_new_rides.sh — Cron-compatible monitor with Telegram
monitor_rides.sh          — Interactive background monitor

DEPENDENCIES
------------
  pip install openai-whisper   # voice note transcription
  ffmpeg                       # required by Whisper (system package)

TRAINING PLAN GOALS
-------------------
  ftp          — Improve FTP (power output)
  event        — Prepare for a specific event
  distance     — Hit a weekly distance target
  weight-loss  — Weight loss + base fitness
  general      — General fitness maintenance

ENVIRONMENT VARIABLES
---------------------
  STRAVA_TELEGRAM_BOT_TOKEN — Telegram bot token
  STRAVA_TELEGRAM_CHAT_ID   — Telegram chat ID
  ANTHROPIC_API_KEY         — Claude API key (alternative to config.json)

CONFIG
------
  ~/.config/strava/config.json        — Settings and credentials
  ~/.config/strava/tokens.json        — Strava OAuth tokens (auto-managed)
  ~/.config/strava/training_plan.json — Active training plan

TELEGRAM BOT COMMANDS
---------------------
  /coach                    — Show current coach + list all
  /coach nino|pogi|badger|cannibal  — Switch coach persona
  /ride                     — Analyze latest ride
  /voice                    — Hear your coach speak (TTS)
  /plan                     — Today's planned workout
  /planxco                  — Today's XCO strength session
  /newplan                  — Create a training plan (step-by-step wizard)
  /deleteplan               — Delete current training plan
  /week                     — This week's full schedule
  /nextweek                 — Next week's schedule
  /nextmonth                — Next 4 weeks overview
  /fullplan                 — Entire training plan
  /stats                    — Last 7 days summary
  /stats 30                 — Last N days summary (any number)
  /stats30  /month          — Last 30 days shorthand
  /help                     — All commands

  Plain text message        — AI coaching chat (Claude)
  Voice note                — Transcribed via Whisper → AI coaching chat

  # Run bot in cron (every 5 min)
  */5 * * * * /path/to/scripts/telegram_bot.py --once

  # Or run continuously
  ./scripts/telegram_bot.py --loop

SUPPORTED ACTIVITY TYPES
------------------------
  Ride, VirtualRide, MountainBikeRide, GravelRide,
  EBikeRide, EMountainBikeRide, Handcycle, Velomobile

INSTALL VIA OPENCLAW
--------------------
  npx playbooks add skill openclaw/skills --skill strava-custom-coach

REPOSITORY
----------
  https://gitlab.com/bins7/strava-custom-coach
