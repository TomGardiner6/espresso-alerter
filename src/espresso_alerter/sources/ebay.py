"""eBay UK via the official Browse API (OAuth2 client-credentials app token).

Docs: https://developer.ebay.com/api-docs/buy/browse/resources/item_summary/methods/search
"""

from __future__ import annotations

import base64
import logging
import os
import time

import httpx

from ..config import Config, Target
from ..httputil import request_with_retries
from ..models import Listing

log = logging.getLogger(__name__)

_TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
_SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
_SCOPE = "https://api.ebay.com/oauth/api_scope"


class EbaySource:
    name = "ebay"

    def __init__(self, client_id: str, client_secret: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._token: str | None = None
        self._token_expiry: float = 0.0
        self._http = httpx.Client()

    @classmethod
    def from_env(cls) -> "EbaySource | None":
        client_id = os.environ.get("EBAY_CLIENT_ID")
        client_secret = os.environ.get("EBAY_CLIENT_SECRET")
        if not client_id or not client_secret:
            return None
        return cls(client_id, client_secret)

    def _get_token(self) -> str:
        # App tokens last ~2h; refresh 5 min early.
        if self._token and time.time() < self._token_expiry - 300:
            return self._token
        basic = base64.b64encode(
            f"{self._client_id}:{self._client_secret}".encode()
        ).decode()
        resp = request_with_retries(
            self._http,
            "POST",
            _TOKEN_URL,
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "client_credentials", "scope": _SCOPE},
        )
        resp.raise_for_status()
        payload = resp.json()
        self._token = payload["access_token"]
        self._token_expiry = time.time() + int(payload.get("expires_in", 7200))
        log.info("source=ebay token refreshed expires_in=%ss", payload.get("expires_in"))
        return self._token

    def fetch(self, target: Target, config: Config) -> list[Listing]:
        token = self._get_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "X-EBAY-C-MARKETPLACE-ID": "EBAY_GB",
        }
        # Filter server-side to GB items at or under max_price; the strict
        # bargain gate is applied later in the pipeline.
        filters = (
            f"price:[..{target.max_price:g}],"
            "priceCurrency:GBP,"
            "itemLocationCountry:GB,"
            "buyingOptions:{FIXED_PRICE|BEST_OFFER}"
        )

        listings: dict[str, Listing] = {}
        for keyword in target.keywords:
            resp = request_with_retries(
                self._http,
                "GET",
                _SEARCH_URL,
                headers=headers,
                params={"q": keyword, "filter": filters, "limit": 50, "sort": "price"},
            )
            resp.raise_for_status()
            for item in resp.json().get("itemSummaries", []):
                listing = self._normalise(item)
                if listing is not None:
                    listings[listing.listing_id] = listing

        log.info(
            "source=ebay target=%r fetched=%d", target.name, len(listings)
        )
        return list(listings.values())

    @staticmethod
    def _normalise(item: dict) -> Listing | None:
        item_id = item.get("itemId")
        title = item.get("title")
        price = item.get("price") or {}
        url = item.get("itemWebUrl")
        if not (item_id and title and price.get("value") and url):
            return None

        loc = item.get("itemLocation") or {}
        location_bits = [loc.get("city"), loc.get("postalCode")]
        location = ", ".join(b for b in location_bits if b) or None

        distance = None
        dist = item.get("distanceFromPickupLocation")
        if dist and dist.get("value") is not None:
            distance = float(dist["value"])

        return Listing(
            source="ebay",
            listing_id=str(item_id),
            title=str(title),
            price=float(price["value"]),
            currency=str(price.get("currency", "GBP")),
            url=str(url),
            location=location,
            distance_miles=distance,
        )
