"""The time-shuffle tripwire — §6.1 step 10's first probe, feature 125.

app_spec.xml, "Leakage Tripwires", feature 125: *"System scores a
candidate against time-shuffled forward returns, which rejects the node
when a surviving Sharpe indicates leakage."*  docs/alpha-engine-prd.md
§C6 spells the probe's whole theory in one line — *"Score against
time-shuffled forward returns.  Surviving Sharpe means leakage."* — and
§C2 puts it in the frozen evaluator's responsibilities ("Run leakage
tripwires (§C6)", step 6 of that list); docs/nullius-tech-architecture.md
§6.1 gives it its pipeline seat, step 10, first of the three probes
(``tripwires   time-shuffle, label-permute, perturbation stability``).
This module is that first probe: it takes a candidate's score panel and a
target bundle, breaks the temporal pairing between them, re-scores, and
states a verdict.

Four decisions carry the feature, and each is a pin rather than a knob:

*a time shuffle re-dates whole cross-sections, and it is a derangement.*
    "Time-shuffled forward returns" could mean several things, so the one
    thing it means here is pinned: the shuffle permutes **rebalance
    dates** — each date's entire per-symbol cross-section of forward
    returns moves, intact, to another date — and the permutation has no
    fixed point.  Two properties do the work.  Moving whole cross-sections
    is what makes this a *time* shuffle rather than the label permutation
    feature 126 runs: re-dating a cross-section destroys exactly the
    date-aligned relationship between a score and the return it was
    scored against, while leaving each cross-section's internal structure
    (its dispersion, its cross-symbol correlation) untouched, so whatever
    survives the shuffle is information the candidate carries about the
    target panel that does not depend on the pairing — a full-sample
    normalization, a symbol-level fit, a panel statistic computed over
    dates the signal was not supposed to see.  And the derangement
    guarantee is what makes the probe's null airtight: a permutation that
    happened to fix date ``d`` would leave that date's aligned pair —
    the very thing under test — intact by luck of the draw, so the
    pairing is re-drawn (deterministically, from the same stream) until
    *every* date is moved.  This is deliberately not §7.2's 20-day block
    permutation: the null oracle block-permutes to build a *world* a
    signal can be re-executed against (autocorrelation and volatility
    clustering preserved so the null world still looks like a market),
    while this probe breaks a *pairing* for an already-computed score
    panel, where the statistic reads one cross-section per date and no
    20-day structure can enter.  Two machineries, two features; neither
    is a second implementation of the other.

*the surviving Sharpe is the candidate's own book, scored against the
shuffled panel.*
    The statistic is the one the whole evaluator already speaks: per
    rebalance date, the score-weighted unit book's return — the mean over
    the date's joined cross-section of ``score × forward return`` — and
    then the Sharpe of that per-date series, mean over population
    standard deviation, the same ``ddof=0`` convention feature 80 pins
    for ``ir_standalone``.  The scores arrive as step 3's normalized
    output (cross-sectional z-scores, feature 74) and are consumed as-is:
    re-normalizing here would be a second implementation of feature 74,
    and the normalizer's scale stability is *why* the mean-of-products
    book needs no second weighting — the threshold below compares a
    ratio, and a ratio is invariant to any global scale.  Symbols are
    joined per date under feature 75's absence rule (a symbol one side
    carries and the other does not is not in that date's cross-section,
    and neither side is zero-filled to become one); a date whose join is
    empty measured nothing and is not in the probe, and a probe left with
    fewer than two such dates is refused — nothing was measured, and a
    tripwire that "passed" a node it never probed is the failure this
    category exists to prevent.

*"indicates leakage" is a two-sided level test against the √T null.*
    Under the shuffle — with every aligned pair broken — a candidate
    carrying no panel-level information has a surviving Sharpe whose
    product with ``√T`` is approximately standard normal, which is the
    same ``√(1/T)`` standard error the PRD's multiple-testing bars are
    stated in.  The verdict is therefore a threshold: reject when
    ``|surviving Sharpe|`` exceeds ``Φ⁻¹(1 − level/2) / √T``, with the
    level pinned at :data:`DEFAULT_SHUFFLE_LEVEL` (0.01, two-sided —
    leakage is sign-agnostic, and a candidate that systematically
    *anti*-tracks the shuffled panel carries exactly the same marginal
    information as one that tracks it; a one-sided probe would let the
    sign-flipped leak through, and the corpus feature 133 plants must
    have 0 escapes).  The test is two-sided, so the nominal false-alarm
    rate is the level itself: at 1%, one clean node in a hundred is
    sacrificed, and the realized rate runs slightly above nominal because
    per-date score-weighted returns are heavier-tailed than Gaussian —
    pinned in the conservative direction, since a tripwire that errs
    does better erring toward rejection than toward letting leakage
    through.  The threshold is computed, not tabled, so a deployment
    tightening the level (feature 127's configured thresholds are the
    precedent) is a parameter change and not a second calibration.

*the verdict is stated, and the rejection is persisted by the features
that own persistence.*
    "Rejects the node" is this feature's to *state*: the verdict record
    carries ``rejected`` and the §8 outcome word — ``tripwire_fail`` when
    rejected, ``ok`` when the probe states no failure — in the closed
    two-word slice of the trial vocabulary a tripwire can speak (the
    ledger's four-word set is feature 91's to stamp, restated here for
    the same reason the evaluator restates it: this member imports no
    other, and a shared vocabulary spelled twice with one provenance
    comment beats an import that couples the frozen evaluator's step 10
    to the ledger's).  What the feature does *not* do is write anything
    down: poisoning the node together with its subtree is feature 131,
    the replay-pool excision feature 132, and the corpus that must
    produce 0 escapes feature 133.  A verdict here is a value — full of
    its own evidence (the pairing, the statistic, the threshold, the
    seed, the level) — and the features that persist will find everything
    they need on it.

**Determinism, pinned twice over.**  The same panel, seed and level
produce the same verdict bit-for-bit: the dates are sorted before
anything touches them (mapping order is insertion order, and the
determinism contract §12 does not trust it), and the shuffle draws only
``random.Random(seed).random()`` — the one primitive Python guarantees
stable across versions — assigning each date one uniform key and sorting
by key, which is a uniform permutation without ``random.shuffle``'s
version-dependent integer draws.  The rejection re-draw advances the
same stream, so the derangement is a pure function of (sorted dates,
seed).  A different seed is a different — equally valid — probe, which
is why the seed is carried *on the verdict*: a reader checking a
persisted rejection can rebuild the pairing from the record's own terms.

**The horizon policy.**  The probe runs on one target series, and the
bundle step 4 aligned carries five, so the policy is pinned here as it
is pinned for feature 80's metrics: the shortest horizon
:data:`HORIZONS` names that the target bundle actually covers — the
fastest-turning horizon is the one with the most rebalance dates and so
the tightest probe (the largest ``T`` in the threshold's ``√T``), and
"shortest covered" is a function of the bundle rather than a caller's
knob, so two deployments running the same node return the same verdict.
:data:`HORIZONS` is restated from the evaluator's closed set rather than
imported, for the same one-provenance reason as the outcome vocabulary:
the five horizons are the spec's (feature 75, §6.1 step 4), not this
member's to widen and not the evaluator's to lend.

**What this module does not do.**  It does not permute labels (feature
126 — the *second* independent probe, within-date, deliberately not
built on this module's shuffle), re-run candidates under perturbations
(features 127 through 130), persist anything (131, 132), or maintain the
leaking corpus (133).  It takes a score panel and a target bundle and
answers exactly the one question step 10 asks first: *does this
candidate still score against forward returns whose dates have been
shuffled — and if it does, is that surviving Sharpe more than chance?*

**The layering note.**  This module is stdlib-only — dates, mappings,
sorting, square roots and one injected-by-construction seed; no polars,
no pyarrow, no lake, no environment, no HTTP, and no import of any other
workspace member.  The panels arrive as plain mappings of plain floats,
the shape every evaluator step past the materialization boundary already
speaks, so the tripwires member stays import-safe for the factory's
scan, the replay path, and the hash-pinned evaluator image this suite
ships inside.
"""

