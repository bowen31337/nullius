"""Feature 199's gate: the verified served limit against a campaign's history.

app_spec.xml feature 199: *System rejects a depth model whose verified served
context limit is below the campaign history size, rather than trusting a
published figure.*  This file drives :func:`providers.require_served_context`
— the gate — and the two records it reads and answers,
:class:`providers.ServedContextLimit` and
:class:`providers.VerifiedServedContext`.

**The load-bearing test is the first one, and it is about provenance rather
than magnitude.**  §14.1's instruction is *"verify the served context limit
(``--max-model-len``), not the marketing number"*, so a figure that is
comfortably large but was read off a spec sheet must be refused — the number's
*source* is the subject, and a gate that only compared counts would admit it.
:func:`providers.published_figure` is how a caller states that source, and the
two spellings of the refused state are pinned against each other.

**The candidates are §14.2's registry, as they are in ``test_depth.py``.**  The
admitted measurements are the depth row's models (DeepSeek V4.1 Flash, Gemini
3.1 Flash-Lite, Claude Haiku 4.5) verified at their 1M windows; the refused one
is the self-hosted 262K tier, which §14.1 confines to early depth, narrow
campaigns and the bootstrap worlds.  Pinning against the registry's numbers
means a regression answers *"which real model would we now refuse?"* rather
than *"which synthetic tuple changed meaning?"*.

**The bar is the campaign's, and that is what separates this suite from
``test_depth.py``.**  Feature 198's bar is one fixed constant; this feature's
bar is an argument, so the same measurement is admitted for one campaign and
refused for another — pinned here, because a suite that only ever tested one
history size would pass against a gate that had quietly hard-coded one.

**The ordering is pinned as a decision.**  An unverified figure is refused
*before* the counts are compared and independently of them, because an
unverified number cannot be compared at all: a published figure that looks
large enough is not a measurement that cleared the bar, and one that looks too
small is not a measurement that failed it.

**The boundary with feature 198 is pinned too.**  That record carries a
*declared* window and this one a *served* limit, the two are separate types
with no part in common but the model's name, and a :class:`providers.DepthModel`
handed to this gate is turned away for carrying none of the three parts this
measurement is recognised by — the very value the sentence refuses as evidence
cannot be the value that clears the gate.
"""

from __future__ import annotations

import importlib
import pathlib
from dataclasses import FrozenInstanceError, fields
from types import SimpleNamespace

import pytest
from providers import (
    UNVERIFIED_SERVED_LIMIT,
    DepthModel,
    DepthModelError,
    InsufficientContextError,
    LongContextSurchargeError,
    ServedContextBelowHistoryError,
    ServedContextLimit,
    ServedContextUnverifiedError,
    VerifiedServedContext,
    published_figure,
    require_served_context,
)

#: §14.1's sizing facts, as the histories a test declares: ~1k tokens per
#: ``proposal.md`` plus its ``score.json``, *"a 500-node campaign carries
#: roughly 500K tokens of history by the late rounds"*, and §14.2's own
#: measurement of the average depth call at ~300K with late calls beyond 600K.
#: Spelled as data so the tests read like the document they come from.
WIDE_CAMPAIGN_HISTORY = 500_000
NARROW_CAMPAIGN_HISTORY = 120_000

#: §14.2's depth-role primary — *"deepseek-flash (V4.1)"*, 1M flat — verified
#: as served.  ``verified=True`` is the measured state this whole feature
#: exists to require.
DEEPSEEK_FLASH = ServedContextLimit("deepseek-flash", 1_000_000, True)

#: §14.2's two alternates, verified at their 1M windows: Gemini 3.1 Flash-Lite
#: (*"flat at any context, to 1M"*) and Claude Haiku 4.5 (*"no long-ctx
#: premium"*).  All three are §14.1's depth row and all three hold a wide
#: campaign's history.
GEMINI_FLASH_LITE = ServedContextLimit("gemini-3.1-flash-lite", 1_000_000, True)
CLAUDE_HAIKU = ServedContextLimit("claude-haiku-4-5", 1_000_000, True)

#: §14.2's self-hosted depth tier — *"**262K ceiling** confines these to early
#: depth, narrow campaigns, and §10.6 bootstrap worlds"* — **verified** at the
#: window it actually serves.  2**18 is the count that ceiling spells; the
#: test's meaning does not hinge on the last digit, only on its being far under
#: a wide campaign's history and comfortably over a narrow one's.
ORNITH = ServedContextLimit("ornith-1.5-35b-a3b", 2**18, True)

