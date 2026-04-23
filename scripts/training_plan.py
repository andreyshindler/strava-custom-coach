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
    7: (1.50, 9.99,  "Neuromuscular"),
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


# ═══════════════════════════════════════════════════════════════════════════════
# XCO RACING PLANS
# Structured race-prep plans by category: Beginner / Intermediate / Advanced / Pro
# Fixed phase structures (not repeating 4-week cycles)
# ═══════════════════════════════════════════════════════════════════════════════

XCO_RACING_WORKOUTS = {
    # ── REST ──────────────────────────────────────────────────────────────────
    "rest": {
        "name": "Rest Day", "duration_min": 0, "tss_per_hour": 0, "zone": 0,
        "type": "rest", "description": "Complete rest.",
    },

    # ── BEGINNER ──────────────────────────────────────────────────────────────
    "xco_active_recovery": {
        "name": "Active Recovery Spin", "duration_min": 30, "tss_per_hour": 20,
        "zone": 1, "type": "bike",
        "description": "Very easy spin, Z1 only. Flush the legs, no effort.",
    },
    "xco_z1_z2_mtb": {
        "name": "Z1-Z2 MTB Ride", "duration_min": 50, "tss_per_hour": 40,
        "zone": 2, "type": "bike",
        "description": "Easy trail ride, stay in Z1-Z2. Focus on smooth pedalling and body position.",
    },
    "xco_core_mobility": {
        "name": "Core & Mobility", "duration_min": 30, "tss_per_hour": 0,
        "zone": 0, "type": "gym",
        "description": "Plank, dead bug, hip mobility, band work. Keep it light and controlled.",
    },
    "xco_z2_road": {
        "name": "Z2 Road/Gravel Spin", "duration_min": 60, "tss_per_hour": 50,
        "zone": 2, "type": "bike",
        "description": "Steady Z2 on road or gravel. Aerobic base. Keep HR and power in check.",
    },
    "xco_mtb_skills_long": {
        "name": "Z2 MTB Trail Ride 90 min", "duration_min": 90, "tss_per_hour": 50,
        "zone": 2, "type": "bike",
        "description": "90 min trail ride, Z2 effort. Practice cornering and trail flow.",
    },
    "xco_z2_tempo": {
        "name": "Z2 + 2x8 min Z3 Tempo", "duration_min": 75, "tss_per_hour": 65,
        "zone": 3, "type": "bike",
        "description": "Warm up 20 min, then 2x8 min at Z3 tempo pace with 5 min easy between. Cool down.",
    },
    "xco_strength": {
        "name": "Strength: Squats/Deadlifts/Lunges", "duration_min": 45, "tss_per_hour": 0,
        "zone": 0, "type": "gym",
        "description": "3x10 goblet squat, 3x8 Romanian deadlift, 3x10 reverse lunge each leg.",
    },
    "xco_z2_endurance": {
        "name": "Z2 Endurance 75 min", "duration_min": 75, "tss_per_hour": 50,
        "zone": 2, "type": "bike",
        "description": "Steady Z2 endurance ride. Build aerobic base. No hard efforts.",
    },
    "xco_mtb_skills_2hr": {
        "name": "MTB Skills + 2hr Z2 Ride", "duration_min": 120, "tss_per_hour": 50,
        "zone": 2, "type": "bike",
        "description": "2 hrs on trail, mostly Z2. Spend 20 min on skills: corners, drops, rock gardens.",
    },
    "xco_z1_spin": {
        "name": "Z1 Recovery Spin", "duration_min": 45, "tss_per_hour": 25,
        "zone": 1, "type": "bike",
        "description": "Easy 45 min spin. Z1 only. Active recovery between harder sessions.",
    },
    "xco_threshold_4x5": {
        "name": "4x5 min Z4 Threshold", "duration_min": 60, "tss_per_hour": 90,
        "zone": 4, "type": "bike",
        "description": "Warm up 15 min, 4x5 min at Z4 (91-105% FTP), 3 min easy between. Cool down.",
    },
    "xco_strength_core": {
        "name": "Strength + Core", "duration_min": 45, "tss_per_hour": 0,
        "zone": 0, "type": "gym",
        "description": "Squat 3x8, hip thrust 3x10, plank 3x45s, dead bug 3x10 each side.",
    },
    "xco_z2_z3_sprints": {
        "name": "Z2-Z3 + 3x2 min Z5 Sprints", "duration_min": 75, "tss_per_hour": 75,
        "zone": 5, "type": "bike",
        "description": "45 min Z2-Z3 then 3x2 min at Z5 (106-120% FTP) with 3 min full recovery between.",
    },
    "xco_race_sim": {
        "name": "Race Simulation - XCO Laps", "duration_min": 105, "tss_per_hour": 90,
        "zone": 4, "type": "bike",
        "description": "3-4 laps of a loop at race effort. Include technical sections. Practice pacing.",
    },
    "xco_z1_long": {
        "name": "Z1 Long Easy Ride", "duration_min": 75, "tss_per_hour": 30,
        "zone": 1, "type": "bike",
        "description": "75 min very easy. Z1 only. Legs should feel fresh at the end.",
    },
    "xco_threshold_3x5": {
        "name": "3x5 min Z4 Threshold", "duration_min": 50, "tss_per_hour": 85,
        "zone": 4, "type": "bike",
        "description": "Warm up 15 min, 3x5 min at Z4, 3 min easy between. Short but sharp.",
    },
    "xco_z1_z2_easy": {
        "name": "Easy Z1-Z2 Ride 60 min", "duration_min": 60, "tss_per_hour": 40,
        "zone": 2, "type": "bike",
        "description": "Easy 60 min, Z1-Z2. Keep the legs moving without adding fatigue.",
    },
    "xco_z6_sprints": {
        "name": "Z2 Ride + 4x30s Z6 Sprints", "duration_min": 60, "tss_per_hour": 60,
        "zone": 6, "type": "bike",
        "description": "40 min Z2 then 4x30 sec all-out Z6 sprints with 3 min easy between. Race sharpness.",
    },
    "xco_pre_race": {
        "name": "Pre-Race Openers 45 min", "duration_min": 45, "tss_per_hour": 45,
        "zone": 2, "type": "bike",
        "description": "45 min easy with 3x30 sec accelerations to race pace. Get the legs firing.",
    },
    "xco_race_day": {
        "name": "RACE DAY", "duration_min": 90, "tss_per_hour": 100,
        "zone": 5, "type": "bike",
        "description": "Race day. Warm up 20 min, full effort on course.",
    },

    # ── INTERMEDIATE ──────────────────────────────────────────────────────────
    "xco_z1_easy_60": {
        "name": "Easy Z1 Ride 60 min", "duration_min": 60, "tss_per_hour": 25,
        "zone": 1, "type": "bike",
        "description": "Very easy 60 min. Z1 only. Active recovery or off-season base.",
    },
    "xco_z2_road_90": {
        "name": "Z2 Road/Gravel 90 min", "duration_min": 90, "tss_per_hour": 50,
        "zone": 2, "type": "bike",
        "description": "90 min steady Z2 on road or gravel. No intensity. Pure aerobic base.",
    },
    "xco_gym_lower_body": {
        "name": "Gym: Squat / RDL / Split Squat", "duration_min": 60, "tss_per_hour": 0,
        "zone": 0, "type": "gym",
        "description": "Back squat 4x6, Romanian deadlift 4x6, split squat 3x8 each leg. Heavy.",
    },
    "xco_z2_mtb_tech": {
        "name": "Z2 MTB - Technical Terrain 90 min", "duration_min": 90, "tss_per_hour": 50,
        "zone": 2, "type": "bike",
        "description": "90 min trail ride on technical terrain. Z2 effort. Skills under control.",
    },
    "xco_gym_upper_lower": {
        "name": "Gym: Hip Thrust / Bench / Pull-ups", "duration_min": 55, "tss_per_hour": 0,
        "zone": 0, "type": "gym",
        "description": "Hip thrust 4x8, bench press 3x8, pull-ups 3x6, core circuit 3 rounds.",
    },
    "xco_long_z2_mtb": {
        "name": "Long Z2 MTB Ride 2.5 hrs", "duration_min": 150, "tss_per_hour": 50,
        "zone": 2, "type": "bike",
        "description": "2.5 hrs on trail, all Z2. Maximum aerobic volume for this phase.",
    },
    "xco_threshold_4x8": {
        "name": "4x8 min Z4 Threshold", "duration_min": 75, "tss_per_hour": 90,
        "zone": 4, "type": "bike",
        "description": "Warm up 15 min. 4x8 min at Z4 (91-105% FTP), 4 min easy between. Power meter required.",
    },
    "xco_z2_endurance_90": {
        "name": "Z2 Endurance 90 min", "duration_min": 90, "tss_per_hour": 50,
        "zone": 2, "type": "bike",
        "description": "90 min Z2. Pair with gym session if scheduled same day.",
    },
    "xco_z2_z3_mtb": {
        "name": "Z2-Z3 MTB + 2x15 min Z3 Blocks", "duration_min": 90, "tss_per_hour": 65,
        "zone": 3, "type": "bike",
        "description": "MTB ride with 2x15 min Z3 tempo blocks (5 min easy between). Technical terrain preferred.",
    },
    "xco_skills_long": {
        "name": "XCO Skills + Long Z2/Z3 Ride 2.5 hrs", "duration_min": 150, "tss_per_hour": 60,
        "zone": 3, "type": "bike",
        "description": "2.5 hrs with 20-30 min dedicated to skills: corners, technical climbs, drops.",
    },
    "xco_z2_recovery_70": {
        "name": "Z2 Active Recovery 70 min", "duration_min": 70, "tss_per_hour": 45,
        "zone": 2, "type": "bike",
        "description": "Easy 70 min, low end Z2. Flush the legs from weekend intensity.",
    },
    "xco_vo2_6x3": {
        "name": "6x3 min Z5 VO2max", "duration_min": 65, "tss_per_hour": 95,
        "zone": 5, "type": "bike",
        "description": "Warm up 15 min. 6x3 min at Z5 (110-115% FTP), 3 min easy between. Hard but controlled.",
    },
    "xco_z2_gym_maint": {
        "name": "Z2 75 min + Gym Maintenance", "duration_min": 75, "tss_per_hour": 50,
        "zone": 2, "type": "bike",
        "description": "Z2 ride 75 min, then 30 min gym maintenance: squat, hip thrust, core.",
    },
    "xco_threshold_2x20": {
        "name": "2x20 min Z4 Threshold", "duration_min": 60, "tss_per_hour": 90,
        "zone": 4, "type": "bike",
        "description": "Warm up 10 min. 2x20 min at Z4 (91-105% FTP), 5 min easy between. Sustained effort.",
    },
    "xco_race_sim_hard": {
        "name": "Race Simulation - Hard XCO Laps 2 hrs", "duration_min": 135, "tss_per_hour": 90,
        "zone": 4, "type": "bike",
        "description": "4-5 hard laps on a technical course. Race-pace effort. Measure each lap.",
    },
    "xco_z1_z2_long_90": {
        "name": "Z1-Z2 Long Easy 90 min", "duration_min": 90, "tss_per_hour": 35,
        "zone": 2, "type": "bike",
        "description": "Easy 90 min, Z1-Z2. Recovery after hard week.",
    },
    "xco_race_openers": {
        "name": "Race Openers: Z2 + 4x1 min Z5", "duration_min": 60, "tss_per_hour": 60,
        "zone": 5, "type": "bike",
        "description": "40 min Z2, then 4x1 min at Z5 race pace with 3 min easy between. Get sharp.",
    },
    "xco_z1_recovery_60": {
        "name": "Easy Z1 Recovery 60 min", "duration_min": 60, "tss_per_hour": 25,
        "zone": 1, "type": "bike",
        "description": "Very easy 60 min. Z1 only. Pre-race or post-race recovery.",
    },
    "xco_threshold_2x15": {
        "name": "2x15 min Z4 Threshold", "duration_min": 50, "tss_per_hour": 85,
        "zone": 4, "type": "bike",
        "description": "Warm up 10 min. 2x15 min at Z4, 5 min easy between. Race-week sharpener.",
    },
    "xco_pre_race_short": {
        "name": "Pre-Race: Easy + 3x30s Openers", "duration_min": 30, "tss_per_hour": 45,
        "zone": 2, "type": "bike",
        "description": "30 min easy with 3x30 sec accelerations to race pace. Leg prep before tomorrow.",
    },

    # ── ADVANCED ──────────────────────────────────────────────────────────────
    "xco_easy_run": {
        "name": "Easy Run 30-45 min", "duration_min": 40, "tss_per_hour": 30,
        "zone": 1, "type": "gym",
        "description": "Easy off-bike run 30-45 min. Z1-Z2 effort. Cross-training for off-season.",
    },
    "xco_pump_track": {
        "name": "Pump Track - No Seatpost", "duration_min": 60, "tss_per_hour": 35,
        "zone": 2, "type": "bike",
        "description": "60 min pump track riding, seatpost all the way down. Pure body position and flow.",
    },
    "xco_gym_max_strength": {
        "name": "Gym: Max Strength - Heavy Compound", "duration_min": 60, "tss_per_hour": 0,
        "zone": 0, "type": "gym",
        "description": "Back squat 4x4, trap bar deadlift 4x4, split squat 3x5 each. 85-90% 1RM. Full rest.",
    },
    "xco_z2_gravel_2hr": {
        "name": "Z2 Gravel/Road 2 hrs", "duration_min": 120, "tss_per_hour": 50,
        "zone": 2, "type": "bike",
        "description": "2 hrs Z2 on road or gravel. Easy aerobic maintenance during transition phase.",
    },
    "xco_gym_posterior_core": {
        "name": "Gym: Posterior Chain + Core + Upper", "duration_min": 60, "tss_per_hour": 0,
        "zone": 0, "type": "gym",
        "description": "Hip thrust 4x8, single-leg RDL 3x8 each, Nordic curl 3x6, Pallof press, pull-ups.",
    },
    "xco_long_mtb_3hr": {
        "name": "Long MTB Z1-Z2 Skills Focus 3 hrs", "duration_min": 180, "tss_per_hour": 48,
        "zone": 2, "type": "bike",
        "description": "3 hrs on trail, all Z1-Z2. No power targets. Skills focus: corners, drops, flow.",
    },
    "xco_z2_2hr_z3_blocks": {
        "name": "Z2 2 hrs + 2x20 min Z3 Blocks", "duration_min": 120, "tss_per_hour": 60,
        "zone": 3, "type": "bike",
        "description": "Z2 ride with 2x20 min Z3 tempo blocks embedded. 5 min easy between blocks.",
    },
    "xco_gym_maint_z2": {
        "name": "Gym Maintenance + Z2 90 min", "duration_min": 90, "tss_per_hour": 50,
        "zone": 2, "type": "bike",
        "description": "30 min gym maintenance (squat, hip thrust, core), then Z2 ride 90 min.",
    },
    "xco_threshold_5x8": {
        "name": "5x8 min Z4 Threshold", "duration_min": 80, "tss_per_hour": 90,
        "zone": 4, "type": "bike",
        "description": "Warm up 15 min. 5x8 min at Z4 (91-105% FTP), 3 min easy between. All reps same power.",
    },
    "xco_long_trail_z2": {
        "name": "Long MTB XCO Trail 3-4 hrs Z2", "duration_min": 210, "tss_per_hour": 50,
        "zone": 2, "type": "bike",
        "description": "3-4 hrs on technical XCO trail, all Z2. Volume is the goal. Fuelling practice.",
    },
    "xco_vo2_8x2_micro": {
        "name": "8x2 min Z5-Z6 / 30-15 Micro-Intervals", "duration_min": 65, "tss_per_hour": 95,
        "zone": 6, "type": "bike",
        "description": "Option A: 8x2 min at Z5-Z6 (2 min rest). Option B: 20x30 sec Z6 / 15 sec Z1 x 3 sets.",
    },
    "xco_z2_gym_circuit": {
        "name": "Z2 90 min + Gym Power-Endurance Circuit", "duration_min": 90, "tss_per_hour": 50,
        "zone": 2, "type": "bike",
        "description": "Z2 ride 90 min, then gym power-endurance circuit: goblet squat, step-ups, KB swing.",
    },
    "xco_threshold_z7_sprints": {
        "name": "2x20 min Z4 + 6x30s Z7 Sprints", "duration_min": 75, "tss_per_hour": 95,
        "zone": 7, "type": "bike",
        "description": "2x20 min Z4 threshold, then tag 6x30 sec all-out Z7 sprints after. Neuromuscular finish.",
    },
    "xco_race_sim_full_gas": {
        "name": "Race Sim Full Gas 2.5-3 hrs", "duration_min": 165, "tss_per_hour": 90,
        "zone": 5, "type": "bike",
        "description": "Full-gas race simulation 2.5-3 hrs on technical XCO course. Lap each loop.",
    },
    "xco_z2_long_2hr": {
        "name": "Long Z2 Endurance 2-2.5 hrs", "duration_min": 135, "tss_per_hour": 50,
        "zone": 2, "type": "bike",
        "description": "2-2.5 hrs easy Z2 endurance. Recovery after hard week or post race-sim.",
    },
    "xco_threshold_3x15": {
        "name": "3x15 min Z4 Cruise Intervals", "duration_min": 70, "tss_per_hour": 88,
        "zone": 4, "type": "bike",
        "description": "Warm up 10 min. 3x15 min at Z4 (FTP), 4 min easy between. Sustained threshold.",
    },
    "xco_skills_tech_90": {
        "name": "Technical Skills 90 min - Fast Corners", "duration_min": 90, "tss_per_hour": 45,
        "zone": 3, "type": "bike",
        "description": "90 min dedicated to technical skills at pace: high-speed corners, rock gardens, roots.",
    },
    "xco_race_sim_short_4x10": {
        "name": "Short Race Sim: 4x10 min XCO Laps", "duration_min": 75, "tss_per_hour": 90,
        "zone": 4, "type": "bike",
        "description": "4x10 min XCO lap efforts at max sustainable pace. 3 min easy between.",
    },
    "xco_training_race": {
        "name": "Open A-Race / Training Race", "duration_min": 120, "tss_per_hour": 90,
        "zone": 5, "type": "bike",
        "description": "Race a local event or high-quality group ride at race intensity. Calibration race.",
    },
    "xco_z2_2hr_recovery": {
        "name": "Z2 2 hrs Recovery", "duration_min": 120, "tss_per_hour": 48,
        "zone": 2, "type": "bike",
        "description": "Easy 2 hrs Z2. Recovery ride after race or race simulation.",
    },
    "xco_vo2_4x5": {
        "name": "4x5 min Z5 - Sharp", "duration_min": 50, "tss_per_hour": 92,
        "zone": 5, "type": "bike",
        "description": "Warm up 10 min. 4x5 min at Z5 (106-115% FTP), 3 min easy between. Taper sharpener.",
    },
    "xco_z6_openers": {
        "name": "Easy 30 min + 3x1 min Z6 Openers", "duration_min": 35, "tss_per_hour": 50,
        "zone": 6, "type": "bike",
        "description": "30 min easy, then 3x1 min at Z6 with full recovery. Open up the legs.",
    },
    "xco_travel_spin": {
        "name": "Travel + Course Recon Easy Spin", "duration_min": 45, "tss_per_hour": 30,
        "zone": 1, "type": "bike",
        "description": "Easy spin on course or road. Recon the track. Keep it very easy.",
    },
    "xco_race_start_practice": {
        "name": "20 min + 5x10s Race-Start Practice", "duration_min": 20, "tss_per_hour": 40,
        "zone": 6, "type": "bike",
        "description": "20 min easy, then 5 explosive standing starts from 0. UCI XCO is won in the first 200m.",
    },

    # ── PRO / ELITE ───────────────────────────────────────────────────────────
    "xco_fun_ride": {
        "name": "Fun Ride - BMX/Pump Track (no data)", "duration_min": 60, "tss_per_hour": 35,
        "zone": 2, "type": "bike",
        "description": "No HR, no power. BMX, pump track, dirt jumps. Ride for fun. Mental reset.",
    },
    "xco_gym_mobility": {
        "name": "Gym: Mobility + Movement Screening", "duration_min": 60, "tss_per_hour": 0,
        "zone": 0, "type": "gym",
        "description": "Full body mobility, movement screening, injury prevention. No load.",
    },
    "xco_z1_z2_cross_training": {
        "name": "Z1-Z2 Ride / Run / Swim 90 min", "duration_min": 90, "tss_per_hour": 30,
        "zone": 2, "type": "bike",
        "description": "Cross-training: easy run, swim, or Z1-Z2 ride. 90 min. Mental variety.",
    },
    "xco_gym_max_strength_elite": {
        "name": "Gym: Max Strength - Heavy Lifts (Elite)", "duration_min": 70, "tss_per_hour": 0,
        "zone": 0, "type": "gym",
        "description": "Trap bar deadlift 5x3, back squat 5x3, split squat 4x4. >90% 1RM. Full rest 5 min.",
    },
    "xco_group_mtb_3hr": {
        "name": "Group MTB Ride 3 hrs - Social/Skills", "duration_min": 180, "tss_per_hour": 48,
        "zone": 2, "type": "bike",
        "description": "Social group MTB ride 3 hrs. No power targets. Skills, fun, mental recovery.",
    },
    "xco_z2_road_2hr": {
        "name": "Z2 Road Recovery 2 hrs", "duration_min": 120, "tss_per_hour": 50,
        "zone": 2, "type": "bike",
        "description": "2 hrs Z2 road ride. Easy aerobic work. Daily volume building block.",
    },
    "xco_z2_z3_mtb_3hr": {
        "name": "Z2-Z3 MTB 3 hrs + 2x20 min Z3", "duration_min": 180, "tss_per_hour": 60,
        "zone": 3, "type": "bike",
        "description": "3 hr MTB ride with 2x20 min Z3 tempo blocks. Technical terrain preferred.",
    },
    "xco_gym_am_z2_pm": {
        "name": "Gym AM + Z2 Road 2 hrs PM", "duration_min": 120, "tss_per_hour": 50,
        "zone": 2, "type": "bike",
        "description": "Morning gym: max strength or explosive. Afternoon: 2 hrs Z2 road. Two-a-day.",
    },
    "xco_threshold_5x10": {
        "name": "5x10 min Z4 Threshold", "duration_min": 90, "tss_per_hour": 90,
        "zone": 4, "type": "bike",
        "description": "Warm up 15 min. 5x10 min at Z4 (91-105% FTP), 4 min rest. Power meter target.",
    },
    "xco_z1_flush": {
        "name": "Z1 Active Recovery Flush 60-75 min", "duration_min": 65, "tss_per_hour": 20,
        "zone": 1, "type": "bike",
        "description": "60-75 min very easy Z1. Active flush after hard day. Keep HR low.",
    },
    "xco_long_trail_4_5hr": {
        "name": "Long XCO Trail 4-5 hrs All Z2", "duration_min": 270, "tss_per_hour": 50,
        "zone": 2, "type": "bike",
        "description": "4-5 hrs on technical XCO trail, all Z2. Maximum aerobic volume. Fuel and hydrate properly.",
    },
    "xco_z2_road_2hr_gym": {
        "name": "Z2 Road 2 hrs + Optional Gym", "duration_min": 120, "tss_per_hour": 50,
        "zone": 2, "type": "bike",
        "description": "2 hrs Z2 road, then optional 30 min gym maintenance if legs allow.",
    },
    "xco_z1_z2_easy_90": {
        "name": "Z1-Z2 Easy 90 min", "duration_min": 90, "tss_per_hour": 35,
        "zone": 2, "type": "bike",
        "description": "Easy 90 min, Z1-Z2. Between hard days. Flush and recover.",
    },
    "xco_vo2_10x2_or_40_20": {
        "name": "10x2 min Z5-Z6 / 40-20 Intervals x20", "duration_min": 75, "tss_per_hour": 95,
        "zone": 6, "type": "bike",
        "description": "Option A: 10x2 min at Z5-Z6 (2 min rest). Option B: 20x40 sec Z6 / 20 sec Z1 x 3 sets, 5 min between.",
    },
    "xco_z2_2_5hr_gym": {
        "name": "Z2 Endurance 2.5 hrs + Gym", "duration_min": 150, "tss_per_hour": 50,
        "zone": 2, "type": "bike",
        "description": "2.5 hrs Z2, then 30-40 min gym strength maintenance.",
    },
    "xco_threshold_2x30": {
        "name": "2x30 min Z4 Threshold", "duration_min": 80, "tss_per_hour": 90,
        "zone": 4, "type": "bike",
        "description": "Warm up 10 min. 2x30 min at Z4 (91-105% FTP), 8 min easy between. Elite standard.",
    },
    "xco_race_or_sim_full": {
        "name": "XCO Race or Simulation + Z2 Cooldown", "duration_min": 180, "tss_per_hour": 80,
        "zone": 5, "type": "bike",
        "description": "Race or full-gas race simulation 2-2.5 hrs, then 30 min Z2 cooldown.",
    },
    "xco_long_z2_mtb_3_4hr": {
        "name": "Long Z2 MTB 3-4 hrs", "duration_min": 210, "tss_per_hour": 50,
        "zone": 2, "type": "bike",
        "description": "3-4 hrs Z2 MTB. Long aerobic ride. Volume is the stimulus.",
    },
    "xco_sim_4laps": {
        "name": "XCO Sim: 4 Hard Laps Race-Pace", "duration_min": 90, "tss_per_hour": 90,
        "zone": 5, "type": "bike",
        "description": "4 full laps at race pace on a technical XCO course. Time each lap. Consistent power output.",
    },
    "xco_z2_skills_2hr": {
        "name": "Z2 2 hrs + Specific Skills", "duration_min": 120, "tss_per_hour": 52,
        "zone": 2, "type": "bike",
        "description": "2 hrs Z2 with 20-30 min focused skill work: rock gardens, steep technical climbs.",
    },
    "xco_z7_microbursts": {
        "name": "Micro-Bursts: 3x8x20s Z7 / 40s Z2", "duration_min": 55, "tss_per_hour": 95,
        "zone": 7, "type": "bike",
        "description": "3 sets of 8x20 sec Z7 (>150% FTP) / 40 sec Z2. 5 min easy between sets.",
    },
    "xco_prerace_openers_1min": {
        "name": "Pre-Race: 60 min + 4x1 min Openers", "duration_min": 60, "tss_per_hour": 55,
        "zone": 5, "type": "bike",
        "description": "60 min with 4x1 min at race pace (Z5) openers. 3 min easy between. Get sharp.",
    },
    "xco_z1_flush_45": {
        "name": "Easy Z1 Flush 45 min", "duration_min": 45, "tss_per_hour": 20,
        "zone": 1, "type": "bike",
        "description": "45 min very easy Z1. Post-race flush or pre-hard-day primer.",
    },
    "xco_race_sharp": {
        "name": "Race-Sharp: 5x5 min Z5 + Z7 Sprints", "duration_min": 60, "tss_per_hour": 95,
        "zone": 7, "type": "bike",
        "description": "5x5 min at Z5 (110% FTP) then 6x10 sec Z7 all-out sprints. Race-week sharpener.",
    },
    "xco_course_recon": {
        "name": "Course Recon - Full Lap + Line Selection", "duration_min": 60, "tss_per_hour": 35,
        "zone": 2, "type": "bike",
        "description": "Full course lap at easy pace. Identify lines, braking points, technical sections.",
    },
    "xco_z2_mental_rehearsal": {
        "name": "Z2 90 min + Visualization Session", "duration_min": 90, "tss_per_hour": 45,
        "zone": 2, "type": "bike",
        "description": "Z2 ride 90 min, followed by 15-20 min visualization of race-day execution.",
    },
    "xco_race_start_5x": {
        "name": "Easy 45 min + Race-Start Practice x5", "duration_min": 45, "tss_per_hour": 40,
        "zone": 6, "type": "bike",
        "description": "45 min easy, then 5x explosive race-start from standstill. UCI XCO won in first 200m.",
    },
    "xco_openers_30sec": {
        "name": "30 min Easy + 3x30 sec Openers", "duration_min": 30, "tss_per_hour": 45,
        "zone": 6, "type": "bike",
        "description": "30 min easy with 3x30 sec race-pace openers. Leg primer before race day.",
    },
}


