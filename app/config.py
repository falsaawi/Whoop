"""Application configuration loaded from environment variables / .env file."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Whoop OAuth
    whoop_client_id: str
    whoop_client_secret: str
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
    database_url: str = "postgresql+psycopg2://whoop:whoop@localhost:5432/whoop"

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

    @property
    def scope_list(self) -> list[str]:
        return self.whoop_scopes.split()


@lru_cache
def get_settings() -> Settings:
    return Settings()
