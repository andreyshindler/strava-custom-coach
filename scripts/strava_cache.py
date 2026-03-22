#!/usr/bin/env python3
"""
Manage local cache of Strava activities.
"""
import json
from pathlib import Path
from datetime import datetime

CACHE_DIR = Path.home() / ".cache" / "strava"

def ensure_cache_dir(cache_dir=CACHE_DIR):
    """Create cache directory if it doesn't exist."""
    cache_dir.mkdir(parents=True, exist_ok=True)

def load_cached_activities(cache_dir=CACHE_DIR):
    """Load activities from cache."""
    ensure_cache_dir(cache_dir)
    f = cache_dir / "activities.json"
    if not f.exists():
        return []
    try:
        with open(f) as fp:
            return json.load(fp)
    except Exception as e:
        print(f"[strava_cache] WARNING: activities.json corrupted ({e}) — returning empty cache")
        return []

def save_activities_to_cache(activities, cache_dir=CACHE_DIR):
    """Save activities to cache."""
    ensure_cache_dir(cache_dir)
    with open(cache_dir / "activities.json", 'w') as f:
        json.dump(activities, f, indent=2)
    with open(cache_dir / "last_sync.txt", 'w') as f:
        f.write(datetime.now().isoformat())

def get_last_sync_time(cache_dir=CACHE_DIR):
    """Get the last sync timestamp."""
    f = cache_dir / "last_sync.txt"
    if not f.exists():
        return None
    with open(f) as fp:
        return fp.read().strip()

def update_cache_with_new_activities(new_activities, cache_dir=CACHE_DIR):
    """Merge new activities into cache, avoiding duplicates."""
    cached = load_cached_activities(cache_dir)
    cached_ids = {a['id'] for a in cached}

    for activity in new_activities:
        if activity['id'] not in cached_ids:
            cached.insert(0, activity)

    cached.sort(key=lambda x: x['start_date'], reverse=True)
    cached = cached[:500]

    save_activities_to_cache(cached, cache_dir)
    return cached

def get_activity_by_id(activity_id, cache_dir=CACHE_DIR):
    """Get a specific activity from cache."""
    cached = load_cached_activities(cache_dir)
    for activity in cached:
        if activity['id'] == activity_id:
            return activity
    return None

if __name__ == '__main__':
    print(f"Cache directory: {CACHE_DIR}")
    print(f"Last sync: {get_last_sync_time()}")
    print(f"Cached activities: {len(load_cached_activities())}")
