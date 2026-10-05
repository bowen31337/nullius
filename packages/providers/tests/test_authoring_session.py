"""Feature 3's suite: the authoring session — one budgeted provider per pin.

Feature 2 gave the deployment a config of pinned models and feature 4 will give
the calls they answer a store; this feature joins them, and the suite tests the
three things its sentence joins:

* the **routing** — which pin a role serves, with the root role drawing the
  same family the rotation will record;
* the **resolution** — one provider per pin per session, so a campaign spends
  one budget per model rather than one per call, counted with a fake resolver;
* the **boundary** — :func:`providers.role_for_depth`, as the rule feature 7's
  author reads off a child's depth.

No database, no credential and no network: the resolver is a fake that hands
back a scripted provider and counts how often it was asked, which is the shape
this addition's constraint requires and the reason the session takes a resolver
rather than reaching for the live registry itself.
"""

from __future__ import annotations

import uuid

import pytest
from providers import (
    AuthoringConfig,
    AuthoringConfigError,
    AuthoringSession,
    BudgetedProvider,
    BudgetExhaustedError,
    ModelPin,
    Provider,
    RootRotationError,
    role_for_depth,
    rotation_index,
)
from providers._authoring import AUTHORING_ROLES

#: §14.1's roots row and §14.2's depth row, as the pins a deployment states.
#: The same ids feature 2's suite uses, so a session fixture reads like the
#: deployment it stands in for.
ROOT_PINS = (
    "anthropic/claude-opus-5/20260401",
    "openai/gpt-5.6-sol/20260701",
    "google/gemini-3.1-pro/20260801",
)
DEPTH_PIN = "deepseek/deepseek-v4-flash/20260910"


def make_config(**overrides) -> AuthoringConfig:
    """A full authoring config with sensible ceilings, any field overridden.

    The depth and policy pins default to *different* models, so a test that
    wants the two roles to share one budget says so by overriding — the
    shared-budget case is a deliberate statement rather than the fixture's
    accident.
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


class StubProvider(Provider):
    """A provider that answers nothing useful, for routing-only tests.

    Resolution always wraps the answer in a :class:`BudgetedProvider`, so even
    a test that only reads the routed *pin* needs a real provider to resolve —
    a ``None`` would be refused by the wrapper's own constructor.
    """

    def _complete(self, request):  # pragma: no cover - never called here
        raise AssertionError("the routing tests never complete a call")


class CountingResolver:
    """A fake resolver that counts its calls and hands back a provider per pin.

    The spec's own instruction — *"Tests use a fake resolve that counts
    calls"* — made concrete: the resolver records every pin it was asked for
    and how often, and answers a fresh scripted provider each time it is
    called, so a test can prove the session resolved a pin **once** by
    asserting the provider it got back is the same object it got before and
    that the count did not move.
    """

    def __init__(self, factory=None):
        self._factory = factory or (lambda pin: StubProvider())
        self.calls: list[ModelPin] = []

    def __call__(self, pin: ModelPin) -> Provider:
        self.calls.append(pin)
        return self._factory(pin)

    @property
    def count(self) -> int:
        return len(self.calls)


@pytest.fixture
def resolver(scripted_provider, make_completion):
    """A counting resolver answering a scripted provider per pin.

    Each scripted provider answers with a usage that spends a *little*, so a
    budget test can drive several calls before a ceiling is reached — the
    ceilings are set per test.
    """

    def factory(pin: ModelPin) -> Provider:
        return scripted_provider(
            lambda request: make_completion(
                f"answer for {pin.agent_model_id}",
                model=pin.model,
                input_tokens=100,
                output_tokens=50,
            )
        )

    return CountingResolver(factory)


@pytest.fixture
def make_request():
    """A minimal valid request, modelled on the conftest builder's shape."""
    from providers import Message, Request

    return Request(
        messages=(Message(role="user", content="author a signal"),),
        model="irrelevant",
        temperature=0.0,
        max_tokens=64,
    )


# ── role_for_depth: the §14.1 boundary as one comparison ──────────────────────


def test_a_child_at_or_above_the_boundary_is_a_root():
    # §14.1's roots row is depths 0–1; a child at either depth is authored by
    # the rotated frontier tier.
    assert role_for_depth(0) == "root"
    assert role_for_depth(1) == "root"


