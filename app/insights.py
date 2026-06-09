"""Deeper analysis of stored Whoop data: baselines, trends, records and
rule-based health recommendations.

``compute_insights`` queries the window and delegates to ``_analyze`` (pure,
so it is unit-testable without a database).  The recommendation rules are
deliberately transparent heuristics built on Whoop's own guidance: recovery
bands (green 67+, yellow 34-66, red <34), HRV/RHR baseline deviation, sleep
duration/consistency, and matching training strain to recovery.
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean, pstdev

from sqlalchemy import select
from sqlalchemy.orm import Session, load_only

from app.models import Cycle, Profile, Recovery, Sleep, Workout


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def _avg(values) -> float | None:
    clean = [v for v in values if v is not None]
    return sum(clean) / len(clean) if clean else None


def _bucket(score: float | None) -> str | None:
    if score is None:
        return None
    if score >= 67:
        return "green"
    if score >= 34:
        return "yellow"
    return "red"


def _parse_offset(tz: str | None) -> timedelta:
    """'+03:00' -> timedelta(hours=3). Defensive: bad input -> 0."""
    if not tz:
        return timedelta(0)
    try:
        sign = -1 if tz.startswith("-") else 1
        hh, mm = tz.lstrip("+-").split(":")[:2]
        return sign * timedelta(hours=int(hh), minutes=int(mm))
    except Exception:
        return timedelta(0)


def _ma(series: list[dict], window: int = 7) -> list[dict]:
    """Rolling mean over the previous up-to-``window`` points of a series."""
    out = []
    values: list[float] = []
    for point in series:
        values.append(point["v"])
        if len(values) > window:
            values.pop(0)
        out.append({"t": point["t"], "v": sum(values) / len(values)})
    return out


def _pct_change(recent: list[float], baseline: list[float]) -> float | None:
    """% change of mean(recent) vs mean(baseline)."""
    if not recent or not baseline:
        return None
    base = mean(baseline)
    if not base:
        return None
    return (mean(recent) - base) / abs(base) * 100.0


def _split_recent(values: list[float], n: int = 7):
    """Last ``n`` values vs everything before them."""
    if len(values) <= n:
        return values, []
    return values[-n:], values[:-n]


def _stats(values: list[float]) -> dict:
    clean = [v for v in values if v is not None]
    if not clean:
        return {"mean": None, "std": None, "min": None, "max": None}
    return {
        "mean": mean(clean),
        "std": pstdev(clean) if len(clean) > 1 else 0.0,
        "min": min(clean),
        "max": max(clean),
    }


# --------------------------------------------------------------------------- #
# Recommendation rules
# --------------------------------------------------------------------------- #
def _recommendations(d: dict) -> list[dict]:
    """Turn the computed analysis into prioritised, actionable advice."""
    recs: list[dict] = []

    def add(priority, category, title, detail):
        recs.append(
            {"priority": priority, "category": category, "title": title, "detail": detail}
        )

    cur = d["current"]
    trends = d["trends"]
    sleep = d["sleep_analysis"]
    training = d["training_analysis"]

    # --- Recovery today ---------------------------------------------------- #
    if cur["recovery_bucket"] == "red":
        add(
            "high", "recovery", "Take a recovery day",
            f"Your latest recovery is {cur['recovery']:.0f}% (red zone). Skip intense "
            "training today: think walking, stretching or mobility work, extra "
            "hydration, and an earlier bedtime tonight.",
        )
    elif cur["recovery_bucket"] == "yellow":
        add(
            "medium", "recovery", "Train, but keep it moderate",
            f"Recovery is {cur['recovery']:.0f}% (yellow). Moderate effort is fine — "
            "aim below your usual strain and avoid max-intensity sessions.",
        )
    elif cur["recovery_bucket"] == "green":
        add(
            "positive", "recovery", "Green light — good day to push",
            f"Recovery is {cur['recovery']:.0f}%. Your body is primed: this is the day "
            "for your harder or longer session.",
        )

    # --- HRV / RHR trends --------------------------------------------------- #
    if trends["hrv_pct"] is not None and trends["hrv_pct"] <= -10:
        add(
            "high", "strain", "HRV is trending down",
            f"Your 7-day HRV is {abs(trends['hrv_pct']):.0f}% below your recent "
            "baseline — a classic sign of accumulating stress or training load. "
            "Cut intensity for a few days, protect sleep, and watch alcohol and "
            "late meals.",
        )
    if trends["rhr_pct"] is not None and trends["rhr_pct"] >= 5:
        add(
            "medium", "heart", "Resting heart rate is elevated",
            f"Your 7-day resting HR is {trends['rhr_pct']:.0f}% above baseline. This "
            "often precedes illness or signals under-recovery. Take it easier and "
            "monitor — if it keeps climbing, prioritise rest.",
        )

    # --- Sleep -------------------------------------------------------------- #
    avg_sleep = sleep["avg_hours"]
    if avg_sleep is not None and avg_sleep < 7.0:
        add(
            "high", "sleep", "You are under-sleeping",
            f"You average {avg_sleep:.1f}h of sleep — under the 7-9h adults need and "
            "the single biggest lever for recovery, HRV and next-day energy. Try "
            "moving bedtime 30-45 minutes earlier this week.",
        )
    elif avg_sleep is not None and avg_sleep < 7.5:
        add(
            "low", "sleep", "A little more sleep would help",
            f"You average {avg_sleep:.1f}h. Nudging toward 7.5-8h should lift your "
            "recovery scores and HRV.",
        )
    if sleep["bedtime_std_hours"] is not None and sleep["bedtime_std_hours"] > 1.5:
        add(
            "medium", "sleep", "Stabilise your sleep schedule",
            f"Your bedtime varies by ±{sleep['bedtime_std_hours']:.1f}h. An irregular "
            "schedule disrupts circadian rhythm even when total hours are fine — "
            "aim for the same bedtime within ~30 minutes, weekends included.",
        )
    if sleep["avg_performance"] is not None and sleep["avg_performance"] < 80:
        add(
            "low", "sleep", "Sleep quality has room to improve",
            f"Average sleep performance is {sleep['avg_performance']:.0f}%. Keep the "
            "bedroom cool and dark, stop caffeine after midday, and avoid screens "
            "in the last 30 minutes before bed.",
        )

    # --- Training load ------------------------------------------------------ #
    if training["overreach_days_14d"] >= 2:
        add(
            "medium", "strain", "Match training to recovery",
            f"In the last 2 weeks you trained hard on {training['overreach_days_14d']} "
            "low-recovery days. Occasional overreach is fine, but a pattern erodes "
            "fitness gains — use red days for active recovery instead.",
        )
    wpw = training["workouts_per_week"]
    if wpw is not None and wpw < 3:
        add(
            "medium", "activity", "Add training frequency",
            f"You average {wpw:.1f} workouts per week. Building to 3-5 sessions — "
            "even adding one easy zone-2 cardio session (30-45 min where you can "
            "still talk) — improves cardiovascular health and HRV.",
        )
    elif wpw is not None and wpw >= 3:
        add(
            "positive", "activity", "Solid training consistency",
            f"You average {wpw:.1f} workouts per week — keep that rhythm going.",
        )

    # --- Vitals ------------------------------------------------------------- #
    if d["averages"]["spo2_percentage"] is not None and d["averages"]["spo2_percentage"] < 95:
        add(
            "low", "vitals", "Blood oxygen runs slightly low",
            f"Average SpO2 is {d['averages']['spo2_percentage']:.1f}%. Sensor fit, "
            "altitude or congestion can explain it, but if it stays below 95% "
            "consistently it is worth mentioning to a doctor.",
        )
    if (
        trends["respiratory_pct"] is not None
        and trends["respiratory_pct"] >= 6
    ):
        add(
            "low", "vitals", "Respiratory rate is up",
            "Your recent respiratory rate is noticeably above baseline — often an "
            "early signal of illness. Ease off and keep an eye on how you feel.",
        )

    order = {"high": 0, "medium": 1, "low": 2, "positive": 3}
    recs.sort(key=lambda r: order[r["priority"]])
    if not any(r["priority"] in ("high", "medium") for r in recs):
        add(
            "positive", "overall", "Keep doing what you're doing",
            "No red flags in this window: sleep, recovery and training load all "
            "look balanced.",
        )
    return recs


def _overall_status(current: dict, trends: dict, sleep: dict) -> dict:
    hrv_down = trends["hrv_pct"] is not None and trends["hrv_pct"] <= -10
    if current["recovery_bucket"] == "red" or hrv_down:
        return {
            "level": "red",
            "headline": "Prioritise recovery",
            "detail": "Your body is asking for rest — favour sleep and easy movement over intensity.",
        }
    if (
        current["recovery_bucket"] == "green"
        and (trends["hrv_pct"] is None or trends["hrv_pct"] > -5)
        and (sleep["avg_hours"] is None or sleep["avg_hours"] >= 7)
    ):
        return {
            "level": "green",
            "headline": "Ready to perform",
            "detail": "Recovery, HRV and sleep are all in good shape — a great day to challenge yourself.",
        }
    return {
        "level": "yellow",
        "headline": "Steady — maintain the balance",
        "detail": "You're in a workable middle ground: train smart and protect your sleep.",
    }


# --------------------------------------------------------------------------- #
# Core analysis (pure — takes ORM-ish rows, returns JSON-able dict)
# --------------------------------------------------------------------------- #
def _analyze(cycles, recoveries, sleeps, workouts, profile, days: int, cutoff: datetime) -> dict:
    rec_by_cycle = {r.cycle_id: r for r in recoveries}
    main_sleeps = [s for s in sleeps if not s.nap]

    # ---- daily series ------------------------------------------------------ #
    series: dict[str, list[dict]] = {
        "recovery": [], "hrv": [], "rhr": [], "strain": [],
        "sleep_hours": [], "sleep_performance": [],
    }
    scatter = []
    for c in cycles:
        if c.start is None:
            continue
        ts = _iso(c.start)
        if c.strain is not None:
            series["strain"].append({"t": ts, "v": c.strain})
        r = rec_by_cycle.get(c.id)
        if r is None:
            continue
        if r.recovery_score is not None:
            series["recovery"].append({"t": ts, "v": r.recovery_score})
            if c.strain is not None:
                scatter.append({"t": ts, "recovery": r.recovery_score, "strain": c.strain})
        if r.hrv_rmssd_milli is not None:
            series["hrv"].append({"t": ts, "v": r.hrv_rmssd_milli})
        if r.resting_heart_rate is not None:
            series["rhr"].append({"t": ts, "v": r.resting_heart_rate})

    for s in main_sleeps:
        if s.start is None:
            continue
        ts = _iso(s.start)
        if s.end is not None:
            series["sleep_hours"].append(
                {"t": ts, "v": (s.end - s.start).total_seconds() / 3600.0}
            )
        if s.sleep_performance_percentage is not None:
            series["sleep_performance"].append({"t": ts, "v": s.sleep_performance_percentage})

    series_ma = {k: _ma(v) for k, v in series.items()}

    # ---- trends: last 7 entries vs the rest of the window ------------------ #
    trends = {}
    for key, label in (("hrv", "hrv_pct"), ("rhr", "rhr_pct"),
                       ("recovery", "recovery_pct"), ("sleep_hours", "sleep_hours_pct"),
                       ("sleep_performance", "respiratory_placeholder")):
        recent, base = _split_recent([p["v"] for p in series[key]])
        trends[label] = _pct_change(recent, base)
    resp_values = [s.respiratory_rate for s in main_sleeps if s.respiratory_rate is not None]
    recent, base = _split_recent(resp_values)
    trends["respiratory_pct"] = _pct_change(recent, base)
    del trends["respiratory_placeholder"]

    # ---- current status (latest cycle with a recovery + latest sleep) ------ #
    latest_cycle = cycles[-1] if cycles else None
    latest_rec = None
    for c in reversed(cycles):
        if c.id in rec_by_cycle:
            latest_rec = rec_by_cycle[c.id]
            break
    latest_sleep = main_sleeps[-1] if main_sleeps else None
    current = {
        "date": _iso(latest_cycle.start) if latest_cycle else None,
        "strain": latest_cycle.strain if latest_cycle else None,
        "recovery": latest_rec.recovery_score if latest_rec else None,
        "recovery_bucket": _bucket(latest_rec.recovery_score) if latest_rec else None,
        "hrv": latest_rec.hrv_rmssd_milli if latest_rec else None,
        "rhr": latest_rec.resting_heart_rate if latest_rec else None,
        "spo2": latest_rec.spo2_percentage if latest_rec else None,
        "skin_temp": latest_rec.skin_temp_celsius if latest_rec else None,
        "sleep_hours": (
            (latest_sleep.end - latest_sleep.start).total_seconds() / 3600.0
            if latest_sleep and latest_sleep.start and latest_sleep.end
            else None
        ),
        "sleep_performance": (
            latest_sleep.sleep_performance_percentage if latest_sleep else None
        ),
    }

    baselines = {
        "hrv": _stats([p["v"] for p in series["hrv"]]),
        "rhr": _stats([p["v"] for p in series["rhr"]]),
        "recovery": _stats([p["v"] for p in series["recovery"]]),
        "strain": _stats([p["v"] for p in series["strain"]]),
        "sleep_hours": _stats([p["v"] for p in series["sleep_hours"]]),
    }

    # ---- sleep analysis ----------------------------------------------------- #
    bedtime_offsets = []
    for s in main_sleeps:
        if s.start is None:
            continue
        local = s.start + _parse_offset(s.timezone_offset)
        # hours since noon avoids the midnight wrap-around for normal bedtimes
        bedtime_offsets.append(((local.hour + local.minute / 60.0) - 12) % 24)
    sleep_analysis = {
        "avg_hours": _avg([p["v"] for p in series["sleep_hours"]]),
        "avg_performance": _avg([p["v"] for p in series["sleep_performance"]]),
        "avg_respiratory_rate": _avg(resp_values),
        "bedtime_std_hours": (
            pstdev(bedtime_offsets) if len(bedtime_offsets) > 1 else None
        ),
        "nights_under_7h": sum(1 for p in series["sleep_hours"] if p["v"] < 7),
        "nights_total": len(series["sleep_hours"]),
        "naps": sum(1 for s in sleeps if s.nap),
    }

    # ---- training analysis --------------------------------------------------#
    now = datetime.now(timezone.utc)
    overreach = 0
    for c in cycles:
        if c.start is None or c.start < now - timedelta(days=14):
            continue
        r = rec_by_cycle.get(c.id)
        if r and r.recovery_score is not None and r.recovery_score < 34 \
                and c.strain is not None and c.strain >= 12:
            overreach += 1

    weeks: dict[str, dict] = defaultdict(
        lambda: {"workouts": 0, "minutes": 0.0, "kilojoules": 0.0, "strains": []}
    )
    for w in workouts:
        if w.start is None:
            continue
        monday = (w.start - timedelta(days=w.start.weekday())).date().isoformat()
        bucket = weeks[monday]
        bucket["workouts"] += 1
        if w.end is not None:
            bucket["minutes"] += (w.end - w.start).total_seconds() / 60.0
        if w.kilojoule is not None:
            bucket["kilojoules"] += w.kilojoule
        if w.strain is not None:
            bucket["strains"].append(w.strain)
    weekly = [
        {
            "week": k,
            "workouts": v["workouts"],
            "minutes": round(v["minutes"], 1),
            "kilojoules": round(v["kilojoules"], 1),
            "avg_strain": _avg(v["strains"]),
        }
        for k, v in sorted(weeks.items())
    ]
    window_weeks = max(days / 7.0, 1.0)
    training_analysis = {
        "overreach_days_14d": overreach,
        "workouts_per_week": len(workouts) / window_weeks if workouts else 0.0,
        "weekly": weekly,
    }

    sport_counts: dict[str, int] = {}
    sport_minutes: dict[str, float] = {}
    for w in workouts:
        name = w.sport_name or (f"Sport {w.sport_id}" if w.sport_id is not None else "Unknown")
        sport_counts[name] = sport_counts.get(name, 0) + 1
        if w.start is not None and w.end is not None:
            sport_minutes[name] = sport_minutes.get(name, 0.0) + (
                (w.end - w.start).total_seconds() / 60.0
            )

    # ---- records ------------------------------------------------------------#
    def _best(points, key=max):
        return key(points, key=lambda p: p["v"]) if points else None

    records = {
        "best_hrv": _best(series["hrv"]),
        "lowest_rhr": _best(series["rhr"], key=min),
        "best_recovery": _best(series["recovery"]),
        "max_strain": _best(series["strain"]),
        "longest_sleep": _best(series["sleep_hours"]),
    }

    distribution = {"green": 0, "yellow": 0, "red": 0}
    for p in series["recovery"]:
        distribution[_bucket(p["v"])] += 1

    recent_workouts = [
        {
            "id": w.id,
            "sport": w.sport_name,
            "start": _iso(w.start),
            "duration_minutes": (
                (w.end - w.start).total_seconds() / 60.0
                if w.start is not None and w.end is not None else None
            ),
            "strain": w.strain,
            "kilojoule": w.kilojoule,
            "average_heart_rate": w.average_heart_rate,
            "max_heart_rate": w.max_heart_rate,
        }
        for w in sorted(
            workouts,
            key=lambda w: w.start or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )[:10]
    ]

    result = {
        "days": days,
        "since": _iso(cutoff),
        "generated_at": _iso(now),
        "profile": {
            "name": (
                f"{profile.first_name or ''} {profile.last_name or ''}".strip()
                if profile else None
            ),
        },
        "counts": {
            "cycles": len(cycles),
            "recoveries": len(series["recovery"]),
            "sleeps": len(main_sleeps),
            "workouts": len(workouts),
        },
        "averages": {
            "recovery_score": _avg([p["v"] for p in series["recovery"]]),
            "strain": _avg([p["v"] for p in series["strain"]]),
            "hrv_rmssd_milli": _avg([p["v"] for p in series["hrv"]]),
            "resting_heart_rate": _avg([p["v"] for p in series["rhr"]]),
            "spo2_percentage": _avg([r.spo2_percentage for r in recoveries]),
            "skin_temp_celsius": _avg([r.skin_temp_celsius for r in recoveries]),
            "sleep_hours": sleep_analysis["avg_hours"],
            "sleep_performance": sleep_analysis["avg_performance"],
        },
        "totals": {
            "workout_minutes": sum(
                (w.end - w.start).total_seconds() / 60.0
                for w in workouts if w.start is not None and w.end is not None
            ),
            "workout_kilojoules": sum(
                w.kilojoule for w in workouts if w.kilojoule is not None
            ),
        },
        "current": current,
        "baselines": baselines,
        "trends": trends,
        "sleep_analysis": sleep_analysis,
        "training_analysis": training_analysis,
        "recovery_distribution": distribution,
        "workouts_by_sport": sport_counts,
        "workout_minutes_by_sport": {k: round(v, 1) for k, v in sport_minutes.items()},
        "records": records,
        "series": series,
        "series_ma7": series_ma,
        "scatter": scatter,
        "recent_workouts": recent_workouts,
    }
    result["overall"] = _overall_status(current, trends, sleep_analysis)
    result["recommendations"] = _recommendations(result)
    return result


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def compute_insights(db: Session, days: int = 90) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    cycles = list(
        db.scalars(
            select(Cycle)
            .options(load_only(Cycle.id, Cycle.start, Cycle.strain,
                               Cycle.kilojoule, Cycle.max_heart_rate))
            .where(Cycle.start >= cutoff)
            .order_by(Cycle.start)
        ).all()
    )
    cycle_ids = [c.id for c in cycles]
    recoveries = []
    if cycle_ids:
        recoveries = list(
            db.scalars(
                select(Recovery)
                .options(load_only(
                    Recovery.cycle_id, Recovery.recovery_score,
                    Recovery.hrv_rmssd_milli, Recovery.resting_heart_rate,
                    Recovery.spo2_percentage, Recovery.skin_temp_celsius,
                ))
                .where(Recovery.cycle_id.in_(cycle_ids))
            ).all()
        )
    sleeps = list(
        db.scalars(
            select(Sleep)
            .options(load_only(
                Sleep.id, Sleep.start, Sleep.end, Sleep.nap,
                Sleep.timezone_offset, Sleep.sleep_performance_percentage,
                Sleep.respiratory_rate,
            ))
            .where(Sleep.start >= cutoff)
            .order_by(Sleep.start)
        ).all()
    )
    workouts = list(
        db.scalars(
            select(Workout)
            .options(load_only(
                Workout.id, Workout.start, Workout.end, Workout.sport_id,
                Workout.sport_name, Workout.strain, Workout.kilojoule,
                Workout.average_heart_rate, Workout.max_heart_rate,
            ))
            .where(Workout.start >= cutoff)
            .order_by(Workout.start)
        ).all()
    )
    profile = db.scalars(select(Profile)).first()
    return _analyze(cycles, recoveries, sleeps, workouts, profile, days, cutoff)
