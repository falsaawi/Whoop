"""Thin client around the Whoop developer API.

Handles the OAuth 2.0 authorization-code flow, automatic access-token refresh,
and paginated collection fetching.  Tokens are persisted in the ``oauth_tokens``
table via :class:`app.models.TokenStore`.
"""
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import TokenStore

settings = get_settings()


class WhoopAuthError(RuntimeError):
    """Raised when we have no valid token and cannot refresh."""


# --------------------------------------------------------------------------- #
# OAuth helpers
# --------------------------------------------------------------------------- #
def build_authorize_url(state: str) -> str:
    """URL the user visits to grant access to their Whoop data."""
    params = {
        "response_type": "code",
        "client_id": settings.whoop_client_id,
        "redirect_uri": settings.whoop_redirect_uri,
        "scope": " ".join(settings.scope_list),
        "state": state,
    }
    return f"{settings.whoop_auth_url}?{urlencode(params)}"


def _save_token(db: Session, payload: dict) -> TokenStore:
    """Persist a token response (from auth or refresh) into the single-row table."""
    expires_at = None
    if payload.get("expires_in") is not None:
        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=int(payload["expires_in"])
        )

    token = db.get(TokenStore, 1)
    if token is None:
        token = TokenStore(id=1)
        db.add(token)

    token.access_token = payload["access_token"]
    # Whoop only returns a refresh_token when the "offline" scope is granted;
    # keep the existing one on refresh responses that omit it.
    if payload.get("refresh_token"):
        token.refresh_token = payload["refresh_token"]
    token.token_type = payload.get("token_type", "bearer")
    token.scope = payload.get("scope")
    token.expires_at = expires_at
    db.commit()
    db.refresh(token)
    return token


def exchange_code_for_token(db: Session, code: str) -> TokenStore:
    """Swap an authorization ``code`` (from the OAuth callback) for tokens."""
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": settings.whoop_client_id,
        "client_secret": settings.whoop_client_secret,
        "redirect_uri": settings.whoop_redirect_uri,
    }
    resp = httpx.post(settings.whoop_token_url, data=data, timeout=30)
    resp.raise_for_status()
    return _save_token(db, resp.json())


def _refresh_token(db: Session, token: TokenStore) -> TokenStore:
    if not token.refresh_token:
        raise WhoopAuthError(
            "Access token expired and no refresh token is available. "
            "Re-authorize at /auth/login (ensure the 'offline' scope is granted)."
        )
    data = {
        "grant_type": "refresh_token",
        "refresh_token": token.refresh_token,
        "client_id": settings.whoop_client_id,
        "client_secret": settings.whoop_client_secret,
        "scope": "offline",
    }
    resp = httpx.post(settings.whoop_token_url, data=data, timeout=30)
    resp.raise_for_status()
    return _save_token(db, resp.json())


def get_valid_access_token(db: Session) -> str:
    """Return a non-expired access token, refreshing it if necessary."""
    token = db.get(TokenStore, 1)
    if token is None:
        raise WhoopAuthError("Not authorized yet. Visit /auth/login first.")

    # Refresh if the token expires within the next 60 seconds.
    if token.expires_at is not None:
        expires_at = token.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc) + timedelta(seconds=60):
            token = _refresh_token(db, token)

    return token.access_token


# --------------------------------------------------------------------------- #
# Data fetching
# --------------------------------------------------------------------------- #
def get_collection(db: Session, path: str, params: dict | None = None) -> list[dict]:
    """Fetch every record from a paginated Whoop collection endpoint.

    Whoop returns ``{"records": [...], "next_token": "..."}``.  We follow
    ``next_token`` until it is absent, accumulating all records.
    """
    params = dict(params or {})
    records: list[dict] = []
    url = f"{settings.whoop_api_base}{path}"

    with httpx.Client(timeout=30) as client:
        while True:
            access_token = get_valid_access_token(db)
            headers = {"Authorization": f"Bearer {access_token}"}
            resp = client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            body = resp.json()

            records.extend(body.get("records", []))
            next_token = body.get("next_token")
            if not next_token:
                break
            params["nextToken"] = next_token

    return records


def get_single(db: Session, path: str) -> dict:
    """Fetch a single (non-paginated) resource, e.g. the user profile."""
    access_token = get_valid_access_token(db)
    headers = {"Authorization": f"Bearer {access_token}"}
    resp = httpx.get(f"{settings.whoop_api_base}{path}", headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()
