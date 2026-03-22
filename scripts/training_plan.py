#!/usr/bin/env python3
"""
training_plan.py — Generate personalized cycling training plans.
Usage:
    ./scripts/training_plan.py --interactive
    ./scripts/training_plan.py --goal ftp --weeks 12 --ftp 220
    ./scripts/training_plan.py --persona badger --goal event --event-name "Gran Fondo" --event-date 2026-06-15
    ./scripts/training_plan.py --list-personas
"""

import argparse
import json
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from personas import PERSONAS, load_active_persona, get_persona, list_personas

CONFIG_DIR = Path.home() / ".config" / "strava"
PLAN_FILE  = CONFIG_DIR / "training_plan.json"
CONFIG_FILE = CONFIG_DIR / "config.json"

# ── Zone definitions ──────────────────────────────────────────────────────────
POWER_ZONES = {
    1: (0,    0.55,  "Active Recovery"),
    2: (0.55, 0.75,  "Endurance"),
    3: (0.75, 0.90,  "Tempo"),
    4: (0.90, 1.05,  "Threshold"),
    5: (1.05, 1.20,  "VO2 Max"),
    6: (1.20, 1.50,  "Anaerobic"),
}

# ── Workout library (descriptions injected from persona at runtime) ──────────
WORKOUTS_BASE = {
    "z2_base":        {"name": "Zone 2 Endurance",     "duration_min": 60,  "tss_per_hour": 50, "zone": 2},
    "long_ride":      {"name": "Long Ride",             "duration_min": 120, "tss_per_hour": 55, "zone": 2},
    "sweet_spot":     {"name": "Sweet Spot Intervals",  "duration_min": 75,  "tss_per_hour": 80, "zone": 3},
    "threshold_2x20": {"name": "2×20 Threshold",        "duration_min": 60,  "tss_per_hour": 90, "zone": 4},
    "vo2_intervals":  {"name": "VO2 Max Intervals",     "duration_min": 60,  "tss_per_hour": 95, "zone": 5},
    "recovery":       {"name": "Recovery Spin",         "duration_min": 40,  "tss_per_hour": 30, "zone": 1},
    "tempo":          {"name": "Tempo Ride",            "duration_min": 75,  "tss_per_hour": 70, "zone": 3},
    "rest":           {"name": "Rest Day",              "duration_min": 0,   "tss_per_hour": 0,  "zone": 0},
}

def get_workouts(persona):
    """Merge base workout specs with persona-specific descriptions."""
    notes = persona.get("workout_notes", {})
    result = {}
    for key, base in WORKOUTS_BASE.items():
        w = dict(base)
        w["description"] = notes.get(key, base.get("description", ""))
        result[key] = w
    return result

# ── Weekly plan templates ─────────────────────────────────────────────────────
PLAN_TEMPLATES = {
    "ftp":         [
        ["rest", "z2_base", "threshold_2x20", "rest", "sweet_spot",     "z2_base", "long_ride"],
        ["rest", "z2_base", "threshold_2x20", "rest", "vo2_intervals",  "z2_base", "long_ride"],
        ["rest", "z2_base", "sweet_spot",     "rest", "threshold_2x20", "z2_base", "long_ride"],
        ["rest", "recovery","sweet_spot",     "rest", "recovery",        "z2_base", "z2_base"],
    ],
    "event":       [
        ["rest", "z2_base", "sweet_spot",     "rest", "z2_base",        "rest",    "long_ride"],
        ["rest", "z2_base", "threshold_2x20", "rest", "tempo",          "z2_base", "long_ride"],
        ["rest", "z2_base", "vo2_intervals",  "rest", "threshold_2x20", "z2_base", "long_ride"],
        ["rest", "recovery","sweet_spot",     "rest", "recovery",        "z2_base", "z2_base"],
    ],
    "distance":    [
        ["rest", "z2_base", "z2_base",    "rest", "tempo",      "z2_base", "long_ride"],
        ["rest", "z2_base", "sweet_spot", "rest", "z2_base",    "z2_base", "long_ride"],
        ["rest", "z2_base", "z2_base",    "rest", "sweet_spot", "z2_base", "long_ride"],
        ["rest", "recovery","z2_base",    "rest", "recovery",   "z2_base", "z2_base"],
    ],
    "weight-loss": [
        ["z2_base", "z2_base", "z2_base", "rest", "z2_base",    "rest",    "long_ride"],
        ["z2_base", "z2_base", "tempo",   "rest", "z2_base",    "rest",    "long_ride"],
        ["rest",    "z2_base", "z2_base", "rest", "sweet_spot", "z2_base", "long_ride"],
        ["rest",    "recovery","z2_base", "rest", "recovery",   "z2_base", "long_ride"],
    ],
    "general":     [
        ["rest", "z2_base", "sweet_spot",     "rest", "z2_base", "rest", "long_ride"],
        ["rest", "z2_base", "tempo",          "rest", "z2_base", "rest", "long_ride"],
        ["rest", "z2_base", "threshold_2x20", "rest", "z2_base", "rest", "long_ride"],
        ["rest", "recovery","z2_base",        "rest", "recovery","z2_base","z2_base"],
    ],
}

