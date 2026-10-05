"""Feature 7 — the LLM author: a workspace in, an authored signal out.

additions_spec_llm_authoring.xml: *"System authors a refined signal with
signal_agent._llm_author.LLMSignalAuthor(session, *, history_store, contract,
anti_convergence, guidance, config, max_retries=1)."*  The claims this suite
pins are the ones that make the object a *driver* rather than a prompt
builder:

* the **derivation** — the child's id is
  ``uuid5(discovery.EXPANSION_NAMESPACE, str(parent))`` and its depth is
  ``parent + 1``, and the role the model is chosen by is read off that depth
  (feature 3's :func:`providers.role_for_depth`);
* the **prompt** — every prior proposal of the campaign reaches the request
  verbatim, paired with its score, and both feature 208's guidance gate and
  feature 210's clause gate screen it *before* a call is placed;
* the **acceptance** — the answer is read by feature 6, adopted by feature
  205's contract, and admitted by feature 210's structural gate against the
  *code* each prior proposal holds (an unparsable prior is held at its
  recorded ``code_hash``), never against the proposals' raw markdown;
* the **retry** — a model-repairable defect (parse, adoption or structure) is
  shown back to the model up to ``max_retries`` times, and the whole authoring
  is refused as :class:`~signal_agent.AuthoringRefusedError` after the last;
* the **non-retry** — :class:`~providers.BudgetExhaustedError` and
  :class:`~providers.ServedModelMismatchError` propagate unchanged and are
  never retried;
* the **record** — the child, the role, the pin, the sampling, the usage
  summed over *every* call, the serving model and the root tier.

No network, no credential and no database: the provider is a fake (or a
:class:`providers.RecordedProvider` for the replay case) and the history store
is a stand-in, which is the shape this addition's constraint requires.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import discovery
import providers
import pytest
from providers import (
    AgentSampling,
    AuthoringConfig,
    AuthoringSession,
    BudgetExhaustedError,
    Completion,
    ModelPin,
    Provider,
    RecordedProvider,
    Request,
    ServedModelMismatchError,
    Usage,
)
from signal_agent import (
    AntiConvergenceClauseError,
    PriorProposal,
    ScoreRecord,
    SignalContract,
    anti_convergence_gate,
    prompt_guidance_gate,
    signal_contract,
    skeleton_digest,
)
from signal_agent._llm_author import (
    AUTHORING_REFUSED_CODE,
    AuthoredSignal,
    AuthoringRefusedError,
    LLMSignalAuthor,
)

#: The pins a deployment states, the same ids the session's own suite uses so
#: a fixture here reads like the deployment it stands in for.
ROOT_PIN = "anthropic/claude-opus-5/20260401"
DEPTH_PIN = "deepseek/deepseek-v4-flash/20260910"
POLICY_PIN = "google/gemini-3.1-pro/20260801"

ROOT_MODEL = "claude-opus-5"
DEPTH_MODEL = "deepseek-v4-flash"

CAMPAIGN = "8f14e45f-cea3-4f93-8d2e-000000000001"
PARENT = "8f14e45f-cea3-4f93-8d2e-000000000002"

#: A conforming signal source — §5.1's entrypoint, the declared parameters.
#: No trailing newline: feature 6's parser dedents and strips the block body,
#: so this is the exact text the contract adopts.
CONFORMING_CODE = (
    "def signal(ctx, seed):\n"
    "    return pl.Series([1.0] * len(ctx.universe))"
)

#: A *different* conforming structure, for prior-history fixtures: an answer
#: equal to this one is novel, so a test that wants the first answer accepted
#: must not hand the same skeleton in as a prior.
PRIOR_CODE = "def signal(ctx, seed):\n    return ctx.close.ewm_mean(span=10)"

#: The held-set fixtures' prior code — one-indicator momentum, the source the
#: bug report's own probe used.  An answer repeating it exactly, or with only
#: its numbers changed, is the convergence feature 210 exists to refuse.
MOMENTUM_CODE = "def signal(ctx, seed):\n    return ctx.closes().pct_change()"

#: The same structure with a number in it, and the same structure with that
#: number changed — a parameter tweak, the shape §14.1's "400th variant of one
#: indicator" is four hundred of.
MOMENTUM_WINDOW_20 = (
    "def signal(ctx, seed):\n"
    "    return ctx.closes().pct_change().rolling_mean(20)"
)
MOMENTUM_WINDOW_60 = (
    "def signal(ctx, seed):\n"
    "    return ctx.closes().pct_change().rolling_mean(60)"
)

#: A prior proposal document that carries no python fence at all, so feature
#: 6's parse cannot read code out of it — the shape whose only structure is
#: the ``code_hash`` its row recorded.
LOST_SOURCE_DOC = (
    "Mechanism: momentum.\n\n(The source block was lost in transit.)"
)

#: The same source, non-conforming: the second parameter is misnamed.
NON_CONFORMING_CODE = (
    "def signal(ctx, wrong_name):\n"
    "    return None"
)

CONFORMING_ANSWER = (
    "```python\n" + CONFORMING_CODE + "\n```\n\n"
    "Mechanism: momentum continuation after a liquidity sweep.\n"
)
NON_CONFORMING_ANSWER = (
    "```python\n" + NON_CONFORMING_CODE + "\n```\n\n"
    "Mechanism: a misnamed entrypoint.\n"
)
#: An answer with no python block at all — feature 6 refuses it.
UNPARSEABLE_ANSWER = "I cannot help with that request."


# ── The fakes ─────────────────────────────────────────────────────────────────


def completion(content: str, *, model: str, usage: tuple[int, int, int] = (10, 5, 0)) -> Completion:
    return Completion(
        content=content,
        model=model,
        usage=Usage(*usage),
    )


class FakeProvider(Provider):
    """A provider that answers a scripted list and keeps every request it saw.

    The spec's own instruction — *"Tests drive it with providers.
    RecordedProvider or a fake provider"* — made concrete: an answer may be a
    :class:`~providers.Completion` or an exception instance (raised from the
    seam, so a budget or serving-model failure travels the real path), and
    every request is captured so a test can assert on the prompt text.
    """

    def __init__(self, answers, *, model: str) -> None:
        self._answers = list(answers)
        self._model = model
        self.requests: list[Request] = []

    @property
    def calls(self) -> int:
        return len(self.requests)

    def _complete(self, request: Request) -> Completion:
        self.requests.append(request)
        if not self._answers:
            raise AssertionError("the fake provider was called more than scripted")
        answer = self._answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer


class FakeSession:
    """A minimal session: answers the ``(provider, pin)`` a role serves.

    The real :class:`providers.AuthoringSession` is exercised separately; this
    stand-in lets a test route an exact provider and pin without standing up a
    config's rotation, and records every call so the derivation of the role and
    the child id can be asserted.
    """

    def __init__(self, providers_by_role, pins_by_role) -> None:
        self._providers = providers_by_role
        self._pins = pins_by_role
        self.calls: list[dict] = []

    def provider_for(self, role, *, campaign_id, node_id):
        self.calls.append(
            {"role": role, "campaign_id": campaign_id, "node_id": node_id}
        )
        return self._providers[role], self._pins[role]


class FakeHistoryStore:
    """A history store: ``history(campaign_id)`` and ``load(node_id)``.

    ``load`` answers ``None`` for an unrecorded node (the honest three-way
    distinction the real store keeps), so the "a missing score is an absence,
    not a drop" claim is testable.
    """

    def __init__(self, priors=(), scores=None) -> None:
        self._priors = tuple(priors)
        self._scores = dict(scores or {})
        self.history_calls: list[str] = []
        self.load_calls: list[str] = []

    def history(self, campaign_id):
        self.history_calls.append(campaign_id)
        return self._priors

    def load(self, node_id):
        self.load_calls.append(node_id)
        if node_id not in self._scores:
            return None
        return SimpleNamespace(score=self._scores[node_id])


class RefusingGuidance:
    """A guidance gate whose ``require`` refuses — for the pre-call ordering."""

    def __init__(self, error: BaseException) -> None:
        self._error = error

    def require(self, prompt):
        raise self._error


class RefusingClauseGate:
    """An anti-convergence gate whose ``require_in`` refuses, clause intact.

    ``text()`` answers the committed clause so feature 5 can still build the
    prompt; only the *prompt* half refuses, which is exactly the ordering this
    suite pins — the refusal happens before the provider is reached.
    """

    def __init__(self, error: BaseException, text: str) -> None:
        self._error = error
        self._text = text

    def text(self) -> str:
        return self._text

    def require_in(self, prompt):
        raise self._error

    def admit(self, source, held=()):  # pragma: no cover - never reached
        raise AssertionError("a prompt refusal must precede the structural gate")


# ── Fixtures and builders ─────────────────────────────────────────────────────


def make_config(**overrides) -> AuthoringConfig:
    fields = {
        "root_tier": (ROOT_PIN,),
        "depth": DEPTH_PIN,
        "policy": POLICY_PIN,
        "temperature": 0.4,
        "max_tokens": 4096,
        "max_input_tokens": 1_000_000,
        "max_output_tokens": 1_000_000,
    }
    fields.update(overrides)
    return AuthoringConfig(**fields)


def workspace(depth: int = 0, node_id: str = PARENT) -> discovery.NodeWorkspace:
    return discovery.NodeWorkspace(
        node_id=node_id,
        parent_id=None,
        campaign_id=CAMPAIGN,
        theme_root="momentum",
        depth=depth,
    )


def prior(
    node_id: str, proposal: str = PRIOR_CODE, code_hash: str = "c" * 64
) -> PriorProposal:
    return PriorProposal(node_id=node_id, proposal=proposal, code_hash=code_hash)


def proposal_document(
    code: str, mechanism: str = "momentum over the prior close."
) -> str:
    """A prior proposal as the history actually persists one (feature 207).

    Feature 6 pins ``proposal`` as the model's *full raw answer* — the
    ``Mechanism:`` line, the prose and the ```` ```python ```` fence — and
    feature 207 persists that field verbatim, so this is the shape a real
    ``PriorProposal.proposal`` holds.  A bare source string is not: no store
    records one as a proposal document, and a held-set test that handed the
    gate bare source would be testing a history no campaign ever had.
    """
    return f"Mechanism: {mechanism}\n\n```python\n{code}\n```\n"


def fenced_answer(code: str, mechanism: str = "momentum over the prior close.") -> str:
    """An answer in the authoring format around ``code`` — the model's shape."""
    return f"```python\n{code}\n```\n\nMechanism: {mechanism}\n"


def build_author(
    *,
    provider: Provider,
    role: str = "root",
    pin: ModelPin | None = None,
    history_store: FakeHistoryStore | None = None,
    contract: SignalContract | None = None,
    anti_convergence=None,
    guidance=None,
    config: AuthoringConfig | None = None,
    max_retries: int = 1,
) -> LLMSignalAuthor:
    chosen_pin = pin or (
        ModelPin.parse(ROOT_PIN) if role == "root" else ModelPin.parse(DEPTH_PIN)
    )
    session = FakeSession({role: provider}, {role: chosen_pin})
    return LLMSignalAuthor(
        session,
        history_store=history_store if history_store is not None else FakeHistoryStore(),
        contract=contract if contract is not None else signal_contract(),
        anti_convergence=(
            anti_convergence if anti_convergence is not None else anti_convergence_gate()
        ),
        guidance=guidance if guidance is not None else prompt_guidance_gate(),
        config=config if config is not None else make_config(),
        max_retries=max_retries,
    )


# ── The derivation: child id, depth and role ──────────────────────────────────


def test_child_id_and_depth_follow_the_tree_rule() -> None:
    provider = FakeProvider(
        [completion(CONFORMING_ANSWER, model=ROOT_MODEL)], model=ROOT_MODEL
    )
    author = build_author(provider=provider)
    # A fake session so the routed role and node id can be read back.
    session = author._session
    result = author(workspace(depth=0))
    expected = str(uuid.uuid5(discovery.EXPANSION_NAMESPACE, PARENT))
    assert session.calls == [
        {"role": "root", "campaign_id": CAMPAIGN, "node_id": expected}
    ]
    assert result.record.node_id == expected


def test_depth_role_is_read_off_the_child_depth() -> None:
    # A child at depth 2 is past §14.1's root boundary: the depth pin serves it.
    for parent_depth, expected_role, model in (
        (0, "root", ROOT_MODEL),
        (1, "depth", DEPTH_MODEL),
    ):
        provider = FakeProvider([completion(CONFORMING_ANSWER, model=model)], model=model)
        author = build_author(
            provider=provider, role=expected_role
        )
        result = author(workspace(depth=parent_depth))
        assert author._session.calls[0]["role"] == expected_role
        assert result.record.role == expected_role
        assert result.record.depth == parent_depth + 1


# ── The prompt: every prior proposal, verbatim, before any call ───────────────


def test_request_carries_every_prior_proposal_verbatim() -> None:
    first = (
        "def signal(ctx, seed):\n"
        "    # " + ("x" * 4000) + "\n"
        "    return ctx.close.rolling_mean(20)\n"
    )
    second = "def signal(ctx, seed):\n    return ctx.volume\n"
    store = FakeHistoryStore(
        priors=(
            prior(str(uuid.uuid4()), first),
            prior(str(uuid.uuid4()), second),
        ),
        scores={},
    )
    provider = FakeProvider([completion(CONFORMING_ANSWER, model=ROOT_MODEL)], model=ROOT_MODEL)
    author = build_author(provider=provider, history_store=store)
    author(workspace())

    sent = provider.requests[0]
    user_text = sent.messages[-1].content
    system_text = sent.messages[0].content
    assert first in user_text
    assert second in user_text
    # The whole body, not a slice: the 4000-character comment is intact.
    assert "x" * 4000 in user_text
    # The committed clause reaches the system message verbatim (feature 210).
    assert anti_convergence_gate().text() in system_text
    # And the scores are carried beside each proposal, or the honest absence.
    assert "null" in user_text


def test_unscored_history_entries_are_kept_not_dropped() -> None:
    scored_node = str(uuid.uuid4())
    unscored_node = str(uuid.uuid4())
    store = FakeHistoryStore(
        priors=(prior(scored_node), prior(unscored_node)),
        scores={scored_node: ScoreRecord(ic_mean=0.2)},
    )
    provider = FakeProvider([completion(CONFORMING_ANSWER, model=ROOT_MODEL)], model=ROOT_MODEL)
    author = build_author(provider=provider, history_store=store)
    author(workspace())
    # Both nodes were asked about, and both reached the request.
    assert store.load_calls == [scored_node, unscored_node]
    user_text = provider.requests[0].messages[-1].content
    assert scored_node in user_text and unscored_node in user_text


# ── The gates run before any call ─────────────────────────────────────────────


def test_guidance_refusal_happens_before_any_call() -> None:
    from signal_agent import InjectedGuidanceError

    refusal = InjectedGuidanceError("injected_guidance: a digested section")
    provider = FakeProvider([completion(CONFORMING_ANSWER, model=ROOT_MODEL)], model=ROOT_MODEL)
    author = build_author(
        provider=provider, guidance=RefusingGuidance(refusal)
    )
    with pytest.raises(InjectedGuidanceError):
        author(workspace())
    assert provider.calls == 0


def test_clause_refusal_happens_before_any_call() -> None:
    refusal = AntiConvergenceClauseError("clause_absent: the prompt dropped it")
    gate = RefusingClauseGate(refusal, anti_convergence_gate().text())
    provider = FakeProvider([completion(CONFORMING_ANSWER, model=ROOT_MODEL)], model=ROOT_MODEL)
    author = build_author(provider=provider, anti_convergence=gate)
    with pytest.raises(AntiConvergenceClauseError):
        author(workspace())
    assert provider.calls == 0


# ── Acceptance: the four parts and the record ─────────────────────────────────


def test_acceptance_carries_code_mechanism_proposal_and_record() -> None:
    provider = FakeProvider([completion(CONFORMING_ANSWER, model=ROOT_MODEL)], model=ROOT_MODEL)
    author = build_author(provider=provider, config=make_config(temperature=0.25))
    result = author(workspace())
    assert isinstance(result, AuthoredSignal)
    assert result.code == CONFORMING_CODE
    assert result.stated_mechanism == "momentum continuation after a liquidity sweep."
    assert result.proposal == CONFORMING_ANSWER
    record = result.record
    assert isinstance(record, providers.AuthoringRecord)
    assert record.role == "root"
    assert record.served_model == ROOT_MODEL
    assert record.sampling == AgentSampling(temperature=0.25)
    assert record.tier == make_config().tier
    assert record.usage == Usage(10, 5, 0)


def test_depth_role_record_carries_no_tier() -> None:
    provider = FakeProvider([completion(CONFORMING_ANSWER, model=DEPTH_MODEL)], model=DEPTH_MODEL)
    author = build_author(provider=provider, role="depth")
    result = author(workspace(depth=1))
    assert result.record.role == "depth"
    assert result.record.tier is None


# ── The retry: repairable defects ─────────────────────────────────────────────


def test_unparseable_answer_is_retried_then_accepted() -> None:
    provider = FakeProvider(
        [
            completion(UNPARSEABLE_ANSWER, model=ROOT_MODEL),
            completion(CONFORMING_ANSWER, model=ROOT_MODEL),
        ],
        model=ROOT_MODEL,
    )
    author = build_author(provider=provider)
    result = author(workspace())
    assert result.code == CONFORMING_CODE
    assert provider.calls == 2
    # The retry request appends the assistant's answer and a user defect.
    retry = provider.requests[1]
    assert retry.messages[-2].role == "assistant"
    assert retry.messages[-2].content == UNPARSEABLE_ANSWER
    assert retry.messages[-1].role == "user"
    assert "authored_output" in retry.messages[-1].content


def test_non_conforming_source_is_retried_then_accepted() -> None:
    provider = FakeProvider(
        [
            completion(NON_CONFORMING_ANSWER, model=ROOT_MODEL),
            completion(CONFORMING_ANSWER, model=ROOT_MODEL),
        ],
        model=ROOT_MODEL,
    )
    author = build_author(provider=provider)
    result = author(workspace())
    assert result.code == CONFORMING_CODE
    assert provider.calls == 2
    # The defect quotes the adoption's own problem sentences.
    defect = provider.requests[1].messages[-1].content
    assert "seed argument must be named" in defect


def test_converged_structure_is_retried_then_accepted() -> None:
    # A prior proposal whose skeleton equals CONFORMING_ANSWER's, so the first
    # answer is a parameter tweak and is refused; the second is a genuinely
    # different structure and is admitted.  The prior is a *document* — the
    # fence and the Mechanism line a real history persists — holding that code.
    store = FakeHistoryStore(
        priors=(prior(str(uuid.uuid4()), proposal_document(CONFORMING_CODE)),)
    )
    different_answer = (
        "```python\n"
        "def signal(ctx, seed):\n"
        "    spread = ctx.high - ctx.low\n"
        "    return spread.ewm_mean(span=seed)\n"
        "```\n"
        "Mechanism: a range-compression bet.\n"
    )
    provider = FakeProvider(
        [
            completion(CONFORMING_ANSWER, model=ROOT_MODEL),
            completion(different_answer, model=ROOT_MODEL),
        ],
        model=ROOT_MODEL,
    )
    author = build_author(provider=provider, history_store=store, max_retries=1)
    result = author(workspace())
    assert provider.calls == 2
    assert result.code == (
        "def signal(ctx, seed):\n"
        "    spread = ctx.high - ctx.low\n"
        "    return spread.ewm_mean(span=seed)"
    )
    # The retry message the model saw names the anti-convergence gate's code.
    assert "parameter_tweak" in provider.requests[1].messages[-1].content


