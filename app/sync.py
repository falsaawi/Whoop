"""Pull data from Whoop and upsert it into PostgreSQL.

Each ``sync_*`` function fetches a collection, maps the fields we care about,
and performs an idempotent INSERT ... ON CONFLICT DO UPDATE so re-running a sync
never creates duplicates and always refreshes scores that Whoop has recomputed.
"""
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app import whoop_client
from app.models import (
    BodyMeasurement, Cycle, Profile, Recovery, Sleep, SyncRun, Workout,
)


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    # Whoop returns ISO 8601 timestamps ending in 'Z'.
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _upsert(db: Session, model, rows: list[dict], index_elements: list[str]) -> int:
    if not rows:
        return 0
    stmt = insert(model).values(rows)
    update_cols = {
        c.name: stmt.excluded[c.name]
        for c in model.__table__.columns
        if c.name not in index_elements and c.name != "synced_at"
    }
    stmt = stmt.on_conflict_do_update(
        index_elements=index_elements, set_=update_cols
    )
    db.execute(stmt)
    db.commit()
    return len(rows)


# --------------------------------------------------------------------------- #
# Mappers: Whoop record -> DB row dict
# --------------------------------------------------------------------------- #
def _map_cycle(r: dict[str, Any]) -> dict:
    score = r.get("score") or {}
    return {
        "id": r["id"],
        "user_id": r.get("user_id"),
        "start": _dt(r.get("start")),
        "end": _dt(r.get("end")),
        "timezone_offset": r.get("timezone_offset"),
        "score_state": r.get("score_state"),
        "strain": score.get("strain"),
        "kilojoule": score.get("kilojoule"),
        "average_heart_rate": score.get("average_heart_rate"),
        "max_heart_rate": score.get("max_heart_rate"),
        "raw": r,
    }


def _map_recovery(r: dict[str, Any]) -> dict:
    score = r.get("score") or {}
    return {
        "cycle_id": r["cycle_id"],
        "sleep_id": str(r["sleep_id"]) if r.get("sleep_id") is not None else None,
        "user_id": r.get("user_id"),
        "score_state": r.get("score_state"),
        "recovery_score": score.get("recovery_score"),
        "resting_heart_rate": score.get("resting_heart_rate"),
        "hrv_rmssd_milli": score.get("hrv_rmssd_milli"),
        "spo2_percentage": score.get("spo2_percentage"),
        "skin_temp_celsius": score.get("skin_temp_celsius"),
        "raw": r,
    }


def _map_sleep(r: dict[str, Any]) -> dict:
    score = r.get("score") or {}
    stage = score.get("stage_summary") or {}
    return {
        "id": str(r["id"]),
        "user_id": r.get("user_id"),
        "start": _dt(r.get("start")),
        "end": _dt(r.get("end")),
        "timezone_offset": r.get("timezone_offset"),
        "nap": r.get("nap"),
        "score_state": r.get("score_state"),
        "sleep_performance_percentage": score.get("sleep_performance_percentage"),
        "respiratory_rate": score.get("respiratory_rate"),
        "raw": r,
    }


def _map_workout(r: dict[str, Any]) -> dict:
    score = r.get("score") or {}
    return {
        "id": str(r["id"]),
        "user_id": r.get("user_id"),
        "start": _dt(r.get("start")),
        "end": _dt(r.get("end")),
        "timezone_offset": r.get("timezone_offset"),
        "sport_id": r.get("sport_id"),
        "sport_name": r.get("sport_name"),
        "score_state": r.get("score_state"),
        "strain": score.get("strain"),
        "average_heart_rate": score.get("average_heart_rate"),
        "max_heart_rate": score.get("max_heart_rate"),
        "kilojoule": score.get("kilojoule"),
        "raw": r,
    }


# --------------------------------------------------------------------------- #
# Public sync functions
# --------------------------------------------------------------------------- #
def sync_profile(db: Session) -> int:
    r = whoop_client.get_single(db, "/user/profile/basic")
    row = {
        "user_id": r["user_id"],
        "email": r.get("email"),
        "first_name": r.get("first_name"),
        "last_name": r.get("last_name"),
        "raw": r,
    }
    return _upsert(db, Profile, [row], ["user_id"])


def sync_body(db: Session) -> int:
    r = whoop_client.get_single(db, "/user/measurement/body")
    row = {
        "id": 1,
        "height_meter": r.get("height_meter"),
        "weight_kilogram": r.get("weight_kilogram"),
        "max_heart_rate": r.get("max_heart_rate"),
        "raw": r,
    }
    return _upsert(db, BodyMeasurement, [row], ["id"])


def sync_cycles(db: Session, params: dict | None = None) -> int:
    records = whoop_client.get_collection(db, "/cycle", params)
    rows = [_map_cycle(r) for r in records]
    return _upsert(db, Cycle, rows, ["id"])


def sync_recovery(db: Session, params: dict | None = None) -> int:
    records = whoop_client.get_collection(db, "/recovery", params)
    rows = [_map_recovery(r) for r in records]
    return _upsert(db, Recovery, rows, ["cycle_id"])


def sync_sleep(db: Session, params: dict | None = None) -> int:
    records = whoop_client.get_collection(db, "/activity/sleep", params)
    rows = [_map_sleep(r) for r in records]
    return _upsert(db, Sleep, rows, ["id"])


def sync_workouts(db: Session, params: dict | None = None) -> int:
    records = whoop_client.get_collection(db, "/activity/workout", params)
    rows = [_map_workout(r) for r in records]
    return _upsert(db, Workout, rows, ["id"])


def sync_all(db: Session, params: dict | None = None) -> dict[str, int]:
    """Sync every collection.  ``params`` may contain start/end date filters."""
    return {
        "profile": sync_profile(db),
        "body": sync_body(db),
        "cycles": sync_cycles(db, params),
        "recovery": sync_recovery(db, params),
        "sleep": sync_sleep(db, params),
        "workouts": sync_workouts(db, params),
    }


def run_and_log(
    db: Session, trigger: str, params: dict | None = None
) -> SyncRun:
    """Run :func:`sync_all` and record the outcome in the ``sync_runs`` table.

    Re-raises any exception after logging it so callers can still surface errors
    (e.g. as an HTTP 401), while the failure is persisted for auditing.
    """
    run = SyncRun(
        trigger=trigger,
        status="running",
        since=(params or {}).get("start"),
        started_at=datetime.now(timezone.utc),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    try:
        counts = sync_all(db, params)
    except Exception as exc:
        run.status = "error"
        run.error = str(exc)
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        raise

    run.status = "success"
    run.counts = counts
    run.finished_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(run)
    return run