DAYS = ["Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"]


def load_config():
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return {"ftp": 220, "weight_kg": 75}


def estimate_tss(workout_key, workouts, ftp_multiplier=1.0):
    w = workouts[workout_key]
    return int((w["duration_min"] / 60) * w["tss_per_hour"] * ftp_multiplier)


def build_plan(goal, weeks, ftp, persona, start_date=None,
               event_name=None, event_date=None,
               target_ftp=None, target_km=None, target_kg=None):
    workouts   = get_workouts(persona)
    template   = PLAN_TEMPLATES.get(goal, PLAN_TEMPLATES["general"])
    start      = start_date or datetime.today()
    # Align to Sunday (weekday 6)
    days_to_sunday = (6 - start.weekday()) % 7
    start      = start + timedelta(days=days_to_sunday)
    vol        = 0.85 if ftp < 200 else (1.0 if ftp < 280 else 1.15)

    plan = {
        "goal": goal, "weeks": weeks, "ftp": ftp,
        "persona": persona["id"],
        "start_date": start.strftime("%Y-%m-%d"),
        "created_at": datetime.now().isoformat(),
        "event_name": event_name, "event_date": event_date,
        "target_ftp": target_ftp, "target_km": target_km, "target_kg": target_kg,
        "weekly_plans": [],
    }

    for week_num in range(1, weeks + 1):
        tidx       = (week_num - 1) % len(template)
        week_tmpl  = template[tidx]
        phase      = "recovery" if tidx == 3 else ("peak" if week_num >= weeks - 1 else "build")
        week_start = start + timedelta(weeks=week_num - 1)
        days       = []
        week_tss   = 0

        for i, wkey in enumerate(week_tmpl):
            w       = workouts[wkey]
            day_d   = week_start + timedelta(days=i)
            tss     = estimate_tss(wkey, workouts, vol) if wkey != "rest" else 0
            week_tss += tss
            days.append({
                "day": DAYS[i], "date": day_d.strftime("%Y-%m-%d"),
                "workout": wkey, "name": w["name"],
                "description": w["description"],
                "duration_min": w["duration_min"], "tss": tss, "zone": w["zone"],
            })

        plan["weekly_plans"].append({
            "week": week_num, "phase": phase,
            "week_start": week_start.strftime("%Y-%m-%d"),
            "total_tss": week_tss, "days": days,
        })

    return plan


def print_plan(plan, persona):
    p = persona
    print(f"\n{'='*60}")
    print(f"  {p['plan_prefix']} TRAINING PLAN")
    print(f"  Goal: {plan['goal'].upper()}", end="")
    if plan.get("event_name"):
        print(f" — {plan['event_name']}", end="")
    print(f"\n  FTP: {plan['ftp']}W  |  Start: {plan['start_date']}  |  Duration: {plan['weeks']} weeks")
    print(f"  {p['header_quote']}")
    print(f"{'='*60}\n")

    for week in plan["weekly_plans"]:
        print(f"── WEEK {week['week']} ({week['phase'].upper()}) — TSS target: {week['total_tss']} ──")
        for day in week["days"]:
            if day["workout"] == "rest":
                print(f"  {day['day'][:3]} {day['date']}: REST")
            else:
                zs = f"Z{day['zone']}" if day["zone"] > 0 else ""
                print(f"  {day['day'][:3]} {day['date']}: {day['name']} ({day['duration_min']}min {zs}) — TSS {day['tss']}")
                print(f"                 {day['description']}")
        print()


