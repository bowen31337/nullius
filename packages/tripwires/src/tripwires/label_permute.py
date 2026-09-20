"""The label-permutation tripwire — §6.1 step 10's second probe, feature 126.

app_spec.xml, "Leakage Tripwires", feature 126: *"System scores a candidate
against label-permuted targets as a second independent leakage probe, which
returns a pass or fail verdict."*  docs/alpha-engine-prd.md §C6 states it as the
second of three sentences in one breath — *"Score against time-shuffled forward
returns.  Surviving Sharpe means leakage.  Score against label-permuted targets.
Same test, different permutation."* — and docs/nullius-tech-architecture.md §6.1
gives it its seat, step 10, second of the three probes
(``tripwires   time-shuffle, label-permute, perturbation stability``).  Feature
125 is the first; this module is the second, and :mod:`tripwires.time_shuffle`
names this one as the probe it is *not*: *"the second independent probe,
within-date, deliberately not built on this module's shuffle"*.

**"Same test, different permutation" is the whole feature, and the two nouns are
the work.**  *Same test*: the statistic is feature 125's, stated once there and
consumed here — per rebalance date, the score-weighted unit book's return, the
mean over the date's joined cross-section of ``score × forward return``, and then
the Sharpe of that per-date series, mean over population standard deviation
(``ddof=0``, feature 80's convention); and the verdict is the same two-sided
level test against ``Φ⁻¹(1 − level/2) / √T``, because a Sharpe taken over ``T``
dates is standardized to the standard normal by ``√T`` whether the per-date
values came from re-dated returns or from re-labelled ones.  *Different
permutation*: what moves is not the calendar but the **labels** — the symbol
names — so the permutation is a **within-date derangement of each rebalance
date's joined cross-section**: on every date, each symbol's forward return is
handed to a different symbol, and no symbol keeps its own.

**Why that is a genuinely different probe, and not feature 125 restated.**  A
time shuffle moves *whole cross-sections* to other dates, so it destroys exactly
the date-aligned relationship between a score and the return it was scored
against while leaving every cross-section's *internal* structure — its
dispersion, its cross-symbol correlation, and above all the alphabet that pairs
a symbol with its own return *within that date* — untouched.  This probe destroys
precisely the other thing: it leaves every date where it was and breaks the
within-date alignment.  The two are therefore complementary rather than
redundant, and the complementarity is measurable rather than argued, on the two
canonical leaks:

* a **whole-sample per-symbol statistic** — each symbol's mean over the entire
  forward-return sample, held constant across dates (feature 133's planted
  corpus, in all four of its kinds) — is aligned with its symbol on every date,
  so re-labelling within a date destroys it, while re-dating cross-sections
  cannot.  Measured through feature 133's own corpus at the pinned defaults
  (120 dates, 30 symbols, seed 20260210), the four kinds figure ``0.064`` of
  this probe's bar — they **escape it flat**, having already been caught by
  feature 125 at ``2.24``;
* a **date-local cross-sectional statistic** — the date's own cross-sectional
  mean of its forward returns, the same value on every symbol — is a function of
  the date rather than of the symbol, so re-dating cross-sections cannot disturb
  it and re-labelling within a date destroys it.  Measured through the same
  probe it figures ``2.35`` (60 dates), ``2.99`` (120), ``4.55`` (240) and
  ``5.56`` (480) of the bar, and the growth is the bar's rather than the
  statistic's: the surviving Sharpe itself is flat in ``T`` (``0.78``, ``0.83``,
  ``0.74``, ``0.75`` at those widths — the date-local component is a single
  cross-sectional draw per date, so its per-date book return has a fixed
  dispersion) while the threshold falls as ``1/√T``.  Widening the grid
  therefore buys detection power against this leak linearly in ``√T``, which is
  why the measurements above widen with the grid at all.  Feature 125, by
  contrast, reads at most ``0.39`` of its own bar on the same panels: the leak
  **escapes feature 125** and is caught here.

Neither probe is the other's superset, and neither is the other's second
opinion: one asks *does the candidate know which date it is?*, the other *does it
know which symbol it is?*, and a leak has to answer one of those to leak at all.
That is what §C6 means by *"a second independent leakage probe"*, and it is why
this module is a second implementation of the *permutation* and not of anything
else.

**The two classes the corpus does not plant, stated because the corpus is a
closed vocabulary.**  Feature 133's ``LEAK_KINDS`` is deliberately the set of
leaks *feature 125's* bar is calibrated to catch — its own docstring says so, and
says why a corpus that planted leaks a probe is not supposed to catch would
assert a false guarantee.  The date-local class above is exactly such a leak for
feature 125, so the corpus omits it and this probe is the one that catches it;
and symmetrically the corpus's four kinds are leaks this probe escapes.  So the
"0 escapes" feature 133 asserts is a statement about the probe its
:meth:`~tripwires.corpus.CorpusSignal.run` runs — feature 125's — and the suite's
rejects the corpus through that probe and through the re-runs' own detections
(features 127 through 130, whose verdicts carry ``reference_rejected``), not
through this one.  This module states the measurement rather than inheriting a
guarantee it does not provide: widening the corpus to a leak class this probe
owns is feature 133's to do, and a corpus entry added from here would be a second
provenance for the vocabulary that feature pins.

**The derangement, and why it is a derangement again.**  Feature 125 draws a
fixed-point-free permutation of the dates because a date that happened to stay
put would leave that date's aligned pair — the very thing under test — intact by
luck of the draw.  The same argument runs one level down and is pinned the same
way: a symbol that kept its own forward return would leave its own aligned pair
in the cross-section, so within each date the labels are permuted *until no
symbol is fixed*, by rejection sampling from the same stream.  The guarantee is
what makes the probe's null airtight: under it, no aligned score-return pair
survives anywhere in the panel, so whatever the candidate still scores is
information it carries that does not depend on *which symbol carried which
return*.

**One derangement per date, drawn from one stream — and the tempting
alternative, measured rather than dismissed.**  Each date draws its own
permutation, because that is what makes this a within-date probe: a *single
global* relabelling shared by every date is a **symbol rename** rather than a
broken label pairing, and it hands the same two symbols to each other on all
``T`` dates, which is cross-date structure the per-date draw does not have.  It
is the tempting simplification (one permutation instead of ``T``, and it reads
naturally as "permute the labels"), and it is the wrong *definition* even where
it is not the weaker probe.  The honest measurement is that the two are close on
everything tried here: over 3000 null draws both calibrate to the nominal bar
(``0.0143`` per-date and ``0.0093`` global at 120 dates, ``0.0110`` and
``0.0097`` at 240), and a leak riding one symbol pair's within-date alignment
was detected by neither at either width (``0.013`` against ``0.013`` across 300
seeds at 120 dates).  So the choice rests on what the probe *is* — §C6's second
sentence permutes the labels of *the* cross-section the candidate was scored on,
one date at a time — and not on a power gap this module can claim; a global
renaming would be a different probe, and calling it the same one is what this
module declines to do.  The per-date draw is also what makes the seed an audit
handle: the whole pairing is a pure function of (sorted cross-sections, seed),
so a persisted rejection is rebuildable from the record's own terms, exactly as
feature 125's is.

**The verdict is a value, and its field names are feature 125's on purpose.**
``rejected`` and the §8 outcome word — ``tripwire_fail`` when rejected, ``ok``
when the probe states no failure — in the closed two-word slice of the trial
vocabulary a tripwire can speak, restated from
:data:`~tripwires.time_shuffle.TRIPWIRE_OUTCOMES` rather than re-spelled.  The
verdict carries ``surviving_sharpe``, ``threshold``, ``seed``, ``level``,
``horizon``, ``dates``, ``node_id``, ``tripwire``, ``rejected`` and ``outcome``
— **the ten names feature 131's structural check asks for**, and unlike feature
127's verdict (which deliberately renames them, because *its* rejection cause is
a different comparison) this one shares them because its rejection *is* the same
comparison: ``|surviving_sharpe| > threshold``, over this probe's own statistic.
So a label-permute failure is a failure feature 131 can poison a subtree on, and
the store's re-derivation of the decision is this probe's own arithmetic rather
than a borrowed one; ``tripwire`` (``"label-permute"``) is what tells a persisted
record *which* of step 10's probes fired, and ``pairing`` is a different shape
(``{date: {symbol: symbol}}`` rather than ``{date: date}``), so the two verdicts
cannot be confused by a reader who has both.  What this feature does *not* do is
write anything down: poisoning the node together with its subtree is feature 131,
the replay-pool excision feature 132, and the leaking corpus feature 133.

**Determinism, pinned twice over.**  The same panel, seed and level produce the
same verdict bit-for-bit: the dates are sorted before anything touches them and
each date's symbols are sorted before the draw (mapping order is insertion order,
and the determinism contract §12 does not trust it), and the permutation draws
only ``random.Random(seed).random()`` — the one primitive Python guarantees stable
across versions — assigning each symbol one uniform key and sorting by key, which
is a uniform permutation without ``random.shuffle``'s version-dependent integer
draws.  The rejection re-draw advances the same stream, so the pairing is a pure
function of (sorted cross-sections, seed).  A different seed is a different —
equally valid — probe, which is why the seed is carried *on the verdict*.

**The horizon policy, restated as the spec's rather than invented.**  The probe
runs on one target series, and the bundle step 4 aligned carries five, so the
policy is the one feature 125 pins and feature 80 pins for the metrics: the
shortest horizon :data:`~tripwires.time_shuffle.HORIZONS` names that the target
bundle actually covers — the fastest-turning horizon has the most rebalance dates
and so the largest ``T`` in the threshold's ``√T``, and "shortest covered" is a
function of the bundle rather than a caller's knob, so two deployments running
the same node return the same verdict.  The scan is spelled in
:func:`_resolve_horizon` rather than reached through feature 125's runner,
because *this* probe must refuse the panels *it* cannot measure: its measurability
is strictly stricter than the time shuffle's — a date needs two symbols for a
derangement to exist, where re-dating is content with one — so borrowing feature
125's runner to resolve the horizon would borrow its refusals, and a one-symbol
grid would come back as a measured verdict instead of a refusal.

**What this module does not do.**  It does not re-date cross-sections (feature
125), re-run candidates under perturbations (features 127 through 130), persist
anything (131, 132), maintain or widen the leaking corpus (133), or emit the
triage figure (134).  It does not re-implement the book, the Sharpe or the
threshold either: the statistic's arithmetic is spelled once here beside feature
125's because the *pairing it is read over* is different, and the threshold is a
delegation to :func:`~tripwires.time_shuffle.time_shuffle_threshold` for the
one-provenance reason :func:`~tripwires.window_offset.window_figure` delegates to
:func:`~tripwires.subsample.subsample_figure`.  It takes a score panel and a
target bundle and answers exactly the one question step 10 asks second: *does
this candidate still score against forward returns whose labels have been
permuted — and if it does, is that surviving Sharpe more than chance?*

**The layering note.**  This module is stdlib-only — dates, mappings, sorting,
``random``, square roots and one injected-by-construction seed; no polars, no
pyarrow, no lake, no environment, no HTTP, and no import of any other workspace
member.  The one import that crosses a sibling is
:mod:`tripwires.time_shuffle`, and it is deliberately narrow: the panel
validators (feature 75's absence rule, the finiteness and duplicate-bar refusals
spelled once beside the probe that owns them), the horizon set, the outcome
vocabulary and the threshold's closed form — the shared *arithmetic and
vocabulary* of step 10, never its shuffle.  The panels arrive as plain mappings
of plain floats, the shape every evaluator step past the materialization boundary
already speaks, so the tripwires member stays import-safe for the factory's scan,
the replay path, and the hash-pinned evaluator image this suite ships inside.
"""

