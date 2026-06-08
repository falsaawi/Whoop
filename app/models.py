"""Database models for Whoop OAuth tokens and the data we pull from the API.

Each data table keeps a couple of commonly-queried columns *plus* the full raw
JSON payload (``raw``) returned by Whoop.  Storing the raw payload makes the
pipeline resilient to Whoop API schema changes -- you never lose data even if a
new field appears that we don't explicitly map.
"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TokenStore(Base):
    """Single-row table holding the current OAuth tokens for the user."""

    __tablename__ = "oauth_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    access_token: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_type: Mapped[str] = mapped_column(String(32), default="bearer")
    scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SyncRun(Base):
    """One row per /sync or /cron/sync invocation — an audit log so you can see
    when the daily sync last ran and whether it succeeded."""

    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trigger: Mapped[str] = mapped_column(String(16))  # "manual" | "cron"
    status: Mapped[str] = mapped_column(String(16))  # "running" | "success" | "error"
    since: Mapped[str | None] = mapped_column(String(32))
    counts: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Profile(Base):
    __tablename__ = "profiles"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str | None] = mapped_column(String(255))
    first_name: Mapped[str | None] = mapped_column(String(255))
    last_name: Mapped[str | None] = mapped_column(String(255))
    raw: Mapped[dict] = mapped_column(JSONB)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Cycle(Base):
    __tablename__ = "cycles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timezone_offset: Mapped[str | None] = mapped_column(String(16))
    score_state: Mapped[str | None] = mapped_column(String(32))
    strain: Mapped[float | None] = mapped_column(Float)
    kilojoule: Mapped[float | None] = mapped_column(Float)
    average_heart_rate: Mapped[int | None] = mapped_column(Integer)
    max_heart_rate: Mapped[int | None] = mapped_column(Integer)
    raw: Mapped[dict] = mapped_column(JSONB)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Recovery(Base):
    __tablename__ = "recoveries"

    # Recovery is keyed by the cycle it belongs to.
    cycle_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    sleep_id: Mapped[str | None] = mapped_column(String(64), index=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    score_state: Mapped[str | None] = mapped_column(String(32))
    recovery_score: Mapped[float | None] = mapped_column(Float)
    resting_heart_rate: Mapped[float | None] = mapped_column(Float)
    hrv_rmssd_milli: Mapped[float | None] = mapped_column(Float)
    spo2_percentage: Mapped[float | None] = mapped_column(Float)
    skin_temp_celsius: Mapped[float | None] = mapped_column(Float)
    raw: Mapped[dict] = mapped_column(JSONB)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Sleep(Base):
    __tablename__ = "sleeps"

    # v1 uses integer ids, v2 uses UUID strings -> store as string to support both.
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timezone_offset: Mapped[str | None] = mapped_column(String(16))
    nap: Mapped[bool | None] = mapped_column()
    score_state: Mapped[str | None] = mapped_column(String(32))
    sleep_performance_percentage: Mapped[float | None] = mapped_column(Float)
    respiratory_rate: Mapped[float | None] = mapped_column(Float)
    raw: Mapped[dict] = mapped_column(JSONB)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Workout(Base):
    __tablename__ = "workouts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timezone_offset: Mapped[str | None] = mapped_column(String(16))
    sport_id: Mapped[int | None] = mapped_column(Integer)
    sport_name: Mapped[str | None] = mapped_column(String(128))
    score_state: Mapped[str | None] = mapped_column(String(32))
    strain: Mapped[float | None] = mapped_column(Float)
    average_heart_rate: Mapped[int | None] = mapped_column(Integer)
    max_heart_rate: Mapped[int | None] = mapped_column(Integer)
    kilojoule: Mapped[float | None] = mapped_column(Float)
    raw: Mapped[dict] = mapped_column(JSONB)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