#: The seat's module path, spelled the way the loader spells every seat.  The
#: import is done inside the test rather than at module scope because the seat
#: pulls in the ``app`` package, which this suite — a member suite — can only
#: reach once the repository root is on ``sys.path``.  (The test_pin_component
#: pattern, kept identical so the two component suites reach the seat the same
#: way.)
SEAT = "app.modules.providers"


@pytest.fixture
def app_on_the_path(monkeypatch):
    """Make ``app`` importable, then hand back the seat module.

    The member suite does not depend on the ``app`` package — it must not, or
    the member could not be tested on its own — so the seat is imported here
    with the repository root spliced onto ``sys.path``, and the splice is undone
    afterwards by monkeypatch rather than left behind for later tests.
    """
    root = str(pathlib.Path(__file__).resolve().parents[3])
    monkeypatch.syspath_prepend(root)
    return importlib.import_module(SEAT)


# ── The sentence's core: provenance, not magnitude ────────────────────────────


def test_a_published_figure_is_refused_though_it_is_large_enough():
    # THE TEST THIS FEATURE IS ABOUT.  A one-million-token figure — the same
    # number the admitted measurements carry — is refused because it was read
    # off a spec sheet rather than measured, and the refusal says so by name.
    # A gate that only compared counts would admit this value and would have
    # no way to tell it from a measurement, which is exactly the collapse
    # §14.1's "verify ... not the marketing number" exists to prevent.
    published = ServedContextLimit("ornith-1.5-35b-a3b", 1_000_000, published_figure())
    with pytest.raises(ServedContextUnverifiedError) as refusal:
        require_served_context(published, history_tokens=WIDE_CAMPAIGN_HISTORY)
    message = str(refusal.value)
    # The refusal quotes §14.1's instruction and the mechanism the spec sheet
    # hides, so a caller who read the card learns what to go and read instead.
    assert "--max-model-len" in message
    assert "marketing number" in message
    assert "1,000,000" in message
    # And it names the history it could not be checked against: the campaign's
    # own figure is the bar this number was never measured against.
    assert "500,000" in message


def test_the_published_state_is_a_named_none_like_the_flat_case():
    # The refused state is a *stated* fact, not a flag a caller forgets — the
    # flat_pricing() / hosted_api_weights() discipline, applied where the two
    # states are a boolean apart.  Both spellings pass the same value, and the
    # point of naming it is that the second says "I know this is the card's
    # number" while the first may be a field nobody considered.
    assert UNVERIFIED_SERVED_LIMIT is False
    assert published_figure() is UNVERIFIED_SERVED_LIMIT
    stated = ServedContextLimit("m", 1_000_000, published_figure())
    bare = ServedContextLimit("m", 1_000_000, False)
    assert stated == bare
    assert stated.is_verified is bare.is_verified is False
    # And the other state reads the same way through the same property.
    assert DEEPSEEK_FLASH.is_verified is True


def test_a_published_figure_is_refused_even_when_it_looks_too_small():
    # The second half of the ordering's justification: an unverified figure is
    # refused on provenance *whatever* its magnitude.  A card claiming 262K is
    # not a measurement that failed the bar — it is a number nobody measured,
    # and reporting it as "too small for this campaign" would send its reader
    # to shorten a campaign that may well be fine on the served window.
    card = ServedContextLimit("ornith", 2**18, published_figure())
    with pytest.raises(ServedContextUnverifiedError):
        require_served_context(card, history_tokens=WIDE_CAMPAIGN_HISTORY)


# ── The admitted case: §14.1's depth row holds a wide campaign's history ──────


@pytest.mark.parametrize("measured", [DEEPSEEK_FLASH, GEMINI_FLASH_LITE, CLAUDE_HAIKU])
def test_the_registrys_depth_models_hold_a_wide_campaigns_history(measured):
    # The gate's positive case, on §14.1's own depth row: every model the
    # architecture selected for the role, verified at its served window, holds
    # the history §14.1 measures for a mature wide campaign.  The answer is the
    # pair plus its margin — a record, not the measurement passed through — and
    # it is frozen, because an admission is an observation and not a knob.
    admitted = require_served_context(measured, history_tokens=WIDE_CAMPAIGN_HISTORY)
    assert isinstance(admitted, VerifiedServedContext)
    assert admitted == VerifiedServedContext(
        model=measured.model,
        served_tokens=measured.served_tokens,
        history_tokens=WIDE_CAMPAIGN_HISTORY,
    )
    with pytest.raises(FrozenInstanceError):
        admitted.model = "another-model"  # type: ignore[misc]