from __future__ import annotations

import datetime as dt
import math
import random
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from .errors import TripwirePanelError, TripwireStatisticError
from .normal import normal_quantile

__all__ = [
    "DEFAULT_SHUFFLE_LEVEL",
    "DEFAULT_SHUFFLE_SEED",
    "HORIZONS",
    "TIME_SHUFFLE_NAME",
    "TRIPWIRE_OUTCOMES",
    "TimeShuffleVerdict",
    "run_time_shuffle_tripwire",
    "surviving_sharpe",
    "time_shuffle_pairing",
    "time_shuffle_threshold",
]

#: The probe's own name, in §C6's and §6.1 step 10's spelling — the first
#: word of ``time-shuffle, label-permute, perturbation stability``.  A
#: verdict carries it so a persisted failure (feature 131) can say *which*
#: tripwire fired, and the hyphen is the spec's own: it is one probe of a
#: three-probe step, not a module name.
TIME_SHUFFLE_NAME: str = "time-shuffle"

#: The two outcome words a tripwire can state — the slice of §8's trial
#: vocabulary (``outcome TEXT NOT NULL -- ok | timeout | error |
#: tripwire_fail``) that step 10 owns: a probe either states no failure
#: (``ok``) or it is the reason the trial failed (``tripwire_fail``).
#: ``timeout`` and ``error`` are the sandbox's words (features 73 and 91);
#: they are restated as absent, not omitted.  This tuple is the member's
#: restatement of a vocabulary the ledger persists and this member cannot
#: import — the same one-provenance rule the evaluator applies when it
#: restates the ledger's four words in its own debit step.
TRIPWIRE_OUTCOMES: tuple[str, ...] = ("ok", "tripwire_fail")

