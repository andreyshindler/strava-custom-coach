#!/usr/bin/env python3
"""
webhook.py — Strava webhook server for strava-custom-coach.

Strava sends events to this server whenever an activity is created,
updated, or deleted. On a new ride, the server auto-analyzes it and
pushes a Telegram notification.

Usage:
    # Start the webhook server (default port 8421)
    ./scripts/webhook.py serve [--port 8421]

    # Register (subscribe) this endpoint with Strava
    ./scripts/webhook.py subscribe --url https://yourhost.example.com/webhook

    # View current Strava webhook subscription(s)
    ./scripts/webhook.py list

    # Delete a Strava webhook subscription
    ./scripts/webhook.py delete <subscription_id>

Config keys in ~/.config/strava/config.json:
    webhook_verify_token   — arbitrary secret string Strava echoes back during
                             subscription validation (default: "strava-coach")
    telegram_bot_token     — for push notifications
    telegram_chat_id       — destination chat/user
    ftp                    — FTP in watts (used for analysis)
    weight_kg              — rider weight (used for W/kg)
"""

import hashlib
import hmac
import json
import os
import sys
import urllib.request
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from strava_api import get_activity, load_config, meters_to_km, seconds_to_hm, estimate_tss, CYCLING_TYPES, urlopen_with_retry
from personas import load_active_persona, pick_feedback

CONFIG_FILE = Path.home() / ".config" / "strava" / "config.json"


# ── Telegram helpers (duplicated locally to avoid circular imports) ────────────

def _tg_send(text, voice_text=None):
    """Send a Telegram message using config file credentials.
    If voice_text is provided, saves it to pending_voice.txt and adds
    the 'Hear coach' inline button (compatible with telegram_bot.py's callback handler).
    """
    cfg = load_config()
    token   = os.environ.get("STRAVA_TELEGRAM_BOT_TOKEN") or cfg.get("telegram_bot_token", "")
    chat_id = os.environ.get("STRAVA_TELEGRAM_CHAT_ID")   or str(cfg.get("telegram_chat_id", ""))
    if not token or not chat_id:
        print("[webhook] Telegram not configured — skipping notification.")
        return

    if voice_text:
        vf = Path.home() / ".config" / "strava" / "pending_voice.txt"
        vf.parent.mkdir(parents=True, exist_ok=True)
        vf.write_text(voice_text)
        payload = {
            "chat_id":    chat_id,
            "text":       text[:4000],
            "parse_mode": "Markdown",
            "reply_markup": {
                "inline_keyboard": [[
                    {"text": "🔊 Hear coach", "callback_data": "voice"}
                ]]
            },
        }
        data = json.dumps(payload).encode()
        req  = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
    else:
        data = urllib.parse.urlencode({
            "chat_id":    chat_id,
            "text":       text[:4000],
            "parse_mode": "Markdown",
        }).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=data,
            method="POST",
        )

    urlopen_with_retry(req, timeout=15)


# ── Activity analysis ──────────────────────────────────────────────────────────