def test_the_answer_carries_the_margin_the_docs_reason_in():
    # §14.1 argues in margins — a 1M window against ~600K of late-call history
    # — and the margin is what tells a caller how much further this campaign's
    # history can grow before it outruns the window again.  Derived from the
    # two counts and never stored beside them, exactly as
    # MeasuredCacheRate.hit_rate is: there is one fact and this is its
    # quotient, not a second copy that could disagree.
    admitted = require_served_context(
        DEEPSEEK_FLASH, history_tokens=WIDE_CAMPAIGN_HISTORY
    )
    assert admitted.headroom_tokens == 500_000
    # A caller may also declare §14.2's *late* call rather than the average:
    # 600K of a 1M window leaves 400K, and the gate is the same arithmetic.
    late = require_served_context(DEEPSEEK_FLASH, history_tokens=600_000)
    assert late.headroom_tokens == 400_000


def test_a_measurement_at_the_history_is_admitted_and_one_token_below_is_not():
    # "At least as large as the campaign's history" means *at least* — a window
    # that holds the history exactly holds the whole of it — and the token
    # below it is the bar missed by the smallest possible amount.  The same
    # "at least" boundary feature 198's fixed bar keeps, pinned on both sides
    # so it cannot quietly become "above".
    at_the_history = ServedContextLimit("exact", 500_000, True)
    assert (
        require_served_context(
            at_the_history, history_tokens=WIDE_CAMPAIGN_HISTORY
        ).headroom_tokens
        == 0
    )
    with pytest.raises(ServedContextBelowHistoryError) as refusal:
        require_served_context(
            ServedContextLimit("one-below", 499_999, True),
            history_tokens=WIDE_CAMPAIGN_HISTORY,
        )
    # The refusal quotes both counts and their difference: the gap is the
    # number the repair turns on (shed this much history, or gain this much
    # window), and a message that named only one count would leave its reader
    # subtracting.
    message = str(refusal.value)
    assert "499,999" in message
    assert "500,000" in message
    assert "short by 1 token" in message


def test_the_self_hosted_tier_is_refused_for_a_wide_campaign():
    # §14.1's own clause, on the registry's own short-window tier and with the
    # window *verified* — so this is the feature's second refusal and not its
    # first: "a model with a 256K window physically cannot execute the defining
    # prompt of this system in a mature wide campaign".  The refusal confines
    # rather than condemns, naming where such a model belongs instead.
    with pytest.raises(ServedContextBelowHistoryError) as refusal:
        require_served_context(ORNITH, history_tokens=WIDE_CAMPAIGN_HISTORY)
    message = str(refusal.value)
    assert "262,144" in message
    assert "bootstrap worlds" in message
    # And it says *why* the history is the prompt, so the repair is legible.
    assert "proposal.md" in message


def test_the_very_same_measurement_is_admitted_for_a_narrow_campaign():
    # THE DIFFERENCE FROM FEATURE 198, pinned.  Feature 198's bar is one fixed
    # constant, so a 262K model is refused for the depth role outright.  This
    # feature's bar is *the campaign's own*, which is how §14.1's own
    # resolution reads — the short-window tier is "confined to early-depth
    # nodes, narrow campaigns, and the §10.6 bootstrap worlds", so the same
    # measurement is admissible where the history is short enough to fit it.
    # A suite that only ever declared one history size would pass against a
    # gate that had hard-coded it; this test is what makes the bar an argument
    # rather than a constant.
    admitted = require_served_context(ORNITH, history_tokens=NARROW_CAMPAIGN_HISTORY)
    assert admitted.model == ORNITH.model
    assert admitted.history_tokens == NARROW_CAMPAIGN_HISTORY
    assert admitted.headroom_tokens == 2**18 - NARROW_CAMPAIGN_HISTORY


