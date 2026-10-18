"""``python -m orchestrator.canary_cli`` — the canary, with its evaluators wired.

``additions_spec_dreaming_m3.xml`` feature 5 (274b72f) made
``require_dreaming_allowed`` refuse a canary pass that did not include the
*evaluation* canary — a re-evaluation of one stored research node and one
replay of a stored policy over its stored campaign tree, each compared
against a constant frozen by ``--freeze-reference`` — and gave
:func:`canary.run.main` the three seams that need: ``evaluate_node``,
``replay_policy`` and ``evaluation_config_sha256``.  No caller was ever
written.  ``./run.sh canary`` ran ``python -m canary.run``, whose own
``__main__`` calls ``main()`` with none of the three, so every recorded run
carried ``evaluation_canary=0`` and ``./run.sh dream`` was refused forever
for a stale or missing evaluation-canary pass.  This module is that caller.

**Why here and not in the canary member.**  The evaluators *are* the
orchestrator's own live evaluation path — the sealed snapshot, the cost
model, the sandbox, the per-node out-of-sample IR — and the dependency runs
one way: ``orchestrator`` depends on ``canary``, never the reverse.  A
canary member that imported :mod:`orchestrator._financial_eval` to wire its
own CLI would invert that edge.  So the command lives in the member that
owns the implementation it injects, and ``run.sh`` points its ``canary``
verb here; :mod:`canary.run` keeps its seams, its refusals and its store
exactly as they are.

**What is wired, and when.**  :func:`orchestrator._context.
load_evaluation_context` is asked for this process's evaluation context —
the same call :mod:`orchestrator.dream` and :mod:`orchestrator.campaign`
make, off the same ``NULLIUS_EVALUATION_CONFIG``.  With a context carrying a
non-empty ``oos_dates`` the three seams are supplied:

* ``evaluate_node(campaign_id, node_id)`` — that node's out-of-sample
  cost-adjusted IR, through :func:`orchestrator._financial_eval._oos_ir`,
  which is the identical read
  :func:`~orchestrator._financial_eval.score_on_financial_world` scores a
  committed pick by.
* ``replay_policy(campaign_id)`` — the score of
  :func:`~orchestrator._financial_eval.score_on_financial_world` over
  :data:`orchestrator.dream.M2_INCUMBENT_PATH`'s source, the M3 baseline
  ``docs/preregistration/2026-10-17-m3-dreaming.ADDENDUM.md`` names, over
  that campaign.
* ``evaluation_config_sha256`` — the digest of the file
  ``NULLIUS_EVALUATION_CONFIG`` names, through
  :func:`orchestrator.dream.evaluation_config_sha256`, the identical helper
  ``dream`` stamps its financial-world rows with.  Reused rather than
  re-implemented: the frozen constant and the rows written under it must
  name the *same* configuration, and two hash implementations would be two
  answers to that question.

**A new**
:class:`~orchestrator._financial_eval.FinancialEvalContext` **for every
call.**  That dataclass's per-run cache is keyed by ``(node_id,
oos_dates)`` and its scope *is* the instance's lifetime; a canary that built
one per run would answer a nightly re-evaluation from memory, comparing a
stored constant against an echo of whatever the node scored the first time
— a determinism check that could never fail.  So each call constructs its
own, and the cache is useless by construction.

**No evaluation config, no evaluators — unchanged refusals.**  With
``NULLIUS_EVALUATION_CONFIG`` unset, or naming a document with no
``oos_dates``, there is no out-of-sample window to re-evaluate anything
over: this command then passes none of the three seams and
:func:`canary.run.main`'s own behaviour applies untouched — a toy-only run
on a deployment with no frozen evaluation reference, and that module's own
refusal by name on one with a frozen evaluation reference.  A *configured
but broken* document is refused here instead, before ``canary.run`` is
called, exactly as :mod:`orchestrator.dream` refuses it: a canary that fell
back to toy-only because its evaluation config could not be read would be
the very silence this command exists to end.

``DATABASE_URL`` is checked before the context is loaded and, when absent,
left entirely to :func:`canary.run.main`, so this command never mints a
second exit code for a fault that module already answers with its own.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Mapping, Sequence

from canary import run as canary_run
from canary.run import DATABASE_URL_ENV

from ._context import (
    EvaluationConfigError,
    EvaluationContext,
    load_evaluation_context,
)
from ._financial_eval import (
    FinancialEvalContext,
    _oos_ir,
    score_on_financial_world,
)
from .dream import M2_INCUMBENT_PATH, evaluation_config_sha256

__all__ = [
    "CANARY_CLI_CODE",
    "DATABASE_URL_ENV",
    "EXIT_BROKEN",
    "EXIT_CONFIG",
    "EXIT_OK",
    "EXIT_REFUSED",
    "main",
]

#: The greppable word this module's own refusals open with — never
#: ``canary.run``'s or a collaborator's, which already open with their own.
CANARY_CLI_CODE = "canary_cli"

#: This command's own exit codes. The three values are ``canary.run``'s —
#: restated here in the workspace's own convention
#: (``orchestrator.shadow``, ``orchestrator.dream``) rather than imported, so
#: this module states its contract without depending on another module's
#: spelling of it. A run this command *does* reach ``canary.run.main`` for
#: answers that module's code unchanged, which is the whole of the
#: "exit codes are canary.run.main's" promise.
EXIT_OK = 0
#: A refusal: a broken evaluation config, or anything ``canary.run`` refuses.
EXIT_REFUSED = 1
#: Missing configuration — no ``DATABASE_URL``, reported by ``canary.run``.
EXIT_CONFIG = 2
#: Broken determinism, reported by ``canary.run``.
EXIT_BROKEN = 3


def _read_baseline_source() -> str:
    """The M3 baseline policy's source — the policy the replay scores.

    :data:`orchestrator.dream.M2_INCUMBENT_PATH` is the one spelling of that
    file (the addendum's *"The baseline is deploy/dreaming/incumbent.m2.py"*),
    so the canary's replay and ``dream``'s own baseline sweep name the same
    policy.  A file that cannot be read is refused with this module's code
    word rather than raised: an unreadable baseline means there is no replay
    to freeze or compare, not a crash to report as one.
    """
    try:
        return M2_INCUMBENT_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise EvaluationConfigError(
            f"{CANARY_CLI_CODE}: the fixed M2 baseline "
            f"{str(M2_INCUMBENT_PATH)!r} could not be read: {exc}; the "
            "evaluation canary's replay half re-scores that rule, so a "
            "deployment without it cannot freeze or replay the evaluation "
            "canary at all"
        ) from exc


def _node_evaluator(context: EvaluationContext) -> Callable[[str, str], float]:
    """``evaluate_node``: one stored node's out-of-sample cost-adjusted IR.

    A fresh :class:`~orchestrator._financial_eval.FinancialEvalContext` per
    call, so the per-run cache can never answer a nightly re-evaluation from
    memory — see the module docstring.
    """

    def evaluate_node(campaign_id: str, node_id: str) -> float:
        return float(
            _oos_ir(
                node_id,
                campaign_id=campaign_id,
                context=FinancialEvalContext(evaluation=context),
            )
        )

    return evaluate_node


def _replay_evaluator(
    context: EvaluationContext, source: str
) -> Callable[[str], float]:
    """``replay_policy``: the M3 baseline's score over one campaign's tree.

    Same fresh-context rule as :func:`_node_evaluator`: the replay and the
    node re-evaluation are two independent measurements, and a shared cache
    between them — or across nights — would make the second a memory of the
    first.
    """

    def replay_policy(campaign_id: str) -> float:
        pick = score_on_financial_world(
            source,
            campaign_id,
            context=FinancialEvalContext(evaluation=context),
        )
        return float(pick.score)

    return replay_policy


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    emit: Callable[[str], object] = print,
) -> int:
    """``python -m orchestrator.canary_cli [--freeze-reference]``.

    ``argv``, ``env`` and ``emit`` are handed to :func:`canary.run.main`
    exactly as received, plus the evaluation canary's three seams when this
    process has an evaluation context with an out-of-sample grid (see the
    module docstring).  ``env`` is where ``DATABASE_URL`` and
    ``NULLIUS_EVALUATION_CONFIG`` are read from, the same seam every other
    operator CLI in this workspace takes, and it defaults to the process
    environment.
    """
    source = os.environ if env is None else env

    evaluate_node: Callable[[str, str], float] | None = None
    replay_policy: Callable[[str], float] | None = None
    config_sha256: str | None = None

    database_url = source.get(DATABASE_URL_ENV, "").strip()
    if database_url:
        try:
            evaluation_context = load_evaluation_context(env=source)
            if evaluation_context is not None and evaluation_context.oos_dates:
                baseline_source = _read_baseline_source()
                config_sha256 = evaluation_config_sha256(source)
                evaluate_node = _node_evaluator(evaluation_context)
                replay_policy = _replay_evaluator(evaluation_context, baseline_source)
        except EvaluationConfigError as exc:
            print(str(exc), file=sys.stderr)
            return EXIT_REFUSED

    # Without a store there is nothing to load a context against, and
    # canary.run owns that refusal and its exit code -- the store is its
    # contract, and a second answer here could only disagree with it. The
    # three seams are passed either way, as None when unwired, so a caller
    # reading this command's call sees one shape and not three.
    return canary_run.main(
        argv,
        env=source,
        emit=emit,
        evaluate_node=evaluate_node,
        replay_policy=replay_policy,
        evaluation_config_sha256=config_sha256,
    )


if __name__ == "__main__":  # pragma: no cover - the module's own door
    raise SystemExit(main())
