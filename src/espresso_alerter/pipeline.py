"""One sweep: fetch from every source, dedupe, match, gate, report."""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass

from .config import Config, Target
from .models import Listing
from .sources.base import Source
from .store import Store

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Candidate:
    """A listing that passed the bargain gate this sweep."""

    listing: Listing
    target: Target
    median: float | None  # None => insufficient history
    pct_under_median: float | None


def _passes_bargain_gate(
    listing: Listing, target: Target, store: Store, config: Config
) -> Candidate | None:
    """Apply the strict gate. Returns a Candidate or None (with a log line)."""
    prices = store.recent_prices(target.name, config.history_window)
    median = statistics.median(prices) if len(prices) >= config.history_window else None

    # Scam sanity check: absurdly cheap vs running median, or no location.
    # Suppressed listings do NOT feed the price history.
    if median is not None and listing.price < median * config.scam_median_fraction:
        log.info(
            "suppressed=scam-price target=%r price=%.2f median=%.2f url=%s",
            target.name, listing.price, median, listing.url,
        )
        return None
    if not listing.location:
        log.info(
            "suppressed=no-location target=%r price=%.2f url=%s",
            target.name, listing.price, listing.url,
        )
        return None

    # A genuine, sanely-priced sighting: feed the rolling price history
    # (the median above deliberately excludes this listing itself).
    store.add_sighting(target.name, listing)

    if listing.price > target.bargain_price:
        log.info(
            "rejected=above-bargain-price target=%r price=%.2f bargain=%.2f",
            target.name, listing.price, target.bargain_price,
        )
        return None

    if median is not None and listing.price >= median:
        log.info(
            "rejected=not-below-median target=%r price=%.2f median=%.2f",
            target.name, listing.price, median,
        )
        return None

    pct_under = (1 - listing.price / median) * 100 if median else None
    return Candidate(listing=listing, target=target, median=median, pct_under_median=pct_under)


def sweep(config: Config, sources: list[Source], store: Store) -> list[Candidate]:
    """Run one full sweep across all sources. Never raises on a source failure."""
    from .matching import match_target

    candidates: list[Candidate] = []
    for source in sources:
        for target in config.targets:
            try:
                listings = source.fetch(target, config)
            except Exception:
                log.exception(
                    "source=%s target=%r fetch failed; continuing", source.name, target.name
                )
                continue

            for listing in listings:
                if store.is_seen(listing.source, listing.listing_id):
                    continue

                matched = match_target(listing.title, config)
                # fetch() searched for this target's keywords, but the title
                # may really belong to another target (or be an excluded
                # spares/parts listing) — trust the matcher, not the query.
                store.record_listing(listing, matched.name if matched else None, matched is not None)
                if matched is None:
                    log.info(
                        "unmatched source=%s title=%r price=%.2f",
                        listing.source, listing.title, listing.price,
                    )
                    continue
                if listing.price > matched.max_price:
                    log.info(
                        "rejected=above-max-price target=%r price=%.2f",
                        matched.name, listing.price,
                    )
                    continue

                candidate = _passes_bargain_gate(listing, matched, store, config)
                if candidate is not None:
                    log.info(
                        "candidate target=%r price=%.2f url=%s",
                        matched.name, listing.price, listing.url,
                    )
                    candidates.append(candidate)

    return candidates


def format_digest(candidates: list[Candidate]) -> str:
    """Skimmable one-message digest, shared by dry-run output and Telegram."""
    lines = ["☕ Espresso bargains:"]
    for c in candidates:
        li = c.listing
        if c.pct_under_median is not None:
            vs_median = f"{c.pct_under_median:.0f}% under recent median"
        else:
            vs_median = "insufficient history"
        where = li.location or "unknown location"
        if li.distance_miles is not None:
            where += f" ({li.distance_miles:.0f} mi)"
        lines.append(
            f"• {c.target.name}: £{li.price:.2f} — {vs_median}\n"
            f"  {where} · {li.source}\n"
            f"  {li.url}"
        )
    return "\n".join(lines)
