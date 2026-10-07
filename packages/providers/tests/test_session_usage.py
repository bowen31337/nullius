"""Feature 4 of additions_spec_llm_usage_tracking.xml: the session records usage.

*System records the usage of every authoring call a campaign makes, so that
each provider ``AuthoringSession.provider_for`` returns is wrapped in a
``UsageRecordingProvider`` bound to that call's ``campaign_id``, ``node_id``,
``role`` and ``pin`` whenever a usage store is configured.*  Feature 3 gave the
package the store and the recorder; this suite is the join, over the same
fake-resolver shape :mod:`test_authoring_session` already drives — no
database but the tmp sqlite file ``database_url`` names, no network and no
credential.

Three things the addition's sentence states, three groups of tests:

* a session built with a ``usage_store`` records one row per completed call,
  attributed to that call's own campaign, node, role and pin — proven by
  authoring a root, a child and a retry of that child, the shape
  ``signal_agent._llm_author`` drives this session through;
* a session built with **no** store (the default) is byte-identical to a
  session from before this feature: no row is ever written, and
  ``provider_for`` answers the same cached :class:`~providers.BudgetedProvider`
  it always did;
* a call the budget refuses still records one row — ``refused_budget``, zero
  tokens — and the budget's own ceilings and running totals are untouched by
  the recording sitting outside it.
"""

from __future__ import annotations

import uuid

import pytest
from providers import (
    AuthoringConfig,
    AuthoringSession,
    BudgetedProvider,
    BudgetExhaustedError,
    ModelPin,
    Provider,
)
from providers._usage_store import UsageStore

ROOT_PINS = (
    "anthropic/claude-opus-5/20260401",
    "openai/gpt-5.6-sol/20260701",
    "google/gemini-3.1-pro/20260801",
)
DEPTH_PIN = "deepseek/deepseek-v4-flash/20260910"


def make_config(**overrides) -> AuthoringConfig:
    """A full authoring config with sensible ceilings, any field overridden.

    The same fixture :mod:`test_authoring_session` builds, restated here
    rather than imported: this suite is about the recorder the session wraps
    around a pin, not about the routing that fixture's suite already covers.
    """
    fields = {
        "root_tier": ROOT_PINS,
        "depth": DEPTH_PIN,
        "policy": "google/gemini-3.1-pro/20260801",
        "temperature": 0.4,
        "max_tokens": 4096,
        "max_input_tokens": 1_000_000,
        "max_output_tokens": 1_000_000,
    }
    fields.update(overrides)
    return AuthoringConfig(**fields)


class CountingResolver:
    """A fake resolver answering a scripted provider per pin, counting calls.

    The same shape :mod:`test_authoring_session`'s own fixture uses: no
    network and no credential, so this suite drives the recorder with
    exactly the fake the addition's own sentence names ("a session with a
    fake resolver").
    """

    def __init__(self, factory):
        self._factory = factory
        self.calls: list[ModelPin] = []

    def __call__(self, pin: ModelPin) -> Provider:
        self.calls.append(pin)
        return self._factory(pin)


@pytest.fixture
def resolver(scripted_provider, make_completion):
    """A counting resolver whose scripted provider answers a small, fixed usage."""

    def factory(pin: ModelPin) -> Provider:
        return scripted_provider(
            lambda request: make_completion(
                f"answer for {pin.agent_model_id}",
                model=pin.model,
                input_tokens=10,
                output_tokens=5,
            )
        )

    return CountingResolver(factory)


@pytest.fixture
def request_(make_request):
    """One minimal, valid request — a fresh one per call, like a real author's."""

    def _build():
        return make_request(bodies=(("user", "author a signal"),))

    return _build


# ── Recording: a root, a child and a retry — three rows, right attribution ───


def test_a_root_a_child_and_a_retry_record_three_rows(database_url, resolver, request_):
    store = UsageStore(database_url)
    session = AuthoringSession(make_config(), resolver, usage_store=store)
    campaign = str(uuid.uuid4())
    root_node = str(uuid.uuid4())
    child_node = str(uuid.uuid4())

    root_provider, root_pin = session.provider_for(
        "root", campaign_id=campaign, node_id=root_node
    )
    root_provider.complete(request_())

    child_provider, child_pin = session.provider_for(
        "depth", campaign_id=campaign, node_id=child_node
    )
    child_provider.complete(request_())

    # The retry: the same child node authored again (the shape
    # signal_agent._llm_author drives when a first attempt must be redone).
    retry_provider, retry_pin = session.provider_for(
        "depth", campaign_id=campaign, node_id=child_node
    )
    retry_provider.complete(request_())

    rows = store.rows(campaign_id=campaign)
    assert len(rows) == 3
    assert [row.role for row in rows] == ["root", "depth", "depth"]
    assert [row.node_id for row in rows] == [root_node, child_node, child_node]
    assert all(row.campaign_id == campaign for row in rows)
    assert rows[0].pin == str(root_pin)
    assert rows[1].pin == rows[2].pin == str(child_pin) == str(retry_pin)
    assert all(row.outcome == "ok" for row in rows)


