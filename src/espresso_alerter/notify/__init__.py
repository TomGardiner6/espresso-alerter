"""Notifiers. Each implements the `Notifier` protocol in base.py."""

from __future__ import annotations

import logging

from .base import Notifier
from .telegram import TelegramNotifier

log = logging.getLogger(__name__)


def build_notifier() -> Notifier | None:
    notifier = TelegramNotifier.from_env()
    if notifier is None:
        log.warning(
            "notifier=telegram unavailable reason=missing-credentials "
            "(set TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID in .env)"
        )
    return notifier
