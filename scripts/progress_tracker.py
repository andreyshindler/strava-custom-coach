"""progress_tracker.py — per-user fitness progress tracking and automatic plan adjustment.

Tracks FTP history, weekly TSS compliance, CTL/ATL/TSB form, and peak power records
in a per-user SQLite database (fitness.db).  Called after every ride to silently
update the training plan when meaningful changes are detected.
"""

import copy
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from strava_api import estimate_tss as _estimate_tss_activity, CYCLING_TYPES as _CYCLING_TYPES


def _md_escape(text: str) -> str:
    """Escape characters that break Telegram MarkdownV1 in user-supplied strings."""
    return str(text).replace("*", "⁎").replace("_", "ⳕ").replace("`", "'")

# ---------------------------------------------------------------------------
# Adjustment trigger constants
# ---------------------------------------------------------------------------
FTP_CHANGE_THRESHOLD   = 0.05   # 5% FTP shift triggers plan rescale
LOW_COMPLIANCE_RATIO   = 0.70   # < 70% = under-training
HIGH_COMPLIANCE_RATIO  = 1.25   # > 125% = over-training
LOW_COMPLIANCE_WEEKS   = 3      # consecutive weeks needed for under-training trigger
HIGH_COMPLIANCE_WEEKS  = 2      # consecutive weeks needed for over-training trigger
FATIGUE_TSB_THRESHOLD  = -40.0  # TSB below this = overreached
LOW_TSS_SCALE          = 0.85   # reduce TSS by 15% when chronically under-training
HIGH_TSS_SCALE         = 1.10   # increase TSS by 10% when chronically over-training
RECOVERY_TSS_SCALE     = 0.60   # reduce TSS by 40% for acute recovery week
ADJUST_HORIZON_WEEKS   = 4      # how many future weeks TSS triggers 2/3 rescale


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def db_path(config_dir: Path) -> Path:
    """Return path to per-user fitness.db."""
    return Path(config_dir) / "fitness.db"


def init_db(conn: sqlite3.Connection) -> None:
    """Create all tables if they don't exist.  Idempotent."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS ftp_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            recorded_at TEXT    NOT NULL,
            ftp_watts   INTEGER NOT NULL,
            source      TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS weekly_compliance (
            week_key    TEXT PRIMARY KEY,
            week_start  TEXT NOT NULL,
            planned_tss INTEGER NOT NULL,
            actual_tss  INTEGER NOT NULL,
            compliance  REAL    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS peak_power (
            duration_label TEXT PRIMARY KEY,
            best_watts     INTEGER NOT NULL,
            achieved_on    TEXT    NOT NULL,
            activity_name  TEXT    NOT NULL DEFAULT ''
        );
    """)
    conn.commit()


def open_db(config_dir: Path) -> sqlite3.Connection:
    """Open (and initialise) the per-user fitness.db."""
    conn = sqlite3.connect(str(db_path(config_dir)))
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


# ---------------------------------------------------------------------------
# FTP history
# ---------------------------------------------------------------------------

def record_ftp_history(conn: sqlite3.Connection, ftp_watts: int, source: str,
                        *, recorded_at: str | None = None) -> None:
    """Insert an FTP reading only if it differs from the most recent stored value."""
    row = conn.execute(
        "SELECT ftp_watts FROM ftp_history ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row and row["ftp_watts"] == ftp_watts:
        return  # de-duplicate identical consecutive readings
    if recorded_at is None:
        recorded_at = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        "INSERT INTO ftp_history (recorded_at, ftp_watts, source) VALUES (?, ?, ?)",
        (recorded_at, ftp_watts, source),
    )
    conn.commit()


