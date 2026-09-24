"""The dreaming loop's hold on the replay pool — feature 270.

app_spec.xml, *Dreaming Loop & Meta-Selection*, feature 270:

    System rejects a replay pool mutation during a dreaming iteration, holding
    the pool fixed for the cycle.

docs/alpha-engine-prd.md §C5 states the rule as the *first clause of the loop*
rather than as a caveat on it — *"Per outer iteration: hold the replay pool
fixed, run M code revisions of π, evaluate each on every stored tree, select
the argmax under §7"* — and §12.1 says why the qualifier is load-bearing:

    The dreaming loop **overfits its own replay pool**.  The paper's guarantee
    ``V^{m★} ≥ V^0`` holds on the *fixed history*; selecting the max over ``M``
    revisions scored on a handful of worlds is the same multiple-testing
    problem one level up.

The guarantee is a guarantee about a fixed history, so the history has to
actually be fixed.  This member is the part of the system that does the fixing
and the part that refuses the moving.

What it is
----------

One component, :data:`COMPONENT_NAME`, sitting over the database the replay
pool already lives in.  :meth:`~dreaming.cycle.CycleFreeze.open` writes a hold
row naming the iteration and recording the pool's **commitment** — a digest
over which worlds the tournament is held over — and installing a
``BEFORE INSERT``/``UPDATE``/``DELETE`` guard per pool table per operation;
:meth:`~dreaming.cycle.CycleFreeze.release` closes the hold;
:meth:`~dreaming.cycle.CycleFreeze.verify` re-reads the commitment and answers
whether the pool moved.

**The enforcement is the trigger, not a wrapper.**  A Python guard is a rule
its caller can walk around by opening the database itself, and the pool's
writers are not all this member's callers — the replay member writes scores
(``replay_score``, migration ``0109``), the bootstrap member authors worlds
(``bootstrap_world``, features 188/191), and an operator bisecting a
deployment has a ``sqlite3`` shell.  A rule about a *store* has to live in the
store, so the refusal is a ``RAISE(ABORT, ...)`` in the database and the Python
API is only its translation: a caller that used this member reads a
:class:`~dreaming.errors.PoolFrozenError` naming the holding iteration, and a
caller that bypassed it is refused just the same, by SQLite, with the raw
abort.

**Three members already obey this rule.  This is the one that enforces it.**
:mod:`tripwires.excise` (feature 132) exists to excise a poisoned subtree from
the replay pool and takes the one decision that makes it compatible with
feature 270 — it never deletes a row, because *"feature 270 forbids exactly
that mutation"*; :mod:`canary._void` (feature 144) makes the identical call for
the identical reason, and :mod:`bootstrap._census` (feature 186) reads the
pool's two halves without writing either.  Three members were built to this
rule before this module existed; what was missing was the refusal, and the
account of which cycle is holding what.

What it is not
--------------

**It carries the ladder's floor as a second sentence, not a third face of
feature 270.**  §12.1's floor — *"below 20 worlds: do not run dreaming; fixed
exploration; accumulate history"* — is a precondition on a run that has *not*
started, which is feature 275's sentence.  It lives in this member as its own
code (``pool_too_thin``, :data:`POOL_TOO_THIN_CODE`) and its own class
(:class:`~dreaming.errors.PoolTooThinError`), a sibling of feature 270's
``pool_frozen`` rather than a face of it: feature 270's subject is a cycle that
is *already going* and must not have its pool moved underneath it, and its
repair is *stop writing, or close the iteration*, while the floor's subject is
a run that has not begun and should not begin, and its repair is *grow the
pool, or run fixed exploration*.  The two sentences have different repairs, so
they are two classes under the one :class:`~dreaming.errors.DreamingError`
base, and the floor is a judgment over a count the caller already has —
:func:`dreaming.ladder.rejects_thin_pool` takes the figure, it never counts the
pool — which is the honest division between a verdict and a count.  What this
member gives the floor is the same honest pool size it gives feature 270: the
hold records ``world_count`` at the moment it opened, and a pool that is not
there is refused rather than counted as zero.

**It carries the revision cap's schedule and its per-cycle record as a third
sentence.**  §C5 runs ``M`` code revisions per outer iteration, and §12.1's
ladder caps ``M`` by the pool's size — *"20–50: dreaming with M capped at
8–10"*, *"50+: full dreaming, M = 30–40"* — so feature 277's sentence takes
the top rung: the cap rises to 40 (:data:`FULL_DREAMING_CAP`) once the pool
holds 50 or more worlds (:data:`FULL_DREAMING_WORLDS`).  The schedule
(:func:`dreaming.cap.revision_cap`) is the same shape the floor is — a
judgment over the count the caller already has, delegating the bottom rung to
feature 275's own refusal — and the record
(:func:`dreaming.cap.record_cycle_cap`) writes one row per cycle into this
member's own ``cycle_cap`` table (:data:`CYCLE_CAP_TABLE`), append-only, each
row carrying the pool size its cap was decided over.  The cap is persisted
rather than remembered because Appendix B's selection bar — ``advantage >
√(2 ln M) · σ_V / √n_worlds``, the bar feature 280 applies to the winning
revision — reads ``M`` back, and a bar computed over an ``M`` nobody recorded
is a bar over a number nobody ran.  The record takes the figure rather than
counting the pool (the same verdict-count split the floor states), refuses a
database that holds no pool for the same reason the freeze does — a cap over
a pool that is not there caps nothing — and its refusals are its own pair of
classes (:class:`~dreaming.errors.CapRequestError`,
:class:`~dreaming.errors.CapRecordError`), translated at the seam from the
member's one spellings of the shared rules, never borrowed from feature 270's
vocabulary.

**It carries the middle rung's ceiling as a fourth sentence, and that is the
half of the ladder the schedule cannot state.**  Feature 277 *answers* the cap
the thin band runs under — 10 — while feature 276 *refuses* a cycle that means
to run more than that while the pool sits in the band: *"System rejects a
revision count above 10 while the pool holds between 20 and 50 worlds, so the
selection bar stays low."*  The refusal is
:func:`dreaming.ceiling.rejects_uncapped_sweep`, the same verdict-over-counts
shape the floor is — the revision count the caller means to run and the pool's
size in, a refusal out — and it consumes rather than respells every ladder
figure it judges by: the band's cap is feature 277's
:data:`CAPPED_SWEEP_CAP`, its edges are feature 275's floor and feature 277's
:data:`FULL_DREAMING_WORLDS`.  So the number a cycle is *entitled to* on the
thin rung and the number it is *refused above* are one constant, and the
default judgment admits exactly what the schedule answers at every pool size.
Above the band there is no ceiling — the pool has cleared 50, the raise has
fired, and ``M`` is feature 277's to answer at 40 — and below it the refusal is
feature 275's, delegated, in the floor's own word, because a pool that may not
dream at all needs no cap on its sweep.  The one refusal the sentence itself
mints is :class:`~dreaming.errors.RevisionCeilingError`, its own class and
deliberately without a code word: its repair (*lower ``M`` to the band's cap,
or grow the pool until the raise applies*) is neither the floor's (*grow the
pool before dreaming at all*) nor the cap's (*re-consider the ask*), so a
caller that caught it as either would act on the wrong fact.  The reason the
ceiling exists at all is §12.1's own arithmetic: Appendix B's bar is
``advantage > √(2 ln M) · σ_V / √n_worlds``, ``§12.1`` computes ``n > 53``
worlds at ``M = 40``, and a pool of 20–50 is short of that by construction —
so a wider sweep is *available* only once the pool clears the band, and the
selection bar stays low because it cannot be raised.

**It carries the pool's train/holdout split as a fifth sentence.**  §12.1's
top rung reads *"50+: full dreaming, ``M = 30–40``, 70/30 train/holdout split
on worlds"*, and §10.3.1 spells the call with the feature's own clause as its
comment — ``train, holdout = pool.split(0.7, ...)  # select on train, report
on holdout``.  Feature 278's sentence (*"System splits the pool 70 to 30 into
train and holdout, which returns selection on train with reporting on
holdout"*) is that call: :func:`dreaming.split.split_replay_pool` resolves the
database the deployment names, reads the pool's worlds
(:func:`dreaming.split.pool_worlds` — a world once, whichever half names it
and however many score rows name it), and answers a
:class:`dreaming.split.PoolSplit` whose two halves are the pool's worlds
ranked by a digest over a rotation and each id.  The arithmetic is exact
rational largest-remainder — 20 worlds split 14/6, 50 split 35/15, and the
indivisible pool's odd world goes to the half with the larger remainder, ties
to the holdout — and the assignment is deterministic, so the same pool at the
same rotation answers the same split in any process.  The split exists because
a cycle that reported on the worlds it selected over would be grading its own
homework: §12.1's *"the dreaming loop overfits its own replay pool"* is the
warning, and a holdout the selection never touched is the mitigation.  Its
refusals are its own pair of classes
(:class:`~dreaming.errors.SplitRequestError`,
:class:`~dreaming.errors.SplitStoreError`) under the one base, with the thin
pool delegated to feature 275's refusal as the cap and the ceiling delegate
theirs — a pool too thin to dream on needs no train and no holdout.

**It carries the comparison's own shape as a sixth sentence, and that is the
half of §11.0 the split cannot state.**  §12.1's top rung and §10.3.1's bar are
both written against a *paired continuous statistic*, and §11.0 is where the
PRD says why: *"Raw FDR is a proportion, and proportions are power-poor …
Fix the statistic, not the ambition."*  Feature 281's sentence is that
instruction as a refusal — *"System rejects a difference-in-proportions
comparison, using a paired continuous statistic over the same worlds
instead"* — and :mod:`dreaming.paired` is the two halves of it:
:func:`dreaming.paired.rejects_proportion_comparison` is the **rejects**, a
verdict over figures the caller already holds (the shape the floor, the
ceiling and the schedule all take) that compares §11.0's two capacities and
refuses the comparison the pool cannot fund, naming the paired statistic the
caller should ask for instead; and
:func:`dreaming.paired.paired_ir_difference` is the replacement — the two
arms' per-world out-of-sample IR readings in, a
:class:`dreaming.paired.PairedDifference` out, tested paired over the worlds
**both** arms carry, world by world.  The pairing is the whole of the ~364 →
~56 improvement §11.0 computes: the arms replay the same worlds, so the
world-to-world variation cancels inside each difference and what is left has
the deviation ``σ_diff`` the PRD's arithmetic is written at.  A world only one
arm carries is therefore **refused** rather than dropped — dropping it
silently converts the comparison into the unpaired one §11.0 rejects, arriving
through the arithmetic instead of through the request, and the ``t`` figure
that comes out still looks paired.  The split (feature 278) is what makes the
*same worlds* a set the selection never touched; this is what makes the
comparison over them honest.  Its refusals are its own pair of classes
(:class:`~dreaming.errors.ProportionComparisonError` for the wrong statistic,
:class:`~dreaming.errors.PairedComparisonError` for worlds that will not pair)
under the one base, with the thin pool delegated to feature 275's refusal as
the cap, the ceiling and the split delegate theirs.

**It carries the family-shaped holdout as a seventh sentence, and that is the
half of §4.5 the world-shaped split cannot state.**  Feature 278's split
protects the *report* from the *selection*, but it samples worlds, not
families: a random 30% of the pool carries every family the pool carries,
nearly in proportion, so the holdout worlds of family ``F`` sat beside train
worlds of ``F`` in the pool the selection read — and a policy that had
memorised ``F``'s texture passes that holdout with a ΔIR that is not
transfer.  Feature 282's sentence (*"System computes leave-one-family-out
transfer by holding an entire theme root out of the pool, which returns the
delta on that held-out theme"*) is §4.5's other holdout, the one
*"memorized family texture"* cannot survive: :mod:`dreaming.transfer` holds
the root out **entirely** — every world whose theme root is the family named
leaves the pool — and answers the paired delta on that family's worlds alone
(:func:`dreaming.transfer.family_transfer`, §11.1's ``lofo_delta_ir`` line
made to run), with the store seam
(:func:`dreaming.transfer.pooled_family_transfer`) reading both arms from the
pool's own ``replay_score`` rows and refusing a family census that disagrees
with the pool's membership in either direction.  The family a world belongs
to is not a column of the pool — it is the world's own fact, carried by the
question seam's ``meta()`` — so the caller hands the census in whole, and
the arithmetic is feature 281's, restricted to the held-out family's worlds
and never respelled; the floor judges the pool that *remains*, delegated to
feature 275's refusal as the cap, the ceiling and the split delegate theirs.
Its refusals are its own pair of classes
(:class:`~dreaming.errors.TransferRequestError` for the ask's own facts,
:class:`~dreaming.errors.TransferStoreError` for a store that holds no pool
or no honest census of one) under the one base.

**It carries the tournament's own verdict as an eighth sentence.**  §C5's
loop ends *"select the argmax under §7"*, and §12.1 names what is wrong with
stopping there: the winner is a **max**, and a max is biased — *"the
dreaming loop overfits its own replay pool … selecting the max over ``M``
revisions … is the same multiple-testing problem one level up"*.  Appendix
B's bar is the width of that problem, ``advantage > √(2 ln M) · σ_V /
√n_worlds`` — the expected maximum of ``M`` scores that carry no advantage
at all, §7.3's null max-Sharpe figure stated one level up — and feature
280's sentence (*"System rejects a winning revision whose advantage falls
below the square root of twice the log of M scaled by score deviation"*)
is that bar applied to the winner: :func:`dreaming.bar.selection_bar`
answers the figure, :func:`dreaming.bar.rejects_unbarred_winner` is the
verdict over figures the caller already holds (the shape the floor, the
ceiling, the schedule and the comparison's own *rejects* all take), and
:func:`dreaming.bar.cycle_bar` is the seam that reads ``M`` back from
feature 277's record — the **newest** ``cycle_cap`` row naming the
iteration, because a retried cycle is re-decided and the decision in force
is the last one — and judges feature 281's
:class:`~dreaming.paired.PairedDifference` at it: the advantage, the
deviation and the world count one comparison already carries, since §12.1's
``σ_V ≈ 0.8`` and §11.0's ``σ_diff ≈ 0.8`` are one figure and the
sections' ``n > 53`` and ``~56`` are two derivations of the same pool.  The
edge is strict — a winner exactly at the bar has not survived it, the edge
:meth:`~dreaming.paired.PairedDifference.clears` states for the gate's own
criterion — and the repair is neither a re-ask nor a re-point: it is *keep
the incumbent*, which is the paper's ``V^{m★} ≥ V^0`` holding by
construction (feature 273 keeps the incumbent in the candidate set, so
when nothing clears, the incumbent *is* the argmax).  Its refusals are its
own three classes (:class:`~dreaming.errors.BarRequestError` for the ask's
own facts, :class:`~dreaming.errors.BarRecordError` for a store that holds
no recorded ``M`` — the *"a bar computed over an ``M`` nobody recorded is a
bar over a number nobody ran"* refusal — and
:class:`~dreaming.errors.SelectionBarError` for the verdict itself,
opening with ``advantage_below_bar``), with the cap's request and record
refusals translated at the seam, never borrowed.

**It carries the holdout's rotation as a ninth sentence, and that is the
clause of §12.1's top rung the split's own call leaves as an argument.**
§10.3.1 spells the split with it — ``pool.split(0.7,
rotate_each_cycle=True)`` — and §12.1's ladder row carries it as the
rung's last clause: *"50+: full dreaming, ``M = 30–40``, 70/30
train/holdout split on worlds, holdout rotated each cycle."*  Feature
279's sentence (*"System rotates the holdout split every cycle,
persisting which worlds were held out per iteration"*) is both halves of
that clause, and :mod:`dreaming.rotation` is its two acts:
:func:`dreaming.rotation.cycle_rotation` is the member's own law — **a
cycle's rotation is its own name**, the validated iteration id handed to
feature 278's rank as the discriminator, so *the split of cycle N* is
recomputable from the cycle's name alone and the append-only history is
never an input to the splits it describes — and
:func:`dreaming.rotation.record_cycle_holdout` is the persisting half:
read the pool, take the split at the cycle's own rotation, and write one
row per cycle into this member's own ``cycle_holdout`` table
(:data:`CYCLE_HOLDOUT_TABLE`) carrying **which worlds were held out**, in
the split's own rank order, beside the pool's size and the exact share the
half was taken by, with :func:`dreaming.rotation.cycle_holdouts` answering
the account an operator asks for after the fact: *which worlds did each
cycle report on?*  The rotation exists because a holdout that never moves
is a holdout the loop can *learn* — the winner of every cycle selected on
the same 70% and reported on the same 30% is §12.1's multiple-testing
problem one level up again, spread over time — and the record exists
because §12's M3 exit criterion is *"evaluated on worlds held out of the
dreaming loop"*, and a criterion read over worlds nobody recorded is a
criterion read over nothing.  Its refusals are its own pair of classes
(:class:`~dreaming.errors.HoldoutRequestError` for the ask's own facts,
:class:`~dreaming.errors.HoldoutRecordError` for a store that holds no
pool or a row that will not read back) under the one base, with the thin
pool delegated to feature 275's refusal as the cap, the ceiling and the
split delegate theirs — a pool too thin to dream on has no halves to
rotate.

**It carries the sweep's production as its first sentence.**  §C5's loop
begins *"run ``M`` code revisions of ``π``"*, and feature 271's sentence is
that production: :mod:`dreaming.reviser` answers ``M`` candidate modules, one
per revision index ``1..M``, each a complete policy source the replay engine
can import and replay.  A candidate (:class:`dreaming.reviser.CandidateModule`)
carries its revised ``source``, its ``code_hash`` (the sha256 identity feature
274 persists to ``policy_revision.code_hash``), its ``module_id`` (the version
feature 274 writes as ``policy_revision.policy_version``), its ``parent_version``
(``π^0 = π_t``'s version, so feature 273 can add the incumbent back) and its
``revision_index``.  The default reviser is a seeded, deterministic,
structure-preserving perturbation — :func:`dreaming.reviser.default_reviser`
parses the incumbent, jitters only its numeric-literal magnitudes within
:data:`dreaming.reviser.REVISION_BAND`, and unparses — so a candidate descended
from an admitted incumbent carries none of feature 230's anti-patterns nor
feature 231's learned component, admissible by construction; the loop screens
each with policy-runtime's gate (feature 230, in the policy-runtime member,
which this member never imports) before replay.  The production is deterministic
in ``(source, count, seed)`` and deduplicates by ``code_hash``, refusing with
:class:`~dreaming.errors.RevisionError` when the incumbent cannot fund ``M``
distinct candidates — a production verdict, not a malformed ask — while a
malformed ask is :class:`~dreaming.errors.RevisionRequestError`.  It is pure and
store-free: it reads the source the caller holds, opens no database and imports
nothing from :mod:`dreaming.cycle`, so ``depends_on="270"`` is the loop-ordering
fact, not a code dependency.  A pluggable ``reviser`` lets a deployment
substitute its own policy-development strategy without moving the contract.

**It carries the sweep as its middle clause.**  §C5's loop continues *"evaluate
each on every stored tree"*, and feature 272's sentence is that act:
:mod:`dreaming.sweep` runs the candidate set feature 271 produced against the
pool's worlds and persists one ``replay_score`` row per ``(candidate, world)``
pair.  It is the member's one **act** rather than one more judgment: the
evaluator that replays a candidate over a world's stored tree is the replay
path, which lives in the ``replay`` member and arrives as a callable — no
member imports another — while the row itself is feature 255's and migration
``0109``'s, written through the replay member's own ``persist_replay_score``
reached through the composed application's seat, so ``0109``'s shape keeps one
writer in this workspace rather than two.  The coverage law is the feature:
``M`` candidates and ``n`` worlds is exactly ``M × n`` rows, no pair skipped
and none taken twice, which :func:`dreaming.sweep.plan_sweep` answers as a pure
plan before a single replay is paid for.  Each row's ``is_holdout`` is read
from feature 278's own predicate — the seam ``0109``'s column exists to carry
— and a split is passed in, never taken here.  Where §C5's first clause meets
its middle one, the sweep is **refused**: feature 270's guards refuse every
write to the pool's tables while an iteration holds them, and a sweep attempted
under an open hold translates the replay member's wrapper into this member's
:class:`~dreaming.errors.PoolFrozenError` in feature 270's own word, because
the repair is *close the iteration* and not a second sweep.  Nothing bends that
rule: no guard is dropped, no second connection opened, no hold re-taken to
slip a row underneath one.

**It is not the incumbent's return or the selector.**  Putting ``π^0 = π_t``
back into the candidate set so a selection can never fall below the current
policy (feature 273) and taking the argmax under §7's aggregated objective,
persisting the winner to ``policy_revision`` (feature 274), are each their own
features depending on the sweep.  This member holds the pool, splits it,
rotates the split per cycle and persists which worlds each iteration held out,
runs the sweep that produces the evidence, compares arms over it and bars a
winner that does not survive the noise its own tournament earned; it produces
the candidate set and writes the evidence but never runs a policy, never scores
a world and never picks a winner — the bar *refuses* one, the sweep *reports*
one, and the act of refusing a winner is not the act of crowning it.

**It never writes the pool's tables.**  Feature 270's whole subject is not
writing them.  ``pool_freeze`` is this member's own table and the only table it
creates; :mod:`dreaming.layout` restates the pool's two spellings with their
provenance because a trigger needs a table's *name*, and restates them
deliberately **without importing** the members that own them — no member in
this workspace imports another, and a member that did would couple a
database's history to a package's import graph, invisibly, at the one place it
matters: a deployment that installed one and not the other.

The seat
--------

**The registration lives here and not in a submodule.**  ``@register`` fires at
import time, and importing a *submodule* of this package is not the same act as
importing the package: a submodule's registration would fire only on the first
``create_app()`` of a process, and only if that process happened to load it.
Keeping the decorator in ``__init__.py`` — spelled against names imported from
``.cycle`` rather than beside it — is what makes the component present from the
moment the workspace scan touches this package.  Nothing edits a registry,
router table, entry-points list or app factory to wire this package in: the
package joining the uv workspace *is* the wiring, and the loader's scan of the
declared members is the whole of what discovers it.

Composition-time behaviour follows the workspace's one rule: **degrade, don't
break**.  :func:`build_cycle_freeze` returns a
:class:`~dreaming.cycle.CycleFreeze` when ``DATABASE_URL`` names a store, and
``None`` when it names none — a deployment without a relational store composes
no freeze, which is a discoverable state rather than an exception and not the
same fact as a pool that is not currently held.  The builder performs **no
I/O**: it resolves a URL and constructs an object whose path is read lazily, so
composing an application never touches the disk — and it **never holds
anything**, because §C5's hold is *per outer iteration* and an application that
acquired one at composition time would be holding a pool for as long as the
process lived.

**One component, and it may be ``None``.**  ``"dreaming"`` is the member's
first and only component, registered unprefixed, following the ``ledger`` /
``artifacts`` / ``discovery`` precedent for a member whose first component is
the whole of what it contributes.  The name sorts after ``discovery`` and
before ``evaluator``, so every name-sorted ``app.order`` adjacency in the
existing suite is untouched.

The seat is ``src/app/modules/dreaming``, which answers exactly one question —
*what is the composed cycle freeze?* — and re-exports nothing of the member's
API beyond that: a caller who has the freeze reaches ``open()``, ``release()``,
``verify()``, ``guard()`` and ``holds()`` on it, and a second spelling of those
here would be a second thing to keep in sync.  :data:`COMPONENT_NAME` is
spelled once here and repeated literally in the seat, whose suite asserts the
two agree so the pair cannot drift apart silently.
"""

