"""Interface every notifier implements."""

from __future__ import annotations

from typing import Protocol


class Notifier(Protocol):
    """A channel alerts go out on (Telegram today; anything later).

    `send` delivers one already-formatted digest message. It may raise on
    total failure — the caller leaves the alerts pending so they go out
    with the next successful send instead of being lost.
    """

    name: str

    def send(self, alert: str) -> None: ...