#: The horizons the spec names, ascending — restated from feature 75 and
#: §6.1 step 4 (``h ∈ {1,2,5,10,20}``) so this member resolves its probe
#: horizon without importing the evaluator.  Closed for the same reason it
#: is closed there: a probe horizon the spec does not name is a threshold
#: axis nobody calibrated, and the shortest-covered policy below reads
#: this order.
HORIZONS: tuple[int, ...] = (1, 2, 5, 10, 20)

#: The default shuffle seed.  Pinned to a fixed integer (0) rather than
#: derived from anything — node id, campaign, wall clock — because the
#: probe's value is partly its *repeatability*: the same node probed twice
#: returns the same verdict, and an operator replaying a persisted
#: rejection reproduces it from the record's own seed.  A deployment that
#: wants a different probe draws passes a different one; feature 127's
#: re-run-under-a-different-seed is the evaluator-side counterpart.
DEFAULT_SHUFFLE_SEED: int = 0

#: The default two-sided level of the surviving-Sharpe test — the nominal
#: false-alarm rate, the probability a clean node's surviving Sharpe
#: exceeds the threshold by chance.  0.01: one node in a hundred.  Small
#: enough that a fleet of candidates is not culled by noise, large enough
#: that the canonical leak (verified: a full-sample symbol-mean score
#: over 120 dates of 30 symbols) clears the bar by a factor near two.
DEFAULT_SHUFFLE_LEVEL: float = 0.01


# -- The panels, accepted and validated ---------------------------------------


def _panel_date(where: str, key: object) -> dt.date:
    """Coerce one panel key to a calendar :class:`datetime.date`.

    Accepted spellings: a ``date``, or an ISO string naming one — the
    courtesy every evaluator step extends the rebalance grid.  A
    ``datetime`` is refused (the panels are day-granular, and truncating
    an instant to its day would guess which candle the caller meant);
    anything else is refused by name.
    """
    if isinstance(key, dt.datetime):
        raise TripwirePanelError(
            f"the {where} are keyed by a datetime ({key!r}); the tripwire "
            "panels are day-granular — key by the calendar date (or its "
            "ISO string), one cross-section per rebalance date"
        )
    if isinstance(key, dt.date):
        return key
    if isinstance(key, str):
        try:
            return dt.date.fromisoformat(key)
        except ValueError as exc:
            raise TripwirePanelError(
                f"the {where} carry the date {key!r}, which is not an ISO "
                "date; panels are keyed by rebalance dates (or ISO date "
                "strings), one per bar"
            ) from exc
    raise TripwirePanelError(
        f"the {where} must be keyed by dates or ISO date strings, got "
        f"{key!r} ({type(key).__name__})"
    )


def _panel_value(where: str, day: dt.date, symbol: object, raw: object) -> float:
    """One panel cell, as a finite float.

    Finite because a NaN or ±inf score or return would reach the verdict
    dressed as a measurement.  A ``bool`` is refused even though Python
    calls it an ``int``: ``True`` is not a score and not a return, and the
    arithmetic would happily carry it.  Integers are accepted and
    normalized — a score panel of ints is a legitimate upstream spelling.
    """
    if not isinstance(symbol, str) or not symbol:
        raise TripwirePanelError(
            f"the {where} for {day.isoformat()} must be keyed by non-empty "
            f"symbol names, got {symbol!r}"
        )
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise TripwirePanelError(
            f"the {where} for {symbol!r} on {day.isoformat()} must be a "
            f"number, got {raw!r} ({type(raw).__name__})"
        )
    number = float(raw)
    if not math.isfinite(number):
        raise TripwirePanelError(
            f"the {where} for {symbol!r} on {day.isoformat()} is not finite "
            f"({raw!r}); a NaN or ±inf would reach the tripwire verdict "
            "dressed as a measurement"
        )
    return number


