"""FastAPI application entry point.

Run with:  uvicorn app.main:app --reload
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import socket
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi import Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app import sync
from app.auth import router as auth_router
from app.config import get_settings
from app.dashboard import router as dashboard_router
from app.database import get_db, init_db
from app.models import (
    Cycle, HeartRateSample, Profile, Recovery, Sleep, SyncRun, Workout,
)
from app.whoop_client import WhoopAuthError

settings = get_settings()

app = FastAPI(
    title="Whoop Data API",
    description="Pull Whoop data via OAuth 2.0 and store it in PostgreSQL.",
    version="1.0.0",
)
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret)
app.include_router(auth_router)
app.include_router(dashboard_router)

# TripSplit static app — bundled travel expense splitter. Served at /splitter.
_splitter_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "splitter")
if os.path.isdir(_splitter_dir):
    app.mount(
        "/splitter",
        StaticFiles(directory=_splitter_dir, html=True),
        name="splitter",
    )


@app.on_event("startup")
def on_startup() -> None:
    if settings.auto_create_tables:
        try:
            init_db()
        except Exception as exc:  # keep the app up so /health can report it
            logging.getLogger(__name__).warning("init_db failed on startup: %s", exc)


@app.get("/")
def root():
    return {
        "service": "Whoop Data API",
        "next_steps": [
            "1. GET /auth/login to connect your Whoop account",
            "2. POST /sync to pull your data into PostgreSQL",
            "3. GET /dashboard for a visual summary, or /recovery, /sleep, /workouts, /cycles, /profile for raw data",
        ],
    }


@app.get("/health")
def health():
    """Liveness check that also reports what's left to configure."""
    missing = [
        name
        for name, value in (
            ("WHOOP_CLIENT_ID", settings.whoop_client_id),
            ("WHOOP_CLIENT_SECRET", settings.whoop_client_secret),
            ("CRON_SECRET", settings.cron_secret),
        )
        if not value
    ]
    if "localhost" in settings.database_url:
        missing.append("DATABASE_URL (still pointing at localhost)")

    from app.database import engine

    # On Vercel/Lambda a bad hostname surfaces as a cryptic EBUSY, so check
    # DNS explicitly and expose the host (never credentials) to aid debugging.
    db_host = engine.url.host or ""
    try:
        socket.getaddrinfo(db_host, engine.url.port or 5432)
        dns = "ok"
    except OSError as exc:
        dns = f"cannot resolve: {exc}"

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        database = "ok"
    except Exception as exc:
        database = f"unreachable: {str(exc)[:200]}"

    status = "ok" if not missing and database == "ok" else "needs_configuration"
    return {
        "status": status,
        "missing_env_vars": missing,
        "database": database,
        "database_host": repr(db_host),
        "database_host_dns": dns,
    }


@app.post("/admin/init-db")
def admin_init_db(request: Request):
    """Create database tables. Run once after deploying (serverless platforms
    don't reliably fire startup events). Protected by CRON_SECRET."""
    _verify_cron(request)
    init_db()
    return {"status": "tables created"}


def _serialize(obj) -> dict:
    """Turn a SQLAlchemy model instance into a JSON-serializable dict."""
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


def _date_params(start: str | None, end: str | None) -> dict:
    params: dict[str, str] = {}
    if start:
        params["start"] = start
    if end:
        params["end"] = end
    return params


@app.post("/sync")
def trigger_sync(
    start: str | None = Query(None, description="ISO start, e.g. 2026-01-01T00:00:00Z"),
    end: str | None = Query(None, description="ISO end, e.g. 2026-06-08T00:00:00Z"),
    db: Session = Depends(get_db),
):
    """Pull every Whoop collection and upsert into the database."""
    try:
        run = sync.run_and_log(db, "manual", _date_params(start, end))
    except WhoopAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    return {"run_id": run.id, "synced": run.counts}


def _verify_cron(request: Request) -> None:
    """Ensure the caller is Vercel Cron (or someone holding CRON_SECRET).

    Vercel automatically sends ``Authorization: Bearer $CRON_SECRET`` on cron
    invocations when the CRON_SECRET env var is set.
    """
    if not settings.cron_secret:
        # No secret configured -> allow (useful for local testing only).
        return
    auth = request.headers.get("authorization", "")
    if auth != f"Bearer {settings.cron_secret}":
        raise HTTPException(status_code=401, detail="Unauthorized cron request.")


@app.get("/cron/sync")
def cron_sync(request: Request, db: Session = Depends(get_db)):
    """Daily incremental sync, triggered by Vercel Cron.

    Re-fetches a rolling window (``SYNC_LOOKBACK_DAYS``) and upserts it, so newly
    finalized scores are updated without duplicating existing rows.
    """
    _verify_cron(request)
    since = datetime.now(timezone.utc) - timedelta(days=settings.sync_lookback_days)
    start = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        run = sync.run_and_log(db, "cron", {"start": start})
    except WhoopAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    return {"run_id": run.id, "synced": run.counts, "since": start}