def test_converged_structure_refused_twice_raises_authoring_refused() -> None:
    store = FakeHistoryStore(
        priors=(prior(str(uuid.uuid4()), proposal_document(CONFORMING_CODE)),)
    )
    # Both answers hold the prior's skeleton (one differing only in a literal),
    # so the negative constraint refuses each and the whole authoring is refused.
    tweak = CONFORMING_ANSWER.replace("[1.0]", "[2.0]")
    provider = FakeProvider(
        [
            completion(CONFORMING_ANSWER, model=ROOT_MODEL),
            completion(tweak, model=ROOT_MODEL),
        ],
        model=ROOT_MODEL,
    )
    author = build_author(provider=provider, history_store=store, max_retries=1)
    with pytest.raises(AuthoringRefusedError) as caught:
        author(workspace())
    assert AUTHORING_REFUSED_CODE in str(caught.value)
    assert "parameter_tweak" in str(caught.value)


# ── The held set: prior code, not prior prose ─────────────────────────────────


def test_an_exact_repeat_of_a_prior_proposals_code_is_refused() -> None:
    # The bug's own reproduction: the prior proposal is a document — a
    # Mechanism line, prose and the fence — and the answer repeats the exact
    # source inside it.  Handing the gate the markdown left it nothing it
    # could parse, so the repeat was admitted as novel on the first call.
    store = FakeHistoryStore(
        priors=(prior(str(uuid.uuid4()), proposal_document(MOMENTUM_CODE)),)
    )
    repeat = fenced_answer(MOMENTUM_CODE, mechanism="momentum again.")
    provider = FakeProvider(
        [completion(repeat, model=ROOT_MODEL), completion(repeat, model=ROOT_MODEL)],
        model=ROOT_MODEL,
    )
    author = build_author(provider=provider, history_store=store, max_retries=1)
    with pytest.raises(AuthoringRefusedError) as caught:
        author(workspace())
    assert "parameter_tweak" in str(caught.value)
    assert provider.calls == 2
    # The refusal went through the existing retry path and named the gate's
    # own code word, so the model was told what to repair.
    assert "parameter_tweak" in provider.requests[1].messages[-1].content