from __future__ import annotations

import datetime as dt
import math
import random
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from .errors import TripwirePanelError, TripwireStatisticError
from .time_shuffle import (
    HORIZONS,
    TRIPWIRE_OUTCOMES,
    _panel_date,
    _validated_series,
    _validated_targets,
    time_shuffle_threshold,
)

__all__ = [
    "DEFAULT_LABEL_LEVEL",
    "DEFAULT_LABEL_SEED",
    "LABEL_PERMUTE_NAME",
    "LabelPermuteVerdict",
    "label_permute_pairing",
    "label_permute_threshold",
    "permuted_book_sharpe",
    "run_label_permute_tripwire",
]

#: The probe's own name, in §C6's and §6.1 step 10's spelling — the middle word
#: of ``time-shuffle, label-permute, perturbation stability``.  A verdict carries
#: it so a persisted failure (feature 131) can say *which* of step 10's probes
#: fired, and it is deliberately **not** :data:`~tripwires.time_shuffle.
#: TIME_SHUFFLE_NAME`: the two probes score against different permutations, and a
#: record that named both ``time-shuffle`` would make a label-permute rejection
#: indistinguishable from one the first probe stated.
LABEL_PERMUTE_NAME: str = "label-permute"

#: The default permutation seed.  Pinned to a fixed integer — rather than left to
#: follow :data:`~tripwires.time_shuffle.DEFAULT_SHUFFLE_SEED` — for the reason
#: the sibling axes pin theirs: the probe's value is partly its *repeatability*,
#: and sharing one integer between two probes would make this one's pairing a
#: function of the other's default, which is the coupling the member's
#: one-probe-per-file argument exists to avoid.  There is nothing special about
#: the value beyond being this probe's pinned draw; a deployment that wants a
#: different probe passes a different one.
DEFAULT_LABEL_SEED: int = 20260210

