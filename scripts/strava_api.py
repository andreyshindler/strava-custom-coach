#!/usr/bin/env python3
"""
strava_api.py — Shared Strava API helper for all scripts.
Handles token refresh, activity fetching, and formatting.
"""

import json
import time
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime, timezone

import urllib.error

from strava_cache import load_cached_activities, update_cache_with_new_activities, CACHE_DIR

CONFIG_FILE = Path.home() / ".config" / "strava" / "config.json"


def urlopen_with_retry(req, *, timeout=10, retries=3):
    """urlopen with exponential-backoff retry for transient errors.

    Retries on network errors (URLError), 5xx server errors, and 429 rate limits.
    Raises immediately on other 4xx client errors.
    Returns raw response bytes.
    """
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code >= 500 and attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
        except urllib.error.URLError as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
TOKEN_FILE  = Path.home() / ".config" / "strava" / "tokens.json"


def load_config(user_dir=None):
    """Load config. If user_dir given, reads user_dir/config.json, else owner CONFIG_FILE."""
    f = (user_dir / "config.json") if user_dir else CONFIG_FILE
    if not f.exists():
        raise FileNotFoundError(f"Config not found at {f}. Run ./scripts/setup.sh first.")
    return json.loads(f.read_text())


def load_tokens(user_dir=None):
    """Load tokens from user_dir/tokens.json or default TOKEN_FILE."""
    f = (user_dir / "tokens.json") if user_dir else TOKEN_FILE
    if not f.exists():
        raise FileNotFoundError(f"Tokens not found at {f}. Run ./scripts/complete_auth.py first.")
    return json.loads(f.read_text())


def refresh_token_if_needed(tokens, config, user_dir=None):
    """Refresh access token if expired. Returns (tokens, refreshed: bool)."""
    expires_at = tokens.get("expires_at", 0)
    if time.time() < expires_at - 60:
        return tokens, False

    data = urllib.parse.urlencode({
        "client_id":     config["client_id"],
        "client_secret": config["client_secret"],
        "grant_type":    "refresh_token",
        "refresh_token": tokens["refresh_token"],
    }).encode()

    req = urllib.request.Request("https://www.strava.com/oauth/token", data=data, method="POST")
    new_tokens = json.loads(urlopen_with_retry(req, timeout=15))

    token_file = (user_dir / "tokens.json") if user_dir else TOKEN_FILE
    token_file.write_text(json.dumps(new_tokens, indent=2))
    return new_tokens, True


def get_access_token(user_dir=None):
    config = load_config(user_dir)
    tokens = load_tokens(user_dir)
    tokens, refreshed = refresh_token_if_needed(tokens, config, user_dir)
    if refreshed:
        print("🔄 Access token refreshed.")
    return tokens["access_token"]


def api_get(endpoint, params=None, user_dir=None):
    token = get_access_token(user_dir)
    url = f"https://www.strava.com/api/v3{endpoint}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})

    try:
        return json.loads(urlopen_with_retry(req, timeout=10))
    except urllib.error.HTTPError as e:
        if e.code == 429:
            retry_after = int(e.headers.get("X-RateLimit-Limit", "60"))
            raise RuntimeError(f"Strava rate limit hit — retry after {retry_after}s") from e
        raise RuntimeError(f"Strava API error {e.code}: {e.reason}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error reaching Strava: {e.reason}") from e


CYCLING_TYPES = [
    "Ride", "VirtualRide", "MountainBikeRide", "GravelRide",
    "EBikeRide", "EMountainBikeRide", "Handcycle", "Velomobile",
]


def get_activities(days=30, limit=30, activity_type=None, user_dir=None):
    """Fetch activities with local cache. Only fetches from API activities newer than
    the most recent cached entry. activity_type can be a string, list of strings, or
    None (all types). Defaults to all cycling types. Pass activity_type=[] to skip filtering."""
    if activity_type is None:
        activity_type = CYCLING_TYPES

    # Per-user cache dir derived from user_dir name (chat_id)
    cache_dir = (CACHE_DIR / user_dir.name) if user_dir else CACHE_DIR

    cached = load_cached_activities(cache_dir)
    if cached:
        after_ts = int(_activity_ts(cached[0]))
        new_from_api = api_get("/athlete/activities", {
            "after":    after_ts,
            "per_page": 200,
            "page":     1,
        }, user_dir)
    else:
        new_from_api = api_get("/athlete/activities", {
            "per_page": 200,
            "page":     1,
        }, user_dir)

    if new_from_api:
        cached = update_cache_with_new_activities(new_from_api, cache_dir)

    cutoff = time.time() - (days * 86400)
    activities = [a for a in cached if _activity_ts(a) >= cutoff]

    if activity_type:
        if isinstance(activity_type, str):
            activity_type = [activity_type]
        activities = [
            a for a in activities
            if a.get("sport_type") in activity_type or a.get("type") in activity_type
        ]

    return activities[:limit]


def _activity_ts(a):
    """Parse start_date UTC string to a Unix timestamp."""
    try:
        return datetime.strptime(a["start_date"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc).timestamp()
    except Exception:
        return 0


def get_activity(activity_id, user_dir=None):
    return api_get(f"/activities/{activity_id}", user_dir=user_dir)


def meters_to_km(m):
    return round(m / 1000, 1)


def seconds_to_hm(s):
    h, m = divmod(s // 60, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


def format_activity_summary(a):
    name     = a.get("name", "Untitled")
    date     = a.get("start_date_local", "")[:10]
    dist     = meters_to_km(a.get("distance", 0))
    duration = seconds_to_hm(a.get("moving_time", 0))
    elev     = a.get("total_elevation_gain", 0)
    power    = a.get("average_watts")
    hr       = a.get("average_heartrate")
    speed    = round(a.get("average_speed", 0) * 3.6, 1)

    parts = [f"{date}  {name}", f"  Distance: {dist} km  |  Time: {duration}  |  Speed: {speed} km/h"]
    if elev:
        parts.append(f"  Elevation: {int(elev)} m")
    if power:
        parts.append(f"  Power: {int(power)} W avg")
    if hr:
        parts.append(f"  Heart rate: {int(hr)} bpm avg")
    return "\n".join(parts)


def estimate_tss(activity, ftp):
    """Rough TSS estimate from activity data."""
    duration = activity.get("moving_time", 0)
    avg_watts = activity.get("average_watts")
    if avg_watts and ftp:
        np = avg_watts * 1.05  # rough NP estimate
        if_ = np / ftp
        tss = (duration * np * if_) / (ftp * 3600) * 100
        return round(tss)
    # Fallback: estimate from duration + HR
    hr = activity.get("average_heartrate", 0)
    if hr:
        hr_factor = min(hr / 160, 1.2)
        return round((duration / 3600) * 50 * hr_factor)
    return round((duration / 3600) * 45)
