"""Feature 204's dice: the four sampling settings, and every way a value fails.

app_spec.xml feature 204: *System persists ``agent_ckpt_hash`` for self-hosted
weights plus ``agent_sampling`` recording temperature, top_p, thinking and
seed.*  This file holds the half of that sentence that is about the *value* —
what a sampling record is, how it renders into the one JSON document the
``node`` column can hold, and what it refuses — and leaves the half that is
about the *row* to ``test_weights_store.py``.  ``test_ckpt.py`` takes the other
value type, the checkpoint hash.  The split is the one this member's suites
already take: ``test_pinning.py`` is 203's value and ``test_pin_store.py`` its
row.

**The refusal that carries the feature is the partial document.**  A column that
is a JSON object could hold ``{"temperature": 0.7}`` and a reader could fill the
other three from what the code happens to default to — and that reader would be
reporting a *draw* that nobody recorded, on a row whose score is reproducible
only by the settings the original run actually used.  0115's comment says why
that matters in the requirement's own words: *a replay that re-issues the
authoring call without these four cannot reproduce the node, and determinism
under replay is the property §14 demands of every recorded decision*.  So the
tests below that assert a partial record is refused are not testing a parser's
strictness; they are testing that this member will not invent three quarters of
a draw, and the ones that matter most are named after that.

The settings are the four the sentence names, in the sentence's order, and the
order is worth keeping in the tests rather than sorting: a reader checking the
feature text against the suite should find ``temperature, top_p, thinking,
seed`` in both.
"""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest
from providers import (
    DEFAULT_SAMPLING,
    MAX_TEMPERATURE,
    SAMPLING_KEYS,
    SEED_MAX,
    AgentSampling,
    AgentSamplingMalformedError,
    ModelPinError,
    require_agent_sampling,
)
from providers._sampling import EFFORT_LEVELS

#: The four settings in the feature sentence's order, and the test that pins
#: this tuple against the sentence is below.  Spelled as a tuple in the test
#: module rather than read from the member, so that a change to
#: :data:`~providers.SAMPLING_KEYS` is a failing test about the *feature text*
#: rather than a suite that follows the code wherever it goes.
SENTENCE_KEYS = ("temperature", "top_p", "thinking", "seed")


# ── The four settings, as a value ─────────────────────────────────────────────


def test_the_recorded_settings_are_the_four_the_sentence_names():
    # The assertion that fails if the feature is ever widened or narrowed
    # without the suite noticing: app_spec.xml names exactly these four, and a
    # fifth setting is a change to what a replay has to re-issue.
    assert SAMPLING_KEYS == SENTENCE_KEYS


def test_the_module_defaults_are_the_settings_a_deployment_that_turns_no_knobs_records():
    # DEFAULT_SAMPLING is what a caller gets from AgentSampling() and what the
    # suite's planted rows carry, so the two must be one spelling.  Greedy
    # decoding with thinking off is the honest default: it is what a deployment
    # that configured nothing actually did, and recording a guess in its place
    # would make every node look reproducible by settings nobody used.
    assert DEFAULT_SAMPLING == {
        "temperature": 0.0,
        "top_p": 1.0,
        "thinking": False,
        "seed": 0,
    }


def test_a_sampling_renders_as_the_canonical_json_document_the_column_stores():
    # The stored form is one text document, and it is the canonical JSON the
    # rest of this codebase renders identity with — `sort_keys`, no spaces,
    # allow_nan=False — spelled by cost_model.identity.canonical_cost_model and
    # artifacts._execution._render_trace.  Keys sorted so that two equal
    # records are one string: the column is compared as text by the store's
    # conflict refusal, and a hash of that text is what a replay check would
    # compare.
    sampling = AgentSampling()
    assert sampling.to_json() == (
        '{"seed":0,"temperature":0.0,"thinking":false,"top_p":1.0}'
    )
    assert sampling.agent_sampling == sampling.to_json()
    assert str(sampling) == sampling.to_json()


def test_a_sampling_is_hashable_and_frozen():
    # Frozen because a record of a draw is history: the store holds settings and
    # a caller holding one must not be able to edit the row's meaning in place.
    # Hashable because the store's idempotence check compares two records, and a
    # value type that could not be a dict key or a set member would push callers
    # back to comparing rendered text.
    sampling = AgentSampling(temperature=0.7)
    with pytest.raises(FrozenInstanceError):
        sampling.temperature = 0.9  # type: ignore[misc]
    assert {sampling, AgentSampling(temperature=0.7)} == {sampling}


