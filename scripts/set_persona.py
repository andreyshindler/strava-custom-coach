#!/usr/bin/env python3
"""
set_persona.py — Choose your cycling coach persona.
Usage:
    ./scripts/set_persona.py              # Interactive selector
    ./scripts/set_persona.py nino         # Set directly
    ./scripts/set_persona.py --list       # List all personas
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
from personas import PERSONAS, save_active_persona, load_active_persona, list_personas


def interactive_select():
    persona_list = list(PERSONAS.values())
    current = load_active_persona()

    print("\n🚴 Strava Cycling Coach — Choose Your Coach\n")
    print("Who do you want in your ear on every ride?\n")

    for i, p in enumerate(persona_list, 1):
        marker = " ← active" if p["id"] == current["id"] else ""
        print(f"  [{i}] {p['label']}{marker}")
        print(f"       {p['tagline']}\n")

    choice = input("Enter number (or press Enter to keep current): ").strip()
    if not choice:
        print(f"\n✅ Keeping current coach: {current['name']}")
        return

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(persona_list):
            selected = persona_list[idx]
            save_active_persona(selected["id"])
            print(f"\n✅ Coach set to: {selected['name']}")
            print(f"\n{selected['greeting']}")
        else:
            print("Invalid selection.")
    except ValueError:
        print("Invalid input.")


def main():
    if "--list" in sys.argv or "-l" in sys.argv:
        print(list_personas())
        current = load_active_persona()
        print(f"  Active: {current['name']} (--persona {current['id']})\n")
        return

    if len(sys.argv) >= 2 and not sys.argv[1].startswith("-"):
        persona_id = sys.argv[1].lower()
        if persona_id in PERSONAS:
            save_active_persona(persona_id)
            p = PERSONAS[persona_id]
            print(f"\n✅ Coach set to: {p['name']}\n")
            print(p["greeting"])
        else:
            print(f"Unknown persona '{persona_id}'. Run with --list to see options.")
        return

    interactive_select()


if __name__ == "__main__":
    main()