#: The default two-sided level of the surviving-Sharpe test — the nominal
#: false-alarm rate, the probability a clean node's surviving Sharpe exceeds the
#: threshold by chance.  Pinned at the same 0.01 as
#: :data:`~tripwires.time_shuffle.DEFAULT_SHUFFLE_LEVEL`, and pinned *here*
#: rather than imported from there, because the two numbers are two probes' false
#: alarm rates and not one shared constant: a deployment tightening the
#: time-shuffle bar (feature 127's configured thresholds are the precedent)
#: should not silently tighten the label-permute bar with it, and a single
#: imported constant could not express the difference.  Measured against this
#: probe's own null over 400 draws: 0.0075 at 60, 120 and 240 dates, 0.0100 at
#: 480 — and 0.0110 to 0.0143 over 3000 draws, so the nominal rate is right and
#: the 400-draw figures are themselves noisy.
DEFAULT_LABEL_LEVEL: float = 0.01


# -- The permutation -----------------------------------------------------------


def label_permute_pairing(
    cross_sections: Mapping[dt.date | str, Iterable[str]],
    *,
    seed: int = DEFAULT_LABEL_SEED,
) -> Mapping[dt.date, Mapping[str, str]]:
    """The within-date derangement of the labels — ``{date: {symbol: symbol}}``.

    ``cross_sections`` maps each rebalance date to the symbols its joined
    cross-section carries (the symbols *both* the scores and the targets hold,
    feature 75's absence rule); the result names, for each of those dates, which
    symbol receives which other symbol's forward return.  Every inner mapping
    is a permutation of that date's symbols with **no fixed point** — a symbol
    that kept its own return would leave its own aligned pair, the very thing
    under test, intact by luck of the draw, which is the argument feature 125
    applies to dates, applied here to labels.

    Each date draws its *own* permutation, in sorted date order, from one
    ``random.Random(seed)`` stream: each symbol draws one uniform key and
    sorting by key is a uniform permutation without ``random.shuffle``'s
    version-dependent integer draws; a draw that fixes any symbol is discarded
    and re-drawn from the same stream — rejection sampling — so the result is
    uniform over each date's derangements.  Deterministic in (sorted
    cross-sections, seed): the same inputs always return the same pairing,
    bit-for-bit, on any machine.  One permutation per date rather than one
    global relabelling is the probe's definition rather than a saving — see the
    module docstring for the measurement that falsifies the global variant.

    ``seed`` must be an integer that is not a ``bool``.  Every date must carry
    at least two *distinct* symbols, because a derangement of one symbol does
    not exist and a one-symbol cross-section is the identity by necessity —
    there is no permutation to be and no probe to state.
    """
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TripwirePanelError(
            f"the label permutation seed must be an integer, got {seed!r} "
            f"({type(seed).__name__}); the pairing is a pure function of the "
            "sorted cross-sections and the seed, and a non-integer seed names "
            "no stream to draw from"
        )
    if not isinstance(cross_sections, Mapping):
        raise TripwirePanelError(
            "the label permutation is drawn over a mapping of rebalance date "
            f"to the symbols that date's cross-section carries, got "
            f"{type(cross_sections).__name__}; a bare iterable is not a grid of "
            "cross-sections, and the permutation is per date"
        )
    if not cross_sections:
        raise TripwirePanelError(
            "the label permutation is drawn over at least one rebalance date "
            "with a cross-section, got none; a permuted label pairing over an "
            "empty panel is not a probe"
        )
    sections: dict[dt.date, tuple[str, ...]] = {}
    for key, symbols in cross_sections.items():
        day = _panel_date("label permutation grid", key)
        if day in sections:
            raise TripwirePanelError(
                f"the label permutation grid carries {day.isoformat()} twice "
                "under different spellings; one bar, one cross-section, and a "
                "permutation over a grid that carries a bar twice is not a "
                "relabelling of the panel the candidate was scored on"
            )
        if isinstance(symbols, (str, bytes)) or not hasattr(symbols, "__iter__"):
            raise TripwirePanelError(
                f"the cross-section on {day.isoformat()} must be an iterable "
                f"of symbol names, got {type(symbols).__name__}; a string would "
                "be iterated character by character"
            )
        seen: set[str] = set()
        for symbol in symbols:
            if not isinstance(symbol, str) or not symbol:
                raise TripwirePanelError(
                    f"the cross-section on {day.isoformat()} must be keyed by "
                    f"non-empty symbol names, got {symbol!r}"
                )
            if symbol in seen:
                raise TripwirePanelError(
                    f"the cross-section on {day.isoformat()} carries the "
                    f"symbol {symbol!r} twice; a permutation assigns each "
                    "symbol exactly one return, and a cross-section that names "
                    "one twice has no permutation to be"
                )
            seen.add(symbol)
        if len(seen) < 2:
            raise TripwirePanelError(
                f"the cross-section on {day.isoformat()} carries "
                f"{len(seen)} symbol(s); permuting labels within a date needs "
                "at least two, because a one-symbol permutation is the identity "
                "and leaves that symbol's aligned pair — the very thing under "
                "test — intact, so there is no probe to state"
            )
        sections[day] = tuple(sorted(seen))
    rng = random.Random(seed)
    drawn: dict[dt.date, Mapping[str, str]] = {}
    for day in sorted(sections):
        symbols = sections[day]
        while True:
            keys = {symbol: rng.random() for symbol in symbols}
            shuffled = sorted(symbols, key=lambda symbol: keys[symbol])
            if all(source != moved for source, moved in zip(symbols, shuffled)):
                drawn[day] = MappingProxyType(dict(zip(symbols, shuffled)))
                break
    return MappingProxyType(drawn)


