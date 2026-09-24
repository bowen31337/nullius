"""The dreaming loop's last act — feature 274.

app_spec.xml, *Dreaming Loop & Meta-Selection*, feature 274:

    System selects the argmax candidate under the aggregated objective,
    persisting the winner into the ``policy_revision`` table.

docs/alpha-engine-prd.md §C5 states it as the terminal clause of the loop —
*"Per outer iteration: hold the replay pool fixed, run ``M`` code revisions of
``π``, evaluate each on every stored tree, select the argmax under §7"* — and
§12.1 names the thing that is wrong with stopping at a bare max: the winner is
a **max**, and a max is biased, *"the dreaming loop overfits its own replay
pool … selecting the max over ``M`` revisions … is the same multiple-testing
problem one level up"*.  This module is the *crowning* half of that clause —
the selector feature 280's bar deliberately is not.  :mod:`dreaming.bar`
(feature 280) *refuses* a winner whose advantage does not survive §12.1's
selection-noise bar, and its docstring states that feature 274 "selects the
argmax and writes the winner into ``policy_revision``; this module refuses a
winner, and the act of refusing one is not the act of crowning it".  So the
loop drives the sweep, takes this module's argmax, and only then judges it at
feature 280's bar; this module crowns the max the sweep earned and the bar has
already let through, and judges nothing against the bar itself.

What it is
----------

Two halves in one module, beside feature 270's single ``"dreaming"``
component, the shape the floor, the cap, the ceiling, the split, the rotation,
the bar, the comparison and the transfer all take.

**The verdict —** :func:`select_argmax(candidates, objectives)`: the candidate
set feature 271 produced and each one's aggregated objective (feature 263's
``scoring.AggregatedObjective``, read duck-typed by its finite ``score`` and
its ``world_count`` of one or more — the two figures the argmax needs, and the
same two figures feature 280's bar judges) in, and the winning candidate out:
the one carrying the strictly-maximum aggregated ``score``.  It is **pure** —
no store, no clock, no environment, no ``@register`` component — the argmax is
a judgment over figures the caller already holds, the shape the ladder's other
verdicts take, and a caller that only wants to know *which candidate won* asks
this and pays for nothing.  It **refuses** rather than silently defaults on an
empty set, an empty objective mapping, a candidate the objectives do not
cover, an objective that carries no finite score, an objective keyed to a
module id no candidate carries, and a **tie** on the maximum — the argmax is
undefined over two candidates sharing the top score, and picking one by
iteration order would be a selection that changed with nothing.

**The act —** :func:`commit_selection(...)` is the store seam and the
feature's only act.  It resolves the database the deployment names, reads the
sweep's evidence back from the pool's own ``replay_score`` table — a
``sqlite3`` connection opened against the resolved path, the same read-time
seam :func:`dreaming.paired._pool_arm` takes — because the composed replay
component exposes only the *writer* ``persist_replay_score`` and no reader of
the score rows, so there is no carrier to hand in and no ``app.modules.replay``
seat to resolve one through: the evidence read is a read, and the member that
owns the rows owns no reader of them.  It groups each candidate's rows into the
regime strata the caller hands in — the same strata-keyed mapping feature
263's ``aggregate_objective`` takes — and aggregates each candidate over its
worlds under §7 with feature 263's ``aggregate_objective``, reached the way
the policy-runtime member's free seams reach a sibling — through the scoring
member's own namespace, ``importlib.import_module("scoring")``, **not** the
composed ``app.modules.scoring`` seat, which answers only the per-world
objective (:func:`scoring.world_objective_component`) and not the blend.  It
takes :func:`select_argmax`'s winner and persists one row into
``policy_revision`` (migration ``0109``) **directly**: feature 274 is the
table's sole writer, because the replay member's ``persist_replay_score``
writes ``replay_score`` and not this table, so writing the winner's row
through it would land in the wrong table.  The persisted row carries the
winner's ``module_id`` as ``policy_version``, its ``code_hash``, its
``parent_version`` from the candidate and its aggregated ``score`` as
``aggregate_score``, with ``selected`` TRUE.

What it is not
--------------

**It is not the sweep, the aggregate or the bar.**  It runs no replay, scores
no world, blends no strata and judges no winner against §12.1's noise bar —
feature 280 refuses one; this module crowns the max the sweep earned.  The
candidate set it ranks over is the value feature 271 produces; the objectives
it ranks them by are feature 263's ``AggregatedObjective`` values; the §7
blend is feature 263's arithmetic, consumed, never respelled.  It is not
feature 273 either: 273 puts the incumbent back into the candidate set so the
argmax never falls below the current policy, and this module takes the argmax
over whatever candidate set it is handed — if the loop has run 273 first, the
incumbent is one candidate among the set; if it has not, this module ranks the
revisions alone.

**It never writes the pool's tables.**  Feature 270's whole subject is not
writing them.  ``policy_revision`` is not a pool table — feature 270's triggers
guard ``replay_score`` and ``bootstrap_world`` — so the selector's write is
permitted under an open hold, and the selector's evidence read is a read,
likewise permitted.  It drops no guard, opens no second connection and
re-holds nothing to slip a row underneath the hold.  It reads the pool's tables
only by name, restated here in :mod:`dreaming.layout`'s style (pinned against
``0109`` and against the replay member by ``test_cross_member.py``) rather than
importing the members that own them — a member that imported another would
couple a database's history to a package's import graph.

The store seam
--------------

The evidence read and the winner's row both go through this module's own
``sqlite3`` connection against the resolved path — never through a composed
component, because none speaks this read and none owns this table.  The store
is resolved by an explicit URL, then ``DATABASE_URL`` (the member's one
spelling, translated at the seam from :func:`dreaming.cycle.sqlite_path`),
refused when neither names a ``sqlite`` path.  The pool-tables probe is
:func:`dreaming.layout.pool_tables_present` — a ``sqlite_master`` read, never
a row read — and a database holding no ``replay_score`` is refused naming the
table.  The §7 blend is the one thing reached across the member boundary, and
it is reached through the scoring member's namespace at call time, so the
factory's scan — which imports this package to fire its ``@register`` — pays
nothing for a module it never composes.  Stdlib only at module scope:
``math``, ``os``, ``sqlite3`` and the ``collections.abc`` / ``contextlib`` /
``dataclasses`` / ``pathlib`` / ``typing`` helpers.

The winner's identity is the candidate's own ``module_id`` and ``code_hash``,
read not recomputed — the selector persists the candidate the loop handed it,
so a row's ``policy_version`` and ``code_hash`` are the produced value's, and a
selector that re-hashed the source would be a second spelling of what a
candidate is.  The verdict is deterministic and order-independent — the winner
is the candidate whose objective score is strictly greater than every other,
so the same candidate set and objectives answer the same winner (or the same
refusal) regardless of mapping or candidate order, the determinism law the
aggregate holds one transform over.

Its refusals are their own pair of classes under the one
:class:`~dreaming.errors.DreamingError` base, with the thin pool and the held
pool delegated to feature 275's and feature 270's refusals as the cap, the
ceiling, the split, the transfer, the bar and the rotation all delegate
theirs — a pool too thin to dream on has no winner to crown, and a held pool
is feature 270's word, not this module's.
"""