def test_the_module_bakes_in_no_bar_of_its_own():
    # The module carries no numeric bar: the bar here is the campaign's, and a
    # constant would be an assertion about a campaign this module has never
    # seen (§14.1 reasons *"at ~1k tokens per proposal.md"* and *"roughly 500K
    # tokens"* — estimates, not this feature's operands).  The sharpest
    # contrast with feature 198, whose whole surface is a 1M token bar spelled
    # as data and cited in four refusal messages.
    #
    # Read from the module's own namespace rather than the package __all__,
    # because ownership is the point: the package legitimately exports bars
    # belonging to other features, and this module *quotes* one of them —
    # 198's LARGE_HISTORY_FROM_DEPTH, a depth rather than a token count — in
    # its refusal message.  Quoting another module's constant is not owning a
    # bar.  What must be true of _served is that it declares no token count of
    # its own: every constant it holds is either the named-null boolean or an
    # object that belongs to another module.
    import providers._depth as depth
    import providers._served as served

    baked = {
        name: value
        for name, value in vars(served).items()
        if name.isupper() and not name.startswith("_")
    }
    owned = {
        name: value
        for name, value in baked.items()
        if name != "UNVERIFIED_SERVED_LIMIT"
        and all(value is not other for other in vars(depth).values())
    }
    assert owned == {}, (
        f"the module declares a constant of its own beyond the named-null "
        f"boolean: {sorted(owned)} — a token count here would be a bar about a "
        f"campaign this module has never seen"
    )
    # And the one it does quote is 198's notion of a *depth*, which is why it
    # is a bar this module may reason about without owning: it says which
    # nodes' histories are large, never how large a history is.
    assert served.LARGE_HISTORY_FROM_DEPTH is depth.LARGE_HISTORY_FROM_DEPTH
    assert served.LARGE_HISTORY_FROM_DEPTH < 100
    # Neither record's construction demands a magnitude either: a measurement
    # and a history are valid at any size, and it is only their comparison that
    # is ever refused.
    assert ServedContextLimit("tiny", 1, True).served_tokens == 1
    assert VerifiedServedContext("tiny", 1, 1).headroom_tokens == 0


# ── The ordering: verification before comparison ──────────────────────────────


def test_the_figure_is_refused_before_the_counts_are_compared():
    # A candidate both unverified *and* apparently too small fails on the
    # provenance — the exact class, not merely the base — because the ordering
    # is a decision: you cannot conclude "this deployment's served limit is
    # below the history" from a spec sheet, and that inference is what the
    # sentence forbids.  A caller with both lacks is told the figure was never
    # a measurement, not that a measurement came up short.
    both_lacks = ServedContextLimit("card-only", 2**18, published_figure())
    with pytest.raises(DepthModelError) as refusal:
        require_served_context(both_lacks, history_tokens=WIDE_CAMPAIGN_HISTORY)
    assert type(refusal.value) is ServedContextUnverifiedError
    # The other order — verified but too small — is the second refusal, so the
    # two arms are genuinely distinguished rather than one class wearing both.
    with pytest.raises(ServedContextBelowHistoryError):
        require_served_context(
            ServedContextLimit("card-only", 2**18, True),
            history_tokens=WIDE_CAMPAIGN_HISTORY,
        )


def test_the_history_is_validated_after_the_measurement_is_recognised():
    # A history that is not a positive token count is a malformed *description*
    # — the base refusal, not a named one — on the grounds _depth_errors states
    # for its own trivia.  But a value that is not a measurement at all is
    # turned away first, because there is nothing to hold the history against.
    for malformed in (0, -1, True, "500K", 500_000.0, None):
        with pytest.raises(DepthModelError) as refusal:
            require_served_context(DEEPSEEK_FLASH, history_tokens=malformed)
        assert type(refusal.value) is DepthModelError
        assert "history_tokens must be" in str(refusal.value)


# ── The shape guard: malformed descriptions are the base refusal ──────────────


