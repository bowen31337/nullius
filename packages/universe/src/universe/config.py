"""The universe definition, written down and hashable.

docs/nullius-tech-architecture.md §4.2 puts ``universe_definition`` inside
the snapshot hash, so the definition must be a value that can be pinned,
compared and hashed — never ambient state scattered across call sites. A
frozen dataclass gives that: two builds with equal configs are the same
build, and a changed knob is a changed definition.

The defaults encode the spec, not taste: ``top_n`` defaults to 100 (the
architecture sizes the lake around "a 100-symbol universe") and the ranking
window is the 30-day median dollar volume the spec names. ``window_days``,
``min_observations`` and ``min_dollar_volume`` are configurable because
they are policy; the *shape* of the rule — trailing window, median, top-N —
is not.

``min_observations`` is the anti-flash-in-the-pan guard: a symbol must have
traded at least this many days inside the trailing window for its median to
mean anything. ``min_dollar_volume`` is the liquidity floor (feature 47):
a symbol whose trailing median dollar volume falls below it is excluded
from the universe and the exclusion is persisted with its reason, so an
audit can tell "out-ranked" from "not liquid enough to trade". Both default
to the values that keep this member exactly on the plain rule of feature
40 — rank by the 30-day median, full stop: a floor of 0 excludes nothing
(dollar volumes are non-negative by construction), and the stricter
eligibility policy is a floor the operator configures.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

__all__ = ["UniverseConfig"]


@dataclass(frozen=True)
class UniverseConfig:
    """Parameters of the monthly top-N-by-median-dollar-volume universe.

    Attributes:
        top_n: Symbols admitted to the monthly universe (rank 1..top_n).
        window_days: Length in calendar days of the trailing dollar-volume
            window ending the day before the effective month starts.
        min_observations: Minimum number of daily bars a symbol must have
            inside the window to be eligible for ranking at all.
        min_dollar_volume: The liquidity floor. A symbol whose trailing
            median dollar volume falls *below* this is excluded from the
            universe and the exclusion persisted with its reason. Exactly
            at the floor the symbol is eligible — "falls below" is strict.
            The default of 0.0 configures no floor, which is feature 40's
            plain ranking rule.
    """

    top_n: int = 100
    window_days: int = 30
    min_observations: int = 1
    min_dollar_volume: float = 0.0

    def __post_init__(self) -> None:
        for name in ("top_n", "window_days", "min_observations"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(f"{name} must be an int, got {type(value).__name__}")
            if value < 1:
                raise ValueError(
                    f"{name} must be >= 1, got {value}; a universe build with "
                    "no members or an empty window is a misconfiguration, not "
                    "an empty result"
                )
        floor = self.min_dollar_volume
        if isinstance(floor, bool) or not isinstance(floor, (int, float)):
            raise TypeError(
                f"min_dollar_volume must be a number, got {type(floor).__name__}"
            )
        if not math.isfinite(floor):
            raise ValueError(
                f"min_dollar_volume must be finite, got {floor}; a NaN or "
                "infinite floor is a typo, not a policy"
            )
        if floor < 0:
            raise ValueError(
                f"min_dollar_volume must be >= 0, got {floor}; a negative "
                "liquidity floor is a misconfiguration, not a stricter policy"
            )
        # Pin to float so an int floor (10_000 == 10_000.0) compares and
        # hashes identically to the same floor spelled as a float.
        object.__setattr__(self, "min_dollar_volume", float(floor))
