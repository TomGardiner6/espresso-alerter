"""Telegram notifier via the Bot API (token + chat ID from .env)."""

from __future__ import annotations

import logging
import os

import httpx

from ..httputil import request_with_retries

log = logging.getLogger(__name__)

# Telegram caps messages at 4096 chars; split on item boundaries below this.
_MAX_MESSAGE_CHARS = 4000


def _split_message(text: str, limit: int = _MAX_MESSAGE_CHARS) -> list[str]:
    """Split an over-long digest into chunks, breaking between lines."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        if current and len(current) + len(line) + 1 > limit:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks


class TelegramNotifier:
    name = "telegram"

    def __init__(self, bot_token: str, chat_id: str) -> None:
        self._url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self._chat_id = chat_id
        self._http = httpx.Client()

    @classmethod
    def from_env(cls) -> "TelegramNotifier | None":
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID")
        if not token or not chat_id:
            return None
        return cls(token, chat_id)

    def send(self, alert: str) -> None:
        for chunk in _split_message(alert):
            resp = request_with_retries(
                self._http,
                "POST",
                self._url,
                data={
                    "chat_id": self._chat_id,
                    "text": chunk,
                    "disable_web_page_preview": "true",
                },
            )
            resp.raise_for_status()
        log.info("notifier=telegram sent chars=%d", len(alert))
