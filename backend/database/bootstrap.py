"""Idempotent startup bootstrap for DB seed data.

Runs after migrations. Seeds course workbook + verified badges, and optionally
imports participants when a participant workbook is available.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text

if __package__:
    from .database import SessionLocal
    from .models import Badge, Completion, EventStat, Lab, ScrapeLog, User
    from .seed import (
        ADVISORY_LOCK_KEY,
        _counts,
        _course_file,
        _read_verified_badge_evidence,
        _require_migrations_current,
    )
    from ..course_parser import parse_course
    from ..excel_manager import load_participants
    from ..main import _import_course_rows, _import_users, _import_verified_badges
else:  # pragma: no cover
    from database import SessionLocal
    from models import Badge, Completion, EventStat, Lab, ScrapeLog, User
    from seed import (
        ADVISORY_LOCK_KEY,
        _counts,
        _course_file,
        _read_verified_badge_evidence,
        _require_migrations_current,
    )
    from course_parser import parse_course
    from excel_manager import load_participants
    from main import _import_course_rows, _import_users, _import_verified_badges

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
PARTICIPANT_SHEET = "Clean Participants"
COURSE_SHEET = "GCP Labs & Courses"
DEFAULT_PARTICIPANTS_FILE = DATA_DIR / "clean_participants.xlsx"


def _participants_file() -> Path:
    configured = os.getenv("PARTICIPANT_WORKBOOK_PATH")
    if configured:
        return Path(configured).expanduser()
    return DEFAULT_PARTICIPANTS_FILE


def bootstrap_database(*, dry_run: bool = False) -> dict[str, Any]:
    """Seed course/badge data and participants (if workbook is available)."""
    course_path = _course_file()
    course_rows = parse_course(str(course_path), sheet_name=COURSE_SHEET)
    verified_badges = _read_verified_badge_evidence()

    participants_file = _participants_file()
    participant_rows: list[dict] = []
    participant_issues: list[str] = []
    participants_source: str | None = None
    if participants_file.exists():
        participant_rows = load_participants(str(participants_file), sheet_name=PARTICIPANT_SHEET)
        participant_issues = list(getattr(load_participants, "last_issues", []) or [])
        participants_source = str(participants_file)

    session = SessionLocal()
    try:
        _require_migrations_current(session.connection())
        # Serialize concurrent startup/bootstrap invocations.
        session.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": ADVISORY_LOCK_KEY})
        before = _counts(session)

        badge_result = _import_verified_badges(session, verified_badges)
        user_result = None
        if participants_source is not None:
            user_result = _import_users(session, participant_rows)
        course_result = _import_course_rows(session, course_rows)
        available_badges = session.scalar(select(func.count()).select_from(Badge)) or 0

        result: dict[str, Any] = {
            "dry_run": dry_run,
            "course_workbook": str(course_path),
            "courses_read": len(course_rows),
            "verified_badges_read": len(verified_badges),
            "verified_badges": badge_result,
            "labs_imported": course_result["imported"],
            "unresolved_lab_mappings": course_result["unresolved"],
            "verified_badges_available": int(available_badges),
            "participants_source": participants_source,
            "participants_read": len(participant_rows) if participants_source else 0,
            "participant_issues": participant_issues,
            "users": user_result,
        }

        staged_counts = _counts(session)
        if dry_run:
            session.rollback()
            after = before
        else:
            session.commit()
            after = staged_counts

        result["counts_before"] = before
        result["counts_after"] = after
        return result
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap PostgreSQL seed data for startup.")
    parser.add_argument("--dry-run", action="store_true", help="Report changes and roll back writes.")
    args = parser.parse_args()
    try:
        result = bootstrap_database(dry_run=args.dry_run)
    except Exception as error:
        parser.exit(1, f"Bootstrap failed: {error}\n")
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
