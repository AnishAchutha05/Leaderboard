import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/test_db")

from openpyxl import Workbook

from backend import main
from backend.scheduler import SchedulerConfig, ScrapeSchedulerService


class WorkbookConfigTests(unittest.TestCase):
    def _make_course_workbook(self, path: Path):
        wb = Workbook()
        ws = wb.active
        ws.title = "GCP Labs & Courses"
        ws.append(["Name", "Lab/Course", "Completion/Skill", "Total Credits Needed", "Link"])
        ws.append(["Sample Course", "Course", "Completion", 1, "https://example.com/course"])
        wb.save(path)

    def test_course_workbook_path_env_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            wb_path = Path(tmp) / "custom_course.xlsx"
            self._make_course_workbook(wb_path)
            with patch.dict(os.environ, {"COURSE_WORKBOOK_PATH": str(wb_path)}, clear=False):
                resolved = main._resolve_course_workbook_path()
                self.assertEqual(resolved, wb_path)
                self.assertEqual(main.validate_course_workbook_exists(), wb_path)
                rows = main._load_course_rows()
                self.assertEqual(len(rows), 1)

    def test_participant_workbook_path_env_override(self):
        with patch.dict(os.environ, {"PARTICIPANT_WORKBOOK_PATH": "/tmp/custom_participants.xlsx"}, clear=False):
            self.assertEqual(main._resolve_participant_workbook_path(), Path("/tmp/custom_participants.xlsx"))

    def test_missing_course_workbook_validation_is_clear(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.xlsx"
            with patch.dict(os.environ, {"COURSE_WORKBOOK_PATH": str(missing)}, clear=False):
                with self.assertRaisesRegex(FileNotFoundError, "Course workbook not found"):
                    main.validate_course_workbook_exists()


class CorsConfigTests(unittest.TestCase):
    def test_parse_cors_origins_from_env(self):
        with patch.dict(os.environ, {"CORS_ALLOW_ORIGINS": "https://app.example.com, https://admin.example.com"}, clear=False):
            self.assertEqual(main._parse_cors_origins(), ["https://app.example.com", "https://admin.example.com"])

    def test_parse_cors_origins_rejects_wildcard_with_credentials(self):
        with patch.dict(os.environ, {"CORS_ALLOW_ORIGINS": "*"}, clear=False):
            self.assertEqual(main._parse_cors_origins(), ["http://localhost:3000"])

    def test_parse_cors_origins_defaults_to_localhost(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CORS_ALLOW_ORIGINS", None)
            self.assertEqual(main._parse_cors_origins(), ["http://localhost:3000"])


class SchedulerShutdownTests(unittest.TestCase):
    def test_shutdown_waits_for_inflight_cycle(self):
        started = threading.Event()
        release = threading.Event()

        def slow_process(_user_id, **_kwargs):
            started.set()
            release.wait(timeout=3)
            return {"user_id": _user_id, "status": "Success", "badges_found": 0, "new_badges_found": 0}

        class FakeScalarResult:
            def __init__(self, values): self._values = list(values)
            def all(self): return list(self._values)
        class FakeSession:
            def __init__(self, user_ids): self.user_ids = user_ids
            def scalars(self, _q): return FakeScalarResult(self.user_ids)
            def __enter__(self): return self
            def __exit__(self, *a): return False
        def session_factory(): return FakeSession([1])

        service = ScrapeSchedulerService(
            SchedulerConfig(interval_minutes=60, concurrency=1, run_initial_cycle=False, shutdown_grace_seconds=2),
            process_user=slow_process,
            session_factory=session_factory,
            engine_obj=MagicMock(),
            scheduler=MagicMock(),
            load_course_rows=lambda: [],
            validate_course_workbook=lambda: None,
        )
        t = threading.Thread(target=lambda: service.run_cycle(trigger="test"))
        t.start()
        self.assertTrue(started.wait(timeout=2))
        # shutdown should wait for in-flight cycle (release after short delay)
        def release_later():
            time.sleep(0.2)
            release.set()
        threading.Thread(target=release_later).start()
        begin = time.time()
        service.shutdown(wait=True)
        elapsed = time.time() - begin
        t.join(timeout=2)
        self.assertGreaterEqual(elapsed, 0.15)
        self.assertFalse(t.is_alive())


if __name__ == "__main__":
    unittest.main()
