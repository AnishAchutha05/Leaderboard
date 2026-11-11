"""Background scraping scheduler service.

Runs as part of a dedicated worker process. Reuses the existing participant
processing pipeline and avoids attaching jobs to FastAPI startup.
"""

from __future__ import annotations

import logging
import os
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, EVENT_JOB_MISSED
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select, text

if __package__:
    from .database.database import SessionLocal, engine
    from .database.models import User
    from .main import _load_course_rows, _process_user, validate_course_workbook_exists
    from .scraper import (
        DEFAULT_LAUNCH_TIMEOUT_MS,
        DEFAULT_NAVIGATION_TIMEOUT_MS,
        DEFAULT_OPERATION_TIMEOUT_MS,
    )
else:  # pragma: no cover - supports direct script-style imports
    from database.database import SessionLocal, engine
    from database.models import User
    from main import _load_course_rows, _process_user, validate_course_workbook_exists
    from scraper import (
        DEFAULT_LAUNCH_TIMEOUT_MS,
        DEFAULT_NAVIGATION_TIMEOUT_MS,
        DEFAULT_OPERATION_TIMEOUT_MS,
    )

logger = logging.getLogger(__name__)

CYCLE_LOCK_KEY = 731_804_161_2027


@dataclass(frozen=True)
class SchedulerConfig:
    interval_minutes: int = 60
    concurrency: int = 3
    # Default false to avoid unnecessary full scrapes on every worker restart in production.
    # Set SCRAPE_RUN_INITIAL=true to run once immediately on startup.
    run_initial_cycle: bool = False
    launch_timeout_ms: int = DEFAULT_LAUNCH_TIMEOUT_MS
    navigation_timeout_ms: int = DEFAULT_NAVIGATION_TIMEOUT_MS
    operation_timeout_ms: int = DEFAULT_OPERATION_TIMEOUT_MS
    shutdown_grace_seconds: int = 180

    @classmethod
    def from_env(cls) -> "SchedulerConfig":
        return cls(
            interval_minutes=max(1, int(os.getenv("SCRAPE_INTERVAL_MINUTES", "60"))),
            concurrency=max(1, int(os.getenv("SCRAPE_CONCURRENCY", "3"))),
            run_initial_cycle=os.getenv("SCRAPE_RUN_INITIAL", "false").strip().lower()
            in {"1", "true", "yes", "on"},
            launch_timeout_ms=max(1_000, int(os.getenv("SCRAPE_LAUNCH_TIMEOUT_MS", str(DEFAULT_LAUNCH_TIMEOUT_MS)))),
            navigation_timeout_ms=max(1_000, int(os.getenv("SCRAPE_NAVIGATION_TIMEOUT_MS", str(DEFAULT_NAVIGATION_TIMEOUT_MS)))),
            operation_timeout_ms=max(1_000, int(os.getenv("SCRAPE_OPERATION_TIMEOUT_MS", str(DEFAULT_OPERATION_TIMEOUT_MS)))),
            shutdown_grace_seconds=max(10, int(os.getenv("SCRAPE_SHUTDOWN_GRACE_SECONDS", "180"))),
        )


