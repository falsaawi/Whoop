# Whoop Data API

Pull your personal [Whoop](https://www.whoop.com/) data (recovery, sleep,
workouts, cycles, profile) via the official Whoop developer API using OAuth 2.0,
and store it in PostgreSQL.

Built with **FastAPI** + **SQLAlchemy** + **PostgreSQL**.

```
You ──(browser)──▶ /auth/login ──▶ Whoop authorize screen
                                        │
        Whoop redirects back with ?code=…
                                        ▼
        /auth/callback  ──exchange──▶  access + refresh token  ──▶  oauth_tokens table
                                        │
        POST /sync ──▶ Whoop REST API ──map──▶ PostgreSQL (cycles, recovery, sleep, workouts)
                                        │
        GET /recovery /sleep /workouts /cycles /profile ◀── read your stored data
```

---

## Step 1 — Get Whoop API credentials

1. Go to the **Whoop Developer Dashboard**: <https://developer.whoop.com>
2. Sign in with your normal Whoop account and create a **Team** if prompted.
3. Create a **New Application**. Fill in:
   - **Name**: anything, e.g. `My Data Pipeline`.
   - **Redirect URIs**: add **exactly** `http://localhost:8000/auth/callback`
     (it must match `WHOOP_REDIRECT_URI` in your `.env` character-for-character).
   - **Scopes**: enable `read:recovery`, `read:cycles`, `read:sleep`,
     `read:workout`, `read:profile`, `read:body_measurement`, and **`offline`**
     (`offline` is what gets you a refresh token so syncing keeps working).
4. After creating the app you'll see a **Client ID** and **Client Secret** —
   copy both. You'll paste them into `.env` in Step 3.

> Note: Whoop's self-serve apps authorize **your own** account by default,
> which is exactly what we want here.

---

## Step 2 — Start PostgreSQL

The easiest path is Docker (matches the default `DATABASE_URL`):

```bash
docker compose up -d
```

This starts Postgres on `localhost:5432` with user/password/db all `whoop`.

> Already have your own Postgres? Skip Docker and just point `DATABASE_URL`
> at it in Step 3.

---

## Step 3 — Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set:

- `WHOOP_CLIENT_ID` and `WHOOP_CLIENT_SECRET` — from Step 1.
- `SESSION_SECRET` — generate one:
  ```bash
  python -c "import secrets; print(secrets.token_hex(32))"
  ```
- Leave `WHOOP_REDIRECT_URI` and `DATABASE_URL` as-is unless you changed them.

---

## Step 4 — Install dependencies & run the API

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

uvicorn app.main:app --reload
```

Tables are created automatically on startup. Open the interactive docs at
<http://localhost:8000/docs>.

---

## Step 5 — Connect your Whoop account (OAuth)

In your **browser**, visit:

```
http://localhost:8000/auth/login
```

You'll be sent to Whoop, asked to authorize, then redirected back to
`/auth/callback`, which stores your tokens in the `oauth_tokens` table. You only
do this once — the API auto-refreshes the token after that.

---

## Step 6 — Pull (sync) your data

```bash
# Sync everything Whoop has
curl -X POST http://localhost:8000/sync

# Or limit to a date range (ISO 8601, UTC)
curl -X POST "http://localhost:8000/sync?start=2026-01-01T00:00:00Z&end=2026-06-08T00:00:00Z"
```

Response tells you how many records were upserted per collection:

```json
{ "synced": { "profile": 1, "cycles": 120, "recovery": 118, "sleep": 130, "workouts": 45 } }
```

Re-running `/sync` is **idempotent** — it updates existing rows instead of
creating duplicates (INSERT … ON CONFLICT DO UPDATE).

---

## Step 7 — Read your stored data

```bash
curl http://localhost:8000/profile
curl http://localhost:8000/recovery
curl http://localhost:8000/sleep
curl http://localhost:8000/workouts
curl http://localhost:8000/cycles
```

Or query Postgres directly:

```bash
docker exec -it whoop-postgres psql -U whoop -d whoop \
  -c "SELECT start, recovery_score, hrv_rmssd_milli, resting_heart_rate
      FROM recoveries r JOIN cycles c ON c.id = r.cycle_id
      ORDER BY start DESC LIMIT 10;"
```

---

## Project layout

```
app/
├── main.py          FastAPI app: /sync + read endpoints, table creation
├── auth.py          OAuth login + callback routes
├── whoop_client.py  OAuth flow, token refresh, paginated API fetching
├── sync.py          Map Whoop records -> DB rows, idempotent upserts
├── models.py        SQLAlchemy tables (incl. raw JSONB of every payload)
├── database.py      Engine / session / Base
└── config.py        Settings loaded from .env
docker-compose.yml   Local PostgreSQL
requirements.txt
.env.example
```

## How it stays robust

- **Raw payloads kept**: every table has a `raw` JSONB column storing the
  exact record Whoop returned, so no data is lost even if Whoop adds fields.
- **Auto token refresh**: expired access tokens are refreshed transparently
  using the stored refresh token (requires the `offline` scope).
- **Pagination handled**: collection endpoints follow `next_token` until all
  records are fetched.
- **API version configurable**: `WHOOP_API_BASE` in `.env` lets you point at a
  different API version without code changes.

## Endpoints

| Method | Path             | Purpose                                  |
|--------|------------------|------------------------------------------|
| GET    | `/auth/login`    | Start OAuth — connect your Whoop account |
| GET    | `/auth/callback` | OAuth redirect target (handled for you)  |
| POST   | `/sync`          | Pull all data into Postgres              |
| GET    | `/profile`       | Stored profile                           |
| GET    | `/cycles`        | Stored physiological cycles              |
| GET    | `/recovery`      | Stored recovery scores                   |
| GET    | `/sleep`         | Stored sleep activities                  |
| GET    | `/workouts`      | Stored workouts                          |
| GET    | `/health`        | Liveness check                           |

## Troubleshooting

- **401 from `/sync`** → you haven't connected yet, or no refresh token. Visit
  `/auth/login` and make sure the `offline` scope is enabled on your app.
- **`redirect_uri` mismatch on Whoop** → the URI in `.env` must match the one
  registered on the developer portal exactly (scheme, host, port, path).
- **Can't connect to DB** → is `docker compose up -d` running? Does
  `DATABASE_URL` match?