def test_the_recorded_pin_is_the_pin_provider_for_answered(
    database_url, resolver, request_
):
    store = UsageStore(database_url)
    session = AuthoringSession(make_config(), resolver, usage_store=store)
    campaign = str(uuid.uuid4())
    node = str(uuid.uuid4())
    provider, pin = session.provider_for(
        "policy", campaign_id=campaign, node_id=node
    )
    provider.complete(request_())
    (row,) = store.rows(campaign_id=campaign)
    assert row.pin == str(pin)
    assert row.role == "policy"
    assert row.node_id == node
    assert row.campaign_id == campaign


def test_a_second_call_on_the_same_pin_is_a_second_row(database_url, resolver, request_):
    # One budgeted provider is cached per pin, but the recorder wrapped around
    # it is rebuilt per provider_for call, so each call still leaves its own
    # row rather than the second being lost to the cache.
    store = UsageStore(database_url)
    session = AuthoringSession(make_config(), resolver, usage_store=store)
    campaign = str(uuid.uuid4())
    node = str(uuid.uuid4())
    first, _ = session.provider_for("depth", campaign_id=campaign, node_id=node)
    first.complete(request_())
    second, _ = session.provider_for("depth", campaign_id=campaign, node_id=node)
    second.complete(request_())
    assert len(store.rows(campaign_id=campaign)) == 2


# ── No store: byte-identical to a session with no usage tracking at all ─────


def test_with_no_store_provider_for_answers_the_bare_budgeted_provider(resolver):
    session = AuthoringSession(make_config(), resolver)
    provider, _ = session.provider_for(
        "depth", campaign_id=str(uuid.uuid4()), node_id=str(uuid.uuid4())
    )
    assert isinstance(provider, BudgetedProvider)


def test_with_no_store_the_same_pin_still_answers_the_same_cached_object(resolver):
    session = AuthoringSession(make_config(), resolver)
    campaign = str(uuid.uuid4())
    node = str(uuid.uuid4())
    first, _ = session.provider_for("depth", campaign_id=campaign, node_id=node)
    second, _ = session.provider_for("depth", campaign_id=campaign, node_id=node)
    assert first is second


def test_with_no_store_no_rows_are_ever_written(database_url, resolver, request_):
    # A store exists (so this test can prove it stayed empty), but the
    # session was never given it — the addition's "without one, behaviour is
    # byte-identical to today" means no row anywhere, not just no crash.
    store = UsageStore(database_url)
    session = AuthoringSession(make_config(), resolver)
    campaign = str(uuid.uuid4())
    for role, node in (
        ("root", str(uuid.uuid4())),
        ("depth", str(uuid.uuid4())),
        ("policy", str(uuid.uuid4())),
    ):
        provider, _ = session.provider_for(role, campaign_id=campaign, node_id=node)
        provider.complete(request_())
    assert store.rows(campaign_id=campaign) == ()


# ── A budget refusal: one refused_budget row, the budget itself untouched ───


def test_a_budget_refusal_records_one_refused_budget_row(
    database_url, scripted_provider, make_completion, request_
):
    # A ceiling the first call already exceeds, so the *second* call is the
    # one the budget refuses — one running total for the pin, spent down
    # across both provider_for calls, exactly as test_authoring_session
    # proves for the unwrapped BudgetedProvider.
    def factory(pin):
        return scripted_provider(
            lambda request: make_completion(
                "answer", model=pin.model, input_tokens=10, output_tokens=50
            )
        )

    resolver = CountingResolver(factory)
    store = UsageStore(database_url)
    session = AuthoringSession(
        make_config(max_output_tokens=50), resolver, usage_store=store
    )
    campaign = str(uuid.uuid4())

    first, _ = session.provider_for(
        "depth", campaign_id=campaign, node_id=str(uuid.uuid4())
    )
    first.complete(request_())

    second, pin = session.provider_for(
        "depth", campaign_id=campaign, node_id=str(uuid.uuid4())
    )
    with pytest.raises(BudgetExhaustedError):
        second.complete(request_())

    rows = store.rows(campaign_id=campaign)
    assert len(rows) == 2
    assert rows[0].outcome == "ok"
    assert rows[1].outcome == "refused_budget"
    assert rows[1].input_tokens == 0
    assert rows[1].output_tokens == 0
    assert rows[1].campaign_id == campaign
    assert rows[1].role == "depth"
    assert rows[1].pin == str(pin)


def test_the_budget_refusal_row_does_not_change_the_budgets_own_totals(
    database_url, scripted_provider, make_completion, request_
):
    def factory(pin):
        return scripted_provider(
            lambda request: make_completion(
                "answer", model=pin.model, input_tokens=10, output_tokens=50
            )
        )

    resolver = CountingResolver(factory)
    store = UsageStore(database_url)
    session = AuthoringSession(
        make_config(max_output_tokens=50), resolver, usage_store=store
    )
    campaign = str(uuid.uuid4())
    node = str(uuid.uuid4())

    recording_provider, pin = session.provider_for(
        "depth", campaign_id=campaign, node_id=node
    )
    recording_provider.complete(request_())
    # The cached, unwrapped BudgetedProvider underneath — the object the
    # ceilings and running spend actually live on.
    budgeted = session.providers[pin]
    assert isinstance(budgeted, BudgetedProvider)
    assert budgeted.spent() == (10, 50)

    with pytest.raises(BudgetExhaustedError):
        recording_provider.complete(request_())
    # The refusal recorded a row (proven above); the budget itself never saw
    # a call it could count, so its running spend is exactly as before.
    assert budgeted.spent() == (10, 50)