def test_a_numbers_only_tweak_of_a_prior_proposals_code_is_refused() -> None:
    # The same structure with one literal changed — §14.1's "400th variant of
    # one indicator" — is the same hypothesis re-submitted, not a new one.
    store = FakeHistoryStore(
        priors=(prior(str(uuid.uuid4()), proposal_document(MOMENTUM_WINDOW_20)),)
    )
    tweak = fenced_answer(MOMENTUM_WINDOW_60, mechanism="momentum, smoothed.")
    provider = FakeProvider(
        [completion(tweak, model=ROOT_MODEL), completion(tweak, model=ROOT_MODEL)],
        model=ROOT_MODEL,
    )
    author = build_author(provider=provider, history_store=store, max_retries=1)
    with pytest.raises(AuthoringRefusedError) as caught:
        author(workspace())
    assert "parameter_tweak" in str(caught.value)
    assert provider.calls == 2


def test_a_structurally_new_signal_is_admitted_on_the_first_call() -> None:
    # The negative constraint refuses repeats, not novelty: against a prior
    # document holding MOMENTUM_CODE, a genuinely different structure — a new
    # term, not a new literal — is admitted without spending a retry.
    store = FakeHistoryStore(
        priors=(prior(str(uuid.uuid4()), proposal_document(MOMENTUM_CODE)),)
    )
    provider = FakeProvider([completion(CONFORMING_ANSWER, model=ROOT_MODEL)], model=ROOT_MODEL)
    author = build_author(provider=provider, history_store=store)
    result = author(workspace())
    assert result.code == CONFORMING_CODE
    assert provider.calls == 1


