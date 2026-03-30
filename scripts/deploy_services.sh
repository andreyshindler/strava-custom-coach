#!/usr/bin/env bash
# deploy_services.sh — Install and start systemd services:
#   1. strava-coach-bot  — main Telegram bot (multi-user, one process)
#   2. onboarding-web    — Flask app that handles the Strava OAuth callback
#
# Usage:
#   export STRAVA_TELEGRAM_BOT_TOKEN="123456:AABBcc..."
#   export PUBLIC_URL="https://yourserver.com"
#   export FLASK_SECRET="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
#   export ANTHROPIC_API_KEY="sk-ant-..."
#   export ADMIN_PASSWORD="yourpassword"   # for /admin page
#   bash scripts/deploy_services.sh

set -e

# ── Require env vars ──────────────────────────────────────────────────────────
for var in STRAVA_TELEGRAM_BOT_TOKEN PUBLIC_URL FLASK_SECRET ANTHROPIC_API_KEY; do
    if [[ -z "${!var}" ]]; then
        echo "❌ $var is not set. Aborting."
        exit 1
    fi
done

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$(which python3)"
USER="$(whoami)"

echo ""
echo "🚀 Custom Coach — Deploy Services"
echo "========================================="
echo "Project: $PROJECT_DIR"
echo "User:    $USER"
echo "Python:  $PYTHON"
echo ""

# ── Install Python dependencies ───────────────────────────────────────────────
echo "📦 Installing Python dependencies..."
pip3 install -q flask flask-limiter gunicorn

# ── 1. strava-coach-bot — main multi-user Telegram bot ───────────────────────
echo "⚙️  Creating strava-coach-bot service..."

sudo tee /etc/systemd/system/strava-coach-bot.service > /dev/null <<EOF
[Unit]
Description=Custom Coach — Telegram Bot (multi-user)
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$PROJECT_DIR/scripts
ExecStart=$PYTHON $PROJECT_DIR/scripts/telegram_bot.py --loop
Restart=always
RestartSec=10

Environment=STRAVA_TELEGRAM_BOT_TOKEN=$STRAVA_TELEGRAM_BOT_TOKEN
Environment=ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY
Environment=PUBLIC_URL=$PUBLIC_URL

StandardOutput=journal
StandardError=journal
SyslogIdentifier=strava-coach-bot

[Install]
WantedBy=multi-user.target
EOF

# ── 2. onboarding-web — Flask OAuth callback server ──────────────────────────
echo "⚙️  Creating onboarding-web service..."

sudo tee /etc/systemd/system/onboarding-web.service > /dev/null <<EOF
[Unit]
Description=Strava Coach Onboarding Web (Flask/gunicorn)
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$PROJECT_DIR/onboarding
ExecStart=$(which gunicorn) --workers 2 --bind 127.0.0.1:5000 app:app
Restart=always
RestartSec=10

Environment=FLASK_SECRET=$FLASK_SECRET
Environment=PUBLIC_URL=$PUBLIC_URL
Environment=ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY
Environment=STRAVA_TELEGRAM_BOT_TOKEN=$STRAVA_TELEGRAM_BOT_TOKEN
Environment=ADMIN_USER=${ADMIN_USER:-admin}
Environment=ADMIN_PASSWORD=${ADMIN_PASSWORD:-}
Environment=WEBHOOK_VERIFY_TOKEN=${WEBHOOK_VERIFY_TOKEN:-strava-coach}
Environment=CODE_DIR=$PROJECT_DIR

StandardOutput=journal
StandardError=journal
SyslogIdentifier=onboarding-web

[Install]
WantedBy=multi-user.target
EOF

# ── Reload and start ──────────────────────────────────────────────────────────
echo "🔄 Reloading systemd..."
sudo systemctl daemon-reload

echo "▶️  Starting strava-coach-bot..."
sudo systemctl enable --now strava-coach-bot.service

echo "▶️  Starting onboarding-web..."
sudo systemctl enable --now onboarding-web.service

echo ""
echo "✅ Services started."
echo ""
echo "Check status:"
echo "  sudo systemctl status strava-coach-bot"
echo "  sudo systemctl status onboarding-web"
echo ""
echo "View logs:"
echo "  journalctl -u strava-coach-bot -f"
echo "  journalctl -u onboarding-web -f"
echo ""

# ── nginx hint ────────────────────────────────────────────────────────────────
echo "📝 nginx — add this block to your server config:"
echo ""
echo "    location /tg/callback {"
echo "        proxy_pass         http://127.0.0.1:5000;"
echo "        proxy_set_header   Host \$host;"
echo "        proxy_set_header   X-Real-IP \$remote_addr;"
echo "        proxy_set_header   X-Forwarded-For \$proxy_add_x_forwarded_for;"
echo "        proxy_set_header   X-Forwarded-Proto \$scheme;"
echo "    }"
echo ""
echo "Then reload nginx:  sudo nginx -t && sudo systemctl reload nginx"
echo ""
echo "Make sure PUBLIC_URL matches your Strava app's Authorization Callback Domain."
