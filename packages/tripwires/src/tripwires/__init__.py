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
replay pool, and feature 133 maintains the planted-leak corpus the whole suite
must score 0 escapes against — and feature 133 lives *in this member*, as
:mod:`tripwires.corpus`, because the corpus is a set of score panels and the
verdicts they produce, both of them values this package already owns the
vocabulary for.  Later features of the category extend this member; they do
not replace it.

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
audit row and nothing else.  Feature 132's excision — reading those marks and
rejecting the scores the branch contributed — is still not here, and the
pool's refusal is the place it must live.

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
    TripwirePanelError,
    TripwirePoisonError,
    TripwireStatisticError,
)
from .layout import (
    DATABASE_URL_ENV,
    NODE_POISONED_COLUMN,
    NODE_TABLE,
    node_bootstrap_schema,
    validated_node_id,
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

__all__ = [
    "COMPONENT_NAME",
    "CORPUS_GRID",
    "CORPUS_SEED",
    "CORPUS_SYMBOLS",
    "DATABASE_URL_ENV",
    "DEFAULT_SHUFFLE_LEVEL",
    "DEFAULT_SHUFFLE_SEED",
    "HORIZONS",
    "LEAK_KINDS",
    "NODE_POISONED_COLUMN",
    "NODE_TABLE",
    "NORMAL_QUANTILE_SWITCH",
    "POISON_COMPONENT_NAME",
    "POISON_TABLE",
    "TIME_SHUFFLE_NAME",
    "TRIPWIRE_OUTCOMES",
    "CorpusSignal",
    "PoisonRecord",
    "PoisonStore",
    "PoisonedSubtree",
    "TimeShuffleTripwire",
    "TimeShuffleVerdict",
    "TripwireError",
    "TripwirePanelError",
    "TripwirePoisonError",
    "TripwireStatisticError",
    "build_poison_store",
    "build_time_shuffle_tripwire",
    "node_bootstrap_schema",
    "normal_quantile",
    "planted_signals",
    "poison_node",
    "poisoned_node_ids",
    "run_time_shuffle_tripwire",
    "surviving_sharpe",
    "time_shuffle_pairing",
    "time_shuffle_threshold",
    "validated_node_id",
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
    (``run``/``pairing``/``threshold``) for the app seat and the features that
    follow, not arithmetic.
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
