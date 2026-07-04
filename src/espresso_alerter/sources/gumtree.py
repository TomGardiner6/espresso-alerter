"""Gumtree UK via HTML scraping — no official API exists.

⚠️  EXPECTED TO BREAK: Gumtree can change its markup at any time, and when it
does this module (and only this module) needs updating. All selectors live in
the SELECTORS block below. To fix a breakage:

  1. Fetch a search page, e.g.:
     curl -L -H "User-Agent: <a real browser UA>" \
       "https://www.gumtree.com/search?search_category=all&q=gaggia+classic&search_location=Oxford&distance=40" > page.html
  2. Find the listing cards (as of 2026-07 they are
     <article data-q="search-result"> elements; the data-q attributes are
     Gumtree's own test hooks and change far less often than CSS classes —
     never select on the css-* class names, they are auto-generated hashes).
  3. Update the SELECTORS block and re-run:
     uv run espresso-alerter --once --dry-run

⚠️  BOT PROTECTION: Gumtree sits behind Radware Bot Manager. Burst traffic
(observed threshold: ~12 requests in 10s) triggers a JavaScript challenge —
HTTP status 247 with a small page referencing kramericaindustries...js /
window.rbzns — that a plain HTTP client cannot pass, after which ALL requests
are challenged for a while. Defences here: a ~10s paced gap between requests,
challenge detection that raises GumtreeChallengeError instead of silently
parsing zero listings, and a cooldown so a challenged sweep doesn't keep
poking the block. If challenges persist at this pace, accept intermittent
Gumtree coverage — eBay is the reliable backbone.
"""

from __future__ import annotations

import logging
import random
import re
import time
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from ..config import Config, Target
from ..httputil import request_with_retries
from ..models import Listing

log = logging.getLogger(__name__)

_BASE_URL = "https://www.gumtree.com"
_SEARCH_URL = f"{_BASE_URL}/search"

# ---------------------------------------------------------------- SELECTORS
_SEL_CARD = 'article[data-q="search-result"]'
_SEL_ANCHOR = 'a[data-q="search-result-anchor"]'  # href ends /<numeric id>
_SEL_TITLE = '[data-q="tile-title"]'
_SEL_PRICE = '[data-q="tile-price"]'  # text like "£230" or "£1,200"
_SEL_LOCATION = '[data-q="tile-location"]'
# ---------------------------------------------------------------------------

# Plain browser headers: Gumtree serves the full server-rendered page to
# normal browsers; default httpx/curl UAs risk bot-blocking.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}

# Pace requests like a human browsing — bursts trip Radware (see docstring).
_REQUEST_GAP_SECONDS = 10.0
_REQUEST_JITTER_SECONDS = 4.0

# Once challenged, don't touch Gumtree again for this long.
_CHALLENGE_COOLDOWN_SECONDS = 30 * 60

# Fingerprints of the Radware challenge response.
_CHALLENGE_STATUS = 247
_CHALLENGE_MARKERS = ("kramericaindustries", "window.rbzns")


class GumtreeChallengeError(RuntimeError):
    """Raised when Gumtree serves its bot challenge instead of results."""


def _parse_price(text: str) -> float | None:
    """'£230' / '£1,200.50' -> float; None for 'Free', 'Contact seller', etc."""
    m = re.search(r"£\s*([\d,]+(?:\.\d+)?)", text)
    if not m:
        return None
    return float(m.group(1).replace(",", ""))


def parse_search_page(html: str) -> list[Listing]:
    """Extract normalised listings from one search-results page.

    Skips (with a log line) any card missing the fields we need — a page
    full of skips is the signal that the SELECTORS block is stale.
    """
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(_SEL_CARD)
    listings: list[Listing] = []
    for card in cards:
        anchor = card.select_one(_SEL_ANCHOR)
        title_el = card.select_one(_SEL_TITLE)
        price_el = card.select_one(_SEL_PRICE)
        href = anchor.get("href") if anchor else None
        id_match = re.search(r"/(\d+)/?$", href) if href else None
        price = _parse_price(price_el.get_text()) if price_el else None

        if not (href and id_match and title_el and price is not None):
            log.info(
                "source=gumtree skipped-card href=%r title=%r price=%r "
                "(if every card skips, the selectors are stale — see module docstring)",
                href, title_el.get_text(strip=True) if title_el else None,
                price_el.get_text(strip=True) if price_el else None,
            )
            continue

        location_el = card.select_one(_SEL_LOCATION)
        location = location_el.get_text(strip=True) if location_el else None

        listings.append(
            Listing(
                source="gumtree",
                listing_id=id_match.group(1),
                title=title_el.get_text(strip=True),
                price=price,
                currency="GBP",
                url=urljoin(_BASE_URL, href),
                location=location or None,
                distance_miles=None,  # not shown on result tiles
            )
        )
    if cards and not listings:
        log.warning("source=gumtree parsed 0 of %d cards — selectors likely stale", len(cards))
    return listings


def _is_challenge(resp: httpx.Response) -> bool:
    return resp.status_code == _CHALLENGE_STATUS or any(
        marker in resp.text for marker in _CHALLENGE_MARKERS
    )


class GumtreeSource:
    name = "gumtree"
    # One target per sweep, rotated by the pipeline: with the ~45-min sweep
    # cadence this is only ~1-2 requests every 45 min (a full rotation of all
    # targets takes a few hours), which stays comfortably under the Radware
    # burst threshold. eBay remains the every-sweep backbone.
    targets_per_sweep = 1

    def __init__(self) -> None:
        self._http = httpx.Client(headers=_HEADERS, follow_redirects=True)
        self._last_request_at = 0.0
        self._blocked_until = 0.0

    def _pace(self) -> None:
        """Keep a polite, slightly jittered gap between successive requests."""
        gap = _REQUEST_GAP_SECONDS + random.uniform(0, _REQUEST_JITTER_SECONDS)
        wait = self._last_request_at + gap - time.time()
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.time()

    def fetch(self, target: Target, config: Config) -> list[Listing]:
        if time.time() < self._blocked_until:
            raise GumtreeChallengeError(
                f"cooling down after bot challenge "
                f"({(self._blocked_until - time.time()) / 60:.0f} min left)"
            )

        listings: dict[str, Listing] = {}
        for keyword in target.keywords:
            self._pace()
            resp = request_with_retries(
                self._http,
                "GET",
                _SEARCH_URL,
                params={
                    "search_category": "all",
                    "q": keyword,
                    "search_location": config.location,
                    "distance": int(config.max_distance_miles),
                },
            )
            if _is_challenge(resp):
                self._blocked_until = time.time() + _CHALLENGE_COOLDOWN_SECONDS
                raise GumtreeChallengeError(
                    "bot challenge served (HTTP 247/Radware); backing off "
                    f"{_CHALLENGE_COOLDOWN_SECONDS // 60} min"
                )
            resp.raise_for_status()
            for listing in parse_search_page(resp.text):
                listings[listing.listing_id] = listing

        log.info("source=gumtree target=%r fetched=%d", target.name, len(listings))
        return list(listings.values())