# -- The statistic and the threshold -------------------------------------------


def label_permute_threshold(
    dates: int, *, level: float = DEFAULT_LABEL_LEVEL
) -> float:
    """The surviving-Sharpe rejection threshold for ``dates`` measured dates.

    ``Φ⁻¹(1 − level/2) / √dates`` — a **delegation** to
    :func:`~tripwires.time_shuffle.time_shuffle_threshold`, not a second
    implementation of the closed form, for the one-provenance reason
    :func:`~tripwires.window_offset.window_figure` delegates to
    :func:`~tripwires.subsample.subsample_figure`: one arithmetic, one home.

    The delegation is not a convenience — the two probes genuinely share the
    bar.  Feature 125's threshold standardizes a Sharpe taken over ``T``
    rebalance dates by ``√T``, which is exact when the per-date book returns are
    independent and near-Gaussian; this probe's per-date values are also one
    independent draw per date (each date's labels are permuted independently of
    every other date's), so its Sharpe standardizes the same way.  Measured
    against this probe's own null: 0.0143 at 120 dates and 0.0110 at 240 over
    3000 draws, against the nominal 0.01.

    The two-sided form is the same choice feature 125 makes and for the same
    reason: leakage is sign-agnostic, and a candidate that systematically
    *anti*-tracks the permuted labels carries exactly the same marginal
    information as one that tracks them, so a one-sided probe would let the
    sign-flipped leak through.
    """
    return time_shuffle_threshold(dates, level=level)