from __future__ import annotations

from app.module_loader import register

from .bar import (
    SELECTION_BAR_CODE,
    cycle_bar,
    rejects_unbarred_winner,
    selection_bar,
)
from .cap import (
    CAPPED_SWEEP_CAP,
    CYCLE_CAP_TABLE,
    FULL_DREAMING_CAP,
    FULL_DREAMING_WORLDS,
    CapRecord,
    cycle_cap_schema,
    cycle_caps,
    record_cycle_cap,
    revision_cap,
)
from .ceiling import rejects_uncapped_sweep
from .cycle import (
    DATABASE_URL_ENV,
    FREEZE_CODE,
    FREEZE_TABLE,
    POOL_FREEZE_COMPONENT_NAME,
    POOL_TABLES,
    REPLAY_SCORE_TABLE,
    UNGUARDED_CODE,
    WORLD_TABLE,
    CycleFreeze,
    FreezeRecord,
    cycle_freeze_schema,
    expected_triggers,
    missing_guards,
    open_cycle_freeze,
    pool_commitment,
    sqlite_path,
)
from .errors import (
    BarRecordError,
    BarRequestError,
    CapRecordError,
    CapRequestError,
    DreamingError,
    FreezeRequestError,
    HoldoutRecordError,
    HoldoutRequestError,
    PairedComparisonError,
    PoolFrozenError,
    PoolTooThinError,
    ProportionComparisonError,
    RevisionCeilingError,
    RevisionError,
    RevisionRequestError,
    SelectionBarError,
    SplitRequestError,
    SplitStoreError,
    SweepRequestError,
    SweepStoreError,
    TransferRequestError,
    TransferStoreError,
)
from .ladder import (
    LADDER_FLOOR_WORLDS,
    POOL_TOO_THIN_CODE,
    rejects_thin_pool,
    validated_floor,
)
from .layout import (
    POOL_SCHEMA_BY_TABLE,
    REPLAY_SCORE_COLUMNS,
    WORLD_COLUMNS,
    pool_bootstrap_schema,
    pool_tables_present,
)
from .paired import (
    PAIRED_CODE,
    PAIRED_LEVEL,
    POWER,
    PROPORTION_CODE,
    PROPORTION_DESIGN_EFFECT,
    PairedDifference,
    paired_ir_difference,
    paired_pool_difference,
    power_capacity,
    rejects_proportion_comparison,
)
from .reviser import (
    REVISION_BAND,
    CandidateModule,
    candidate_module,
    default_reviser,
    revise_policy,
)
from .rotation import (
    CYCLE_HOLDOUT_TABLE,
    HoldoutRecord,
    cycle_holdout_schema,
    cycle_holdouts,
    cycle_rotation,
    record_cycle_holdout,
)
from .select import (
    SELECT_REQUEST_CODE,
    SELECT_STORE_CODE,
    SelectionRequestError,
    SelectionStoreError,
    commit_selection,
    select_argmax,
)
from .split import (
    TRAIN_FRACTION,
    PoolSplit,
    pool_worlds,
    split_pool,
    split_replay_pool,
)
from .sweep import (
    SWEEP_CODE,
    SWEEP_STORE_CODE,
    SweepPair,
    SweepReport,
    plan_sweep,
    sweep_candidates,
)
from .transfer import (
    FamilyPartition,
    FamilyTransfer,
    family_transfer,
    leave_one_family_out,
    pooled_family_transfer,
)

