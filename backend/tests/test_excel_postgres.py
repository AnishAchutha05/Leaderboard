from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from openpyxl import Workbook
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from backend.course_parser import parse_course
from backend.database.database import SessionLocal
from backend.database.models import Badge, Completion, Lab, ScrapeLog, User
from backend.excel_manager import load_participants
from backend.main import _import_users, _process_user
from backend.participant_manager import validate_profile_url
from backend.scraper import badge_from_link

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"


class ExcelParserTests(unittest.TestCase):
    def test_real_workbooks(self):
        participants = load_participants(str(DATA_DIR / "clean_participants.xlsx"), "Clean Participants")
        courses = parse_course(str(DATA_DIR / "course.xlsx"), "GCP Labs & Courses")
        self.assertEqual(len(participants), 498)
        self.assertEqual(len(courses), 6)
        self.assertEqual(courses[0]["item_type"], "Course")
        self.assertEqual(courses[1]["item_type"], "Challenge Lab")
        self.assertEqual(courses[0]["credits"], 5)

    def test_reordered_participant_headers_blank_duplicate_and_nullable_email(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["Public Profile URL", "Email", "Full Name"])
        sheet.append(["https://www.skills.google/public_profiles/abc123", None, " First User "])
        sheet.append([None, None, None])
        sheet.append(["https://www.skills.google/public_profiles/abc123/", "other@example.com", "Duplicate"])
        with tempfile.NamedTemporaryFile(suffix=".xlsx") as temp:
            workbook.save(temp.name)
            rows = load_participants(temp.name)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "First User")
        self.assertIsNone(rows[0]["email"])
        self.assertEqual(len(load_participants.last_issues), 1)

    def test_missing_participant_header_is_clear(self):
        workbook = Workbook()
        workbook.active.append(["Name", "Email"])
        with tempfile.NamedTemporaryFile(suffix=".xlsx") as temp:
            workbook.save(temp.name)
            with self.assertRaisesRegex(ValueError, "Name and Public Profile URL"):
                load_participants(temp.name)

    def test_reordered_course_headers_and_missing_header(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["Link", "Name", "Completion/Skill", "Total Credits Needed", "Lab/Course"])
        sheet.append(["https://example.test/course", "Exact Badge", "Completion", 4, "Course"])
        sheet.append([None, None, None, None, None])
        with tempfile.NamedTemporaryFile(suffix=".xlsx") as temp:
            workbook.save(temp.name)
            rows = parse_course(temp.name)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["lab_name"], "Exact Badge")
        self.assertEqual(rows[0]["item_type"], "Course")
        self.assertEqual(rows[0]["credits"], 4)

        broken = Workbook()
        broken.active.append(["Name", "Lab/Course", "Link"])
        with tempfile.NamedTemporaryFile(suffix=".xlsx") as temp:
            broken.save(temp.name)
            with self.assertRaisesRegex(ValueError, "missing required headers"):
                parse_course(temp.name)

    def test_badge_scraper_requires_real_id_and_extracts_title_date(self):
        record = badge_from_link(
            "https://www.skills.google/public_profiles/profile/badges/abc-123",
            "View Badge",
            "Google Cloud Fundamentals\nEarned Nov 10, 2026",
        )
        self.assertEqual(record["badge_id"], "abc-123")
        self.assertEqual(record["badge_name"], "Google Cloud Fundamentals")
        self.assertEqual(record["date"], "Nov 10, 2026")
        self.assertIsNone(badge_from_link("https://www.skills.google/catalog", "Course", "Course"))