def interactive_setup(persona):
    print(persona["interactive_intro"])

    # ── GOAL ─────────────────────────────────────────────────────────────────
    print("=" * 60)
    print("STEP 1: What is your primary training goal?")
    print("=" * 60)
    print()
    print("  [1] Improve FTP")
    print("      Raise your power threshold. Best if you want to get faster")
    print("      on climbs and sustain harder efforts for longer.")
    print("      Key sessions: threshold intervals, sweet spot, VO2 max.")
    print()
    print("  [2] Prepare for a specific event")
    print("      Build fitness around a race, gran fondo, or sportive date.")
    print("      Plan peaks at your event date. Good for XCO races, marathons,")
    print("      road events, or any goal with a fixed deadline.")
    print()
    print("  [3] Hit a weekly distance target")
    print("      Volume-focused plan. Builds aerobic base and endurance.")
    print("      Best if your goal is to ride more km per week consistently.")
    print()
    print("  [4] Weight loss + base fitness")
    print("      Higher volume, lower intensity. More Zone 2 and long rides.")
    print("      Maximises calorie burn while building sustainable fitness.")
    print()
    print("  [5] General fitness")
    print("      Balanced mix of endurance, tempo, and intensity.")
    print("      Good all-round plan if you have no specific target.")
    print()
    goals = {"1": "ftp", "2": "event", "3": "distance", "4": "weight-loss", "5": "general"}
    choice = input("Enter 1-5: ").strip()
    goal   = goals.get(choice, "general")
    print(f"  → Goal set: {goal}\n")

    # ── FTP ──────────────────────────────────────────────────────────────────
    print("=" * 60)
    print("STEP 2: Your current FTP (Functional Threshold Power)")
    print("=" * 60)
    print()
    print("  FTP is the maximum power you can sustain for ~1 hour.")
    print("  It's the foundation of every training zone in this plan.")
    print()
    print("  How to find your FTP:")
    print("  • 20-min test: ride all-out for 20 min, multiply avg power by 0.95")
    print("  • Ramp test: increase power every minute until failure, take 75% of peak")
    print("  • Estimate from recent rides: hard 1-hour effort avg power ≈ FTP")
    print()
    print("  Typical ranges:")
    print("  • Beginner:     100–180W  (untrained or returning to cycling)")
    print("  • Recreational: 180–250W  (rides regularly, some structured training)")
    print("  • Enthusiast:   250–320W  (trains consistently, races occasionally)")
    print("  • Advanced:     320W+     (serious racer, high training volume)")
    print()
    print("  Enter 0 if unknown — we'll use 200W as a starting estimate.")
    print()
    ftp = int(input("Your FTP in watts: ").strip() or "200")
    if ftp == 0:
        ftp = 200
        print("  → Using 200W as starting estimate.")
    else:
        print(f"  → FTP set: {ftp}W")
    print()

    # ── WEEKS ────────────────────────────────────────────────────────────────
    print("=" * 60)
    print("STEP 3: Plan duration (weeks)")
    print("=" * 60)
    print()
    print("  How long do you want this training block to run?")
    print()
    print("  Recommendations:")
    print("  •  4 weeks — short block, good for a quick fitness boost")
    print("  •  8 weeks — standard block, solid base + intensity phase")
    print("  • 12 weeks — ideal for event prep with full periodization")
    print("  • 16 weeks — serious build, 3 full base→build→peak cycles")
    print("  • 20–24 weeks — full season preparation")
    print()
    print("  Structure: every 4 weeks = 3 build weeks + 1 recovery week.")
    print()
    weeks = int(input("Number of weeks (4–24): ").strip() or "8")
    print(f"  → Duration set: {weeks} weeks\n")

    # ── XCO ──────────────────────────────────────────────────────────────────
    print("=" * 60)
    print("STEP 4: XCO Power Training (optional)")
    print("=" * 60)
    print()
    print("  Cross-country mountain biking demands more than just cycling fitness.")
    print("  XCO races require explosive accelerations, strength on steep climbs,")
    print("  and the ability to control the bike through technical terrain.")
    print()
    print("  If enabled, this adds 2 gym sessions per week:")
    print("  • Max Strength     — heavy squats, deadlifts, split squats")
    print("                       builds raw force for climbing and sprinting")
    print("  • Explosive Power  — jump squats, box jumps, kettlebell swings")
    print("                       trains the fast-twitch snap for accelerations")
    print("  • Strength Endurance — circuits at higher reps")
    print("                       sustains power output through a full XCO race")
    print("  • Core & Coordination — balance, anti-rotation, proprioception")
    print("                       Nino Schurter does this year-round")
    print()
    print("  Also adds bike-specific power sessions:")
    print("  • Torque intervals (big gear, low cadence) — steep climb simulation")
    print("  • Sprint power intervals — race-winning accelerations")
    print("  • Micro-burst intervals — punchy XCO terrain simulation")
    print()
    print("  Recommended if: you race XCO, do technical MTB, or want")
    print("  to improve explosive power alongside cycling fitness.")
    print()
    xco = input("Include XCO power training? [y/N]: ").strip().lower() == "y"
    print(f"  → XCO power training: {'YES' if xco else 'NO'}\n")

    # ── GOAL-SPECIFIC ─────────────────────────────────────────────────────────
    event_name = event_date = target_ftp = target_km = target_kg = None

    if goal == "event":
        print("=" * 60)
        print("STEP 5: Event details")
        print("=" * 60)
        print()
        print("  The plan will periodize toward this date — peaking")
        print("  in the final 1-2 weeks before your event.")
        print()
        event_name = input("Event name (e.g. 'XCO Regional Champs'): ").strip()
        event_date = input("Event date (YYYY-MM-DD, e.g. 2026-06-15): ").strip()
        print(f"  → Event: {event_name} on {event_date}\n")

    elif goal == "ftp":
        print("=" * 60)
        print("STEP 5: FTP target")
        print("=" * 60)
        print()
        print(f"  Your current FTP: {ftp}W")
        print(f"  Realistic gains in {weeks} weeks: +10 to +30W depending on training history.")
        print(f"  First-time structured training: up to +40W possible.")
        print()
        target_ftp = int(input(f"Target FTP in watts [{ftp + 20}]: ").strip() or str(ftp + 20))
        print(f"  → Target FTP: {target_ftp}W (+{target_ftp - ftp}W)\n")

    elif goal == "distance":
        print("=" * 60)
        print("STEP 5: Weekly distance target")
        print("=" * 60)
        print()
        print("  How many km per week do you want to build toward?")
        print()
        print("  Typical targets:")
        print("  •  100 km/week — recreational, 3-4 rides")
        print("  •  150 km/week — enthusiast, 4-5 rides")
        print("  •  200 km/week — dedicated, 5-6 rides")
        print("  •  250km+/week — high volume training")
        print()
        target_km = int(input("Weekly distance target (km): ").strip() or "150")
        print(f"  → Distance target: {target_km} km/week\n")

    elif goal == "weight-loss":
        print("=" * 60)
        print("STEP 5: Weight target")
        print("=" * 60)
        print()
        print("  Your target body weight. Used to track progress.")
        print("  Sustainable loss: 0.5–1 kg per week with proper nutrition.")
        print("  This plan maximises aerobic volume to support fat burning.")
        print()
        target_kg = float(input("Target weight in kg (or 0 to skip): ").strip() or "0")
        if target_kg:
            print(f"  → Target weight: {target_kg} kg\n")

    print("=" * 60)
    print("  Building your plan...")
    print("=" * 60)
    print()

    return goal, weeks, ftp, xco, event_name, event_date, target_ftp, target_km, target_kg


