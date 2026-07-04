"""Load config.yaml and .env. All tuning lives in YAML; secrets in env."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv


@dataclass
class Target:
    name: str
    keywords: list[str]
    max_price: float
    bargain_price: float
    # Optional per-target override of the global exclusion list, for the day
    # you decide you *do* want e.g. spares listings for one model.
    exclude_keywords: list[str] | None = None


@dataclass
class Config:
    targets: list[Target]
    location: str = "Oxford"
    max_distance_miles: float = 40
    sweep_interval_minutes: int = 45
    min_hours_between_messages: float = 3
    history_window: int = 20
    scam_median_fraction: float = 0.25
    exclude_keywords: list[str] = field(default_factory=list)


def load_config(path: str | Path = "config.yaml") -> Config:
    load_dotenv()  # makes .env values visible to sources/notifiers via os.environ

    raw = yaml.safe_load(Path(path).read_text())
    targets = [Target(**t) for t in raw.pop("targets")]
    return Config(targets=targets, **raw)