__all__ = [
    "CAPPED_SWEEP_CAP",
    "COMPONENT_NAME",
    "CYCLE_CAP_TABLE",
    "CYCLE_HOLDOUT_TABLE",
    "DATABASE_URL_ENV",
    "FREEZE_CODE",
    "FREEZE_TABLE",
    "FULL_DREAMING_CAP",
    "FULL_DREAMING_WORLDS",
    "LADDER_FLOOR_WORLDS",
    "PAIRED_CODE",
    "PAIRED_LEVEL",
    "POOL_SCHEMA_BY_TABLE",
    "POOL_TABLES",
    "POOL_TOO_THIN_CODE",
    "POWER",
    "PROPORTION_CODE",
    "PROPORTION_DESIGN_EFFECT",
    "REPLAY_SCORE_COLUMNS",
    "REPLAY_SCORE_TABLE",
    "REVISION_BAND",
    "SELECTION_BAR_CODE",
    "SELECT_REQUEST_CODE",
    "SELECT_STORE_CODE",
    "SWEEP_CODE",
    "SWEEP_STORE_CODE",
    "TRAIN_FRACTION",
    "UNGUARDED_CODE",
    "WORLD_COLUMNS",
    "WORLD_TABLE",
    "BarRecordError",
    "BarRequestError",
    "CandidateModule",
    "CapRecord",
    "CapRecordError",
    "CapRequestError",
    "CycleFreeze",
    "DreamingError",
    "FamilyPartition",
    "FamilyTransfer",
    "FreezeRecord",
    "FreezeRequestError",
    "HoldoutRecord",
    "HoldoutRecordError",
    "HoldoutRequestError",
    "PairedComparisonError",
    "PairedDifference",
    "PoolFrozenError",
    "PoolSplit",
    "PoolTooThinError",
    "ProportionComparisonError",
    "RevisionCeilingError",
    "RevisionError",
    "RevisionRequestError",
    "SelectionBarError",
    "SelectionRequestError",
    "SelectionStoreError",
    "SplitRequestError",
    "SplitStoreError",
    "SweepPair",
    "SweepReport",
    "SweepRequestError",
    "SweepStoreError",
    "TransferRequestError",
    "TransferStoreError",
    "build_cycle_freeze",
    "candidate_module",
    "commit_selection",
    "cycle_bar",
    "cycle_cap_schema",
    "cycle_caps",
    "cycle_freeze_schema",
    "cycle_holdout_schema",
    "cycle_holdouts",
    "cycle_rotation",
    "default_reviser",
    "expected_triggers",
    "family_transfer",
    "ladder_floor",
    "leave_one_family_out",
    "missing_guards",
    "open_cycle_freeze",
    "paired_ir_difference",
    "paired_pool_difference",
    "plan_sweep",
    "pool_bootstrap_schema",
    "pool_commitment",
    "pool_tables_present",
    "pool_worlds",
    "pooled_family_transfer",
    "power_capacity",
    "record_cycle_cap",
    "record_cycle_holdout",
    "rejects_proportion_comparison",
    "rejects_thin_pool",
    "rejects_unbarred_winner",
    "rejects_uncapped_sweep",
    "revise_policy",
    "revision_cap",
    "select_argmax",
    "selection_bar",
    "split_pool",
    "split_replay_pool",
    "sqlite_path",
    "sweep_candidates",
    "validated_floor",
]

