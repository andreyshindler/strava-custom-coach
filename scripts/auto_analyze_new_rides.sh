#!/usr/bin/env bash
# auto_analyze_new_rides.sh — Cron-compatible new ride detector with Telegram + training plan check.
# Add to crontab: */30 * * * * /path/to/scripts/auto_analyze_new_rides.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_FILE="$HOME/.config/strava/last_seen_activity.txt"
LOG_FILE="$HOME/.config/strava/monitor.log"

mkdir -p "$(dirname "$STATE_FILE")"
touch "$LOG_FILE"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

send_telegram() {
    local msg="$1"
    local token="${STRAVA_TELEGRAM_BOT_TOKEN:-}"
    local chat_id="${STRAVA_TELEGRAM_CHAT_ID:-}"

    if [[ -z "$token" || -z "$chat_id" ]]; then
        log "Telegram not configured (set STRAVA_TELEGRAM_BOT_TOKEN and STRAVA_TELEGRAM_CHAT_ID)"
        return
    fi

    curl -s -X POST "https://api.telegram.org/bot${token}/sendMessage" \
        -d "chat_id=${chat_id}" \
        -d "text=${msg}" \
        -d "parse_mode=Markdown" \
        > /dev/null
}

log "Checking for new rides..."

# Get latest activity ID
LATEST_JSON=$("$SCRIPT_DIR/get_latest_ride.py" --json 2>/dev/null || echo "{}")
LATEST_ID=$(echo "$LATEST_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('id',''))" 2>/dev/null || echo "")

if [[ -z "$LATEST_ID" ]]; then
    log "No activities found or API error."
    exit 0
fi

# Compare with last seen
LAST_SEEN=$(cat "$STATE_FILE" 2>/dev/null || echo "")

if [[ "$LATEST_ID" == "$LAST_SEEN" ]]; then
    log "No new rides. Latest: $LATEST_ID"
    exit 0
fi

log "New ride detected: $LATEST_ID"
echo "$LATEST_ID" > "$STATE_FILE"

# Generate analysis summary
ANALYSIS=$("$SCRIPT_DIR/analyze_ride.py" "$LATEST_ID" 2>/dev/null || echo "Could not analyze ride $LATEST_ID")

# Check training plan compliance
PLAN_FILE="$HOME/.config/strava/training_plan.json"
PLAN_NOTE=""
if [[ -f "$PLAN_FILE" ]]; then
    TODAY=$(date '+%Y-%m-%d')
    PLAN_NOTE=$(python3 - <<EOF
import json
from pathlib import Path
plan = json.loads(Path("$PLAN_FILE").read_text())
for week in plan.get("weekly_plans", []):
    for day in week.get("days", []):
        if day.get("date") == "$TODAY":
            w = day.get("name", "")
            tss = day.get("tss", 0)
            print(f"\n📋 Today's planned workout: {w} (target TSS: {tss})")
            break
EOF
)
fi

MSG="🚴 *New Ride Detected!*

${ANALYSIS}${PLAN_NOTE}"

send_telegram "$MSG"
log "Notification sent for ride $LATEST_ID"