def get_ftp_history(conn: sqlite3.Connection) -> list:
    """Return all FTP history rows ordered oldest first."""
    rows = conn.execute(
        "SELECT recorded_at, ftp_watts, source FROM ftp_history ORDER BY id ASC"
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# CTL / ATL / TSB  (computed on demand — no daily TSS table needed)
# ---------------------------------------------------------------------------

def compute_ctl_atl_tsb(activities: list, ftp: int, *, today: datetime | None = None) -> dict:
    """Compute CTL, ATL, and TSB using EMA over all activity dates.

    CTL uses a 42-day time constant; ATL uses 7 days.
    Both start at 0.0.  Returns {"ctl": float, "atl": float, "tsb": float}.
    """
    if today is None:
        today = datetime.today()
    today_date = today.date()

    # Build daily TSS totals keyed by date string "YYYY-MM-DD"
    daily_tss: dict = {}
    for act in activities:
        raw_date = act.get("start_date_local", "")
        if not raw_date:
            continue
        date_str = raw_date[:10]  # "YYYY-MM-DD"
        tss = _estimate_tss_activity(act, ftp)
        daily_tss[date_str] = daily_tss.get(date_str, 0) + tss

    if not daily_tss:
        return {"ctl": 0.0, "atl": 0.0, "tsb": 0.0}

    min_date = datetime.strptime(min(daily_tss.keys()), "%Y-%m-%d").date()
    ctl = 0.0
    atl = 0.0
    current = min_date
    while current <= today_date:
        tss = daily_tss.get(current.strftime("%Y-%m-%d"), 0)
        ctl += (tss - ctl) / 42
        atl += (tss - atl) / 7
        current += timedelta(days=1)

    return {"ctl": round(ctl, 1), "atl": round(atl, 1), "tsb": round(ctl - atl, 1)}


# ---------------------------------------------------------------------------
# FTP estimation (wraps training_plan.analyse_rides_for_plan)
# ---------------------------------------------------------------------------

def estimate_current_ftp(activities: list):
    """Return (est_ftp: int|None, source: str) estimated from cycling power data.

    Three strategies tried in order, best result wins:
      1. 20-min best effort (1080–1500 s): avg_watts × 0.95
      2. 45–90 min best effort (2700–5400 s): avg_watts × 1.05
      3. Fallback — best avg_watts across any cycling ride × 0.95

    Returns (None, "no power data") when no power-meter rides are available.
    """
    power_rides = [
        a for a in activities
        if _is_cycling(a) and (a.get("average_watts") or 0) > 50
    ]
    if not power_rides:
        return None, "no power data"

    best_ftp = 0
    source = "no power data"

    # Strategy 1: 20-min best (classic FTP test duration)
    rides_20 = [a for a in power_rides if 1080 <= a.get("moving_time", 0) <= 1500]
    if rides_20:
        est = int(max(a["average_watts"] for a in rides_20) * 0.95)
        if est > best_ftp:
            best_ftp = est
            source = "20-min best effort ×0.95"

    # Strategy 2: 45–90 min best effort (NP correction)
    rides_45_90 = [a for a in power_rides if 2700 <= a.get("moving_time", 0) <= 5400]
    if rides_45_90:
        est = int(max(a["average_watts"] for a in rides_45_90) * 1.05)
        if est > best_ftp:
            best_ftp = est
            source = "45–90 min best effort ×1.05"

    # Strategy 3: fallback from any ride
    if not best_ftp:
        best_ftp = int(max(a["average_watts"] for a in power_rides) * 0.95)
        source = "estimated from power history"

    return (best_ftp, source) if best_ftp > 0 else (None, "no power data")


# ---------------------------------------------------------------------------
# Peak power records
# ---------------------------------------------------------------------------

_PEAK_POWER_RANGES = {
    "5min":  (240, 360),    # 4–6 minutes
    "20min": (1080, 1500),  # 18–25 minutes
}


def _is_cycling(act: dict) -> bool:
    """Return True if the activity is a cycling type."""
    t = act.get("sport_type") or act.get("type", "")
    return t in _CYCLING_TYPES


def update_peak_power(conn: sqlite3.Connection, activities: list) -> list:
    """Update 5-min and 20-min peak power records from cycling activities only.

    Uses average_watts of rides whose moving_time falls within the proxy
    duration range.  Returns list of PR announcement strings (empty if none).
    """
    prs = []
    for label, (lo, hi) in _PEAK_POWER_RANGES.items():
        best_watts = 0
        best_act = None
        for act in activities:
            if not _is_cycling(act):
                continue
            mt = act.get("moving_time", 0)
            w = act.get("average_watts")
            if w and lo <= mt <= hi and w > best_watts:
                best_watts = int(w)
                best_act = act

        if not best_act or best_watts == 0:
            # No cycling activity in this range — clear any stale record (e.g. from a run)
            conn.execute("DELETE FROM peak_power WHERE duration_label = ?", (label,))
            conn.commit()
            continue

        row = conn.execute(
            "SELECT best_watts FROM peak_power WHERE duration_label = ?", (label,)
        ).fetchone()

        if row is None or best_watts != row["best_watts"]:
            date_str = (best_act.get("start_date_local", "") or "")[:10]
            name = best_act.get("name", "Unknown ride")
            conn.execute(
                """INSERT INTO peak_power (duration_label, best_watts, achieved_on, activity_name)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(duration_label) DO UPDATE SET
                       best_watts = excluded.best_watts,
                       achieved_on = excluded.achieved_on,
                       activity_name = excluded.activity_name""",
                (label, best_watts, date_str, name),
            )
            conn.commit()
            prs.append(f"New {label} power PR: {best_watts}W ({name}, {date_str})")

    return prs


def get_peak_power(conn: sqlite3.Connection) -> dict:
    """Return dict of {duration_label: {best_watts, achieved_on, activity_name}}."""
    rows = conn.execute(
        "SELECT duration_label, best_watts, achieved_on, activity_name FROM peak_power"
    ).fetchall()
    return {r["duration_label"]: dict(r) for r in rows}


# ---------------------------------------------------------------------------
# Weekly compliance
# ---------------------------------------------------------------------------

def _week_key(date_str: str) -> str:
    """Convert 'YYYY-MM-DD' to 'YYYY-W%W' ISO week key."""
    return datetime.strptime(date_str, "%Y-%m-%d").strftime("%Y-W%W")


def record_weekly_compliance(conn: sqlite3.Connection, plan: dict, activities: list,
                              ftp: int, *, target_weeks: int = 8) -> None:
    """Compute actual vs planned TSS for recent plan weeks and upsert into DB."""
    weekly_plans = plan.get("weekly_plans", [])
    today_str = datetime.today().strftime("%Y-%m-%d")

    # Build a quick date → TSS lookup from activities
    act_tss_by_date: dict = {}
    for act in activities:
        raw_date = act.get("start_date_local", "")
        if not raw_date:
            continue
        d = raw_date[:10]
        act_tss_by_date[d] = act_tss_by_date.get(d, 0) + _estimate_tss_activity(act, ftp)

    processed = 0
    for week in reversed(weekly_plans):
        week_start = week.get("week_start", "")
        if not week_start or week_start >= today_str:
            continue  # skip future weeks
        if processed >= target_weeks:
            break

        planned_tss = week.get("total_tss", 0)

        # Sum actual TSS across the 7 days of this plan week
        actual_tss = 0
        try:
            wstart = datetime.strptime(week_start, "%Y-%m-%d")
            for offset in range(7):
                d = (wstart + timedelta(days=offset)).strftime("%Y-%m-%d")
                actual_tss += act_tss_by_date.get(d, 0)
        except ValueError:
            continue

        compliance = actual_tss / planned_tss if planned_tss > 0 else 0.0
        wkey = _week_key(week_start)

        conn.execute(
            """INSERT INTO weekly_compliance
                   (week_key, week_start, planned_tss, actual_tss, compliance)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(week_key) DO UPDATE SET
                   planned_tss = excluded.planned_tss,
                   actual_tss  = excluded.actual_tss,
                   compliance  = excluded.compliance""",
            (wkey, week_start, planned_tss, actual_tss, round(compliance, 3)),
        )
        processed += 1

    conn.commit()


def get_compliance_history(conn: sqlite3.Connection, n_weeks: int = 8) -> list:
    """Return last n_weeks compliance rows ordered oldest-first."""
    rows = conn.execute(
        """SELECT week_key, week_start, planned_tss, actual_tss, compliance
           FROM weekly_compliance
           ORDER BY week_key DESC
           LIMIT ?""",
        (n_weeks,),
    ).fetchall()
    return list(reversed([dict(r) for r in rows]))


# ---------------------------------------------------------------------------
# Plan adjustment logic
# ---------------------------------------------------------------------------

def _find_first_future_week_idx(plan: dict) -> int:
    """Return index of the first week_start that is strictly after today."""
    today_str = datetime.today().strftime("%Y-%m-%d")
    for i, week in enumerate(plan.get("weekly_plans", [])):
        if week.get("week_start", "") > today_str:
            return i
    return len(plan.get("weekly_plans", []))  # no future weeks


def _tsb_label(tsb: float) -> str:
    if tsb > 10:
        return "Fresh"
    if tsb > -10:
        return "Neutral"
    if tsb > -30:
        return "Tired"
    if tsb > -40:
        return "Very Tired"
    return "Overreached"


def check_and_adjust_plan(plan: dict, fitness_data: dict, config_dir: Path):
    """Evaluate adjustment triggers and rescale future plan weeks as needed.

    Works on a deep copy of plan.  Returns (updated_plan, messages).
    updated_plan is the original if no triggers fired.
    messages is a list of short human-readable strings (one per trigger).
    """
    from training_plan import adjust_future_weeks  # local import

    plan_copy = copy.deepcopy(plan)
    messages = []
    first_idx = _find_first_future_week_idx(plan_copy)

    if first_idx >= len(plan_copy.get("weekly_plans", [])):
        return plan_copy, messages  # plan has ended — nothing to adjust

    plan_ftp = fitness_data.get("plan_ftp", plan_copy.get("ftp", 200))
    est_ftp = fitness_data.get("est_ftp")
    compliance_history = fitness_data.get("compliance_history", [])
    tsb = fitness_data.get("tsb", 0.0)

    # Trigger 1 — FTP drift ≥ 5%
    if est_ftp and plan_ftp and abs(est_ftp - plan_ftp) / plan_ftp >= FTP_CHANGE_THRESHOLD:
        scale = est_ftp / plan_ftp
        adjust_future_weeks(plan_copy, scale, first_idx)
        plan_copy["ftp"] = est_ftp
        direction = "+" if est_ftp > plan_ftp else ""
        pct = round((scale - 1) * 100)
        messages.append(
            f"FTP updated {plan_ftp}W\u2192{est_ftp}W: rescaled weeks "
            f"{first_idx + 1}\u2013{len(plan_copy['weekly_plans'])} "
            f"({direction}{pct}%)"
        )

    # Trigger 2 — Chronic low compliance (3+ consecutive weeks < 70%)
    if len(compliance_history) >= LOW_COMPLIANCE_WEEKS:
        last_n = compliance_history[-LOW_COMPLIANCE_WEEKS:]
        if all(r["compliance"] < LOW_COMPLIANCE_RATIO for r in last_n):
            adjust_future_weeks(plan_copy, LOW_TSS_SCALE, first_idx,
                                horizon=ADJUST_HORIZON_WEEKS)
            messages.append(
                f"{LOW_COMPLIANCE_WEEKS} consecutive low-compliance weeks: "
                f"reduced next {ADJUST_HORIZON_WEEKS} weeks TSS by 15%"
            )

    # Trigger 3 — Chronic high compliance (2+ consecutive weeks > 125%)
    if len(compliance_history) >= HIGH_COMPLIANCE_WEEKS:
        last_n = compliance_history[-HIGH_COMPLIANCE_WEEKS:]
        if all(r["compliance"] > HIGH_COMPLIANCE_RATIO for r in last_n):
            adjust_future_weeks(plan_copy, HIGH_TSS_SCALE, first_idx,
                                horizon=ADJUST_HORIZON_WEEKS)
            messages.append(
                f"{HIGH_COMPLIANCE_WEEKS} consecutive high-compliance weeks: "
                f"increased next {ADJUST_HORIZON_WEEKS} weeks TSS by 10%"
            )

    # Trigger 4 — Severe fatigue (TSB < -40) — runs last, can override T2/T3 for week N+1
    if tsb < FATIGUE_TSB_THRESHOLD:
        adjust_future_weeks(plan_copy, RECOVERY_TSS_SCALE, first_idx, horizon=1)
        messages.append(
            f"High fatigue (TSB {tsb:.0f}): converting next week to recovery \u2212 40% TSS"
        )

    return plan_copy, messages


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_post_ride_update(chat_id: str, config_dir, activities: list, plan) -> list:
    """Orchestrator called after every ride.

    Updates peak power, compliance, and fitness load; applies plan adjustments
    if triggered.  Returns a list of strings for the caller to send to the user
    (PR announcements + plan adjustment notices).  Never sends Telegram messages.

    Args:
        chat_id:    Telegram chat ID string (used for logging only)
        config_dir: per-user config dir (str or Path)
        activities: full activity list from strava cache
        plan:       training plan dict, or None
    """
    config_dir = Path(config_dir)
    notifications = []

    # Load current FTP from per-user config
    try:
        from strava_api import load_config
        cfg = load_config(user_dir=config_dir)
        ftp = int(cfg.get("ftp", 220))
    except Exception:
        ftp = 220

    try:
        conn = open_db(config_dir)
    except Exception as e:
        return [f"[progress] DB error: {e}"]

    try:
        # Peak power records
        pr_strings = update_peak_power(conn, activities)
        notifications.extend(pr_strings)

        if plan:
            # Weekly compliance
            record_weekly_compliance(conn, plan, activities, ftp)

            # Current fitness metrics
            form = compute_ctl_atl_tsb(activities, ftp)
            est_ftp, ftp_src = estimate_current_ftp(activities)
            compliance_history = get_compliance_history(conn, n_weeks=8)

            fitness_data = {
                "ctl": form["ctl"],
                "atl": form["atl"],
                "tsb": form["tsb"],
                "est_ftp": est_ftp,
                "plan_ftp": plan.get("ftp", ftp),
                "compliance_history": compliance_history,
            }

            updated_plan, adj_messages = check_and_adjust_plan(plan, fitness_data, config_dir)

            if adj_messages:
                # Persist adjusted plan
                plan_file = config_dir / "training_plan.json"
                try:
                    plan_file.write_text(json.dumps(updated_plan, indent=2))
                except Exception as e:
                    adj_messages.append(f"[progress] plan save failed: {e}")
                notifications.extend(adj_messages)

            # Record FTP history if estimate changed
            if est_ftp:
                record_ftp_history(conn, est_ftp, "auto-estimated")

        conn.close()
    except Exception as e:
        try:
            conn.close()
        except Exception:
            pass
        return notifications + [f"[progress] update error: {e}"]

    return notifications


# ---------------------------------------------------------------------------
# Formatting helpers (used by telegram_bot for /progress and /trends)
# ---------------------------------------------------------------------------

def format_progress_dashboard(config_dir, persona_name: str = "") -> str:
    """Return full /progress dashboard text."""
    config_dir = Path(config_dir)

    # Load current FTP
    try:
        from strava_api import load_config
        cfg = load_config(user_dir=config_dir)
        ftp = int(cfg.get("ftp", 220))
    except Exception:
        ftp = 220

    # Load activities — try per-user cache first, fetch from Strava if empty
    try:
        from strava_cache import load_cached_activities, CACHE_DIR
        from strava_api import get_activities
        cache_dir = CACHE_DIR / config_dir.name if config_dir.name != "strava" else CACHE_DIR
        activities = load_cached_activities(cache_dir)
        if not activities:
            activities = get_activities(days=60, limit=200, user_dir=config_dir)
    except Exception:
        activities = []

    # Auto-backfill on first use so new users see data immediately
    try:
        conn = open_db(config_dir)
        needs_bootstrap = (
            conn.execute("SELECT COUNT(*) FROM ftp_history").fetchone()[0] == 0
            and conn.execute("SELECT COUNT(*) FROM peak_power").fetchone()[0] == 0
        )
        if needs_bootstrap and activities:
            update_peak_power(conn, activities)
            est_ftp, _ = estimate_current_ftp(activities)
            if est_ftp:
                record_ftp_history(conn, est_ftp, "auto-estimated")
            # Load plan for compliance backfill
            try:
                plan_file = config_dir / "training_plan.json"
                if plan_file.exists():
                    _plan = json.loads(plan_file.read_text())
                    record_weekly_compliance(conn, _plan, activities, ftp)
            except Exception:
                pass
        conn.close()
    except Exception as e:
        return f"Could not load fitness data: {e}"

    try:
        conn = open_db(config_dir)

        form = compute_ctl_atl_tsb(activities, ftp) if activities else {"ctl": 0.0, "atl": 0.0, "tsb": 0.0}
        ftp_rows = get_ftp_history(conn)
        peaks = get_peak_power(conn)
        compliance = get_compliance_history(conn, n_weeks=8)

        conn.close()
    except Exception as e:
        return f"Could not load fitness data: {e}"

    today_str = datetime.today().strftime("%Y-%m-%d")
    lines = [f"\U0001f4ca *Fitness Dashboard*\n"]

    # Form & Load
    tsb_label = _tsb_label(form["tsb"])
    lines.append(f"*Form & Load ({today_str})*")
    lines.append(f"  CTL (fitness):  {form['ctl']:.1f}")
    lines.append(f"  ATL (fatigue):  {form['atl']:.1f}")
    lines.append(f"  TSB (form):    {form['tsb']:+.1f}  \u2014 {tsb_label}")

    # FTP History
    lines.append("\n*FTP History*")
    if ftp_rows:
        for i, row in enumerate(ftp_rows):
            marker = "  \u2190 current" if i == len(ftp_rows) - 1 else ""
            lines.append(f"  {row['recorded_at'][:10]}  {row['ftp_watts']}W  ({_md_escape(row['source'])}){marker}")
    else:
        lines.append(f"  (no history yet \u2014 current config FTP: {ftp}W)")

    # Peak Power
    lines.append("\n*Peak Power Records*")
    for label in ("5min", "20min"):
        p = peaks.get(label)
        if p:
            lines.append(f"  {label} best:  {p['best_watts']}W  ({_md_escape(p['activity_name'])}, {p['achieved_on']})")
        else:
            lines.append(f"  {label} best:  \u2014 (no data yet)")

    # Plan Compliance
    lines.append("\n*Plan Compliance \u2014 Last 8 Weeks*")
    if compliance:
        for row in compliance:
            pct = round(row["compliance"] * 100)
            if pct >= 100:
                emoji = "\u2705"
            elif pct >= 70:
                emoji = "\U0001f535"
            else:
                emoji = "\u26a0\ufe0f"
            lines.append(
                f"  {row['week_key']}  planned {row['planned_tss']}  "
                f"actual {row['actual_tss']}  {emoji} {pct}%"
            )
    else:
        lines.append("  No active training plan \u2014 use /newplan to create one.")

    if persona_name:
        lines.append(f"\n\u2014 {persona_name}")

    return "\n".join(lines)


def format_trends_fitness_suffix(config_dir) -> str:
    """Return CTL/ATL/TSB + 4-week compliance block for appending to /trends output.

    Returns empty string if fitness.db doesn't exist yet or on any error.
    """
    config_dir = Path(config_dir)
    db = db_path(config_dir)
    if not db.exists():
        return ""

    try:
        from strava_api import load_config
        cfg = load_config(user_dir=config_dir)
        ftp = int(cfg.get("ftp", 220))
    except Exception:
        ftp = 220

    try:
        from strava_cache import load_cached_activities, CACHE_DIR
        from strava_api import get_activities
        cache_dir = CACHE_DIR / config_dir.name if config_dir.name != "strava" else CACHE_DIR
        activities = load_cached_activities(cache_dir)
        if not activities:
            activities = get_activities(days=60, limit=200, user_dir=config_dir)
    except Exception:
        activities = []

    try:
        conn = open_db(config_dir)
        form = compute_ctl_atl_tsb(activities, ftp) if activities else {"ctl": 0.0, "atl": 0.0, "tsb": 0.0}
        compliance = get_compliance_history(conn, n_weeks=4)
        conn.close()
    except Exception:
        return ""

    lines = ["\n"]
    tsb_label = _tsb_label(form["tsb"])
    lines.append("*Fitness load (today):*")
    lines.append(
        f"  CTL (fitness): {form['ctl']:.1f}  "
        f"ATL (fatigue): {form['atl']:.1f}  "
        f"TSB (form): {form['tsb']:+.1f} \u2014 {tsb_label}"
    )

    if compliance:
        lines.append("\n*Plan compliance (last 4 weeks):*")
        for row in compliance:
            pct = round(row["compliance"] * 100)
            if pct >= 100:
                emoji = "\u2705"
            elif pct >= 70:
                emoji = "\U0001f535"
            else:
                emoji = "\u26a0\ufe0f"
            lines.append(
                f"  {row['week_key']}  planned {row['planned_tss']} TSS  "
                f"actual {row['actual_tss']} TSS  {emoji} {pct}%"
            )

    return "\n".join(lines)
