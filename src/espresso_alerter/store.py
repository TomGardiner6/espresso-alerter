"""SQLite persistence: seen listings (dedupe) and per-target price history."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from .models import Listing, PendingAlert

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

CREATE TABLE IF NOT EXISTS pending_alerts (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    target           TEXT NOT NULL,
    source           TEXT NOT NULL,
    listing_id       TEXT NOT NULL,
    title            TEXT NOT NULL,
    price            REAL NOT NULL,
    url              TEXT NOT NULL,
    location         TEXT,
    distance_miles   REAL,
    median           REAL,
    pct_under_median REAL,
    created_at       TEXT NOT NULL,
    sent_at          TEXT
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str | Path = "alerter.db") -> None:
        # check_same_thread=False: the scheduler (stage 5) runs sweeps in a
        # worker thread, not the thread that built the Store. Access is
        # serialised (one sweep at a time via max_instances=1) and further
        # guarded by _lock, so cross-thread use is safe.
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.RLock()
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def is_seen(self, source: str, listing_id: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM listings WHERE source = ? AND listing_id = ?",
                (source, listing_id),
            ).fetchone()
        return row is not None

    def record_listing(self, listing: Listing, target: str | None, matched: bool) -> None:
        with self._lock:
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
        with self._lock:
            self._conn.execute(
                "INSERT INTO price_history (target, source, listing_id, price, seen_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (target, listing.source, listing.listing_id, listing.price, _now()),
            )
            self._conn.commit()

    def recent_prices(self, target: str, window: int) -> list[float]:
        """Last `window` sighting prices for a target, newest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT price FROM price_history WHERE target = ?"
                " ORDER BY id DESC LIMIT ?",
                (target, window),
            ).fetchall()
        return [r[0] for r in rows]

    # -- pending alerts (rate-capped digest queue) ---------------------------

    def add_pending(self, alert: PendingAlert) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO pending_alerts
                   (target, source, listing_id, title, price, url, location,
                    distance_miles, median, pct_under_median, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    alert.target,
                    alert.source,
                    alert.listing_id,
                    alert.title,
                    alert.price,
                    alert.url,
                    alert.location,
                    alert.distance_miles,
                    alert.median,
                    alert.pct_under_median,
                    _now(),
                ),
            )
            self._conn.commit()

    def unsent_alerts(self) -> list[PendingAlert]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT id, target, source, listing_id, title, price, url,
                          location, distance_miles, median, pct_under_median
                   FROM pending_alerts WHERE sent_at IS NULL ORDER BY id"""
            ).fetchall()
        return [
            PendingAlert(
                id=r[0], target=r[1], source=r[2], listing_id=r[3], title=r[4],
                price=r[5], url=r[6], location=r[7], distance_miles=r[8],
                median=r[9], pct_under_median=r[10],
            )
            for r in rows
        ]

    def mark_sent(self, alert_ids: list[int]) -> None:
        now = _now()
        with self._lock:
            self._conn.executemany(
                "UPDATE pending_alerts SET sent_at = ? WHERE id = ?",
                [(now, alert_id) for alert_id in alert_ids],
            )
            self._conn.commit()

    # -- meta key/value (e.g. last_message_at) -------------------------------

    def get_meta(self, key: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM meta WHERE key = ?", (key,)
            ).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            self._conn.commit()