def build_ride_message(activity, ftp, persona):
    """Return a Telegram-friendly Markdown summary of the activity."""
    name     = activity.get("name", "Untitled")
    date     = activity.get("start_date_local", "")[:10]
    dist     = meters_to_km(activity.get("distance", 0))
    duration = seconds_to_hm(activity.get("moving_time", 0))
    elev     = int(activity.get("total_elevation_gain", 0))
    speed    = round(activity.get("average_speed", 0) * 3.6, 1)

    avg_pwr  = activity.get("average_watts")
    max_pwr  = activity.get("max_watts")
    avg_hr   = activity.get("average_heartrate")
    max_hr   = activity.get("max_heartrate")
    calories = activity.get("calories")
    tss      = estimate_tss(activity, ftp)

    cfg      = load_config()
    weight   = cfg.get("weight_kg", 75)
    w_per_kg = round(avg_pwr / weight, 2) if avg_pwr and weight else None

    intensity_factor = None
    if avg_pwr and ftp:
        intensity_factor = round((avg_pwr * 1.05) / ftp, 2)

    p = persona
    lines = [
        f"*New ride — {name}*",
        f"_{date}   Coach: {p['name']}_",
        "",
        f"*Overview*",
        f"  Distance:  {dist} km",
        f"  Time:      {duration}",
        f"  Elevation: {elev} m",
        f"  Avg speed: {speed} km/h",
    ]

    if avg_pwr:
        lines += ["", "*Power*",
                  f"  Avg: {int(avg_pwr)} W" + (f"  Max: {int(max_pwr)} W" if max_pwr else "")]
        if w_per_kg:
            lines.append(f"  W/kg: {w_per_kg}")
        if intensity_factor:
            lines.append(f"  IF: {intensity_factor}  (FTP {ftp} W)")
        lines.append(f"  Est. TSS: {tss}")

    if avg_hr:
        lines += ["", "*Heart Rate*",
                  f"  Avg: {int(avg_hr)} bpm" + (f"  Max: {int(max_hr)} bpm" if max_hr else "")]

    if calories:
        lines.append(f"\n  Calories: {int(calories)} kcal")

    # PRs
    segments = activity.get("segment_efforts", [])
    if segments:
        prs = [s for s in segments if s.get("pr_rank") == 1]
        if prs:
            lines.append(f"\n*PRs ({len(prs)})*")
            for s in prs[:5]:
                lines.append(f"  * {s['name']} — {seconds_to_hm(s.get('elapsed_time', 0))}")

    # Coaching note
    zf = p["zone_feedback"]
    lines.append(f"\n{p['coach_label']}")
    if intensity_factor:
        if intensity_factor < 0.65:
            note = pick_feedback(zf, "z1")
        elif intensity_factor < 0.80:
            note = pick_feedback(zf, "z2")
        elif intensity_factor < 0.95:
            note = pick_feedback(zf, "z3")
        elif intensity_factor < 1.05:
            note = pick_feedback(zf, "z4")
        else:
            note = pick_feedback(zf, "z5")
    else:
        note = pick_feedback(zf, "no_ftp")
    lines.append(f"  _{note}_")

    return "\n".join(lines)


def handle_activity_event(event):
    """Called for create/update events on an activity object."""
    aspect      = event.get("aspect_type")
    activity_id = event.get("object_id")

    if aspect == "delete":
        print(f"[webhook] Activity {activity_id} deleted — nothing to do.")
        return

    print(f"[webhook] Fetching activity {activity_id} (aspect={aspect}) ...")
    try:
        activity = get_activity(activity_id)
    except Exception as exc:
        print(f"[webhook] Failed to fetch activity {activity_id}: {exc}")
        return

    sport = activity.get("sport_type") or activity.get("type", "")
    if sport not in CYCLING_TYPES:
        print(f"[webhook] Skipping non-cycling activity ({sport}).")
        return

    cfg     = load_config()
    ftp     = cfg.get("ftp", 220)
    persona = load_active_persona()

    msg = build_ride_message(activity, ftp, persona)
    # Extract the coaching note (last non-empty line, strip markdown italics)
    voice_text = next(
        (l.strip().strip("_") for l in reversed(msg.splitlines()) if l.strip()),
        ""
    )
    print(f"[webhook] Sending Telegram notification for '{activity.get('name')}'")
    try:
        _tg_send(msg, voice_text=voice_text)
    except Exception as exc:
        print(f"[webhook] Telegram error: {exc}")


# ── HTTP request handler ───────────────────────────────────────────────────────

class WebhookHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        print(f"[webhook] {self.address_string()} {fmt % args}")

    def _verify_token(self):
        cfg = load_config()
        return cfg.get("webhook_verify_token", "strava-coach")

    # GET — hub challenge (Strava subscription verification)
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/robots.txt":
            body = b"User-agent: *\nDisallow: /\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path != "/webhook":
            self._respond(404, "Not found")
            return

        params = dict(urllib.parse.parse_qsl(parsed.query))
        mode      = params.get("hub.mode")
        challenge = params.get("hub.challenge")
        verify    = params.get("hub.verify_token")

        if mode == "subscribe" and verify == self._verify_token():
            body = json.dumps({"hub.challenge": challenge}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            print(f"[webhook] Subscription validated (challenge={challenge})")
        else:
            print(f"[webhook] Validation failed: mode={mode!r} verify={verify!r}")
            self._respond(403, "Forbidden")

    def _verify_signature(self, body: bytes) -> bool:
        """Verify Strava's X-Hub-Signature header using HMAC-SHA256."""
        sig_header = self.headers.get("X-Hub-Signature", "")
        if not sig_header.startswith("sha256="):
            return False
        secret = self._verify_token().encode()
        expected = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig_header, expected)

    # POST — incoming event
    def do_POST(self):
        if self.path != "/webhook":
            self._respond(404, "Not found")
            return

        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length) if length else b""

        # Verify Strava signature before processing
        if not self._verify_signature(body):
            print(f"[webhook] Rejected POST — invalid signature from {self.address_string()}")
            self._respond(403, "Forbidden")
            return

        # Acknowledge immediately — Strava requires 200 within 2 seconds
        self._respond(200, "EVENT_RECEIVED")

        try:
            event = json.loads(body)
        except json.JSONDecodeError:
            print(f"[webhook] Received non-JSON body: {body[:200]}")
            return

        print(f"[webhook] Event: {event}")
        if event.get("object_type") == "activity":
            handle_activity_event(event)

    def _respond(self, code, text):
        body = text.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ── Strava subscription management ────────────────────────────────────────────

def _strava_webhook_api(method, endpoint, params=None, data=None):
    url = f"https://www.strava.com/api/v3{endpoint}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    encoded = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request(url, data=encoded, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read()
        print(f"[webhook] Strava API error {exc.code}: {body.decode()}")
        sys.exit(1)


def cmd_subscribe(callback_url):
    cfg          = load_config()
    client_id    = cfg["client_id"]
    client_secret = cfg["client_secret"]
    verify_token = cfg.get("webhook_verify_token", "strava-coach")

    print(f"Subscribing webhook to: {callback_url}")
    result = _strava_webhook_api("POST", "/push_subscriptions", data={
        "client_id":     client_id,
        "client_secret": client_secret,
        "callback_url":  callback_url,
        "verify_token":  verify_token,
    })
    print(f"Subscription created: {json.dumps(result, indent=2)}")


def cmd_list():
    cfg = load_config()
    result = _strava_webhook_api("GET", "/push_subscriptions", params={
        "client_id":     cfg["client_id"],
        "client_secret": cfg["client_secret"],
    })
    if not result:
        print("No active webhook subscriptions.")
    else:
        print(json.dumps(result, indent=2))


def cmd_delete(subscription_id):
    cfg = load_config()
    _strava_webhook_api("DELETE", f"/push_subscriptions/{subscription_id}", params={
        "client_id":     cfg["client_id"],
        "client_secret": cfg["client_secret"],
    })
    print(f"Subscription {subscription_id} deleted.")


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Strava webhook server & subscription manager")
    sub    = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="Run the webhook HTTP server")
    p_serve.add_argument("--port", type=int, default=8421, help="Port to listen on (default: 8421)")
    p_serve.add_argument("--host", type=str, default="0.0.0.0", help="Host to bind (default: 0.0.0.0)")

    p_sub = sub.add_parser("subscribe", help="Register this webhook with Strava")
    p_sub.add_argument("--url", required=True, help="Public HTTPS URL, e.g. https://yourhost.example.com/webhook")

    sub.add_parser("list", help="List active Strava webhook subscriptions")

    p_del = sub.add_parser("delete", help="Delete a Strava webhook subscription")
    p_del.add_argument("subscription_id", type=int)

    args = parser.parse_args()

    if args.command == "serve":
        server = HTTPServer((args.host, args.port), WebhookHandler)
        print(f"[webhook] Listening on {args.host}:{args.port}/webhook")
        print("[webhook] Press Ctrl-C to stop.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\n[webhook] Stopped.")

    elif args.command == "subscribe":
        cmd_subscribe(args.url)

    elif args.command == "list":
        cmd_list()

    elif args.command == "delete":
        cmd_delete(args.subscription_id)


if __name__ == "__main__":
    main()