@app.post("/webhooks/whoop")
async def whoop_webhook(request: Request, db: Session = Depends(get_db)):
    """Receive Whoop webhook events (sleep/recovery/workout created or updated)
    and run a short lookback sync, so the data lands minutes after Whoop scores
    it instead of waiting for the daily cron.

    Signature scheme per Whoop docs: base64(HMAC-SHA256(client_secret,
    timestamp + raw_body)) in X-WHOOP-Signature.
    """
    body = await request.body()
    if settings.whoop_client_secret:
        ts = request.headers.get("x-whoop-signature-timestamp", "")
        provided = request.headers.get("x-whoop-signature", "")
        expected = base64.b64encode(
            hmac.new(
                settings.whoop_client_secret.encode(),
                ts.encode() + body,
                hashlib.sha256,
            ).digest()
        ).decode()
        if not hmac.compare_digest(provided, expected):
            raise HTTPException(status_code=401, detail="Invalid webhook signature.")

    try:
        event = json.loads(body or b"{}")
    except ValueError:
        event = {}
    event_type = event.get("type", "unknown")

    # Whoop fires several events at once (waking up scores sleep, recovery and
    # cycle together) — debounce so one burst triggers a single sync.
    last = db.scalars(
        select(SyncRun)
        .where(SyncRun.status == "success")
        .order_by(SyncRun.finished_at.desc())
        .limit(1)
    ).first()
    now = datetime.now(timezone.utc)
    if last and last.finished_at is not None:
        finished = last.finished_at
        if finished.tzinfo is None:
            finished = finished.replace(tzinfo=timezone.utc)
        if now - finished < timedelta(minutes=2):
            return {"status": "skipped", "reason": "synced moments ago", "event": event_type}

    start = (now - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        run = sync.run_and_log(db, "webhook", {"start": start})
    except WhoopAuthError as exc:
        # Still 200: webhook retries can't fix auth; the error is logged in sync_runs.
        return {"status": "auth_error", "detail": str(exc)}
    return {"status": "ok", "run_id": run.id, "event": event_type, "synced": run.counts}


@app.post("/ingest/heart-rate")
def ingest_heart_rate(payload: dict, request: Request, db: Session = Depends(get_db)):
    """Receive continuous heart-rate samples from a local BLE collector.

    Body: {"samples": [{"ts": "2026-06-12T10:00:00Z", "bpm": 62}, ...],
           "source": "ble"}
    Auth: Authorization: Bearer <CRON_SECRET> (same secret as the cron).
    """
    _verify_cron(request)
    samples = payload.get("samples") or []
    if not samples:
        return {"stored": 0}
    if len(samples) > 5000:
        raise HTTPException(status_code=413, detail="Too many samples in one batch.")
    source = str(payload.get("source") or "ble")[:32]

    rows = []
    for s in samples:
        try:
            ts = datetime.fromisoformat(str(s["ts"]).replace("Z", "+00:00"))
            bpm = float(s["bpm"])
        except (KeyError, TypeError, ValueError):
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if 20 <= bpm <= 250:
            rows.append({"ts": ts, "bpm": bpm, "source": source})
    if rows:
        stmt = pg_insert(HeartRateSample).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["ts"], set_={"bpm": stmt.excluded.bpm}
        )
        db.execute(stmt)
        db.commit()
    return {"stored": len(rows)}


@app.get("/api/heart-rate")
def api_heart_rate(
    response: Response,
    hours: int = Query(6, ge=1, le=168),
    db: Session = Depends(get_db),
):
    """Minute-averaged continuous heart rate for the last N hours."""
    response.headers["Cache-Control"] = "public, s-maxage=60, stale-while-revalidate=300"
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    minute = func.date_trunc("minute", HeartRateSample.ts).label("t")
    stmt = (
        select(
            minute,
            func.avg(HeartRateSample.bpm).label("avg"),
            func.min(HeartRateSample.bpm).label("min"),
            func.max(HeartRateSample.bpm).label("max"),
        )
        .where(HeartRateSample.ts >= since)
        .group_by(minute)
        .order_by(minute)
    )
    points = [
        {"t": row[0].isoformat(), "avg": round(float(row[1]), 1),
         "min": float(row[2]), "max": float(row[3])}
        for row in db.execute(stmt).all()
    ]
    return {"hours": hours, "points": points}


@app.get("/sync/history")
def sync_history(limit: int = 20, db: Session = Depends(get_db)):
    """Most recent sync runs (audit log) — newest first."""
    stmt = select(SyncRun).order_by(SyncRun.started_at.desc()).limit(limit)
    return [_serialize(o) for o in db.scalars(stmt).all()]


# --------------------------------------------------------------------------- #
# Read endpoints
# --------------------------------------------------------------------------- #
@app.get("/profile")
def get_profile(db: Session = Depends(get_db)):
    return [_serialize(o) for o in db.scalars(select(Profile)).all()]


@app.get("/cycles")
def get_cycles(limit: int = 50, db: Session = Depends(get_db)):
    stmt = select(Cycle).order_by(Cycle.start.desc()).limit(limit)
    return [_serialize(o) for o in db.scalars(stmt).all()]


@app.get("/recovery")
def get_recovery(limit: int = 50, db: Session = Depends(get_db)):
    stmt = select(Recovery).order_by(Recovery.cycle_id.desc()).limit(limit)
    return [_serialize(o) for o in db.scalars(stmt).all()]


@app.get("/sleep")
def get_sleep(limit: int = 50, db: Session = Depends(get_db)):
    stmt = select(Sleep).order_by(Sleep.start.desc()).limit(limit)
    return [_serialize(o) for o in db.scalars(stmt).all()]


@app.get("/workouts")
def get_workouts(limit: int = 50, db: Session = Depends(get_db)):
    stmt = select(Workout).order_by(Workout.start.desc()).limit(limit)
    return [_serialize(o) for o in db.scalars(stmt).all()]