def test_an_unparsable_prior_proposal_is_held_at_its_recorded_code_hash() -> None:
    # A document with no python fence cannot be re-read for code, so the prior
    # is held at the digest its row recorded.  The fixture sets that hash to
    # the skeleton digest of the answer's own code, so a refusal here is the
    # code_hash fallback reaching the gate — the parse path never ran.
    store = FakeHistoryStore(
        priors=(
            prior(
                str(uuid.uuid4()),
                LOST_SOURCE_DOC,
                code_hash=skeleton_digest(MOMENTUM_CODE),
            ),
        )
    )
    repeat = fenced_answer(MOMENTUM_CODE)
    provider = FakeProvider(
        [completion(repeat, model=ROOT_MODEL), completion(repeat, model=ROOT_MODEL)],
        model=ROOT_MODEL,
    )
    author = build_author(provider=provider, history_store=store, max_retries=1)
    with pytest.raises(AuthoringRefusedError) as caught:
        author(workspace())
    assert "parameter_tweak" in str(caught.value)
    assert provider.calls == 2


def test_an_unparsable_prior_proposal_with_no_code_hash_is_skipped() -> None:
    # Nothing to hold the prior at — no code to read, no hash recorded — so
    # the comparison set the gate sees is empty and the repeat is admitted as
    # the campaign's first structure.  A prior the gate cannot read is one it
    # has no opinion about, which is the gate's own stance.
    store = FakeHistoryStore(
        priors=(prior(str(uuid.uuid4()), LOST_SOURCE_DOC, code_hash=""),)
    )
    provider = FakeProvider(
        [completion(fenced_answer(MOMENTUM_CODE), model=ROOT_MODEL)],
        model=ROOT_MODEL,
    )
    author = build_author(provider=provider, history_store=store)
    result = author(workspace())
    assert result.code == MOMENTUM_CODE
    assert provider.calls == 1


