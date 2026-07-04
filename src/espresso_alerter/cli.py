"""CLI entry point: sweep once or on a schedule, optionally dry-run."""

from __future__ import annotations

import argparse
import logging
import sys

from .config import load_config
from .logging_setup import setup_logging
from .pipeline import format_digest, sweep
from .sources import build_sources
from .store import Store

log = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="espresso-alerter",
        description="Sweep UK secondhand listings for espresso-gear bargains.",
    )
    parser.add_argument("--config", default="config.yaml", help="path to config.yaml")
    parser.add_argument("--db", default="alerter.db", help="path to SQLite database")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="full sweep, print what WOULD be sent, send nothing",
    )
    parser.add_argument(
        "--once", action="store_true", help="run a single sweep and exit"
    )
    parser.add_argument("--verbose", action="store_true", help="debug logging")
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)
    config = load_config(args.config)
    sources = build_sources(config)
    if not sources:
        log.error("no sources available — nothing to sweep (check .env credentials)")
        return 1

    store = Store(args.db)
    try:
        if not args.once:
            # Scheduler lands in stage 5; until then run a single sweep.
            log.warning("scheduled mode not built yet (stage 5); running one sweep")

        candidates = sweep(config, sources, store)
        log.info("sweep complete candidates=%d", len(candidates))

        if candidates:
            digest = format_digest(candidates)
            if args.dry_run:
                print("\n--- DRY RUN: would send this digest ---\n")
                print(digest)
                print("\n--- end dry run (nothing sent) ---")
            else:
                # Telegram notifier lands in stage 2.
                log.warning("notifier not built yet (stage 2); printing digest instead")
                print(digest)
        else:
            log.info("no qualifying bargains this sweep")
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
