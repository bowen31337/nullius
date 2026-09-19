"""The universe definition, written down and hashable.

docs/nullius-tech-architecture.md §4.2 puts ``universe_definition`` inside
the snapshot hash, so the definition must be a value that can be pinned,
compared and hashed — never ambient state scattered across call sites. A
frozen dataclass gives that: two builds with equal configs are the same
build, and a changed knob is a changed definition.

The defaults encode the spec, not taste: ``top_n`` defaults to 100 (the
architecture sizes the lake around "a 100-symbol universe") and the ranking
window is the 30-day median dollar volume the spec names. ``window_days``
and ``min_observations`` are configurable because they are policy; the
*shape* of the rule — trailing window, median, top-N — is not.

``min_observations`` is the anti-flash-in-the-pan guard: a symbol must have
traded at least this many days inside the trailing window for its median to
mean anything. The default of 1 keeps this member exactly on the spec
(feature 40 ranks by the 30-day median, full stop) while leaving the
stricter eligibility policy to the sibling that owns it.
"""

from __future__ import annotations

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
    """

    top_n: int = 100
    window_days: int = 30
    min_observations: int = 1

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
