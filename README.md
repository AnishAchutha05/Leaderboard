# Google Skills Tracker

FastAPI backend and Next.js leaderboard backed by PostgreSQL. Database schema changes are managed only through Alembic migrations; the seed command imports source workbooks without dropping or truncating data.

## Local PostgreSQL setup

Requirements: Docker Compose and Python 3.12 (or the project-supported interpreter).

Start PostgreSQL 16 and wait for its health check:

```sh
docker compose up -d postgres
docker compose ps
```

The Compose service exposes PostgreSQL on `localhost:5433`, persists its data in the `postgres_data` named volume, and checks readiness with `pg_isready`. Its credentials are for local development only; never reuse them in production.

Set the application connection URL in your shell (or an untracked local environment file):

```sh
export DATABASE_URL='postgresql+psycopg://tracker_user:tracker_password@localhost:5433/google_skills_tracker'
```

`DATABASE_URL` is required. The application and Alembic accept PostgreSQL URLs using `postgres://`, `postgresql://`, or `postgresql+psycopg://`; the first two are normalized to the psycopg 3 driver. Do not commit credentials.

## Fresh database initialization

From the project root, run migrations before the idempotent seed:

```sh
alembic upgrade head
python -m backend.database.seed
```

With the local virtual environment, use its executable paths if they are not on `PATH`, for example `.venv/bin/alembic` and `.venv/bin/python`.

The seed command reads:

- `data/clean_participants.xlsx`, worksheet `Clean Participants` only. It never imports `Needs Review`.
- `data/GCP_Labs_Courses_Professional.xlsx`, worksheet `GCP Labs & Courses`, when present; otherwise it uses the compatible `data/course.xlsx` workbook.

Participant deduplication uses the public profile URL. Names/emails and resolvable lab fields are updated from the workbooks. A badge-to-lab association is created only when the course name has one exact match to a badge with an actual, verified Google Skills badge ID already persisted by the application. The workbooks do not themselves contain badge IDs, so unresolved rows are reported and not fabricated. Default seeding does not start browser sessions.

### Seed modes

```sh
python -m backend.database.seed                 # Import workbooks; no scraping
python -m backend.database.seed --dry-run       # Report intended work and roll back
python -m backend.database.seed --scrape        # Explicitly scrape all imported profiles
```

`--dry-run` cannot be combined with `--scrape`; it performs no persistent writes. `--scrape` is opt-in and may take a long time because it visits each participant profile. Successful scrapes persist badges only when an actual badge ID is found in a Google Skills badge link. Failed scrapes are logged and do not delete stored completions.

The seeder verifies the database is at the current Alembic revision before writing. It serializes concurrent seeding, uses SQLAlchemy transactions, and never drops, truncates, or deletes production data. Safe reseeding is simply:

```sh
alembic upgrade head
python -m backend.database.seed
```

## Render PostgreSQL initialization

Create a Render PostgreSQL instance and link its connection URL to the backend service as the secret environment variable `DATABASE_URL`. Prefer Render's internal connection URL. The URL scheme is normalized by the application and Alembic; no database URL or credential should be committed to this repository.

For a Render web service, configure a pre-deploy command:

```sh
alembic upgrade head && python -m backend.database.seed
```

This applies migrations first, then performs safe, repeatable, non-scraping initialization on each deploy. Ensure the source workbooks listed above are included in the deployed repository/image. If the service plan does not offer a pre-deploy command, run the same command once in a Render shell or one-off job after setting `DATABASE_URL` and before serving traffic. Docker's local named volume and Render's database are separate; initialize each environment independently.

## Tests

The PostgreSQL integration tests use the configured `DATABASE_URL`. Point it at a disposable, isolated test database before running them; the tests clear their fixture tables and are not intended for a shared or production database.

```sh
python -m unittest -v backend.tests.test_excel_postgres backend.tests.test_seed
```

The test suite covers real workbook parsing, reordered/missing columns, blank and duplicate rows, seed idempotency, dry-run rollback, completion timestamp preservation, failed-transaction rollback, and Render URL normalization.
