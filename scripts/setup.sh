#!/usr/bin/env bash
# setup.sh — Strava Cycling Coach initial setup

set -e

CONFIG_DIR="$HOME/.config/strava"
mkdir -p "$CONFIG_DIR"

echo ""
echo "🚴 Strava Cycling Coach — Setup"
echo "================================"
echo ""
echo "You'll need a Strava API application. If you haven't created one:"
echo "  → https://www.strava.com/settings/api"
echo "  → Application Name: anything (e.g. Clawdbot)"
echo "  → Authorization Callback Domain: localhost"
echo ""

read -p "Enter your Strava Client ID: " CLIENT_ID
if ! [[ "$CLIENT_ID" =~ ^[0-9]+$ ]]; then
  echo "❌ Client ID must be a number (e.g. 12345). Got: '$CLIENT_ID'" >&2
  exit 1
fi

read -p "Enter your Strava Client Secret: " CLIENT_SECRET
if ! [[ "$CLIENT_SECRET" =~ ^[a-f0-9]{40}$ ]]; then
  echo "❌ Client Secret must be a 40-character hex string. Got: '$CLIENT_SECRET'" >&2
  exit 1
fi

echo ""
echo "Your Telegram chat ID (so the bot only responds to you)."
echo "To find it: message @userinfobot on Telegram — it replies with your ID."
read -p "Enter your Telegram chat ID: " TELEGRAM_CHAT_ID
if ! [[ "$TELEGRAM_CHAT_ID" =~ ^-?[0-9]+$ ]]; then
  echo "❌ Telegram chat ID must be a number (positive for users, negative for groups). Got: '$TELEGRAM_CHAT_ID'" >&2
  exit 1
fi

# Save to config
cat > "$CONFIG_DIR/config.json" <<EOF
{
  "client_id": "$CLIENT_ID",
  "client_secret": "$CLIENT_SECRET",
  "ftp": 220,
  "weight_kg": 75,
  "monitoring_frequency_minutes": 30,
  "telegram_chat_id": "$TELEGRAM_CHAT_ID",
  "training_plan_active": false,
  "notification_on_plan_deviation": true
}
EOF

echo ""
echo "✅ Credentials saved to $CONFIG_DIR/config.json"
echo ""
echo "Now authorize with Strava. Open this URL in your browser:"
echo ""
echo "  https://www.strava.com/oauth/authorize?client_id=${CLIENT_ID}&response_type=code&redirect_uri=http://localhost/exchange_token&approval_prompt=force&scope=read,activity:read_all"
echo ""
echo "After authorizing, you'll be redirected to a localhost URL."
echo "Copy the 'code' parameter from that URL and run:"
echo ""
echo "  ./scripts/complete_auth.py YOUR_CODE_HERE"
echo ""
