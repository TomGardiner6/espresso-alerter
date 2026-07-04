"""Title matching: keyword hit required, exclusion phrases veto."""

from __future__ import annotations

import re

from .config import Config, Target


def _contains_phrase(title: str, phrase: str) -> bool:
    return re.search(rf"\b{re.escape(phrase.lower())}\b", title.lower()) is not None


def match_target(title: str, config: Config) -> Target | None:
    """Return the first target whose keywords match `title`, or None.

    A title is vetoed if it contains any exclusion phrase (the target's own
    list if set, otherwise the global one) — guards against spares/broken/
    accessory listings masquerading as the real thing.
    """
    for target in config.targets:
        if not any(_contains_phrase(title, kw) for kw in target.keywords):
            continue
        excludes = (
            target.exclude_keywords
            if target.exclude_keywords is not None
            else config.exclude_keywords
        )
        if any(_contains_phrase(title, ex) for ex in excludes):
            return None
        return target
    return None