def main():
    parser = argparse.ArgumentParser(description="Generate a cycling training plan")
    parser.add_argument("--interactive",    action="store_true")
    parser.add_argument("--goal",           choices=["ftp","event","distance","weight-loss","general"])
    parser.add_argument("--weeks",          type=int, default=8)
    parser.add_argument("--ftp",            type=int, default=None)
    parser.add_argument("--persona",        type=str, default=None, help="nino / pogi / badger / cannibal")
    parser.add_argument("--xco",            action="store_true", help="Include XCO power training (gym + explosive)")
    parser.add_argument("--list-personas",  action="store_true")
    parser.add_argument("--event-name",     type=str)
    parser.add_argument("--event-date",     type=str)
    parser.add_argument("--target-ftp",     type=int)
    parser.add_argument("--target-km",      type=int)
    parser.add_argument("--target-kg",      type=float)
    parser.add_argument("--show",           action="store_true")
    parser.add_argument("--save",           action="store_true")
    parser.add_argument("--export",         action="store_true")
    args = parser.parse_args()

    if args.list_personas:
        print(list_personas())
        return

    config  = load_config()
    ftp     = args.ftp or config.get("ftp", 220)
    persona = get_persona(args.persona) if args.persona else load_active_persona()

    if args.show:
        if PLAN_FILE.exists():
            plan  = json.loads(PLAN_FILE.read_text())
            p_id  = plan.get("persona", "nino")
            p     = get_persona(p_id)
            if plan.get("xco_power"):
                print_xco_plan(plan, p)
            else:
                print_plan(plan, p)
        else:
            print("No saved plan found. Run with --interactive to create one.")
        return

    if args.interactive:
        goal, weeks, ftp, xco, event_name, event_date, target_ftp, target_km, target_kg = interactive_setup(persona)
    else:
        if not args.goal:
            parser.print_help()
            sys.exit(1)
        goal       = args.goal
        weeks      = args.weeks
        xco        = args.xco
        event_name = args.event_name
        event_date = args.event_date
        target_ftp = args.target_ftp
        target_km  = args.target_km
        target_kg  = args.target_kg

    if xco:
        plan = build_xco_plan(
            goal=goal, weeks=weeks, ftp=ftp, persona=persona,
            event_name=event_name, event_date=event_date, target_ftp=target_ftp,
        )
        print_xco_plan(plan, persona)
    else:
        plan = build_plan(
            goal=goal, weeks=weeks, ftp=ftp, persona=persona,
            event_name=event_name, event_date=event_date,
            target_ftp=target_ftp, target_km=target_km, target_kg=target_kg,
        )
        print_plan(plan, persona)

    if args.save or args.interactive:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        PLAN_FILE.write_text(json.dumps(plan, indent=2))
        print(f"✅ Plan saved to {PLAN_FILE}")

    if args.export:
        out = Path.cwd() / "training_plan.json"
        out.write_text(json.dumps(plan, indent=2))
        print(f"✅ Plan exported to {out}")


