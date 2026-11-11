"""Dedicated entry point for the background scrape scheduler worker."""

from __future__ import annotations

import logging
import os
import sys

if __package__:
    from .scheduler import ScrapeSchedulerService, SchedulerConfig
else:  # pragma: no cover
    from scheduler import ScrapeSchedulerService, SchedulerConfig


def configure_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def main() -> int:
    configure_logging()
    service = ScrapeSchedulerService(SchedulerConfig.from_env())
    return service.run_forever()


if __name__ == "__main__":
    sys.exit(main())
