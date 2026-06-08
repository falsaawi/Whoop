"""FastAPI application entry point.

Run with:  uvicorn app.main:app --reload
"""
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app import sync
from app.auth import router as auth_router
from app.config import get_settings
from app.database import get_db, init_db
from app.models import Cycle, Profile, Recovery, Sleep, Workout
from app.whoop_client import WhoopAuthError

settings = get_settings()

app = FastAPI(
    title="Whoop Data API",
    description="Pull Whoop data via OAuth 2.0 and store it in PostgreSQL.",
    version="1.0.0",
)
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret)
app.include_router(auth_router)


@app.on_event("startup")
def on_startup() -> None:
    if settings.auto_create_tables:
        init_db()


@app.get("/")
def root():
    return {
        "service": "Whoop Data API",
        "next_steps": [
            "1. GET /auth/login to connect your Whoop account",
            "2. POST /sync to pull your data into PostgreSQL",
            "3. GET /recovery, /sleep, /workouts, /cycles, /profile to read it",
        ],
    }


@app.get("/health")
def health():
    return {"status": "ok"}


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
        result = sync.sync_all(db, _date_params(start, end))
    except WhoopAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    return {"synced": result}


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
        result = sync.sync_all(db, {"start": start})
    except WhoopAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    return {"synced": result, "since": start}


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
