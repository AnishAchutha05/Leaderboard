import logging
import os
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

# Allow importing backend modules without requiring a live database connection.
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/test_db")

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.database.models import Badge, Base, Completion, Lab, ScrapeLog, User
from backend.scraper import PlaywrightError, PlaywrightTimeoutError, scrape_badges


def make_playwright(candidates=None, *, goto_error=None, evaluate_error=None, new_page_error=None):
    playwright_cm = MagicMock()
    playwright = MagicMock()
    browser = MagicMock()
    page = MagicMock()

    playwright_cm.__enter__.return_value = playwright
    playwright_cm.__exit__.return_value = False
    playwright.chromium.launch.return_value = browser

    if new_page_error:
        browser.new_page.side_effect = new_page_error
    else:
        browser.new_page.return_value = page

    if goto_error:
        page.goto.side_effect = goto_error
    if evaluate_error:
        page.evaluate.side_effect = evaluate_error
    else:
        page.evaluate.return_value = candidates if candidates is not None else []

    return playwright_cm, playwright, browser, page


class ScraperPipelineTests(unittest.TestCase):
    def _scrape(self, candidates=None, **kwargs):
        playwright_cm, *_ = make_playwright(candidates=candidates, **kwargs)
        with patch("backend.scraper.sync_playwright", return_value=playwright_cm):
            with self.assertLogs("backend.scraper", level="INFO") as logs:
                result = scrape_badges("https://www.skills.google/public_profiles/test")
        return result, "\n".join(logs.output)

    def test_empty_profile_returns_empty_list(self):
        result, logs = self._scrape([])
        self.assertEqual(result, [])
        self.assertIn("Navigation completed", logs)
        self.assertIn("DOM extraction completed", logs)
        self.assertIn("Scrape completed", logs)

    def test_one_badge_extracted(self):
        result, _ = self._scrape([
            {
                "href": "https://www.skills.google/public_profiles/p/badges/abc123",
                "linkText": "Cloud Badge",
                "cardText": "Cloud Badge\nEarned Nov 10, 2026",
            }
        ])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["badge_id"], "abc123")
        self.assertEqual(result[0]["badge_name"], "Cloud Badge")
        self.assertEqual(result[0]["date"], "Nov 10, 2026")
        self.assertEqual(result[0]["url"], "https://www.skills.google/public_profiles/p/badges/abc123")

    def test_multiple_badges_extracted(self):
        result, _ = self._scrape([
            {"href": "https://www.skills.google/public_profiles/p/badges/one", "linkText": "Badge One", "cardText": "Badge One\nEarned Jan 1, 2026"},
            {"href": "https://www.skills.google/public_profiles/p/badges/two", "linkText": "Badge Two", "cardText": "Badge Two\nEarned Jan 2, 2026"},
        ])
        self.assertEqual({b["badge_id"] for b in result}, {"one", "two"})

    def test_irrelevant_navigation_links_ignored(self):
        result, _ = self._scrape([
            {"href": "https://www.skills.google/catalog", "linkText": "Catalog", "cardText": "Catalog"},
            {"href": "https://support.google.com/", "linkText": "Support", "cardText": "Support"},
            {"href": "https://www.skills.google/public_profiles/p/badges/real1", "linkText": "Real Badge", "cardText": "Real Badge\nEarned Feb 2, 2026"},
        ])
        self.assertEqual([b["badge_id"] for b in result], ["real1"])

    def test_duplicate_badge_ids_deduplicated(self):
        result, _ = self._scrape([
            {"href": "https://www.skills.google/public_profiles/p/badges/dup1", "linkText": "Badge A", "cardText": "Badge A\nEarned Mar 1, 2026"},
            {"href": "https://www.skills.google/public_profiles/p/badges/dup1", "linkText": "Badge A duplicate", "cardText": "Badge A\nEarned Mar 2, 2026"},
        ])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["badge_id"], "dup1")

    def test_profile_badge_card_dom_structure_regression(self):
        # Mirrors the actual DOM structure observed on
        # https://www.skills.google/public_profiles/83075bd1-9ac5-4ffe-8615-7781d8cc76b1
        # (div.profile-badge with a.badge-image, ql-title-medium, ql-body-medium).
        candidates = [
            {
                "href": "https://www.skills.google/public_profiles/83075bd1-9ac5-4ffe-8615-7781d8cc76b1/badges/29567872",
                "linkText": "Google Cloud Computing Foundations: Cloud Computing Fundamentals",
                "cardText": "Google Cloud Computing Foundations: Cloud Computing Fundamentals\nEarned Nov 11, 2026 EST",
            },
            {
                "href": "https://www.skills.google/public_profiles/83075bd1-9ac5-4ffe-8615-7781d8cc76b1/badges/20654633",
                "linkText": "Implement Cloud Collaboration and Productivity Workflows",
                "cardText": "Implement Cloud Collaboration and Productivity Workflows\nEarned Dec 4, 2025 EST",
            },
            {
                "href": "https://www.skills.google/public_profiles/83075bd1-9ac5-4ffe-8615-7781d8cc76b1/badges/20571233",
                "linkText": "The Basics of Google Cloud Compute",
                "cardText": "The Basics of Google Cloud Compute\nEarned Nov 30, 2025 EST",
            },
            # Fallback duplicate emitted by anchor pass for same badge card.
            {
                "href": "https://www.skills.google/public_profiles/83075bd1-9ac5-4ffe-8615-7781d8cc76b1/badges/29567872",
                "linkText": "",
                "cardText": "Google Cloud Computing Foundations: Cloud Computing Fundamentals\nEarned Nov 11, 2026 EST",
            },
        ]
        result, _ = self._scrape(candidates)
        by_id = {badge["badge_id"]: badge for badge in result}
        self.assertEqual(set(by_id), {"29567872", "20654633", "20571233"})
        self.assertEqual(
            by_id["29567872"]["badge_name"],
            "Google Cloud Computing Foundations: Cloud Computing Fundamentals",
        )
        self.assertEqual(by_id["29567872"]["date"], "Nov 11, 2026")
        self.assertEqual(by_id["20571233"]["badge_name"], "The Basics of Google Cloud Compute")
        self.assertEqual(by_id["20571233"]["date"], "Nov 30, 2025")

    def test_navigation_timeout_raises_clear_failure(self):
        playwright_cm, *_ = make_playwright(goto_error=PlaywrightTimeoutError("nav timeout"))
        with patch("backend.scraper.sync_playwright", return_value=playwright_cm):
            with self.assertRaisesRegex(TimeoutError, "Timed out while loading profile page"):
                scrape_badges("https://www.skills.google/public_profiles/test")

    def test_browser_closure_error_raises_clear_failure(self):
        playwright_cm, *_ = make_playwright(evaluate_error=PlaywrightError("Target closed"))
        with patch("backend.scraper.sync_playwright", return_value=playwright_cm):
            with self.assertRaisesRegex(RuntimeError, "Browser error during badge extraction"):
                scrape_badges("https://www.skills.google/public_profiles/test")

    def test_successful_completion_persistence(self):
        engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, future=True)

        @contextmanager
        def begin():
            session = Session()
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        @contextmanager
        def readonly():
            session = Session()
            try:
                yield session
            finally:
                session.close()

        # Seed minimal data
        with begin() as db:
            user = User(id=1, name="Test User", email=None, public_profile_url="https://www.skills.google/public_profiles/test-user")
            badge = Badge(id="badge-1", name="Course Badge", category="Completion")
            db.add_all([user, badge])
            db.flush()
            lab = Lab(id=1, name="Course Badge", item_type="Course", total_credits=1, url="https://example.test/course", badge_id="badge-1")
            db.add(lab)

        scraped = [{"badge_id": "badge-1", "badge_name": "Course Badge", "date": "Nov 10, 2026", "status": "Done", "url": "https://www.skills.google/badges/badge-1"}]
        course_rows = [{"source_row": 2, "lab_name": "Course Badge", "item_type": "Course", "credits": 1, "lab_url": "https://example.test/course", "badge_name": "Course Badge", "category": "Completion"}]

        import backend.main as main

        with patch.object(main, "SessionLocal", side_effect=lambda: readonly()), \
             patch.object(main, "validate_profile_url", return_value=True), \
             patch.object(main, "scrape_badges", return_value=scraped), \
             patch.object(main, "_load_course_rows", return_value=course_rows):
            # first call for participant lookup uses readonly session; persistence uses begin()
            def session_factory():
                return readonly()
            # We need SessionLocal() for lookup and SessionLocal.begin() for persistence/failure log.
            factory = MagicMock()
            factory.return_value = readonly()
            factory.begin.side_effect = lambda: begin()
            with patch.object(main, "SessionLocal", factory):
                with self.assertLogs("backend.main", level="INFO") as logs:
                    result = main._process_user(1)

        self.assertEqual(result["status"], "Success")
        self.assertEqual(result["badges_found"], 1)
        with readonly() as db:
            self.assertEqual(db.scalar(select(Completion).where(Completion.user_id == 1)).badge_id, "badge-1")
            self.assertEqual(db.scalar(select(ScrapeLog).where(ScrapeLog.user_id == 1)).status, "Success")
        joined_logs = "\n".join(logs.output)
        self.assertIn("Participant lookup started", joined_logs)
        self.assertIn("Scrape started", joined_logs)
        self.assertIn("Scrape completed", joined_logs)
        self.assertIn("Course loading started", joined_logs)
        self.assertIn("Database persistence started", joined_logs)
        self.assertIn("Database persistence committed", joined_logs)

    def test_failed_scrape_does_not_persist_false_success(self):
        engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, future=True)

        @contextmanager
        def begin():
            session = Session()
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        @contextmanager
        def readonly():
            session = Session()
            try:
                yield session
            finally:
                session.close()

        with begin() as db:
            user = User(id=2, name="Fail User", email=None, public_profile_url="https://www.skills.google/public_profiles/fail-user")
            badge = Badge(id="existing-badge", name="Existing Badge", category="Unclassified")
            lab = Lab(id=10, name="Existing Lab", item_type="Course", total_credits=1, url="https://example.test/existing", badge_id="existing-badge")
            db.add_all([user, badge, lab])
            db.flush()
            db.add(Completion(user_id=2, badge_id="existing-badge", lab_id=10, is_completed=True,
                              first_detected_at=datetime.now(timezone.utc), last_verified_at=datetime.now(timezone.utc)))

        import backend.main as main
        factory = MagicMock()
        factory.return_value = readonly()
        factory.begin.side_effect = lambda: begin()
        with patch.object(main, "SessionLocal", factory), \
             patch.object(main, "validate_profile_url", return_value=True), \
             patch.object(main, "scrape_badges", side_effect=RuntimeError("boom")):
            result = main._process_user(2)

        self.assertEqual(result["status"], "Failed")
        with readonly() as db:
            self.assertEqual(db.scalar(select(Completion).where(Completion.user_id == 2)).badge_id, "existing-badge")
            log = db.scalar(select(ScrapeLog).where(ScrapeLog.user_id == 2))
            self.assertEqual(log.status, "Failed")
            self.assertIn("boom", log.error_message)


if __name__ == "__main__":
    unittest.main()