XCO_RACING_PLANS = {
    "beginner": {
        "label": "Beginner XCO", "category": "Cat 4-3",
        "weeks": 16, "hours_range": "4-8 hrs/week", "tss_range": "150-300 TSS/week",
        "phases": [
            {"name": "pre_base",   "label": "Pre-Base",   "week_range": (1, 3),
             "template": ["xco_active_recovery","rest","xco_z1_z2_mtb","xco_core_mobility","xco_z2_road","rest","xco_mtb_skills_long"]},
            {"name": "base_build", "label": "Base Build", "week_range": (4, 9),
             "template": ["xco_z1_spin","rest","xco_z2_tempo","xco_strength","xco_z2_endurance","rest","xco_mtb_skills_2hr"]},
            {"name": "build",      "label": "Build",      "week_range": (10, 13),
             "template": ["xco_z1_long","rest","xco_threshold_4x5","xco_strength_core","xco_z2_z3_sprints","rest","xco_race_sim"]},
            {"name": "race_prep",  "label": "Race Prep",  "week_range": (14, 16),
             "template": ["rest","rest","xco_threshold_3x5","xco_z1_z2_easy","xco_z6_sprints","rest","xco_pre_race"],
             "final_week_sunday": "xco_race_day"},
        ],
    },
    "intermediate": {
        "label": "Intermediate XCO", "category": "Cat 2-1",
        "weeks": 20, "hours_range": "8-12 hrs/week", "tss_range": "300-550 TSS/week",
        "phases": [
            {"name": "off_season_base", "label": "Off-Season Base", "week_range": (1, 4),
             "template":          ["xco_z1_easy_60","rest","xco_z2_road_90","xco_gym_lower_body","xco_z2_mtb_tech","xco_gym_upper_lower","xco_long_z2_mtb"],
             "recovery_template": ["rest","rest","xco_z2_road_90","rest","xco_z2_mtb_tech","rest","xco_z1_easy_60"],
             "recovery_weeks": [4]},
            {"name": "base",        "label": "Base",        "week_range": (5, 12),
             "template": ["xco_z2_recovery_70","rest","xco_threshold_4x8","xco_z2_endurance_90","xco_z2_z3_mtb","rest","xco_skills_long"]},
            {"name": "build",       "label": "Build",       "week_range": (13, 17),
             "template": ["xco_z1_z2_long_90","rest","xco_vo2_6x3","xco_z2_gym_maint","xco_threshold_2x20","rest","xco_race_sim_hard"]},
            {"name": "race_season", "label": "Race Season", "week_range": (18, 20),
             "template": ["xco_race_day","rest","xco_race_openers","xco_z1_recovery_60","xco_threshold_2x15","rest","xco_pre_race_short"]},
        ],
    },
    "advanced": {
        "label": "Advanced XCO", "category": "Cat 1 / Elite Amateur",
        "weeks": 24, "hours_range": "12-16 hrs/week", "tss_range": "500-750 TSS/week",
        "phases": [
            {"name": "transition",     "label": "Transition / Off-Season", "week_range": (1, 4),
             "template": ["xco_easy_run","rest","xco_pump_track","xco_gym_max_strength","xco_z2_gravel_2hr","xco_gym_posterior_core","xco_long_mtb_3hr"]},
            {"name": "base",           "label": "Base - 80/20 Polarized",  "week_range": (5, 10),
             "template": ["xco_z2_road_90","rest","xco_z2_2hr_z3_blocks","xco_gym_maint_z2","xco_threshold_5x8","rest","xco_long_trail_z2"]},
            {"name": "specific_build", "label": "Specific Build",           "week_range": (11, 18),
             "template":          ["xco_z2_long_2hr","rest","xco_vo2_8x2_micro","xco_z2_gym_circuit","xco_threshold_z7_sprints","rest","xco_race_sim_full_gas"],
             "recovery_template": ["xco_z2_road_90","rest","xco_z2_2hr_z3_blocks","rest","xco_threshold_5x8","rest","xco_z2_long_2hr"],
             "recovery_weeks": [14, 18]},
            {"name": "pre_race_build", "label": "Pre-Race Build",           "week_range": (19, 22),
             "template": ["xco_z2_2hr_recovery","rest","xco_threshold_3x15","xco_skills_tech_90","xco_race_sim_short_4x10","xco_z1_z2_easy","xco_training_race"]},
            {"name": "taper",          "label": "Taper & Peak",             "week_range": (23, 24),
             "template": ["rest","rest","xco_vo2_4x5","xco_z1_z2_easy","xco_z6_openers","xco_travel_spin","xco_race_start_practice"],
             "final_week_sunday": "xco_race_day"},
        ],
    },
    "pro_elite": {
        "label": "Pro / Elite XCO", "category": "World Cup / National Elite",
        "weeks": 32, "hours_range": "15-25 hrs/week", "tss_range": "700-1100 TSS/week",
        "phases": [
            {"name": "active_recovery",     "label": "Active Recovery Block",  "week_range": (1, 3),
             "template": ["rest","rest","xco_fun_ride","xco_gym_mobility","xco_z1_z2_cross_training","xco_gym_max_strength_elite","xco_group_mtb_3hr"]},
            {"name": "base_1",              "label": "Base I - CTL 60-100+",   "week_range": (4, 9),
             "template": ["xco_z2_road_2hr_gym","xco_z2_road_2hr","xco_z2_z3_mtb_3hr","xco_gym_am_z2_pm","xco_threshold_5x10","xco_z1_flush","xco_long_trail_4_5hr"]},
            {"name": "base_2",              "label": "Base II - Polarized",    "week_range": (10, 16),
             "template": ["xco_long_z2_mtb_3_4hr","xco_z1_z2_easy_90","xco_vo2_10x2_or_40_20","xco_z2_2_5hr_gym","xco_threshold_2x30","xco_z1_recovery_60","xco_race_or_sim_full"]},
            {"name": "race_specific_build", "label": "Race-Specific Build",    "week_range": (17, 24),
             "template":          ["xco_z1_flush_45","xco_active_recovery","xco_sim_4laps","xco_z2_skills_2hr","xco_z7_microbursts","xco_prerace_openers_1min","xco_race_day"],
             "recovery_template": ["xco_z1_flush_45","xco_active_recovery","xco_z2_road_2hr","xco_z2_skills_2hr","xco_z1_z2_easy_90","xco_prerace_openers_1min","xco_race_day"],
             "recovery_weeks": [20, 24]},
            {"name": "championship_peak",   "label": "Championship Peak",      "week_range": (25, 32),
             "template": ["rest","rest","xco_race_sharp","xco_course_recon","xco_z2_mental_rehearsal","xco_race_start_5x","xco_openers_30sec"],
             "final_week_sunday": "xco_race_day"},
        ],
    },
}


