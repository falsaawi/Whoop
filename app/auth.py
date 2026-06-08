"""OAuth 2.0 routes: kick off authorization and handle the Whoop callback."""
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app import whoop_client
from app.database import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/login")
def login(request: Request):
    """Redirect the user to Whoop to authorize access to their data."""
    state = secrets.token_urlsafe(24)
    request.session["oauth_state"] = state
    return RedirectResponse(whoop_client.build_authorize_url(state))


@router.get("/callback")
def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
):
    """Whoop redirects here with ?code=...  We exchange it for tokens."""
    if error:
        raise HTTPException(status_code=400, detail=f"Whoop returned error: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code.")

    expected_state = request.session.pop("oauth_state", None)
    if not state or state != expected_state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state.")

    whoop_client.exchange_code_for_token(db, code)
    return {
        "status": "authorized",
        "message": "Whoop account connected. You can now POST /sync to pull data.",
    }