def _validated_series(where: str, series: object) -> dict[dt.date, dict[str, float]]:
    """One date-keyed panel, validated once, as ``{date: {symbol: value}}``.

    Returns plain dicts — the input mapping is the caller's to keep, and
    the probe works over its own normalized copy.  Duplicate dates under
    different spellings (``date(...)`` and its ISO string) are refused:
    one bar, one cross-section, and a panel that carries a bar twice is a
    panel whose shuffle could pair a score with its own alignment.
    """
    if not isinstance(series, Mapping):
        raise TripwirePanelError(
            f"the {where} must map rebalance date to {{symbol: value}}, "
            f"got {type(series).__name__} — the probe reads the panel as a "
            "value, not a callable or a frame"
        )
    panel: dict[dt.date, dict[str, float]] = {}
    for key, row in series.items():
        day = _panel_date(where, key)
        if day in panel:
            raise TripwirePanelError(
                f"the {where} carry {day.isoformat()} twice under different "
                "spellings; one bar, one cross-section, and a shuffle over "
                "a panel that carries a bar twice is not a derangement of "
                "the grid the candidate was scored on"
            )
        if not isinstance(row, Mapping):
            raise TripwirePanelError(
                f"the {where} for {day.isoformat()} must map symbol to "
                f"value, got {type(row).__name__}"
            )
        cells: dict[str, float] = {}
        for symbol, raw in row.items():
            cells[symbol] = _panel_value(where, day, symbol, raw)
        if cells:
            panel[day] = cells
    return panel


def _validated_targets(targets: object) -> dict[int, dict[dt.date, dict[str, float]]]:
    """The target bundle, validated once, as ``{horizon: series}``.

    The shape step 4 aligned and step 5 gated: one series per horizon,
    each ``{rebalance date: {symbol: forward return}}``.  Horizons outside
    :data:`HORIZONS` are refused — the set is the spec's, closed — and a
    horizon whose series is empty is *kept* (the alignment's shape promise
    carries empty coverage) and simply covers nothing in the resolution
    below.
    """
    if not isinstance(targets, Mapping):
        raise TripwirePanelError(
            "the targets must map horizon to {date: {symbol: forward "
            f"return}}, got {type(targets).__name__} — pass the gated "
            "bundle's series as values, one per horizon"
        )
    bundle: dict[int, dict[dt.date, dict[str, float]]] = {}
    for horizon, series in targets.items():
        if isinstance(horizon, bool) or not isinstance(horizon, int):
            raise TripwirePanelError(
                f"a target horizon must be an integer period count, got "
                f"{horizon!r} ({type(horizon).__name__})"
            )
        if horizon not in HORIZONS:
            raise TripwirePanelError(
                f"horizon {horizon} is not one of the horizons the spec "
                f"names ({', '.join(str(h) for h in HORIZONS)}); the probe "
                "horizon is resolved from the closed set, and a horizon "
                "nobody calibrated is a threshold axis nobody calibrated"
            )
        bundle[horizon] = _validated_series(
            f"targets at horizon {horizon}", series
        )
    return bundle


# -- The shuffle ---------------------------------------------------------------


def time_shuffle_pairing(
    dates: object, *, seed: int = DEFAULT_SHUFFLE_SEED
) -> Mapping[dt.date, dt.date]:
    """The derangement that re-dates the panel — ``{score date: target date}``.

    A permutation of ``dates`` with no fixed point, drawn from
    ``random.Random(seed)`` by the one version-stable primitive: each date
    draws one uniform key, and sorting by key is a uniform permutation
    without ``random.shuffle``'s version-dependent integer draws.  A draw
    that fixes any date is discarded and re-drawn from the same stream —
    rejection sampling — so the result is uniform over *derangements* and
    the probe's null is airtight: no aligned pair survives the shuffle by
    luck of the draw.  Deterministic in (sorted dates, seed); the same
    inputs always return the same pairing, bit-for-bit, on any machine.

    ``dates`` must be an iterable of at least two distinct calendar dates
    (or ISO date strings); ``seed`` an integer that is not a ``bool``.
    Both smaller faults are refused by name, because a one-date shuffle is
    the identity by necessity and there is no probe to state.
    """
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TripwirePanelError(
            f"the shuffle seed must be an integer, got {seed!r} "
            f"({type(seed).__name__}); the pairing is a pure function of "
            "the sorted dates and the seed, and a non-integer seed names "
            "no stream to draw from"
        )
    if isinstance(dates, (str, bytes)) or not hasattr(dates, "__iter__"):
        raise TripwirePanelError(
            "the shuffle is drawn over an iterable of calendar dates, got "
            f"{type(dates).__name__}; a single date is not a grid, and a "
            "string would be iterated character by character"
        )
    seen: set[dt.date] = set()
    for key in dates:
        day = _panel_date("shuffle grid", key)
        if day in seen:
            raise TripwirePanelError(
                f"the shuffle grid carries {day.isoformat()} twice; the "
                "pairing is a permutation, and a grid with a repeated bar "
                "has no permutation to be"
            )
        seen.add(day)
    ordered = sorted(seen)
    if len(ordered) < 2:
        raise TripwirePanelError(
            f"the shuffle grid carries {len(ordered)} date; a time shuffle "
            "needs at least two, because a one-date permutation is the "
            "identity and leaves the very pairing under test intact — "
            "there is no probe to state"
        )
    rng = random.Random(seed)
    while True:
        keys = {day: rng.random() for day in ordered}
        shuffled = sorted(ordered, key=lambda day: keys[day])
        if all(source != moved for source, moved in zip(ordered, shuffled)):
            return MappingProxyType(dict(zip(ordered, shuffled)))


