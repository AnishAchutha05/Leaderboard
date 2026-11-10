"""Idempotently load approved workbook data into PostgreSQL.

Run migrations first: ``alembic upgrade head``. Scraping is deliberately
opt-in because it launches a browser for every participant.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import func, select, text

from .database import SessionLocal
from .models import Badge, Completion, EventStat, Lab, ScrapeLog, User
from ..course_parser import parse_course
from ..excel_manager import load_participants
from ..main import _import_course_rows, _import_users, _process_user

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
PARTICIPANTS_FILE = DATA_DIR / "clean_participants.xlsx"
COURSE_FILE_CANDIDATES = (
    DATA_DIR / "GCP_Labs_Courses_Professional.xlsx",
    DATA_DIR / "course.xlsx",
)
PARTICIPANT_SHEET = "Clean Participants"
COURSE_SHEET = "GCP Labs & Courses"
ADVISORY_LOCK_KEY = 731_804_161_2026


def _course_file() -> Path:
    for path in COURSE_FILE_CANDIDATES:
        if path.exists():
            return path
    raise FileNotFoundError(
        "Course workbook not found. Expected one of: "
        + ", ".join(str(path) for path in COURSE_FILE_CANDIDATES)
    )


def _require_migrations_current(connection) -> None:
    """Refuse to seed an un-migrated or partially migrated database."""
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    expected_revision = scripts.get_current_head()
    try:
        current_revision = MigrationContext.configure(connection).get_current_revision()
    except Exception as error:
        raise RuntimeError(
            "Could not read the Alembic revision. Run `alembic upgrade head` before seeding."
        ) from error
    if current_revision != expected_revision:
        raise RuntimeError(
            f"Database migration revision is {current_revision!r}; expected "
            f"{expected_revision!r}. Run `alembic upgrade head` before seeding."
        )


def _counts(session) -> dict[str, int]:
    return {
        model.__tablename__: int(session.scalar(select(func.count()).select_from(model)) or 0)
        for model in (User, Badge, Lab, Completion, ScrapeLog, EventStat)
    }


def seed_database(*, dry_run: bool = False, scrape: bool = False) -> dict[str, Any]:
    """Import workbooks safely; optionally scrape profiles after import."""
    if dry_run and scrape:
        raise ValueError("--dry-run and --scrape cannot be combined; scraping changes database state.")
    if not PARTICIPANTS_FILE.exists():
        raise FileNotFoundError(f"Participant workbook not found: {PARTICIPANTS_FILE}")

    participant_rows = load_participants(str(PARTICIPANTS_FILE), PARTICIPANT_SHEET)
    course_path = _course_file()
    course_rows = parse_course(str(course_path), sheet_name=COURSE_SHEET)

    session = SessionLocal()
    try:
        _require_migrations_current(session.connection())
        # Serialize concurrent seed invocations without changing the six-table schema.
        session.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": ADVISORY_LOCK_KEY})
        before = _counts(session)

        user_result = _import_users(session, participant_rows)
        course_result = _import_course_rows(session, course_rows)
        available_badges = session.scalar(select(func.count()).select_from(Badge)) or 0
        planned = {
            "participants_read": len(participant_rows),
            "participant_issues": load_participants.last_issues,
            "users": user_result,
            "courses_read": len(course_rows),
            "labs_imported": course_result["imported"],
            "unresolved_lab_mappings": course_result["unresolved"],
            "verified_badges_available": int(available_badges),
            "scraping_requested": scrape,
        }
        staged_counts = _counts(session)

        if dry_run:
            session.rollback()
            after = before
        else:
            session.commit()
            after = staged_counts
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    scrape_results = []
    if scrape:
        with SessionLocal() as db:
            user_ids = list(db.scalars(select(User.id).order_by(User.id)).all())
        scrape_results = [_process_user(user_id) for user_id in user_ids]
        # Newly verified badge records may resolve course associations. The
        # application's exact-name resolver is reused; no IDs are generated.
        session = SessionLocal()
        try:
            with session.begin():
                refreshed_courses = parse_course(str(course_path), sheet_name=COURSE_SHEET)
                refreshed_lab_result = _import_course_rows(session, refreshed_courses)
            planned["labs_imported_after_scrape"] = refreshed_lab_result["imported"]
            planned["unresolved_lab_mappings_after_scrape"] = refreshed_lab_result["unresolved"]
        finally:
            session.close()

    planned["dry_run"] = dry_run
    planned["counts_before"] = before
    planned["counts_after"] = after
    if scrape:
        planned["scrape_summary"] = {
            "users_attempted": len(scrape_results),
            "succeeded": sum(result["status"] == "Success" for result in scrape_results),
            "failed": sum(result["status"] == "Failed" for result in scrape_results),
            "badges_found": sum(result.get("badges_found", 0) for result in scrape_results),
        }
    return planned


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed PostgreSQL from approved Excel workbooks.")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--dry-run", action="store_true", help="Report changes and roll back all seed writes.")
    modes.add_argument("--scrape", action="store_true", help="Opt in to scraping all imported participants.")
    args = parser.parse_args()

    try:
        result = seed_database(dry_run=args.dry_run, scrape=args.scrape)
    except Exception as error:
        parser.exit(1, f"Seeding failed: {error}\n")
    import json
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
