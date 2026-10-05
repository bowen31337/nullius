"""Feature 9's suite: the LLM policy reviser — the sweep's model-driven half.

additions_spec_llm_authoring.xml, "Policy Development Author", feature 9.  This
suite pins the four things the feature's own sentence joins, in the member's own
suite (``packages/dreaming/tests``), collected under this directory's own
conftest for the same-basename-collision reason the rest of the member gives.

The suite is written against the four claims:

* **it is a reviser** — :class:`LLMReviser` matches dreaming's
  :data:`~dreaming.reviser.Reviser` shape, so
  ``revise_policy(incumbent, count, reviser=...)`` works unchanged;
* **the call is the one the feature names** — the policy pin comes from the
  session at ``("policy", campaign_id="policy-development", node_id="revision-N")``,
  and the request carries the incumbent in full, the index, the seed, and the
  config's temperature and ``max_tokens``;
* **the answer is read strictly** — exactly one ```` ```python ```` block, its
  body the revised source, with :class:`ReviserOutputError` (code word
  ``reviser_output``) for zero blocks, several, a blank body, an unterminated
  fence, and an answer identical to the incumbent (naming the revision index);
* **the spend is recorded** — each call appends a
  :class:`providers.AuthoringRecord` with role ``policy`` to
  :attr:`LLMReviser.records`, including a call whose answer is refused.

**No network, no credential, and a fake provider.**  The constraint this
addition states is met here as everywhere: the session is a fake that records
the ``provider_for`` call it received and hands back a provider whose answer the
test scripts, so every claim is about what this module *sends* and what it *does
with an answer* — never about a vendor.  The one place a real session would be
built (a deployment) is exactly the seam a fake replaces.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

# Feature 9 is the one place in this member that reaches a sibling: the provider
# vocabulary (the record, the sampling, require_served) is the providers
# member's, and this suite is the only one here that imports it.  The member's
# conftest puts the app and dreaming roots on ``sys.path``; the providers root is
# added here, beside the import, so this file collects whether the sibling was
# installed in the venv or only sits in the workspace — the same path bootstrap
# the cross-member suite performs for the members it reaches.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_PROVIDERS_SRC = str(_REPO_ROOT / "packages" / "providers" / "src")
if _PROVIDERS_SRC not in sys.path:
    sys.path.insert(0, _PROVIDERS_SRC)

from dreaming.errors import DreamingError
from dreaming.llm_reviser import (
    POLICY_CAMPAIGN_ID,
    REVISER_OUTPUT_CODE,
    LLMReviser,
    ReviserOutputError,
)
from dreaming.reviser import revise_policy
from providers import (
    AuthoringConfig,
    Completion,
    ModelPin,
    Provider,
    ServedModelMismatchError,
    Usage,
)

#: The pin the fake session answers, matching the config's policy pin.  Its
#: ``model`` is the name require_served compares a completion's ``model``
#: against, so the fake provider below serves exactly this.
POLICY_PIN = ModelPin(
    provider="google", model="gemini-3.1-pro", version="20260801"
)

#: The incumbent the tests revise — a small exploration policy with a numeric
#: threshold, so a "revised" answer has an obvious magnitude to move.
INCUMBENT = (
    "def explore(ctx, seed):\n"
    "    threshold = 1.0\n"
    "    return threshold\n"
)


def make_config(**overrides) -> AuthoringConfig:
    """A full authoring config whose policy pin is :data:`POLICY_PIN`."""
    fields = {
        "root_tier": ("google/gemini-3.1-pro/20260801",),
        "depth": "deepseek/deepseek-v4-flash/20260910",
        "policy": "google/gemini-3.1-pro/20260801",
        "temperature": 0.4,
        "max_tokens": 4096,
        "max_input_tokens": 1_000_000,
        "max_output_tokens": 1_000_000,
    }
    fields.update(overrides)
    return AuthoringConfig(**fields)


def fenced(source: str, *, language: str = "python", prose: str = "") -> str:
    """A model answer carrying ``source`` in exactly one fenced block."""
    prefix = f"{prose}\n\n" if prose else ""
    return f"{prefix}```{language}\n{source}\n```\n"


def revised_module(index: int) -> str:
    """A distinct, importable module for revision ``index``.

    Distinct from :data:`INCUMBENT` (whose threshold is ``1.0``) for every
    index, and distinct between indices, so a sweep over it funds as many
    candidates as it asks for and no answer is an echo of the incumbent.
    """
    return (
        "def explore(ctx, seed):\n"
        f"    threshold = {index + 1}.0\n"
        "    return threshold\n"
    )


class FakeProvider(Provider):
    """A provider whose answer is computed from the request, and no transport.

    The fake counts the requests it received so a test can assert what the
    reviser *sent*, and answers whatever ``fn(request)`` returns — so one fake
    can serve a fixed answer (the refusal tests) or one derived from the
    revision index the request carries (the sweep test).
    """

    def __init__(self, fn, *, served_model: str = "gemini-3.1-pro") -> None:
        self._fn = fn
        self._served_model = served_model
        self.requests = []

    def _complete(self, request) -> Completion:
        self.requests.append(request)
        return Completion(
            content=self._fn(request),
            model=self._served_model,
            usage=Usage(input_tokens=11, output_tokens=7),
        )


class FakeSession:
    """The authoring session's routing half, recorded — no providers resolved.

    Answers the ``(provider, pin)`` the reviser asks for and keeps the
    ``provider_for`` arguments, so the routing claim (role, campaign, node) is
    asserted on what the reviser actually asked for rather than on a mock's
    expectation.
    """

    def __init__(self, provider: Provider, pin: ModelPin = POLICY_PIN) -> None:
        self._provider = provider
        self._pin = pin
        self.calls: list[tuple[str, object, object]] = []

    def provider_for(self, role, *, campaign_id, node_id):
        self.calls.append((role, campaign_id, node_id))
        return self._provider, self._pin


def make_reviser(provider: Provider, *, config: AuthoringConfig | None = None):
    session = FakeSession(provider)
    return LLMReviser(session, config=config or make_config()), session, provider


def _index_of(request) -> int:
    """The revision index the request's user message carries."""
    content = request.messages[-1].content
    match = re.search(r"revision index: (\d+)", content)
    assert match is not None
    return int(match.group(1))