def build_xco_racing_plan(category, ftp, persona, start_date=None):
    """Build a structured XCO racing plan by category (beginner/intermediate/advanced/pro_elite)."""
    meta  = XCO_RACING_PLANS[category]
    weeks = meta["weeks"]
    start = start_date or datetime.today()
    days_to_sunday = (6 - start.weekday()) % 7
    start = start + timedelta(days=days_to_sunday)
    vol   = 0.85 if ftp < 200 else (1.0 if ftp <= 280 else 1.15)

    plan = {
        "goal": "xco_racing", "xco_category": category, "xco_power": True,
        "weeks": weeks, "ftp": ftp, "persona": persona["id"],
        "start_date": start.strftime("%Y-%m-%d"),
        "created_at": datetime.now().isoformat(),
        "weekly_plans": [],
    }

    rest_day = {
        "name": "Rest Day", "duration_min": 0, "tss_per_hour": 0,
        "zone": 0, "type": "rest", "description": "",
    }

    for week_num in range(1, weeks + 1):
        phase = next(p for p in meta["phases"]
                     if p["week_range"][0] <= week_num <= p["week_range"][1])
        is_recovery   = week_num in phase.get("recovery_weeks", [])
        tmpl_key      = "recovery_template" if is_recovery else "template"
        template      = phase[tmpl_key]
        final_sun_key = phase.get("final_week_sunday") if week_num == weeks else None

        week_start = start + timedelta(weeks=week_num - 1)
        days = []
        week_tss = 0

        for i, wkey in enumerate(template):
            if i == 0 and final_sun_key:
                wkey = final_sun_key
            day_d = week_start + timedelta(days=i)
            w     = XCO_RACING_WORKOUTS.get(wkey, rest_day)
            wtype = w.get("type", "rest")
            if wtype == "gym":
                tss = 30
            elif wtype == "bike":
                tss = int((w["duration_min"] / 60) * w["tss_per_hour"] * vol)
            else:
                tss = 0
            week_tss += tss
            days.append({
                "day": DAYS[i], "date": day_d.strftime("%Y-%m-%d"),
                "workout": wkey, "name": w["name"],
                "description": w.get("description", ""),
                "duration_min": w["duration_min"], "tss": tss,
                "zone": w.get("zone", 0), "type": wtype,
            })

        plan["weekly_plans"].append({
            "week": week_num, "phase": phase["name"],
            "phase_label": phase["label"],
            "week_start": week_start.strftime("%Y-%m-%d"),
            "total_tss": week_tss, "days": days,
        })

    return plan


