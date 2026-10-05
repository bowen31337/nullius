"""Feature 1 of additions_spec_campaign_driver.xml ("Roots") —
``LLMSignalAuthor.author_root(campaign_id, theme_root, *, root_id)``: a
campaign's opening signal, authored at depth 0 with role ``"root"``.

A root has no parent to derive a child id from, so its own id is the
caller's ``root_id`` — a UUID — rather than a value :mod:`discovery`
derives.  Everything else is the claim that a root walks *the same* path
feature 7's :meth:`~signal_agent._llm_author.LLMSignalAuthor.__call__`
walks for an expansion:

* the **routing** — ``session.provider_for("root", campaign_id=…,
  node_id=root_id)`` is exactly how the model is chosen, so the root
  rotation (additions_spec_llm_authoring.xml feature 3) decides it;
* the **prompt** — built from the campaign's whole history (empty for a
  campaign's first root) in ``theme_root`` at depth 0, screened by
  feature 208's guidance gate and feature 210's clause gate before any
  call is placed;
* the **retry and acceptance** — the same parse/adopt/anti-convergence
  loop, the same :class:`~signal_agent.AuthoringRefusedError` after the
  retries are spent;
* the **non-retry** — :class:`~providers.BudgetExhaustedError` and
  :class:`~providers.ServedModelMismatchError` propagate unchanged;
* the **record** — ``depth == 0`` and ``role == "root"``, carrying the
  declared frontier tier the way any root record does.

This file borrows its fakes and fixtures from :mod:`test_llm_author`
(the same convention ``packages/router/tests/test_bingx_rebalance.py``
uses toward ``test_bingx_mirror``) rather than redefine them, so a root's
suite reads against the same vocabulary an expansion's does.
"""

from __future__ import annotations

import uuid

import providers
import pytest
from providers import (
    AgentSampling,
    BudgetExhaustedError,
    ServedModelMismatchError,
    Usage,
)
from signal_agent import anti_convergence_gate
from signal_agent._llm_author import (
    AUTHORING_REFUSED_CODE,
    AuthoredSignal,
    AuthoringRefusedError,
)

from test_llm_author import (  # isort: skip
    CAMPAIGN,
    CONFORMING_ANSWER,
    CONFORMING_CODE,
    DEPTH_MODEL,
    FakeHistoryStore,
    FakeProvider,
    MOMENTUM_CODE,
    NON_CONFORMING_ANSWER,
    ROOT_MODEL,
    ScoreRecord,
    UNPARSEABLE_ANSWER,
    build_author,
    completion,
    fenced_answer,
    make_config,
    prior,
    proposal_document,
)

ROOT_ID = "8f14e45f-cea3-4f93-8d2e-0000000000aa"
THEME_ROOT = "momentum"


# ── The routing: role "root", depth 0, the caller's own id ───────────────────


def test_root_is_authored_at_depth_zero_with_role_root() -> None:
    provider = FakeProvider([completion(CONFORMING_ANSWER, model=ROOT_MODEL)], model=ROOT_MODEL)
    author = build_author(provider=provider)
    result = author.author_root(CAMPAIGN, THEME_ROOT, root_id=ROOT_ID)
    assert isinstance(result, AuthoredSignal)
    assert result.record.node_id == ROOT_ID
    assert result.record.depth == 0
    assert result.record.role == "root"


def test_session_is_asked_for_the_root_role_with_the_callers_own_id() -> None:
    provider = FakeProvider([completion(CONFORMING_ANSWER, model=ROOT_MODEL)], model=ROOT_MODEL)
    author = build_author(provider=provider)
    author.author_root(CAMPAIGN, THEME_ROOT, root_id=ROOT_ID)
    assert author._session.calls == [
        {"role": "root", "campaign_id": CAMPAIGN, "node_id": ROOT_ID}
    ]


def test_a_uuid_root_id_is_canonicalized_the_same_as_a_string_one() -> None:
    # The spec states root_id as "a UUID" — a caller may hand in either a
    # uuid.UUID instance or its string form, and both must route and record
    # identically.
    as_uuid = uuid.UUID(ROOT_ID)
    provider = FakeProvider([completion(CONFORMING_ANSWER, model=ROOT_MODEL)], model=ROOT_MODEL)
    author = build_author(provider=provider)
    result = author.author_root(CAMPAIGN, THEME_ROOT, root_id=as_uuid)
    assert result.record.node_id == ROOT_ID
    assert author._session.calls[0]["node_id"] == ROOT_ID


# ── The prompt: theme_root and depth 0, empty history on the first root ─────


def test_prompt_names_theme_root_and_depth_zero() -> None:
    provider = FakeProvider([completion(CONFORMING_ANSWER, model=ROOT_MODEL)], model=ROOT_MODEL)
    author = build_author(provider=provider)
    author.author_root(CAMPAIGN, THEME_ROOT, root_id=ROOT_ID)
    system_text = provider.requests[0].messages[0].content
    assert '"theme_root": "momentum"' in system_text
    assert '"depth": 0' in system_text
    # The committed clause reaches the system message verbatim (feature 210).
    assert anti_convergence_gate().text() in system_text


def test_empty_history_renders_as_the_honest_first_node_statement() -> None:
    store = FakeHistoryStore()
    provider = FakeProvider([completion(CONFORMING_ANSWER, model=ROOT_MODEL)], model=ROOT_MODEL)
    author = build_author(provider=provider, history_store=store)
    author.author_root(CAMPAIGN, THEME_ROOT, root_id=ROOT_ID)
    assert store.history_calls == [CAMPAIGN]
    user_text = provider.requests[0].messages[-1].content
    assert "this is the first node" in user_text


