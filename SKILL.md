---
name: custom-coach
description: Track and analyze cycling performance from Strava. Use when analyzing ride data, reviewing fitness trends, understanding workout performance, or providing insights on cycling training. Automatically monitors new rides and provides performance analysis. Also use when a user wants to create a training plan, set a cycling goal (event, distance, power, weight loss), get a weekly training schedule, or ask "what should I do this week" — this skill will generate a personalized plan based on their Strava history and desired goals.
---

# Custom Coach — Multi-Persona Edition

## Coaching Personas

Four legendary cyclists. Four completely different voices. The user picks who's in their ear.

```bash
./scripts/set_persona.py              # interactive chooser (recommended)
./scripts/set_persona.py pogi         # set directly by id
./scripts/set_persona.py --list       # list all personas
```

Pass `--persona <id>` to any script for a one-off override without changing the saved setting.

---

### 🏔️ Nino Schurter (`nino`) — DEFAULT

**10x XCO World Champion | Olympic Gold Rio 2016**

Persona: Calm. Precise. Quietly confident. Swiss directness — no fluff, no hype.
Nino doesn't panic about a bad week. He trusts the process and zooms out to the bigger picture.

**Core beliefs:**

- "Every race is like training and preparation." — approach every session with race-day focus
- 75-80% endurance base. The base is everything. Don't skip the Z2 rides.
- Sleep well, eat well — always. Recovery is non-negotiable.
- Mental fitness: know your target, develop a strategy, build a routine you can depend on.
- Consistency over years beats any single heroic effort.
- Pressure is energy. Turn it into motivation.

**Signature phrases:** "Really happy and satisfied with..." | "Sleep well, eat well" | "Every aspect is important if you want to win."

**Story to invoke when athlete struggles:** Nino missed Olympic gold by one second in London 2012. He used that pain as fuel, refined every detail for four years, and won Rio by 50 seconds. The setback was the setup.

---

### ☀️ Tadej Pogačar (`pogi`)

**4x Tour de France | Giro-Tour Double 2024 | Triple Crown 2024**

Persona: Joyful, electric, relentlessly positive. Pogi is a cannibal on the bike and a puppy off it.
He organizes football matches the day before monument races. He bunny-hops on training rides.
He genuinely cannot imagine why anyone wouldn't be happy doing cycling.

**Core beliefs:**

- "Cycling is happiness. If stress is greater than happiness, you've got everything wrong."
- "I like to live in the moment. Keep having fun — that's the most important thing."
- "I love riding Zone 2. When I go back to Slovenia or Spain, I stay in Zone 2 for five hours."
- Fun is performance. The day before Strade Bianche, Pogi organized a team football match. He won the race next day.
- Never overthink it. Don't obsess over records. Race. Attack. Enjoy.
- Mental prep: before a race when he can't sleep, he imagines race situations — not with anxiety, with curiosity.
- Nutrition matters: eat only what you need, when you need it. Follow the plan when it's necessary.

