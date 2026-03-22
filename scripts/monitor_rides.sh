#!/usr/bin/env bash
# monitor_rides.sh — Interactive background ride monitor.
# Polls every N minutes and reports new rides to terminal + Telegram.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INTERVAL="${1:-30}"  # minutes, default 30

echo "🚴 Strava Ride Monitor started (checking every ${INTERVAL} min)"
echo "   Press Ctrl+C to stop"
echo ""

while true; do
    "$SCRIPT_DIR/auto_analyze_new_rides.sh"
    echo "[$(date '+%H:%M')] Checked. Next check in ${INTERVAL} min..."
    sleep $((INTERVAL * 60))
done
