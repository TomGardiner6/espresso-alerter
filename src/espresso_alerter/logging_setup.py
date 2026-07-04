"""Structured logging: key=value lines to logs/alerter.log plus the console."""

from __future__ import annotations

import logging
from pathlib import Path

_FORMAT = "%(asctime)s level=%(levelname)s module=%(name)s %(message)s"


def setup_logging(log_dir: str | Path = "logs", verbose: bool = False) -> None:
    Path(log_dir).mkdir(parents=True, exist_ok=True)

    file_handler = logging.FileHandler(Path(log_dir) / "alerter.log")
    file_handler.setFormatter(logging.Formatter(_FORMAT))

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(_FORMAT))

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(console)

    # httpx logs every request at INFO; keep the log signal-heavy.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