if __name__ == "__main__":
    main()

# ═══════════════════════════════════════════════════════════════════════════════
# XCO POWER TRAINING SYSTEM
# Cross-country specific gym + explosive work integrated into cycling plans
# ═══════════════════════════════════════════════════════════════════════════════

XCO_GYM_WORKOUTS = {

    # ── MAX STRENGTH (heavy, low rep) ─────────────────────────────────────────
    "gym_max_strength": {
        "name": "Max Strength — Gym",
        "type": "gym",
        "duration_min": 60,
        "description": (
            "Heavy compound lifts. 4-5 sets × 3-5 reps @ 85-90% 1RM. Full rest 3-4 min between sets.\n"
            "  • Back squat or trap bar deadlift — primary lower body strength\n"
            "  • Bulgarian split squat — single-leg power, hip stability\n"
            "  • Hip thrust — glute drive for climbing power\n"
            "  • Single-leg Romanian deadlift — posterior chain, balance\n"
            "  XCO focus: This builds the raw force you need to accelerate out of corners,\n"
            "  power through technical sections, and sprint to the finish."
        ),
    },

    # ── EXPLOSIVE / POWER (fast, reactive) ────────────────────────────────────
    "gym_explosive": {
        "name": "Explosive Power — Gym",
        "type": "gym",
        "duration_min": 50,
        "description": (
            "Speed-strength work. 4 sets × 4-6 reps. Move the weight as fast as possible.\n"
            "  • Jump squats with light load (30% 1RM) — rate of force development\n"
            "  • Box jumps 3×6 — explosive hip extension\n"
            "  • Medicine ball rotational throw — torso power for technical terrain\n"
            "  • Kettlebell swing — hip hinge explosiveness\n"
            "  • Depth drops → jump — reactive strength, critical for XCO descents\n"
            "  XCO focus: XCO racing demands repeated explosive efforts — accelerations,\n"
            "  sprint sections, rock gardens. This is where you build that snap."
        ),
    },

    # ── STRENGTH ENDURANCE (moderate load, higher rep circuit) ────────────────
    "gym_strength_endurance": {
        "name": "Strength Endurance — Gym",
        "type": "gym",
        "duration_min": 55,
        "description": (
            "Circuit-style. 3-4 rounds, 10-15 reps, 60-90s rest between rounds.\n"
            "  • Goblet squat × 15\n"
            "  • Step-ups with dumbbells × 12 each leg\n"
            "  • Single-leg press × 12 each\n"
            "  • Nordic hamstring curl × 8 (injury prevention, critical for cyclists)\n"
            "  • Lateral band walks × 20 each — hip abductor strength\n"
            "  • Plank variations 3×45s\n"
            "  XCO focus: Mirrors the repeated efforts of a 1.5-2hr XCO race.\n"
            "  Trains muscles to produce force when already fatigued."
        ),
    },

    # ── CORE & COORDINATION (technical, balance-based) ────────────────────────
    "gym_core_coordination": {
        "name": "Core & Coordination — Gym",
        "type": "gym",
        "duration_min": 45,
        "description": (
            "Technical control work. 3 sets each, focus on quality not load.\n"
            "  • Single-leg deadlift on balance pad — proprioception\n"
            "  • Pallof press — anti-rotation core stability\n"
            "  • Dead bug variations — lumbar stability under load\n"
            "  • Copenhagen plank — adductor strength (often neglected)\n"
            "  • Bosu ball squat — unstable surface balance\n"
            "  • Band pull-apart / face pulls — shoulder health\n"
            "  XCO focus: Nino Schurter does this year-round. A mountain biker needs\n"
            "  power AND coordination simultaneously — on the bike and off it."
        ),
    },

    # ── ON-BIKE POWER (torque / low cadence) ──────────────────────────────────
    "bike_torque": {
        "name": "Torque / Low-Cadence Intervals",
        "type": "bike",
        "duration_min": 60,
        "description": (
            "On the bike. 5-6 × 5 min at 50-60 rpm @ Zone 3-4 power. 3 min easy between.\n"
            "  Forces maximum muscle recruitment per pedal stroke.\n"
            "  Best done on a climb or trainer in a big gear.\n"
            "  XCO focus: Replicates the grinding effort of steep technical climbs\n"
            "  where cadence drops and raw leg strength determines the outcome."
        ),
    },

    # ── ON-BIKE SPRINTS (neuromuscular, pure power) ───────────────────────────
    "bike_sprints": {
        "name": "Sprint Power Intervals",
        "type": "bike",
        "duration_min": 60,
        "description": (
            "After 20 min warm-up: 8-10 × 10-15 sec all-out sprints. Full recovery 3-4 min.\n"
            "  Start from rolling speed (~20 km/h). Wind up through the gears. Maximum effort.\n"
            "  Track peak power if possible — aim to maintain across all efforts.\n"
            "  XCO focus: Race-winning accelerations — out of corners, re-starts after\n"
            "  technical sections, final sprint. Pure neuromuscular power."
        ),
    },

    # ── ON-BIKE MICRO-BURSTS ──────────────────────────────────────────────────
    "bike_microbursts": {
        "name": "Micro-Burst Intervals",
        "type": "bike",
        "duration_min": 60,
        "description": (
            "3-4 sets of 10 min blocks: alternate 15 sec ON (130-150% FTP) / 15 sec OFF (50% FTP).\n"
            "  10 min easy between blocks.\n"
            "  Brutal but specific — mirrors the punchy, variable power of XCO terrain.\n"
            "  XCO focus: XCO courses are never smooth. This trains your body to recover\n"
            "  between efforts while maintaining overall speed."
        ),
    },

    # ── REST (gym day) ────────────────────────────────────────────────────────
    "rest": {
        "name": "Rest Day",
        "type": "rest",
        "duration_min": 0,
        "description": "Complete rest. No gym, no bike. Sleep well, eat well.",
    },
}