from __future__ import annotations

import importlib
import math
import os
import sqlite3
from collections.abc import Iterable, Mapping
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .cycle import sqlite_path
from .errors import SelectionRequestError, SelectionStoreError
from .layout import REPLAY_SCORE_TABLE, pool_tables_present

__all__ = [
    "SELECT_REQUEST_CODE",
    "SELECT_STORE_CODE",
    "commit_selection",
    "select_argmax",
]

#: The code a *selection-ask* refusal opens with — the greppable word naming a
#: malformed candidate set, objective mapping or identity, the convention
#: §7.3's ``heterogeneous_world``, feature 241's ``illegal_theme`` and this
#: member's ``pool_frozen`` already follow for a refusal an operator greps for.
#: Feature 274's verdict verb is *selects*, so the ask's refusals name their
#: subject, and the code is deliberately not feature 272's ``sweep_malformed``
#: nor feature 280's ``advantage_below_bar``: a caller that caught the
#: selector's malformed ask as the sweep's or the bar's would act on the wrong
#: fact.
SELECT_REQUEST_CODE = "selection_malformed"

#: The code a *selection-store* refusal opens with — no database, no pool, or a
#: winner that measured but would not land.  The store half of the same
#: greppability convention, and deliberately not feature 272's
#: ``sweep_ungrounded``: the selector reads the evidence the sweep wrote and
#: crowns one, and a caller that caught its store refusal as the sweep's would
#: re-run a sweep that already landed.
SELECT_STORE_CODE = "selection_ungrounded"


@dataclass(frozen=True, slots=True)
class _RowScore:
    """One ``replay_score`` reading, as feature 263's world-score seam expects.

    The §7 blend reads each world by a readable ``world_id`` and a finite
    ``score`` (duck-typed, never ``isinstance`` — the module loader's
    synthetic-name re-execution means a type check would refuse the very
    objects composition produces), so the selector's read rows are wrapped in
    this value before they cross the seam: a frozen, slotted carrier so two
    callers holding one reading cannot move each other's figure, the stance the
    member's :class:`~dreaming.cycle.FreezeRecord` and
    :class:`~dreaming.reviser.CandidateModule` take.  It carries the two facts
    the blend reads and nothing more.
    """

    world_id: str
    score: float


# -- the verdict --------------------------------------------------------------