@pytest.mark.parametrize(
    "kwargs",
    [
        {"model": 3},
        {"model": ""},
        {"model": "   "},
        {"model": None},
        {"served_tokens": True},
        {"served_tokens": "1M"},
        {"served_tokens": 1_000_000.0},
        {"served_tokens": 0},
        {"served_tokens": -1},
        {"verified": 1},
        {"verified": 0},
        {"verified": "yes"},
        {"verified": None},
    ],
)
def test_a_malformed_measurement_is_the_base_refusal_not_a_named_one(kwargs):
    # A bad *description* is not a failed *criterion*: these are refused by the
    # base, exactly (no subclass).  The bool cases are the quiet ones on the
    # count — ``True`` is an int in Python, and a config layer handing one over
    # would otherwise be read as a one-token window — and the ``verified``
    # cases are the quiet ones there: a coerced ``1`` or a truthy string would
    # decide the one question this feature turns on.
    full = {"model": "m", "served_tokens": 1_000_000, "verified": True}
    full.update(kwargs)
    with pytest.raises(DepthModelError) as refusal:
        require_served_context(
            ServedContextLimit(**full), history_tokens=WIDE_CAMPAIGN_HISTORY
        )
    assert type(refusal.value) is DepthModelError


@pytest.mark.parametrize(
    "part, expected",
    [
        ("model", "a served context limit's model must be a string"),
        ("served_tokens", "served_tokens must be an int"),
        ("verified", "a served context limit's verified must be a bool"),
    ],
)
def test_a_malformed_measurement_names_the_part_that_is_wrong(part, expected):
    # The refusal has to be actionable: naming ``served_tokens`` tells a caller
    # which of three fields to fix, and a message that said only "malformed
    # measurement" would leave them bisecting a probe config.  The malformed
    # value rides a stub rather than a record — a record this malformed cannot
    # exist — which also pins that the gate's re-make path validates the parts
    # it was handed rather than answering "not a measurement" about a shape it
    # recognised.
    parts = {"model": "m", "served_tokens": 1_000_000, "verified": True}
    parts[part] = object()
    with pytest.raises(DepthModelError) as refusal:
        require_served_context(
            SimpleNamespace(**parts), history_tokens=WIDE_CAMPAIGN_HISTORY
        )
    assert expected in str(refusal.value)
    # ...and the field is named even when the value is not printable-friendly:
    # the malformed object rides in the message, so the reader sees what they
    # handed over rather than only its type.
    assert repr(parts[part]) in str(refusal.value)


def test_a_blank_name_and_a_non_string_name_get_different_messages():
    # Two failures, two repairs: an empty name is a string that says nothing,
    # a non-string is not a name at all.  A single "bad model" message would
    # send a caller whose config has a trailing comma looking in the wrong
    # place, and the blank case is the quiet one — an unset environment
    # variable arrives as "" and is otherwise perfectly well-typed.
    with pytest.raises(DepthModelError) as blank:
        ServedContextLimit("", 1_000_000, True)
    assert "non-empty string" in str(blank.value)
    with pytest.raises(DepthModelError) as not_a_string:
        ServedContextLimit(3, 1_000_000, True)
    assert "must be a string" in str(not_a_string.value)
    assert "non-empty" not in str(not_a_string.value)


def test_the_model_name_is_canonicalized_but_not_judged():
    # The name is stripped, the way feature 201 canonicalizes a provider lookup
    # key and for the same reason: a name carried with a config file's stray
    # spaces is one name, not two.  Anything non-blank is kept — this gate
    # judges a window, not a naming convention.
    assert ServedContextLimit("  deepseek-flash  ", 1_000_000, True).model == (
        "deepseek-flash"
    )
    assert ServedContextLimit("local/ornith:fp8", 1_000_000, True).model == (
        "local/ornith:fp8"
    )


def test_verified_has_no_default():
    # The published figure must not be admissible by omission: a field that
    # defaulted to True would let a caller who read a spec sheet and never
    # probed anything pass the gate by saying nothing, which is the §14.1 trap
    # arriving through a constructor signature.  Pinned structurally, so the
    # default cannot be added back without this test noticing.
    parameters = {field.name for field in fields(ServedContextLimit)}
    assert parameters == {"model", "served_tokens", "verified"}
    with pytest.raises(TypeError):
        ServedContextLimit("m", 1_000_000)  # type: ignore[call-arg]


# ── Recognition by parts, not class ───────────────────────────────────────────


