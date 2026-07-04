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
