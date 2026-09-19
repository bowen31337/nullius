"""Purging a cross-validation fold at its split boundary — pipeline step 6.

app_spec.xml feature 77: *"System rejects a cross-validation fold whose
holding period is not purged at the split boundary."* docs/nullius-tech-
architecture.md §6.1 names the step — ``6. purge_and_embargo  purge H,
embargo L around every CV split`` — and §C6.2 of the PRD states the intent
behind it: *"Purge the holding period (H) around every CV split so a label
whose holding period straddles a split leaks no test-set return into
training."*

The feature sentence is a refusal, and this module is exactly that refusal.
It does not split the data into folds, it does not choose the split, and it
does not trim the training set down to a purged one. It takes the market
grid, the split a caller has already drawn, the training half of that fold,
and the holding period the label at the split is measured over, and it
*certifies* the fold: it raises when the training set lets a training bar
sit close enough to the split to leak the label's test-set return, and it
returns a verdict record when the fold is clean.

**What "the holding period straddles a split" means, and why it leaks.** A
label at bar ``j`` is the forward return from the close on ``j`` to the close
``H`` bars later — ``close[j+H] / close[j] − 1``. That exit close,
``close[j+H]``, is realised *after* ``j``; if ``j + H`` reaches the split or
past it, the label is built from a test-set price, and a model trained on it
has learned from the test set. So a training bar ``j`` leaks exactly when
``j + H ≥ split`` — equivalently, when ``j ≥ split − H`` on the market grid.
The purge keeps every such bar out of training: the last training bar must
sit at grid index ``≤ split − H − 1``. This module checks exactly that.

**Why the whole market grid is an input, not the fold alone.** The holding
period is a count of *grid bars*, and the distance that matters is the
distance from the last training bar to the split *on the market grid* — the
same sorted sequence of bars feature 75's alignment walks, where "one period"
is one bar, not one calendar day (weekends and holidays have no bars). A fold
handed in as "its training bars and its split" cannot speak for that
distance: the bars between the last training bar and the split are exactly
the ones a purge removes, so a fold that omits them would make an adjacent
training-bar-and-split look purged when it leaks. The grid is therefore
required — it is the ruler the holding period is measured against, and a
check without it would certify leaks it cannot see.

**The bar-granular rule, stated once.** With the market grid ``g`` (indexed
from 0), the split at ``split_index`` and the last training bar at
``last_index``, the holding period is purged exactly when::

    last_index ≤ split_index − H − 1

The ``H`` bars at grid indices ``split_index − H … split_index − 1`` are the
holding period's mirror image; any training bar inside them is un-purged. The
**shortfall** the verdict reports is how many grid bars the last training bar
sits past that line — the number that would have to be dropped from the end
of the training half to purge the fold.

**What this module does not do.** It does not split (a caller draws the
folds), it does not trim (a caller removes the ``H`` bars the shortfall names
and re-checks), it does not embargo (feature 78 adds the embargo around the
purged split), it does not align targets (feature 75) or apply costs
(feature 79). It takes the grid, the training half, the split and the holding
period as given and answers exactly the one question step 6 puts in scope:
*is the holding period purged at this split boundary?* — raising when it is
not, so an un-purged fold never reaches the metrics that would trust it.

**The layering note.** This module is stdlib-only — no polars, no pyarrow,
no lake, no environment, no numerics. The values in and out are dates and a
bar count in a plain record, because a purge check is a statement about the
ordering of bars, not a computation over a frame. Importing this member
therefore costs composition — and the replay path §1 forbids from reaching
the evaluator — nothing at all, matching the import-cheap discipline the
rest of this package holds to.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from ._errors import EvaluatorPurgeError

__all__ = [
    "PurgeCheck",
    "check_fold_purged",
]


def _as_date(value: object, label: str) -> dt.date:
    """Coerce one date-like value to a calendar :class:`datetime.date`.

    Accepted spellings: a ``date`` or an ISO string naming one — the same
    courtesy the window and the alignment extend their date keys. A
    ``datetime`` is refused (it names an instant, and the purge is
    bar-granular: the grid, the split and the training dates are dates, so
    silently truncating an instant to its day would be a guess about which
    bar the caller meant), and anything else is refused by name.
    """
    if isinstance(value, dt.datetime):
        raise EvaluatorPurgeError(
            f"{label} is a datetime ({value!r}); the purge is bar-granular — "
            "name dates by calendar date (or its ISO string), the day the "
            "bar belongs to"
        )
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value)
        except ValueError as exc:
            raise EvaluatorPurgeError(
                f"{label} is {value!r}, not an ISO date; the grid, the split "
                "and the training dates are calendar dates (or ISO date "
                "strings), one per bar"
            ) from exc
    raise EvaluatorPurgeError(
        f"{label} must be a date or ISO date string, got {value!r} "
        f"({type(value).__name__})"
    )


def _as_grid(values: object) -> tuple[dt.date, ...]:
    """The market grid — an ordered, de-duplicated sequence of bar dates.

    The grid is the ruler the holding period is measured against (see the
    module docstring): the sorted union of every bar date the evaluation
    names. It is accepted as any iterable of date-like values; each is
    coerced (see :func:`_as_date`), and the sequence is refused unless it
    arrives sorted and without a bar twice — a market grid is an ordering,
    and an unsorted or duplicated one is a broken ruler a check cannot trust.
    An empty grid is refused: there is no boundary to purge at where there
    are no bars.
    """
    if isinstance(values, (str, bytes)) or not hasattr(values, "__iter__"):
        raise EvaluatorPurgeError(
            "grid must be an iterable of dates (or ISO date strings), got "
            f"{type(values).__name__}; the market grid is the ruler the "
            "holding period is measured against"
        )
    grid: list[dt.date] = [_as_date(value, "a grid bar") for value in values]
    if not grid:
        raise EvaluatorPurgeError(
            "grid is empty — the holding period is measured against the "
            "market grid, and a grid with no bars has no split to purge at"
        )
    if grid != sorted(set(grid)):
        raise EvaluatorPurgeError(
            "grid must arrive sorted and without a bar twice; the market grid "
            "is an ordering, and an unsorted or duplicated ruler is one a "
            "purge check cannot measure against"
        )
    return tuple(grid)


def _as_date_set(values: object, grid: tuple[dt.date, ...]) -> set[dt.date]:
    """A fold's training half — the grid bars a model would be trained on.

    Accepted as any iterable of date-like values; each is coerced (see
    :func:`_as_date`) and must be a bar of ``grid`` — a training date off the
    grid is a fold drawn on a different timeline, which this check cannot
    place. Collected into a set, because the check asks only *which* bars are
    trained on. An empty training half is refused: a fold has a training half
    to purge and a test half to score, so a fold with no training bars was
    never drawn.
    """
    if isinstance(values, (str, bytes)) or not hasattr(values, "__iter__"):
        raise EvaluatorPurgeError(
            "training_dates must be an iterable of dates (or ISO date "
            f"strings), got {type(values).__name__}; the fold's training half "
            "is the bars a model is trained on"
        )
    seen: set[dt.date] = set()
    for value in values:
        day = _as_date(value, "a training date")
        if day not in grid:
            raise EvaluatorPurgeError(
                f"a training date {day.isoformat()} is not on the market "
                "grid; the fold's training half must be bars of the grid the "
                "holding period is measured against"
            )
        seen.add(day)
    if not seen:
        raise EvaluatorPurgeError(
            "training_dates is empty — a fold has a training half to purge "
            "and a test half to score; draw the fold before checking it"
        )
    return seen


@dataclass(frozen=True)
class PurgeCheck:
    """The verdict of a single split-boundary purge check.

    The value feature 77's step returns when a fold *is* purged: the last
    training bar, the split, and the shortfall — always ``0`` here, because
    :func:`check_fold_purged` raises for an un-purged fold rather than
    returning one. Carried beside the fold it describes, filed in a report,
    or compared across folds without recomputing (frozen, hashable).
    """

    #: The latest bar the training set reaches, as a calendar date.
    last_training_bar: dt.date
    #: The split boundary the holding period starts at.
    split: dt.date
    #: How many grid bars the last training bar sits past the purge line — the
    #: number to drop from the end of the training half to purge the fold.
    #: Always ``0`` on a record this module returns (an un-purged fold is
    #: raised, not returned); carried so a hand-built verdict can name a fold
    #: a caller is inspecting.
    shortfall: int

    def __post_init__(self) -> None:
        # Object.__setattr__ because the dataclass is frozen and these are
        # the values the constructor accepted.
        for name in ("last_training_bar", "split"):
            value = getattr(self, name)
            if not isinstance(value, dt.date) or isinstance(value, dt.datetime):
                raise EvaluatorPurgeError(
                    f"{name} must be a calendar date, got {value!r}"
                )
        if isinstance(self.shortfall, bool) or not isinstance(self.shortfall, int):
            raise EvaluatorPurgeError("shortfall must be an integer bar count")
        if self.shortfall < 0:
            raise EvaluatorPurgeError("shortfall cannot be negative")

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"PurgeCheck(last_training_bar={self.last_training_bar.isoformat()}, "
            f"split={self.split.isoformat()}, shortfall={self.shortfall})"
        )


def check_fold_purged(
    grid: object,
    training_dates: object,
    split: object,
    holding_period: object,
) -> PurgeCheck:
    """Certify that a fold's holding period is purged at its split boundary.

    Pipeline step 6 (§6.1): a cross-validation fold is split into a training
    half and a test half at a boundary date ``split`` on the market grid. The
    label at ``split`` is the forward return over its holding period — the
    ``holding_period`` bars after ``split`` — and that return is realised in
    the test set, so a training bar whose own holding period reaches the split
    would leak that test-set return into the model. This function certifies
    that the training half keeps the holding period out, and **raises** when
    it does not — an un-purged fold is refused, never returned, so it can
    never reach the metrics that would trust it.

    ``grid`` is the market grid — the ordered, de-duplicated sequence of bar
    dates (or ISO date strings) the evaluation names, the ruler the holding
    period is measured against. ``training_dates`` is the fold's training half
    — the grid bars a model would be trained on. ``split`` is the boundary the
    holding period starts at — a grid date or ISO string. ``holding_period``
    is the number of grid bars the holding period spans — a positive integer,
    one of feature 75's horizons — because it is the leakage of a label
    measured over that span the purge prevents.

    The holding period is purged exactly when the last training bar sits at
    grid index ``≤ split_index − holding_period − 1``; the ``holding_period``
    bars just before the split are the holding period's mirror image, and any
    training bar inside them leaks.

    Returns a :class:`PurgeCheck` naming the last training bar, the split and
    the shortfall (``0``). Raises :class:`EvaluatorPurgeError`, each with its
    reason (see ``_errors``): a ``holding_period`` that is not a positive bar
    count; a grid that is not a well-formed market grid; a split not on the
    grid, or itself a training bar; a training date off the grid, or past the
    split; and a training half whose last bar is within the holding period of
    the split — the fold is un-purged, and the refusal names how many bars it
    falls short.
    """
    if isinstance(holding_period, bool) or not isinstance(holding_period, int):
        raise EvaluatorPurgeError(
            "holding_period must be a positive integer number of grid bars — "
            f"one of the horizons the label is measured over — got "
            f"{holding_period!r} ({type(holding_period).__name__})"
        )
    if holding_period <= 0:
        raise EvaluatorPurgeError(
            f"holding_period must be at least one grid bar, got {holding_period}; "
            "a holding period of zero bars has nothing to purge — the label's "
            "return is realised over the bars after the split, and those bars "
            "must be kept out of training"
        )

    grid_dates = _as_grid(grid)
    training = _as_date_set(training_dates, grid_dates)
    split_day = _as_date(split, "the split")
    if split_day not in grid_dates:
        raise EvaluatorPurgeError(
            f"the split {split_day.isoformat()} is not on the market grid; "
            "the boundary the holding period starts at must be a bar the "
            "holding period is measured against"
        )

    # The split is the boundary, not a member of the training half. A fold
    # that trains on its own split would train on the label's entry bar — and
    # silently dropping it would let the leakage the purge exists to catch
    # pass, so it is refused rather than narrowed around.
    if split_day in training:
        raise EvaluatorPurgeError(
            f"the split {split_day.isoformat()} is one of the training dates; "
            "a split is the boundary the holding period starts at, not a bar "
            "to train on — the label's own entry bar would be trained on, so "
            "draw the fold with the split between the two halves"
        )

    position = {day: index for index, day in enumerate(grid_dates)}
    split_index = position[split_day]
    last_bar = max(training)
    last_index = position[last_bar]

    # A training bar past the split puts the test half behind the model — the
    # fold has its halves the wrong way round, refused rather than trusted.
    if last_index > split_index:
        raise EvaluatorPurgeError(
            f"the last training bar {last_bar.isoformat()} is after the split "
            f"{split_day.isoformat()}; a split puts the training half before "
            "it and the test half after it"
        )

    # The purge line is the last grid index a training bar may occupy: the
    # split minus the holding period, minus one more because a bar whose own
    # holding period merely *reaches* the split still leaks. The shortfall is
    # how many bars the last training bar sits past it — the number to drop
    # from the end of the training half to purge the fold.
    purge_line = split_index - holding_period - 1
    shortfall = max(0, last_index - purge_line)
    if shortfall > 0:
        raise EvaluatorPurgeError(
            f"the fold's holding period is not purged at the split "
            f"{split_day.isoformat()}: the last training bar "
            f"{last_bar.isoformat()} sits {shortfall} grid "
            f"{'bar' if shortfall == 1 else 'bars'} inside the purge line, so "
            "a training bar leaks the label's test-set return into the model "
            "— drop the last "
            f"{shortfall} {'bar' if shortfall == 1 else 'bars'} of the "
            "training half, or widen the split's holding period, and re-check"
        )

    return PurgeCheck(
        last_training_bar=last_bar,
        split=split_day,
        shortfall=shortfall,
    )