def analyse_rides_for_plan(activities, known_ftp=200):
    """Analyse last 90 days of rides to auto-suggest plan parameters."""
    MTB_TYPES = {"MountainBikeRide", "EMountainBikeRide"}
    CYCLING_TYPES = {"Ride", "VirtualRide", "MountainBikeRide", "GravelRide",
                     "EBikeRide", "EMountainBikeRide", "Handcycle", "Velomobile"}

    cutoff = datetime.now() - timedelta(days=90)
    recent = []
    for a in activities:
        try:
            d = datetime.strptime(a.get("start_date", "")[:10], "%Y-%m-%d")
        except (ValueError, TypeError):
            continue
        if d >= cutoff and (a.get("sport_type") in CYCLING_TYPES or a.get("type") in CYCLING_TYPES):
            recent.append((d, a))
    if not recent:
        return None

    recent.sort(key=lambda x: x[0])
    ride_count = len(recent)
    span_days = max((recent[-1][0] - recent[0][0]).days, 7)
    rides_per_week = round(ride_count / (span_days / 7), 1)

    # FTP estimation
    est_ftp, ftp_source = None, "no power data"
    power_rides = [(d, a) for d, a in recent if a.get("average_watts", 0) > 50]
    if power_rides:
        med = [(d, a) for d, a in power_rides if 2700 <= a.get("moving_time", 0) <= 5400]
        if med:
            est_ftp = int(max(a["average_watts"] for _, a in med))
            ftp_source = f"best {len(med)}-ride 45–90 min effort"
        else:
            est_ftp = int(max(a["average_watts"] for _, a in power_rides) * 0.88)
            ftp_source = "estimated from power history"

    # Weekly TSS (inline formula to avoid circular import with strava_api)
    ftp_ref = est_ftp or known_ftp
    weekly: dict = {}
    for d, a in recent:
        wk = d.strftime("%Y-W%W")
        dur = a.get("moving_time", 0)
        avg_watts = a.get("average_watts")
        if avg_watts and ftp_ref:
            np_est = avg_watts * 1.05
            if_ = np_est / ftp_ref
            tss = (dur * np_est * if_) / (ftp_ref * 3600) * 100
        else:
            hr = a.get("average_heartrate", 0)
            if hr:
                tss = (dur / 3600) * 50 * min(hr / 160, 1.2)
            else:
                tss = (dur / 3600) * 45
        weekly[wk] = weekly.get(wk, 0) + round(tss)
    avg_weekly_tss = int(sum(weekly.values()) / len(weekly)) if weekly else 0

    # Ride type mix
    mtb_count = sum(1 for _, a in recent
                    if a.get("sport_type") in MTB_TYPES or a.get("type") in MTB_TYPES)
    mtb_pct = mtb_count / ride_count
    primary_type = "mtb" if mtb_pct >= 0.6 else ("mixed" if mtb_pct >= 0.3 else "road")

    # Suggestions
    suggested_goal = (
        "xco_racing" if primary_type in ("mtb", "mixed") and avg_weekly_tss >= 150
        else ("ftp" if avg_weekly_tss >= 250 else "general")
    )
    suggested_category = (
        "pro_elite"    if avg_weekly_tss >= 700 else
        "advanced"     if avg_weekly_tss >= 450 else
        "intermediate" if avg_weekly_tss >= 250 else
        "beginner"
    )
    suggested_weeks = (
        20 if rides_per_week >= 5 and avg_weekly_tss >= 400 else
        16 if rides_per_week >= 4 and avg_weekly_tss >= 250 else
        12 if rides_per_week >= 3 else 8
    )

    return {
        "ride_count":         ride_count,
        "rides_per_week":     rides_per_week,
        "avg_weekly_tss":     avg_weekly_tss,
        "mtb_pct":            round(mtb_pct * 100),
        "primary_type":       primary_type,
        "est_ftp":            est_ftp,
        "ftp_source":         ftp_source,
        "has_power":          bool(power_rides),
        "suggested_goal":     suggested_goal,
        "suggested_category": suggested_category,
        "suggested_weeks":    suggested_weeks,
        "suggested_xco":      primary_type in ("mtb", "mixed"),
    }


def adjust_future_weeks(plan, scale_factor, start_week_idx, *, horizon=None):
    """Rescale TSS in-place for future plan weeks.

    Modifies plan["weekly_plans"][i]["total_tss"] and each day's "tss" by
    multiplying by scale_factor (rounded to int).  Does not touch dates,
    workout names, or any other fields.

    Args:
        plan:            training plan dict (mutated in place)
        scale_factor:    multiplicative factor, e.g. 0.85 or 1.10
        start_week_idx:  index into plan["weekly_plans"] to start from (inclusive)
        horizon:         if given, only rescale this many weeks; None = all remaining
    """
    weeks = plan.get("weekly_plans", [])
    end_idx = start_week_idx + horizon if horizon is not None else len(weeks)
    for i in range(start_week_idx, min(end_idx, len(weeks))):
        week = weeks[i]
        week["total_tss"] = round(week.get("total_tss", 0) * scale_factor)
        for day in week.get("days", []):
            day["tss"] = round(day.get("tss", 0) * scale_factor)