def test_retries_spent_raises_authoring_refused_naming_the_last_defect() -> None:
    provider = FakeProvider(
        [
            completion(UNPARSEABLE_ANSWER, model=ROOT_MODEL),
            completion(UNPARSEABLE_ANSWER, model=ROOT_MODEL),
        ],
        model=ROOT_MODEL,
    )
    author = build_author(provider=provider, max_retries=1)
    with pytest.raises(AuthoringRefusedError) as caught:
        author(workspace())
    message = str(caught.value)
    assert message.startswith(AUTHORING_REFUSED_CODE)
    assert "authored_output" in message
    assert provider.calls == 2


def test_zero_retries_refuses_after_the_first_bad_answer() -> None:
    provider = FakeProvider([completion(UNPARSEABLE_ANSWER, model=ROOT_MODEL)], model=ROOT_MODEL)
    author = build_author(provider=provider, max_retries=0)
    with pytest.raises(AuthoringRefusedError):
        author(workspace())
    assert provider.calls == 1


def test_negative_max_retries_is_refused() -> None:
    with pytest.raises(ValueError):
        build_author(
            provider=FakeProvider([], model=ROOT_MODEL), max_retries=-1
        )


# ── The non-retry: budget and serving-model failures propagate ────────────────


def test_budget_exhausted_propagates_and_is_not_retried() -> None:
    provider = FakeProvider(
        [BudgetExhaustedError("budget_exhausted: spent")], model=ROOT_MODEL
    )
    author = build_author(provider=provider, max_retries=3)
    with pytest.raises(BudgetExhaustedError):
        author(workspace())
    assert provider.calls == 1


