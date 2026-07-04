"""One sweep: fetch from every source, dedupe, match, gate, queue, notify."""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .config import Config, Target
from .models import Listing, PendingAlert
from .notify.base import Notifier
from .sources.base import Source
from .store import Store

log = logging.getLogger(__name__)

_LAST_MESSAGE_KEY = "last_message_at"


@dataclass(frozen=True)
class Candidate:
    """A listing that passed the bargain gate this sweep."""

    listing: Listing
    target: Target
    median: float | None  # None => insufficient history
    pct_under_median: float | None

    def to_pending(self) -> PendingAlert:
        return PendingAlert(
            target=self.target.name,
            source=self.listing.source,
            listing_id=self.listing.listing_id,
            title=self.listing.title,
            price=self.listing.price,
            url=self.listing.url,
            location=self.listing.location,
            distance_miles=self.listing.distance_miles,
            median=self.median,
            pct_under_median=self.pct_under_median,
        )


def _passes_bargain_gate(
    listing: Listing, target: Target, store: Store, config: Config
) -> Candidate | None:
    """Apply the strict gate. Returns a Candidate or None (with a log line)."""
    prices = store.recent_prices(target.name, config.history_window)
    median = statistics.median(prices) if len(prices) >= config.history_window else None

    # Scam/accessory sanity checks: below the target's absolute floor,
    # absurdly cheap vs running median, or no location.
    # Suppressed listings do NOT feed the price history.
    if listing.price < target.min_price:
        log.info(
            "suppressed=below-floor target=%r price=%.2f floor=%.2f url=%s",
            target.name, listing.price, target.min_price, listing.url,
        )
        return None
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


def _select_targets(source: Source, targets: list[Target], store: Store) -> list[Target]:
    """Pick which targets to query this sweep for one source.

    A source may cap itself with `targets_per_sweep` (Gumtree does, to stay
    low-volume); we then rotate through the full list across sweeps using a
    per-source cursor persisted in the store, so over N sweeps every target
    is covered without ever bursting. Sources without the cap get everything.
    """
    per_sweep = getattr(source, "targets_per_sweep", None)
    if per_sweep is None or per_sweep >= len(targets):
        return targets

    cursor_key = f"target_cursor:{source.name}"
    start = int(store.get_meta(cursor_key) or 0) % len(targets)
    selected = [targets[(start + i) % len(targets)] for i in range(per_sweep)]
    store.set_meta(cursor_key, str((start + per_sweep) % len(targets)))
    log.info(
        "source=%s querying %d/%d targets this sweep: %s",
        source.name, len(selected), len(targets), [t.name for t in selected],
    )
    return selected


def sweep(config: Config, sources: list[Source], store: Store) -> list[Candidate]:
    """Run one full sweep across all sources. Never raises on a source failure."""
    from .matching import match_target

    candidates: list[Candidate] = []
    for source in sources:
        for target in _select_targets(source, config.targets, store):
            try:
                listings = source.fetch(target, config)
            except Exception as exc:
                log.warning(
                    "source=%s target=%r fetch failed: %s; continuing",
                    source.name, target.name, exc,
                )
                log.debug("fetch failure traceback", exc_info=True)
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


def format_digest(alerts: list[PendingAlert]) -> str:
    """Skimmable one-message digest, shared by dry-run output and Telegram."""
    lines = ["☕ Espresso bargains:"]
    for a in alerts:
        if a.pct_under_median is not None:
            vs_median = f"{a.pct_under_median:.0f}% under recent median"
        else:
            vs_median = "insufficient history"
        where = a.location or "unknown location"
        if a.distance_miles is not None:
            where += f" ({a.distance_miles:.0f} mi)"
        lines.append(
            f"• {a.target}: £{a.price:.2f} — {vs_median}\n"
            f"  {where} · {a.source}\n"
            f"  {a.url}"
        )
    return "\n".join(lines)


def run_cycle(
    config: Config,
    sources: list[Source],
    store: Store,
    notifier: Notifier | None,
    dry_run: bool = False,
) -> None:
    """One complete cycle: sweep, queue qualifiers, send if the rate cap allows.

    New qualifiers are always persisted to the pending queue first (so a
    crash, rate-capped hold, or dry run never loses them); the digest goes
    out only when `min_hours_between_messages` has elapsed since the last
    send, and alerts are marked sent only after Telegram accepts the message.
    """
    candidates = sweep(config, sources, store)
    for candidate in candidates:
        store.add_pending(candidate.to_pending())
    log.info("sweep complete new_qualifiers=%d", len(candidates))

    pending = store.unsent_alerts()
    if not pending:
        log.info("no pending alerts")
        return

    digest = format_digest(pending)

    if dry_run:
        print("\n--- DRY RUN: would send this digest ---\n")
        print(digest)
        print("\n--- end dry run (nothing sent; alerts stay pending) ---")
        return

    now = datetime.now(timezone.utc)
    last_sent_raw = store.get_meta(_LAST_MESSAGE_KEY)
    if last_sent_raw is not None:
        last_sent = datetime.fromisoformat(last_sent_raw)
        window = timedelta(hours=config.min_hours_between_messages)
        remaining = last_sent + window - now
        if remaining > timedelta(0):
            log.info(
                "rate-capped: holding %d alert(s) for %.1fh more",
                len(pending), remaining.total_seconds() / 3600,
            )
            return

    if notifier is None:
        log.warning("no notifier configured; holding %d alert(s)", len(pending))
        return

    try:
        notifier.send(digest)
    except Exception:
        log.exception("notifier=%s send failed; alerts stay pending", notifier.name)
        return

    store.mark_sent([a.id for a in pending if a.id is not None])
    store.set_meta(_LAST_MESSAGE_KEY, now.isoformat(timespec="seconds"))
    log.info("digest sent alerts=%d notifier=%s", len(pending), notifier.name)