#: The name this member registers under.  Re-exported from
#: :mod:`dreaming.cycle` rather than respelled, and named ``COMPONENT_NAME``
#: rather than the module-qualified spelling so the seat
#: (``src/app/modules/dreaming``) can import it under the one name every seat
#: in this workspace exports — the shape the loader's discovery expects.
COMPONENT_NAME = POOL_FREEZE_COMPONENT_NAME

#: The ladder floor's world count — §12.1's 20, the floor a dreaming run must
#: meet.  Re-exported from :mod:`dreaming.ladder` under the friendlier name the
#: seat and a caller reach for, the way :data:`POOL_FREEZE_COMPONENT_NAME` is
#: re-exported as :data:`COMPONENT_NAME`; a caller that asks *what is the
#: floor?* gets one spelling, and a second spelling here would be a second
#: thing to keep in sync.
ladder_floor = LADDER_FLOOR_WORLDS


@register(COMPONENT_NAME)
def build_cycle_freeze() -> CycleFreeze | None:
    """Component builder: the cycle freeze this deployment holds the pool with.

    Takes no arguments — that is the factory's registration protocol — and
    resolves ``DATABASE_URL`` at build time, so a composed application carries
    the freeze for the deployment the process is actually running in.  The
    member's other spelling of the same act,
    :func:`~dreaming.cycle.open_cycle_freeze`, resolves the same variable when
    it is called without a URL, so a script and a composed application reach
    the same hold over the same database.

    Returns ``None`` when nothing names a relational store.  That is
    deliberately not a freeze over an empty pool — and not the same fact as a
    pool that is currently unheld, which is :meth:`~dreaming.cycle.CycleFreeze.
    open_hold` answering ``None`` about a database that definitely exists.  An
    unheld pool answers *no cycle is walking this pool right now*; this
    ``None`` says there is no database to walk one in, and a caller that needs
    §C5's first clause must treat it as a refusal to proceed rather than as a
    pool it happened to find free.  The distinction is the one
    :func:`bootstrap.build_bootstrap_pool` draws for its own deployment state.

    Never raises — including for a URL whose scheme this member cannot speak,
    which is refused by name the first time an operation needs the path rather
    than here.  The factory builds every registered component on every
    :func:`~app.module_loader.create_app` call, so a builder that raised would
    take composition down for every unrelated feature in the workspace; a
    process that *requires* a hold passes a URL to :class:`~dreaming.cycle.
    CycleFreeze` directly, where a named
    :class:`~dreaming.errors.FreezeRequestError` is the right answer.

    Construction performs no I/O and acquires no hold: the path is resolved on
    first use, so composing the application never opens a database, and §C5's
    pool is fixed only when a caller's ``open()`` fixes it.  An application
    that held a pool from composition time would hold it for as long as the
    process lived, which would be a dreaming cycle that never ended.
    """
    return CycleFreeze.resolve()