def test_a_sampling_compares_by_its_four_settings(make_sampling):
    # Value equality is what makes the store's "already recorded, and equal"
    # answer a comparison of *draws* rather than of objects, so a retry
    # carrying a freshly built record is answered as a retry.
    assert make_sampling(temperature=0.7) == make_sampling(temperature=0.7)
    assert make_sampling(temperature=0.7) != make_sampling(temperature=0.8)


@pytest.mark.parametrize(
    "moved",
    [
        {"temperature": 0.5},
        {"top_p": 0.5},
        {"thinking": True},
        {"seed": 7},
    ],
)
def test_every_one_of_the_four_is_part_of_the_identity(make_sampling, moved):
    # Each setting is asserted on its own, because the failure this catches is
    # a comparison that was written against three of the four — the record then
    # answers *already recorded, and equal* for a genuinely different draw, and
    # the row's score becomes reproducible only by settings it does not hold.
    assert make_sampling(**moved) != make_sampling()


def test_a_sampling_round_trips_through_the_document_that_stores_it(make_sampling):
    # to_json is the column's spelling and parse is the read side, so the two
    # are inverses: a record read back from the column is the record that was
    # written.  This is the property the store's reads rest on.
    written = make_sampling(temperature=1.25, top_p=0.3, thinking=True, seed=SEED_MAX)
    assert AgentSampling.parse(written.to_json()) == written
    assert AgentSampling.parse(written.to_dict()) == written
    # A record with thinking on is a different *document*, not a prettier one —
    # the flag is part of what a replay has to re-issue.
    assert json.loads(written.to_json())["thinking"] is True


def test_to_dict_always_names_all_four_settings(make_sampling):
    # The document is never partial, whatever the constructor was given: the
    # constructor has Python keyword defaults, a *document* has no defaults.
    # A caller that wants to record a draw reads all four here.
    assert tuple(sorted(make_sampling().to_dict())) == tuple(sorted(SENTENCE_KEYS))


# ── What a sampling refuses ───────────────────────────────────────────────────


def test_a_partial_record_is_refused_rather_than_completed(make_sampling):
    # **The refusal this feature is about.**  A document naming some of the four
    # is not a shorter record of a draw, it is a record of a different one: the
    # caller that filled the gaps would be asserting settings the authoring run
    # never used, on a score that is reproducible only by the ones it did.
    with pytest.raises(AgentSamplingMalformedError) as refusal:
        require_agent_sampling({"temperature": 0.7})
    message = str(refusal.value)
    # It names what is missing *and* the values that would record it, because a
    # refusal that only said "incomplete" would leave the caller to guess
    # whether the gap was theirs or the schema's.
    for key in ("top_p", "thinking", "seed"):
        assert key in message


def test_a_record_with_a_setting_this_feature_does_not_have_is_refused():
    # PRD §5a's stratification reads *the same draw* as meaning the same four
    # settings.  A fifth name is either a newer feature's column arriving early
    # or a misspelling, and neither is a draw this member can claim to have
    # recorded — so it is refused rather than dropped, since dropping it would
    # silently narrow the record to settings that are not the whole draw.
    with pytest.raises(AgentSamplingMalformedError) as refusal:
        require_agent_sampling(
            {"temperature": 0.0, "top_p": 1.0, "thinking": False, "seed": 0,
             "repetition_penalty": 1.1}
        )
    assert "repetition_penalty" in str(refusal.value)


@pytest.mark.parametrize(
    "temperature",
    [-0.1, MAX_TEMPERATURE + 0.1, 3, float("inf"), float("nan"), "0.7"],
)
def test_a_temperature_outside_zero_to_two_is_refused(temperature):
    # The band every provider in §14.1's tables accepts; a value outside it is
    # not a draw any of them could have made, so recording it would describe a
    # run that cannot have happened.  NaN and the strings are refused for the
    # sharper reason: NaN is not a number the column can round-trip
    # (allow_nan=False), and "0.7" is text that *looks* like the setting.
    # ``None`` is deliberately not in this list — see
    # test_a_null_temperature_means_not_sent below. It used to be refused here,
    # which was the defect this module's no-sampling extension fixes: a model
    # that rejects temperature outright has no number to record, honest or
    # otherwise, and null was the only spelling left unclaimed for that.
    with pytest.raises(AgentSamplingMalformedError):
        AgentSampling(temperature=temperature)


