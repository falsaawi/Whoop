"""FastAPI application entry point.

Run with:  uvicorn app.main:app --reload
"""
from fastapi import Depends, FastAPI, HTTPException, Query
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
