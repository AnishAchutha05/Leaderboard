# Deployment and Production Configuration

This document describes the production-oriented setup implemented for the Google Skills Tracker and the manual steps still required for Render.

## Architecture (intended)

1. **Managed PostgreSQL** (Render PostgreSQL) – persistent application database.
2. **FastAPI Web Service** (`Dockerfile.api`) – API only; no scheduler attached.
3. **Background Worker** (`Dockerfile.worker`) – runs `python -m backend.scheduler_worker` with Playwright/Chromium; **single instance only**.
4. **Next.js Web Service** (`frontend/website/Dockerfile`) – Node runtime (`next start`), not static export.

## Environment variables

See `.env.example` for the full list. Key variables:

### Backend API / Worker
- `DATABASE_URL` (**required**) – PostgreSQL URL (`postgres://` / `postgresql://` / `postgresql+psycopg://` accepted; normalized internally).
- `CORS_ALLOW_ORIGINS` – comma-separated allowed frontend origins (no wildcard when credentials enabled). Default: `http://localhost:3000`.
- `COURSE_WORKBOOK_PATH` – path to course/lab workbook (required for scraping/matching/import flows). Default resolves to `data/course.xlsx` or `data/GCP_Labs_Courses_Professional.xlsx` locally.
- `PARTICIPANT_WORKBOOK_PATH` – path to participant workbook for seed/import flows (may contain PII; never commit). Default: `data/clean_participants.xlsx`.
- `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT`, `DB_POOL_RECYCLE` – SQLAlchemy pool tuning (size for API + worker concurrency within DB connection limits).

### Scheduler worker
- `SCRAPE_INTERVAL_MINUTES` (default 60)
- `SCRAPE_CONCURRENCY` (default 3)
- `SCRAPE_RUN_INITIAL` (default `false` to avoid unnecessary full scrape on every restart; set `true` only if desired)
- `SCRAPE_LAUNCH_TIMEOUT_MS`, `SCRAPE_NAVIGATION_TIMEOUT_MS`, `SCRAPE_OPERATION_TIMEOUT_MS`
- `SCRAPE_SHUTDOWN_GRACE_SECONDS` (default 180)
- `LOG_LEVEL`

### Frontend
- `NEXT_PUBLIC_API_URL` – backend base URL used by browser fetches. **Must be set at build time** for Next.js (baked into the client bundle). Do not hardcode Render URLs in source.

## Workbooks and data safety
- **Course workbook** is required at runtime by API/worker/seed (`COURSE_WORKBOOK_PATH`). It contains lab configuration (no participant PII) and must be available in deployed environments (baked into image, mounted, or provided at configured path).
- **Participant workbook** (`PARTICIPANT_WORKBOOK_PATH`) may contain PII and **must never be committed or baked into images**. `.gitignore` and `.dockerignore` exclude participant/PII files.
- Scheduler loads/caches course rows once per scraping cycle (not per participant). Missing required workbooks produce clear validation errors.

## Docker

- `Dockerfile.api`: FastAPI service image. Runs `alembic upgrade head` before starting Uvicorn (`${PORT}` supported).
- `Dockerfile.worker`: Playwright-enabled worker image based on `mcr.microsoft.com/playwright/python:v1.64.0-noble`, installs project deps and `playwright install chromium` (no extra browsers), runs `python -m backend.scheduler_worker`.
- `frontend/website/Dockerfile`: multi-stage Next.js Node image; accepts `ARG NEXT_PUBLIC_API_URL` at build.

## Render Blueprint (`render.yaml`)

`render.yaml` defines managed Postgres, API web service, single-instance worker, and frontend web service. **Manual updates required before apply:**
- Replace `https://REPLACE_WITH_FRONTEND_URL` in API `CORS_ALLOW_ORIGINS` with the deployed frontend URL.
- Replace `https://REPLACE_WITH_API_URL` in frontend `NEXT_PUBLIC_API_URL` (build-time env/arg in Render service settings) with the deployed API URL.
- Choose appropriate plans/regions and confirm database connection limits vs `DB_POOL_SIZE`/`DB_MAX_OVERFLOW`/worker concurrency.
- Ensure the course workbook is present at `COURSE_WORKBOOK_PATH` in both API and worker containers (current Dockerfiles copy `data/` excluding ignored PII files; if your deployment must not rely on repo `data/course.xlsx`, mount/provision the file and set the path accordingly).

### Migrations
- `Dockerfile.api` runs `alembic upgrade head` on container start before the API serves traffic. If you prefer a separate Render pre-deploy/release step, move migrations there and remove them from the web start command (ensure the step runs with the same `DATABASE_URL` and code revision).

### Render settings to verify manually
- **Worker:** exactly 1 instance/replica (advisory lock + in-process guards prevent duplicates, but scaling workers is not supported by this design).
- **Health checks:** API path `/api/health`.
- **Networking:** worker must have outbound internet access to `skills.google`; frontend must reach API over HTTPS; CORS must include the exact frontend origin.
- **Secrets:** store `DATABASE_URL` and any sensitive values as Render secrets/env vars (never hardcode).
- **Filesystem:** container filesystems are ephemeral except attached disks; runtime uploads (course/participant) will not persist across deploys unless stored in managed DB or external/persistent storage.

## Local run commands (development)

### 1. PostgreSQL (Docker Compose)
```bash
docker compose up -d postgres
# stop: docker compose stop postgres
# restart: docker compose restart postgres
# down: docker compose down
```

### 2. Backend (FastAPI)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL='postgresql+psycopg://tracker_user:tracker_password@localhost:5433/google_skills_tracker'
export CORS_ALLOW_ORIGINS='http://localhost:3000'
export COURSE_WORKBOOK_PATH='./data/course.xlsx'  # optional, default discovery applies
alembic upgrade head
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

### 3. Background scheduler worker (separate process)
```bash
source .venv/bin/activate
export DATABASE_URL='postgresql+psycopg://tracker_user:tracker_password@localhost:5433/google_skills_tracker'
export COURSE_WORKBOOK_PATH='./data/course.xlsx'
# optional: SCRAPE_RUN_INITIAL=true for an immediate cycle
python -m backend.scheduler_worker
```

### 4. Frontend (Next.js)
```bash
cd frontend/website
npm install
export NEXT_PUBLIC_API_URL='http://localhost:8000'  # build-time for production builds
npm run dev    # dev
# production: npm run build && npm run start -- -p 3000
```

## Notes
- Do not run the scheduler inside the API service. Do not run bulk scrapes against all participants during routine testing.
- Existing completion records are preserved on scrape failures (per-participant transactions + failure logging).