def test_the_ends_of_the_temperature_band_are_both_accepted():
    # Greedy decoding and the top of the documented band are both real draws.
    # The lower end is the default, so the boundary that matters is the upper.
    assert AgentSampling(temperature=0.0).temperature == 0.0
    assert AgentSampling(temperature=MAX_TEMPERATURE).temperature == MAX_TEMPERATURE


def test_a_null_temperature_means_not_sent(make_sampling):
    # The no-sampling extension's reading: a model that rejects temperature
    # outright (claude-opus-5-5, claude-sonnet-5-5) was sent none, and null is
    # the honest record of that — not a coercion to 0.0, which would claim the
    # vendor received a temperature it never did.
    record = AgentSampling(temperature=None)
    assert record.temperature is None
    assert AgentSampling.parse(record.to_json()).temperature is None
    # And it is still part of the identity: a null temperature is a different
    # draw from any number, the same way every other setting is.
    assert make_sampling(temperature=None) != make_sampling(temperature=0.0)


@pytest.mark.parametrize("top_p", [0.0, -0.1, 1.5, float("nan"), "0.9"])
def test_a_top_p_outside_the_unit_interval_is_refused(top_p):
    # Exclusive at zero: top_p=0 is not "take nothing", it is a division the
    # sampler cannot perform, and a record claiming it would describe a draw no
    # implementation makes.
    # ``None`` is deliberately not in this list — see
    # test_a_null_top_p_means_not_sent below; it used to be refused here, which
    # was the same defect the temperature list's comment explains.
    with pytest.raises(AgentSamplingMalformedError):
        AgentSampling(top_p=top_p)


def test_the_top_of_the_top_p_interval_is_accepted():
    # 1.0 is the default and means *no nucleus filtering* — a real, recorded
    # choice rather than an unset field.
    assert AgentSampling(top_p=1.0).top_p == 1.0


def test_a_null_top_p_means_not_sent():
    # Same reading as temperature: null is "not sent", not "take nothing" —
    # the latter is what top_p=0 would mean, and that is still refused above.
    record = AgentSampling(top_p=None)
    assert record.top_p is None
    assert AgentSampling.parse(record.to_json()).top_p is None


@pytest.mark.parametrize("thinking", [1, 0, "true", "yes", 1.0, None])
def test_a_thinking_that_is_not_a_boolean_is_refused(thinking):
    # **The trap this test exists for:** ``bool`` is a subclass of ``int`` in
    # Python, so a check written as "is this an int" accepts 1 and 0 and the
    # record then round-trips as ``true``/``false`` — a *different* draw
    # reported under the same name.  The refusal has to be on the type, not on
    # the truthiness, which is why the check runs before the numeric ones.
    # ``None`` stays refused here even after the no-sampling extension: unlike
    # temperature and top_p, thinking's "I wasn't asked to turn this knob"
    # spelling is the string "adaptive" below, not null.
    with pytest.raises(AgentSamplingMalformedError):
        AgentSampling(thinking=thinking)


def test_both_booleans_are_accepted_and_survive_the_round_trip():
    # Extended thinking changes what a replay has to re-issue — a node authored
    # with it on is not reproducible by the same temperature alone.
    for value in (True, False):
        record = AgentSampling(thinking=value)
        assert record.thinking is value
        assert AgentSampling.parse(record.to_json()).thinking is value


def test_thinking_adaptive_is_accepted_and_survives_the_round_trip():
    # claude-opus-5-5 and claude-sonnet-5-5's reasoning is not a flag the
    # caller turns on or off — it is adaptive, and "adaptive" is the third,
    # closed spelling the no-sampling extension adds for exactly that model
    # family. It is a different draw from both booleans, not a synonym for
    # either.
    record = AgentSampling(thinking="adaptive")
    assert record.thinking == "adaptive"
    assert AgentSampling.parse(record.to_json()).thinking == "adaptive"
    assert record != AgentSampling(thinking=True)
    assert record != AgentSampling(thinking=False)


@pytest.mark.parametrize("thinking", ["Adaptive", "ADAPTIVE", " adaptive", "adaptiv"])
def test_a_near_miss_spelling_of_adaptive_is_refused(thinking):
    # Exact spelling only, the same no-coercion rule every other setting in
    # this module follows — a near miss is a caller's typo, not a model whose
    # thinking this record can describe.
    with pytest.raises(AgentSamplingMalformedError):
        AgentSampling(thinking=thinking)