# -- The statistic and the threshold -------------------------------------------


def time_shuffle_threshold(dates: int, *, level: float = DEFAULT_SHUFFLE_LEVEL) -> float:
    """The surviving-Sharpe rejection threshold for ``dates`` measured dates.

    ``Φ⁻¹(1 − level/2) / √dates`` — the two-sided level-``level`` quantile
    of the null that standardizes the surviving Sharpe by ``√T`` (the
    PRD's ``√(1/T)`` standard error).  A pure function of the date count
    and the level, so the threshold a verdict carried is the threshold
    any reader recomputes, and the verdict record below enforces exactly
    that.
    """
    if isinstance(dates, bool) or not isinstance(dates, int):
        raise TripwirePanelError(
            f"the threshold is taken over a count of measured dates, got "
            f"{dates!r} ({type(dates).__name__})"
        )
    if dates < 2:
        raise TripwirePanelError(
            f"the threshold standardizes by √T over at least two measured "
            f"dates, got {dates}; a one-date Sharpe names a zero dispersion "
            "and a fabricated infinity"
        )
    if isinstance(level, bool) or not isinstance(level, (int, float)):
        raise TripwirePanelError(
            f"the level must be a number strictly inside (0, 1), got "
            f"{level!r} ({type(level).__name__})"
        )
    probability = float(level)
    if not math.isfinite(probability) or not 0.0 < probability < 1.0:
        raise TripwirePanelError(
            f"the level must be a finite number strictly inside (0, 1), "
            f"got {level!r}; the level is a false-alarm rate, and 0 or 1 "
            "names a threshold that rejects nothing or everything"
        )
    return normal_quantile(1.0 - probability / 2.0) / math.sqrt(dates)


def surviving_sharpe(
    scores: Mapping[dt.date | str, Mapping[str, float]],
    targets: Mapping[dt.date | str, Mapping[str, float]],
    pairing: Mapping[dt.date, dt.date],
) -> float:
    """The candidate's Sharpe against the shuffled panel — the statistic.

    Per date in the pairing: the score-weighted unit book's return, the
    mean over the joined cross-section (feature 75's absence rule) of
    ``score × forward return``, where the returns are the *paired* date's
    — the date the shuffle moved there.  Then the Sharpe of that per-date
    series: mean over population standard deviation (``ddof=0``, feature
    80's convention).  ``scores`` and ``targets`` are single-horizon
    panels ``{date: {symbol: value}}``; the scores are step 3's normalized
    output and are consumed as-is (re-normalizing would be a second
    implementation of feature 74, and the ratio is scale-invariant).

    The pairing must be a derangement whose keys are exactly the dates
    both panels carry *and* whose every joined cross-section is non-empty
    — the runner guarantees both, and a hand-built pairing that violates
    either is refused, because a statistic measured over a pairing with a
    fixed point or an empty join is a statistic the probe never defined.
    Zero dispersion across the measured dates refuses rather than dividing
    by zero (:class:`~tripwires.TripwireStatisticError`).
    """
    score_panel = _validated_series("scores", scores)
    target_panel = _validated_series("targets", targets)
    if not isinstance(pairing, Mapping):
        raise TripwirePanelError(
            "the pairing must map score date to target date, got "
            f"{type(pairing).__name__} — pass time_shuffle_pairing's result"
        )
    shared = sorted(set(score_panel) & set(target_panel))
    captured: dict[dt.date, dt.date] = {}
    for source, moved in pairing.items():
        if not isinstance(source, dt.date) or isinstance(source, dt.datetime):
            raise TripwirePanelError(
                f"the pairing must be keyed by calendar dates, got "
                f"{source!r}"
            )
        if not isinstance(moved, dt.date) or isinstance(moved, dt.datetime):
            raise TripwirePanelError(
                f"the pairing for {source.isoformat()} must name a calendar "
                f"date, got {moved!r}"
            )
        if source == moved:
            raise TripwirePanelError(
                f"the pairing fixes {source.isoformat()}; a fixed point "
                "leaves that date's aligned pair — the very thing under "
                "test — intact, and the probe's null is only airtight over "
                "a derangement"
            )
        captured[source] = moved
    if set(captured) != set(shared):
        raise TripwirePanelError(
            "the pairing must cover exactly the dates both panels carry "
            f"({len(shared)} shared, pairing covers {len(captured)}); a "
            "statistic measured over any other grid is a statistic the "
            "probe never defined"
        )
    per_date: list[float] = []
    for day in shared:
        paired = target_panel[captured[day]]
        common = set(score_panel[day]) & set(paired)
        if not common:
            raise TripwirePanelError(
                f"the joined cross-section on {day.isoformat()} is empty — "
                "the scores and the paired returns share no symbol, so the "
                "date measured nothing; the runner excludes such dates "
                "before pairing, and a pairing that includes one was built "
                "somewhere other than this module"
            )
        per_date.append(
            math.fsum(score_panel[day][symbol] * paired[symbol] for symbol in common)
            / len(common)
        )
    count = len(per_date)
    mean = math.fsum(per_date) / count
    variance = math.fsum((value - mean) ** 2 for value in per_date) / count
    deviation = math.sqrt(variance)
    if deviation == 0.0:
        raise TripwireStatisticError(
            "the score-weighted book returned the same value against the "
            "shuffled panel on every measured date, so its dispersion is "
            "zero and the surviving Sharpe is undefined; refusing rather "
            "than dividing by zero — a candidate that never varied across "
            "dates has no reward-to-variance ratio for the probe to read"
        )
    return mean / deviation


