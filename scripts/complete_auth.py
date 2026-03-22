#!/usr/bin/env python3
"""
complete_auth.py — Exchange Strava OAuth code for access/refresh tokens.
Usage: ./scripts/complete_auth.py YOUR_CODE_HERE
"""

import json
import sys
import urllib.request
import urllib.parse
from pathlib import Path

CONFIG_FILE = Path.home() / ".config" / "strava" / "config.json"
TOKEN_FILE = Path.home() / ".config" / "strava" / "tokens.json"


def main():
    if len(sys.argv) < 2:
        print("Usage: ./scripts/complete_auth.py YOUR_AUTH_CODE")
        sys.exit(1)

    code = sys.argv[1].strip()

    if not CONFIG_FILE.exists():
        print("❌ Config not found. Run ./scripts/setup.sh first.")
        sys.exit(1)

    config = json.loads(CONFIG_FILE.read_text())
    client_id = config["client_id"]
    client_secret = config["client_secret"]

    print("🔑 Exchanging authorization code for tokens...")

    data = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
    }).encode()

    req = urllib.request.Request(
        "https://www.strava.com/oauth/token",
        data=data,
        method="POST"
    )

    try:
        with urllib.request.urlopen(req) as resp:
            tokens = json.loads(resp.read())
    except Exception as e:
        print(f"❌ Token exchange failed: {e}")
        sys.exit(1)

    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(tokens, indent=2))

    athlete = tokens.get("athlete", {})
    name = f"{athlete.get('firstname', '')} {athlete.get('lastname', '')}".strip()
    print(f"✅ Authorized as: {name or 'Unknown athlete'}")
    print(f"✅ Tokens saved to {TOKEN_FILE}")
    print("")
    print("You're all set! Try:")
    print("  ./scripts/get_latest_ride.py")
    print("  ./scripts/training_plan.py --interactive")


if __name__ == "__main__":
    main()
