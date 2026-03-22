#!/usr/bin/env python3
"""
get_latest_ride.py — Fetch and display the most recent Strava ride.
Usage: ./scripts/get_latest_ride.py [--json]
"""

import argparse
import json
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from strava_api import get_activities, get_activity, format_activity_summary, load_config, estimate_tss


def main():
    parser = argparse.ArgumentParser(description="Get latest Strava ride")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    args = parser.parse_args()

    activities = get_activities(days=30, limit=10)
    activities.sort(key=lambda a: a.get("start_date", ""), reverse=True)
    if not activities:
        print("No rides found in the last 30 days.")
        sys.exit(0)

    activity = activities[0]

    if args.json:
        # Fetch detailed version
        detail = get_activity(activity["id"])
        print(json.dumps(detail, indent=2))
        return

    config = load_config()
    ftp = config.get("ftp", 220)
    tss = estimate_tss(activity, ftp)

    print("\n🚴 Latest Ride\n" + "─" * 40)
    print(format_activity_summary(activity))
    print(f"  Est. TSS: {tss}")

    # Segment PRs
    segments = activity.get("segment_efforts", [])
    prs = [s for s in segments if s.get("pr_rank") == 1]
    if prs:
        print(f"\n🏆 PRs: {', '.join(s['name'] for s in prs[:5])}")

    print()


if __name__ == "__main__":
    main()