# -- The verdict ---------------------------------------------------------------


@dataclass(frozen=True)
class TimeShuffleVerdict:
    """Step 10's first answer — the time-shuffle probe's verdict, with its evidence.

    The record feature 125 states and the persistence features consume
    (131 poisons the node and subtree from exactly this; 132 excises the
    branch; 133's corpus asserts 0 of these fail to fire on a planted
    leak).  Every term the verdict was computed from is carried on it —
    the seed and level rebuild the pairing and the threshold, the pairing
    itself is the evidence the derangement property holds, and the
    statistic sits beside the threshold it was judged against — because a
    rejection that poisons a subtree is an irreversible act and must be
    auditable from the record alone, the same reason the metrics record
    carries its own ic_series to be checked against.

    The invariants are enforced at construction, so a record built by
    hand — or by a later feature whose producer drifted — fails loudly
    rather than carrying a lying verdict: ``rejected`` must equal the
    comparison the statistic and the threshold actually make, the outcome
    word must be the verdict's own translation into §8's vocabulary, the
    threshold must recompute from the level and the date count, and the
    pairing must be a derangement over exactly the measured dates.
    """

    #: The node whose candidate was probed.
    node_id: str
    #: The probe's name — always :data:`TIME_SHUFFLE_NAME`; carried so a
    #: persisted failure names which tripwire fired.
    tripwire: str
    #: The horizon whose target series was probed — the shortest the
    #: bundle covered, per the module's pinned policy.
    horizon: int
    #: How many rebalance dates the probe measured — the ``T`` behind the
    #: threshold's ``√T``.
    dates: int
    #: The seed the shuffle was drawn from — carried so the pairing, and
    #: therefore the whole verdict, is reproducible from the record.
    seed: int
    #: The two-sided level the threshold was taken at.
    level: float
    #: The Sharpe of the score-weighted book against the shuffled panel.
    surviving_sharpe: float
    #: The rejection threshold — ``Φ⁻¹(1 − level/2) / √dates``.
    threshold: float
    #: The verdict: ``True`` when the surviving Sharpe indicates leakage
    #: and the node is rejected.
    rejected: bool
    #: The verdict in §8's trial vocabulary — ``tripwire_fail`` when
    #: rejected, ``ok`` when the probe states no failure.
    outcome: str
    #: The derangement the probe scored against — ``{score date: target
    #: date}``, every date moved.
    pairing: Mapping[dt.date, dt.date]

    def __post_init__(self) -> None:
        # object.__setattr__ where the constructor normalizes; this record
        # validates only, like the records it sits beside.
        if not isinstance(self.node_id, str) or not self.node_id.strip():
            raise TripwirePanelError(
                "a time-shuffle verdict must name the node whose candidate "
                f"it probed, got {self.node_id!r}"
            )
        if self.tripwire != TIME_SHUFFLE_NAME:
            raise TripwirePanelError(
                f"a time-shuffle verdict's tripwire is {TIME_SHUFFLE_NAME!r}, "
                f"got {self.tripwire!r}; the record names which probe "
                "fired, and a second spelling is a second tripwire"
            )
        if isinstance(self.horizon, bool) or not isinstance(self.horizon, int):
            raise TripwirePanelError(
                f"a time-shuffle verdict's horizon must be an integer "
                f"period count, got {self.horizon!r}"
            )
        if self.horizon not in HORIZONS:
            raise TripwirePanelError(
                f"horizon {self.horizon} is not one of the horizons the "
                f"spec names ({', '.join(str(h) for h in HORIZONS)})"
            )
        if isinstance(self.dates, bool) or not isinstance(self.dates, int):
            raise TripwirePanelError(
                f"a time-shuffle verdict's date count must be an integer, "
                f"got {self.dates!r}"
            )
        if self.dates < 2:
            raise TripwirePanelError(
                f"a time-shuffle verdict measures at least two dates, got "
                f"{self.dates}; below that there is no shuffle and no "
                "dispersion, and a verdict over one date states a probe "
                "that never ran"
            )
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise TripwirePanelError(
                f"a time-shuffle verdict's seed must be an integer, got "
                f"{self.seed!r}"
            )
        for field in ("level", "surviving_sharpe", "threshold"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TripwirePanelError(
                    f"a time-shuffle verdict's {field} must be a number, "
                    f"got {value!r}"
                )
            if not math.isfinite(float(value)):
                raise TripwirePanelError(
                    f"a time-shuffle verdict's {field} is not finite "
                    f"({value!r}); a NaN or ±inf would reach the node "
                    "record dressed as a measurement"
                )
            object.__setattr__(self, field, float(value))
        if not 0.0 < self.level < 1.0:
            raise TripwirePanelError(
                f"a time-shuffle verdict's level is a false-alarm rate "
                f"strictly inside (0, 1), got {self.level!r}"
            )
        if not isinstance(self.rejected, bool):
            raise TripwirePanelError(
                f"a time-shuffle verdict's rejection is a boolean, got "
                f"{self.rejected!r}"
            )
        if self.threshold <= 0.0:
            raise TripwirePanelError(
                f"a time-shuffle verdict's threshold is positive, got "
                f"{self.threshold!r}"
            )
        expected_threshold = time_shuffle_threshold(
            self.dates, level=self.level
        )
        if self.threshold != expected_threshold:
            raise TripwirePanelError(
                f"the time-shuffle verdict says its threshold is "
                f"{self.threshold!r} but level {self.level!r} over "
                f"{self.dates} dates standardizes to "
                f"{expected_threshold!r}; the record disagrees with its "
                "own arithmetic — a threshold no reader can recompute is "
                "a threshold no rejection can be audited against"
            )
        if self.rejected != (abs(self.surviving_sharpe) > self.threshold):
            raise TripwirePanelError(
                f"the time-shuffle verdict says rejected={self.rejected!r} "
                f"but its own terms decide otherwise (|{self.surviving_sharpe!r}| "
                f"vs {self.threshold!r}); the record disagrees with itself, "
                "so it was built somewhere other than this module's "
                "arithmetic — a verdict the node record would trust and "
                "be wrong by"
            )
        if self.outcome not in TRIPWIRE_OUTCOMES:
            raise TripwirePanelError(
                f"a time-shuffle verdict's outcome is one of "
                f"{', '.join(TRIPWIRE_OUTCOMES)} (§8's vocabulary), got "
                f"{self.outcome!r}"
            )
        expected_outcome = "tripwire_fail" if self.rejected else "ok"
        if self.outcome != expected_outcome:
            raise TripwirePanelError(
                f"the time-shuffle verdict says rejected={self.rejected!r} "
                f"but carries outcome {self.outcome!r}; the outcome word is "
                "the verdict's own translation into the trial vocabulary, "
                "and the two spellings of one fact cannot disagree"
            )
        if not isinstance(self.pairing, Mapping):
            raise TripwirePanelError(
                "a time-shuffle verdict's pairing maps score date to "
                f"target date, got {type(self.pairing).__name__}"
            )
        captured: dict[dt.date, dt.date] = {}
        for source, moved in self.pairing.items():
            if not isinstance(source, dt.date) or isinstance(source, dt.datetime):
                raise TripwirePanelError(
                    f"the verdict's pairing is keyed by calendar dates, got "
                    f"{source!r}"
                )
            if not isinstance(moved, dt.date) or isinstance(moved, dt.datetime):
                raise TripwirePanelError(
                    f"the verdict's pairing for {source.isoformat()} names "
                    f"a calendar date, got {moved!r}"
                )
            if source == moved:
                raise TripwirePanelError(
                    f"the verdict's pairing fixes {source.isoformat()}; a "
                    "derangement moves every date, and a fixed point is an "
                    "aligned pair the shuffle left intact"
                )
            captured[source] = moved
        if set(captured) != set(captured.values()):
            raise TripwirePanelError(
                "the verdict's pairing is not a permutation: its keys and "
                "its values are different date sets, so some date's "
                "returns were paired twice and another's not at all"
            )
        if len(captured) != self.dates:
            raise TripwirePanelError(
                f"the time-shuffle verdict claims {self.dates} measured "
                f"dates but its pairing carries {len(captured)}; the count "
                "is the T behind the threshold's √T, and a record whose "
                "denominator disagrees with its own evidence is a record "
                "no reader can size"
            )
        object.__setattr__(self, "pairing", MappingProxyType(captured))

    def __hash__(self) -> int:
        # The mapping is not hashable until it collapses to tuples; the
        # fold keeps __hash__ consistent with __eq__, as every record in
        # this workspace does.
        return hash(
            (
                self.node_id,
                self.tripwire,
                self.horizon,
                self.dates,
                self.seed,
                self.level,
                self.surviving_sharpe,
                self.threshold,
                self.rejected,
                self.outcome,
                tuple(sorted(self.pairing.items())),
            )
        )

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"TimeShuffleVerdict(node={self.node_id!r}, "
            f"horizon={self.horizon}, {self.dates} dates, "
            f"surviving_sharpe={self.surviving_sharpe:+.4f}, "
            f"threshold={self.threshold:.4f}, "
            f"outcome={self.outcome!r})"
        )