# XCO-integrated weekly templates
# Format: list of 7 days, each is (workout_key, source)
# source = "cycling" uses main WORKOUTS_BASE, source = "xco" uses XCO_GYM_WORKOUTS
XCO_PLAN_TEMPLATES = {
    # ── BASE PHASE (weeks 1-3 of each 4-week block) ───────────────────────────
    "xco_base": [
        # Sun              Mon               Tue                     Wed          Thu                         Fri                           Sat
        [("rest","x"), ("z2_base","c"),  ("gym_max_strength","x"),("rest","x"), ("z2_base","c"),         ("gym_core_coordination","x"), ("long_ride","c")],
        [("rest","x"), ("z2_base","c"),  ("gym_max_strength","x"),("rest","x"), ("bike_torque","x"),      ("gym_strength_endurance","x"),("long_ride","c")],
        [("rest","x"), ("z2_base","c"),  ("gym_explosive","x"),   ("rest","x"), ("sweet_spot","c"),       ("gym_core_coordination","x"), ("long_ride","c")],
        [("rest","x"), ("recovery","c"), ("gym_core_coordination","x"),("rest","x"),("recovery","c"),     ("rest","x"),                  ("z2_base","c")],
    ],

    # ── BUILD PHASE (higher intensity, more XCO specifics) ───────────────────
    "xco_build": [
        [("rest","x"), ("z2_base","c"),  ("gym_max_strength","x"),("rest","x"), ("bike_torque","x"),      ("gym_explosive","x"),         ("long_ride","c")],
        [("rest","x"), ("z2_base","c"),  ("gym_explosive","x"),   ("rest","x"), ("vo2_intervals","c"),    ("gym_strength_endurance","x"),("long_ride","c")],
        [("rest","x"), ("z2_base","c"),  ("gym_max_strength","x"),("rest","x"), ("bike_microbursts","x"), ("gym_explosive","x"),         ("long_ride","c")],
        [("rest","x"), ("recovery","c"), ("gym_core_coordination","x"),("rest","x"),("recovery","c"),     ("rest","x"),                  ("z2_base","c")],
    ],

    # ── PEAK / PRE-RACE (sharpen, reduce gym volume) ─────────────────────────
    "xco_peak": [
        [("rest","x"), ("z2_base","c"),  ("gym_explosive","x"),          ("rest","x"), ("bike_sprints","x"),     ("gym_core_coordination","x"), ("long_ride","c")],
        [("rest","x"), ("z2_base","c"),  ("gym_explosive","x"),          ("rest","x"), ("bike_microbursts","x"), ("gym_core_coordination","x"), ("long_ride","c")],
        [("rest","x"), ("z2_base","c"),  ("gym_core_coordination","x"),  ("rest","x"), ("bike_sprints","x"),     ("rest","x"),                  ("sweet_spot","c")],
        [("rest","x"), ("recovery","c"), ("rest","x"),                   ("rest","x"), ("recovery","c"),         ("rest","x"),                  ("z2_base","c")],
    ],
}

