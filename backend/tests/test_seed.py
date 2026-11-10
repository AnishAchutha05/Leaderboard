from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from sqlalchemy import delete, func, select

from backend.database import seed
from backend.database.database import SessionLocal, normalize_database_url
from backend.database.models import Badge, Completion, EventStat, Lab, ScrapeLog, User
from backend.course_parser import parse_course

MODELS = (Completion, ScrapeLog, Lab, Badge, User, EventStat)


class SeedTests(unittest.TestCase):
    """Run these tests only against an isolated PostgreSQL test database."""

    def setUp(self):
        with SessionLocal.begin() as db:
            for model in MODELS:
                db.execute(delete(model))

    def tearDown(self):
        with SessionLocal.begin() as db:
            for model in MODELS:
                db.execute(delete(model))

    def counts(self):
        with SessionLocal() as db:
            return seed._counts(db)

    def test_seed_twice_is_idempotent_and_non_destructive_to_completions(self):
        with patch.object(seed, "_process_user") as scraper:
            first = seed.seed_database()
            scraper.assert_not_called()
        self.assertEqual(first["users"]["inserted"], 498)
        self.assertEqual(first["courses_read"], 6)
        self.assertEqual(len(first["unresolved_lab_mappings"]), 6)
        self.assertEqual(first["counts_after"]["users"], 498)
        self.assertEqual(first["counts_after"]["badges"], 0)
        self.assertEqual(first["counts_after"]["labs"], 0)

        course = parse_course(str(seed._course_file()), seed.COURSE_SHEET)[0]
        with SessionLocal.begin() as db:
            user = db.scalar(select(User).where(User.public_profile_url.like("%ef3d5428-be0c-4961-8bf5-a73d4678d405%")))
            self.assertIsNotNone(user)
            user_id = user.id
            badge = Badge(id="fixture-real-id-from-test", name="Google Cloud Computing Foundations: Cloud Computing Fundamentals", category="Completion")
            db.add(badge)
            db.flush()
            lab = Lab(name=badge.name, item_type="Course", total_credits=5,
                      url=course["lab_url"], badge_id=badge.id)
            db.add(lab)
            db.flush()
            earned_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
            first_detected_at = datetime(2026, 1, 3, tzinfo=timezone.utc)
            last_verified_at = datetime(2026, 1, 4, tzinfo=timezone.utc)
            db.add(Completion(user_id=user_id, badge_id=badge.id, lab_id=lab.id,
                              is_completed=True, earned_at=earned_at,
                              first_detected_at=first_detected_at,
                              last_verified_at=last_verified_at))

        with patch.object(seed, "_process_user") as scraper:
            second = seed.seed_database()
            scraper.assert_not_called()
        self.assertEqual(second["users"]["inserted"], 0)
        self.assertEqual(second["users"]["updated"], 498)
        self.assertEqual(len(second["unresolved_lab_mappings"]), 5)
        self.assertEqual(second["counts_after"]["users"], 498)
        self.assertEqual(second["counts_after"]["badges"], 1)
        self.assertEqual(second["counts_after"]["labs"], 1)
        self.assertEqual(second["counts_after"]["completions"], 1)
        with SessionLocal() as db:
            completion = db.scalar(select(Completion))
            self.assertEqual(completion.earned_at, earned_at)
            self.assertEqual(completion.first_detected_at, first_detected_at)
            self.assertEqual(completion.last_verified_at, last_verified_at)

    def test_dry_run_rolls_back_every_change(self):
        before = self.counts()
        result = seed.seed_database(dry_run=True)
        self.assertEqual(result["users"]["inserted"], 498)
        self.assertEqual(result["dry_run"], True)
        self.assertEqual(result["counts_after"], before)
        self.assertEqual(self.counts(), before)

    def test_import_exception_rolls_back_users_and_labs(self):
        before = self.counts()
        with patch.object(seed, "_import_course_rows", side_effect=RuntimeError("fixture failure")):
            with self.assertRaisesRegex(RuntimeError, "fixture failure"):
                seed.seed_database()
        self.assertEqual(self.counts(), before)

    def test_dry_run_and_scrape_are_incompatible(self):
        with self.assertRaisesRegex(ValueError, "cannot be combined"):
            seed.seed_database(dry_run=True, scrape=True)


class DatabaseUrlTests(unittest.TestCase):
    def test_render_postgres_schemes_use_psycopg(self):
        self.assertEqual(
            normalize_database_url("postgres://user:pass@host/db"),
            "postgresql+psycopg://user:pass@host/db",
        )
        self.assertEqual(
            normalize_database_url("postgresql://user:pass@host/db"),
            "postgresql+psycopg://user:pass@host/db",
        )


if __name__ == "__main__":
    unittest.main()