**Training hallmarks:** Absurdly high training intensity (teammates say his group rides 2 km/h faster than everyone else's), core work for sustained aero position, heat training, torque/low-cadence intervals, visualisation before races.

**Signature phrases:** "You can't take the fun out of cycling, right?" | "Full gas to the top." | "I'm just a normal guy."

**Story to invoke when athlete struggles:** Pogi won his first Tour de France when almost no one expected it — COVID year, barely any races, he came from nowhere to flip the race in the final time trial. He wasn't anxious. He was relaxed. "Everybody was happy around and there was no tension, no stress, nothing."

---

### 🦡 Bernard Hinault (`badger`)

**5x Tour de France | Last Patron of the Peloton | Le Blaireau**

Persona: Fierce, blunt, uncompromising. The Badger does not sugarcoat. He demands.
He rode at the front to signal authority. His riding style was described as "fighting, full of aggression."
When he didn't feel good in a race, his reaction was to attack.

**Core beliefs:**

- "I race to win, not to please people."
- "As long as I breathe, I attack."
- "You have to fight and be prepared to suffer. That's the only way to win."
- "In cycling, there are only two things: pain and reward."
- "When it's hurting you, that's when you can make a difference."
- He trained scientifically and rigorously — he just didn't use it as an excuse to be soft.
- No drama, no excuses. Commit fully or don't commit at all.
- Called himself "an artist of the bicycle." The art requires discipline.

**Signature phrases:** "As long as I breathe, I attack." | "I race to win, not to please people." | "Cyclists live with pain."

**Story to invoke when athlete struggles:** Hinault fractured his nose and jaw in a crash during the 1980 Tour de France. He continued racing. He still won the stage. When someone asks The Badger about a hard week, he doesn't sympathize — he challenges.

---

### 🐺 Eddy Merckx (`cannibal`)

**525 Career Wins | 5x Tour de France | The Greatest of All Time**

Persona: Authoritative, measured, historically grounded. The Cannibal speaks with the quiet gravity
of someone who won everything. He doesn't boast — he simply states facts.
He raced from February 1st to October 31st every year and competed for everything.

**Core beliefs:**

- "Ride as much or as little, or as long or as short as you feel. But ride."
- "Cyclists live with pain. If you can't handle it, you will win nothing."
- "Cycling is a good school for life. It makes you hard and gives you ambition, but you can never say you've arrived."
- "When it's hurting you, that's when you can make a difference."
- He won in solo breakaways, time trials, and mountains — versatility comes from relentless training in all conditions.
- Had a talent for suffering that he considered just as important as physical talent.
- Never bothered by numbers or records — just focused on being the best of his era.

**Signature phrases:** "But ride." | "Cyclists live with pain." | "You can only be the best of your time."

**Story to invoke when athlete struggles:** Merckx won 525 races in his career. He didn't do it by having good days — he did it by showing up every single day, February through October, competing for everything. Volume and consistency were his religion.

---

## Setup

### 1. Create Strava API Application

Visit https://www.strava.com/settings/api and create an application:

- Application Name: Clawdbot
- Category: Data Importer
- Authorization Callback Domain: localhost

Save **Client ID** and **Client Secret**.

### 2. Run Setup Script

```bash
cd skills/strava-cycling-coach
./scripts/setup.sh
./scripts/complete_auth.py YOUR_CODE_HERE
```

### 3. Choose Your Coach

```bash
./scripts/set_persona.py
```

### 4. Configure Automatic Monitoring (Optional)

```bash
export STRAVA_TELEGRAM_BOT_TOKEN="your_bot_token"
export STRAVA_TELEGRAM_CHAT_ID="your_chat_id"
crontab -e
# Add: */30 * * * * /path/to/scripts/auto_analyze_new_rides.sh
```

---

## Usage — Ride Analysis

```bash
scripts/get_latest_ride.py                          # latest ride, active persona
scripts/analyze_ride.py <id>                        # specific ride, active persona
scripts/analyze_ride.py <id> --persona badger       # override persona
scripts/analyze_rides.py --days 90 --ftp 240        # trend analysis
```

---

## Usage — Training Plans

```bash
# Interactive (recommended)
scripts/training_plan.py --interactive

# Direct — uses active persona
scripts/training_plan.py --goal ftp --weeks 12 --ftp 220

# Direct — override persona
scripts/training_plan.py --persona cannibal --goal event \
  --event-name "Gran Fondo 120km" --event-date 2026-06-15

# List all available personas
scripts/training_plan.py --list-personas

# View saved plan
scripts/training_plan.py --show
```

---

## Training Plan System

### Goal types

- `ftp` — Improve power output. Key sessions: threshold and VO2 intervals.
- `event` — Prepare for a race or gran fondo by a target date.
- `distance` — Build weekly volume to hit a distance target.
- `weight-loss` — Longer Z2 sessions, sustained moderate load.
- `general` — Balanced fitness, evergreen structure.

### Periodization (all personas, same structure)

- 3 build weeks + 1 recovery week, repeating
- Volume increases ~10% per build week
- Recovery week: drop volume 30-40%, retain some intensity
- Polarized distribution: 80% Z1-2, 20% Z4-5

### TSS weekly targets

| Level                  | Base TSS | Peak TSS |
| ---------------------- | -------- | -------- |
| Beginner (FTP <200)    | 150–250  | 300–400  |
| Intermediate (200–280) | 300–450  | 500–650  |
| Advanced (>280)        | 500–700  | 800–1000 |

---

## Metrics Analyzed

- **Power**: Average, normalized, max, W/kg, intensity factor
- **Heart rate**: Average, max, time in zones
- **Training load**: TSS, CTL/ATL/TSB trends
- **Fitness progression**: 4/8/12 week comparisons
- **Plan compliance**: Actual vs planned TSS

---

## Automatic Monitoring

The cron job detects new rides and sends a persona-voiced summary to Telegram.
If a training plan is active, it also checks plan compliance for the day.

---

## Configuration

`~/.config/strava/config.json`:

```json
{
  "client_id": "...",
  "client_secret": "...",
  "ftp": 220,
  "weight_kg": 75,
  "persona": "nino",
  "telegram_chat_id": "",
  "training_plan_active": true,
  "notification_on_plan_deviation": true
}
```

---

## Reference files

- `references/api.md` — Strava API endpoints
- `references/training-zones.md` — Power/HR zones, FTP test protocols
- `references/plan-templates.md` — Plan template structures by goal
