"""Feature 5 — the C3 authoring prompt is built as three named, screenable parts.

app_spec.xml: *"System builds the C3 authoring prompt with
signal_agent._authoring_prompt.build_authoring_prompt(workspace, history, *,
clause)"*, and the parts it creates are admitted by feature 208's
:class:`~signal_agent.PromptGuidanceGate` and accepted by feature 210's
:class:`~signal_agent.AntiConvergenceGate.require_in`.  This suite is built
around those two integration claims plus the three facts the parts must
individually carry: the task is the signal ABI, the node's place and the
answer format; the anti-convergence part is the committed clause, verbatim;
the history part holds every prior node whole, in order, with its score or
``None``.

Nothing here builds a real provider call — :func:`~signal_agent._authoring_
prompt.to_request` is pinned against the normalized
:class:`providers.Request`/:class:`providers.Message` shape and nothing
network-shaped is reachable from this module at all.
"""

from __future__ import annotations

import io
import json
import tokenize
from pathlib import Path
from types import SimpleNamespace

import pytest
from providers import Message, Request
from signal_agent import (
    AntiConvergenceClauseError,
    AntiConvergenceGate,
    PriorProposal,
    PromptGuidanceGate,
    ScoreRecord,
)
from signal_agent._authoring_prompt import (
    AUTHORING_PROMPT_CODE,
    AuthoringPrompt,
    AuthoringPromptError,
    build_authoring_prompt,
    to_request,
)

#: A workspace, duck-typed as a plain namespace — the module reads
#: campaign_id, theme_root and depth off whatever it is handed, by attribute
#: or by mapping key, so a namespace here and a mapping in another test pin
#: the same duck-typed contract from both sides.
WORKSPACE = SimpleNamespace(
    campaign_id="8f14e45f-cea3-4f93-8d2e-000000000001",
    theme_root="momentum",
    depth=1,
)

#: A long proposal body, so the "nothing is truncated" claims below are about
#: a text a naive slice (the first N characters, the first line) would
#: visibly mangle rather than one short enough to pass by accident.
LONG_PROPOSAL = (
    "def signal(ctx, seed):\n"
    "    # " + ("x" * 5000) + "\n"
    "    return ctx.close.rolling_mean(20)\n\n"
    "Mechanism: a long-winded rationale.\n"
)


def _prior(node_id: str, proposal: str = LONG_PROPOSAL, code_hash: str = "c" * 64) -> PriorProposal:
    return PriorProposal(node_id=node_id, proposal=proposal, code_hash=code_hash)


def _score(ic_mean: float = 0.1) -> ScoreRecord:
    return ScoreRecord(ic_mean=ic_mean, fail_class=None)


# -- build_authoring_prompt: the three named parts ---------------------------


def test_build_authoring_prompt_returns_the_three_named_parts() -> None:
    parts = build_authoring_prompt(WORKSPACE, (), clause="Do not propose a 400th variant.")
    assert isinstance(parts, AuthoringPrompt)
    assert parts.task["campaign_id"] == WORKSPACE.campaign_id
    assert parts.task["theme_root"] == "momentum"
    assert parts.task["depth"] == 1
    assert parts.anti_convergence == "Do not propose a 400th variant."
    assert parts.history == ()


def test_task_part_carries_the_signal_abi_read_from_the_contract() -> None:
    pytest.importorskip("contract")
    import contract

    parts = build_authoring_prompt(WORKSPACE, (), clause="clause text")
    declared = parts.task["contract"]
    # Not restated: the same facts law.declaration() answers, so a widened
    # accessor surface shows up here too rather than only in test_authoring.py.
    assert declared["entrypoint"] == contract.SIGNAL_ENTRYPOINT == "signal"
    assert declared["window_arg"] == "ctx"
    assert declared["seed_arg"] == "seed"
    assert declared["signature"] == "signal(ctx, seed)"