def test_the_gate_takes_any_record_shaped_measurement_and_answers_one_class():
    # Recognition is by parts, not class: the module loader imports every
    # member twice, so an isinstance gate would refuse the very record a caller
    # built from the member's other copy.  A SimpleNamespace with the three
    # parts is admitted, and the answer is re-made from this module's class —
    # value-equal to the member's own record, and never the object offered.
    offered = SimpleNamespace(
        model="deepseek-flash", served_tokens=1_000_000, verified=True
    )
    admitted = require_served_context(offered, history_tokens=WIDE_CAMPAIGN_HISTORY)
    assert isinstance(admitted, VerifiedServedContext)
    assert admitted is not offered
    assert admitted == require_served_context(
        DEEPSEEK_FLASH, history_tokens=WIDE_CAMPAIGN_HISTORY
    )


def test_the_gate_recognises_the_other_imports_twin():
    # **The deployment case, driven rather than described.**  The loader
    # imports every member twice — once as ``_nullius_scanned_providers`` by
    # file path, once as ``providers`` — so ``ServedContextLimit`` exists as
    # two class objects over one source file, and a dataclass's generated
    # ``__eq__`` answers ``False`` between them for every value.  A gate that
    # recognised a measurement with ``isinstance`` would therefore refuse the
    # very record a caller legitimately built from the member's other copy.
    #
    # A suite that only ever builds measurements from the module it imported
    # cannot see this, which is why the measurement below comes from the
    # scanned copy.  The scan runs here rather than being relied on from
    # another test module, so this test stands alone whatever order the suite
    # is collected in; the registry is fresh so it does not disturb the
    # components the other tests read.  (The test_pin_store.py pattern.)
    from app.module_loader import Registration, scan_components

    scan_components(registry=Registration())
    scanned = importlib.import_module("_nullius_scanned_providers")
    assert scanned.ServedContextLimit is not ServedContextLimit, (
        "the two copies are one class, so this test no longer exercises a "
        "second class object and the loader's double import is what changed"
    )
    offered = scanned.ServedContextLimit("deepseek-flash", 1_000_000, True)
    # The trap, asserted directly: the caller's measurement and this module's
    # are the same three values and are *not* equal.
    assert offered != DEEPSEEK_FLASH
    # The answer carries this module's class, so the equality a caller writes
    # downstream holds — and the same scanned measurement re-gates idempotently
    # rather than being refused on a second pass.
    admitted = require_served_context(offered, history_tokens=WIDE_CAMPAIGN_HISTORY)
    assert type(admitted) is VerifiedServedContext
    assert admitted == require_served_context(
        DEEPSEEK_FLASH, history_tokens=WIDE_CAMPAIGN_HISTORY
    )
    # ...and the refusals fire on a scanned record too: recognition is by
    # parts, so the *second* refusal is not silently lost to the double import.
    with pytest.raises(ServedContextBelowHistoryError):
        require_served_context(
            scanned.ServedContextLimit("ornith", 2**18, True),
            history_tokens=WIDE_CAMPAIGN_HISTORY,
        )


def test_a_getattr_hook_cannot_fabricate_a_measurement():
    # The recognition reads ``object.__getattribute__``, which does not fall
    # back to ``__getattr__`` — so an object whose hook answers the three parts
    # is *not* a measurement, and the gate is not a place where a hook can
    # offer a probe result.  (See require_depth_model for the same rule on
    # feature 198's seam.)

    class Fabricating:
        def __getattr__(self, name: str) -> str:
            if name in ("model", "served_tokens", "verified"):
                return "fabricated"
            raise AttributeError(name)

    with pytest.raises(DepthModelError) as refusal:
        require_served_context(Fabricating(), history_tokens=WIDE_CAMPAIGN_HISTORY)
    assert "must be a ServedContextLimit" in str(refusal.value)


@pytest.mark.parametrize(
    "value",
    [
        "deepseek-flash",
        "anthropic/claude-opus-5/20260401",
        None,
        42,
        {"model": "m", "served_tokens": 1_000_000, "verified": True},
        ["m", 1_000_000, True],
        (1_000_000, True),
    ],
)
def test_a_non_measurement_is_refused_rather_than_guessed(value):
    # Not a measurement, on either side of the feature's own family: a bare
    # model string — even a perfectly pinned triple from feature 203 — carries
    # no measured window and no provenance, and neither does a dict or a list.
    # The gate checks a measurement; a value carrying none cannot be checked,
    # and padding the missing parts would be admitting a model nobody measured.
    with pytest.raises(DepthModelError) as refusal:
        require_served_context(value, history_tokens=WIDE_CAMPAIGN_HISTORY)
    assert "must be a ServedContextLimit" in str(refusal.value)