class ScrapeSchedulerService:
    def __init__(
        self,
        config: SchedulerConfig | None = None,
        *,
        process_user: Callable[..., dict] = _process_user,
        session_factory=SessionLocal,
        engine_obj=engine,
        scheduler: BackgroundScheduler | None = None,
        load_course_rows: Callable[..., list[dict]] = _load_course_rows,
        validate_course_workbook: Callable[..., object] = validate_course_workbook_exists,
    ) -> None:
        self.config = config or SchedulerConfig.from_env()
        self.process_user = process_user
        self.session_factory = session_factory
        self.engine = engine_obj
        self.scheduler = scheduler or BackgroundScheduler(timezone="UTC")
        self.load_course_rows = load_course_rows
        self.validate_course_workbook = validate_course_workbook
        self._cycle_running = threading.Lock()
        self._shutdown = threading.Event()
        self._installed_signal_handlers = False
        self._initial_thread: threading.Thread | None = None

    def _acquire_worker_lock(self, connection) -> bool:
        """Prevent duplicate scheduler worker instances across processes."""
        return bool(connection.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": CYCLE_LOCK_KEY}).scalar())

    def _release_worker_lock(self, connection) -> None:
        try:
            connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": CYCLE_LOCK_KEY})
        except Exception:
            logger.exception("Failed to release scheduler advisory lock")

    def _process_one(self, user_id: int, course_rows: list[dict]) -> dict:
        return self.process_user(
            user_id,
            launch_timeout_ms=self.config.launch_timeout_ms,
            navigation_timeout_ms=self.config.navigation_timeout_ms,
            operation_timeout_ms=self.config.operation_timeout_ms,
            course_rows=course_rows,
        )

    def run_cycle(self, *, trigger: str = "scheduled") -> dict:
        if self._shutdown.is_set():
            logger.warning("Scrape cycle skipped (%s): worker is shutting down", trigger)
            return {"status": "skipped", "reason": "shutdown", "trigger": trigger}

        if not self._cycle_running.acquire(blocking=False):
            logger.warning("Scrape cycle skipped (%s): previous cycle still running", trigger)
            return {"status": "skipped", "reason": "cycle_running", "trigger": trigger}

        started_at = datetime.now(timezone.utc)
        start_perf = time.perf_counter()
        logger.info(
            "Scrape cycle started trigger=%s at=%s interval_minutes=%s concurrency=%s",
            trigger,
            started_at.isoformat(),
            self.config.interval_minutes,
            self.config.concurrency,
        )
        summary = {
            "status": "completed",
            "trigger": trigger,
            "started_at": started_at.isoformat(),
            "processed": 0,
            "successful": 0,
            "failed": 0,
            "badges_extracted": 0,
            "new_completions": 0,
            "duration_seconds": 0.0,
        }
        try:
            # Validate required runtime asset and load/cache course workbook once per cycle.
            self.validate_course_workbook()
            course_rows = self.load_course_rows()
            logger.info("Course workbook loaded once for cycle rows=%d", len(course_rows))

            with self.session_factory() as db:
                user_ids = list(db.scalars(select(User.id).order_by(User.id)).all())
            logger.info("Scrape cycle participants loaded count=%d", len(user_ids))

            results: list[dict] = []
            if user_ids and not self._shutdown.is_set():
                with ThreadPoolExecutor(max_workers=self.config.concurrency) as executor:
                    futures = {}
                    for user_id in user_ids:
                        if self._shutdown.is_set():
                            logger.warning("Shutdown requested; skipping submission of remaining participants")
                            break
                        futures[executor.submit(self._process_one, user_id, course_rows)] = user_id
                    for future in as_completed(futures):
                        user_id = futures[future]
                        try:
                            result = future.result()
                        except Exception as error:
                            logger.exception("Unhandled participant failure in cycle for user_id=%s", user_id)
                            result = {"user_id": user_id, "status": "Failed", "error": str(error)}
                        results.append(result)
                        logger.info(
                            "Participant cycle result user_id=%s status=%s badges_found=%s new_badges_found=%s",
                            result.get("user_id"),
                            result.get("status"),
                            result.get("badges_found", 0),
                            result.get("new_badges_found", 0),
                        )

            if self._shutdown.is_set():
                summary["status"] = "interrupted"
            summary.update(
                {
                    "processed": len(results),
                    "successful": sum(1 for r in results if r.get("status") == "Success"),
                    "failed": sum(1 for r in results if r.get("status") != "Success"),
                    "badges_extracted": sum(int(r.get("badges_found", 0) or 0) for r in results),
                    "new_completions": sum(int(r.get("new_badges_found", 0) or 0) for r in results),
                }
            )
            return summary
        except Exception as error:
            summary["status"] = "failed"
            summary["error"] = str(error)
            logger.exception("Scrape cycle failed trigger=%s", trigger)
            return summary
        finally:
            ended_at = datetime.now(timezone.utc)
            summary["ended_at"] = ended_at.isoformat()
            summary["duration_seconds"] = round(time.perf_counter() - start_perf, 3)
            logger.info(
                "Scrape cycle finished trigger=%s status=%s processed=%s successful=%s failed=%s "
                "badges_extracted=%s new_completions=%s duration_seconds=%s ended_at=%s",
                trigger,
                summary.get("status"),
                summary.get("processed"),
                summary.get("successful"),
                summary.get("failed"),
                summary.get("badges_extracted"),
                summary.get("new_completions"),
                summary.get("duration_seconds"),
                summary["ended_at"],
            )
            self._cycle_running.release()

    def _on_job_event(self, event) -> None:
        if event.exception:
            logger.exception("Scheduled scrape job raised an exception", exc_info=event.exception)
        elif getattr(event, "code", None) == EVENT_JOB_MISSED:
            logger.warning("Scheduled scrape job missed")

    def start(self) -> None:
        if self.scheduler.running:
            return
        # Validate required workbook early for clearer startup failures.
        self.validate_course_workbook()
        self.scheduler.add_listener(self._on_job_event, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR | EVENT_JOB_MISSED)
        self.scheduler.add_job(
            self.run_cycle,
            trigger=IntervalTrigger(minutes=self.config.interval_minutes),
            id="hourly_scrape_cycle",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            kwargs={"trigger": "interval"},
        )
        self.scheduler.start()
        logger.info(
            "Scheduler started interval_minutes=%s concurrency=%s run_initial_cycle=%s",
            self.config.interval_minutes,
            self.config.concurrency,
            self.config.run_initial_cycle,
        )
        if self.config.run_initial_cycle:
            # Run initial cycle in background so worker startup/shutdown remain responsive.
            self._initial_thread = threading.Thread(
                target=self.run_cycle,
                kwargs={"trigger": "startup"},
                name="initial-scrape-cycle",
                daemon=False,
            )
            self._initial_thread.start()

    def shutdown(self, wait: bool = True) -> None:
        self._shutdown.set()
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
        if wait:
            # Allow an in-flight cycle to finish gracefully (per-participant work is isolated).
            acquired = self._cycle_running.acquire(timeout=self.config.shutdown_grace_seconds)
            if acquired:
                self._cycle_running.release()
            else:
                logger.warning(
                    "Timed out waiting %ss for in-flight scrape cycle during shutdown",
                    self.config.shutdown_grace_seconds,
                )
            if self._initial_thread and self._initial_thread.is_alive():
                self._initial_thread.join(timeout=max(1, self.config.shutdown_grace_seconds))
        logger.info("Scheduler shut down")

    def install_signal_handlers(self) -> None:
        if self._installed_signal_handlers:
            return

        def _handler(signum, _frame):
            logger.info("Received signal %s, shutting down scheduler worker", signum)
            self._shutdown.set()
            self.shutdown(wait=False)

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, _handler)
            except Exception:
                logger.debug("Could not install handler for signal %s", sig)
        self._installed_signal_handlers = True

    def wait(self) -> None:
        try:
            while not self._shutdown.is_set():
                self._shutdown.wait(timeout=1)
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received, shutting down scheduler worker")
            self._shutdown.set()
            self.shutdown(wait=True)

    def run_forever(self) -> int:
        self.install_signal_handlers()
        with self.engine.connect() as connection:
            if not self._acquire_worker_lock(connection):
                logger.error("Another scheduler worker instance is already running; exiting.")
                return 1
            try:
                self.start()
                self.wait()
                return 0
            finally:
                self.shutdown(wait=True)
                self._release_worker_lock(connection)
