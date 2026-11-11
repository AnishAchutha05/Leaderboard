import os
import threading
import time
import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/test_db")

from backend.scheduler import SchedulerConfig, ScrapeSchedulerService


class FakeScalarResult:
    def __init__(self, values):
        self._values = list(values)

    def all(self):
        return list(self._values)


class FakeSession:
    def __init__(self, user_ids):
        self.user_ids = user_ids

    def scalars(self, _query):
        return FakeScalarResult(self.user_ids)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def make_session_factory(user_ids):
    def factory():
        return FakeSession(user_ids)
    return factory


class FakeConnection:
    def __init__(self, lock_acquired=True):
        self.lock_acquired = lock_acquired
        self.executed = []

    def execute(self, stmt, params=None):
        self.executed.append((str(stmt), params))
        sql = str(stmt)
        if "pg_try_advisory_lock" in sql:
            return MagicMock(scalar=lambda: self.lock_acquired)
        return MagicMock(scalar=lambda: True)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeEngine:
    def __init__(self, lock_acquired=True):
        self.connection = FakeConnection(lock_acquired=lock_acquired)

    def connect(self):
        return self.connection


class SchedulerWorkerTests(unittest.TestCase):
    def test_start_triggers_initial_cycle_and_schedules_hourly_job(self):
        scheduler = MagicMock()
        scheduler.running = False
        service = ScrapeSchedulerService(
            SchedulerConfig(interval_minutes=60, concurrency=3, run_initial_cycle=True),
            process_user=MagicMock(return_value={"status": "Success"}),
            session_factory=make_session_factory([]),
            engine_obj=FakeEngine(),
            scheduler=scheduler,
        )
        service.run_cycle = MagicMock(return_value={"status": "completed"})

        service.start()

        scheduler.add_job.assert_called_once()
        _, kwargs = scheduler.add_job.call_args
        self.assertEqual(kwargs["id"], "hourly_scrape_cycle")
        self.assertEqual(kwargs["max_instances"], 1)
        self.assertTrue(kwargs["coalesce"])
        self.assertEqual(kwargs["trigger"].interval.total_seconds(), 3600)
        scheduler.start.assert_called_once()

        deadline = time.time() + 2
        while time.time() < deadline and service.run_cycle.call_count == 0:
            time.sleep(0.01)
        self.assertGreaterEqual(service.run_cycle.call_count, 1)
        self.assertEqual(service.run_cycle.call_args.kwargs.get("trigger"), "startup")

    def test_hourly_scheduling_interval_is_configurable(self):
        scheduler = MagicMock()
        scheduler.running = False
        service = ScrapeSchedulerService(
            SchedulerConfig(interval_minutes=15, concurrency=2, run_initial_cycle=False),
            process_user=MagicMock(),
            session_factory=make_session_factory([]),
            engine_obj=FakeEngine(),
            scheduler=scheduler,
        )
        service.start()
        _, kwargs = scheduler.add_job.call_args
        self.assertEqual(kwargs["trigger"].interval.total_seconds(), 900)

    def test_overlapping_cycle_is_skipped(self):
        started = threading.Event()
        release = threading.Event()

        def slow_process(_user_id, **_kwargs):
            started.set()
            release.wait(timeout=2)
            return {"user_id": _user_id, "status": "Success", "badges_found": 0, "new_badges_found": 0}

        service = ScrapeSchedulerService(
            SchedulerConfig(interval_minutes=60, concurrency=1, run_initial_cycle=False),
            process_user=slow_process,
            session_factory=make_session_factory([1]),
            engine_obj=FakeEngine(),
            scheduler=MagicMock(),
        )

        t = threading.Thread(target=lambda: service.run_cycle(trigger="first"))
        t.start()
        self.assertTrue(started.wait(timeout=2))
        skipped = service.run_cycle(trigger="second")
        self.assertEqual(skipped["status"], "skipped")
        self.assertEqual(skipped["reason"], "cycle_running")
        release.set()
        t.join(timeout=2)

    def test_multiple_participants_processed_with_bounded_concurrency_and_failure_isolation(self):
        active = 0
        max_active = 0
        lock = threading.Lock()

        def process(user_id, **kwargs):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            try:
                time.sleep(0.05)
                if user_id == 2:
                    return {"user_id": 2, "status": "Failed", "error": "boom", "badges_found": 0, "new_badges_found": 0}
                return {"user_id": user_id, "status": "Success", "badges_found": 1, "new_badges_found": 1}
            finally:
                with lock:
                    active -= 1

        service = ScrapeSchedulerService(
            SchedulerConfig(interval_minutes=60, concurrency=2, run_initial_cycle=False),
            process_user=process,
            session_factory=make_session_factory([1, 2, 3, 4]),
            engine_obj=FakeEngine(),
            scheduler=MagicMock(),
        )
        summary = service.run_cycle(trigger="test")

        self.assertEqual(summary["status"], "completed")
        self.assertEqual(summary["processed"], 4)
        self.assertEqual(summary["successful"], 3)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["badges_extracted"], 3)
        self.assertEqual(summary["new_completions"], 3)
        self.assertLessEqual(max_active, 2)
        self.assertGreaterEqual(max_active, 2)

    def test_duplicate_worker_instance_prevented_by_advisory_lock(self):
        scheduler = MagicMock()
        service = ScrapeSchedulerService(
            SchedulerConfig(interval_minutes=60, concurrency=3, run_initial_cycle=False),
            process_user=MagicMock(),
            session_factory=make_session_factory([]),
            engine_obj=FakeEngine(lock_acquired=False),
            scheduler=scheduler,
        )
        code = service.run_forever()
        self.assertEqual(code, 1)
        scheduler.start.assert_not_called()

    def test_failed_participant_exception_is_isolated(self):
        def process(user_id, **kwargs):
            if user_id == 1:
                raise RuntimeError("unexpected")
            return {"user_id": user_id, "status": "Success", "badges_found": 2, "new_badges_found": 0}

        service = ScrapeSchedulerService(
            SchedulerConfig(interval_minutes=60, concurrency=2, run_initial_cycle=False),
            process_user=process,
            session_factory=make_session_factory([1, 2]),
            engine_obj=FakeEngine(),
            scheduler=MagicMock(),
        )
        summary = service.run_cycle(trigger="test")
        self.assertEqual(summary["processed"], 2)
        self.assertEqual(summary["successful"], 1)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["badges_extracted"], 2)


if __name__ == "__main__":
    unittest.main()