def select_argmax(candidates: Any, objectives: Any) -> Any:
    """The argmax under §7's aggregated objective — the winning candidate, or refuse.

    The pure verdict half of feature 274: the candidate set feature 271
    produced and each one's aggregated objective in, and the single winning
    candidate out.  It is **pure** — no store, no clock, no environment — a
    judgment over figures the caller already holds, the shape the ladder's
    other verdicts take, and the winner is the candidate whose objective
    carries a ``score`` strictly greater than every other candidate's.

    Both arguments are read **duck-typed**, by the attributes the verdict
    needs rather than by ``isinstance`` — a member never imports another, and
    the module loader's synthetic-name re-execution means an ``isinstance``
    would refuse the very objects composition produces.  A candidate is read
    for its ``module_id`` and ``code_hash`` (each a non-empty text identity,
    the way :func:`dreaming.sweep` reads them); an objective is read for its
    ``score`` (a finite real — a ``−∞`` miss's number may not be counterfeited,
    the aggregate's own ``−∞`` argument one level up) and its ``world_count``
    (a whole number of one or more — an objective aggregated over no world
    names no score to rank by).

    Refused, with :class:`~dreaming.errors.SelectionRequestError`, before
    anything is read:

    * an **empty candidate set** — an argmax over nothing is a tournament
      nobody entered, not a null selection;
    * an **empty objective mapping** — no candidate has a figure to rank it by;
    * a candidate whose ``module_id`` is not non-empty text — it addresses no
      revision to crown;
    * an objective that is not a value carrying a finite ``score`` and a
      ``world_count`` of one or more — the two figures the argmax needs;
    * a candidate the objectives do not cover — a candidate with no objective
      names no score to rank it by;
    * an objective keyed to a ``module_id`` no candidate carries — an objective
      for a revision that did not run;
    * a **tie** on the maximum score — two candidates sharing the top score,
      over which the argmax is undefined; picking one by iteration order would
      be a selection that changed with nothing, so the refusal names both and
      states the repair: the loop must break the tie by a fact outside the
      aggregate, or keep the incumbent.

    The maximum is taken over the objectives' own ``score`` field — never a
    re-derived figure — so the verdict and the number cannot disagree.  It is
    deterministic and order-independent: the winner is the candidate whose
    objective score is strictly greater than every other, so the same
    candidate set and objectives answer the same winner (or the same refusal)
    regardless of mapping iteration order or candidate order.

    Args:
        candidates: a non-empty sequence of candidate modules — the value
            feature 271 produces, read duck-typed by ``module_id`` and
            ``code_hash``.
        objectives: a mapping of ``module_id`` to an aggregated objective,
            read duck-typed by a finite ``score`` and a ``world_count`` of one
            or more — the same two figures feature 280's bar judges.

    Returns:
        The single winning candidate — the one whose objective carries the
        strictly-maximum ``score``.

    Raises:
        SelectionRequestError: on any of the refusals above, each naming what
            it is about, before anything is read.
    """
    ordered = _candidates_of(candidates)
    scored = _objectives_of(objectives)

    missing = [module_id for module_id in ordered if module_id not in scored]
    if missing:
        raise SelectionRequestError(
            f"{SELECT_REQUEST_CODE}: the argmax ranks each candidate by its "
            f"aggregated objective, and {len(missing)} of the "
            f"{len(ordered)} candidate(s) — {sorted(missing)} — carry no "
            "objective: a candidate with no score names nothing to rank it by, "
            "so the argmax over the set is undefined. §C5's loop aggregates "
            "each candidate under §7 before it selects, so every candidate it "
            "hands here carries a figure (feature 274)"
        )
    orphaned = [module_id for module_id in scored if module_id not in ordered]
    if orphaned:
        raise SelectionRequestError(
            f"{SELECT_REQUEST_CODE}: an objective is keyed to a module id no "
            f"candidate carries — {sorted(orphaned)}: an objective for a "
            "revision that did not run names a score that belongs to no "
            "candidate here, and ranking on it would crown a revision the set "
            "does not contain. §C5's loop aggregates exactly the candidates it "
            "produced, so every objective names one (feature 274)"
        )

    best = _strictly_best(ordered, scored)
    if best is None:
        tied = sorted(
            {module_id for module_id in ordered if scored[module_id] == _top(scored)}
        )
        raise SelectionRequestError(
            f"{SELECT_REQUEST_CODE}: the argmax is undefined over a tie — two "
            f"candidates share the top aggregated score {scored[tied[0]]}: "
            f"{tied}. Picking one by iteration order would be a selection that "
            "changed with nothing, so the winner is refused rather than broken; "
            "the loop must break the tie by a fact outside the aggregate (a "
            "held-out reading, the incumbent's priority) or keep the incumbent, "
            "which is the paper's ``V^m★ ≥ V^0`` holding by construction "
            "(feature 273) — feature 280's bar is the fact outside the "
            "aggregate that §12.1 means the loop to break ties with (feature "
            "274)"
        )
    return _candidate_by_id(ordered_candidates=candidates, module_id=best)


# -- the act ------------------------------------------------------------------