def test_served_model_mismatch_propagates_and_is_not_retried() -> None:
    provider = FakeProvider(
        [completion(CONFORMING_ANSWER, model="some-other-model")], model=ROOT_MODEL
    )
    author = build_author(provider=provider, max_retries=3)
    with pytest.raises(ServedModelMismatchError):
        author(workspace())
    assert provider.calls == 1


# ── Usage summed over every call ──────────────────────────────────────────────


def test_usage_is_summed_over_every_call_including_refused_ones() -> None:
    provider = FakeProvider(
        [
            completion(UNPARSEABLE_ANSWER, model=ROOT_MODEL, usage=(10, 5, 2)),
            completion(CONFORMING_ANSWER, model=ROOT_MODEL, usage=(20, 7, 3)),
        ],
        model=ROOT_MODEL,
    )
    author = build_author(provider=provider, max_retries=1)
    result = author(workspace())
    assert result.record.usage == Usage(30, 12, 5)


# ── The real session, and the recorded provider ───────────────────────────────


class _Resolver:
    """A resolver that hands back one provider per pin, built from a script."""

    def __init__(self, script) -> None:
        self._script = script
        self.calls: list[ModelPin] = []

    def __call__(self, pin: ModelPin) -> Provider:
        self.calls.append(pin)
        return self._script(pin)