class PostgresIntegrationTests(unittest.TestCase):
    def setUp(self):
        with SessionLocal.begin() as db:
            db.execute(delete(Completion))
            db.execute(delete(ScrapeLog))
            db.execute(delete(Lab))
            db.execute(delete(Badge))
            db.execute(delete(User))

    def tearDown(self):
        with SessionLocal.begin() as db:
            db.execute(delete(Completion))
            db.execute(delete(ScrapeLog))
            db.execute(delete(Lab))
            db.execute(delete(Badge))
            db.execute(delete(User))

    def test_user_upsert_deduplicates_by_profile_and_accepts_null_email(self):
        rows = [
            {"name": "A", "email": None, "profile_url": "https://www.skills.google/public_profiles/abc123"},
            {"name": "duplicate", "email": "dup@example.test", "profile_url": "https://skills.google/public_profiles/abc123/"},
        ]
        with SessionLocal.begin() as db:
            result = _import_users(db, rows)
        with SessionLocal() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(User)), 1)
            self.assertIsNone(db.scalar(select(User)).email)
        self.assertEqual((result["inserted"], result["skipped"]), (1, 1))

    def test_duplicate_badge_and_completion_are_idempotent(self):
        course_rows = parse_course(str(DATA_DIR / "course.xlsx"), "GCP Labs & Courses")
        badge_record = {"badge_id": "test-badge-actual-id", "badge_name": course_rows[0]["lab_name"],
                        "date": "Nov 10, 2026", "status": "Done"}
        with SessionLocal.begin() as db:
            user = User(name="Scrape User", email=None,
                        public_profile_url="https://www.skills.google/public_profiles/test-user")
            db.add(user)
            db.flush()
            user_id = user.id
        with patch("backend.main.scrape_badges", return_value=[badge_record]):
            first = _process_user(user_id)
            second = _process_user(user_id)
        with SessionLocal() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Badge)), 1)
            self.assertEqual(db.scalar(select(func.count()).select_from(Lab)), 1)
            self.assertEqual(db.scalar(select(func.count()).select_from(Completion)), 1)
        self.assertEqual(first["new_badges_found"], 1)
        self.assertEqual(second["new_badges_found"], 0)

    def test_completion_unique_constraint_and_transaction_rollback(self):
        now = datetime.now(timezone.utc)
        with SessionLocal.begin() as db:
            user = User(name="Rollback User", email=None,
                        public_profile_url="https://www.skills.google/public_profiles/rollback")
            badge = Badge(id="rollback-badge", name="Rollback Badge", category="Unclassified")
            db.add_all([user, badge])
            db.flush()
            lab = Lab(name="Rollback Lab", item_type="Course", total_credits=1,
                      url="https://example.test/rollback", badge_id=badge.id)
            db.add(lab)
            db.flush()
            completion = Completion(user_id=user.id, badge_id=badge.id, lab_id=lab.id,
                                    is_completed=True, first_detected_at=now,
                                    last_verified_at=now)
            db.add(completion)
            user_id = user.id
            badge_id = badge.id
            lab_id = lab.id
        with self.assertRaises(IntegrityError):
            with SessionLocal.begin() as db:
                db.add(Completion(user_id=user_id, badge_id=badge_id, lab_id=lab_id,
                                  is_completed=True, first_detected_at=now,
                                  last_verified_at=now))
        with SessionLocal() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Completion)), 1)
        with self.assertRaises(RuntimeError):
            with SessionLocal.begin() as db:
                db.add(User(name="Must Roll Back", email=None,
                            public_profile_url="https://www.skills.google/public_profiles/rollback-test"))
                raise RuntimeError("forced rollback")
        with SessionLocal() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(User)), 1)

    def test_invalid_url_and_failed_scrape_preserve_completion(self):
        self.assertFalse(validate_profile_url("https://example.test/not-a-profile"))
        now = datetime.now(timezone.utc)
        with SessionLocal.begin() as db:
            user = User(name="Existing Completion", email=None,
                        public_profile_url="https://www.skills.google/public_profiles/existing")
            badge = Badge(id="existing-real-id", name="Existing Badge", category="Unclassified")
            db.add_all([user, badge])
            db.flush()
            lab = Lab(name="Existing Lab", item_type="Course", total_credits=1,
                      url="https://example.test/existing", badge_id=badge.id)
            db.add(lab)
            db.flush()
            db.add(Completion(user_id=user.id, badge_id=badge.id, lab_id=lab.id,
                              is_completed=True, earned_at=now,
                              first_detected_at=now, last_verified_at=now))
            user_id = user.id
        with patch("backend.main.scrape_badges", side_effect=RuntimeError("simulated scrape failure")):
            result = _process_user(user_id)
        with SessionLocal() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Completion)), 1)
            log = db.scalar(select(ScrapeLog).where(ScrapeLog.user_id == user_id))
            self.assertEqual(log.status, "Failed")
            self.assertIn("simulated scrape failure", log.error_message)
        self.assertEqual(result["status"], "Failed")


if __name__ == "__main__":
    unittest.main()