def commit_selection(
    candidates: Any,
    *,
    strata: Any,
    beta: Any,
    iteration_id: str | None = None,
    database_url: Any = None,
    env: Mapping[str, str] | None = None,
    lam: float | None = None,
) -> Any:
    """Resolve the pool, aggregate each candidate under §7, crown and persist the winner.

    The store-seam half of feature 274, and the feature's only act.  It
    resolves the database the deployment names (an explicit URL first, then
    ``DATABASE_URL``, refused when neither names a ``sqlite`` path this member
    can speak), reads the sweep's evidence back from the pool's own
    ``replay_score`` table directly — a ``sqlite3`` connection opened against
    the resolved path, the same read-time seam :func:`dreaming.paired._pool_arm`
    takes, because the composed replay component exposes only the writer
    ``persist_replay_score`` and no reader of the score rows — groups each
    candidate's rows into the regime strata the caller hands in, aggregates
    each candidate over its worlds under §7 with feature 263's
    ``aggregate_objective`` (reached through the scoring member's namespace,
    never the composed seat), takes :func:`select_argmax`'s winner, and
    persists one row into ``policy_revision`` directly — feature 274 is the
    table's sole writer, because the replay member's writer lands in
    ``replay_score``, not here.

    The ``strata`` are the regime partition the blend is taken over — a mapping
    of stratum name to the world ids that belong to it, the same strata-keyed
    mapping feature 263's ``aggregate_objective`` takes — so the selector's
    score is the §7 blend of the stratum mean and the stratum minimum, not a
    raw average.  ``beta`` is §7.4's single scalar, *fixed within an episode*,
    and it selects which score rows are the episode's: the read is filtered to
    the rows scored at this ``beta``, so the argmax aggregates the scores the
    sweep earned at the episode's explore/exploit setting and never a reading
    taken under another.  A candidate with a world its rows name that no stratum
    covers is refused rather than dropped — a dropped world silently changes
    which tournament the argmax is taken over, the way plan_sweep refuses a
    world the split does not hold.

    The persisted row carries the winner's ``module_id`` as ``policy_version``,
    its ``code_hash``, its ``parent_version`` and its aggregated ``score`` as
    ``aggregate_score``, with ``selected`` TRUE.  The winner's identity is read
    from the candidate, not recomputed.

    The verdict is judged **before** feature 280's bar, not at it: this module
    crowns the argmax and writes it, and judges nothing against §12.1's
    selection-noise bar — that is feature 280's verdict, and the loop drives it
    between the sweep and the commit.  A caller that wants the bar met calls
    :func:`dreaming.bar.cycle_bar` (feature 280) and lets it raise before
    calling this, the way the sweep's docstring orders the loop — hold,
    produce, sweep, select, then bar.

    Args:
        candidates: the candidate set feature 271 produced — read duck-typed by
            ``module_id`` and ``code_hash``.
        strata: a mapping of stratum name to an iterable of the world ids that
            belong to it — the regime partition the §7 blend is taken over.
        beta: §7.4's single scalar — a finite number, the explore/exploit
            setting the episode's score rows were measured at.
        iteration_id: the cycle this selection is for — non-empty text when
            given, carried into the store's account of which cycle crowned the
            winner; the ``policy_revision`` table carries no iteration column,
            so it is a tag for the refusal and the operator's record, not a
            persisted field.
        database_url: an explicit store URL, tried first.
        env: the environment to read ``DATABASE_URL`` from when no URL is
            given — defaults to ``os.environ``.
        lam: the §7 blend's weight on the stratum minimum — a finite real in
            feature 263's band; ``None`` (the default) resolves to scoring's
            :data:`~scoring.LAMBDA_DEFAULT`, the band's midpoint, so the
            selector blends under the same knob the aggregate answers.

    Returns:
        The winning candidate — :func:`select_argmax`'s argmax, now persisted
        as the ``selected`` row of ``policy_revision``.

    Raises:
        SelectionRequestError: a malformed candidate set, ``strata``, ``beta``
            or ``lam`` — refused before anything is read.
        SelectionStoreError: the store's face — no database, a database holding
            no pool, a candidate with a world the strata do not cover, an
            objective that would not aggregate, or a winner that measured but
            whose row would not land.
    """
    ordered = _candidates_of(candidates)
    strata = _validated_strata(strata)
    episode_beta = _validated_beta(beta)
    weight = _require_lambda(lam)

    path = _selection_path(database_url, env)
    with closing(sqlite3.connect(path)) as connection:
        present = pool_tables_present(connection)
        if REPLAY_SCORE_TABLE not in present:
            raise SelectionStoreError(
                f"{SELECT_STORE_CODE}: selecting the argmax reads the sweep's "
                f"evidence from the pool's own {REPLAY_SCORE_TABLE!r} table, and "
                f"this database holds no {REPLAY_SCORE_TABLE!r} — the pool the "
                "dreaming loop runs over is not here, so there is no score to "
                "aggregate and no winner to crown. Point DATABASE_URL at the "
                "database the replay pool lives in (feature 274)"
            )
        objectives = {
            module_id: _aggregate_candidate(
                connection, module_id, episode_beta, strata, weight
            )
            for module_id in ordered
        }
        winner = select_argmax(candidates, objectives)
        _persist_winner(connection, winner, objectives[winner.module_id], iteration_id)
    return winner


# -- the store seam's private vocabulary --------------------------------------