def test_drives_the_real_authoring_session() -> None:
    def script(pin: ModelPin) -> Provider:
        return FakeProvider([completion(CONFORMING_ANSWER, model=pin.model)], model=pin.model)

    session = AuthoringSession(make_config(), _Resolver(script))
    author = LLMSignalAuthor(
        session,
        history_store=FakeHistoryStore(),
        contract=signal_contract(),
        anti_convergence=anti_convergence_gate(),
        guidance=prompt_guidance_gate(),
        config=make_config(),
    )
    result = author(workspace())
    assert result.record.role == "root"
    assert result.record.pin == ModelPin.parse(ROOT_PIN)
    assert result.record.served_model == ROOT_MODEL


def test_recorded_provider_replays_the_prompt() -> None:
    # Capture the exact request the author builds, then replay it offline — the
    # "RecordedProvider" shape the spec names.  The prompt is deterministic, so
    # the recorded hash matches the replayed one.
    capture = FakeProvider([completion(CONFORMING_ANSWER, model=ROOT_MODEL)], model=ROOT_MODEL)
    build_author(provider=capture)(workspace())
    recorded_request = capture.requests[0]

    replay = RecordedProvider(
        [providers.RecordedResponse(request=recorded_request, completion=completion(CONFORMING_ANSWER, model=ROOT_MODEL))]
    )
    author = build_author(provider=replay)
    result = author(workspace())
    assert result.code == CONFORMING_CODE
    assert result.proposal == CONFORMING_ANSWER


# ── The seam discovery actually consumes ──────────────────────────────────────


def test_the_result_is_the_shape_discovery_reads() -> None:
    provider = FakeProvider([completion(CONFORMING_ANSWER, model=ROOT_MODEL)], model=ROOT_MODEL)
    result = build_author(provider=provider)(workspace())
    # NodeExpansion reads .code (non-blank str) and an optional .stated_mechanism
    # (str or None) and ignores every other attribute.
    assert isinstance(result.code, str) and result.code.strip()
    assert isinstance(result.stated_mechanism, str)