def permuted_book_sharpe(
    scores: Mapping[dt.date | str, Mapping[str, float]],
    targets: Mapping[dt.date | str, Mapping[str, float]],
    pairing: Mapping[dt.date, Mapping[str, str]],
) -> float:
    """The candidate's Sharpe against the label-permuted panel — the statistic.

    Per date in the pairing: the score-weighted unit book's return, the mean
    over the date's joined cross-section (feature 75's absence rule) of
    ``score × forward return``, where each symbol's return is the one its
    *permuted* label received — the return the derangement handed it.  Then the
    Sharpe of that per-date series: mean over population standard deviation
    (``ddof=0``, feature 80's convention), the same arithmetic feature 125's
    ``surviving_sharpe`` states for the re-dated panel.  ``scores`` and
    ``targets`` are single-horizon panels ``{date: {symbol: value}}``; the
    scores are step 3's normalized output and are consumed as-is
    (re-normalizing would be a second implementation of feature 74, and the
    ratio is scale-invariant).

    The statistic's arithmetic is spelled here rather than reached through
    feature 125's function because the *pairing* is read differently — that one
    looks up a whole other date's cross-section, this one looks up a symbol
    within the same date — and passing a label pairing to that function would
    have to fail rather than silently read the wrong panel.  What is *not*
    re-spelled is anything under the division: the join, the absence rule, the
    finiteness refusals and the population dispersion convention are the
    member's, taken from the module that owns them.

    The pairing must be a derangement per date whose dates are exactly the ones
    both panels carry, whose every inner mapping covers exactly that date's
    joined cross-section, and whose every joined cross-section is non-empty —
    the runner guarantees all four, and a hand-built pairing that violates any
    is refused, because a statistic measured over a pairing with a fixed point,
    a missing symbol or an empty join is a statistic the probe never defined.
    Zero dispersion across the measured dates refuses rather than dividing by
    zero (:class:`~tripwires.TripwireStatisticError`).
    """
    score_panel = _validated_series("scores", scores)
    target_panel = _validated_series("targets", targets)
    if not isinstance(pairing, Mapping):
        raise TripwirePanelError(
            "the pairing must map rebalance date to {symbol: symbol}, got "
            f"{type(pairing).__name__} — pass label_permute_pairing's result"
        )
    shared = sorted(set(score_panel) & set(target_panel))
    captured: dict[dt.date, Mapping[str, str]] = {}
    for source, moved in pairing.items():
        if not isinstance(source, dt.date) or isinstance(source, dt.datetime):
            raise TripwirePanelError(
                f"the pairing must be keyed by calendar dates, got {source!r}"
            )
        if not isinstance(moved, Mapping):
            raise TripwirePanelError(
                f"the pairing for {source.isoformat()} must map symbol to "
                f"symbol, got {type(moved).__name__}; a label permutation "
                "moves the labels within one date, and a value that is not a "
                "mapping names no relabelling of that date's cross-section"
            )
        captured[source] = moved
    if set(captured) != set(shared):
        raise TripwirePanelError(
            "the pairing must cover exactly the dates both panels carry "
            f"({len(shared)} shared, pairing covers {len(captured)}); a "
            "statistic measured over any other grid is a statistic the probe "
            "never defined"
        )
    per_date: list[float] = []
    for day in shared:
        common = set(score_panel[day]) & set(target_panel[day])
        if not common:
            raise TripwirePanelError(
                f"the joined cross-section on {day.isoformat()} is empty — "
                "the scores and the returns share no symbol, so the date "
                "measured nothing"
            )
        if len(common) < 2:
            raise TripwirePanelError(
                f"the joined cross-section on {day.isoformat()} carries "
                f"{len(common)} symbol; permuting labels within a date needs at "
                "least two, because a one-symbol permutation is the identity "
                "and leaves that symbol's aligned pair intact — the runner "
                "excludes such dates before pairing, and a pairing that "
                "includes one was built somewhere other than this module"
            )
        moved = captured[day]
        if set(moved) != common:
            raise TripwirePanelError(
                f"the pairing for {day.isoformat()} covers {len(moved)} "
                f"symbol(s) and the joined cross-section carries {len(common)}; "
                "a permutation of one date's labels assigns exactly that "
                "date's symbols, and a pairing that covers any other set is "
                "one the probe never defined"
            )
        if set(moved.values()) != common:
            raise TripwirePanelError(
                f"the pairing for {day.isoformat()} is not a permutation of "
                "its cross-section: its keys and its values are different "
                "symbol sets, so some symbol's return was handed out twice and "
                "another's not at all"
            )
        fixed = sorted(symbol for symbol, other in moved.items() if symbol == other)
        if fixed:
            raise TripwirePanelError(
                f"the pairing fixes {', '.join(fixed)} on {day.isoformat()}; a "
                "derangement moves every label, and a fixed point leaves that "
                "symbol's aligned pair — the very thing under test — intact, "
                "so the probe's null is only airtight over a derangement"
            )
        per_date.append(
            math.fsum(
                score_panel[day][symbol] * target_panel[day][moved[symbol]]
                for symbol in common
            )
            / len(common)
        )
    count = len(per_date)
    mean = math.fsum(per_date) / count
    variance = math.fsum((value - mean) ** 2 for value in per_date) / count
    deviation = math.sqrt(variance)
    if deviation == 0.0:
        raise TripwireStatisticError(
            "the score-weighted book returned the same value against the "
            "label-permuted panel on every measured date, so its dispersion is "
            "zero and the surviving Sharpe is undefined; refusing rather than "
            "dividing by zero — a candidate that never varied across dates has "
            "no reward-to-variance ratio for the probe to read"
        )
    return mean / deviation