def test_a_published_candidate_record_is_not_a_measurement():
    # THE BOUNDARY WITH FEATURE 198, and the sharpest case of the rule above.
    # A DepthModel carries a *declared* window — the published figure — and no
    # served limit and no provenance: it is the very value §14.1's sentence
    # refuses as evidence, so it must not be readable as the measurement that
    # clears the gate.  It is turned away for carrying none of the three parts,
    # and its 1M context_tokens is not quietly read as a served window.
    with pytest.raises(DepthModelError) as refusal:
        require_served_context(
            DepthModel("deepseek-flash", 1_000_000), history_tokens=1
        )
    assert "must be a ServedContextLimit" in str(refusal.value)
    # And the two records share no part but the model's name: neither can be
    # swapped for the other at any call site.
    assert {f.name for f in fields(DepthModel)} & {
        f.name for f in fields(ServedContextLimit)
    } == {"model"}


# ── The answer record ─────────────────────────────────────────────────────────


def test_the_answer_carries_only_what_it_answers_with():
    # Three fields: the model, the verified limit, the declared history — and
    # the margin derived from the last two rather than stored beside them.  The
    # surface is pinned here so an addition is a decision the suite notices,
    # and headroom is deliberately absent from it: a stored margin is a second
    # copy of a fact the two counts already carry.
    assert [field.name for field in fields(VerifiedServedContext)] == [
        "model",
        "served_tokens",
        "history_tokens",
    ]
    assert "headroom_tokens" not in {
        field.name for field in fields(VerifiedServedContext)
    }
    admitted = require_served_context(
        DEEPSEEK_FLASH, history_tokens=WIDE_CAMPAIGN_HISTORY
    )
    assert isinstance(type(admitted).headroom_tokens, property), (
        "headroom must be derived, never a stored field"
    )


def test_two_admissions_of_one_pair_are_equal():
    # Value-equal, so a suite computes an admission and compares it to the one
    # a caller holds without sharing an object — the testability every record
    # in this package gets from being a value type.
    assert require_served_context(
        DEEPSEEK_FLASH, history_tokens=WIDE_CAMPAIGN_HISTORY
    ) == require_served_context(DEEPSEEK_FLASH, history_tokens=WIDE_CAMPAIGN_HISTORY)


def test_a_hand_built_admission_cannot_smuggle_a_refused_pair():
    # The record validates its own arithmetic, so a hand-built one cannot carry
    # past a reader a pair the gate would have refused — the discipline
    # MeasuredCacheRate keeps for its own two counts.  Without this, the
    # type's existence would be the only thing saying "this held the history",
    # and a fabricated record would launder a refusal into an admission.
    with pytest.raises(DepthModelError) as refusal:
        VerifiedServedContext(
            model="ornith",
            served_tokens=2**18,
            history_tokens=WIDE_CAMPAIGN_HISTORY,
        )
    assert type(refusal.value) is DepthModelError
    assert "below the" in str(refusal.value)


def test_the_admission_is_frozen_and_value_equal():
    admitted = require_served_context(
        DEEPSEEK_FLASH, history_tokens=WIDE_CAMPAIGN_HISTORY
    )
    with pytest.raises(FrozenInstanceError):
        admitted.served_tokens = 1  # type: ignore[misc]
    assert admitted == VerifiedServedContext(
        model="deepseek-flash",
        served_tokens=1_000_000,
        history_tokens=WIDE_CAMPAIGN_HISTORY,
    )


# ── The taxonomy ──────────────────────────────────────────────────────────────


def test_the_two_refusals_join_feature_198s_base_and_no_other():
    # One base for the role's whole vocabulary — 198's two refusals and 199's
    # two — because they ask one question of one axis.  Neither new class is
    # reachable through the package's other bases: a served limit nobody
    # measured is not a call that failed, not a node that cannot be pinned, not
    # a price on the wrong axis, and not a window that was missed.
    from providers import (
        BatchRoutingError,
        DepthCacheError,
        DepthScheduleError,
        ModelPinError,
        ProviderError,
    )

    assert issubclass(ServedContextUnverifiedError, DepthModelError)
    assert issubclass(ServedContextBelowHistoryError, DepthModelError)
    for other in (
        ProviderError,
        ModelPinError,
        DepthScheduleError,
        BatchRoutingError,
        DepthCacheError,
    ):
        assert not issubclass(DepthModelError, other)
        assert not issubclass(other, DepthModelError)
    # Nor the standard library's: the seam's vocabulary is this feature's, the
    # discipline every error module in this package states.
    assert not issubclass(DepthModelError, ValueError)