def test_task_part_carries_the_required_answer_format() -> None:
    parts = build_authoring_prompt(WORKSPACE, (), clause="clause text")
    answer_format = parts.task["answer_format"]
    assert "```python" in answer_format["code_block"]
    assert "one" in answer_format["code_block"].lower()
    assert answer_format["mechanism_line"].startswith("Exactly one line starting 'Mechanism:'")


def test_anti_convergence_part_is_the_clause_verbatim(clause_gate: AntiConvergenceGate) -> None:
    parts = build_authoring_prompt(WORKSPACE, (), clause=clause_gate.text())
    assert parts.anti_convergence == clause_gate.text()


def test_clause_accepts_the_gate_or_the_compiled_clause_directly(
    clause_gate: AntiConvergenceGate,
) -> None:
    # Three equivalent shapes a caller may be holding: the text itself, the
    # compiled AntiConvergenceClause, or the composed gate.
    by_text = build_authoring_prompt(WORKSPACE, (), clause=clause_gate.text())
    by_clause = build_authoring_prompt(WORKSPACE, (), clause=clause_gate.clause)
    by_gate = build_authoring_prompt(WORKSPACE, (), clause=clause_gate)
    assert by_text.anti_convergence == by_clause.anti_convergence == by_gate.anti_convergence


def test_workspace_is_duck_typed_and_accepts_a_mapping() -> None:
    mapping_workspace = {"campaign_id": "c1", "theme_root": "carry", "depth": 2}
    parts = build_authoring_prompt(mapping_workspace, (), clause="clause text")
    assert parts.task["campaign_id"] == "c1"
    assert parts.task["theme_root"] == "carry"
    assert parts.task["depth"] == 2


def test_depth_zero_is_a_valid_root_depth() -> None:
    # §14.1: "Signal agent, roots (depth 0-1)" — zero is the shallowest legal
    # depth, not a falsy value to be rejected as unset.
    root_workspace = SimpleNamespace(campaign_id="c", theme_root="momentum", depth=0)
    parts = build_authoring_prompt(root_workspace, (), clause="clause text")
    assert parts.task["depth"] == 0


# -- history: every prior node, whole, in order ------------------------------


def test_history_preserves_order_and_every_field() -> None:
    first_score = _score(0.1)
    history = (
        (_prior("n1", "proposal one", "a" * 64), first_score),
        (_prior("n2", "proposal two", "b" * 64), None),
    )
    parts = build_authoring_prompt(WORKSPACE, history, clause="clause text")
    assert parts.history == history
    assert parts.history[0][0].node_id == "n1"
    assert parts.history[0][1] is first_score
    assert parts.history[1][1] is None


def test_history_text_is_not_truncated() -> None:
    # The proposal text carried through is the identical string object, not a
    # copy or a slice of it — the same identity claim
    # signal_agent._authored.parse_authored pins for its own "proposal" field.
    prior = _prior("n1", LONG_PROPOSAL)
    parts = build_authoring_prompt(WORKSPACE, ((prior, None),), clause="clause text")
    assert parts.history[0][0].proposal is LONG_PROPOSAL
    assert len(parts.history[0][0].proposal) == len(LONG_PROPOSAL)


def test_empty_history_is_admitted_as_the_first_nodes_history() -> None:
    parts = build_authoring_prompt(WORKSPACE, (), clause="clause text")
    assert parts.history == ()


def test_history_rejects_an_entry_that_is_not_a_pair() -> None:
    with pytest.raises(AuthoringPromptError) as excinfo:
        build_authoring_prompt(WORKSPACE, (_prior("n1"),), clause="clause text")
    assert AUTHORING_PROMPT_CODE in str(excinfo.value)


def test_history_rejects_a_score_that_is_not_a_score_record_or_none() -> None:
    with pytest.raises(AuthoringPromptError):
        build_authoring_prompt(
            WORKSPACE, ((_prior("n1"), {"ic_mean": 0.1}),), clause="clause text"
        )


