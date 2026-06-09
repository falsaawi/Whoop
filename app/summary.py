"""Aggregate Whoop data stored in PostgreSQL into a summary payload.

Used by the ``/dashboard`` page (HTML) and the ``/api/summary`` JSON endpoint.
Keeps queries simple: pulls rows for the requested time window and computes
averages, distributions and time series in Python. Volumes are small (a year
of data is roughly 365 cycles + matching recoveries/sleeps/workouts), so this
is fast and avoids fragile SQL aggregations across the join.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Cycle, Profile, Recovery, Sleep, Workout


def _avg(values):
    clean = [v for v in values if v is not None]
    return sum(clean) / len(clean) if clean else None


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def _bucket(score: float | None) -> str | None:
    """Whoop's traffic-light recovery bands: red <34, yellow 34-66, green 67+."""
    if score is None:
        return None
    if score >= 67:
        return "green"
    if score >= 34:
        return "yellow"
    return "red"


def compute_summary(db: Session, days: int = 30) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    cycles = list(
        db.scalars(
            select(Cycle).where(Cycle.start >= cutoff).order_by(Cycle.start)
        ).all()
    )
    cycle_ids = [c.id for c in cycles]

    recoveries = []
    if cycle_ids:
        recoveries = list(
            db.scalars(
                select(Recovery).where(Recovery.cycle_id.in_(cycle_ids))
            ).all()
        )

    sleeps = list(
        db.scalars(
            select(Sleep).where(Sleep.start >= cutoff).order_by(Sleep.start)
        ).all()
    )

    workouts = list(
        db.scalars(
            select(Workout).where(Workout.start >= cutoff).order_by(Workout.start)
        ).all()
    )

    profile = db.scalars(select(Profile)).first()

    rec_by_cycle = {r.cycle_id: r for r in recoveries}
    main_sleeps = [s for s in sleeps if not s.nap]

    rec_scores = [r.recovery_score for r in recoveries if r.recovery_score is not None]
    distribution = {"green": 0, "yellow": 0, "red": 0}
    for s in rec_scores:
        distribution[_bucket(s)] += 1

    sport_counts: dict[str, int] = {}
    for w in workouts:
        name = w.sport_name or (f"Sport {w.sport_id}" if w.sport_id is not None else "Unknown")
        sport_counts[name] = sport_counts.get(name, 0) + 1

    recovery_series = []
    hrv_series = []
    rhr_series = []
    strain_series = []
    for c in cycles:
        if c.start is None:
            continue
        ts = _iso(c.start)
        if c.strain is not None:
            strain_series.append({"t": ts, "v": c.strain})
        r = rec_by_cycle.get(c.id)
        if r is None:
            continue
        if r.recovery_score is not None:
            recovery_series.append({"t": ts, "v": r.recovery_score})
        if r.hrv_rmssd_milli is not None:
            hrv_series.append({"t": ts, "v": r.hrv_rmssd_milli})
        if r.resting_heart_rate is not None:
            rhr_series.append({"t": ts, "v": r.resting_heart_rate})

    sleep_series = [
        {"t": _iso(s.start), "v": s.sleep_performance_percentage}
        for s in main_sleeps
        if s.start is not None and s.sleep_performance_percentage is not None
    ]

    sleep_durations_hours = [
        (s.end - s.start).total_seconds() / 3600.0
        for s in main_sleeps
        if s.start is not None and s.end is not None
    ]

    sleep_duration_series = [
        {"t": _iso(s.start), "v": (s.end - s.start).total_seconds() / 3600.0}
        for s in main_sleeps
        if s.start is not None and s.end is not None
    ]

    recent_workouts = [
        {
            "id": w.id,
            "sport": w.sport_name,
            "start": _iso(w.start),
            "end": _iso(w.end),
            "duration_minutes": (
                (w.end - w.start).total_seconds() / 60.0
                if w.start is not None and w.end is not None
                else None
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

    return {
        "days": days,
        "since": _iso(cutoff),
        "profile": {
            "name": (
                f"{profile.first_name or ''} {profile.last_name or ''}".strip()
                if profile
                else None
            ),
            "email": profile.email if profile else None,
        },
        "counts": {
            "cycles": len(cycles),
            "recoveries": len(rec_scores),
            "sleeps": len(main_sleeps),
            "naps": sum(1 for s in sleeps if s.nap),
            "workouts": len(workouts),
        },
        "averages": {
            "recovery_score": _avg([r.recovery_score for r in recoveries]),
            "strain": _avg([c.strain for c in cycles]),
            "hrv_rmssd_milli": _avg([r.hrv_rmssd_milli for r in recoveries]),
            "resting_heart_rate": _avg([r.resting_heart_rate for r in recoveries]),
            "spo2_percentage": _avg([r.spo2_percentage for r in recoveries]),
            "skin_temp_celsius": _avg([r.skin_temp_celsius for r in recoveries]),
            "sleep_performance": _avg(
                [s.sleep_performance_percentage for s in main_sleeps]
            ),
            "respiratory_rate": _avg([s.respiratory_rate for s in main_sleeps]),
            "sleep_hours": _avg(sleep_durations_hours),
            "max_heart_rate": _avg([c.max_heart_rate for c in cycles]),
        },
        "totals": {
            "kilojoules": sum(c.kilojoule for c in cycles if c.kilojoule is not None),
            "workout_kilojoules": sum(
                w.kilojoule for w in workouts if w.kilojoule is not None
            ),
            "workout_minutes": sum(
                (w.end - w.start).total_seconds() / 60.0
                for w in workouts
                if w.start is not None and w.end is not None
            ),
        },
        "recovery_distribution": distribution,
        "workouts_by_sport": sport_counts,
        "series": {
            "recovery": recovery_series,
            "strain": strain_series,
            "sleep_performance": sleep_series,
            "sleep_hours": sleep_duration_series,
            "hrv": hrv_series,
            "rhr": rhr_series,
        },
        "recent_workouts": recent_workouts,
    }
