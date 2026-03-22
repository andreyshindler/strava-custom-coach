"""
personas.py — Coaching persona definitions for the Strava Cycling Coach.

Each persona captures the voice, philosophy, and training beliefs of a legendary
cyclist. Used by analyze_ride.py, training_plan.py, and the Telegram monitor.
"""

import random


def pick_feedback(zone_feedback: dict, zone: str) -> str:
    """Return a random quote for the given zone. Values may be a str or list[str]."""
    v = zone_feedback.get(zone, "")
    if isinstance(v, list):
        return random.choice(v)
    return v


PERSONAS = {

    # ─────────────────────────────────────────────────────────────────────────
    "nino": {
        "id": "nino",
        "name": "Nino Schurter",
        "label": "🏔️  N1NO — The Swiss Precision Machine",
        "tagline": "10x XCO World Champion | Olympic Gold Rio 2016",
        "greeting": (
            "🏔️  N1NO Coaching Mode\n"
            "   10x XCO World Champion | Olympic Gold Rio 2016\n"
            "   \"Make sure you are aware of your target and develop a strategy.\n"
            "    A routine you can depend on. That is mental fitness.\"\n"
        ),
        "header_quote": "\"Every race is like training and preparation.\" — Nino Schurter",
        "zone_feedback": {
            "z1": [
                "Good recovery ride. This is how you build the base — long, easy, aerobic. "
                "75% of my training is exactly like this. Sleep well tonight, eat well. "
                "Let your body react to the stimuli.",

                "Active recovery. Don't underestimate these sessions — the adaptation happens here, "
                "not during the hard work. Keep it easy. Protect your legs for what's coming.",
                
                "Easy day done. This is how champions train when nobody is watching. "
                "Consistency with these builds everything else."
            ],
            "z2": [
                "Solid endurance work. Bread and butter — the kind of session that builds "
                "champions over years, not weeks. Stay consistent with these.",

                "Good aerobic session. This is the foundation. You can't build intensity "
                "on a weak base — these rides are the investment that pays off in race season.",

                "Zone 2 done. Perfect. In the Swiss mountains I do these for hours. "
                "No shortcuts here. Keep showing up.",
            ],
            "z3": [
                "Tempo effort. Good training stimulus. Hard enough to make you stronger, "
                "so recover properly. Sleep well, eat well tonight. Don't add more intensity tomorrow.",

                "Solid tempo. Your body is adapting right now that means you need to give it the chance to. Rest and food tonight.",

                "Good work in the tempo zone. This teaches the body to keep working when it wants to stop. "
                "Recovery now is as important as the session itself."
            ],
            "z4": [
                "Threshold work. This is where you get faster. Quality session — "
                "but this is exactly why only 20% of training should be this intense. "
                "Every aspect of recovery matters now: sleep, nutrition, rest.",

                "Strong threshold effort. You pushed your ceiling today. "
                "Now let the body absorb it — sleep, nutrition, no shortcuts. "
                "That's how threshold work actually makes you faster.",

                "Good intensity. This is uncomfortable for a reason — it's working. "
                "Now be as disciplined with recovery as you were with the effort."
            ],
            "z5": [
                "High intensity. Really strong effort. This raises your ceiling but only if you recover from it. "
                "Today and tomorrow: sleep well, eat well. No shortcuts.",

                "VO2 work done. You stretched what's possible today. "
                "That adaptation only happens if you protect the next 48 hours sleep is the most important training tool you have.",

                "Maximum effort. This is race-level intensity. "
                "Mentally you're learning to tolerate uncomfortable situations that matters as much as the physical stress. Recover like a champion."
            ],
            "no_ftp": "Add your FTP with --ftp and I can give you real feedback on this ride.",
        },
        "workout_notes": {
            "z2_base":        "Easy aerobic ride — you should be able to hold a full conversation. "
                              "This is the foundation. 75% of my training is exactly this. Don't underestimate it.",
            "long_ride":      "Your key session of the week. Keep it Zone 2 the whole way. "
                              "This builds your aerobic engine. In the Swiss mountains I do these for hours — "
                              "there are no shortcuts here.",
            "sweet_spot":     "2-3 × 15-20 min at 88-93% FTP with 5 min recovery. "
                              "Highly time-efficient. If your time is limited, this is the session I recommend. Really effective.",
            "threshold_2x20": "2 × 20 min at 95-105% FTP with 5 min recovery. "
                              "This is the core FTP builder. Hard, uncomfortable — "
                              "but this is exactly where you get faster. Stay focused.",
            "vo2_intervals":  "5-6 × 3-5 min at 110-120% FTP with equal recovery. "
                              "This raises your ceiling. On a mental level you learn to "
                              "tolerate uncomfortable situations — that matters in a race.",
            "recovery":       "Very easy — Zone 1 only, 30-45 min. "
                              "The adaptation happens during recovery, not during the training. "
                              "Respect this session as much as the hard ones.",
            "tempo":          "Sustained effort at 76-90% FTP. "
                              "Teaches your body to keep working when it wants to stop.",
            "rest":           "Complete rest. I train 6 days a week and protect my one rest day completely. "
                              "Sleep well, eat well. This is part of the training.",
        },
        "plan_prefix": "N1NO",
        "interactive_intro": (
            "🏔️  N1NO Cycling Coach — Training Plan Builder\n"
            "   \"Make sure you are aware of your target and develop a strategy.\n"
            "    A routine you can depend on. That is mental fitness.\" — Nino Schurter\n"
        ),
        "coach_label": "💬 N1NO Says",
    },

    # ─────────────────────────────────────────────────────────────────────────
    "pogi": {
        "id": "pogi",
        "name": "Tadej Pogačar",
        "label": "☀️  POGI — The Joyful Cannibal",
        "tagline": "4x Tour de France | Triple Crown 2024 | Redefining the possible",
        "greeting": (
            "☀️  POGI Coaching Mode\n"
            "   4x Tour de France | Triple Crown 2024\n"
            "   \"Cycling is happiness. If stress is greater than happiness, "
            "you've got everything wrong.\"\n"
        ),
        "header_quote": "\"I like to live in the moment. Keep having fun — that's the most important thing.\" — Tadej Pogačar",
        "zone_feedback": {
            "z1": (
                "Perfect. I love Zone 2. When I'm in Slovenia or Spain on the flat roads, "
                "I stay here for five hours and I genuinely enjoy every minute. "
                "This is where the engine gets built. Fuel well, sleep well."
            ),
            "z2": (
                "Good endurance session! This is the real work — don't let anyone tell you "
                "easy rides are wasted time. You're building something here. Keep smiling out there!"
            ),
            "z3": (
                "Nice tempo effort. Solid work. Now recover properly — "
                "the fun continues tomorrow only if you treat tonight right. "
                "Eat, sleep, repeat."
            ),
            "z4": (
                "Threshold! That's where it hurts, right? Good. That uncomfortable feeling "
                "is you getting faster. I visualise race situations during these — "
                "sometimes before a race when I can't sleep, I imagine exactly this. "
                "It pays off. Recover well tonight."
            ),
            "z5": (
                "Full gas! That's the spirit. In training I go ridiculously hard sometimes — "
                "my teammates say I ride 2 km/h faster than everyone and think nothing of it. "
                "But even I need to recover. Eat plenty tonight, sleep like a champion."
            ),
            "no_ftp": "Tell me your FTP and I'll give you real feedback. Numbers help, even if I sometimes ride by feel!",
        },
        "workout_notes": {
            "z2_base":        "Easy and happy. Zone 2 is where I spend most of my time — "
                              "and I genuinely love it. Put on some music, enjoy the road, build your engine.",
            "long_ride":      "My favourite session. Long, easy, joyful. "
                              "The day before Strade Bianche, my whole team played football in the hotel garden — "
                              "and I won the race next day. Fun is part of the training.",
            "sweet_spot":     "Efficient and effective. 88-93% FTP for 15-20 minutes. "
                              "Do this when time is short but you still want to make it count.",
            "threshold_2x20": "Hard but rewarding. 2 × 20 min near your limit. "
                              "I think about race situations when it gets tough — what happens at the final climb? "
                              "Stay mentally in it.",
            "vo2_intervals":  "Full gas intervals! 5-6 × 3-5 min all out. "
                              "This is where you raise the ceiling. Embrace the suffering — it's only temporary.",
            "recovery":       "Easy spin — feel free, move the legs, no pressure. "
                              "Recovery is not wasted time. It's when you actually get stronger. Enjoy it!",
            "tempo":          "Sustained push at tempo. Good for race simulation — "
                              "training your body and mind to hold effort when it's not comfortable.",
            "rest":           "Rest day! I spend this time with family, friends, maybe a bit of padel. "
                              "Detach from the bike fully. You'll come back fresher and more motivated.",
        },
        "plan_prefix": "POGI",
        "interactive_intro": (
            "☀️  POGI Cycling Coach — Training Plan Builder\n"
            "   \"Cycling makes you happy. The right question isn't why I'm always happy,\n"
            "    but why others aren't.\" — Tadej Pogačar\n"
        ),
        "coach_label": "💬 POGI Says",
    },

    # ─────────────────────────────────────────────────────────────────────────
    "badger": {
        "id": "badger",
        "name": "Bernard Hinault",
        "label": "🦡  THE BADGER — No Excuses, No Prisoners",
        "tagline": "5x Tour de France | Patron of the Peloton | As long as I breathe, I attack",
        "greeting": (
            "🦡  THE BADGER Coaching Mode\n"
            "   5x Tour de France | The Last Patron\n"
            "   \"I race to win, not to please people.\"\n"
        ),
        "header_quote": "\"As long as I breathe, I attack.\" — Bernard Hinault",
        "zone_feedback": {
            "z1": (
                "Recovery ride. Fine. Do it. But do not mistake easy for unimportant — "
                "even I had to recover. The Badger still wore his heart rate monitor "
                "and kept it disciplined. Zone 1 means Zone 1. Not Zone 2. Not 'a little harder.' Zone 1."
            ),
            "z2": (
                "Base work. Good. You have to suffer to win — but you also have to build the base "
                "so the suffering means something. Ride long, ride easy, be consistent. "
                "Don't be impatient."
            ),
            "z3": (
                "Tempo. Acceptable. Now — did you commit fully, or did you drift in and out "
                "of the zone when it got uncomfortable? "
                "Uncomfortable is the point. You have to be prepared to suffer. That's the only way to win."
            ),
            "z4": (
                "Threshold. Now we're talking. This is where champions are made. "
                "Pain is only temporary. When it hurts, that's when you can make a difference. "
                "I never backed down from pain. Neither should you."
            ),
            "z5": (
                "Maximum effort. Excellent. When I didn't feel good in a race, my reaction was to attack. "
                "Not wait. Not hope. ATTACK. Bring that same aggression to your training. "
                "Now go eat and sleep. You've earned it."
            ),
            "no_ftp": "You should know your FTP. Do a test. A champion knows their numbers.",
        },
        "workout_notes": {
            "z2_base":        "Long easy ride. Discipline. Stay in Zone 2 — "
                              "no drifting into 3 because you feel good. Control is strength.",
            "long_ride":      "The longest ride of the week. Non-negotiable. "
                              "When I was racing, I trained in all conditions — rain, cold, everything. "
                              "You build toughness here as much as fitness.",
            "sweet_spot":     "88-93% FTP for 15-20 min. Hard but sustainable. "
                              "No quitting in the middle of an interval. Finish what you started.",
            "threshold_2x20": "2 × 20 minutes at threshold. This is the signature session. "
                              "I used to attack on descents — you need to be strong to do that. "
                              "This is how you build that strength.",
            "vo2_intervals":  "Maximum intensity. Short intervals, full commitment. "
                              "There's a terrible delight in pushing to your absolute limit — find it.",
            "recovery":       "Easy. And I mean EASY. Don't be a hero on recovery days. "
                              "Those who go too hard every day don't win in the end.",
            "tempo":          "Sustained tempo effort. Hold it. When it hurts, hold it. "
                              "That's the whole point.",
            "rest":           "Rest. I was a farmer after cycling — I know what real work looks like. "
                              "Your body needs this. Take it seriously. Don't sneak in extra sessions.",
        },
        "plan_prefix": "BADGER",
        "interactive_intro": (
            "🦡  THE BADGER Cycling Coach — Training Plan Builder\n"
            "   \"In cycling, there are only two things: pain and reward.\n"
            "    You have to be prepared to suffer. That's the only way to win.\" — Bernard Hinault\n"
        ),
        "coach_label": "💬 The Badger Says",
    },

    # ─────────────────────────────────────────────────────────────────────────
    "cannibal": {
        "id": "cannibal",
        "name": "Eddy Merckx",
        "label": "🐺  THE CANNIBAL — Insatiable, Relentless, Complete",
        "tagline": "525 career wins | 5x Tour de France | The Greatest of All Time",
        "greeting": (
            "🐺  THE CANNIBAL Coaching Mode\n"
            "   525 Career Wins | The Greatest of All Time\n"
            "   \"Cyclists live with pain. If you can't handle it, you will win nothing.\"\n"
        ),
        "header_quote": "\"Ride as much or as little, or as long or as short as you feel. But ride.\" — Eddy Merckx",
        "zone_feedback": {
            "z1": (
                "Recovery. Good. Even I recovered. But I also trained from February 1st "
                "to October 31st every year and competed for everything. "
                "You need the base. Ride. Always ride."
            ),
            "z2": (
                "Solid base work. I never thought one thing was beneath me — "
                "I trained on flat roads, in mountains, in time trials, in the classics. "
                "This is the foundation. Don't skip it."
            ),
            "z3": (
                "Tempo. Good effort. I won in solo breakaways, in time trials, in the mountains. "
                "Versatility comes from sessions like this. Make sure you are honest about "
                "whether you truly held the effort."
            ),
            "z4": (
                "Threshold. Strong work. Cycling is a good school for life — "
                "it makes you hard and gives you ambition. "
                "When it's hurting you, that's when you can make a difference. "
                "You did the right thing today."
            ),
            "z5": (
                "Maximum effort. This is how I won 525 races. "
                "I had a talent for suffering, which I thought was just as important "
                "as a talent for riding. You've earned your rest tonight."
            ),
            "no_ftp": "Ride. Then test your FTP. Then ride more. Simple.",
        },
        "workout_notes": {
            "z2_base":        "Aerobic foundation. I raced from February to October — "
                              "this is what kept me going all season long. Stay easy. Build the engine.",
            "long_ride":      "Long ride. The cornerstone session. I was never bothered by numbers — "
                              "I just rode. Make it long, keep it honest, and do it consistently.",
            "sweet_spot":     "Sweet spot intervals. Efficient and effective. "
                              "Cycling is a good school for life — learn to be uncomfortable here.",
            "threshold_2x20": "Threshold intervals. Core strength work. "
                              "I won time trials, sprints, climbs — all built on sessions like this.",
            "vo2_intervals":  "High intensity intervals. I attacked. I broke away. "
                              "This is where you build the capacity to do the same.",
            "recovery":       "Recovery ride. Easy. You need to absorb the training you've done. "
                              "Ride easy or don't ride. No in-between today.",
            "tempo":          "Tempo effort. Sustained discomfort. "
                              "I always thought the pressure of being number one made me tired — "
                              "but I used it. Use this session the same way.",
            "rest":           "Rest day. Not something I gave often. But even champions need it. "
                              "Sleep well. Eat well. Come back hungry.",
        },
        "plan_prefix": "CANNIBAL",
        "interactive_intro": (
            "🐺  THE CANNIBAL Coaching Plan Builder\n"
            "   \"Cycling is a good school for life.\n"
            "    It makes you hard and gives you ambition.\" — Eddy Merckx\n"
        ),
        "coach_label": "💬 The Cannibal Says",
    },
}

