"""Interface every listing source implements."""

from __future__ import annotations

from typing import Protocol

from ..config import Config, Target
from ..models import Listing


class Source(Protocol):
    """A place listings come from (eBay API, Gumtree scrape, ...).

    `fetch` returns normalised Listings for one target. It may raise on
    total failure — the pipeline catches per-source errors so one source
    being down never kills a sweep.

    Optional attribute `targets_per_sweep`: if a source sets this to an int,
    the pipeline queries only that many targets per sweep, rotating through
    the full target list across successive sweeps (used by the Gumtree
    scraper to stay low-volume). Sources without it are queried for every
    target every sweep (the default for an official API like eBay).
    """

    name: str

    def fetch(self, target: Target, config: Config) -> list[Listing]: ...
