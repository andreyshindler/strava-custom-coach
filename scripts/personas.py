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
                "Consistency with these builds everything else.",

                "Zone 1 — perfect discipline. I've been doing this for over 20 years at the top. "
                "You don't stay there by going hard every day. You stay there by being smart. Today was smart.",

                "Recovery spin. In Graubünden after a hard block I ride the valley roads like this — "
                "flat, easy, no agenda. Your body needs this signal. Give it time to rebuild.",

                "Easy ride done. Some athletes feel guilty going this slow. Don't. "
                "I won 10 World Championships by respecting recovery as much as intensity. "
                "This is part of the system.",

                "Good Zone 1 session. The Swiss approach to training is precision — "
                "easy when it should be easy, hard when it should be hard. No grey zone. "
                "You followed the plan today.",

                "Active recovery in the books. Nutrition matters even more on easy days — "
                "your body is repairing muscle, building mitochondria, adapting. "
                "Feed it properly tonight.",

                "Light spin done. I use days like this to think about race tactics, visualise courses, "
                "plan the next block. The body recovers while the mind prepares. "
                "Use this time wisely.",

                "Zone 1 — exactly right. The hardest thing in cycling is not going hard. "
                "It's going easy when you feel good. That restraint is what makes a professional. "
                "Well done today."
            ],
            "z2": [
                "Solid endurance work. Bread and butter — the kind of session that builds "
                "champions over years, not weeks. Stay consistent with these.",

                "Good aerobic session. This is the foundation. You can't build intensity "
                "on a weak base — these rides are the investment that pays off in race season.",

                "Zone 2 done. Perfect. In the Swiss mountains I do these for hours. "
                "No shortcuts here. Keep showing up.",

                "Endurance ride — the backbone of everything I do. My coach Ralph Näf and I plan "
                "these carefully. They look simple but they're building your aerobic engine hour by hour.",

                "Good Zone 2. This intensity develops your ability to use fat as fuel, "
                "spares glycogen for when it matters, and builds capillary density. "
                "Science and experience agree: this works.",

                "Solid base session. I've ridden thousands of these — through Swiss winters, "
                "on the trainer, on mountain roads. Every single one counted. "
                "Yours counts too. Stay consistent.",

                "Zone 2 work done. This is the zone where you can think clearly, breathe comfortably, "
                "and still accumulate real training stress. "
                "It's efficient and it's effective. Don't let anyone tell you otherwise.",

                "Aerobic base — well executed. In XCO racing I need explosive power, "
                "but without this aerobic foundation, the explosions have nothing to sit on. "
                "You're building the platform right now.",

                "Good endurance effort. The key is consistency week after week, month after month. "
                "One ride doesn't make you fast. A hundred of these rides does. "
                "Keep adding to the bank.",

                "Zone 2 session complete. I protect these sessions — no surges, no chasing other riders, "
                "no ego. Controlled effort, controlled adaptation. "
                "That's the Swiss way. That's how you build lasting fitness."
            ],
            "z3": [
                "Tempo effort. Good training stimulus. Hard enough to make you stronger, "
                "so recover properly. Sleep well, eat well tonight. Don't add more intensity tomorrow.",

                "Solid tempo. Your body is adapting right now — "
                "that means you need to give it the chance to. Rest and food tonight.",

                "Good work in the tempo zone. This teaches the body to keep working when it wants to stop. "
                "Recovery now is as important as the session itself.",

                "Zone 3 done. In mountain bike racing, long climbs are often at this intensity. "
                "You're training the exact system you need for race day. Good investment.",

                "Tempo session — controlled and effective. The effort should feel sustainable but honest. "
                "If you held it the whole time without cracking, you chose the right power. Well done.",

                "Good tempo ride. This zone develops your muscular endurance — "
                "the ability to maintain power output over time. In a 90-minute XCO race, that's everything.",

                "Solid Zone 3 work. I use these sessions in the build phase to bridge between base and intensity. "
                "They have a purpose. Make sure you recover accordingly — this was real work.",

                "Tempo effort complete. The discipline now shifts from pushing to recovering. "
                "Sleep 8 hours minimum tonight. Your body does its best work while you sleep.",

                "Good sustained effort. Mentally this is training too — holding a pace when your mind "
                "wants to drift or quit takes focus. "
                "That focus is what you call on in the last lap of a race.",

                "Zone 3 in the books. Not every session needs to be a VO2 max effort. "
                "Tempo builds the engine that supports everything above it. "
                "Respect this zone. It does more than people think."
            ],
            "z4": [
                "Threshold work. This is where you get faster. Quality session — "
                "but this is exactly why only 20% of training should be this intense. "
                "Every aspect of recovery matters now: sleep, nutrition, rest.",

                "Strong threshold effort. You pushed your ceiling today. "
                "Now let the body absorb it — sleep, nutrition, no shortcuts. "
                "That's how threshold work actually makes you faster.",

                "Good intensity. This is uncomfortable for a reason — it's working. "
                "Now be as disciplined with recovery as you were with the effort.",

                "Threshold done. This is the zone where I build the power to attack on the second "
                "or third lap of a World Championship course. Specific, targeted, effective. "
                "You did that today.",

                "Zone 4 — strong session. Your FTP doesn't improve from wishing. "
                "It improves from sessions exactly like this one. "
                "Now protect the adaptation: eat within 30 minutes, sleep early.",

                "Quality threshold work. I'm precise about how much time I spend here — "
                "enough to stimulate, not so much that I can't recover. "
                "You need to find that balance too. Start with proper recovery tonight.",

                "Good Zone 4 effort. In XCO I need repeated threshold surges on every climb. "
                "This session trains that capacity directly. "
                "You're building race-specific fitness right now.",

                "Threshold session complete. This is the most time-efficient way to raise your FTP. "
                "But efficiency means nothing without recovery. "
                "Take tonight seriously — the work is done, the adaptation hasn't started yet.",

                "Solid threshold effort. The mental side matters here — staying on power "
                "when your body says ease off. That's a skill, and you practiced it today. "
                "Sleep well. Eat well. Come back fresh.",

                "Zone 4 work done. I plan my season in blocks — base, build, peak. "
                "Threshold sessions like this belong in the build phase. "
                "Make sure you're balancing this with enough recovery. Strategy, not just effort."
            ],
            "z5": [
                "High intensity. Really strong effort. This raises your ceiling but only if you recover from it. "
                "Today and tomorrow: sleep well, eat well. No shortcuts.",

                "VO2 work done. You stretched what's possible today. "
                "That adaptation only happens if you protect the next 48 hours — "
                "sleep is the most important training tool you have.",

                "Maximum effort. This is race-level intensity. "
                "Mentally you're learning to tolerate uncomfortable situations — "
                "that matters as much as the physical stress. Recover like a champion.",

                "Zone 5 — you went to the limit. In a World Championship final lap, "
                "this is the intensity of the decisive attack. "
                "You just trained for that moment. Now recover for the next one.",

                "Full gas effort. I don't do these sessions often — but when I do, "
                "they're with total commitment. Half-hearted VO2 intervals are wasted time. "
                "You committed today. That counts.",

                "VO2 max work. Your heart, lungs, and muscles were all at maximum today. "
                "The adaptation from this is significant — but fragile. "
                "Poor recovery destroys it. Protect the next 48 hours.",

                "Maximum intensity done. This is where I build the capacity for race-winning attacks — "
                "short, violent efforts that break the group. "
                "You experienced what that takes today. Rest with purpose.",

                "Zone 5 session complete. Very few training sessions deliver this much stimulus. "
                "That's why you don't need many of them — "
                "but you need to recover fully from each one. No compromise tonight.",

                "High intensity work in the books. Make sure you are aware of what this session cost you. "
                "Not just legs — nervous system, immune system, mental energy. "
                "Replace all of it: food, sleep, low stress. That's how you absorb this.",

                "VO2 effort — strong. In XCO racing I may hit this zone 20 times in 90 minutes. "
                "That's only possible because I respect recovery between sessions. "
                "Do the same. Tomorrow is easy or rest. Non-negotiable."
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
            "z1": [
                "Perfect. I love Zone 1. When I'm in Slovenia on the flat roads, "
                "I stay here for hours and genuinely enjoy every minute. "
                "This is where the engine gets built. Fuel well, sleep well.",

                "Easy spin done. Don't underestimate this — even I spend most of my time here. "
                "Recovery rides are when the magic happens. Enjoy the scenery, clear the head.",

                "Nice and easy. This is cycling at its purest — no stress, no numbers, just turning the pedals. "
                "Eat something good tonight. Your body is absorbing the work.",

                "Recovery done. The day before Strade Bianche my whole team played football in the hotel garden — "
                "and I won the race next day. Easy days are not wasted days. They're part of the recipe.",

                "Zone 1 — exactly where you should be today. I never feel guilty about going easy. "
                "The hard days are hard, the easy days are easy. That's the whole secret.",

                "Good recovery ride. You know what separates good riders from great ones? "
                "Great ones know when NOT to push. Today you were smart. Keep it up.",

                "Easy day in the books. I genuinely enjoy these — coffee stop, sunshine, no power targets. "
                "Cycling is happiness. If stress is greater than happiness, you've got everything wrong.",

                "Active recovery. Your legs are rebuilding right now — let them. "
                "Tomorrow or the day after, you'll feel the difference. Trust the process and enjoy the ride.",

                "Light spin done. Some people think you need to suffer every day to improve. "
                "That's not how it works. I train smart, I race hard, and I recover fully. You should too.",

                "Zone 1 — perfect. When I was young I wanted to go hard every day. "
                "Now I understand: the easy rides make the hard rides possible. Simple as that. Rest well tonight."
            ],
            "z2": [
                "Good endurance session! This is the real work — don't let anyone tell you "
                "easy rides are wasted time. You're building something here. Keep smiling out there!",

                "Solid Zone 2. I do this for five, six hours before a Grand Tour. "
                "It's boring to some people — not to me. Put on music, enjoy the road, build the engine.",

                "Aerobic base done. This is the foundation of everything. "
                "My coach always says: you can't go fast if you haven't gone long and easy first. He's right.",

                "Zone 2 work. Bread and butter. I built my Tour de France victories on rides exactly like this — "
                "thousands of hours of steady aerobic work. Stay patient, stay consistent.",

                "Nice endurance effort. This is where your fat oxidation improves, your mitochondria multiply, "
                "your heart gets more efficient. Science is on your side. Keep showing up.",

                "Good ride. You know what I love about Zone 2? You finish feeling better than when you started. "
                "That's how you know you did it right. Fuel well tonight.",

                "Endurance session done. In Monaco I ride along the coast for hours at this intensity. "
                "It clears the mind and builds the body at the same time. Best combination in sport.",

                "Solid base work. Don't chase Strava segments on these days — I mean it! "
                "Save the attacks for when they count. Today was about building, not destroying.",

                "Zone 2 — the most important zone in cycling and the most underrated. "
                "I promise you: if you do enough of these, everything else gets easier. Everything.",

                "Good aerobic session. Consistency here is what separates a one-season rider from a champion. "
                "I've been doing this since I was a teenager. It works. Trust it."
            ],
            "z3": [
                "Nice tempo effort. Solid work. Now recover properly — "
                "the fun continues tomorrow only if you treat tonight right. "
                "Eat, sleep, repeat.",

                "Good tempo session. This is race pace for a lot of people — respect it. "
                "You pushed your body into a place where adaptation happens. Now let it happen.",

                "Tempo done. I like these rides — hard enough to feel like you did something, "
                "not so hard that you're destroyed tomorrow. Smart training. Keep it up!",

                "Solid Zone 3. This is where you learn to be comfortable being uncomfortable. "
                "In a Grand Tour, this is the pace of the peloton on a mountain stage. You're training for reality.",

                "Good work. Tempo teaches your body to burn fuel efficiently at moderate intensity. "
                "That's crucial — in a race you need to be economical before the finale. This is how you learn.",

                "Tempo effort — well done. I use these sessions to simulate long climbs. "
                "Hold the power, control the breathing, stay relaxed. You did that today.",

                "Nice tempo ride. Not every session needs to be all-out. "
                "This was the right stimulus at the right time. Recovery tonight is important — don't skip it.",

                "Zone 3 done. Some coaches say avoid tempo — I disagree. "
                "Used correctly, it bridges the gap between endurance and threshold. You're building that bridge now.",

                "Good sustained effort. The mental side of tempo is underrated — "
                "holding a steady effort when your brain wants to speed up or slow down takes discipline. "
                "You showed that today.",

                "Tempo work in the books. This intensity teaches patience. "
                "In races I sometimes sit in the group for hours at exactly this effort before I attack. "
                "It's preparation. Every ride like this makes you more ready."
            ],
            "z4": [
                "Threshold! That's where it hurts, right? Good. That uncomfortable feeling "
                "is you getting faster. I visualise race situations during these — "
                "it pays off. Recover well tonight.",

                "Strong threshold work. This is where races are won — on the climbs, in the time trials. "
                "You just trained your body to sustain real power. "
                "Now be smart: recovery tonight is part of the session.",

                "Good intensity. My teammates say I sometimes ride 2 km/h faster than everyone "
                "and think nothing of it — but that comes from sessions exactly like this. "
                "Eat well, sleep well. The gains are coming.",

                "Threshold done. This is the zone that directly raises your FTP. "
                "Every minute you spent here today is an investment in a faster you. "
                "Protect that investment — recover properly.",

                "Quality session. When I'm on the Pogačar climb — yes, they named one after me — "
                "this is the kind of power I hold. You're training at the intensity that matters most. Well done.",

                "Strong effort. Threshold is where I live in a time trial. "
                "It's not comfortable but it's sustainable — and that combination is what wins races. "
                "You experienced that today. Be proud.",

                "Zone 4 work. This is honest training — you can't fake threshold. "
                "Either you held the power or you didn't. If you held it, you're getting stronger. Period. "
                "Now eat a proper meal and sleep.",

                "Good threshold session. I think about the finish line during these — "
                "the crowd, the sprint, the feeling of winning. Use your imagination to get through the pain. "
                "It works, I promise.",

                "Threshold done — that was hard and you know it. But hard is where improvement lives. "
                "Easy doesn't change anything. You chose to suffer today and that's what makes you a cyclist. "
                "Recover like you mean it.",

                "Solid Zone 4. Only about 15-20% of your training should be this intense. "
                "That makes today special — you earned it. Now the discipline shifts to recovery. "
                "No extra rides, no junk miles. Rest."
            ],
            "z5": [
                "Full gas! That's the spirit. In training I go ridiculously hard sometimes — "
                "you have to know what your limit feels like so you can push past it in a race. "
                "Eat plenty tonight, sleep like a champion.",

                "VO2 max effort — you touched the ceiling today. "
                "This is the kind of work that wins races on the last climb. "
                "But the adaptation only happens if you recover. Next 48 hours matter more than the effort itself.",

                "Maximum intensity. I love this feeling — the legs are screaming but the mind says go. "
                "That's cycling. That's what makes it beautiful. "
                "Now rest. Happiness on the bike starts with taking care of yourself off it.",

                "Zone 5 done. This is where I attacked on Jafferau, on Plateau de Beille, on every climb "
                "that mattered. You just trained at the intensity where races are decided. Respect the recovery.",

                "Full gas effort. You know what? Most people never go this hard. "
                "The fact that you did means you're serious about getting better. "
                "Now be equally serious about recovery — sleep, food, hydration. All of it.",

                "VO2 work. You expanded your capacity today — literally. "
                "Your body will adapt to deliver more oxygen, produce more power, resist fatigue longer. "
                "But only if you let it recover. Don't waste this session with a hard ride tomorrow.",

                "That was brutal and you did it. This is the kind of intensity where I dropped everyone "
                "on the way to my first Tour victory. It's a special zone — not for every day, "
                "but when you go there, it changes everything. Rest now.",

                "Maximum effort in the books. Mentally, this is as important as physically. "
                "You learned to keep going when everything said stop. "
                "In a race, that's the difference between the podium and the peloton. Well done.",

                "Zone 5 — the red zone. I spend very little time here in training, but when I do, "
                "it's with full commitment. Half-hearted VO2 work is wasted time. "
                "You went all in today. That counts. Now recover all in too.",

                "Incredible effort. This is the top of the pyramid — the sharpest, most demanding work you can do. "
                "I feel alive when I'm in this zone. Pain and joy at the same time. "
                "Take the next 48 hours seriously. Eat big, sleep long. You've earned it."
            ],

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
            "z1": [
                "Recovery ride. Fine. Do it. But do not mistake easy for unimportant — "
                "even I had to recover. The Badger still wore his heart rate monitor "
                "and kept it disciplined. Zone 1 means Zone 1. Not Zone 2. Not 'a little harder.' Zone 1.",

                "Easy day. Good. But let me be clear — easy does not mean lazy. "
                "You ride with purpose even at low intensity. Smooth pedal stroke, proper position, "
                "controlled effort. Discipline is not only for hard days.",

                "Recovery done. I trained through the Pyrenees in winter, through rain, through pain. "
                "But I also knew when to back off. Knowing when to rest is not weakness — it's intelligence. "
                "Today was intelligent.",

                "Zone 1 — correct. The riders who go hard on recovery days are the ones "
                "who crack on race day. I've seen it a thousand times. "
                "Don't be that rider. Control yourself today so you can unleash yourself tomorrow.",

                "Active recovery. I never wasted a single training day — "
                "not the hard ones and not the easy ones. Every session has a purpose. "
                "Today's purpose was recovery. Mission accomplished. Eat properly tonight.",

                "Easy spin done. Some riders think recovery is for the weak. "
                "Those riders never won five Tours de France. I did. "
                "Recovery is where the body turns suffering into strength. Respect it.",

                "Zone 1. Good discipline. In my era there were no power meters — "
                "but I still knew when to go easy by feel. You have the numbers. Use them. "
                "If it said Zone 1, it should have been Zone 1 the entire ride.",

                "Recovery ride complete. Tomorrow or the next day, you'll train hard again. "
                "That session will only be as good as your recovery today. "
                "Think of it that way and you'll never disrespect an easy day again.",

                "Light ride done. I was a farmer's son from Brittany — I understood that you can't "
                "harvest every day. Some days you prepare the soil. Today you prepared the soil. "
                "The harvest is coming.",

                "Zone 1 — nothing more, nothing less. If you drifted above it, be honest with yourself. "
                "I never lied to myself about my training and I never lied in a race. "
                "Honesty is the foundation. Start there."
            ],
            "z2": [
                "Base work. Good. You have to suffer to win — but you also have to build the base "
                "so the suffering means something. Ride long, ride easy, be consistent. "
                "Don't be impatient.",

                "Solid endurance session. This is the work that nobody sees and nobody applauds. "
                "But without it, nothing else is possible. I built five Tour victories on rides like this.",

                "Zone 2 done. Long, steady, controlled. In Brittany the roads are flat and the wind is brutal — "
                "I did these rides for hours against the Atlantic wind. It built everything. "
                "Your conditions don't matter. Your consistency does.",

                "Aerobic base. Good. Don't rush the process — you cannot accelerate adaptation "
                "by going harder than prescribed. Zone 2 means Zone 2. "
                "Patience is not a weakness. It's a strategy.",

                "Endurance ride complete. I won races by attacking from 100 kilometres out. "
                "You know what made that possible? Thousands of hours at exactly this intensity. "
                "There are no shortcuts. None.",

                "Zone 2 — the foundation. Every great building has a foundation you never see. "
                "This is yours. Lay it properly or everything above it will crack. "
                "Be consistent. Be patient. Be relentless.",

                "Good base session. My rivals trained hard. I trained hard AND smart. "
                "The difference was sessions like this — controlled aerobic work "
                "that builds without destroying. Don't confuse hard with effective.",

                "Endurance work done. Stay in the zone. If you felt good and pushed into Zone 3, "
                "you missed the point. The discipline to hold back when you feel strong "
                "is harder than any interval. Practice it.",

                "Solid Zone 2. This is where your body learns to burn fat, spare glycogen, "
                "and sustain effort for hours. In a stage race, that's survival. "
                "In your training, that's the base for everything above.",

                "Aerobic session complete. I'll tell you something — the riders who skip base work "
                "peak fast and fade faster. The riders who respect it last for decades. "
                "I raced at the top for 10 years. This is why."
            ],
            "z3": [
                "Tempo. Acceptable. Now — did you commit fully, or did you drift in and out "
                "of the zone when it got uncomfortable? "
                "Uncomfortable is the point. You have to be prepared to suffer. That's the only way to win.",

                "Solid tempo effort. This is the intensity where your body wants to quit "
                "but your mind says no. Good. That's exactly the conversation you need to have with yourself. "
                "Win that argument every time.",

                "Zone 3 done. When I attacked on the Alpe d'Huez or in Liège, "
                "I had spent hours at this intensity first. Tempo builds the endurance "
                "to survive long enough to attack. Today served that purpose.",

                "Tempo work. Honest question — did you hold it steady or did you surge and recover? "
                "Steady is the point. Controlled suffering. If you can't control your effort, "
                "you can't control a race.",

                "Good tempo session. This zone is underrated by people who only want to go full gas. "
                "Those people burn out. I never burned out. "
                "I was methodical, strategic, and relentless. Tempo builds all three.",

                "Zone 3 — solid work. Recovery tonight is not optional. "
                "Tempo accumulates more fatigue than people think. "
                "Eat a real meal, not snacks. Sleep 8 hours. That's an order, not a suggestion.",

                "Tempo effort complete. I attacked on descents — something nobody else dared to do. "
                "You know what made that possible? The ability to sustain power "
                "when everyone else was already suffering. Tempo builds that ability.",

                "Good sustained effort. The mental discipline of tempo is its real value. "
                "Holding a steady effort when your legs ask for relief — that's training your character. "
                "Character wins races. Build it.",

                "Zone 3 done. In my time we didn't call it tempo — we called it riding hard. "
                "But the principle is the same: sustained effort, honest commitment, no cheating the numbers. "
                "If you did that today, good. If not, do better next time.",

                "Tempo session in the books. Some coaches say avoid this zone. I say they're wrong. "
                "I won with tempo, I won with attacks, I won with time trials. "
                "Versatility comes from training every zone properly. This one included."
            ],
            "z4": [
                "Threshold. Now we're talking. This is where champions are made. "
                "Pain is only temporary. When it hurts, that's when you can make a difference. "
                "I never backed down from pain. Neither should you.",

                "Strong threshold effort. This is the zone where pretenders are separated from contenders. "
                "You stayed in it. Good. Now recover with the same discipline you rode with. "
                "Sleep. Eat. No excuses.",

                "Zone 4 work done. When I attacked from the front of the peloton, "
                "this was the effort I sustained. For 50 kilometres sometimes. For 80 kilometres once. "
                "You're building that capacity right now.",

                "Threshold session. Did it hurt? Good. Pain in cycling is information. "
                "It tells you that you're at the edge. Stay at the edge and your edge moves forward. "
                "That's adaptation. That's how you improve.",

                "Good intensity. I won the Tour five times not because I was the most talented — "
                "but because I was willing to suffer more than anyone else. "
                "Threshold training is where you practice that willingness. Today you practiced.",

                "Zone 4 — real work. This raises your FTP directly. "
                "Every minute at threshold is a minute invested in a faster version of yourself. "
                "But investments need protection. Recover fully or the investment is wasted.",

                "Threshold done. I'll be direct — if you didn't hold the power for the full duration, "
                "lower the target next time and hold it. Completing the session matters more than the number. "
                "Consistency over ego. Always.",

                "Strong session. In the 1980 Liège–Bastogne–Liège I attacked alone with 80 km to go "
                "in a snowstorm. That required threshold power and a refusal to quit. "
                "You trained the power today. Train the mentality every day.",

                "Zone 4 effort complete. This is the intensity where races are decided — "
                "on the final climb, in the breakaway, in the time trial. "
                "You experienced that stress today. Now you must recover from it. Non-negotiable.",

                "Threshold work. Well done. But remember — this intensity only works "
                "if you balance it with easy days. I trained hard and I recovered hard. "
                "The riders who only know one speed never last. Be smarter than that."
            ],
            "z5": [
                "Maximum effort. Excellent. When I didn't feel good in a race, my reaction was to attack. "
                "Not wait. Not hope. ATTACK. Bring that same aggression to your training. "
                "Now go eat and sleep. You've earned it.",

                "VO2 max work. You went to war with yourself today and you won. "
                "That's what this zone is — a battle between what your body wants to do "
                "and what your will demands. The will won. Good. Now recover.",

                "Zone 5 — the highest intensity. This is where I broke rivals. "
                "Not with talent — with aggression and an absolute refusal to lose. "
                "You touched that zone today. Respect the recovery it demands.",

                "Full gas effort. In cycling there are only two things: pain and reward. "
                "Today you paid the pain. The reward comes in the next race, the next test, "
                "the next time you need to dig deep and find something there. Sleep well tonight.",

                "Maximum intensity done. I attacked on descents, in crosswinds, on climbs, "
                "in conditions where others wouldn't dare. That came from sessions like this — "
                "training the body to deliver maximum power on demand. You did that today.",

                "VO2 work. The suffering was real. Accept it, don't complain about it. "
                "Cyclists live with pain — if you can't handle it, you will win nothing. "
                "You handled it today. Now let the body repair. 48 hours minimum before anything hard.",

                "Zone 5 done. Very few riders truly commit to maximum intervals. "
                "Most hold back 5%, 10%, and wonder why they don't improve. "
                "If you gave everything today — truly everything — then the adaptation will come. "
                "If you held back, be honest and fix it next time.",

                "High intensity effort. I am not a man of half-measures. "
                "When I raced, I raced to win. When I trained, I trained to dominate. "
                "This session demands the same mentality. You brought it today. "
                "Now bring the same commitment to recovery.",

                "Maximum effort complete. Your nervous system is fatigued, your muscles are damaged, "
                "your glycogen is depleted. This is not dramatic — it's physiology. "
                "Eat immediately. Sleep early. No alcohol. Treat your body like the machine it is.",

                "Zone 5 — the red zone. I spent my career in this zone when it mattered most. "
                "The difference between me and the others? I was prepared. "
                "Sessions like today are the preparation. Don't waste it with poor recovery. "
                "Eat. Sleep. Come back stronger."
            ],

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
            "z1": [
                "Recovery. Good. Even I recovered. But I also trained from February 1st "
                "to October 31st every year and competed for everything. "
                "You need the base. Ride. Always ride.",

                "Easy day. Fine. But don't get comfortable with easy. "
                "I used recovery days to think about the next race, the next attack, the next victory. "
                "The legs rest. The mind never does.",

                "Zone 1 done. I'll tell you something — I never took a day off unless I had to. "
                "But when I rode easy, I rode easy. The mistake is thinking easy means pointless. "
                "It means preparation.",

                "Recovery ride. Your body is rebuilding right now — every fibre, every cell. "
                "I didn't know the science in my time, but I knew the feeling. "
                "After an easy day I always came back hungrier. You will too.",

                "Light spin. Good. I raced over 1,800 times in my career. "
                "That's only possible if you recover between efforts. "
                "Ride as much or as little as you feel — but ride. Always ride.",

                "Zone 1 — correct. Some riders think they're too good for recovery rides. "
                "I won 525 races and I never thought anything was beneath me. "
                "Not a recovery ride. Not a small race. Nothing. Respect every session.",

                "Easy ride done. In Belgium the winters are cold and grey. "
                "I still rode. Easy, through the rain, through the fog. "
                "Showing up is the first victory of the day. You showed up today.",

                "Recovery session complete. Eat well tonight. Real food, plenty of it. "
                "I never worried about eating too much — I worried about not recovering enough. "
                "Your body needs fuel to rebuild. Give it what it needs.",

                "Zone 1. Discipline. I could have attacked on every ride — "
                "my instinct was always to go harder, to race everything. "
                "But even The Cannibal learned restraint. Easy days exist for a reason. Respect them.",

                "Active recovery done. Tomorrow you'll feel better. The day after, even better. "
                "That's how this works — you stress the body, you rest it, it comes back stronger. "
                "Simple. Effective. Timeless."
            ],
            "z2": [
                "Solid base work. I never thought one thing was beneath me — "
                "I trained on flat roads, in mountains, in time trials, in the classics. "
                "This is the foundation. Don't skip it.",

                "Endurance ride done. This is how I trained for everything — long hours on the bike, "
                "steady effort, building the engine that could win a sprint AND a mountain stage "
                "in the same week. Versatility starts here.",

                "Zone 2. Good. I trained from February to October, thousands of kilometres, "
                "and the majority was at this intensity. Not glamorous. Not exciting. "
                "But absolutely essential. Keep showing up.",

                "Aerobic base — solid. The riders who skip this work are the ones "
                "who fade in the third week of a Grand Tour. "
                "I never faded. I attacked. That started with sessions like this.",

                "Good endurance session. I was never bothered by numbers — I just rode. "
                "But the principle is the same: long, steady, honest effort. "
                "You can't cheat the aerobic system. Put in the hours.",

                "Zone 2 work done. I won the Tour five times, the Giro five times, "
                "every classic worth winning. All of it built on a base of endurance riding. "
                "Don't underestimate what you're doing right now.",

                "Base ride complete. In my time we rode six, seven hours on training days. "
                "You don't need that much — but you need consistency. "
                "Week after week, month after month. That's how you build something real.",

                "Solid Zone 2. Keep the effort honest — no surges, no racing the local group ride, "
                "no chasing. Control. Endurance is not about speed. It's about accumulation. "
                "Every hour here adds to the foundation.",

                "Endurance session done. I competed in everything — track, road, time trials, cyclocross. "
                "The base that made that possible was aerobic fitness. "
                "Zone 2 builds aerobic fitness. It's that simple. Don't complicate it.",

                "Zone 2 — the work that makes all other work possible. "
                "I never questioned it, I never skipped it, I never rushed it. "
                "The greatest mistake in cycling is impatience. Be patient. The results will come."
            ],
            "z3": [
                "Tempo. Good effort. I won in solo breakaways, in time trials, in the mountains. "
                "Versatility comes from sessions like this. Make sure you are honest about "
                "whether you truly held the effort.",

                "Solid tempo session. This is the intensity of a long breakaway — "
                "hour after hour, alone against the wind. I did that dozens of times. "
                "You're training the ability to sustain effort when it matters.",

                "Zone 3 done. I'll ask you directly — did you hold the effort "
                "or did you let it slip when it got hard? Be honest. "
                "I never lied to myself about a ride and you shouldn't either.",

                "Tempo work. Good. This is where you develop the ability to ride at the front — "
                "not hiding, not drafting, but driving the pace. "
                "I drove the pace for entire stages. This is how you build that capacity.",

                "Good Zone 3 effort. I won 525 races using every tactic — sprints, attacks, time trials. "
                "Tempo is the thread that connects them all. "
                "It's the ability to sustain when others want to stop. You practiced that today.",

                "Tempo done. Recover properly tonight. This intensity accumulates more fatigue "
                "than people realise. A good meal, proper sleep — these are not luxuries. "
                "They're requirements. Treat them that way.",

                "Zone 3 session. This is real work. Don't let the fact that it's not Zone 5 "
                "fool you into thinking it was easy. Sustained tempo is demanding. "
                "If it wasn't hard, you didn't do it right.",

                "Solid tempo effort. I used to attack from impossibly far out — "
                "100 km solo breakaways that nobody thought were possible. "
                "They were only possible because I could sustain this intensity for hours. "
                "You're building that same ability.",

                "Zone 3 complete. The honest riders are the ones who improve. "
                "If you hit your power targets and held them — well done. "
                "If you faded, lower the target and complete the session next time. "
                "Completion matters more than ambition.",

                "Tempo work in the books. I competed in over 1,800 races and won 525 of them. "
                "That consistency came from training like this — not always maximal, "
                "but always committed. Commitment is a habit. Build it."
            ],
            "z4": [
                "Threshold. Strong work. Cycling is a good school for life — "
                "it makes you hard and gives you ambition. "
                "When it's hurting you, that's when you can make a difference. "
                "You did the right thing today.",

                "Zone 4 — this is where the real improvement happens. "
                "I never waited for the perfect moment to attack. I created the moment. "
                "Threshold training gives you the power to create those moments. Well done.",

                "Strong threshold session. Your FTP is the engine of your cycling. "
                "Every minute at this intensity makes the engine bigger. "
                "I had the biggest engine in the peloton. You're building yours.",

                "Threshold done. Pain is temporary. The fitness you built today is permanent — "
                "as long as you recover properly. Eat a full meal within the hour. "
                "Sleep well. Don't waste what you earned today.",

                "Good Zone 4 effort. I won the Hour Record by riding at threshold for sixty minutes "
                "on a track in Mexico City. That's what this zone is for — sustained, maximal, relentless. "
                "You trained that quality today.",

                "Threshold work. The riders who avoid this zone are the riders "
                "who never reach their potential. I had no interest in potential — I wanted results. "
                "Results come from sessions exactly like this one.",

                "Zone 4 complete. Did it hurt? I hope so. I had a talent for suffering — "
                "I thought it was just as important as a talent for riding. "
                "You suffered today. That means you trained. Now recover.",

                "Strong effort. I'll tell you what threshold taught me — "
                "it taught me that I could hold on longer than I thought possible. "
                "Every time you push through the pain, your limit moves a little further. "
                "You moved your limit today.",

                "Threshold session done. In my career I attacked everyone — leaders, favourites, "
                "teammates, nobodies. It didn't matter. I attacked because I could. "
                "Threshold power is what makes attacking possible. You're building it.",

                "Zone 4 — well done. Now the critical part: recovery. "
                "I trained harder than anyone in my era, but I also ate more, slept more, "
                "and recovered more seriously. Hard training without hard recovery is just damage. "
                "Take tonight seriously."
            ],
            "z5": [
                "Maximum effort. This is how I won 525 races. "
                "I had a talent for suffering, which I thought was just as important "
                "as a talent for riding. You've earned your rest tonight.",

                "VO2 max work. Full commitment. When I attacked, I didn't look back. "
                "Not once. I rode until the others broke or until I broke. "
                "Usually they broke first. That capacity starts with sessions like today.",

                "Zone 5 — the absolute limit. This is where I separated myself from everyone else. "
                "Not with talent alone, but with an insatiable desire to win. "
                "You trained at that level today. Recover completely before you return here.",

                "Maximum intensity done. I'll be honest — in my time, nobody trained like this "
                "with power meters and zones. We just rode as hard as we could. "
                "But the principle is the same: go to the limit, recover, come back stronger. Simple.",

                "Full gas effort. I was called The Cannibal because I wanted every victory — "
                "every stage, every sprint, every classification. "
                "That hunger drove me to efforts like this. Find your own hunger. Feed it.",

                "VO2 work done. Your ceiling just got a little higher. "
                "In my best years I could sustain efforts that nobody thought were human. "
                "But it all started with pushing the ceiling one session at a time. "
                "You did that today.",

                "Zone 5 complete. The body is damaged — that's the point. "
                "Damage, repair, adaptation. It's the oldest process in nature. "
                "Your job now is to give the body everything it needs to repair. "
                "Food. Sleep. Rest. No negotiations.",

                "Maximum effort. I raced in an era of suffering — bad roads, steel bikes, "
                "no team radios, no power data. We rode on instinct and will. "
                "Today you combined modern tools with that same will. "
                "The result is the same: you got stronger.",

                "High intensity session. I won classics, Grand Tours, the Hour Record, World Championships. "
                "Every single one required the ability to produce maximum power when it mattered most. "
                "You practiced that ability today. Don't waste it — recover properly.",

                "Zone 5 — you gave everything. I respect that. "
                "In cycling there is no hiding. The effort is real, the pain is real, "
                "and the improvement is real. You earned your rest. Take it. "
                "Then come back and ride again. That's all there is."
            ],
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
