"""Stage 5: the scheduled sweep loop (APScheduler).

Runs one sweep immediately, then every `sweep_interval_minutes`. Overlapping
runs are prevented (max_instances=1) and a missed tick is coalesced rather
than piling up. A crash in one cycle is logged and the loop keeps going, so
a transient source/network failure never stops the alerter.

Cron alternative (if you'd rather not keep a process running): schedule
`uv run espresso-alerter --once` every 45 min, e.g.

    */45 * * * *  cd /path/to/espresso-alerter && /path/to/uv run espresso-alerter --once

The persistent pending queue and per-source rotation cursor live in SQLite,
so the cron form behaves identically to the long-running loop.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.blocking import BlockingScheduler

from .config import Config
from .notify.base import Notifier
from .pipeline import run_cycle
from .sources.base import Source
from .store import Store

log = logging.getLogger(__name__)


def run_scheduler(
    config: Config,
    sources: list[Source],
    store: Store,
    notifier: Notifier | None,
    dry_run: bool = False,
) -> None:
    scheduler = BlockingScheduler(timezone="UTC")

    def job() -> None:
        try:
            run_cycle(config, sources, store, notifier, dry_run=dry_run)
        except Exception:
            log.exception("sweep cycle crashed; will retry next interval")

    scheduler.add_job(
        job,
        trigger="interval",
        minutes=config.sweep_interval_minutes,
        # Timezone-aware "now" so the immediate first run isn't offset by the
        # local/UTC gap (a naive datetime would be read as UTC and land in the
        # future). Sweep immediately, then every interval.
        next_run_time=datetime.now(timezone.utc),
        id="sweep",
        max_instances=1,
        coalesce=True,
    )
    log.info(
        "scheduler started interval=%dmin (Ctrl-C to stop)",
        config.sweep_interval_minutes,
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("scheduler stopped")