def _aggregate_candidate(
    connection: sqlite3.Connection,
    module_id: str,
    beta: float,
    strata: Mapping[str, tuple[str, ...]],
    lam: float,
) -> Any:
    """One candidate's §7 objective — read its rows, group into strata, blend.

    Reads the candidate's ``replay_score`` rows at the episode's ``beta`` (the
    last reading per world, in ``id`` order — a repeated read answers the same
    arm in any process, the §12 ordering rule every store in this workspace
    restates), groups them into the caller's strata, and blends them under §7
    with feature 263's ``aggregate_objective``, reached through the scoring
    member's namespace at call time so this module stays import-cheap.

    A world the rows name that no stratum covers is refused rather than
    dropped — a dropped world silently changes which tournament the argmax is
    taken over.  A stratum the candidate scored no world of is refused by the
    aggregate's own law (``min_g`` over nothing is undefined), and that refusal
    is translated here into this module's store word, because a caller that
    crowned a winner must not meet feature 263's class for an aggregate this
    selector asked for.
    """
    rows = connection.execute(
        f"SELECT world_id, score FROM {REPLAY_SCORE_TABLE} "
        "WHERE policy_version = ? AND beta = ? "
        "AND world_id IS NOT NULL AND score IS NOT NULL ORDER BY id",
        (module_id, beta),
    ).fetchall()
    by_world: dict[str, float] = {}
    for world_id, score in rows:
        by_world[world_id] = float(score)

    grouped: dict[str, dict[str, _RowScore]] = {name: {} for name in strata}
    uncovered: list[str] = []
    for world_id, score in by_world.items():
        placed = False
        for name, world_ids in strata.items():
            if world_id in world_ids:
                grouped[name][world_id] = _RowScore(world_id, score)
                placed = True
                break
        if not placed:
            uncovered.append(world_id)
    if uncovered:
        raise SelectionStoreError(
            f"{SELECT_STORE_CODE}: candidate {module_id!r} scored world(s) "
            f"{sorted(uncovered)} that no stratum covers — {sorted(strata)}: a "
            "world the blend's strata do not name cannot be placed in the §7 "
            "aggregate, and dropping it would silently change which tournament "
            "the argmax is taken over, so the candidate is refused rather than "
            "thinned. §C5's loop hands the selector the same strata it labelled "
            "the pool with, so every world the candidate scored sits in one "
            "(feature 274)"
        )

    aggregate_objective = _scoring_member_objective()
    try:
        return aggregate_objective(grouped, lam=lam)
    except Exception as refusal:  # feature 263's AggregationError, translated
        raise SelectionStoreError(
            f"{SELECT_STORE_CODE}: candidate {module_id!r} could not be "
            f"aggregated under §7 over the caller's strata — {refusal}. The "
            "selector blends each candidate over exactly the strata it was "
            "handed, and a candidate that scored no world of a stratum leaves "
            "that stratum empty, which §7's blend refuses rather than zeroing — "
            "the winner is crowned over a candidate set every member of which "
            "aggregated cleanly (feature 274)"
        ) from refusal


def _persist_winner(
    connection: sqlite3.Connection,
    winner: Any,
    objective: Any,
    iteration_id: str | None,
) -> str:
    """Write the winner's row into ``policy_revision`` directly, or translate.

    Feature 274 is the table's sole writer — the replay member's
    ``persist_replay_score`` lands in ``replay_score``, not here — so the row
    is a direct ``INSERT`` against this module's own connection, carrying the
    winner's ``module_id`` as ``policy_version``, its ``code_hash``, its
    ``parent_version`` and its aggregated ``score`` as ``aggregate_score``,
    with ``selected`` TRUE.  The winner's identity is read from the candidate,
    not recomputed.  Every failure on the way is a store fact — the row
    measured but would not land (a duplicate ``policy_version``, a hand on the
    table) — and is raised as :class:`~dreaming.errors.SelectionStoreError`
    with the database's own refusal chained, never swallowed.
    """
    policy_version = winner.module_id
    parent_version = getattr(winner, "parent_version", None)
    code_hash = winner.code_hash
    tag = f" for cycle {iteration_id!r}" if iteration_id else ""
    try:
        connection.execute(
            "INSERT INTO policy_revision "
            "(policy_version, parent_version, code_hash, aggregate_score, selected) "
            "VALUES (?, ?, ?, ?, TRUE)",
            (policy_version, parent_version, code_hash, float(objective.score)),
        )
        connection.commit()
    except Exception as refusal:
        raise SelectionStoreError(
            f"{SELECT_STORE_CODE}: the winning candidate {policy_version!r}"
            f"{tag} measured and won, but its ``policy_revision`` row would not "
            f"land — {refusal}. Feature 274 is the table's sole writer and "
            "writes the winner directly (the replay member's writer lands in "
            "``replay_score``, not here); a row that cannot land is refused "
            "rather than retried over a winner that would silently re-crown "
            "another (feature 274)"
        ) from refusal
    return policy_version


# -- validation and resolution helpers ----------------------------------------


def _candidates_of(value: Any) -> tuple[str, ...]:
    """Read the candidate set's module ids — the ids the argmax ranks, or refuse.

    A non-empty sequence of candidate modules, read duck-typed by ``module_id``
    — each a non-empty text identity, the way :func:`dreaming.sweep` reads
    them, because the module loader's synthetic-name re-execution means an
    ``isinstance`` would refuse the very objects composition produces.  A bare
    candidate module is refused where a sequence belongs, and an empty set is
    refused: an argmax over nothing is a tournament nobody entered.
    """
    if isinstance(value, (str, bytes)) or not isinstance(value, Iterable):
        raise SelectionRequestError(
            f"{SELECT_REQUEST_CODE}: the argmax is taken over the candidate set "
            f"feature 271 produced — a non-empty sequence of candidate modules "
            f"— got {value!r} ({type(value).__name__}). A bare candidate names "
            "one revision, and an argmax over one is not a selection; the loop "
            "hands the selector the ``M`` it produced (feature 274)"
        )
    ordered = [candidate for candidate in value]
    if not ordered:
        raise SelectionRequestError(
            f"{SELECT_REQUEST_CODE}: the argmax is taken over a non-empty "
            "candidate set — got none. An argmax over nothing is a tournament "
            "nobody entered, not a null selection, so the winner is refused "
            "rather than defaulted; §C5's loop produces ``M ≥ 1`` revisions "
            "before it selects (feature 274)"
        )
    ids: list[str] = []
    for candidate in ordered:
        module_id = getattr(candidate, "module_id", None)
        if (
            isinstance(module_id, bool)
            or not isinstance(module_id, str)
            or not module_id.strip()
        ):
            raise SelectionRequestError(
                f"{SELECT_REQUEST_CODE}: a candidate is addressed by its "
                f"``module_id`` — got {module_id!r} ({type(module_id).__name__}) "
                f"on {candidate!r}. It is the version this selector writes as "
                "``policy_revision.policy_version`` and how the argmax's winner "
                "is named, and a candidate that cannot be named crowns no "
                "revision (feature 274)"
            )
        ids.append(module_id)
    return tuple(ids)


