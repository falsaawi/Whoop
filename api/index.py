"""Vercel serverless entrypoint.

Vercel's Python runtime detects the ASGI ``app`` object exported here and serves
the whole FastAPI application from it. All routes (/auth/login, /sync,
/cron/sync, read endpoints) are handled through this single function.
"""
from app.main import app  # noqa: F401  (Vercel looks for `app`)