# -- The probe -----------------------------------------------------------------


def run_time_shuffle_tripwire(
    scores: Mapping[dt.date | str, Mapping[str, float]],
    targets: Mapping[int, Mapping[dt.date | str, Mapping[str, float]]],
    *,
    node_id: str,
    seed: int = DEFAULT_SHUFFLE_SEED,
    level: float = DEFAULT_SHUFFLE_LEVEL,
) -> TimeShuffleVerdict:
    """Run the time-shuffle tripwire and state the verdict — feature 125.

    The probe, in order: resolve the probe horizon (the shortest horizon
    :data:`HORIZONS` names whose target series shares a date with the
    scores — the most-rebalanced, tightest-probed horizon, the same
    shortest-covered policy the metrics step pins); join the two panels
    onto their shared rebalance dates; draw the derangement over those
    dates from ``seed``; score the candidate's score-weighted book
    against the shuffled panel; and state the verdict against
    ``Φ⁻¹(1 − level/2) / √T``, two-sided, rejecting the node when the
    surviving Sharpe indicates leakage.

    Deterministic in (``scores``, ``targets``, ``seed``, ``level``) —
    the same candidate probed twice returns the same verdict, bit-for-
    bit, which is what a persisted, subtree-poisoning rejection must be
    reproducible from.

    Raises :class:`~tripwires.TripwirePanelError` for a malformed panel,
    a bundle that shares no horizon with the scores, fewer than two
    shared rebalance dates, or a shuffled pairing whose joined
    cross-section is empty on some date (the alignment's coherence rules
    — targets for the symbols the execution scored, feature 75 — make a
    disjoint cross-section a broken read rather than a narrower probe,
    and dropping the date would break the derangement the null depends
    on); :class:`~tripwires.TripwireStatisticError` when the measured
    per-date returns never vary.  A *detected leak is not an exception* —
    it is the verdict's ``rejected`` — because a tripwire that raised on
    detection would be indistinguishable, at the ledger, from one that
    crashed.
    """
    if not isinstance(node_id, str) or not node_id.strip():
        raise TripwirePanelError(
            f"the tripwire must name the node it probes, got {node_id!r}; "
            "a verdict that rejects a node it cannot name is a rejection "
            "nothing downstream can attribute"
        )
    score_panel = _validated_series("scores", scores)
    if not score_panel:
        raise TripwirePanelError(
            "the scores carry no rebalance date with a cross-section, so "
            "there is no candidate to probe — a tripwire that 'passed' a "
            "node it never measured is the failure this category exists "
            "to prevent"
        )
    bundle = _validated_targets(targets)

    horizon: int | None = None
    for candidate in HORIZONS:
        series = bundle.get(candidate)
        if series and set(series) & set(score_panel):
            horizon = candidate
            break
    if horizon is None:
        raise TripwirePanelError(
            "the target bundle shares no horizon with the scores at any "
            f"of the horizons the spec names ({', '.join(str(h) for h in HORIZONS)}), "
            "so no forward return can be paired with a score and there is "
            "no probe to state — align and gate a bundle with coverage "
            "first (features 75 and 76)"
        )
    target_panel = bundle[horizon]

    measurable = sorted(
        day
        for day in set(score_panel) & set(target_panel)
        if set(score_panel[day]) & set(target_panel[day])
    )
    if len(measurable) < 2:
        raise TripwirePanelError(
            f"the scores and the horizon-{horizon} targets share "
            f"{len(measurable)} measurable rebalance date(s), and a time "
            "shuffle needs at least two — a one-date permutation is the "
            "identity and would leave the very pairing under test intact"
        )

    pairing = dict(time_shuffle_pairing(measurable, seed=seed))
    sharpe = surviving_sharpe(score_panel, target_panel, pairing)
    dates = len(measurable)
    threshold = time_shuffle_threshold(dates, level=level)
    rejected = abs(sharpe) > threshold
    return TimeShuffleVerdict(
        node_id=node_id,
        tripwire=TIME_SHUFFLE_NAME,
        horizon=horizon,
        dates=dates,
        seed=seed,
        level=level,
        surviving_sharpe=sharpe,
        threshold=threshold,
        rejected=rejected,
        outcome="tripwire_fail" if rejected else "ok",
        pairing=pairing,
    )