# -- The verdict ---------------------------------------------------------------


@dataclass(frozen=True)
class LabelPermuteVerdict:
    """Step 10's second answer — the label-permute probe's verdict, with its evidence.

    The record feature 126 states and the persistence features consume: a
    failure here is a failure feature 131 can poison a node and its subtree from,
    a branch feature 132 excises from the replay pool, and a verdict feature 133's
    corpus asserts its own probe's rejects against.  Every term the verdict was
    computed from is carried on it — the seed and level rebuild the pairing and
    the threshold, the pairing itself is the evidence the derangement property
    holds date by date, and the statistic sits beside the threshold it was judged
    against — because a rejection that poisons a subtree is an irreversible act
    and must be auditable from the record alone, the same reason feature 125's
    verdict carries its own terms.

    **The ten terms are feature 125's names, and that is a decision rather than a
    drift.**  Feature 131 checks a verdict *structurally* — by the ten field names
    a poisoning reads — because the factory's scan gives one source file two
    class objects and ``isinstance`` cannot hold across them, and its own
    comparison is ``|surviving_sharpe| > threshold``.  That comparison is *this*
    probe's comparison too: a label-permute rejection is stated by the same
    two-sided test over a Sharpe of the same book, read against a differently
    permuted panel.  So the names are shared and the re-derivation feature 131
    performs on this record is this probe's own arithmetic.  (Feature 127's
    verdict deliberately renames them, from the other side of the same argument:
    its rejection cause is the *degradation*, so a shared name would have the
    store judge it on a comparison it did not make.)  What keeps the two records
    apart is :attr:`tripwire`, which names the probe, and :attr:`pairing`, whose
    shape is a relabelling per date rather than a re-dating of dates.

    The invariants are enforced at construction, so a record built by hand — or by
    a later feature whose producer drifted — fails loudly rather than carrying a
    lying verdict: ``rejected`` must equal the comparison the statistic and the
    threshold actually make, the outcome word must be the verdict's own
    translation into §8's vocabulary, the threshold must recompute from the level
    and the date count, and the pairing must be a derangement of each measured
    date's labels.
    """

    #: The node whose candidate was probed.
    node_id: str
    #: The probe's name — always :data:`LABEL_PERMUTE_NAME`; carried so a
    #: persisted failure names which of step 10's probes fired.
    tripwire: str
    #: The horizon whose target series was probed — the shortest the bundle
    #: covered, per the member's pinned policy.
    horizon: int
    #: How many rebalance dates the probe measured — the ``T`` behind the
    #: threshold's ``√T``.
    dates: int
    #: The seed the permutation was drawn from — carried so the pairing, and
    #: therefore the whole verdict, is reproducible from the record.
    seed: int
    #: The two-sided level the threshold was taken at.
    level: float
    #: The Sharpe of the score-weighted book against the label-permuted panel.
    surviving_sharpe: float
    #: The rejection threshold — ``Φ⁻¹(1 − level/2) / √dates``.
    threshold: float
    #: The verdict: ``True`` when the surviving Sharpe indicates leakage and the
    #: node is rejected.
    rejected: bool
    #: The verdict in §8's trial vocabulary — ``tripwire_fail`` when rejected,
    #: ``ok`` when the probe states no failure.
    outcome: str
    #: The label derangement the probe scored against — ``{date: {symbol:
    #: symbol}}``, every symbol moved within its own date.
    pairing: Mapping[dt.date, Mapping[str, str]]

    def __post_init__(self) -> None:
        # object.__setattr__ where the constructor normalizes; this record
        # validates only, like the records it sits beside.
        if not isinstance(self.node_id, str) or not self.node_id.strip():
            raise TripwirePanelError(
                "a label-permute verdict must name the node whose candidate it "
                f"probed, got {self.node_id!r}"
            )
        if self.tripwire != LABEL_PERMUTE_NAME:
            raise TripwirePanelError(
                f"a label-permute verdict's tripwire is "
                f"{LABEL_PERMUTE_NAME!r}, got {self.tripwire!r}; the record "
                "names which probe fired, and a second spelling is a second "
                "probe"
            )
        if isinstance(self.horizon, bool) or not isinstance(self.horizon, int):
            raise TripwirePanelError(
                f"a label-permute verdict's horizon must be an integer period "
                f"count, got {self.horizon!r}"
            )
        if self.horizon not in HORIZONS:
            raise TripwirePanelError(
                f"horizon {self.horizon} is not one of the horizons the spec "
                f"names ({', '.join(str(h) for h in HORIZONS)})"
            )
        if isinstance(self.dates, bool) or not isinstance(self.dates, int):
            raise TripwirePanelError(
                f"a label-permute verdict's date count must be an integer, got "
                f"{self.dates!r}"
            )
        if self.dates < 2:
            raise TripwirePanelError(
                f"a label-permute verdict measures at least two dates, got "
                f"{self.dates}; below that there is no dispersion and no "
                "threshold, and a verdict over one date states a probe that "
                "never ran"
            )
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise TripwirePanelError(
                f"a label-permute verdict's seed must be an integer, got "
                f"{self.seed!r}"
            )
        for field in ("level", "surviving_sharpe", "threshold"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TripwirePanelError(
                    f"a label-permute verdict's {field} must be a number, got "
                    f"{value!r}"
                )
            if not math.isfinite(float(value)):
                raise TripwirePanelError(
                    f"a label-permute verdict's {field} is not finite "
                    f"({value!r}); a NaN or ±inf would reach the node record "
                    "dressed as a measurement"
                )
            object.__setattr__(self, field, float(value))
        if not 0.0 < self.level < 1.0:
            raise TripwirePanelError(
                f"a label-permute verdict's level is a false-alarm rate "
                f"strictly inside (0, 1), got {self.level!r}"
            )
        if not isinstance(self.rejected, bool):
            raise TripwirePanelError(
                f"a label-permute verdict's rejection is a boolean, got "
                f"{self.rejected!r}"
            )
        if self.threshold <= 0.0:
            raise TripwirePanelError(
                f"a label-permute verdict's threshold is positive, got "
                f"{self.threshold!r}"
            )
        expected_threshold = label_permute_threshold(self.dates, level=self.level)
        if self.threshold != expected_threshold:
            raise TripwirePanelError(
                f"the label-permute verdict says its threshold is "
                f"{self.threshold!r} but level {self.level!r} over "
                f"{self.dates} dates standardizes to {expected_threshold!r}; "
                "the record disagrees with its own arithmetic — a threshold no "
                "reader can recompute is a threshold no rejection can be "
                "audited against"
            )
        if self.rejected != (abs(self.surviving_sharpe) > self.threshold):
            raise TripwirePanelError(
                f"the label-permute verdict says rejected={self.rejected!r} "
                f"but its own terms decide otherwise "
                f"(|{self.surviving_sharpe!r}| vs {self.threshold!r}); the "
                "record disagrees with itself, so it was built somewhere other "
                "than this module's arithmetic — a verdict the node record "
                "would trust and be wrong by"
            )
        if self.outcome not in TRIPWIRE_OUTCOMES:
            raise TripwirePanelError(
                f"a label-permute verdict's outcome is one of "
                f"{', '.join(TRIPWIRE_OUTCOMES)} (§8's vocabulary), got "
                f"{self.outcome!r}"
            )
        expected_outcome = "tripwire_fail" if self.rejected else "ok"
        if self.outcome != expected_outcome:
            raise TripwirePanelError(
                f"the label-permute verdict says rejected={self.rejected!r} "
                f"but carries outcome {self.outcome!r}; the outcome word is the "
                "verdict's own translation into the trial vocabulary, and the "
                "two spellings of one fact cannot disagree"
            )
        if not isinstance(self.pairing, Mapping):
            raise TripwirePanelError(
                "a label-permute verdict's pairing maps rebalance date to "
                f"{{symbol: symbol}}, got {type(self.pairing).__name__}"
            )
        captured: dict[dt.date, Mapping[str, str]] = {}
        for source, moved in self.pairing.items():
            if not isinstance(source, dt.date) or isinstance(source, dt.datetime):
                raise TripwirePanelError(
                    f"the verdict's pairing is keyed by calendar dates, got "
                    f"{source!r}"
                )
            if not isinstance(moved, Mapping):
                raise TripwirePanelError(
                    f"the verdict's pairing for {source.isoformat()} maps "
                    f"symbol to symbol, got {type(moved).__name__}"
                )
            labels: dict[str, str] = {}
            for symbol, other in moved.items():
                if not isinstance(symbol, str) or not symbol:
                    raise TripwirePanelError(
                        f"the verdict's pairing for {source.isoformat()} is "
                        f"keyed by non-empty symbol names, got {symbol!r}"
                    )
                if not isinstance(other, str) or not other:
                    raise TripwirePanelError(
                        f"the verdict's pairing for {source.isoformat()} sends "
                        f"{symbol!r} to a non-symbol {other!r}"
                    )
                if symbol == other:
                    raise TripwirePanelError(
                        f"the verdict's pairing fixes {symbol!r} on "
                        f"{source.isoformat()}; a derangement moves every label, "
                        "and a fixed point is an aligned pair the permutation "
                        "left intact"
                    )
                labels[symbol] = other
            if set(labels) != set(labels.values()):
                raise TripwirePanelError(
                    f"the verdict's pairing for {source.isoformat()} is not a "
                    "permutation: its keys and its values are different symbol "
                    "sets, so some symbol's return was handed out twice and "
                    "another's not at all"
                )
            captured[source] = MappingProxyType(labels)
        if len(captured) != self.dates:
            raise TripwirePanelError(
                f"the label-permute verdict claims {self.dates} measured dates "
                f"but its pairing carries {len(captured)}; the count is the T "
                "behind the threshold's √T, and a record whose denominator "
                "disagrees with its own evidence is a record no reader can size"
            )
        object.__setattr__(self, "pairing", MappingProxyType(captured))

    def __hash__(self) -> int:
        # The nested mapping is not hashable until it collapses to tuples; the
        # fold keeps __hash__ consistent with __eq__, as every record in this
        # workspace does.
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
                tuple(
                    sorted(
                        (day, tuple(sorted(labels.items())))
                        for day, labels in self.pairing.items()
                    )
                ),
            )
        )

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"LabelPermuteVerdict(node={self.node_id!r}, "
            f"horizon={self.horizon}, {self.dates} dates, "
            f"surviving_sharpe={self.surviving_sharpe:+.4f}, "
            f"threshold={self.threshold:.4f}, "
            f"outcome={self.outcome!r})"
        )


