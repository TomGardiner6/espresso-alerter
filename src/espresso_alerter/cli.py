"""CLI entry point: sweep once or on a schedule, optionally dry-run."""

from __future__ import annotations

import argparse
import logging
import sys

from .config import load_config
from .logging_setup import setup_logging
from .notify import build_notifier
from .pipeline import run_cycle
from .scheduler import run_scheduler
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
        "--once",
        action="store_true",
        help="run a single sweep and exit (default: scheduled loop)",
    )
    parser.add_argument("--verbose", action="store_true", help="debug logging")
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)
    config = load_config(args.config)
    sources = build_sources(config)
    if not sources:
        log.error("no sources available — nothing to sweep (check .env credentials)")
        return 1

    notifier = None if args.dry_run else build_notifier()

    store = Store(args.db)
    try:
        if args.once:
            run_cycle(config, sources, store, notifier, dry_run=args.dry_run)
        else:
            run_scheduler(config, sources, store, notifier, dry_run=args.dry_run)
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
