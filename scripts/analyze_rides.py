#!/usr/bin/env python3
"""
analyze_rides.py — Trend analysis across multiple Strava rides.
Usage: ./scripts/analyze_rides.py [--days 90] [--ftp 220]
"""

import argparse
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
from strava_api import get_activities, load_config, meters_to_km, seconds_to_hm, estimate_tss


def main():
    parser = argparse.ArgumentParser(description="Analyze recent Strava rides")
    parser.add_argument("--days",  type=int, default=30,  help="How many days back to look")
    parser.add_argument("--ftp",   type=int, default=None, help="FTP in watts")
    parser.add_argument("--limit", type=int, default=50,  help="Max rides to fetch")
    args = parser.parse_args()

    config = load_config()
    ftp = args.ftp or config.get("ftp", 220)

    print(f"\nFetching rides from the last {args.days} days...")
    activities = get_activities(days=args.days, limit=args.limit)

    if not activities:
        print("No rides found.")
        sys.exit(0)

    print(f"\n📊 Training Summary — Last {args.days} Days")
    print(f"   {len(activities)} rides analysed  |  FTP: {ftp}W")
    print("─" * 55)

    total_dist     = sum(a.get("distance", 0) for a in activities)
    total_time     = sum(a.get("moving_time", 0) for a in activities)
    total_elev     = sum(a.get("total_elevation_gain", 0) for a in activities)
    total_tss      = sum(estimate_tss(a, ftp) for a in activities)
    avg_power_list = [a["average_watts"] for a in activities if a.get("average_watts")]
    avg_hr_list    = [a["average_heartrate"] for a in activities if a.get("average_heartrate")]

    print(f"\n🚴 Volume")
    print(f"  Total distance:  {meters_to_km(total_dist)} km")
    print(f"  Total time:      {seconds_to_hm(total_time)}")
    print(f"  Total elevation: {int(total_elev)} m")
    print(f"  Total TSS:       {total_tss}")
    print(f"  Weekly avg TSS:  {int(total_tss / (args.days / 7))}")

    if avg_power_list:
        print(f"\n⚡ Power")
        print(f"  Avg power:       {int(sum(avg_power_list)/len(avg_power_list))} W")
        print(f"  Best avg power:  {int(max(avg_power_list))} W")

    if avg_hr_list:
        print(f"\n❤️  Heart Rate")
        print(f"  Avg HR:          {int(sum(avg_hr_list)/len(avg_hr_list))} bpm")

    # Week-by-week breakdown
    print(f"\n📅 Week-by-week")
    weeks = {}
    for a in activities:
        date_str = a.get("start_date_local", "")[:10]
        if not date_str:
            continue
        date = datetime.strptime(date_str, "%Y-%m-%d")
        week_key = date.strftime("%Y-W%U")
        if week_key not in weeks:
            weeks[week_key] = {"rides": 0, "dist": 0, "tss": 0, "time": 0}
        weeks[week_key]["rides"] += 1
        weeks[week_key]["dist"]  += a.get("distance", 0)
        weeks[week_key]["tss"]   += estimate_tss(a, ftp)
        weeks[week_key]["time"]  += a.get("moving_time", 0)

    for wk, data in sorted(weeks.items())[-8:]:
        print(f"  {wk}: {data['rides']} rides  {meters_to_km(data['dist'])}km  {seconds_to_hm(data['time'])}  TSS {data['tss']}")

    # Recent rides list
    print(f"\n🗒  Recent Rides")
    for a in activities[:8]:
        dist  = meters_to_km(a.get("distance", 0))
        date  = a.get("start_date_local", "")[:10]
        name  = a.get("name", "Untitled")[:35]
        pwr   = f" {int(a['average_watts'])}W" if a.get("average_watts") else ""
        print(f"  {date}  {name:<35} {dist:>5}km{pwr}")

    print()


if __name__ == "__main__":
    main()