def _candidate_by_id(*, ordered_candidates: Any, module_id: str) -> Any:
    """The candidate carrying ``module_id`` — the winner, by identity not index.

    Walks the produced sequence once and returns the candidate whose
    ``module_id`` is the winner's, so the selector persists the value the loop
    handed it — its ``code_hash`` and ``parent_version`` read, never
    recomputed.  A miss here is a programming fault, not a caller fault (the
    verdict already proved every winner id names a candidate), so it answers
    the bare fact rather than a malformed-ask class.
    """
    for candidate in ordered_candidates:
        if getattr(candidate, "module_id", None) == module_id:
            return candidate
    raise AssertionError(  # pragma: no cover - the verdict guarantees a match
        f"select_argmax returned {module_id!r}, which names no candidate in the "
        "set it was given"
    )


def _objectives_of(value: Any) -> dict[str, float]:
    """Read each objective's ``score`` — the figure the argmax ranks, or refuse.

    A mapping of ``module_id`` to an aggregated objective, read duck-typed by
    its ``score`` (a finite real — a ``−∞`` miss's number may not be
    counterfeited, the aggregate's own ``−∞`` argument one level up) and its
    ``world_count`` (a whole number of one or more — an objective aggregated
    over no world names no score to rank by).  The verdict keeps the figure,
    never a re-derived one, so the winner and the number cannot disagree.
    """
    if isinstance(value, (str, bytes)) or not isinstance(value, Mapping):
        raise SelectionRequestError(
            f"{SELECT_REQUEST_CODE}: the argmax ranks each candidate by its "
            f"aggregated objective — a mapping of module id to objective — got "
            f"{value!r} ({type(value).__name__}). A bare objective names one "
            "figure, and an argmax that ranked a set by one is not a selection; "
            "the loop hands the selector one objective per candidate (feature "
            "274)"
        )
    scored: dict[str, float] = {}
    for module_id, objective in value.items():
        if not isinstance(module_id, str) or not module_id.strip():
            raise SelectionRequestError(
                f"{SELECT_REQUEST_CODE}: an objective is keyed by a module id — "
                f"got {module_id!r} ({type(module_id).__name__}); it names the "
                "candidate the figure ranks, and an objective that cannot be "
                "named ranks no revision (feature 274)"
            )
        score = getattr(objective, "score", None)
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise SelectionRequestError(
                f"{SELECT_REQUEST_CODE}: an objective is ranked by its ``score`` "
                f"— a finite real — got {score!r} ({type(score).__name__}) for "
                f"module id {module_id!r}. The §7 blend's figure is a real, and "
                "a score that is not one names nothing to rank a candidate by "
                "(feature 274)"
            )
        if not math.isfinite(float(score)):
            raise SelectionRequestError(
                f"{SELECT_REQUEST_CODE}: an objective's ``score`` is a finite "
                f"real — got {score!r} for module id {module_id!r}. A NaN "
                "compares false against every score and would silently drop out "
                "of the argmax, and the only −∞ the objective's vocabulary holds "
                "is the non-committing miss, which feature 222 owns and which "
                "never carries a pick, so no objective may counterfeit it "
                "(feature 274)"
            )
        world_count = getattr(objective, "world_count", None)
        if (
            isinstance(world_count, bool)
            or not isinstance(world_count, int)
            or world_count < 1
        ):
            raise SelectionRequestError(
                f"{SELECT_REQUEST_CODE}: an objective carries a ``world_count`` "
                f"of one or more — got {world_count!r} "
                f"({type(world_count).__name__}) for module id {module_id!r}. "
                "An objective aggregated over no world names no score to rank "
                "a candidate by, and the argmax over it would be a selection "
                "over nothing (feature 274)"
            )
        scored[module_id] = float(score)
    return scored


def _strictly_best(ordered: tuple[str, ...], scored: dict[str, float]) -> str | None:
    """The module id with a score strictly greater than every other, or ``None``.

    Order-independent by construction — the winner is the id whose score beats
    every other, so a tie (two ids sharing the top) answers ``None`` and the
    same set answers the same winner regardless of ``ordered`` or mapping
    order, the determinism law the aggregate holds one judgment over.
    """
    best_id: str | None = None
    best_score = -math.inf
    tied = False
    for module_id in ordered:
        figure = scored[module_id]
        if figure > best_score:
            best_id, best_score, tied = module_id, figure, False
        elif figure == best_score:
            tied = True
    return None if tied else best_id


def _top(scored: dict[str, float]) -> float:
    """The maximum score the objectives carry — the tie's shared figure."""
    return max(scored.values())