def test_the_first_child_below_the_boundary_is_a_depth_call():
    # The boundary's other end, pinned against feature 196's own constant: the
    # first depth the rotation does not cover is the first depth call.
    assert role_for_depth(2) == "depth"
    assert role_for_depth(7) == "depth"


def test_the_answer_is_always_one_of_the_two_tree_roles():
    for depth in range(12):
        assert role_for_depth(depth) in {"root", "depth"}


@pytest.mark.parametrize("value", [True, False, "1", 1.5, None, [], object()])
def test_a_non_integer_depth_is_refused(value):
    # A bool is refused beside the integers because True is an int in Python and
    # a depth of True must not be read as depth 1.
    with pytest.raises(AuthoringConfigError):
        role_for_depth(value)


def test_a_negative_depth_is_refused():
    with pytest.raises(AuthoringConfigError):
        role_for_depth(-1)


# ── The session: construction ────────────────────────────────────────────────


def test_a_session_over_a_config_and_a_resolver(resolver):
    session = AuthoringSession(make_config(), resolver)
    assert session.config == make_config()
    assert session.providers == {}


def test_a_config_that_is_not_one_is_refused(resolver):
    with pytest.raises(AuthoringConfigError):
        AuthoringSession({"root_tier": ROOT_PINS}, resolver)


def test_a_resolver_that_is_not_callable_is_refused():
    with pytest.raises(AuthoringConfigError):
        AuthoringSession(make_config(), "not a resolver")


# ── The routing: depth and policy answer their one pin ───────────────────────


def test_the_depth_role_answers_the_depth_pin(resolver):
    session = AuthoringSession(make_config(), resolver)
    provider, pin = session.provider_for(
        "depth", campaign_id=str(uuid.uuid4()), node_id=str(uuid.uuid4())
    )
    assert pin == ModelPin.parse(DEPTH_PIN)
    assert isinstance(provider, Provider)


def test_the_policy_role_answers_the_policy_pin(resolver):
    session = AuthoringSession(make_config(), resolver)
    _, pin = session.provider_for(
        "policy", campaign_id="policy-development", node_id="revision-3"
    )
    assert pin == ModelPin.parse("google/gemini-3.1-pro/20260801")


def test_a_role_outside_the_three_is_refused_by_name(resolver):
    session = AuthoringSession(make_config(), resolver)
    with pytest.raises(AuthoringConfigError) as raised:
        session.provider_for(
            "frontier", campaign_id=str(uuid.uuid4()), node_id=str(uuid.uuid4())
        )
    assert "frontier" in str(raised.value)
    assert resolver.count == 0  # refused before any resolution


def test_every_declared_role_routes(resolver):
    session = AuthoringSession(make_config(), resolver)
    campaign = str(uuid.uuid4())
    node = str(uuid.uuid4())
    for role in AUTHORING_ROLES:
        session.provider_for(role, campaign_id=campaign, node_id=node)


# ── The rotation: root draws the family the recorder will see ────────────────


def test_the_root_role_draws_from_the_declared_tier():
    session = AuthoringSession(make_config(), CountingResolver())
    config = session.config
    campaign = str(uuid.uuid4())
    for _ in range(32):
        node = str(uuid.uuid4())
        _, pin = session.provider_for("root", campaign_id=campaign, node_id=node)
        # The chosen pin is one the tier declares, named as (provider, model).
        assert (pin.provider, pin.model) in {
            (member.provider, member.model) for member in config.tier.providers
        }


def test_the_root_pin_is_the_rotation_index_over_the_canonical_tier():
    # The same decision RootRotation records: index the canonical tier the way
    # rotation_index does, and map the member back to the config's pin.  The
    # session must agree with this, or feature 4's recorder would meet
    # UnassignedRootProviderError.
    config = make_config()
    session = AuthoringSession(config, CountingResolver())
    campaign = str(uuid.uuid4())
    node = str(uuid.uuid4())
    index = rotation_index(campaign, node, config.tier)
    member = config.tier.providers[index]
    expected = next(
        pin
        for pin in config.root_tier
        if (pin.provider, pin.model) == (member.provider, member.model)
    )
    _, pin = session.provider_for("root", campaign_id=campaign, node_id=node)
    assert pin == expected


