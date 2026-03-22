#!/usr/bin/env python3
"""
analyze_ride.py — Deep analysis of a specific Strava activity.
Usage: ./scripts/analyze_ride.py <activity-id> [--ftp 240] [--persona pogi]
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from strava_api import get_activity, load_config, meters_to_km, seconds_to_hm, estimate_tss
from personas import load_active_persona, get_persona


def analyze(activity, ftp, persona):
    name     = activity.get("name", "Untitled")
    date     = activity.get("start_date_local", "")[:10]
    dist     = meters_to_km(activity.get("distance", 0))
    duration = seconds_to_hm(activity.get("moving_time", 0))
    elev     = int(activity.get("total_elevation_gain", 0))
    speed    = round(activity.get("average_speed", 0) * 3.6, 1)
    max_spd  = round(activity.get("max_speed", 0) * 3.6, 1)

    avg_pwr  = activity.get("average_watts")
    max_pwr  = activity.get("max_watts")
    w_per_kg = None
    config   = load_config()
    weight   = config.get("weight_kg", 75)
    if avg_pwr and weight:
        w_per_kg = round(avg_pwr / weight, 2)

    avg_hr   = activity.get("average_heartrate")
    max_hr   = activity.get("max_heartrate")
    calories = activity.get("calories")
    tss      = estimate_tss(activity, ftp)

    intensity_factor = None
    if avg_pwr and ftp:
        np_estimate = avg_pwr * 1.05
        intensity_factor = round(np_estimate / ftp, 2)

    p = persona
    print(f"\n🚴 Ride Analysis — {name}")
    print(f"   {date}  |  Coach: {p['name']}")
    print("─" * 50)

    print(f"\n📍 Overview")
    print(f"  Distance:    {dist} km")
    print(f"  Time:        {duration}")
    print(f"  Elevation:   {elev} m")
    print(f"  Avg Speed:   {speed} km/h  (max: {max_spd} km/h)")

    if avg_pwr:
        print(f"\n⚡ Power")
        print(f"  Avg Power:   {int(avg_pwr)} W")
        if max_pwr:
            print(f"  Max Power:   {int(max_pwr)} W")
        if w_per_kg:
            print(f"  W/kg:        {w_per_kg}")
        if intensity_factor:
            print(f"  Int. Factor: {intensity_factor}  (FTP: {ftp}W)")
        print(f"  Est. TSS:    {tss}")

    if avg_hr:
        print(f"\n❤️  Heart Rate")
        print(f"  Avg HR:      {int(avg_hr)} bpm")
        if max_hr:
            print(f"  Max HR:      {int(max_hr)} bpm")

    if calories:
        print(f"\n🔥 Calories:   {int(calories)} kcal")

    # Segments and PRs
    segments = activity.get("segment_efforts", [])
    if segments:
        prs  = [s for s in segments if s.get("pr_rank") == 1]
        top3 = [s for s in segments if s.get("pr_rank") in (2, 3)]
        if prs:
            print(f"\n🏆 Personal Records ({len(prs)})")
            for s in prs[:5]:
                t = seconds_to_hm(s.get("elapsed_time", 0))
                print(f"  ⭐ {s['name']} — {t}")
        if top3:
            print(f"\n🥈 Near PRs (top 3 all time)")
            for s in top3[:3]:
                t = seconds_to_hm(s.get("elapsed_time", 0))
                print(f"  {s['name']} — {t} (#{s['pr_rank']})")

    # Coaching note — persona-driven
    zf = p["zone_feedback"]
    print(f"\n{p['coach_label']}")
    if intensity_factor:
        if intensity_factor < 0.65:
            note = zf["z1"]
        elif intensity_factor < 0.80:
            note = zf["z2"]
        elif intensity_factor < 0.95:
            note = zf["z3"]
        elif intensity_factor < 1.05:
            note = zf["z4"]
        else:
            note = zf["z5"]
        print(f"  {note}")
    else:
        print(f"  {zf['no_ftp']}")

    print()


def main():
    parser = argparse.ArgumentParser(description="Analyze a specific Strava activity")
    parser.add_argument("activity_id", type=int, help="Strava activity ID")
    parser.add_argument("--ftp",     type=int,  help="Your FTP in watts")
    parser.add_argument("--persona", type=str,  help="Coach persona (nino/pogi/badger/cannibal)")
    args = parser.parse_args()

    config  = load_config()
    ftp     = args.ftp or config.get("ftp", 220)
    persona = get_persona(args.persona) if args.persona else load_active_persona()

    print(f"Fetching activity {args.activity_id}... [Coach: {persona['name']}]")
    activity = get_activity(args.activity_id)
    analyze(activity, ftp, persona)


if __name__ == "__main__":
    main()