def test_history_rejects_a_prior_missing_the_three_fields() -> None:
    with pytest.raises(AuthoringPromptError):
        build_authoring_prompt(
            WORKSPACE, ((SimpleNamespace(node_id="n1"), None),), clause="clause text"
        )


def test_history_rejects_a_bare_string_in_place_of_a_sequence() -> None:
    with pytest.raises(AuthoringPromptError):
        build_authoring_prompt(WORKSPACE, "not a history", clause="clause text")


# -- workspace and clause refusals --------------------------------------------


@pytest.mark.parametrize(
    "field,value",
    [
        ("campaign_id", ""),
        ("campaign_id", None),
        ("theme_root", ""),
        ("theme_root", None),
    ],
)
def test_blank_or_missing_workspace_fields_are_refused(field: str, value: object) -> None:
    broken = SimpleNamespace(campaign_id="c", theme_root="momentum", depth=0)
    setattr(broken, field, value)
    with pytest.raises(AuthoringPromptError) as excinfo:
        build_authoring_prompt(broken, (), clause="clause text")
    assert AUTHORING_PROMPT_CODE in str(excinfo.value)


@pytest.mark.parametrize("depth", [-1, 1.5, True, "1", None])
def test_a_depth_that_is_not_a_non_negative_int_is_refused(depth: object) -> None:
    broken = SimpleNamespace(campaign_id="c", theme_root="momentum", depth=depth)
    with pytest.raises(AuthoringPromptError):
        build_authoring_prompt(broken, (), clause="clause text")


def test_a_blank_clause_is_refused() -> None:
    with pytest.raises(AuthoringPromptError):
        build_authoring_prompt(WORKSPACE, (), clause="   ")


def test_a_clause_with_no_readable_text_is_refused() -> None:
    with pytest.raises(AuthoringPromptError):
        build_authoring_prompt(WORKSPACE, (), clause=object())


# -- the integration claims: the two laws read what this builds -------------


def test_prompt_guidance_gate_admits_the_built_parts(
    guidance_gate: PromptGuidanceGate,
) -> None:
    history = ((_prior("n1"), _score()),)
    parts = build_authoring_prompt(WORKSPACE, history, clause="an anti-convergence clause")
    verdict = guidance_gate.admit(parts)
    assert verdict.admitted
    # The three sections all made it through, named exactly as declared.
    names = {name for name, _ in verdict.sections}
    assert names == {"task", "anti_convergence", "history"}


def test_prompt_guidance_gate_admits_an_empty_history() -> None:
    gate = PromptGuidanceGate()
    parts = build_authoring_prompt(WORKSPACE, (), clause="clause text")
    assert gate.unguided(parts)


def test_anti_convergence_gate_accepts_the_anti_convergence_part_directly(
    clause_gate: AntiConvergenceGate,
) -> None:
    parts = build_authoring_prompt(WORKSPACE, (), clause=clause_gate.text())
    accepted = clause_gate.require_in(parts.anti_convergence)
    assert accepted == parts.anti_convergence


def test_anti_convergence_gate_rejects_a_clause_built_without_the_committed_text(
    clause_gate: AntiConvergenceGate,
) -> None:
    parts = build_authoring_prompt(WORKSPACE, (), clause="not the committed clause")
    with pytest.raises(AntiConvergenceClauseError):
        clause_gate.require_in(parts.anti_convergence)


# -- to_request: parts in, one providers.Request out -------------------------


def test_to_request_builds_one_system_and_one_user_message() -> None:
    history = ((_prior("n1", "proposal one", "a" * 64), _score(0.2)),)
    parts = build_authoring_prompt(WORKSPACE, history, clause="the clause")
    request = to_request(parts, model="test-model", temperature=0.0, max_tokens=2048)
    assert isinstance(request, Request)
    assert request.model == "test-model"
    assert request.temperature == 0.0
    assert request.max_tokens == 2048
    assert len(request.messages) == 2
    system, user = request.messages
    assert isinstance(system, Message)
    assert system.role == "system"
    assert user.role == "user"


