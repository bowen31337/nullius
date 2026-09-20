"""The planted-leak corpus — feature 133.

app_spec.xml, "Leakage Tripwires", feature 133: *"System maintains a corpus
of deliberately leaking signals that every tripwire must catch, which returns
0 escapes in the suite."*  It depends on feature 125 (the time-shuffle probe),
and it is the ground the whole "Leakage Tripwires" category stands on: a
tripwire suite that rejects nothing is indistinguishable from one that is
broken, so the category keeps a set of *known leaks* — score panels built to
carry information a time shuffle cannot destroy — and asserts, as a single
unblinking fact, that every one of them is caught.  Zero escapes is the bar,
and it is the bar precisely because the signals are planted, not discovered:
the corpus is the adversary's own playbook, and a probe that lets any of it
through has silently stopped probing.

**What a corpus signal is, and what it is not.**  Each signal is a *planted
leak*: a score panel built deterministically from a target bundle so that the
score carries a statistic of the *whole* forward-return sample — the very
thing feature 125's derangement is designed to leave standing.  The mechanism
is pinned in the module's own leak vocabulary (:data:`LEAK_KINDS`): the
canonical full-sample symbol mean, its sign-flipped mirror, the full-sample
per-symbol t-statistic, and that t-statistic's sign-flip.  Each is a distinct
way of leaking, so the corpus tests the probe against a *spread* of leaks
rather than one leak restated; but each is also, at root, the same idea — a
date-independent panel statistic — which is why the corpus can assert 0
escapes rather than merely "most".  A signal is *not* a clean candidate and
*not* a borderline one: it is a deliberate, unambiguous leak, and the corpus
is the wrong place for a signal whose detection depends on the seed or the
grid — such a signal would make the suite's central guarantee flaky, and a
flaky tripwire test is no test of a tripwire at all.

**The discrimination note, stated because the corpus could have been
larger.**  Not every plausible-looking leak survives the shuffle, and that is
a feature of the probe rather than a gap in the corpus.  A score built from a
*median* or a *linear slope* of the sample — or from only *part* of the sample
(half the dates) — escapes: those statistics do not compound into the
per-date mean-of-products the surviving Sharpe reads, so re-dating the
cross-sections does leave them standing in the way the mean does.  The corpus
deliberately omits them, not out of ignorance but because a corpus that
planted leaks the probe is *not supposed to catch* would be a corpus that
asserted a false guarantee.  The four signals kept are exactly the ones whose
leakage the two-sided √T test is calibrated to detect, verified across grid
sizes and seeds; the ones dropped are the control that proves the probe
discriminates rather than merely rejects.  The corpus is the set of leaks a
*correct* tripwire catches — no more, no less.

**Determinism, and the corpus's one seed.**  The corpus is built once, at
import, from :data:`CORPUS_SEED` — a fixed integer, for the same repeatability
reason feature 125 pins its shuffle seed: the suite that asserts 0 escapes
must assert it against the *same* planted panels every run, on every machine,
or the guarantee is a roll of the dice.  The grid (feature 125's own
leak-verification width, 120 dates of 30 symbols) and the seed are the
corpus's two fixed facts; change either and you have a different corpus,
which is why both are pinned as module constants rather than threaded as
arguments.  The panels are plain mappings of plain floats — the shape every
evaluator step past the materialization boundary already speaks — so the
corpus stays import-safe for the frozen evaluator image this suite ships
inside, and the member stays stdlib-only.

**What this module does not do.**  It does not run the probe (that is the
suite's job, and :meth:`CorpusSignal.run` is the one seam it offers for it);
it does not persist the signals or their verdicts (features 131 and 132 own
persistence, and a corpus entry is a value, not a row); it does not widen the
leak vocabulary or the horizon set (those are the spec's, closed); and it
does not plant a clean candidate (a clean candidate is not a leak, and
including one would turn "0 escapes" into a statement about a signal the
corpus was never about).  It maintains the corpus, and nothing more.
"""

from __future__ import annotations

import datetime as dt
import math
import random
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from .time_shuffle import (
    HORIZONS,
    TimeShuffleVerdict,
    run_time_shuffle_tripwire,
)

__all__ = [
    "CORPUS_GRID",
    "CORPUS_SEED",
    "CORPUS_SYMBOLS",
    "LEAK_KINDS",
    "CorpusSignal",
    "planted_signals",
]

