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
    """

    name: str

    def fetch(self, target: Target, config: Config) -> list[Listing]: ...