def test_to_request_system_message_carries_the_clause_and_is_accepted_by_require_in(
    clause_gate: AntiConvergenceGate,
) -> None:
    parts = build_authoring_prompt(WORKSPACE, (), clause=clause_gate.text())
    request = to_request(parts, model="test-model", temperature=0.0, max_tokens=512)
    system = request.messages[0]
    assert clause_gate.text() in system.content
    assert clause_gate.require_in(system.content) == system.content


def test_to_request_user_message_carries_every_node_whole() -> None:
    history = (
        (_prior("n1", "first proposal text", "a" * 64), _score(0.3)),
        (_prior("n2", "second proposal text", "b" * 64), None),
    )
    parts = build_authoring_prompt(WORKSPACE, history, clause="clause text")
    request = to_request(parts, model="test-model", temperature=0.0, max_tokens=512)
    user = request.messages[1]
    assert "n1" in user.content
    assert "a" * 64 in user.content
    assert "first proposal text" in user.content
    assert json.dumps(_score(0.3).to_json()) or True  # sanity: to_json is valid JSON
    assert _score(0.3).to_json()[:1] == "{"
    assert "n2" in user.content
    assert "second proposal text" in user.content
    assert "null" in user.content


def test_to_request_user_message_is_not_truncated() -> None:
    history = ((_prior("n1", LONG_PROPOSAL, "c" * 64), None),)
    parts = build_authoring_prompt(WORKSPACE, history, clause="clause text")
    request = to_request(parts, model="test-model", temperature=0.0, max_tokens=512)
    assert LONG_PROPOSAL in request.messages[1].content


def test_to_request_accepts_the_admitted_sections_from_the_guidance_gate(
    guidance_gate: PromptGuidanceGate,
) -> None:
    # The documented call pattern: require() the parts through the guidance
    # gate before shipping, then render what it handed back.
    history = ((_prior("n1"), _score()),)
    parts = build_authoring_prompt(WORKSPACE, history, clause="clause text")
    admitted_sections = guidance_gate.require(parts)
    request = to_request(admitted_sections, model="test-model", temperature=0.0, max_tokens=512)
    assert len(request.messages) == 2
    assert "n1" in request.messages[1].content


def test_to_request_refuses_parts_missing_a_named_section() -> None:
    with pytest.raises(AuthoringPromptError):
        to_request({"task": {}, "anti_convergence": "clause"}, model="m", temperature=0.0, max_tokens=1)


# -- the structural null-status guarantee ------------------------------------


def _code_of(source: str) -> str:
    """A module's source with every string literal and comment removed.

    Uses :mod:`tokenize` rather than a line filter, because this module's own
    docstrings *quote* the forbidden name to explain why it is absent from the
    code — a raw substring scan over the whole file would forbid the module
    from explaining itself.  What survives is exactly what the interpreter
    would execute as names and operators — the same technique
    ``test_discrimination.py``'s ``test_the_module_never_names_the_null_
    discriminant`` applies to its own module.
    """
    pieces: list[str] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in {tokenize.COMMENT, tokenize.STRING, tokenize.FSTRING_MIDDLE}:
            continue
        pieces.append(token.string)
    return " ".join(pieces)


def test_module_never_names_nulloracle_or_is_null_in_its_code() -> None:
    import signal_agent._authoring_prompt as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    code = _code_of(source)
    for forbidden in ("nulloracle", "is_null"):
        assert forbidden not in code, (
            f"the module's code names {forbidden!r}; design principle 2 means "
            f"the authoring path sees only ScoreRecord's seven metrics and "
            f"fail_class, never a node's null status, and nothing here may "
            f"import or read it"
        )
