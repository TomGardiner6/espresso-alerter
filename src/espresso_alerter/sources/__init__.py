"""Listing sources. Each source implements the `Source` protocol in base.py."""

from __future__ import annotations

import logging

from ..config import Config
from .base import Source
from .ebay import EbaySource
from .gumtree import GumtreeSource

log = logging.getLogger(__name__)


def build_sources(config: Config) -> list[Source]:
    """Instantiate every source whose credentials/config are available."""
    sources: list[Source] = []

    ebay = EbaySource.from_env()
    if ebay is not None:
        sources.append(ebay)
    else:
        log.warning(
            "source=ebay skipped reason=missing-credentials "
            "(set EBAY_CLIENT_ID / EBAY_CLIENT_SECRET in .env)"
        )

    sources.append(GumtreeSource())  # scraping, no credentials needed

    return sources