#: The rebalance grid the corpus is planted on — feature 125's own
#: leak-verification width. Named so the corpus says "the probe's own
#: verification width" rather than restating the number, and kept equal to it
#: so the corpus is scored on exactly the grid the probe was verified against.
CORPUS_GRID: int = 120

#: The symbol count the corpus is planted on — likewise feature 125's own
#: leak-verification width, and kept equal to it for the same reason.
CORPUS_SYMBOLS: int = 30

#: The seed the corpus's planted panels are drawn from. Fixed, for the same
#: repeatability reason feature 125 pins its shuffle seed: the suite that
#: asserts 0 escapes must assert it against the same planted panels every run.
CORPUS_SEED: int = 20260113

#: The leak mechanisms the corpus plants — the probe's own leak vocabulary,
#: closed. Each is a distinct way of leaking a whole-sample statistic; each is
#: caught by the two-sided √T test. A leak kind outside this set is a leak the
#: corpus does not plant, and the suite does not assert on it.
LEAK_KINDS: tuple[str, ...] = (
    "full_sample_mean",
    "full_sample_mean_negated",
    "full_sample_tstat",
    "full_sample_tstat_negated",
)


def _grid() -> list[dt.date]:
    """The corpus's rebalance grid — ``CORPUS_GRID`` consecutive dates."""
    return [
        dt.date(2024, 1, 1) + dt.timedelta(days=offset) for offset in range(CORPUS_GRID)
    ]


def _symbols() -> list[str]:
    """The corpus's symbol names — ``CORPUS_SYMBOLS`` of them, in a fixed order."""
    return [f"S{index:02d}" for index in range(CORPUS_SYMBOLS)]


def _target_bundle(seed: int) -> dict[int, dict[dt.date, dict[str, float]]]:
    """The corpus's forward-return bundle — one series per horizon, of normals.

    Independent across dates *and* symbols, so the bundle carries no
    information of its own: whatever a planted score panel built from it
    carries is the leak, not the market. All five spec horizons are covered —
    the probe resolves its horizon to the shortest (feature 125's pinned
    policy), but the bundle carries the full set so a signal's ``horizon``
    field names the horizon it was scored against, not merely the one the
    probe happened to pick.
    """
    rng = random.Random(seed)
    dates = _grid()
    names = _symbols()
    return {
        horizon: {day: {name: rng.gauss(0.0, 1.0) for name in names} for day in dates}
        for horizon in HORIZONS
    }


def _full_sample_mean(
    series: Mapping[dt.date, Mapping[str, float]],
) -> dict[str, float]:
    """The canonical leak statistic — each symbol's mean over the whole sample.

    A score panel constant across dates at this value carries the whole
    sample's returns into every cross-section, so re-dating the cross-sections
    (what the time shuffle does) cannot disturb it: whatever survives the
    shuffle is the panel-level information the score was never supposed to
    see. This is the leak feature 125's docstring names as verified, and the
    seed from which the others in the corpus grow.
    """
    days = sorted(series)
    return {
        name: math.fsum(series[day][name] for day in days) / len(days)
        for name in series[days[0]]
    }


def _full_sample_tstat(
    series: Mapping[dt.date, Mapping[str, float]],
) -> dict[str, float]:
    """A normalized leak statistic — each symbol's mean over its sample std.

    The same whole-sample information as the mean, but standardized per
    symbol, so the leak is a *t-statistic* rather than a raw mean. It is a
    monotonic re-scaling of the mean across symbols only in the limit of equal
    dispersion; in general it is a distinct panel, which is why the corpus
    plants both — a probe that caught the mean but missed its normalized
    cousin would be a probe tuned to one leak's arithmetic rather than to
    leakage itself.
    """
    days = sorted(series)
    statistic: dict[str, float] = {}
    for name in series[days[0]]:
        column = [series[day][name] for day in days]
        mean = math.fsum(column) / len(column)
        dispersion = math.sqrt(
            math.fsum((value - mean) ** 2 for value in column) / len(column)
        )
        statistic[name] = mean / dispersion if dispersion != 0.0 else 0.0
    return statistic


