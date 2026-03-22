# Training Plan Templates Reference

## Template Structure

Each template is a 4-week cycle (3 build + 1 recovery) that repeats for the plan duration.
Week 4 is always a recovery week with reduced volume.

## Goal Templates

### FTP Improvement
Focus: Threshold and sweet spot work. 2 hard days per week.
Key sessions: 2×20 threshold, sweet spot intervals, VO2 max.
Typical duration: 8–16 weeks.

```
Week 1 (Build):    Z2 | Threshold 2x20 | Rest | Sweet Spot | Z2 | Long Ride | Rest
Week 2 (Build):    Z2 | Threshold 2x20 | Rest | VO2 Max    | Z2 | Long Ride | Rest
Week 3 (Overload): Z2 | Sweet Spot     | Rest | Threshold  | Z2 | Long Ride | Rest
Week 4 (Recovery): Recovery | Sweet Spot | Rest | Recovery  | Z2 | Z2        | Rest
```

### Event Preparation
Focus: Build aerobic base, add race-specific intensity closer to event.
Key sessions: Long ride, threshold, tempo. Taper final 1–2 weeks.
Typical duration: 8–24 weeks (longer = better base).

```
Week 1 (Base):  Z2 | Sweet Spot  | Rest | Z2        | Rest | Long Ride | Rest
Week 2 (Build): Z2 | Threshold   | Rest | Tempo      | Z2   | Long Ride | Rest
Week 3 (Peak):  Z2 | VO2 Max     | Rest | Threshold  | Z2   | Long Ride | Rest
Week 4 (Taper): Recovery | Sweet Spot | Rest | Recovery | Z2 | Z2       | Rest
```

### Distance Target
Focus: Volume and time on bike. Gradual long ride progression.
Key sessions: Long ride (extends each cycle), Z2 bulk, one intensity day.
Typical duration: 6–12 weeks.

### Weight Loss
Focus: Longer Z2 sessions, daily movement. Modest intensity to preserve muscle.
Key sessions: Fasted Z2 (morning, pre-breakfast), longer duration rides, one tempo.
Typical duration: 12–24 weeks.
Notes: Pair with moderate caloric deficit. Don't train fasted before hard sessions.

### General Fitness
Focus: Balanced mix of endurance and one intensity day per week.
Good for: Maintaining fitness, cyclists returning from break, casual riders.
Typical duration: Ongoing / evergreen.

---

## Periodization Logic

### 3:1 Block Structure
- 3 progressive weeks followed by 1 recovery week
- Volume increases ~10% per build week
- Recovery week drops volume 30–40% but retains some intensity

### Taper (event prep only)
- Final 2 weeks before event: reduce volume 40–50%
- Maintain a few short sharp efforts to stay sharp
- No new hard workouts in final week

### Volume Scaling by FTP
- FTP < 200W (beginner):  scale workouts 85%
- FTP 200–280W (intermediate): 100%
- FTP > 280W (advanced): scale 115%

---

## Adding Custom Workouts

To add a workout type, extend the `WORKOUTS` dict in `scripts/training_plan.py`:

```python
"my_custom": {
    "name": "Custom Interval",
    "description": "Your description here.",
    "duration_min": 75,
    "tss_per_hour": 85,
    "zone": 4,
}
```

Then reference it by key in any template week array.
