"""The campaign CLI — ``python -m orchestrator.campaign``.

additions_spec_campaign_driver.xml, "Campaign Loop" category, feature 7:
*System runs a campaign from* ``python -m orchestrator.campaign --type TYPE
--workspaces W --rounds R [--width N] [--allowance UNITS]`` *and prints one
JSON line per emitted event, followed by the summary line.*  Feature 6's
:func:`~orchestrator._campaign.run_campaign` is the whole campaign loop; this
module is the thin door onto it — it resolves the three collaborators a live
deployment supplies through :func:`~app.module_loader.create_app` (the
``"signal-author"``, ``"live-evaluator"`` and ``"nulloracle-type-r-selection"``
components), loads the exploration policy
(:func:`~orchestrator._policy.load_exploration_policy`), and calls
``run_campaign`` with them.  Nothing here evaluates a node, authors a signal
or touches the sidecar's bit — every one of those acts is the component's own,
resolved and handed through unchanged.

**``"live-evaluator"`` is where this command reads its ``context`` from.**
:class:`orchestrator.LiveEvaluator` (feature 8) is both of the two values
``run_campaign`` needs from a live evaluation: its ``.evaluate(node_id,
campaign_id, depth, code)`` is the ``evaluator`` argument, and its own
``.context`` — the :class:`~orchestrator._context.EvaluationContext` feature 5's
loader resolved once, when the component was built — is the ``context``
argument.  Reading ``context`` off the resolved evaluator rather than loading
it a second time is what keeps the two in agreement: a context loaded twice
could resolve a cost model or a snapshot that drifted between the two calls,
and the whole point of loading it once per :func:`create_app` call is that
every consumer of this process's composition shares the identical triple.

**A missing component is a configuration fact, named and refused before
anything is planted.**  ``create_app().get(name)`` answers ``None`` for every
one of the three components when its deployment left it unconfigured — the
degrade-don't-break stance each of their builders states in its own words —
and a campaign cannot plant a root, evaluate one or seal a Type-R draw
without a real author, evaluator or selection behind it.  So each of the
three is checked before ``run_campaign`` is ever called, in the sentence's own
order, and the first ``None`` is the one stderr line this command prints:
naming the missing component by name, never a stack trace.  A policy that
fails to load (:class:`~orchestrator._policy.PolicyLoadError` — a named
``NULLIUS_EXPLORATION_POLICY`` that cannot be read, was refused admission, or
answers something :class:`~orchestrator._policy.ExplorationPolicy` cannot use)
is the same kind of fact — a deployment that pointed a variable at something
broken — and is refused the same way, before anything is planted.

**Everything past that point is ``run_campaign``'s own call, and this module
catches none of its internal stop reasons.**  ``no_batch``, ``budget_exhausted``,
``token_budget`` and ``round_cap`` are all *the campaign finished* — the
spec's own words, "0 when the campaign finished (any stop_reason)" — so this
command's exit is 0 for every one of them, read off the summary event
``run_campaign`` itself emits last, not derived a second time here.  What this
module does catch is an exception ``run_campaign`` lets escape — a root's
authoring refusal propagates uncaught (feature 6's own documented stance: a
root has no row and no derived id to record a failure against until authoring
has actually answered one), and a handful of its real collaborators (discovery,
signal-agent, providers, ledger, nulloracle, policy-runtime) each raise their
own refusal, with no common base class across the five members to catch by
type.  Every one of those refusals opens its own message with a greppable code
word, by this workspace's universal convention, so this command catches the
broad :class:`Exception` at that one boundary, prints the message verbatim to
stderr, and exits 1 — a refusal, not a crash, and the caller reads *which* one
off the one line it printed.

**No credential is ever read here, so none can ever be printed here.**  This
module touches no environment variable of its own beyond the one
``load_exploration_policy`` already reads (``NULLIUS_EXPLORATION_POLICY``,
which never names a key); every API key, sidecar key and database credential
is resolved inside the three components it only ever calls through, never
inspected.  What reaches stderr or stdout is an argument, a component's own
name, or a collaborator's own exception message — and every one of those
members' own refusal messages is already written to carry no credential, the
same discipline :mod:`router.bingx_alert` states for its own scrubbed lines.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import nulloracle
import signal_agent
from policy_runtime import UNBOUNDED_BUDGET

from app.module_loader import create_app

from ._campaign import run_campaign
from ._policy import DEFAULT_BASELINE_WIDTH, PolicyLoadError, load_exploration_policy

__all__ = [
    "CAMPAIGN_CLI_CODE",
    "EXIT_CONFIG",
    "EXIT_OK",
    "EXIT_REFUSED",
    "LIVE_EVALUATOR_COMPONENT_NAME",
    "main",
]

#: The greppable code word this command's own refusals open with — the
#: missing-component and policy-load lines this module prints itself,
#: never a collaborator's own message (each of those already opens with
#: its own code word, and prefixing a second one would bury it).
CAMPAIGN_CLI_CODE = "campaign_cli"

#: The three exit codes the spec's own sentence names: 0 once
#: ``run_campaign`` has answered (any ``stop_reason``), 1 when it let a
#: refusal escape, 2 for a bad argument or a missing/broken configuration.
EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_CONFIG = 2

#: The component name :class:`orchestrator.LiveEvaluator` registers under
#: (``orchestrator/__init__.py``'s own ``_COMPONENT_NAME``, feature 8).
#: Spelled here rather than imported: that name is a private module
#: constant of ``orchestrator/__init__.py``, not part of its public
#: ``__all__`` (unlike ``signal_agent.SIGNAL_AUTHOR_COMPONENT_NAME`` and
#: ``nulloracle.TYPE_R_COMPONENT_NAME``, which this module imports instead
#: of restating), and this feature's own file claim does not touch that
#: module to add one.
LIVE_EVALUATOR_COMPONENT_NAME = "live-evaluator"


def _missing_component_line(name: str) -> str:
    """The one stderr line a missing component prints — names it, nothing else."""
    return (
        f"{CAMPAIGN_CLI_CODE}: create_app() answers no {name!r} component; "
        "a campaign cannot plant a root, evaluate one or seal its Type-R "
        "draw without it — configure the deployment and run again"
    )


def _resolve_or_none(app: Any, name: str) -> tuple[Any, str | None]:
    """One component, or the missing-component line naming it."""
    value = app.get(name)
    if value is None:
        return None, _missing_component_line(name)
    return value, None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m orchestrator.campaign",
        description=(
            "Run one campaign: plant its roots, seal the Type-R draw, "
            "evaluate every root, then loop the round until one of the "
            "four stop conditions fires. Prints one JSON line per emitted "
            "event, followed by the summary line."
        ),
    )
    parser.add_argument(
        "--type",
        dest="campaign_type",
        required=True,
        metavar="TYPE",
        help="the campaign's declared type",
    )
    parser.add_argument(
        "--workspaces",
        type=int,
        required=True,
        metavar="W",
        help="how many root workspaces to plant",
    )
    parser.add_argument(
        "--rounds",
        type=int,
        required=True,
        metavar="R",
        help="the round loop's own cap",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=DEFAULT_BASELINE_WIDTH,
        metavar="N",
        help=f"the batch width per round (default: {DEFAULT_BASELINE_WIDTH})",
    )
    parser.add_argument(
        "--allowance",
        type=float,
        default=UNBOUNDED_BUDGET,
        metavar="UNITS",
        help="the statistical budget allowance (default: unbounded)",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    app: Any = None,
    emit: Callable[[str], object] = print,
) -> int:
    """``python -m orchestrator.campaign``: resolve, compose, run, print.

    Parses the spec's five flags (argparse itself exits 2 for a bad one,
    before this function's own body runs), resolves the ``"signal-author"``,
    ``"live-evaluator"`` and ``"nulloracle-type-r-selection"`` components
    from ``app`` (a real :func:`~app.module_loader.create_app` when ``app``
    is not injected) and loads the exploration policy from ``env``. Refuses
    with :data:`EXIT_CONFIG` and one stderr line the moment any of those
    four is missing or will not load — before a single root is planted.

    Calls :func:`~orchestrator._campaign.run_campaign` with the resolved
    collaborators, routing every event it emits through ``emit`` as one
    JSON line (:func:`print` by default): one line per planted root, per
    evaluated node and per round, and the summary line last — exactly the
    sequence ``run_campaign`` itself emits, unmodified. Returns
    :data:`EXIT_OK` once it has answered, whichever of the four
    ``stop_reason`` words fired. An exception ``run_campaign`` lets escape
    (a root's own authoring refusal, or any of its real collaborators'
    refusals) is printed to stderr and answered with :data:`EXIT_REFUSED`.

    ``env``, ``app`` and ``emit`` are this command's seams: ``env`` is what
    :func:`~orchestrator._policy.load_exploration_policy` reads
    ``NULLIUS_EXPLORATION_POLICY`` from (the process environment when
    ``None``), ``app`` is the composed application the three components are
    read from (a real :func:`~app.module_loader.create_app` when ``None``),
    and ``emit`` is what each JSON line is printed with. A caller that
    injects nothing gets a real deployment's composition.
    """
    parser = _build_parser()
    arguments = parser.parse_args(argv)

    composed = app if app is not None else create_app()

    author, missing = _resolve_or_none(composed, signal_agent.SIGNAL_AUTHOR_COMPONENT_NAME)
    if missing is not None:
        print(missing, file=sys.stderr)
        return EXIT_CONFIG
    evaluator, missing = _resolve_or_none(composed, LIVE_EVALUATOR_COMPONENT_NAME)
    if missing is not None:
        print(missing, file=sys.stderr)
        return EXIT_CONFIG
    sidecar_selection, missing = _resolve_or_none(composed, nulloracle.TYPE_R_COMPONENT_NAME)
    if missing is not None:
        print(missing, file=sys.stderr)
        return EXIT_CONFIG

    try:
        policy = load_exploration_policy(env)
    except PolicyLoadError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_CONFIG

    def _emit_line(event: dict[str, Any]) -> None:
        emit(json.dumps(event))

    try:
        run_campaign(
            campaign_type=arguments.campaign_type,
            workspaces=arguments.workspaces,
            rounds=arguments.rounds,
            width=arguments.width,
            allowance=arguments.allowance,
            author=author,
            evaluator=evaluator,
            policy=policy,
            context=evaluator.context,
            sidecar_selection=sidecar_selection,
            emit=_emit_line,
        )
    except Exception as exc:  # noqa: BLE001 - every collaborator's own
        # refusal is caught here: discovery, signal-agent, providers,
        # ledger, nulloracle and policy-runtime each raise from their own,
        # unrelated base class (see the module docstring), so there is no
        # narrower type this boundary could name instead. Every one of
        # those refusals already opens its own message with a greppable
        # code word, which is what reaches stderr unchanged.
        print(str(exc), file=sys.stderr)
        return EXIT_REFUSED

    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - the module's own door
    raise SystemExit(main())