DEFAULT_PERSONA = "nino"


def get_persona(persona_id: str) -> dict:
    """Return persona dict by id, falling back to default."""
    return PERSONAS.get(persona_id, PERSONAS[DEFAULT_PERSONA])


def list_personas() -> str:
    """Return a formatted list of available personas."""
    lines = ["\nAvailable coaching personas:\n"]
    for pid, p in PERSONAS.items():
        lines.append(f"  {p['label']}")
        lines.append(f"  └─ use: --persona {pid}\n")
    return "\n".join(lines)


def load_active_persona(config_file=None) -> dict:
    """Load the saved active persona from config, or return default."""
    import json
    from pathlib import Path
    if config_file is None:
        config_file = Path.home() / ".config" / "strava" / "config.json"
    if config_file.exists():
        config = json.loads(config_file.read_text())
        persona_id = config.get("persona", DEFAULT_PERSONA)
        return get_persona(persona_id)
    return get_persona(DEFAULT_PERSONA)


def save_active_persona(persona_id: str, config_file=None):
    """Save persona choice to config."""
    import json
    from pathlib import Path
    if config_file is None:
        config_file = Path.home() / ".config" / "strava" / "config.json"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config = {}
    if config_file.exists():
        config = json.loads(config_file.read_text())
    config["persona"] = persona_id
    config_file.write_text(json.dumps(config, indent=2))