#: The corpus's per-kind statistic builders. Each takes the target series and
#: returns ``{symbol: leaked score}``; the score panel is that statistic held
#: constant across dates (the date-independence is the leak). The ``_negated``
#: kinds carry the sign-flipped statistic, which is the same information with
#: the opposite sign — the reason the probe's test is two-sided, and the
#: reason the corpus plants the mirror rather than assuming it.
_STATISTICS: dict[
    str, Callable[[Mapping[dt.date, Mapping[str, float]]], dict[str, float]]
] = {
    "full_sample_mean": _full_sample_mean,
    "full_sample_mean_negated": lambda series: {
        name: -value for name, value in _full_sample_mean(series).items()
    },
    "full_sample_tstat": _full_sample_tstat,
    "full_sample_tstat_negated": lambda series: {
        name: -value for name, value in _full_sample_tstat(series).items()
    },
}

#: One-line statement of the leakage mechanism each kind plants — carried on
#: the signal so the corpus is self-describing: a reader facing a persisted
#: rejection names not just *that* a leak fired but *which* planted leak it
#: was, and why it leaks.
_DESCRIPTIONS: dict[str, str] = {
    "full_sample_mean": (
        "score carries each symbol's mean over the whole forward-return "
        "sample — the canonical lookahead a time shuffle cannot disturb"
    ),
    "full_sample_mean_negated": (
        "the sign-flipped full-sample mean — the same leak anti-tracking the "
        "shuffled panel, caught only because the test is two-sided"
    ),
    "full_sample_tstat": (
        "score carries each symbol's full-sample mean over its own dispersion "
        "— the same whole-sample information, standardized per symbol"
    ),
    "full_sample_tstat_negated": (
        "the sign-flipped full-sample t-statistic — the normalized leak "
        "anti-tracking the shuffled panel"
    ),
}


@dataclass(frozen=True)
class CorpusSignal:
    """One planted leak in the corpus — a score panel built to leak.

    Feature 133's unit: a score panel and the target bundle it was planted
    from, a node id to reject, the leak mechanism (:data:`LEAK_KINDS`) and the
    horizon the probe resolves to. It is a *value* — frozen, self-describing —
    so the suite that asserts 0 escapes asserts against a fixed, auditable
    artifact rather than a re-run. :meth:`run` is the one seam it offers: it
    hands the planted panels to feature 125's probe and returns the verdict,
    so the audit path (run the planted leak, check it is rejected) is the
    probe path.
    """

    #: The node the planted leak is attributed to — the id the probe rejects.
    node_id: str
    #: The leak mechanism — one of :data:`LEAK_KINDS`.
    leak_kind: str
    #: One-line statement of *why* this panel leaks, for an auditable corpus.
    description: str
    #: The horizon the probe resolves the signal's bundle to.
    horizon: int
    #: The planted score panel — ``{date: {symbol: leaked score}}``.
    scores: Mapping[dt.date, Mapping[str, float]]
    #: The target bundle the scores were planted from — ``{horizon: series}``.
    targets: Mapping[int, Mapping[dt.date, Mapping[str, float]]]

    def run(self) -> TimeShuffleVerdict:
        """Run the probe against this planted leak — the audit path.

        Hands the planted panels to feature 125's time-shuffle probe with this
        signal's node id, and returns the verdict. A corpus signal is a
        *known leak*, so the verdict's ``rejected`` is expected to be ``True``
        and its ``outcome`` ``tripwire_fail`` — the suite asserts exactly that,
        and a signal for which it is not true is a corpus entry that has
        stopped leaking, which is the failure feature 133 exists to surface.
        """
        return run_time_shuffle_tripwire(
            self.scores, self.targets, node_id=self.node_id
        )


def planted_signals() -> tuple[CorpusSignal, ...]:
    """The corpus — every planted leak signal, as a fixed tuple.

    Built once from :data:`CORPUS_SEED` at call time: one target bundle, and
    for each leak kind in :data:`LEAK_KINDS` one signal whose score panel is
    that kind's whole-sample statistic held constant across dates. Returns a
    tuple, not a generator — the corpus is a closed, countable set, and the
    suite that asserts 0 escapes iterates it as a whole. The order is the
    leak-vocabulary order, so the corpus reads as the probe's own leak
    taxonomy rather than an arbitrary listing.
    """
    bundle = _target_bundle(CORPUS_SEED)
    series = bundle[HORIZONS[0]]
    return tuple(
        CorpusSignal(
            node_id=f"planted-{kind}",
            leak_kind=kind,
            description=_DESCRIPTIONS[kind],
            horizon=HORIZONS[0],
            scores={day: dict(statistic) for day in sorted(series)},
            targets=bundle,
        )
        for kind in LEAK_KINDS
        for statistic in (_STATISTICS[kind](series),)
    )