def test_prior_history_reaches_the_root_prompt_verbatim() -> None:
    prior_node = str(uuid.uuid4())
    store = FakeHistoryStore(
        priors=(prior(prior_node, MOMENTUM_CODE),),
        scores={prior_node: ScoreRecord(ic_mean=0.3)},
    )
    provider = FakeProvider([completion(CONFORMING_ANSWER, model=ROOT_MODEL)], model=ROOT_MODEL)
    author = build_author(provider=provider, history_store=store)
    author.author_root(CAMPAIGN, THEME_ROOT, root_id=ROOT_ID)
    user_text = provider.requests[0].messages[-1].content
    assert MOMENTUM_CODE in user_text
    assert prior_node in user_text


# ── Acceptance: the four parts and the record ────────────────────────────────


def test_acceptance_carries_code_mechanism_proposal_and_record() -> None:
    provider = FakeProvider([completion(CONFORMING_ANSWER, model=ROOT_MODEL)], model=ROOT_MODEL)
    author = build_author(provider=provider, config=make_config(temperature=0.25))
    result = author.author_root(CAMPAIGN, THEME_ROOT, root_id=ROOT_ID)
    assert result.code == CONFORMING_CODE
    assert result.stated_mechanism == "momentum continuation after a liquidity sweep."
    assert result.proposal == CONFORMING_ANSWER
    record = result.record
    assert isinstance(record, providers.AuthoringRecord)
    assert record.campaign_id == CAMPAIGN
    assert record.served_model == ROOT_MODEL
    assert record.sampling == AgentSampling(temperature=0.25)
    assert record.tier == make_config().tier
    assert record.usage == Usage(10, 5, 0)


# ── The retry: a model-repairable defect is shown back, then accepted ───────


def test_non_conforming_source_is_retried_then_accepted() -> None:
    provider = FakeProvider(
        [
            completion(NON_CONFORMING_ANSWER, model=ROOT_MODEL),
            completion(CONFORMING_ANSWER, model=ROOT_MODEL),
        ],
        model=ROOT_MODEL,
    )
    author = build_author(provider=provider)
    result = author.author_root(CAMPAIGN, THEME_ROOT, root_id=ROOT_ID)
    assert result.code == CONFORMING_CODE
    assert provider.calls == 2
    defect = provider.requests[1].messages[-1].content
    assert "seed argument must be named" in defect


def test_converged_structure_against_a_prior_root_is_refused_then_repaired() -> None:
    store = FakeHistoryStore(
        priors=(prior(str(uuid.uuid4()), proposal_document(CONFORMING_CODE)),)
    )
    different_answer = fenced_answer(
        "def signal(ctx, seed):\n"
        "    spread = ctx.high - ctx.low\n"
        "    return spread.ewm_mean(span=seed)",
        mechanism="a range-compression bet.",
    )
    provider = FakeProvider(
        [
            completion(CONFORMING_ANSWER, model=ROOT_MODEL),
            completion(different_answer, model=ROOT_MODEL),
        ],
        model=ROOT_MODEL,
    )
    author = build_author(provider=provider, history_store=store, max_retries=1)
    result = author.author_root(CAMPAIGN, THEME_ROOT, root_id=ROOT_ID)
    assert provider.calls == 2
    assert "parameter_tweak" in provider.requests[1].messages[-1].content
    assert "spread" in result.code


def test_retries_spent_raises_authoring_refused() -> None:
    provider = FakeProvider(
        [
            completion(UNPARSEABLE_ANSWER, model=ROOT_MODEL),
            completion(UNPARSEABLE_ANSWER, model=ROOT_MODEL),
        ],
        model=ROOT_MODEL,
    )
    author = build_author(provider=provider, max_retries=1)
    with pytest.raises(AuthoringRefusedError) as caught:
        author.author_root(CAMPAIGN, THEME_ROOT, root_id=ROOT_ID)
    message = str(caught.value)
    assert message.startswith(AUTHORING_REFUSED_CODE)
    assert "authored_output" in message
    assert provider.calls == 2


# ── The non-retry: budget and serving-model failures propagate ───────────────


def test_budget_exhausted_propagates_and_is_not_retried() -> None:
    provider = FakeProvider(
        [BudgetExhaustedError("budget_exhausted: spent")], model=ROOT_MODEL
    )
    author = build_author(provider=provider, max_retries=3)
    with pytest.raises(BudgetExhaustedError):
        author.author_root(CAMPAIGN, THEME_ROOT, root_id=ROOT_ID)
    assert provider.calls == 1


def test_served_model_mismatch_propagates_and_is_not_retried() -> None:
    provider = FakeProvider(
        [completion(CONFORMING_ANSWER, model="some-other-model")], model=ROOT_MODEL
    )
    author = build_author(provider=provider, max_retries=3)
    with pytest.raises(ServedModelMismatchError):
        author.author_root(CAMPAIGN, THEME_ROOT, root_id=ROOT_ID)
    assert provider.calls == 1


# ── __call__ is unaffected: the depth role still routes an expansion ─────────


def test_call_still_routes_an_expansion_by_depth_role() -> None:
    import discovery

    workspace = discovery.NodeWorkspace(
        node_id=str(uuid.uuid4()),
        parent_id=None,
        campaign_id=CAMPAIGN,
        theme_root=THEME_ROOT,
        depth=1,
    )
    provider = FakeProvider([completion(CONFORMING_ANSWER, model=DEPTH_MODEL)], model=DEPTH_MODEL)
    author = build_author(provider=provider, role="depth")
    result = author(workspace)
    assert result.record.role == "depth"
    assert result.record.depth == 2
