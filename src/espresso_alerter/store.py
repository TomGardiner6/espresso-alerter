"""SQLite persistence: seen listings (dedupe) and per-target price history."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import Listing

_SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    source        TEXT NOT NULL,
    listing_id    TEXT NOT NULL,
    target        TEXT,
    title         TEXT,
    price         REAL,
    currency      TEXT,
    url           TEXT,
    location      TEXT,
    distance_miles REAL,
    matched       INTEGER NOT NULL DEFAULT 0,
    first_seen    TEXT NOT NULL,
    PRIMARY KEY (source, listing_id)
);

CREATE TABLE IF NOT EXISTS price_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    target     TEXT NOT NULL,
    source     TEXT NOT NULL,
    listing_id TEXT NOT NULL,
    price      REAL NOT NULL,
    seen_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_target ON price_history (target, id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str | Path = "alerter.db") -> None:
        self._conn = sqlite3.connect(path)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def is_seen(self, source: str, listing_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM listings WHERE source = ? AND listing_id = ?",
            (source, listing_id),
        ).fetchone()
        return row is not None

    def record_listing(self, listing: Listing, target: str | None, matched: bool) -> None:
        self._conn.execute(
            """INSERT OR IGNORE INTO listings
               (source, listing_id, target, title, price, currency, url,
                location, distance_miles, matched, first_seen)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                listing.source,
                listing.listing_id,
                target,
                listing.title,
                listing.price,
                listing.currency,
                listing.url,
                listing.location,
                listing.distance_miles,
                int(matched),
                _now(),
            ),
        )
        self._conn.commit()

    def add_sighting(self, target: str, listing: Listing) -> None:
        """Record a genuine (matched, sanely-priced) sighting for median stats."""
        self._conn.execute(
            "INSERT INTO price_history (target, source, listing_id, price, seen_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (target, listing.source, listing.listing_id, listing.price, _now()),
        )
        self._conn.commit()

    def recent_prices(self, target: str, window: int) -> list[float]:
        """Last `window` sighting prices for a target, newest first."""
        rows = self._conn.execute(
            "SELECT price FROM price_history WHERE target = ?"
            " ORDER BY id DESC LIMIT ?",
            (target, window),
        ).fetchall()
        return [r[0] for r in rows]
