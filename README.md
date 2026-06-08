# Whoop Data API

Pull your personal [Whoop](https://www.whoop.com/) data (recovery, sleep,
workouts, cycles, profile) via the official Whoop developer API using OAuth 2.0,
and store it in PostgreSQL.

Built with **FastAPI** + **SQLAlchemy** + **PostgreSQL**. Runs locally **or**
deploys to **Vercel** with a daily **Vercel Cron** job that auto-syncs new data.

There are two ways to run this — pick one:

- **A. Local** (Docker Postgres, manual sync) — Steps 1–7 below.
- **B. Vercel** (hosted Postgres, automatic daily sync) — see
  [Deploy to Vercel](#deploy-to-vercel-daily-auto-sync). Do the local run first
  if you want to test, but it isn't required.

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

## Deploy to Vercel (daily auto-sync)

On Vercel the app runs as a **serverless function** (`api/index.py`), and a
**Vercel Cron** job calls `GET /cron/sync` once a day to pull new data into your
hosted database automatically. There's no always-on server and no Docker.

### 1. Provision a hosted PostgreSQL

Pick any managed Postgres and copy its connection string:

- **Vercel Postgres** (Storage tab → Create → Postgres) — easiest, auto-adds env vars.
- **Neon** (<https://neon.tech>) or **Supabase** (<https://supabase.com>) free tiers.

Convert the connection string to a SQLAlchemy URL by prefixing the driver and
preferring the **pooled** host for serverless:

```
postgresql+psycopg://USER:PASSWORD@POOLED_HOST/DB?sslmode=require
```

### 2. Push this repo to GitHub and import it into Vercel

In Vercel: **Add New → Project → import your GitHub repo**. Vercel auto-detects
the Python function in `api/` and `requirements.txt`. No build command needed.

### 3. Set Environment Variables (Vercel → Project → Settings → Environment Variables)

| Variable | Value |
|----------|-------|
| `WHOOP_CLIENT_ID` / `WHOOP_CLIENT_SECRET` | from the Whoop developer portal |
| `WHOOP_REDIRECT_URI` | `https://<your-project>.vercel.app/auth/callback` |
| `WHOOP_SCOPES` | `offline read:recovery read:cycles read:sleep read:workout read:profile read:body_measurement` |
| `DATABASE_URL` | the SQLAlchemy URL from step 1 |
| `SESSION_SECRET` | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `CRON_SECRET` | another random secret — protects `/cron/sync` |
| `SYNC_LOOKBACK_DAYS` | `7` (optional) |

> **Important:** add `https://<your-project>.vercel.app/auth/callback` to your
> app's Redirect URIs on the Whoop developer portal — it must match
> `WHOOP_REDIRECT_URI` exactly.

### 4. Deploy, then create the tables (once)

After the first deploy, create the schema by calling the protected admin
endpoint once:

```bash
curl -X POST https://<your-project>.vercel.app/admin/init-db \
  -H "Authorization: Bearer $CRON_SECRET"
```

### 5. Connect your Whoop account (once)

Open in your browser:

```
https://<your-project>.vercel.app/auth/login
```

Authorize — tokens are stored in your hosted DB. Because you granted `offline`,
the daily cron renews the access token on its own from here on.

### 6. The daily sync runs automatically

`vercel.json` registers the cron:

```json
{ "crons": [ { "path": "/cron/sync", "schedule": "0 6 * * *" } ] }
```

Every day at **06:00 UTC**, Vercel calls `GET /cron/sync` (with the
`CRON_SECRET` bearer token it injects automatically). The endpoint re-fetches
the last `SYNC_LOOKBACK_DAYS` days and upserts them — new records are inserted,
and scores Whoop finalized late are updated, with no duplicates.

Change the cadence by editing the `schedule` (standard cron, UTC). You can also
trigger it manually:

```bash
curl https://<your-project>.vercel.app/cron/sync -H "Authorization: Bearer $CRON_SECRET"
```

> **Plan note:** Vercel's Hobby plan allows cron jobs to run **once per day**;
> the Pro plan allows finer schedules. Function `maxDuration` is set to 60s in
> `vercel.json` — the incremental window keeps each run well under that.

### Test the serverless build locally (optional)

You can run the exact Vercel serverless setup on your machine before deploying:

```bash
npm i -g vercel       # one-time
vercel dev            # serves api/index.py + applies vercel.json routing
```

`vercel dev` reads env vars from `vercel env pull .env` (or your linked project).
Note that `vercel dev` does **not** fire the cron on a schedule — trigger it
manually with the `curl …/cron/sync` command above to test it.

---

## Project layout

```
app/
├── main.py          FastAPI app: /sync, /cron/sync, read + admin endpoints
├── auth.py          OAuth login + callback routes
├── whoop_client.py  OAuth flow, token refresh, paginated API fetching
├── sync.py          Map Whoop records -> DB rows, idempotent upserts + run log
├── models.py        SQLAlchemy tables (data, oauth_tokens, sync_runs audit log)
├── database.py      Engine (NullPool for serverless) / session / Base
└── config.py        Settings loaded from env / .env
api/
└── index.py         Vercel serverless entrypoint (exports the ASGI app)
vercel.json          Vercel routing + daily cron schedule + maxDuration
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
| POST   | `/sync`          | Pull all data into Postgres (manual/full) |
| GET    | `/cron/sync`     | Daily incremental sync (Vercel Cron; needs `CRON_SECRET`) |
| POST   | `/admin/init-db` | Create tables once after deploy (needs `CRON_SECRET`) |
| GET    | `/sync/history`  | Audit log of recent sync runs (status, counts, errors) |
| GET    | `/profile`       | Stored profile                           |
| GET    | `/cycles`        | Stored physiological cycles              |
| GET    | `/recovery`      | Stored recovery scores                   |
| GET    | `/sleep`         | Stored sleep activities                  |
| GET    | `/workouts`      | Stored workouts                          |
| GET    | `/health`        | Liveness check                           |

Check whether the daily sync is running:

```bash
curl https://<your-project>.vercel.app/sync/history | python -m json.tool
```

## Troubleshooting

- **401 from `/sync`** → you haven't connected yet, or no refresh token. Visit
  `/auth/login` and make sure the `offline` scope is enabled on your app.
- **`redirect_uri` mismatch on Whoop** → the URI in `.env` must match the one
  registered on the developer portal exactly (scheme, host, port, path).
- **Can't connect to DB** → is `docker compose up -d` running? Does
  `DATABASE_URL` match?
- **`TypeError: cannot use a string pattern on a bytes-like object` on startup**
  → the DB connection negotiated `SQL_ASCII` (happens with a `C`/POSIX locale
  runtime). This is already handled: the engine pins `client_encoding=utf-8`
  (see `app/database.py`). Make sure your hosted database is created with
  **UTF8** encoding (Neon/Supabase/Vercel Postgres all are by default).