def _validated_strata(value: Any) -> Mapping[str, tuple[str, ...]]:
    """The regime partition the §7 blend is taken over — a mapping, or refuse.

    A mapping of stratum name to an iterable of non-empty world ids — the same
    strata-keyed mapping feature 263's ``aggregate_objective`` takes.  Refused
    as :class:`~dreaming.errors.SelectionRequestError` before the store is
    touched: not a mapping (a flat collection is the plain mean across regimes,
    the aggregation feature 264 rejects, and it cannot say which worlds share a
    stratum), a bare string (it would otherwise be read as an iterable of
    characters, a message about the wrong repair entirely), a blank stratum
    name, an empty stratum (a stratum that holds no world lends no figure to
    the blend, and a fabricated ``0.0`` would be read as a measured
    catastrophic regime), or a world id that is not non-empty text.  The
    world-id iterables are materialised to tuples so the read can test
    membership against them once per world.
    """
    if isinstance(value, (str, bytes)) or not isinstance(value, Mapping):
        raise SelectionRequestError(
            f"{SELECT_REQUEST_CODE}: the §7 blend is taken over regime strata — "
            f"a mapping of stratum name to the world ids that belong to it — "
            f"got {value!r} ({type(value).__name__}). A flat collection is the "
            "plain mean across regimes, which feature 264 rejects, and it cannot "
            "say which worlds share a stratum; the selector needs the partition "
            "the loop labelled the pool with (feature 274)"
        )
    strata: dict[str, tuple[str, ...]] = {}
    for name, world_ids in value.items():
        if isinstance(name, bool) or not isinstance(name, str) or not name.strip():
            raise SelectionRequestError(
                f"{SELECT_REQUEST_CODE}: a stratum is named by a non-empty "
                f"string — got {name!r} ({type(name).__name__}); a stratum that "
                "cannot be named cannot be reported as the blend's worst regime, "
                "so the partition the selector aggregates over is refused "
                "(feature 274)"
            )
        if isinstance(world_ids, (str, bytes)) or not isinstance(world_ids, Iterable):
            raise SelectionRequestError(
                f"{SELECT_REQUEST_CODE}: the worlds of stratum {name!r} arrive as "
                f"an iterable of world ids — got {world_ids!r} "
                f"({type(world_ids).__name__}). A bare string names one world, "
                "not the set a stratum holds, and would otherwise be read as an "
                "iterable of characters; the selector groups each candidate's "
                "rows into the strata by world id (feature 274)"
            )
        ids = [world_id for world_id in world_ids]
        if not ids:
            raise SelectionRequestError(
                f"{SELECT_REQUEST_CODE}: stratum {name!r} holds no worlds — a "
                "stratum that lends no world lends no figure to the §7 blend, "
                "and a fabricated 0.0 would be read as a measured catastrophic "
                "regime, which is worse than the hole. Name it in the coverage "
                "ledger and let feature 286's ``empty_stratum`` report it; the "
                "selector refuses to aggregate over a stratum it was not given "
                "worlds for (feature 263, feature 274)"
            )
        for world_id in ids:
            if (
                isinstance(world_id, bool)
                or not isinstance(world_id, str)
                or not world_id.strip()
            ):
                raise SelectionRequestError(
                    f"{SELECT_REQUEST_CODE}: a world id in stratum {name!r} is a "
                    f"non-empty string — got {world_id!r} "
                    f"({type(world_id).__name__}); it is how the selector places "
                    "a candidate's row into the partition, and a world that "
                    "cannot be named is placed nowhere (feature 274)"
                )
        strata[name] = tuple(ids)
    if not strata:
        raise SelectionRequestError(
            f"{SELECT_REQUEST_CODE}: the §7 blend is taken over one or more "
            "strata — got none. ``min_g`` over no stratum is undefined, and no "
            "neutral figure is invented for a blend over nothing; the loop hands "
            "the selector the strata it labelled the pool with (feature 274)"
        )
    return strata