def test_the_index_is_applied_to_the_tier_not_the_file_order():
    # A file that listed its pins out of sorted order is the case the two
    # orders disagree on.  The session must follow the tier's canonical order —
    # the order RootRotation.assign indexes — so a campaign whose root lands on
    # the tier's first member is served by that member whatever the file's
    # order was.
    config = make_config(root_tier=tuple(reversed(ROOT_PINS)))
    session = AuthoringSession(config, CountingResolver())
    campaign = str(uuid.uuid4())
    for _ in range(32):
        node = str(uuid.uuid4())
        index = rotation_index(campaign, node, config.tier)
        member = config.tier.providers[index]
        _, pin = session.provider_for("root", campaign_id=campaign, node_id=node)
        assert (pin.provider, pin.model) == (member.provider, member.model)


def test_the_same_root_always_draws_one_family():
    session = AuthoringSession(make_config(), CountingResolver())
    campaign = str(uuid.uuid4())
    node = str(uuid.uuid4())
    pins = {
        session.provider_for("root", campaign_id=campaign, node_id=node)[1]
        for _ in range(8)
    }
    assert len(pins) == 1


def test_the_session_agrees_with_the_rotation_the_recorder_uses(tree_database, root_call):
    # The spec's own guarantee, driven end to end: feature 4 records a root
    # through RootRotation, so the pin this session serves a root with must be
    # the family the rotation assigns that root — otherwise the recorder meets
    # UnassignedRootProviderError.  The file order (anthropic, openai, google)
    # differs from the tier's canonical order (anthropic, google, openai), so a
    # session that indexed root_tier by file order would fail this test.
    from providers import RootRotation

    call, _node = root_call(tree_database, depth=0)
    config = make_config()
    session = AuthoringSession(config, CountingResolver())
    _, pin = session.provider_for(
        "root", campaign_id=call.campaign_id, node_id=call.node_id
    )
    assignment = RootRotation(tree_database).assign(call, config.tier)
    assert (assignment.provider, assignment.model) == (pin.provider, pin.model)


def test_a_malformed_node_id_is_refused_by_the_rotation(resolver):
    # The rotation canonicalises the ids; delegating means a bad node id is its
    # refusal, not this session's — and not a silently different pin.
    session = AuthoringSession(make_config(), resolver)
    with pytest.raises(RootRotationError):
        session.provider_for(
            "root", campaign_id=str(uuid.uuid4()), node_id="not-a-uuid"
        )


# ── The resolution: one provider per pin, one budget per provider ────────────


def test_each_pin_is_resolved_once_per_session(resolver):
    session = AuthoringSession(make_config(), resolver)
    campaign = str(uuid.uuid4())
    for _ in range(5):
        session.provider_for("depth", campaign_id=campaign, node_id=str(uuid.uuid4()))
    assert resolver.count == 1


def test_the_same_pin_answers_the_same_provider_object(resolver):
    session = AuthoringSession(make_config(), resolver)
    campaign = str(uuid.uuid4())
    node = str(uuid.uuid4())
    first, _ = session.provider_for("depth", campaign_id=campaign, node_id=node)
    second, _ = session.provider_for("depth", campaign_id=campaign, node_id=node)
    assert first is second
    assert resolver.count == 1


def test_two_roles_naming_one_model_share_one_budget(scripted_provider, make_completion):
    # The §14.1 split a role-keyed cache would reintroduce: depth and policy
    # pinned to the same model is one budget, and the resolver must be asked
    # once.
    def factory(pin):
        return scripted_provider(
            lambda request: make_completion(
                "answer", model=pin.model, input_tokens=1, output_tokens=1
            )
        )

    resolver = CountingResolver(factory)
    session = AuthoringSession(make_config(policy=DEPTH_PIN), resolver)
    campaign = str(uuid.uuid4())
    depth_provider, depth_pin = session.provider_for(
        "depth", campaign_id=campaign, node_id=str(uuid.uuid4())
    )
    policy_provider, policy_pin = session.provider_for(
        "policy", campaign_id="policy-development", node_id="revision-1"
    )
    assert depth_pin == policy_pin
    assert depth_provider is policy_provider
    assert resolver.count == 1


