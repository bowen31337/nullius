"""Feature 198's gate: the one-million-token, flat-pricing bar.

app_spec.xml feature 198: *System rejects a depth model without a 1 million
token context at flat pricing, because calls at depth 2 or greater carry a
large history.*  This file drives :func:`providers.require_depth_model` —
the gate — and :class:`providers.DepthModel`, the candidate record it reads.

**The candidates are §14.2's registry, not invented shapes.**  The suite's
admitted names are the depth role's own row — DeepSeek V4.1 Flash (*1M
flat*), ``gemini-3.1-flash-lite`` (*flat at any context, to 1M*),
``claude-haiku-4-5`` (*no long-ctx premium*) — and its refused ones are the
registry's other rows: the self-hosted 262K tier (a short window, flat
pricing) and ``gemini-3.1-pro`` (a 2M window behind a 200K surcharge).  The
point of using the registry's numbers is that the gate is then pinned
against the rate cards the architecture actually surveyed, so a regression
answers *"which real model would we now admit or refuse?"* rather than
*"which synthetic tuple changed meaning?"*.

**The two refusals are the sentence's one property missing in its two
ways.**  *A 1 million token context at flat pricing* is a conjunction, so it
fails as a window (:class:`providers.InsufficientContextError`) or as a
pricing shape (:class:`providers.LongContextSurchargeError`) — and the
window is refused first, which is pinned here as a decision: a model that
physically cannot hold the history fails on physics, and what it would have
cost never becomes relevant.

**The record/gate split is pinned, not incidental.**  A 262K-window
candidate *constructs* — §14.1 lists exactly such a tier for early depth,
narrow campaigns and the bootstrap worlds — and is refused only at the gate,
so a caller naming the model for one of those roles has a record to name it
with.  The boundary with the sibling features is pinned too: the record
carries only the three fields the criterion reads, because feature 199
verifies served limits and feature 200 selects on cache-hit price, and a
field this gate does not read is a field that would drift.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from types import SimpleNamespace

import pytest
from providers import (
    FLAT_AT_ANY_CONTEXT,
    LARGE_HISTORY_FROM_DEPTH,
    MIN_DEPTH_CONTEXT_TOKENS,
    DepthModel,
    DepthModelError,
    InsufficientContextError,
    LongContextSurchargeError,
    flat_pricing,
    require_depth_model,
)

#: §14.2's depth-role primary: "deepseek-flash (V4.1) — $0.30/$1.20 peak,
#: $0.006/M cache hits, 1M flat, MIT weights".  The window is the bar itself
#: and the card has no threshold, which is what "1M flat" means.
DEEPSEEK_FLASH = DepthModel("deepseek-flash", 1_000_000, flat_pricing())

#: §14.2's first alternate: "$0.25/$1.50 flat" — the surcharge table's row
#: "Flat at any context, to 1M, on every tier".
GEMINI_FLASH_LITE = DepthModel("gemini-3.1-flash-lite", 1_000_000)

#: §14.2's second alternate: "$1/$5 no long-ctx premium" — Claude's table
#: row is "1M billed at standard pricing, no premium".
CLAUDE_HAIKU = DepthModel("claude-haiku-4-5", 1_000_000, flat_pricing())

#: §14.2's self-hosted depth tier: "**262K ceiling** confines these to early
#: depth, narrow campaigns, and §10.6 bootstrap worlds".  2**18 is the count
#: that ceiling spells; the test's meaning does not hinge on the last digit,
#: only on its being far under the bar.
ORNITH = DepthModel("ornith-1.5-35b-a3b", 2**18)

#: §14.2's root alternate, refused for the depth role on pricing shape alone:
#: a 2M window (comfortably over the bar) behind the Pro tiers' 200K-input
#: threshold, above which "3.1 Pro $2/$12 → $4/$18" — the whole request
#: reprices.
GEMINI_PRO = DepthModel("gemini-3.1-pro", 2_000_000, 200_000)


def test_the_bar_is_the_one_the_spec_names():
    # The feature's sentence carries two numbers — "1 million token context"
    # and "depth 2 or greater" — and both are the module's data, read by the
    # gate and quoted by every refusal.  If either drifted, the gate and the
    # messages would disagree with the spec while agreeing with each other,
    # which is the quietest way a criterion stops being the one specified.
    assert MIN_DEPTH_CONTEXT_TOKENS == 1_000_000
    assert LARGE_HISTORY_FROM_DEPTH == 2


def test_flat_pricing_is_the_named_none():
    # The flat case is a ``None`` the caller *states* — the
    # hosted_api_weights() precedent — so a rate card read as flat is a rate
    # card somebody decided was flat, not a field that happened to be empty.
    assert FLAT_AT_ANY_CONTEXT is None
    assert flat_pricing() is FLAT_AT_ANY_CONTEXT


@pytest.mark.parametrize(
    "candidate", [DEEPSEEK_FLASH, GEMINI_FLASH_LITE, CLAUDE_HAIKU]
)
def test_the_registrys_depth_picks_clear_the_gate(candidate):
    # The gate's positive case is §14.2's own depth row: every model the
    # architecture selected for the role passes the criterion the selection
    # invoked.  The answer is the candidate (value-equal), and the record is
    # frozen — a rate card is a fact, not a knob.
    admitted = require_depth_model(candidate)
    assert admitted == candidate
    assert isinstance(admitted, DepthModel)
    with pytest.raises(FrozenInstanceError):
        admitted.model = "another-model"  # type: ignore[misc]


def test_a_window_at_the_bar_is_admitted_and_one_token_below_is_refused():
    # "A 1 million token context" means *at least* one million — DeepSeek's
    # 1M-flat window is the bar met exactly — and the token below it is the
    # bar missed by the smallest possible amount.  Pinning both sides of the
    # boundary is what keeps "at least" from quietly becoming "above".
    assert require_depth_model(DepthModel("at-the-bar", MIN_DEPTH_CONTEXT_TOKENS))
    with pytest.raises(InsufficientContextError) as refusal:
        require_depth_model(DepthModel("one-below", MIN_DEPTH_CONTEXT_TOKENS - 1))
    # The refusal quotes the because: the bar, the window it refused, and
    # the depth whose calls carry the history the window cannot hold.
    message = str(refusal.value)
    assert "1,000,000" in message
    assert "999,999" in message
    assert "depth 2 or greater" in message


def test_a_short_window_is_refused_though_its_pricing_is_flat():
    # §14.1's hard criterion, on the registry's own short-window tier: a 262K
    # model with a perfectly flat card is still refused, because "a model
    # with a 256K window physically cannot execute the defining prompt of
    # this system in a mature wide campaign".  The refusal is about the
    # role, and the message says where such a model belongs instead.
    with pytest.raises(InsufficientContextError) as refusal:
        require_depth_model(ORNITH)
    message = str(refusal.value)
    assert "262,144" in message
    assert "bootstrap worlds" in message


def test_the_window_is_refused_before_the_pricing():
    # A candidate short of the bar *and* surcharged under it fails on the
    # window — the exact class, not merely the base — because the ordering
    # is a decision: physics first, economics never reached.  A caller with
    # both lacks is told the one no pricing choice can repair.
    both_lacks = DepthModel("cheap-and-surcharged", 131_072, 100_000)
    with pytest.raises(DepthModelError) as refusal:
        require_depth_model(both_lacks)
    assert type(refusal.value) is InsufficientContextError


def test_a_big_window_behind_a_surcharge_is_refused():
    # The other half of the property: gemini-3.1-pro has twice the required
    # window and is refused anyway, because its whole request reprices above
    # 200K input — under the ~300K average depth call, so the headline rate
    # is not the rate this role pays.  This is §14.2's "criterion nobody
    # prices correctly", refused by name.
    with pytest.raises(LongContextSurchargeError) as refusal:
        require_depth_model(GEMINI_PRO)
    message = str(refusal.value)
    assert "200,000" in message
    assert "reprices" in message
    assert "depth 2 or greater" in message


def test_a_surcharge_at_the_bar_still_prices_the_bar_flat():
    # Repricing starts *above* the threshold, so a threshold at exactly the
    # bar leaves every token of the bar priced flat — admitted — while one
    # token below it puts the bar's last token at the surcharged rate,
    # refused.  The boundary is the same "at least" as the window's.
    assert require_depth_model(
        DepthModel("threshold-at-the-bar", 1_000_000, 1_000_000)
    )
    with pytest.raises(LongContextSurchargeError):
        require_depth_model(DepthModel("threshold-below", 1_000_000, 999_999))


def test_the_flat_case_is_the_default_and_the_stated_case_agrees():
    # The record defaults to flat — most candidates carry no threshold — and
    # the stated spelling passes the same gate with the same value, which is
    # the point of giving the flat case a name rather than a convention.
    default = DepthModel("deepseek-flash", 1_000_000)
    stated = DepthModel("deepseek-flash", 1_000_000, flat_pricing())
    assert default.surcharge_threshold is stated.surcharge_threshold is None
    assert require_depth_model(default) == require_depth_model(stated)
    assert require_depth_model(default) == DEEPSEEK_FLASH


def test_the_two_refusals_answer_to_their_own_base_and_no_other():
    # One base for feature 198's whole vocabulary, and no ancestor shared
    # with the package's other two bases: a model refused before the
    # campaign ran has not been called (not ProviderError) and pins no node
    # (not ModelPinError), and a caller catching either of those must not
    # have a selection question answered in their place.
    from providers import ModelPinError, ProviderError

    assert issubclass(InsufficientContextError, DepthModelError)
    assert issubclass(LongContextSurchargeError, DepthModelError)
    assert not issubclass(DepthModelError, ProviderError)
    assert not issubclass(ProviderError, DepthModelError)
    assert not issubclass(DepthModelError, ModelPinError)
    assert not issubclass(ModelPinError, DepthModelError)
    # Nor the standard library's: the seam's vocabulary is this feature's,
    # the discipline every error module in this package states.
    assert not issubclass(DepthModelError, ValueError)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"model": 3},
        {"model": ""},
        {"model": None},
        {"context_tokens": True},
        {"context_tokens": "1M"},
        {"context_tokens": 1_000_000.0},
        {"context_tokens": 0},
        {"context_tokens": -1},
        {"surcharge_threshold": True},
        {"surcharge_threshold": "272K"},
        {"surcharge_threshold": 0},
        {"surcharge_threshold": -5},
    ],
)
def test_a_malformed_description_is_the_base_refusal_not_a_named_one(kwargs):
    # A bad *description* is not a failed *criterion*: these are refused by
    # the base, exactly (no subclass), on the grounds _pin_errors states for
    # its own trivia — the taxonomy splits by question, and "your int is not
    # an int" has no question beyond the message.  The bool cases are the
    # quiet ones: ``True`` is an int in Python, and a config layer handing
    # one over would otherwise be read as a one-token window.  The records
    # are built inside the ``raises`` because the constructor is where the
    # shape guard lives — a malformed candidate cannot exist to be handed
    # over, and the gate would re-make (and re-refuse) it identically.
    full = {"model": "m", "context_tokens": 1_000_000, "surcharge_threshold": None}
    full.update(kwargs)
    with pytest.raises(DepthModelError) as refusal:
        require_depth_model(DepthModel(**full))
    assert type(refusal.value) is DepthModelError


@pytest.mark.parametrize(
    "part, expected",
    [
        ("model", "name must be a string"),
        ("context_tokens", "context_tokens must be an int"),
        ("surcharge_threshold", "surcharge_threshold must be an int"),
    ],
)
def test_a_malformed_description_names_the_part_that_is_wrong(part, expected):
    # The refusal has to be actionable: "a depth model's context_tokens must
    # be an int" tells a caller which of three fields to fix, and a message
    # that said only "malformed candidate" would leave them bisecting a
    # config file.  The malformed value rides a stub rather than a record —
    # a record this malformed cannot exist — which also pins that the gate's
    # re-make path validates the parts it was handed instead of answering
    # "not a candidate" about a shape it recognised.
    parts = {"model": "m", "context_tokens": 1_000_000, "surcharge_threshold": None}
    parts[part] = object()
    with pytest.raises(DepthModelError) as refusal:
        require_depth_model(SimpleNamespace(**parts))
    assert expected in str(refusal.value)


def test_the_gate_takes_any_record_shaped_candidate_and_answers_one_class():
    # Recognition is by parts, not class: the module loader imports every
    # member twice, so an isinstance gate would refuse the very record a
    # caller built from the member's other copy.  A SimpleNamespace with the
    # three parts is admitted, and the answer is re-made from this module's
    # class — value-equal to the member's own record, and never the object
    # that was offered.
    offered = SimpleNamespace(
        model="deepseek-flash",
        context_tokens=1_000_000,
        surcharge_threshold=flat_pricing(),
    )
    admitted = require_depth_model(offered)
    assert isinstance(admitted, DepthModel)
    assert admitted is not offered
    assert admitted == DEEPSEEK_FLASH
    # And the gate's answer is itself admissible — re-made, not passed
    # through — so a caller can hand the answer straight back.
    again = require_depth_model(admitted)
    assert again == admitted
    assert again is not admitted


def test_a_getattr_hook_cannot_fabricate_a_candidate():
    # The recognition reads ``object.__getattribute__``, which does not fall
    # back to ``__getattr__`` — so an object whose hook answers the three
    # parts is *not* a candidate, and the gate is not a place where a hook
    # can offer a model.  (See require_agent_model_id for the same rule on
    # the pin seam.)

    class Fabricating:
        def __getattr__(self, name: str) -> str:
            if name in ("model", "context_tokens", "surcharge_threshold"):
                return "fabricated"
            raise AttributeError(name)

    with pytest.raises(DepthModelError) as refusal:
        require_depth_model(Fabricating())
    assert "must be a DepthModel" in str(refusal.value)


@pytest.mark.parametrize(
    "value",
    [
        "deepseek-flash",
        "anthropic/claude-opus-5/20260401",
        None,
        42,
        {"model": "m", "context_tokens": 1_000_000},
        ["m", 1_000_000, None],
    ],
)
def test_a_non_candidate_is_refused_rather_than_guessed(value):
    # Not a candidate, on either side of the feature's own family: a bare
    # model string — even a perfectly pinned triple from feature 203 —
    # carries no window and no threshold, and neither does a dict or a list.
    # The gate checks a described rate card; a value carrying no description
    # cannot be checked, and padding the missing fields would be admitting a
    # model nobody described.
    with pytest.raises(DepthModelError) as refusal:
        require_depth_model(value)
    assert "must be a DepthModel" in str(refusal.value)


def test_the_record_carries_only_what_the_criterion_reads():
    # Three fields: the name, the window, the threshold.  Feature 199
    # verifies served limits and feature 200 selects on cache-hit price, and
    # those facts belong to their features' records, added when they are
    # read — a field this gate does not read is a field that drifts, and the
    # surface is pinned here so an addition is a decision the suite notices.
    assert [field.name for field in fields(DepthModel)] == [
        "model",
        "context_tokens",
        "surcharge_threshold",
    ]
