"""Normalised listing model shared by all sources."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Listing:
    """One listing, normalised from whichever source produced it.

    `listing_id` must be stable per source so (source, listing_id) can be
    used as the dedupe key forever.
    """

    source: str
    listing_id: str
    title: str
    price: float  # GBP
    currency: str
    url: str
    location: str | None = None
    distance_miles: float | None = None


@dataclass(frozen=True)
class PendingAlert:
    """A gate-passing listing queued for the next allowed digest message.

    Persisted in SQLite so alerts held back by the rate cap survive
    restarts and are never lost.
    """

    target: str
    source: str
    listing_id: str
    title: str
    price: float
    url: str
    location: str | None
    distance_miles: float | None
    median: float | None  # None => insufficient history at qualification time
    pct_under_median: float | None
    id: int | None = None  # database row id once persisted