# -- it is a reviser: the sweep takes it unchanged ---------------------------


def test_the_reviser_answers_a_revised_source_from_one_block():
    provider = FakeProvider(lambda request: fenced(revised_module(1)))
    reviser, _session, _provider = make_reviser(provider)
    assert reviser(INCUMBENT, 1, 0) == revised_module(1)


def test_the_reading_is_wrap_agnostic_for_the_py_spelling():
    # A recorded fixture may carry ```py where the instruction names ```python;
    # both name one format and both are read.
    provider = FakeProvider(lambda request: fenced(revised_module(2), language="py"))
    reviser, _session, _provider = make_reviser(provider)
    assert reviser(INCUMBENT, 2, 0) == revised_module(2)


def test_revise_policy_works_unchanged_with_the_llm_reviser():
    # The feature's own sentence: `revise_policy(incumbent, count,
    # reviser=LLMReviser(...)) works unchanged`.  Each call answers a module
    # distinct per revision index, so the sweep funds three distinct candidates.
    provider = FakeProvider(
        lambda request: fenced(revised_module(_index_of(request)))
    )
    reviser, _session, _provider = make_reviser(provider)
    candidates = revise_policy(INCUMBENT, 3, reviser=reviser)
    assert len(candidates) == 3
    assert [candidate.revision_index for candidate in candidates] == [1, 2, 3]
    assert all(candidate.parent_version is None for candidate in candidates)
    assert len({candidate.code_hash for candidate in candidates}) == 3


# -- the call: the pin, the campaign, the request ----------------------------


def test_it_takes_the_policy_pin_at_the_revision_node():
    provider = FakeProvider(lambda request: fenced(revised_module(5)))
    reviser, session, _provider = make_reviser(provider)
    reviser(INCUMBENT, 5, 0)
    assert session.calls == [("policy", POLICY_CAMPAIGN_ID, "revision-5")]