# -- The probe -----------------------------------------------------------------


def _resolve_horizon(
    score_panel: Mapping[dt.date, Mapping[str, float]],
    bundle: Mapping[int, Mapping[dt.date, Mapping[str, float]]],
) -> int:
    """The shortest horizon the bundle covers that shares a date with the scores.

    The member's pinned policy, spelled here because *this* probe must refuse the
    panels *it* cannot measure rather than inherit feature 125's refusals — see
    the module docstring's horizon paragraph.  The scan is the policy itself:
    :data:`~tripwires.time_shuffle.HORIZONS` ascending, first hit wins, so the
    fastest-turning horizon with coverage is the one probed and the choice is a
    function of the bundle rather than of a caller's knob.
    """
    for candidate in HORIZONS:
        series = bundle.get(candidate)
        if series and set(series) & set(score_panel):
            return candidate
    raise TripwirePanelError(
        "the target bundle shares no horizon with the scores at any of the "
        f"horizons the spec names ({', '.join(str(h) for h in HORIZONS)}), so "
        "no forward return can be paired with a score and there is no probe to "
        "state — align and gate a bundle with coverage first (features 75 and 76)"
    )


def run_label_permute_tripwire(
    scores: Mapping[dt.date | str, Mapping[str, float]],
    targets: Mapping[int, Mapping[dt.date | str, Mapping[str, float]]],
    *,
    node_id: str,
    seed: int = DEFAULT_LABEL_SEED,
    level: float = DEFAULT_LABEL_LEVEL,
) -> LabelPermuteVerdict:
    """Run the label-permutation tripwire and state the verdict — feature 126.

    The probe, in order: resolve the probe horizon (the shortest horizon
    :data:`~tripwires.time_shuffle.HORIZONS` names whose target series shares a
    date with the scores — the member's pinned shortest-covered policy); join the
    two panels onto their shared rebalance dates, keeping the dates whose joined
    cross-section carries at least two symbols, since that is what this probe
    needs to permute; draw the per-date label derangement over those dates from
    ``seed``; score the candidate's score-weighted book against the permuted
    panel; and state the verdict against ``Φ⁻¹(1 − level/2) / √T``, two-sided,
    rejecting the node when the surviving Sharpe indicates leakage.

    Deterministic in (``scores``, ``targets``, ``seed``, ``level``) — the same
    candidate probed twice returns the same verdict, bit-for-bit, which is what a
    persisted, subtree-poisoning rejection must be reproducible from.

    Raises :class:`~tripwires.TripwirePanelError` for a malformed panel, a bundle
    that shares no horizon with the scores, fewer than two measurable rebalance
    dates (a date whose join carries two or more symbols), or a pairing whose
    joined cross-section is empty or one-symbol on some date;
    :class:`~tripwires.TripwireStatisticError` when the measured per-date returns
    never vary.  A *detected leak is not an exception* — it is the verdict's
    ``rejected`` — because a tripwire that raised on detection would be
    indistinguishable, at the ledger, from one that crashed.
    """
    if not isinstance(node_id, str) or not node_id.strip():
        raise TripwirePanelError(
            f"the tripwire must name the node it probes, got {node_id!r}; a "
            "verdict that rejects a node it cannot name is a rejection nothing "
            "downstream can attribute"
        )
    score_panel = _validated_series("scores", scores)
    if not score_panel:
        raise TripwirePanelError(
            "the scores carry no rebalance date with a cross-section, so there "
            "is no candidate to probe — a tripwire that 'passed' a node it "
            "never measured is the failure this category exists to prevent"
        )
    bundle = _validated_targets(targets)
    horizon = _resolve_horizon(score_panel, bundle)
    target_panel = bundle[horizon]

    # A date is measurable here only when its joined cross-section carries two
    # or more symbols — strictly stricter than feature 125, whose derangement
    # moves whole cross-sections and is content with one symbol in them.
    measurable = sorted(
        day
        for day in set(score_panel) & set(target_panel)
        if len(set(score_panel[day]) & set(target_panel[day])) >= 2
    )
    if len(measurable) < 2:
        raise TripwirePanelError(
            f"the scores and the horizon-{horizon} targets share "
            f"{len(measurable)} rebalance date(s) whose joined cross-section "
            "carries two or more symbols, and a label permutation needs at "
            "least two: a one-date permutation has no dispersion to take a "
            "Sharpe over, and a one-symbol cross-section has no derangement to "
            "be"
        )

    pairing = label_permute_pairing(
        {day: sorted(set(score_panel[day]) & set(target_panel[day])) for day in measurable},
        seed=seed,
    )
    sharpe = permuted_book_sharpe(score_panel, target_panel, pairing)
    dates = len(measurable)
    threshold = label_permute_threshold(dates, level=level)
    rejected = abs(sharpe) > threshold
    return LabelPermuteVerdict(
        node_id=node_id,
        tripwire=LABEL_PERMUTE_NAME,
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