# Which template phase to use by week number
def get_xco_phase_template(week_num, total_weeks):
    """Select XCO phase based on position in plan."""
    progress = week_num / total_weeks
    cycle_pos = (week_num - 1) % 4  # 0-3, where 3 = recovery
    if cycle_pos == 3:
        # Always use recovery week from whichever phase we're in
        if progress < 0.5:
            return XCO_PLAN_TEMPLATES["xco_base"][3]
        elif progress < 0.8:
            return XCO_PLAN_TEMPLATES["xco_build"][3]
        else:
            return XCO_PLAN_TEMPLATES["xco_peak"][3]
    else:
        if progress < 0.4:
            return XCO_PLAN_TEMPLATES["xco_base"][cycle_pos]
        elif progress < 0.75:
            return XCO_PLAN_TEMPLATES["xco_build"][cycle_pos]
        else:
            return XCO_PLAN_TEMPLATES["xco_peak"][cycle_pos]


def build_xco_plan(goal, weeks, ftp, persona, start_date=None,
                   event_name=None, event_date=None, target_ftp=None):
    """Build an XCO-integrated training plan with gym + bike sessions."""
    cycling_workouts = get_workouts(persona)
    start = start_date or datetime.today()
    # Align to Sunday (weekday 6)
    days_to_sunday = (6 - start.weekday()) % 7
    start = start + timedelta(days=days_to_sunday)
    vol   = 0.85 if ftp < 200 else (1.0 if ftp < 280 else 1.15)

    plan = {
        "goal": goal, "weeks": weeks, "ftp": ftp,
        "persona": persona["id"],
        "xco_power": True,
        "start_date": start.strftime("%Y-%m-%d"),
        "created_at": datetime.now().isoformat(),
        "event_name": event_name,
        "event_date": event_date,
        "target_ftp": target_ftp,
        "weekly_plans": [],
    }

    for week_num in range(1, weeks + 1):
        cycle_pos  = (week_num - 1) % 4
        phase_name = "recovery" if cycle_pos == 3 else (
            "peak" if week_num / weeks >= 0.75 else
            ("build" if week_num / weeks >= 0.4 else "base")
        )
        week_start   = start + timedelta(weeks=week_num - 1)
        week_template = get_xco_phase_template(week_num, weeks)
        days = []
        week_tss = 0

        for i, (wkey, src) in enumerate(week_template):
            day_d = week_start + timedelta(days=i)

            if src == "c":
                # Cycling workout
                w = cycling_workouts.get(wkey, cycling_workouts["rest"])
                tss = int((w["duration_min"] / 60) * w["tss_per_hour"] * vol) if wkey != "rest" else 0
                wtype = "bike"
            else:
                # XCO gym/power workout
                w = XCO_GYM_WORKOUTS.get(wkey, XCO_GYM_WORKOUTS["rest"])
                tss = 30 if w["type"] == "gym" else (
                      int((w["duration_min"] / 60) * 85 * vol) if w["type"] == "bike" else 0
                )
                wtype = w["type"]

            week_tss += tss
            days.append({
                "day":          DAYS[i],
                "date":         day_d.strftime("%Y-%m-%d"),
                "workout":      wkey,
                "name":         w["name"],
                "description":  w["description"],
                "duration_min": w["duration_min"],
                "tss":          tss,
                "type":         wtype,
            })

        plan["weekly_plans"].append({
            "week":       week_num,
            "phase":      phase_name,
            "week_start": week_start.strftime("%Y-%m-%d"),
            "total_tss":  week_tss,
            "days":       days,
        })

    return plan


