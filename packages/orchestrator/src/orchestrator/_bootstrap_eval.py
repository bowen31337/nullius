"""Feature 4 of additions_spec_operator_surfaces.xml — scoring one (candidate,
bootstrap world) pair, the evaluator feature 11's dreaming cycle hands to
``dreaming.sweep_candidates``.

*System scores one (candidate policy, bootstrap world) pair with
orchestrator._bootstrap_eval.score_on_world(candidate_source, world, *,
round_cap) and returns a carrier with .pick and .score, the shape
dreaming.sweep_candidates expects of its evaluator.*

**Loading the candidate reuses orchestrator._policy's own sequence, not its
class.**  :func:`orchestrator._policy.load_exploration_policy` admits a
*named file* through an environment variable and wraps the result in
:class:`~orchestrator._policy.ExplorationPolicy`, whose answer-validation
assumes the live-campaign contract — a batch of *already-revealed* node ids
to expand, checked against a snapshot :class:`policy_runtime.PrefixView`
whose observation fields (``r2_insample``, ``ic_insample``, ``n_periods``,
``n_features``) are the financial campaign's, not bootstrap's.  A dreaming
candidate arrives here as a literal **source string** (one of ``dreaming``'s
``M`` revisions, never a path), and a bootstrap world's batches are the
*unrevealed* neighbours :meth:`bootstrap.BootstrapQuestion.legal_actions`
and :meth:`~bootstrap.BootstrapQuestion.legal_roots` name — the opposite
shape.  So this module repeats only the sequence 230/231 gate the admission
on (:func:`policy_runtime.screen_policy`, import under
:data:`policy_runtime.POLICY_MODULE_NAME`, run under
:func:`policy_runtime.guard_policy`) and raises the same
:class:`~orchestrator._policy.PolicyLoadError`, imported rather than
restated, so a caller catching one class catches a source that could not be
loaded whichever member asked.

**The candidate's ``select`` is driven over the live question, not a
snapshot.**  A bootstrap world has no second "tree" a selected id expands
into — :meth:`bootstrap.BootstrapQuestion.probe_batch` *is* the reveal — so
the round loop here passes ``select`` the question itself each round
(``select(question)``), never a prefix view.  That is also how the
candidate commits: docs §598's ``question.commit(node_id)`` is
:meth:`BootstrapQuestion.commit`, a plain method on the object the
candidate already holds, with no separate ``EpisodeCommit`` door to open —
feature 222's record fronts a campaign's *tree* (``question.tree.node``),
which a bootstrap question does not carry, so this module reads the
committed node straight off :attr:`BootstrapQuestion.committed` once the
loop ends rather than opening a record that would refuse construction.

**Why the round loop does not validate the batch's shape.**  Exactly as
:func:`replay.rounds.run_replay` "trusts that select returns a prefix-only
batch" and lets the tree's own refusal speak for a bad id, this loop hands
whatever ``select`` returns straight to :meth:`BootstrapQuestion.probe_batch`,
which already refuses a node outside the world's lattice by name.  A second
validation here would be a second place the same check could drift.

**The score is the world's own ground truth, read the way
:func:`bootstrap.ground_truth` reads it** — ``world.label(node_id).r2_holdout``
— never the candidate's own in-sample reading of the pick, because the
replay's score is out-of-sample by construction (prd §313's Change A).

**A policy that commits nothing is scored, not refused** — feature 249's
floor, :data:`replay.NON_COMMITTING_SCORE`, with no pick — because the miss
must stay comparable in dreaming's argmax rather than drop out of it or
raise the cycle it merely lost.

**Determinism.**  Each call imports the candidate fresh (a new
:class:`types.ModuleType` registered under
:data:`policy_runtime.POLICY_MODULE_NAME` and re-``exec``'d), so a module's
own state never survives across two calls, and :meth:`HyperparameterWorld.label`
is a pure function of ``(world, node)``. Two calls of
:func:`score_on_world` over the same source, world and round cap therefore
answer the same pick and the same score.
"""

from __future__ import annotations

import sys
import types
from typing import Any

from bootstrap import question_for
from policy_runtime import (
    POLICY_MODULE_NAME,
    CommittedPick,
    PolicyRuntimeError,
    guard_policy,
    screen_policy,
)
from replay import NON_COMMITTING_SCORE, TerminalPick

from ._policy import POLICY_LOAD_CODE, PolicyLoadError

__all__ = ["score_on_world"]