@pytest.mark.parametrize(
    "seed", [-1, SEED_MAX + 1, 2**64, 1.5, "7", None, True, False]
)
def test_a_seed_that_is_not_a_non_negative_integer_is_refused(seed):
    # ``None`` is refused rather than read as "no seed", because a record with
    # no seed is exactly the record that cannot be replayed — the same ground
    # sandbox.seed.resolve_seed refuses on, and it too refuses ``True``, for the
    # bool-is-an-int reason above rather than for its value.
    with pytest.raises(AgentSamplingMalformedError):
        AgentSampling(seed=seed)


def test_the_seed_band_is_the_signed_64_bit_range():
    # The bound is sandbox.seed.SEED_MAX's, the range every provider's seed
    # parameter accepts; a value above it would be truncated by the sampler and
    # the row would then record a seed that produced nothing.
    assert SEED_MAX == 2**63 - 1
    assert AgentSampling(seed=0).seed == 0
    assert AgentSampling(seed=SEED_MAX).seed == SEED_MAX


# ── effort: the one optional key ──────────────────────────────────────────────


def test_effort_is_absent_by_default_and_omitted_from_the_document():
    # effort is the record's one optional key: a draw that sent none of it
    # renders to the same four-key document every deployment already writes —
    # the property that makes this extension backward compatible.
    record = AgentSampling()
    assert record.effort is None
    assert "effort" not in record.to_dict()
    assert "effort" not in record.to_json()


@pytest.mark.parametrize("effort", sorted(EFFORT_LEVELS))
def test_each_effort_level_is_accepted_and_survives_the_round_trip(effort):
    # claude-opus-5-5 and claude-sonnet-5-5 read output_config.effort in place
    # of temperature and top_p; each of the five levels is a real draw and has
    # to come back out of the stored document as the same draw.
    record = AgentSampling(
        temperature=None, top_p=None, thinking="adaptive", seed=0, effort=effort
    )
    assert record.effort == effort
    assert AgentSampling.parse(record.to_json()).effort == effort
    assert json.loads(record.to_json())["effort"] == effort


@pytest.mark.parametrize("effort", ["LOW", "extreme", "", 1, 1.0, True])
def test_an_unknown_effort_is_refused(effort):
    # Not one of the five levels _anthropic.py's own EFFORT_LEVELS sends on
    # the wire, so it is a spelling no backend reads — refused by the same
    # no-coercion rule every other setting in this module follows.
    with pytest.raises(AgentSamplingMalformedError):
        AgentSampling(effort=effort)


def test_an_extra_unknown_key_alongside_a_valid_effort_is_still_refused():
    # effort being legal now does not open the record up generally: a sixth
    # key this feature has no name for is refused exactly as it was before the
    # extension, whether or not the document also carries a valid effort.
    with pytest.raises(AgentSamplingMalformedError) as refusal:
        require_agent_sampling(
            {
                "temperature": None,
                "top_p": None,
                "thinking": "adaptive",
                "seed": 0,
                "effort": "high",
                "top_k": 40,
            }
        )
    assert "top_k" in str(refusal.value)


def test_a_record_predating_the_no_sampling_extension_round_trips_byte_identical():
    # The compatibility promise this extension makes in both directions: a
    # document written before effort, null temperature/top_p and adaptive
    # thinking existed parses unchanged and renders back to the identical
    # bytes — no key appears, moves, or changes shape just because the record
    # contract grew.
    stored = '{"seed":42,"temperature":0.7,"thinking":true,"top_p":0.9}'
    assert AgentSampling.parse(stored).to_json() == stored


@pytest.mark.parametrize(
    "document", [None, "", "  ", 0.7, [], ["temperature"], "{'temperature': 0.7}", True]
)
def test_a_document_that_is_not_a_json_object_is_refused(document):
    # A NULL is refused here too, and that is the *parser's* line rather than
    # the store's: the column's null is a state the store answers (see
    # test_weights_store.py), but a value that is not the four settings is not a
    # draw and this function will not invent one.
    with pytest.raises(AgentSamplingMalformedError):
        require_agent_sampling(document)


def test_a_refusal_is_a_model_pin_error_and_not_only_this_class():
    # Feature 204's errors join feature 203's base rather than minting a second
    # one: a caller that already handles "this member refused" keeps working,
    # and the taxonomy stays one tree.  See test_pin_errors.py for the whole
    # error-surface assertion.
    assert issubclass(AgentSamplingMalformedError, ModelPinError)


def test_a_refusal_names_the_document_it_would_not_read():
    # The message carries the value, because the one thing the caller needs in
    # order to fix a malformed record is the record.
    with pytest.raises(AgentSamplingMalformedError) as refusal:
        AgentSampling.parse('{"temperature": 0.7}')
    assert "temperature" in str(refusal.value)