def _validated_beta(value: Any) -> float:
    """§7.4's single scalar — a finite number, the episode's explore/exploit setting.

    Fixed within an episode, so it is one value for the whole selection rather
    than one per candidate: a selector whose rows carried different betas would
    aggregate scores measured under different explore/exploit settings, and the
    argmax over them would compare two regimes while every figure looked like a
    score.  Required and with no default, following feature 238's ``width`` and
    :meth:`replay.ReplayEngine.persist_replay_score`'s own ``beta``: the caller
    holds it, this module does not decide it.  The read filters the pool's rows
    to this beta, so the winner is crowned over the scores the sweep earned at
    the episode's setting.

    Refused as :class:`~dreaming.errors.SelectionRequestError` before the store
    is touched — a ``bool``, a non-number, or a non-finite figure (an infinity
    is not a hyperparameter, it is a value outside the space the scoring was
    made in).
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SelectionRequestError(
            f"{SELECT_REQUEST_CODE}: the selector reads the pool's score rows at "
            f"a beta — §7.4's single scalar, fixed within an episode — a finite "
            f"number, got {value!r} ({type(value).__name__}). The beta is the "
            "explore/exploit setting the episode's scores were measured at, and "
            "a value that is not a number names no setting a reader could "
            "reproduce (feature 274)"
        )
    figure = float(value)
    if not math.isfinite(figure):
        raise SelectionRequestError(
            f"{SELECT_REQUEST_CODE}: the selector reads the pool's score rows at "
            f"a finite beta — got {figure!r}. An infinity is not a "
            "hyperparameter: it is a value outside the space the scoring was "
            "made in, and every row the selector read would claim to have been "
            "measured under a setting no reader could reproduce (feature 274)"
        )
    return figure


def _require_lambda(value: float | None) -> float:
    """The §7 blend's weight on the stratum minimum — feature 263's band, or refuse.

    ``None`` (the default) resolves to scoring's :data:`~scoring.LAMBDA_DEFAULT`
    — the band's midpoint, consumed rather than respelled, so the selector
    blends under the same knob the aggregate answers.  A handed value must be a
    finite real in the band, the value's own law as much as the verb's — the
    sentence's second clause is a fact about the score returned.  Refused as
    :class:`~dreaming.errors.SelectionRequestError` before the store is
    touched.
    """
    if value is None:
        return _scoring_member().LAMBDA_DEFAULT
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SelectionRequestError(
            f"{SELECT_REQUEST_CODE}: the §7 blend's ``lam`` is a finite real in "
            f"feature 263's band ``[0.5, 0.7]`` — got {value!r} "
            f"({type(value).__name__}). It is the weight on the worst stratum, "
            "and a value that is not a real names no blend a reader could "
            "reproduce (feature 274)"
        )
    figure = float(value)
    if not math.isfinite(figure) or figure < 0.5 or figure > 0.7:
        raise SelectionRequestError(
            f"{SELECT_REQUEST_CODE}: the §7 blend's ``lam`` is a finite real in "
            f"feature 263's band ``[0.5, 0.7]`` — got {figure!r}. §7.2's blend "
            "is ``(1 − λ)·mean + λ·min`` with ``λ ∈ [0.5, 0.7]``; a weight "
            "outside the band is either a plain mean across regimes (feature "
            "264's refusal) or a pure minimum nobody specified, and the selector "
            "blends under the band the aggregate answers (feature 274)"
        )
    return figure


def _scoring_member() -> Any:
    """The scoring member's own namespace, reached lazily.

    Reached through ``importlib.import_module("scoring")`` — the way the
    policy-runtime member's free seams reach a sibling, **not** the composed
    ``app.modules.scoring`` seat, which answers only the per-world objective
    (:func:`scoring.world_objective_component`) and not the blend.  Resolved
    inside the function so this module stays import-cheap and the factory's
    scan — which imports this package to fire its ``@register`` — pays nothing
    for a module it never composes.  ``None`` from the member is a refusal, not
    a silent success: a deployment that composed no scoring verb has no §7
    blend to crown a winner under.
    """
    member = importlib.import_module("scoring")
    return member


def _scoring_member_objective() -> Any:
    """Feature 263's ``aggregate_objective`` — the §7 blend — reached lazily.

    Read off the scoring member's namespace (:func:`_scoring_member`) rather
    than the composed seat, which answers only the per-world objective and not
    the blend.  Absent is a refusal, not a silent success: a deployment that
    composed no §7 blend has no scalar to crown a winner by.
    """
    member = _scoring_member()
    objective = getattr(member, "aggregate_objective", None)
    if not callable(objective):
        raise SelectionStoreError(
            f"{SELECT_STORE_CODE}: selecting the argmax blends each candidate "
            "under §7 with scoring's ``aggregate_objective``, and the scoring "
            "member exposes none — reached through its own namespace, not the "
            "composed seat, which answers only the per-world objective. A "
            "deployment without the §7 blend has no scalar to crown a winner by "
            "(feature 274)"
        )
    return objective


def _selection_path(database_url: Any, env: Mapping[str, str] | None) -> Path:
    """Resolve the pool the selection is taken over: the URL, then ``DATABASE_URL``.

    The same resolution order :func:`dreaming.split._split_path`,
    :func:`dreaming.cap._cap_path` and :func:`dreaming.paired._pool_path` take,
    and the same refusal stance: an act that means to read the pool and
    resolves nothing is refused by name rather than answered with ``None``.  A
    URL this member cannot speak is refused in the selection's own vocabulary,
    translated at the seam from the one spelling of what a ``sqlite:///`` URL
    names — the discipline the workspace states for error vocabularies and this
    member applies at each store seam.
    """
    url = (
        database_url
        if database_url is not None
        else (os.environ if env is None else env).get("DATABASE_URL", "")
    )
    if not isinstance(url, str) or not url.strip():
        raise SelectionStoreError(
            f"{SELECT_STORE_CODE}: selecting the argmax reads the sweep's "
            "evidence from the pool the dreaming loop runs over, and that needs "
            "the database it lives in — pass it explicitly or set "
            "DATABASE_URL. A selection taken over no database would crown a "
            "winner over scores that were never read, and the figures would "
            "look exactly like ones that had been (feature 274)"
        )
    try:
        return sqlite_path(url)
    except Exception as refusal:
        raise SelectionStoreError(
            f"{SELECT_STORE_CODE}: selecting the argmax reads the pool's own "
            "score rows from the database the dreaming loop runs over, and the "
            f"URL given does not name one this member can speak — see the "
            f"refusal it raised: {refusal}. The winner is crowned over the "
            "evidence the sweep wrote, which lives in one store (feature 274)"
        ) from refusal