def test_two_distinct_pins_are_resolved_separately(resolver):
    # Each distinct pin is resolved exactly once: the count is the number of
    # distinct pins the three roles name, which varies with the rotation (a
    # root may draw the policy pin's family), so the assertion is on the set
    # rather than on a hard-coded three.
    session = AuthoringSession(make_config(), resolver)
    campaign = str(uuid.uuid4())
    node = str(uuid.uuid4())
    _, root_pin = session.provider_for("root", campaign_id=campaign, node_id=node)
    _, depth_pin = session.provider_for("depth", campaign_id=campaign, node_id=node)
    _, policy_pin = session.provider_for("policy", campaign_id=campaign, node_id=node)
    assert set(resolver.calls) == {root_pin, depth_pin, policy_pin}
    assert resolver.count == len({root_pin, depth_pin, policy_pin})


def test_the_resolver_is_a_providers_pin(resolver):
    seen: list[ModelPin] = []

    def recording(pin):
        seen.append(pin)
        return resolver(pin)

    session = AuthoringSession(make_config(), recording)
    session.provider_for(
        "depth", campaign_id=str(uuid.uuid4()), node_id=str(uuid.uuid4())
    )
    assert seen == [ModelPin.parse(DEPTH_PIN)]


# ── The budget: one running total per pinned model ───────────────────────────


def test_the_wrapper_carries_the_configs_ceilings(resolver):
    session = AuthoringSession(
        make_config(max_input_tokens=1234, max_output_tokens=5678), resolver
    )
    provider, _ = session.provider_for(
        "depth", campaign_id=str(uuid.uuid4()), node_id=str(uuid.uuid4())
    )
    assert isinstance(provider, BudgetedProvider)
    assert provider.spent() == (0, 0)


def test_the_budget_is_spent_down_across_calls_to_one_pin(
    scripted_provider, make_completion, make_request
):
    # 100 input / 50 output per answer, ceiling 100 output: the first call
    # crosses the ceiling, and the *next* call is refused — one budget for the
    # pin, drawn on by every call.
    def factory(pin):
        return scripted_provider(
            lambda request: make_completion(
                "answer", model=pin.model, input_tokens=100, output_tokens=50
            )
        )

    session = AuthoringSession(
        make_config(policy=DEPTH_PIN, max_output_tokens=50),
        CountingResolver(factory),
    )
    campaign = str(uuid.uuid4())
    provider, _ = session.provider_for(
        "depth", campaign_id=campaign, node_id=str(uuid.uuid4())
    )
    provider.complete(make_request)
    assert provider.spent() == (100, 50)
    # A second role on the same pin shares the object and its spend.
    same, _ = session.provider_for(
        "policy", campaign_id="policy-development", node_id="revision-1"
    )
    assert same is provider
    with pytest.raises(BudgetExhaustedError):
        same.complete(make_request)


def test_two_pins_do_not_share_a_budget(
    scripted_provider, make_completion, make_request
):
    def factory(pin):
        return scripted_provider(
            lambda request: make_completion(
                "answer", model=pin.model, input_tokens=100, output_tokens=50
            )
        )

    session = AuthoringSession(
        make_config(max_output_tokens=100), CountingResolver(factory)
    )
    campaign = str(uuid.uuid4())
    node = str(uuid.uuid4())
    depth, _ = session.provider_for("depth", campaign_id=campaign, node_id=node)
    policy, _ = session.provider_for("policy", campaign_id=campaign, node_id=node)
    depth.complete(make_request)
    # The policy pin has its own budget, untouched by the depth pin's spend.
    assert policy.spent() == (0, 0)


def test_the_providers_property_is_a_fresh_mapping(resolver):
    session = AuthoringSession(make_config(), resolver)
    session.provider_for(
        "depth", campaign_id=str(uuid.uuid4()), node_id=str(uuid.uuid4())
    )
    snapshot = session.providers
    snapshot.clear()
    # Clearing the returned mapping must not empty the session's cache.
    assert len(session.providers) == 1