def test_the_request_carries_the_incumbent_index_seed_and_knobs():
    provider = FakeProvider(lambda request: fenced(revised_module(3)))
    reviser, _session, _provider = make_reviser(provider)
    reviser(INCUMBENT, 3, "seed-abc")
    request = provider.requests[0]
    # The model is the pin's; the knobs are the config's.
    assert request.model == POLICY_PIN.model
    assert request.temperature == 0.4
    assert request.max_tokens == 4096
    user = request.messages[-1].content
    assert INCUMBENT in user  # the incumbent in full
    assert "revision index: 3" in user
    assert "seed-abc" in user


def test_it_applies_require_served():
    # A vendor quietly serving another model is refused by providers'
    # require_served, before the answer is trusted.
    provider = FakeProvider(
        lambda request: fenced(revised_module(1)),
        served_model="gemini-3.1-pro-preview",
    )
    reviser, _session, _provider = make_reviser(provider)
    with pytest.raises(ServedModelMismatchError):
        reviser(INCUMBENT, 1, 0)


# -- the answer: the refusals ------------------------------------------------


def _refusal(answer: str, *, revision_index: int = 1) -> ReviserOutputError:
    provider = FakeProvider(lambda request: answer)
    reviser, _session, _provider = make_reviser(provider)
    with pytest.raises(ReviserOutputError) as caught:
        reviser(INCUMBENT, revision_index, 0)
    assert REVISER_OUTPUT_CODE in str(caught.value)
    return caught.value


def test_a_zero_block_answer_is_refused():
    _refusal("The revised module is unchanged; no code follows.")


def test_a_several_block_answer_is_refused():
    _refusal(fenced(revised_module(1)) + fenced(revised_module(2)))


def test_a_blank_block_body_is_refused():
    _refusal("```python\n\n```")


def test_an_unterminated_fence_is_refused():
    _refusal("```python\ndef explore(ctx, seed):\n    return 1.0\n")


def test_an_answer_identical_to_the_incumbent_is_refused_naming_the_index():
    refusal = _refusal(fenced(INCUMBENT), revision_index=4)
    assert "4" in str(refusal)


def test_the_refusal_is_a_dreaming_error():
    # A caller catching the member's one base catches this beside a thin pool.
    provider = FakeProvider(lambda request: "no block here")
    reviser, _session, _provider = make_reviser(provider)
    with pytest.raises(DreamingError):
        reviser(INCUMBENT, 1, 0)


# -- the record --------------------------------------------------------------


def test_each_call_appends_a_policy_record():
    provider = FakeProvider(lambda request: fenced(revised_module(2)))
    reviser, _session, _provider = make_reviser(provider)
    assert reviser.records == []
    reviser(INCUMBENT, 2, 7)
    assert len(reviser.records) == 1
    record = reviser.records[0]
    assert record.role == "policy"
    assert record.node_id == "revision-2"
    assert record.campaign_id == POLICY_CAMPAIGN_ID
    assert record.pin == POLICY_PIN
    assert record.served_model == "gemini-3.1-pro"
    assert record.tier is None
    assert record.usage == Usage(input_tokens=11, output_tokens=7)
    assert record.sampling.temperature == 0.4
    assert record.sampling.seed == 7


def test_a_refused_answer_still_records_its_spend():
    # The spend happened; the record is the account of it.
    provider = FakeProvider(lambda request: "no python block at all")
    reviser, _session, _provider = make_reviser(provider)
    with pytest.raises(ReviserOutputError):
        reviser(INCUMBENT, 1, 0)
    assert len(reviser.records) == 1
    assert reviser.records[0].role == "policy"


def test_successive_calls_append_in_order():
    provider = FakeProvider(
        lambda request: fenced(revised_module(_index_of(request)))
    )
    reviser, _session, _provider = make_reviser(provider)
    revise_policy(INCUMBENT, 3, reviser=reviser)
    assert [record.node_id for record in reviser.records] == [
        "revision-1",
        "revision-2",
        "revision-3",
    ]
