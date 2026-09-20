"""The tripwires member — step 10's leakage probes, and feature 125's seat.

app_spec.xml's "Leakage Tripwires" category is a plugin (``plugin="tripwires"``)
of ten features; this package is the member that carries them, and
docs/nullius-tech-architecture.md §6.1 gives the category its pipeline seat —
step 10, ``tripwires   time-shuffle, label-permute, perturbation stability`` —
immediately after the evaluator's metrics and before the trial is debited
(feature 91's ledger row).  The module loader (``app.module_loader``) scans
the members the root ``pyproject.toml`` declares, imports each package, and
composes whatever that package's ``@register`` builder contributes; so the
``@register`` at the foot of this file is the entire wiring story.  Nothing
edits a registry, router or factory to make the tripwires plugin exist:
importing this module *is* joining the application.  (This package shipped
without this file — its submodules importable but invisible to composition —
which is the one failure mode the registration below exists to close: a
scanned member without an ``__init__.py`` is a member the loader skips in
silence.)

**What this member contributes today, and what the component is.**
:class:`TimeShuffleTripwire` — feature 125's probe, wrapped as the value a
composed application carries.  It is deliberately a *stateless facade*, not a
service with configuration: the probe is a pure function of its inputs
(``run_time_shuffle_tripwire``), so there is nothing to resolve at
construction and nothing an environment can get wrong.  Two consequences
follow, and both are the point rather than a shortcut.  The builder cannot
fail composition — the factory calls every registered builder on every
``create_app()``, so a member that insisted on a store, a lake or a pinned
image here would take composition down for every unrelated feature in the
workspace (the stance the evaluator's lazily-configured service and the
ledger's ``None``-when-unconfigured builder both take).  And the two knobs the
probe accepts stay *parameters* — ``seed`` and ``level`` are passed per call,
defaulting to :data:`~tripwires.time_shuffle.DEFAULT_SHUFFLE_SEED` and
:data:`~tripwires.time_shuffle.DEFAULT_SHUFFLE_LEVEL` — because the module
pins those defaults as the probe's repeatability, and a deployment that wants
a different probe passes a different one rather than reconfiguring a shared
object out from under a replay.

**The one name, and why it is the plugin's own.**  The component registers as
``"tripwires"`` (:data:`COMPONENT_NAME`) — the plugin name app_spec.xml gives
the category and the name of this member's seat in the app package
(``src/app/modules/tripwires``).  The *probe's* name is a different thing and
stays where it is pinned: every verdict carries ``tripwire="time-shuffle"``
(:data:`~tripwires.time_shuffle.TIME_SHUFFLE_NAME`), which is how a persisted
failure (feature 131) says *which* probe fired.  Naming the component after
the probe would fuse the two meanings — the registry entry would churn as the
category's other probes land, and a caller asking the composed application for
the tripwire suite would have to know which probe happened to be added first.

**The scope note, stated as the module states it.**  Feature 125 is *only* the
time-shuffle probe: it takes a score panel and a target bundle and answers
step 10's first question.  The label-permutation probe (feature 126) is a
second, independent probe deliberately not built on this one's shuffle; the
seed/offset/subsample/lookback re-runs are features 127 through 130; feature
131 poisons the failing node and its subtree, feature 132 excises it from the
replay pool, feature 133 maintains the planted-leak corpus the whole suite
must score 0 escapes against, and feature 134 emits the triage figure the
family exists to answer — and features 133 and 134 live *in this member*, as
:mod:`tripwires.corpus` and :mod:`tripwires.triage`, because both are made of
score panels and the verdicts those panels produce, values this package
already owns the vocabulary for.  Later features of the category extend this
member; they do not replace it.

**Feature 131 broke the "this package persists nothing" rule, and that is the
honest way to say it.**  The note above used to end there — a verdict is a
*value*, and the features that own persistence would find everything they
needed on it — and feature 131 is one of those features arriving *in this
member* rather than beside it, because "the node together with its entire
subtree" is not a fact a verdict carries and not a fact any other member can
compute: it is the transitive closure of the discovery tree's own
``parent_id``, and the tripwires are the component that has to mark it.  So
:mod:`tripwires.poison` opens a database, and the rule the member keeps is not
"persists nothing" but the narrower and truer one: *persists nothing of its
own, and writes only what a stated verdict says to write*.  The probe is still
a pure function of its inputs; the corpus is still a value; the store is a
seam a composed application carries as a third component
(``"tripwires-poison"``), on its own lifecycle, and it writes the mark and the
audit row and nothing else.

**Feature 132 is the other half of that sentence, and it is a *read*.**  §C6's
rule is *"a failure poisons the node and its entire subtree, **which is excised
from the replay pool**"*, so :mod:`tripwires.excise` is the feature that stops
the pool serving the scores a marked branch contributed — and it does so by
refusing them at read time rather than by deleting rows, for the four reasons
that module's docstring gives at length (the pool is the evidence a selection
was made on; app_spec.xml feature 270 forbids a pool mutation during a dreaming
iteration; a refusal derived from an irreversible mark is monotone, which is the
whole observable behaviour a deletion buys; and idempotence is free for a read
and not for a ``DELETE``).  It arrives as this member's fourth component
(``"tripwires-excise"``), because the join it needs — ``replay_score.committed_pick``
against the marked nodes — is a fact neither the replay member (features
245-255, which does not exist yet) nor any other can compute: the tripwires are
the component that holds both halves, the marks and the pool's rows.

**Feature 127 is the first of the re-runs, and it is the opposite of a second
probe.**  §C6's third sentence — *"Re-run with a different seed, a different
start offset, a different universe subsample.  Degradation beyond threshold is
a reject."* — is features 127 through 130, and :mod:`tripwires.seed_rerun` is
the first axis.  It is worth saying plainly what it does *not* catch, because
the two probes above it are what catch leakage: a planted leak's surviving
Sharpe is identical across seeds (verified zero degradation, all four corpus
kinds), so a re-run sails a leak straight through.  What it catches is a
candidate whose reported surviving Sharpe **did not reproduce** under a second,
equally valid derangement — a statement about the measurement rather than about
the candidate's information — which matters because the rejection it licenses
is irreversible (feature 131 poisons the subtree, feature 132 refuses the
pool).  It arrives as a *method on the probe component* (``rerun``) rather than
as this member's fifth component, and that is the same one-provenance argument
feature 125's scope note makes from the other side: a re-run is this probe
taken twice, so a component of its own would have to reach back through this
one for the statistic, the shuffle and the threshold — three second spellings
of an arithmetic that already has one home.

**Feature 134 is the question the family was built to answer, and it adds
no component.**  app_spec.xml's *"System computes the area under the curve
for perturbation stability separating planted nulls from real signals, which
emits the triage figure"* is the M1 triage gate (docs/alpha-engine-prd.md
§4.5): one number that says whether the stability family separates honest
books from aligned ones *on its own*, with a decision rule hung on its size.
:mod:`tripwires.triage` plants the two labelled populations, runs the three
implemented axes over every candidate through their own runners, and reduces
the two classes' figures to one exact Mann-Whitney AUC per axis and their
macro-mean — a pure function of (``seed``, ``count``) that emits a
:class:`~tripwires.triage.TriageFigure` and nothing else.  It is not a
seventh component and adds no verb to :class:`TimeShuffleTripwire`, for the
corpus's own reason: it is an experiment rather than a service, nothing in a
deployment resolves at composition time, so there is nothing for a builder
to build — and the seam a deployment *does* want (the AUC of its own books,
read back from feature 129's ledger and feature 130's columns) is the pure
:func:`~tripwires.triage.triage_auc` function, not a store or a facade.

**The layering note, restated because it is a constraint on every import
below.**  This package is stdlib-only — dates, mappings, sorting, square roots
and one inverse-normal quantile the member carries for itself
(:mod:`tripwires.normal`) — with exactly one dependency: the workspace root,
for the factory's registration protocol.  No polars, no pyarrow, no lake, no
environment, no HTTP, and no import of any other workspace member.  That is
not frugality for its own sake: the tripwires run inside the frozen evaluator
(architecture §5, "Immutable, containerized, hash-pinned"), and a member whose
import pulls a dependency graph is a member whose determinism story (§12) has
a moving part it cannot name.  The panels arrive as plain mappings of plain
floats — the shape every evaluator step past the materialization boundary
already speaks — so this import stays safe for the factory's scan, the replay
path, and the hash-pinned image the evaluator ships inside.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping

from app.module_loader import register

from .corpus import (
    CORPUS_GRID,
    CORPUS_SEED,
    CORPUS_SYMBOLS,
    LEAK_KINDS,
    CorpusSignal,
    planted_signals,
)
from .errors import (
    TripwireError,
    TripwireExcisionError,
    TripwireNodeMetricError,
    TripwirePanelError,
    TripwirePoisonError,
    TripwireStabilityError,
    TripwireStatisticError,
)
from .excise import COMPONENT_NAME as EXCISE_COMPONENT_NAME
from .excise import (
    ExcisedBranch,
    ExcisedScore,
    PoolScore,
    ReplayPool,
    excise_subtree,
    surviving_scores,
)
from .layout import (
    DATABASE_URL_ENV,
    NODE_METRIC_COLUMN,
    NODE_POISONED_COLUMN,
    NODE_TABLE,
    REPLAY_SCORE_TABLE,
    STABILITY_COLUMNS,
    STABILITY_TABLE,
    node_bootstrap_schema,
    replay_pool_bootstrap_schema,
    stability_bootstrap_schema,
    validated_node_id,
)
from .lookback import (
    DEFAULT_LOOKBACK_JITTER,
    DEFAULT_LOOKBACK_STABILITY_THRESHOLD,
    LOOKBACK_AXIS,
    LookbackRerunVerdict,
    jittered_lookback,
    lookback_figure,
    lookback_stability_threshold,
    run_lookback_rerun,
)
from .node_metric import COMPONENT_NAME as NODE_METRIC_COMPONENT_NAME
from .node_metric import (
    NodeMetricRecord,
    NodeMetricStore,
    node_metric_of,
    record_node_metric,
)
from .normal import NORMAL_QUANTILE_SWITCH, normal_quantile
from .poison import COMPONENT_NAME as POISON_COMPONENT_NAME
from .poison import (
    POISON_TABLE,
    PoisonedSubtree,
    PoisonRecord,
    PoisonStore,
    poison_node,
    poisoned_node_ids,
)
from .seed_rerun import (
    DEFAULT_DEGRADATION_THRESHOLD,
    DEFAULT_RERUN_SEED,
    PERTURBATION_AXES,
    PERTURBATION_STABILITY_NAME,
    SEED_AXIS,
    SeedRerunVerdict,
    run_seed_rerun,
    seed_rerun_degradation,
)
from .stability import COMPONENT_NAME as STABILITY_COMPONENT_NAME
from .stability import (
    StabilityRecord,
    StabilityStore,
    record_stability,
    stability_of,
)
from .subsample import (
    DEFAULT_SUBSAMPLE_FRACTION,
    DEFAULT_SUBSAMPLE_SEED,
    DEFAULT_SUBSAMPLE_STABILITY_THRESHOLD,
    SUBSAMPLE_AXIS,
    SubsampleRerunVerdict,
    run_subsample_rerun,
    subsample_figure,
    subsample_symbols,
)
from .time_shuffle import (
    DEFAULT_SHUFFLE_LEVEL,
    DEFAULT_SHUFFLE_SEED,
    HORIZONS,
    TIME_SHUFFLE_NAME,
    TRIPWIRE_OUTCOMES,
    TimeShuffleVerdict,
    run_time_shuffle_tripwire,
    surviving_sharpe,
    time_shuffle_pairing,
    time_shuffle_threshold,
)
from .triage import (
    TRIAGE_AXES,
    TRIAGE_KINDS,
    TRIAGE_PERSISTENCE,
    TRIAGE_POPULATION,
    TRIAGE_SEED,
    TRIAGE_SIGNAL_HORIZON,
    TRIAGE_TRUE_IC,
    TriageCandidate,
    TriageFigure,
    instability_of,
    planted_nulls,
    real_signals,
    run_triage,
    triage_auc,
)
from .window_offset import (
    DEFAULT_WINDOW_OFFSET,
    DEFAULT_WINDOW_STABILITY_THRESHOLD,
    WINDOW_AXIS,
    WindowRerunVerdict,
    run_window_rerun,
    window_figure,
    window_starts,
)

__all__ = [
    "COMPONENT_NAME",
    "CORPUS_GRID",
    "CORPUS_SEED",
    "CORPUS_SYMBOLS",
    "DATABASE_URL_ENV",
    "DEFAULT_DEGRADATION_THRESHOLD",
    "DEFAULT_LOOKBACK_JITTER",
    "DEFAULT_LOOKBACK_STABILITY_THRESHOLD",
    "DEFAULT_RERUN_SEED",
    "DEFAULT_SHUFFLE_LEVEL",
    "DEFAULT_SHUFFLE_SEED",
    "DEFAULT_SUBSAMPLE_FRACTION",
    "DEFAULT_SUBSAMPLE_SEED",
    "DEFAULT_SUBSAMPLE_STABILITY_THRESHOLD",
    "DEFAULT_WINDOW_OFFSET",
    "DEFAULT_WINDOW_STABILITY_THRESHOLD",
    "EXCISE_COMPONENT_NAME",
    "HORIZONS",
    "LEAK_KINDS",
    "LOOKBACK_AXIS",
    "NODE_METRIC_COLUMN",
    "NODE_METRIC_COMPONENT_NAME",
    "NODE_POISONED_COLUMN",
    "NODE_TABLE",
    "NORMAL_QUANTILE_SWITCH",
    "PERTURBATION_AXES",
    "PERTURBATION_STABILITY_NAME",
    "POISON_COMPONENT_NAME",
    "POISON_TABLE",
    "REPLAY_SCORE_TABLE",
    "SEED_AXIS",
    "STABILITY_COLUMNS",
    "STABILITY_COMPONENT_NAME",
    "STABILITY_TABLE",
    "SUBSAMPLE_AXIS",
    "TIME_SHUFFLE_NAME",
    "TRIAGE_AXES",
    "TRIAGE_KINDS",
    "TRIAGE_PERSISTENCE",
    "TRIAGE_POPULATION",
    "TRIAGE_SEED",
    "TRIAGE_SIGNAL_HORIZON",
    "TRIAGE_TRUE_IC",
    "TRIPWIRE_OUTCOMES",
    "WINDOW_AXIS",
    "CorpusSignal",
    "ExcisedBranch",
    "ExcisedScore",
    "LookbackRerunVerdict",
    "NodeMetricRecord",
    "NodeMetricStore",
    "PoisonRecord",
    "PoisonStore",
    "PoisonedSubtree",
    "PoolScore",
    "ReplayPool",
    "SeedRerunVerdict",
    "StabilityRecord",
    "StabilityStore",
    "SubsampleRerunVerdict",
    "TimeShuffleTripwire",
    "TimeShuffleVerdict",
    "TriageCandidate",
    "TriageFigure",
    "TripwireError",
    "TripwireExcisionError",
    "TripwireNodeMetricError",
    "TripwirePanelError",
    "TripwirePoisonError",
    "TripwireStabilityError",
    "TripwireStatisticError",
    "WindowRerunVerdict",
    "build_node_metric_store",
    "build_poison_store",
    "build_replay_pool",
    "build_stability_store",
    "build_time_shuffle_tripwire",
    "excise_subtree",
    "instability_of",
    "jittered_lookback",
    "lookback_figure",
    "lookback_stability_threshold",
    "node_bootstrap_schema",
    "node_metric_of",
    "normal_quantile",
    "planted_nulls",
    "planted_signals",
    "poison_node",
    "poisoned_node_ids",
    "real_signals",
    "record_node_metric",
    "record_stability",
    "replay_pool_bootstrap_schema",
    "run_lookback_rerun",
    "run_seed_rerun",
    "run_subsample_rerun",
    "run_time_shuffle_tripwire",
    "run_triage",
    "run_window_rerun",
    "seed_rerun_degradation",
    "stability_bootstrap_schema",
    "stability_of",
    "subsample_figure",
    "subsample_symbols",
    "surviving_scores",
    "surviving_sharpe",
    "time_shuffle_pairing",
    "time_shuffle_threshold",
    "triage_auc",
    "validated_node_id",
    "window_figure",
    "window_starts",
]

__version__ = "0.1.0"

#: The component name this member registers under — the plugin name
#: app_spec.xml gives the category (``plugin="tripwires"``) and the name of
#: the member's seat in the app namespace (``src/app/modules/tripwires``).
#: Kept here so anything asking the composed application for the tripwire
#: suite — by way of the member, not by hard-coded string — shares one
#: spelling with the builder below.
COMPONENT_NAME: str = "tripwires"


class TimeShuffleTripwire:
    """Feature 125's probe, as the value a composed application carries.

    A stateless facade over :func:`~tripwires.time_shuffle.run_time_shuffle_tripwire`
    and the two pure functions it is built from, so a caller holding the
    composed component can reach the probe, rebuild its pairing, and recompute
    its threshold without importing this member's submodules by name.  The
    class carries no state — ``__slots__`` is empty and it defines no
    ``__init__`` — which is the honest shape for a probe that is a pure
    function of its inputs and reads nothing from the environment.  Every knob
    is a keyword argument on the call that uses it, defaulting to the module's
    pinned constants; there is no shared seed or level to reconfigure, so two
    callers probing two candidates can never observe each other.

    The delegation is deliberately *thin* — each method is one call to the
    function that owns the arithmetic — because a second implementation of the
    statistic, the shuffle or the threshold is exactly what this member's
    one-provenance rule forbids.  What this class adds is discoverability (the
    factory's scan composes it) and a single duck-checkable seam
    (``run``/``pairing``/``threshold``/``rerun``/``subsample``/``lookback``/
    ``window``)
    for the app seat and the features that follow, not arithmetic.

    **``rerun`` is the fourth verb and the family's first axis.**  Feature 127
    perturbs the one knob this probe deliberately holds fixed — the seed — so
    the re-run is a *method here* rather than a fifth component: it needs the
    statistic, the shuffle and the threshold, all three of which already live
    on this class, and a component of its own would reach back through this one
    for every one of them.  Features 128 through 130 add the same method's
    later axes, beside this one.

    **``subsample`` is the fifth verb and the family's third axis.**  Feature
    129 perturbs the *universe* — the names the panel scores — and holds the
    derangement fixed, so it is a method here for the same reason ``rerun`` is,
    and its single shared ``seed`` parameter is what makes the pair of axes
    complementary rather than a larger sweep of one.  Its figure is not
    ``rerun``'s: that one is signed, one-sided and judged against ``0.77``,
    this one is a magnitude, two-sided and judged against ``1.05``, and the
    two numbers mean nothing against each other's bar.

    **``lookback`` is the sixth verb and the family's fourth axis.**  Feature
    130 perturbs the *window* — how much history the re-run sees — and holds
    both the seed and the universe fixed, so it is a method here for the
    reason the two above are.  Its bar is the family's *widest*
    (``√(1 + 1/(1 + jitter))``, ≈ 1.453 at the pinned minus tenth) because its
    two runs share no noise: the derangement is a function of the whole date
    list, so a truncated window re-dates every date and the two statistics
    are independent — the fact whose *converse* gave ``subsample`` its bar.
    And its figure is the one this feature's persistence half
    (:func:`~tripwires.node_metric.record_node_metric`) writes to the node's
    own ``perturb_stability`` column, 0114's last metric column, beside the
    stability-ledger row the same verdict may also land in.

    **``window`` is the seventh verb and the family's second axis.**  Feature
    128 perturbs the window's *position* — which stretch of the measured grid
    the re-run scores — holding the seed, the universe and the length all
    fixed, so it is a method here for the reason the three above are.  It is
    the axis §C6 names second (*"... a different seed, a different start
    offset, ..."*) and the one that moves the grid's *newest* bar, which every
    other axis holds fixed: the reference window is the trailing ``L`` dates
    and the re-run is the same ``L`` started ``offset`` bars earlier, so the
    two windows differ at both ends and share the dates between.  Its bar is
    the family's equal-length limit — ``√2``, the number ``lookback``'s
    formula tends to as its jitter shrinks — because the same re-dating
    argument that freed ``lookback``'s runs from shared noise frees these,
    with equal lengths on top of it.  And its persistence is the ledger's,
    not a store of its own: the verdict lands in ``tripwire_stability``
    keyed on this axis, beside feature 129's rows, with the knobs it does not
    move written NULL — the row that table's ``(node_id, axis)`` key was
    waiting for.
    """

    __slots__ = ()

    #: The probe's own name, in §C6's and §6.1 step 10's spelling.  Restated
    #: from the module (which pins it) rather than re-spelled, so a verdict's
    #: ``tripwire`` field and the component's identity cannot drift apart.
    name: str = TIME_SHUFFLE_NAME

    def run(
        self,
        scores: Mapping[dt.date | str, Mapping[str, float]],
        targets: Mapping[int, Mapping[dt.date | str, Mapping[str, float]]],
        *,
        node_id: str,
        seed: int = DEFAULT_SHUFFLE_SEED,
        level: float = DEFAULT_SHUFFLE_LEVEL,
    ) -> TimeShuffleVerdict:
        """Run the probe and state the verdict — feature 125's whole answer.

        The candidate's score panel, the gated target bundle (one series per
        horizon, §6.1 step 4), the node's id, and the two knobs.  Returns the
        :class:`~tripwires.time_shuffle.TimeShuffleVerdict` — whose
        ``rejected`` is the probe's detection and ``outcome`` its translation
        into §8's trial vocabulary.  A *detected leak is not an exception*:
        the refusals this raises (a malformed panel, a bundle sharing no
        horizon, fewer than two shared dates, a statistic with zero
        dispersion) all mean the probe could not measure, which the ledger
        must be able to tell apart from a probe that *did* measure and found
        leakage.
        """
        return run_time_shuffle_tripwire(
            scores, targets, node_id=node_id, seed=seed, level=level
        )

    def pairing(
        self, dates: object, *, seed: int = DEFAULT_SHUFFLE_SEED
    ) -> Mapping[dt.date, dt.date]:
        """The derangement the probe scores against — ``{score date: target date}``.

        Exposed on the component because a reader checking a *persisted*
        rejection (feature 131's poisoned subtree, feature 132's excised
        branch) needs to rebuild the pairing the verdict was computed from,
        and the verdict's own ``seed`` is what they rebuild it with.  Same
        function, same seed, same mapping — the audit path is the probe path.
        """
        return time_shuffle_pairing(dates, seed=seed)

    def threshold(self, dates: int, *, level: float = DEFAULT_SHUFFLE_LEVEL) -> float:
        """The rejection threshold over ``dates`` measured dates.

        ``Φ⁻¹(1 − level/2) / √dates``, computed rather than tabled, so a
        deployment tightening the level (feature 127's configured thresholds
        are the precedent) is a parameter change and not a second
        calibration.  ``TimeShuffleVerdict`` enforces this equality at
        construction, so a verdict and a recomputation through this method
        cannot disagree.
        """
        return time_shuffle_threshold(dates, level=level)

    def rerun(
        self,
        scores: Mapping[dt.date | str, Mapping[str, float]],
        targets: Mapping[int, Mapping[dt.date | str, Mapping[str, float]]],
        *,
        node_id: str,
        seed: int = DEFAULT_SHUFFLE_SEED,
        rerun_seed: int = DEFAULT_RERUN_SEED,
        level: float = DEFAULT_SHUFFLE_LEVEL,
        threshold: float = DEFAULT_DEGRADATION_THRESHOLD,
    ) -> SeedRerunVerdict:
        """Re-run the probe under a different seed — feature 127's whole answer.

        The same candidate and bundle :meth:`run` takes, plus the second seed
        and the configured degradation threshold.  Returns the
        :class:`~tripwires.seed_rerun.SeedRerunVerdict` — whose ``degradation``
        is the perturbation-stability figure (feature 130 persists a sibling
        axis of it as ``perturb_stability``), whose ``degradation_rejected`` is
        the spec's own cause, and whose ``rejected`` unions it with the re-run's
        own detection.

        It is a method on *this* component rather than a fifth one because the
        re-run is not a second probe: it is this probe, taken twice, and a
        caller holding the composed probe has everything the re-run needs —
        the statistic, the shuffle and the threshold are already here.  A
        separate component would have to reach back through this one for all
        three, which is the second spelling of the probe the member's
        one-provenance rule forbids.  §6.1 step 10 names the family as one
        probe (``... perturbation stability``) for the same reason.
        """
        return run_seed_rerun(
            scores,
            targets,
            node_id=node_id,
            seed=seed,
            rerun_seed=rerun_seed,
            level=level,
            threshold=threshold,
        )

    def subsample(
        self,
        scores: Mapping[dt.date | str, Mapping[str, float]],
        targets: Mapping[int, Mapping[dt.date | str, Mapping[str, float]]],
        *,
        node_id: str,
        fraction: float = DEFAULT_SUBSAMPLE_FRACTION,
        subsample_seed: int = DEFAULT_SUBSAMPLE_SEED,
        seed: int = DEFAULT_SHUFFLE_SEED,
        level: float = DEFAULT_SHUFFLE_LEVEL,
        threshold: float = DEFAULT_SUBSAMPLE_STABILITY_THRESHOLD,
    ) -> SubsampleRerunVerdict:
        """Re-run the probe against a universe subsample — feature 129's whole answer.

        The same candidate and bundle :meth:`run` takes, plus the fraction of
        the universe to keep and the seed the subsample is drawn under.  Returns
        the :class:`~tripwires.subsample.SubsampleRerunVerdict` — whose
        ``stability`` is the perturbation-stability figure feature 129's
        sentence says is persisted (by
        :func:`~tripwires.stability.record_stability`, into this member's own
        ``tripwire_stability`` table), and whose ``rejected`` unions the
        stability cause with either run's own detection.

        **``seed`` here is one parameter where :meth:`rerun` takes two**, and
        that is the axis' definition rather than a simplification: feature 127
        perturbs the derangement and holds the universe, this feature perturbs
        the universe and holds the derangement, so both runs draw their pairing
        from the *same* seed.  A caller who moved both at once would be running
        two features' perturbations in one measurement and could not say which
        produced the figure.

        It is a method on this component for the reason :meth:`rerun` is: the
        re-run is not a second probe but this probe taken twice, and a caller
        holding the composed probe already has the statistic, the shuffle and
        the threshold it needs.  Feature 128 arrives the same way, and
        :meth:`lookback` below is the axis that already did.
        """
        return run_subsample_rerun(
            scores,
            targets,
            node_id=node_id,
            fraction=fraction,
            subsample_seed=subsample_seed,
            seed=seed,
            level=level,
            threshold=threshold,
        )

    def lookback(
        self,
        scores: Mapping[dt.date | str, Mapping[str, float]],
        targets: Mapping[int, Mapping[dt.date | str, Mapping[str, float]]],
        *,
        node_id: str,
        lookback: int | None = None,
        jitter: float = DEFAULT_LOOKBACK_JITTER,
        seed: int = DEFAULT_SHUFFLE_SEED,
        level: float = DEFAULT_SHUFFLE_LEVEL,
        threshold: float = DEFAULT_LOOKBACK_STABILITY_THRESHOLD,
    ) -> LookbackRerunVerdict:
        """Re-run the probe over a jittered lookback — feature 130's whole answer.

        The same candidate and bundle :meth:`run` takes, plus the declared
        lookback — ``None`` meaning the panel's own full measured span, which
        makes the reference run exactly :meth:`run`'s — and the signed jitter
        taken on it (the spec's *plus or minus 10 percent*, minus by default
        because the minus side is always runnable while the plus side needs
        history the panel may not carry).  Returns the
        :class:`~tripwires.lookback.LookbackRerunVerdict` — whose ``stability``
        is the figure this feature's persistence half writes to the node's own
        ``perturb_stability`` column
        (:func:`~tripwires.node_metric.record_node_metric`), and whose
        ``rejected`` unions the stability cause with either run's own
        detection.

        **``seed`` is one parameter and there is no subsample seed at all**,
        and together those two absences are the axis' definition: 127 perturbs
        the derangement, 129 the universe, and this feature perturbs the
        *window* holding both fixed.  The pairing still differs between the
        runs — the derangement is a function of the whole date list, so the
        jittered window draws its own — but that is a consequence of the
        perturbation rather than a knob, and it is why the axis' bar is
        derived for independent runs where 129's is not.

        It is a method on this component for the reason :meth:`rerun` and
        :meth:`subsample` are: the re-run is not a second probe but this probe
        taken twice, and a caller holding the composed probe already has the
        statistic, the shuffle and the threshold it needs.
        """
        return run_lookback_rerun(
            scores,
            targets,
            node_id=node_id,
            lookback=lookback,
            jitter=jitter,
            seed=seed,
            level=level,
            threshold=threshold,
        )

    def window(
        self,
        scores: Mapping[dt.date | str, Mapping[str, float]],
        targets: Mapping[int, Mapping[dt.date | str, Mapping[str, float]]],
        *,
        node_id: str,
        window: int | None = None,
        offset: int = DEFAULT_WINDOW_OFFSET,
        seed: int = DEFAULT_SHUFFLE_SEED,
        level: float = DEFAULT_SHUFFLE_LEVEL,
        threshold: float = DEFAULT_WINDOW_STABILITY_THRESHOLD,
    ) -> WindowRerunVerdict:
        """Re-run the probe from a different window start offset — feature 128's whole answer.

        The same candidate and bundle :meth:`run` takes, plus the declared
        window — ``None`` meaning the maximal window this axis can offset
        (the panel's measured span less the offset, the axis' structural
        substitute for the family's full-span default, because a window that
        is the whole grid has no position to move to) — and the offset
        itself, in bars.  Returns the
        :class:`~tripwires.window_offset.WindowRerunVerdict` — whose
        ``stability`` is the delta feature 128's sentence says is persisted
        (by :func:`~tripwires.stability.record_stability`, into the same
        ``tripwire_stability`` ledger feature 129's figures land in, keyed on
        this axis), and whose ``rejected`` unions the stability cause with
        either run's own detection.

        **``seed`` is one parameter, and there is no second seed and no
        subsample seed at all** — and those absences, together, are the
        axis' definition: 127 perturbs the derangement, 129 the universe,
        130 the window's *length*, and this feature perturbs the window's
        *position* holding all three fixed.  The pairing still differs
        between the runs — the derangement is a function of the whole date
        list, so the offset window draws its own — but that is a consequence
        of the perturbation rather than a knob, and it is why the axis' bar
        is the equal-length independent-runs ``√2``.

        It is a method on this component for the reason :meth:`rerun`,
        :meth:`subsample` and :meth:`lookback` are: the re-run is not a
        second probe but this probe taken twice, and a caller holding the
        composed probe already has the statistic, the shuffle and the
        threshold it needs.
        """
        return run_window_rerun(
            scores,
            targets,
            node_id=node_id,
            window=window,
            offset=offset,
            seed=seed,
            level=level,
            threshold=threshold,
        )


@register(COMPONENT_NAME)
def build_time_shuffle_tripwire() -> TimeShuffleTripwire:
    """Component builder: the tripwire suite's probe (feature 125).

    Takes no arguments — that is the factory's registration protocol — and
    constructs unconditionally, because there is nothing to resolve: the probe
    reads no environment, touches no lake and holds no store.  That is what
    keeps this member from taking composition down in a bare test process,
    where ``create_app()`` builds every registered component and most of them
    are pointed at an environment this one does not need.

    It returns a :class:`TimeShuffleTripwire` rather than the bare function so
    the composed component is duck-checkable and extensible: the category's
    later probes (features 126 through 130) attach to the same member, and a
    caller that has the component has the seam they will arrive on.
    """
    return TimeShuffleTripwire()


@register(POISON_COMPONENT_NAME)
def build_poison_store() -> PoisonStore | None:
    """Component builder: the store a tripwire failure is persisted to (feature 131).

    Takes no arguments — that is the factory's registration protocol — and
    resolves ``DATABASE_URL`` at build time, so a composed application carries
    the store for the deployment the process is actually running in.

    Returns ``None`` when nothing names a relational store: the
    degrade-don't-break stance every store in this workspace takes toward an
    absent ``DATABASE_URL``, and the same one
    :func:`~nulloracle.verdict.CampaignVerdict.resolve` takes for the campaign
    verdict.  An unconfigured poison store is a discoverable state, and the
    evaluation loop that must persist §C6's rejection is the caller that must
    not find itself in it — which is why :func:`~tripwires.poison.poison_node`
    *refuses* rather than silently no-ops when it resolves no store, while this
    builder stays silent so composition never fails.

    Like the probe's builder, this never raises — including for a URL whose
    scheme the store cannot speak.  The factory builds every registered
    component on every :func:`~app.module_loader.create_app` call, so a builder
    that raised would take composition down for every unrelated feature in the
    workspace; a process that *requires* a store calls
    :meth:`~tripwires.poison.PoisonStore.resolve` or passes a URL to
    ``PoisonStore`` directly, where a named
    :class:`~tripwires.TripwirePoisonError` is the right answer.  Construction
    performs no I/O — the path is resolved on first use — so composing the
    application never opens a database.
    """
    return PoisonStore.resolve()


@register(EXCISE_COMPONENT_NAME)
def build_replay_pool() -> ReplayPool | None:
    """Component builder: the pool a poisoned branch is excised from (feature 132).

    Takes no arguments — that is the factory's registration protocol — and
    resolves ``DATABASE_URL`` at build time, so a composed application carries
    the pool for the deployment the process is actually running in.  It is the
    fourth component this member contributes, and the third that may legitimately
    be ``None``: the probe is ready the instant it is built, while this one and
    the poison store both resolve a relational store that may not be named.

    Returns ``None`` when nothing names a relational store — the
    degrade-don't-break stance :func:`build_poison_store` takes, for the same
    reason: the factory builds every registered component on every
    ``create_app()``, so a builder that raised would take composition down for
    every unrelated feature, and an unconfigured pool is a discoverable state.
    A replay path that *requires* one is the caller that must not find itself in
    it, which is why :func:`~tripwires.excise.surviving_scores` and
    :func:`~tripwires.excise.excise_subtree` refuse rather than no-op when they
    resolve no pool — the same split the poison store's two entry points draw.

    The pool reads its marks through a :class:`~tripwires.poison.PoisonStore`
    built from the same URL, so the two components compose the same deployment's
    database even when only one of them is reached for.  Construction performs
    no I/O — the path is resolved on first use — so composing the application
    never opens a database, and a URL whose scheme this member cannot speak still
    composes, with the refusal deferred to first use.
    """
    return ReplayPool.resolve()


@register(STABILITY_COMPONENT_NAME)
def build_stability_store() -> StabilityStore | None:
    """Component builder: the store a stability figure is persisted to (feature 129).

    Takes no arguments — that is the factory's registration protocol — and
    resolves ``DATABASE_URL`` at build time, so a composed application carries
    the store for the deployment the process is actually running in.  It is the
    fifth component this member contributes and the fourth that may legitimately
    be ``None``, for the reason :func:`build_poison_store` states: the factory
    builds every registered component on every ``create_app()`` call, a builder
    that raised would take composition down for every unrelated feature, and a
    deployment without a relational store is a discoverable state rather than a
    failure.  A process that *requires* one is the caller that must not find
    itself in it — which is why :func:`~tripwires.stability.record_stability`
    and :func:`~tripwires.stability.stability_of` refuse by name where they
    resolve no store, while this builder stays silent.

    It is a **separate component from the poison store** even though both
    resolve the same variable, and that is the point rather than an oversight:
    feature 131's store writes the record of a failure and refuses a verdict
    that passed; this one writes a measurement that is taken either way and has
    a different table, a different key and a different refusal.  A caller asking
    the composed application for the stability store must not be handed the
    poisoning store — the two would answer the same question with an object
    whose every method means the other feature's thing.

    Construction performs no I/O, so composing the application never opens a
    database; a URL whose scheme this member cannot speak still composes, with
    the refusal deferred to first use.
    """
    return StabilityStore.resolve()


@register(NODE_METRIC_COMPONENT_NAME)
def build_node_metric_store() -> NodeMetricStore | None:
    """Component builder: the store a node metric is persisted to (feature 130).

    Takes no arguments — that is the factory's registration protocol — and
    resolves ``DATABASE_URL`` at build time, so a composed application carries
    the store for the deployment the process is actually running in.  It is
    the sixth component this member contributes and the fifth that may
    legitimately be ``None``, for the reason :func:`build_poison_store`
    states: the factory builds every registered component on every
    ``create_app()`` call, a builder that raised would take composition down
    for every unrelated feature, and a deployment without a relational store
    is a discoverable state rather than a failure.  A process that *requires*
    one is the caller that must not find itself in it — which is why
    :func:`~tripwires.node_metric.record_node_metric` and
    :func:`~tripwires.node_metric.node_metric_of` refuse by name where they
    resolve no store, while this builder stays silent.

    It is a **separate component from the stability store** even though both
    resolve the same variable and both persist the same verdict's figure, and
    that is the point rather than an oversight: feature 129's store appends a
    keyed row to a table it owns and requires no node row; this one updates a
    column on the node row the discovery tree owns and refuses a node the
    tree does not hold.  A caller asking the composed application for one and
    handed the other would get an object whose every method means the other
    feature's persistence — and the mistake would surface only as a figure
    missing from the ledger or a node row never written.

    Construction performs no I/O, so composing the application never opens a
    database; a URL whose scheme this member cannot speak still composes, with
    the refusal deferred to first use.
    """
    return NodeMetricStore.resolve()