def print_xco_plan(plan, persona):
    p = persona
    print(f"\n{'='*65}")
    print(f"  {p['plan_prefix']} XCO POWER TRAINING PLAN")
    print(f"  Goal: {plan['goal'].upper()}", end="")
    if plan.get("event_name"):
        print(f" — {plan['event_name']}", end="")
    print(f"\n  FTP: {plan['ftp']}W  |  Start: {plan['start_date']}  |  {plan['weeks']} weeks")
    print(f"  Includes: Cycling + Gym Strength + Explosive Power")
    print(f"  {p['header_quote']}")
    print(f"{'='*65}\n")

    for week in plan["weekly_plans"]:
        gym_days  = sum(1 for d in week["days"] if d.get("type") == "gym")
        bike_days = sum(1 for d in week["days"] if d.get("type") == "bike")
        print(f"── WEEK {week['week']} ({week['phase'].upper()}) — TSS: {week['total_tss']}  |  🚴 {bike_days} rides  💪 {gym_days} gym ──")
        for day in week["days"]:
            t = day.get("type", "rest")
            if t == "rest":
                print(f"  {day['day'][:3]} {day['date']}: REST")
            elif t == "gym":
                print(f"  {day['day'][:3]} {day['date']}: 💪 {day['name']} ({day['duration_min']}min)")
                # Print first line of description only
                first_line = day['description'].split('\n')[0]
                print(f"                 {first_line}")
            else:
                zs = f"Z{day.get('zone','?')}" if day.get("zone") else ""
                print(f"  {day['day'][:3]} {day['date']}: 🚴 {day['name']} ({day['duration_min']}min {zs}) — TSS {day['tss']}")
                first_line = day['description'].split('\n')[0]
                print(f"                 {first_line}")
        print()

    # Phase summary
    print("── PHASE STRUCTURE ──")
    print("  Weeks 1-40%:   BASE  — Max strength + aerobic foundation")
    print("  Weeks 40-75%:  BUILD — Explosive power + high intensity bike")
    print("  Weeks 75-100%: PEAK  — Race-specific sprints + taper gym volume")
    print()