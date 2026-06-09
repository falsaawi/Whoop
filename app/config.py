"""Application configuration loaded from environment variables / .env file."""
import os
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

# Alternative env vars that may hold the Postgres URL, e.g. injected by the
# Vercel/Neon marketplace integration (prefixed with the project name).
_DB_URL_FALLBACK_VARS = (
    "Whoop_DATABASE_URL",
    "Whoop_POSTGRES_URL",
    "POSTGRES_URL",
    "NEON_DATABASE_URL",
)


def _normalize_db_url(url: str) -> str:
    """Rewrite generic Postgres schemes to SQLAlchemy's psycopg3 dialect."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def _is_usable_db_url(url: str) -> bool:
    """True if the URL parses and has a plausible remote host (catches the
    literal '…' left behind by copying a truncated string from a dashboard)."""
    try:
        host = make_url(url).host or ""
    except Exception:
        return False
    return bool(host) and host.isascii() and host not in ("localhost", "127.0.0.1")


class Settings(BaseSettings):
    # Whoop OAuth. Empty defaults keep the app importable when env vars are
    # missing (e.g. fresh deploy); /health reports them as unconfigured.
    whoop_client_id: str = ""
    whoop_client_secret: str = ""
    whoop_redirect_uri: str = "http://localhost:8000/auth/callback"
    whoop_scopes: str = (
        "offline read:recovery read:cycles read:sleep "
        "read:workout read:profile read:body_measurement"
    )

    # Whoop API endpoints (override-able, e.g. to switch API version)
    whoop_auth_url: str = "https://api.prod.whoop.com/oauth/oauth2/auth"
    whoop_token_url: str = "https://api.prod.whoop.com/oauth/oauth2/token"
    whoop_api_base: str = "https://api.prod.whoop.com/developer/v1"

    # Database
    database_url: str = "postgresql+psycopg://whoop:whoop@localhost:5432/whoop"

    # App
    session_secret: str = "change_me"

    # Daily cron sync
    # Secret that Vercel Cron sends as "Authorization: Bearer <secret>".
    cron_secret: str | None = None
    # Rolling window (days) re-fetched on each daily sync so that scores Whoop
    # finalizes a day or two late still get updated.
    sync_lookback_days: int = 7
    # Run CREATE TABLE IF NOT EXISTS on startup. Set false once tables exist to
    # avoid DDL on every serverless cold start.
    auto_create_tables: bool = True

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def _resolve_database_url(self) -> "Settings":
        candidates = [self.database_url] + [
            os.environ.get(var, "") for var in _DB_URL_FALLBACK_VARS
        ]
        for candidate in candidates:
            if candidate and _is_usable_db_url(candidate):
                self.database_url = _normalize_db_url(candidate)
                return self
        # Nothing remote found; keep the (normalized) configured value so
        # local development against localhost still works.
        self.database_url = _normalize_db_url(self.database_url)
        return self

    @property
    def scope_list(self) -> list[str]:
        return self.whoop_scopes.split()


@lru_cache
def get_settings() -> Settings:
    return Settings()
