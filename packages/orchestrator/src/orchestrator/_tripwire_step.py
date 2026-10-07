"""Running the tripwires member's six leakage probes on one evaluated node.

additions_spec_tripwires_live.xml: *System runs the six leakage tripwires on
every evaluated node between metrics and the ledger debit, so that each node
row returns its perturb_stability and a leaking node returns fail_class
"tripwire_fail".*  docs/nullius-tech-architecture.md §6.1 seats this at step
10, between ``compute_metrics`` (step 8, :func:`evaluator.compute_node_metrics`)
and ``debit_ledger`` (step 11, :mod:`orchestrator._charge`); this module is
the one call :mod:`orchestrator._evaluate` makes to reach it.

**The six probes, and the fixed order they run and report in.**  The
tripwires member fronts them as six methods of one composed component
(:class:`tripwires.TimeShuffleTripwire`): two independent probes —
time-shuffle (feature 125) and label-permute (feature 126) — and the
perturbation-stability family's four axes, in the family's own declaration
order (seed, window-offset, universe-subsample, lookback-jitter; features
127 through 130).  This module calls the six module-level runner functions
directly rather than the composed component, because it needs no
configuration the component's defaults do not already carry — every call
below hands the runner nothing but ``(scores, targets, node_id=node_id)``,
so every probe's bar is the tripwires member's own pinned ``DEFAULT_*``
constant, and nothing here is a knob a deployment or a test can move.

**A probe that cannot measure is "not measured", never a node failure.**  A
panel too thin to join two dates, or a per-date series with zero dispersion,
is :mod:`tripwires`' own refusal (:class:`tripwires.TripwireError` and its
two measurement-layer subclasses) — not a detection, and not a crash.  Each
probe runs in its own ``try``, and a refusal there is recorded as
:data:`NOT_MEASURED` for that probe alone; the other five still run, and a
probe that could not measure never joins :attr:`TripwireOutcome.failed`.
This is why ``perturb_stability`` — the lookback-jitter axis' own figure —
is ``None`` precisely when that one probe could not measure, rather than the
whole sweep raising.

**What this module does not do.**  It persists nothing and poisons nothing:
:func:`run_tripwires` takes no ``database_url`` and opens no store, because
the four axis verdicts' stability figures (feature 129's ledger) and the two
independent probes' failing verdicts (feature 131's poisoning) are both
*database* writes, and the evaluation loop that holds ``context.database_url``
is where a write belongs — :mod:`orchestrator._evaluate` is that caller.
This module answers one question, purely: for this node's panel, what did
the six probes find.

**Why only two of the six verdicts can drive feature 131's poisoning.**
:func:`tripwires.poison.poison_node` checks a verdict *structurally*, by the
ten field names :class:`tripwires.time_shuffle.TimeShuffleVerdict` and
:class:`tripwires.label_permute.LabelPermuteVerdict` share
(``surviving_sharpe``, ``threshold`` among them) — and the four
perturbation-axis verdicts deliberately carry *different* names
(``degradation``/``degradation_threshold`` or ``stability``/
``stability_threshold``), by the tripwires member's own one-provenance
argument: a poisoning re-derives its cause from the verdict's own terms, and
a verdict shaped like a time-shuffle rejection would be judged on a
comparison it never made.  So a rejection from one of the four axes can
still fail the node (:attr:`TripwireOutcome.failed` names it), but
:mod:`orchestrator._evaluate` can only call ``poison_node`` with whichever of
the time-shuffle or label-permute verdicts itself rejected.

**Why only three of the four axis figures reach the stability ledger.**  The
tripwires member documents, in :mod:`tripwires.stability`'s own module
docstring, that feature 127's sentence ("rejects the node when degradation
exceeds the configured threshold") names no persistence at all — the seed
axis "hands its verdict to feature 131", not to the stability ledger — while
features 128, 129 and 130 each say "persisting".  :func:`tripwires.stability.record_stability`
reflects this structurally too: it requires a ``stability``/
``stability_threshold`` pair the seed axis' :class:`tripwires.seed_rerun.SeedRerunVerdict`
does not carry (calling it with one raises
:class:`tripwires.TripwireStabilityError` for the missing fields).  So
:mod:`orchestrator._evaluate` records the window, universe-subsample and
lookback-jitter axes' verdicts through ``record_stability`` and leaves the
seed axis as a figure in :attr:`TripwireOutcome.axis_figures` only.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from tripwires import (
    LABEL_PERMUTE_NAME,
    LOOKBACK_AXIS,
    SEED_AXIS,
    SUBSAMPLE_AXIS,
    TIME_SHUFFLE_NAME,
    WINDOW_AXIS,
    TripwireError,
    run_label_permute_tripwire,
    run_lookback_rerun,
    run_seed_rerun,
    run_subsample_rerun,
    run_time_shuffle_tripwire,
    run_window_rerun,
)

__all__ = [
    "NOT_MEASURED",
    "PROBE_NAMES",
    "TripwireOutcome",
    "run_tripwires",
]

#: The sentinel recorded, in :attr:`TripwireOutcome.verdicts`, for a probe
#: whose own tripwires error meant it never produced a verdict — a panel too
#: thin to join, a per-date series with zero dispersion.  A string rather
#: than ``None`` so a reader cannot mistake "this probe did not run" for a
#: verdict object evaluating falsy.
NOT_MEASURED: str = "not measured"

#: The six probes, in the fixed order they are run and reported: step 10's
#: two independent probes first, then the perturbation-stability family's
#: four axes in the family's own declaration order
#: (:data:`tripwires.seed_rerun.PERTURBATION_AXES`).
PROBE_NAMES: tuple[str, ...] = (
    TIME_SHUFFLE_NAME,
    LABEL_PERMUTE_NAME,
    SEED_AXIS,
    WINDOW_AXIS,
    SUBSAMPLE_AXIS,
    LOOKBACK_AXIS,
)

#: The four perturbation-stability axes, in the same order
#: :data:`PROBE_NAMES` carries them — the keys
#: :attr:`TripwireOutcome.axis_figures` carries.
AXIS_NAMES: tuple[str, ...] = (SEED_AXIS, WINDOW_AXIS, SUBSAMPLE_AXIS, LOOKBACK_AXIS)

#: One runner per probe, called with nothing but ``(scores, targets,
#: node_id=node_id)`` — every other argument stays at the tripwires member's
#: own pinned ``DEFAULT_*`` default, which is the whole of "nothing is
#: configurable here".
_RUNNERS: Mapping[str, Any] = MappingProxyType(
    {
        TIME_SHUFFLE_NAME: run_time_shuffle_tripwire,
        LABEL_PERMUTE_NAME: run_label_permute_tripwire,
        SEED_AXIS: run_seed_rerun,
        WINDOW_AXIS: run_window_rerun,
        SUBSAMPLE_AXIS: run_subsample_rerun,
        LOOKBACK_AXIS: run_lookback_rerun,
    }
)


def _axis_figure(axis: str, verdict: Any) -> float:
    """One perturbation axis' instability figure, read off its own verdict.

    The seed axis' ``degradation`` is signed and one-sided against collapse,
    so its magnitude is the figure a candidate that *improved* under the
    re-run is exactly as unstable as one that degraded; the other three
    axes' ``stability`` is already a magnitude.  (This restates, rather than
    calls, :func:`tripwires.instability_of`: that function's own
    ``TRIAGE_AXES`` excludes the window-offset axis, and a window-offset
    figure is exactly as legitimate a magnitude as the other three.)
    """
    if axis == SEED_AXIS:
        return abs(verdict.degradation)
    return verdict.stability


@dataclass(frozen=True)
class TripwireOutcome:
    """The six-probe sweep's whole answer for one node, between step 8 and step 11.

    ``verdicts`` carries each probe's own verdict object, keyed by
    :data:`PROBE_NAMES`, or :data:`NOT_MEASURED` for a probe whose own
    tripwires error meant it never produced one.  ``failed`` names, in
    :data:`PROBE_NAMES`' own order, the probes that measured *and* rejected
    — a probe that could not measure never appears here and never fails the
    node.  ``perturb_stability`` is the lookback-jitter verdict's own
    figure, or ``None`` when that one probe could not measure.
    ``axis_figures`` carries the four perturbation axes' own instability
    figures (:data:`AXIS_NAMES`' order), ``None`` for an axis that could not
    measure.
    """

    verdicts: Mapping[str, Any]
    failed: tuple[str, ...]
    perturb_stability: float | None
    axis_figures: Mapping[str, float | None]


def run_tripwires(
    scores: Mapping[dt.date, Mapping[str, float]],
    targets: Mapping[int, Mapping[dt.date, Mapping[str, float]]],
    *,
    node_id: str,
) -> TripwireOutcome:
    """Run the six leakage tripwires over one node's panel — step 10, whole.

    ``scores`` is the node's normalized per-date score panel — the same
    vectors :func:`evaluator.compute_node_metrics` was handed.  ``targets``
    is the gated, post-cost target bundle at the metrics horizon — the same
    values the node was scored on, so a null node and a real node given
    identical panels are probed identically: this function reads no null
    status and no sidecar key, and has none to read.

    Each of the six probes runs under the tripwires member's own pinned
    defaults, independently: a :class:`tripwires.TripwireError` from one
    (a panel too thin to join, a per-date series with zero dispersion) is
    caught for that probe alone, recorded as :data:`NOT_MEASURED`, and never
    propagates — the other five still run, and a probe that could not
    measure never fails the node.  Pure and deterministic: the same
    ``(scores, targets, node_id)`` produce the same outcome, bit for bit,
    on any machine, since every probe underneath is.
    """
    verdicts: dict[str, Any] = {}
    failed: list[str] = []
    for name in PROBE_NAMES:
        runner = _RUNNERS[name]
        try:
            verdict = runner(scores, targets, node_id=node_id)
        except TripwireError:
            verdicts[name] = NOT_MEASURED
            continue
        verdicts[name] = verdict
        if verdict.rejected:
            failed.append(name)

    axis_figures: dict[str, float | None] = {}
    for axis in AXIS_NAMES:
        verdict = verdicts[axis]
        axis_figures[axis] = (
            None if verdict is NOT_MEASURED else _axis_figure(axis, verdict)
        )

    return TripwireOutcome(
        verdicts=MappingProxyType(verdicts),
        failed=tuple(failed),
        perturb_stability=axis_figures[LOOKBACK_AXIS],
        axis_figures=MappingProxyType(axis_figures),
    )