def score_on_world(candidate_source: str, world: Any, *, round_cap: int) -> TerminalPick:
    """Score one (candidate, world) pair — the evaluator ``dreaming.sweep_candidates`` drives.

    Screens ``candidate_source``, imports it under
    :data:`policy_runtime.POLICY_MODULE_NAME` and drives its top-level
    ``select(question)`` over ``bootstrap.question_for(world)``, one round
    per call under :func:`policy_runtime.guard_policy`, revealing each
    round's answered batch through :meth:`~bootstrap.BootstrapQuestion.
    probe_batch` — until ``select`` answers no batch or ``round_cap`` rounds
    have run.  Reads :attr:`~bootstrap.BootstrapQuestion.committed`
    afterwards: ``None`` answers :class:`~replay.TerminalPick` with no pick
    and :data:`replay.NON_COMMITTING_SCORE`; a committed node answers the
    pick and the world's own ``world.label(node_id).r2_holdout``.

    Raises :class:`~orchestrator._policy.PolicyLoadError` naming the
    admission reason for a source :func:`policy_runtime.screen_policy`
    refuses, for a source that raises importing, and for an admitted source
    with no top-level ``select``.  A :class:`policy_runtime.PolicyRuntimeError`
    raised by the runtime guard (a filesystem reach, an import outside the
    ceiling) propagates unchanged, and so does any exception the candidate's
    own ``select`` raises at call time — neither is a loading fault.
    """
    cap = _validated_round_cap(round_cap)
    select = _load_select(candidate_source)
    question = question_for(world)
    rounds = 0
    while rounds < cap:
        with guard_policy(policy_module=POLICY_MODULE_NAME):
            batch = select(question)
        if not batch:
            break
        question.probe_batch(batch)
        rounds += 1
    pick = question.committed
    if pick is None:
        return TerminalPick(pick=None, score=NON_COMMITTING_SCORE)
    return TerminalPick(pick=CommittedPick(node_id=pick), score=world.label(pick).r2_holdout)


def _validated_round_cap(value: Any) -> int:
    """The round cap, a required positive integer — refused otherwise.

    No default and no module constant, for the same reason
    :func:`replay.rounds.run_replay`'s own ``round_cap`` carries none: the
    cap is the caller's policy decision, and a value that is not a positive
    integer names no loop to run (zero or less would terminate before a
    single round, a non-``int`` would break the comparison).
    """
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PolicyLoadError(
            f"{POLICY_LOAD_CODE}: round_cap is a positive integer — the number "
            "of selection rounds a candidate's select may take before the "
            f"loop stops on its own — got {value!r} ({type(value).__name__})"
        )
    return value


def _load_select(candidate_source: str) -> Any:
    """Admit, import and return the candidate's top-level ``select`` — or refuse.

    The same sequence :func:`orchestrator._policy.load_exploration_policy`
    runs for a named file's text, repeated here for a literal source string:
    :func:`policy_runtime.screen_policy` must adopt it, the admitted text is
    imported as :data:`policy_runtime.POLICY_MODULE_NAME` under
    :func:`policy_runtime.guard_policy`, and the module's top-level
    ``select`` is what is returned.  Every refusal is
    :class:`~orchestrator._policy.PolicyLoadError`, naming the admission
    reason, the import failure, or the missing ``select`` — the one
    vocabulary a caller of this module catches, imported rather than
    restated so the two loaders cannot drift into two classes for one fault.
    """
    decision = screen_policy(candidate_source)
    if not decision.adopted:
        raise PolicyLoadError(
            f"{POLICY_LOAD_CODE}: the candidate's source was refused "
            f"admission ({decision.reason.value}): {decision.detail}"
        )
    module = types.ModuleType(POLICY_MODULE_NAME)
    sys.modules[POLICY_MODULE_NAME] = module
    try:
        with guard_policy(policy_module=POLICY_MODULE_NAME):
            exec(compile(decision.source, "<candidate>", "exec"), module.__dict__)  # noqa: S102
    except PolicyRuntimeError:
        raise
    except Exception as exc:
        raise PolicyLoadError(
            f"{POLICY_LOAD_CODE}: the candidate's source was admitted but "
            f"raised importing it: {exc!r}"
        ) from exc
    select = getattr(module, "select", None)
    if not callable(select):
        raise PolicyLoadError(
            f"{POLICY_LOAD_CODE}: the candidate's source was admitted but "
            "carries no top-level select function: the contract is "
            "select(question), and a module without one names no candidate "
            "to drive"
        )
    return select