def test_the_error_surface_is_exactly_the_four_refusals():
    # A new refusal class has to be added to the taxonomy — which is a
    # *decision* about whether it belongs under DepthModelError or should be a
    # bare base — rather than arriving undocumented.  Compared against the
    # member's own __all__, so this fails on a class being exported and
    # forgotten, which is how a taxonomy drifts.  (The test_pin_errors.py
    # pattern, applied to this base.)
    import providers

    subtree = {
        name
        for name in providers.__all__
        if isinstance(getattr(providers, name, None), type)
        and issubclass(getattr(providers, name), DepthModelError)
        and name != "DepthModelError"
    }
    assert subtree == {
        "InsufficientContextError",
        "LongContextSurchargeError",
        "ServedContextBelowHistoryError",
        "ServedContextUnverifiedError",
    }
    assert DepthModelError.__subclasses__() == [
        InsufficientContextError,
        LongContextSurchargeError,
        ServedContextUnverifiedError,
        ServedContextBelowHistoryError,
    ]


@pytest.mark.parametrize(
    "error",
    [
        ServedContextUnverifiedError,
        ServedContextBelowHistoryError,
    ],
)
def test_each_refusal_is_raised_with_a_sentence(error):
    # Every one of these is raised with a message that says what is wrong and
    # quotes the architecture, so an operator reading a campaign log learns
    # what to go and change rather than which line raised.
    assert issubclass(error, DepthModelError)
    assert error.__doc__, f"{error.__name__} carries no docstring"
    assert len(error.__doc__) > 200, f"{error.__name__}'s is a stub"


# ── The exports and the absence of a component ────────────────────────────────


def test_the_records_and_the_gate_are_importable_directly():
    # The sibling features of this category build on this seam by importing it
    # directly — there is one way to name the verification.
    import providers

    for name in (
        "ServedContextLimit",
        "VerifiedServedContext",
        "ServedContextUnverifiedError",
        "ServedContextBelowHistoryError",
        "UNVERIFIED_SERVED_LIMIT",
        "published_figure",
        "require_served_context",
    ):
        assert hasattr(providers, name)
        assert name in providers.__all__


def test_the_member_registers_no_component_for_this_feature():
    # Verification is a pure criterion: it persists nothing, owns no table,
    # resolves no DATABASE_URL and places no call — the stance feature 201
    # states for its own routing, and the reason 199 is imported directly
    # rather than seated.  A component here would be a deployment-bound fact
    # for a question that is asked with both facts in hand.
    import providers

    from app.module_loader import registered_components

    names = [c.name for c in registered_components()]
    # The member's four registrations, unchanged by this feature.
    assert "providers" in names
    assert "agent-model-pins" in names
    assert "depth-run-windows" in names
    assert "depth-cache-rates" in names
    assert not any("served" in name for name in names)
    # And the store this feature does not have is not half-spelled anywhere.
    assert not hasattr(providers, "SERVED_CONTEXT_TABLE")
    assert not hasattr(providers, "build_served_context")


def test_the_seat_answers_only_its_three_services_still(app_on_the_path):
    # The seat (app.modules.providers) exposes the three composed stores and
    # deliberately not this feature's records: a seat that re-exported a
    # criterion would be a second spelling of the member's surface, and it
    # would invite a caller to reach a contract by way of the application.
    # Feature 199 is absent from it, and the seat's surface is unchanged.
    #
    # The seat is reached through the same fixture the sibling component suites
    # use, which splices the repository root onto sys.path for the duration of
    # the test only.  The member suite must not depend on ``app`` — the member
    # has to be testable on its own — so the splice is undone rather than left
    # behind for every later test in the process.
    assert set(app_on_the_path.__all__) == {
        "COMPONENT_NAME",
        "DEPTH_CACHE_RATES_NAME",
        "DEPTH_RUN_WINDOWS_NAME",
        "agent_model_pins_component",
        "depth_cache_rates_component",
        "depth_run_windows_component",
    }
    assert not hasattr(app_on_the_path, "served_context_component")
