"""Feature 203's value type: the triple, and the alias it refuses.

app_spec.xml feature 203: *System persists ``agent_model_id`` per node as a
provider, model and version triple rather than a rolling alias.*  This file
holds the half of that sentence that is about the *value* — what a pinned
authoring model is, how it renders into the one string the ``node`` column can
hold, and every way a value can fail to be one — and leaves the half that is
about the *row* to ``test_pin_store.py``.  The split is the same one the other
suites in this member take: ``test_completion.py`` and ``test_request.py``
never touch a provider, and ``test_provider.py`` never builds a Usage.

The tests are written against the feature's own language — *pinned*, *rolling
alias*, *stratum* — because that language is the requirement.  A test named
``test_parse_rejects_two_parts`` would pass just as well if the feature's point
were a date format; a test named
``test_a_provider_and_model_without_a_version_is_the_aliasing_target_itself``
is a statement about §14.1 and fails if the reasoning behind the refusal ever
weakens.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from providers import (
    MODEL_PIN_PARTS,
    SEPARATOR,
    ModelPin,
    RollingAliasError,
    require_agent_model_id,
)
from providers._pinning import ROLLING_VERSION_MARKERS

#: The ids architecture §14.1's own tables name, as the fixtures a reader is
#: asked to recognise: the root tier's rotation, the depth tier's model, and a
#: self-hosted checkpoint.  Not decoration — three of these tests are about
#: whether a *real* deployment id survives the parse, and a reader who has
#: §14.1 open should find the same strings in both places.
ROOT_TIER = ("anthropic", "claude-opus-5", "20260401")
DEPTH_TIER = ("deepseek", "deepseek-v4.1-flash", "20260910")
SELF_HOSTED = ("local", "ornith-1.5-35b-a3b", "fp8-2026-05")


# ── The triple, as a value ────────────────────────────────────────────────────


def test_a_pin_renders_as_the_provider_model_version_the_column_stores(make_pin):
    # The stored form is one string, and PRD §4's provenance block and
    # architecture §9.1's column comment both spell it the same way:
    # `provider/model/version`.  This is the assertion that fails if the
    # rendering ever drifts from the spelling the schema's own comment writes.
    pin = make_pin(*ROOT_TIER)
    assert str(pin) == "anthropic/claude-opus-5/20260401"
    assert pin.agent_model_id == str(pin)


def test_a_pin_compares_by_its_three_names_not_by_identity(make_pin):
    # Value equality is what makes the store's idempotence check a comparison
    # of *models* rather than of objects: two pins built from different objects
    # but the same three names are the same model, so a retry carrying one is
    # answered rather than refused as a conflict.
    assert make_pin(*ROOT_TIER) == ModelPin(*ROOT_TIER)
    assert make_pin(*ROOT_TIER) != make_pin(*SELF_HOSTED)
    # ...and a pin differing in exactly one part is a different model, which is
    # the whole reason the triple has three parts rather than a string.
    assert make_pin("anthropic", "claude-opus-5", "20260402") != make_pin(*ROOT_TIER)


def test_a_pin_is_frozen_because_an_author_is_history(make_pin):
    # The model that wrote a node is a fact about the past.  A caller that
    # mutated a pin in memory while the row said otherwise would be exactly the
    # divergence the store's compare-then-set exists to prevent.
    pin = make_pin(*ROOT_TIER)
    with pytest.raises(FrozenInstanceError):
        pin.model = "claude-sonnet-5"  # type: ignore[misc]


def test_a_pin_round_trips_through_the_string_the_column_holds(make_pin):
    # The rendering has an inverse and the inverse is faithful: a store that
    # wrote `str(pin)` and read it back gets the pin it wrote.  Without this,
    # the store's retry path would refuse every second call as a conflict.
    for parts in (ROOT_TIER, DEPTH_TIER, SELF_HOSTED):
        assert require_agent_model_id(str(make_pin(*parts))) == make_pin(*parts)


def test_the_three_parts_are_named_in_the_order_the_spec_names_them():
    # "a provider, model and version triple" is the feature's sentence, and the
    # order is not cosmetic: the parts parse positionally, so a reordering
    # would silently re-key every model stratum already in the store.
    assert MODEL_PIN_PARTS == ("provider", "model", "version")


@pytest.mark.parametrize("parts", [ROOT_TIER, DEPTH_TIER, SELF_HOSTED])
def test_the_dateless_and_dotted_ids_the_architecture_recommends_are_accepted(
    make_pin, parts
):
    # Architecture §14.1 mitigation 2: "Prefer dateless IDs that are documented
    # as pinned snapshots rather than rolling aliases, where the provider
    # offers that guarantee."  A parser that demanded an ISO date of `version`
    # would refuse `claude-opus-5` — the id §14.1's root tier names — and would
    # therefore refuse the ids the architecture recommends.  So: no date check,
    # no format check, three non-empty parts and nothing more.
    assert make_pin(*parts).version == parts[2]


# ── The alias, refused ────────────────────────────────────────────────────────


def test_a_bare_model_name_is_the_rolling_alias_the_feature_refuses():
    # The §14.1 failure itself, with the very id that documented it: DeepSeek
    # retired `deepseek-v4-flash` on 2026-09-10 while continuing to accept the
    # id, serving V4.1-Flash underneath.  A node stamped with this string was
    # authored by one of two different models and the row cannot say which, so
    # it belongs to no stratum — which is why feature 203's answer is a triple.
    with pytest.raises(RollingAliasError) as refusal:
        require_agent_model_id("deepseek-v4-flash")
    message = str(refusal.value)
    assert "deepseek-v4-flash" in message
    # The refusal has to teach: a caller's next question is "why can't I store
    # what the API gave me?", and the answer is that the API's id is not a
    # promise.  The number of parts *is* the diagnosis, so it is stated.
    assert "1 part" in message
    assert "rolling alias" in message or "re-routes silently" in message


def test_a_provider_and_model_without_a_version_is_the_aliasing_target_itself():
    # Worse than the bare name, not better.  `deepseek/flash` writes down the
    # thing that makes the alias dangerous — a model line with no snapshot — so
    # accepting it would be accepting a re-routing target with the re-routing
    # spelled out.  It is refused on the same grounds, with the part count in
    # the message so the caller knows it is one short.
    with pytest.raises(RollingAliasError) as refusal:
        require_agent_model_id("deepseek/flash")
    assert "2 parts" in str(refusal.value)


def test_a_four_part_value_is_refused_rather_than_truncated():
    # Guessing which of the extras is the version would be inventing a stratum,
    # and an invented stratum is a model that never ran.  The refusal is the
    # safe answer even though a lenient parser could "make it work".
    with pytest.raises(RollingAliasError) as refusal:
        require_agent_model_id("anthropic/claude/opus-5/v1")
    assert "4 parts" in str(refusal.value)


def test_the_refusal_is_this_features_vocabulary_not_the_standard_librarys():
    # A caller writes `except RollingAliasError`.  A `ValueError` escaping here
    # would be caught by whatever unrelated handler the caller has for
    # ValueErrors, and the two questions would be answered by one clause — the
    # collapse this package's error modules argue against at length.
    assert not issubclass(RollingAliasError, ValueError)
    with pytest.raises(RollingAliasError):
        require_agent_model_id("a/b/c/d")


@pytest.mark.parametrize(
    "value",
    [
        None,
        42,
        b"anthropic/claude-opus-5/20260401",
        ["anthropic", "claude-opus-5", "20260401"],
    ],
)
def test_a_non_string_is_refused_as_a_value_the_column_cannot_hold(value):
    # The column is TEXT.  A caller passing a list that happens to carry the
    # three parts has not pinned a model — it has passed a container, and the
    # refusal says so rather than stringifying it into something that would
    # store.
    with pytest.raises(RollingAliasError) as refusal:
        require_agent_model_id(value)
    assert "must be a string" in str(refusal.value)


@pytest.mark.parametrize("blank", ["", "   "])
def test_an_empty_or_padded_value_is_not_a_triple(blank):
    # `""` splits into one empty part; `"   "` splits into one padded one.
    # Both are refused — on the empty-part rule rather than the whitespace
    # rule, since the whitespace rule is about a *part* and this value has
    # none — and both are refused as aliases, because what they name is
    # nothing at all.
    with pytest.raises(RollingAliasError):
        require_agent_model_id(blank)


@pytest.mark.parametrize(
    "value",
    [
        "anthropic//20260401",
        "/claude-opus-5/20260401",
        "anthropic/claude-opus-5/",
    ],
)
def test_a_triple_with_an_empty_part_names_no_model(value):
    # Three parts is not enough.  A triple whose `model` part is empty names no
    # model, and a stratum keyed on it would be a stratum of a model that does
    # not exist — which is a worse failure than a refusal, because it would
    # look like a legal group in every report that read it.
    with pytest.raises(RollingAliasError) as refusal:
        require_agent_model_id(value)
    assert "non-empty" in str(refusal.value)


def test_a_padded_part_is_refused_because_it_would_not_round_trip(make_pin):
    # The quiet rule, and the one that earns its place by a failure that is
    # hard to see: a part with padding renders to a stored string that parses
    # back to a *different* part, so a retry of the identical pin would read as
    # a conflict with itself.  Stripping the caller's value instead would let
    # two spellings of one model be stored, and the stored string is the
    # stratum key — so the whitespace is refused and the canonical form is
    # named in the message.
    with pytest.raises(RollingAliasError) as refusal:
        make_pin("anthropic ", "claude-opus-5", "20260401")
    assert "'anthropic'" in str(refusal.value)
    # And the round-trip claim is not theoretical: the padded pin renders to a
    # string the parser refuses outright, so it could never have been read back.
    with pytest.raises(RollingAliasError):
        require_agent_model_id("anthropic /claude-opus-5/20260401")


def test_the_separator_is_refused_inside_a_part_so_the_rendering_is_injective():
    # Without this rule two different models could render to one stored string:
    # ("a/b", "c", "d") and ("a", "b/c", "d") both join to "a/b/c/d".  Two
    # models sharing a stratum is the conflation the triple exists to end, so
    # the rule is structural rather than cosmetic and the test says which two
    # triples would have collided.
    with pytest.raises(RollingAliasError) as refusal:
        ModelPin(provider="a/b", model="c", version="d")
    assert "must not contain" in str(refusal.value)
    # The collision the rule prevents, spelled out: the two triples that would
    # have been one string are now one refusal and one pin.
    with pytest.raises(RollingAliasError):
        ModelPin(provider="a", model="b/c", version="d")
    assert str(ModelPin(provider="a", model="b", version="c")) == "a/b/c"


def test_a_part_error_names_the_part_that_is_wrong(make_pin):
    # The refusal has to be actionable: "a model pin's version must be ..." tells
    # a caller which of three arguments to fix, and a message that said only
    # "malformed pin" would leave them to bisect.
    with pytest.raises(RollingAliasError) as refusal:
        make_pin("anthropic", "claude-opus-5", "")
    assert "version" in str(refusal.value)


def test_parse_is_the_same_parse_as_the_free_function(make_pin):
    # `ModelPin.parse` exists so a caller holding the value type has the
    # operation; it must not be a second implementation, because two parses of
    # the stored form is two answers to "what does a/b/c mean?" — the class of
    # drift this package's seams exist to avoid.
    pin = make_pin(*ROOT_TIER)
    assert ModelPin.parse(str(pin)) == pin
    with pytest.raises(RollingAliasError):
        ModelPin.parse("deepseek-flash")


def test_every_refusal_is_catchable_as_the_features_own_error(make_pin):
    # One base for the whole sentence's vocabulary, on the same terms
    # `providers.ProviderError` gives the *call* seam: a caller that wants
    # every failure of feature 203 in one clause writes one clause.  The two
    # bases are deliberately unrelated, and this asserts the *unrelatedness*
    # too — a node stamped with an alias is not a model call that failed.
    from providers import ModelPinError, ProviderError

    assert issubclass(RollingAliasError, ModelPinError)
    assert not issubclass(ModelPinError, ProviderError)
    assert not issubclass(ProviderError, ModelPinError)
    for malformed in ("deepseek-flash", "", "a/b"):
        with pytest.raises(ModelPinError):
            require_agent_model_id(malformed)
    with pytest.raises(ModelPinError):
        make_pin("anthropic", "claude-opus-5", " v1")
    # ...and a *legal* triple is not caught by the same clause, so the base is
    # not a bucket every value falls into.  An inner space is left alone
    # deliberately: a version string a provider actually publishes may contain
    # one, and only *padding* could break the round trip.
    assert require_agent_model_id(make_pin("local", "ornith", "fp8 build 3"))


def test_the_separator_is_the_one_the_schema_comment_writes(make_pin):
    # One character, spelled once.  If `SEPARATOR` changed, every stored value
    # would change meaning at once and nothing in the schema would notice —
    # so this asserts the character itself, not merely that joining uses it.
    assert SEPARATOR == "/"
    assert str(make_pin("a", "b", "c")).count(SEPARATOR) == 2


# ── A marker in the version slot is an alias wearing a triple's shape ─────────


def test_the_marker_words_are_a_frozenset_of_the_words_the_spec_names():
    # The words are data, not a regex buried in the refusal, so the rule can be
    # read off the module and no caller has to reverse-engineer which strings
    # are traps.  A frozenset because membership is the only question asked of
    # it, and a *set* because the rule is a set of words, not a ranking.
    assert isinstance(ROLLING_VERSION_MARKERS, frozenset)
    assert ROLLING_VERSION_MARKERS == frozenset(
        {"latest", "current", "stable", "default", "newest", "live", "auto"}
    )


@pytest.mark.parametrize("marker", sorted(ROLLING_VERSION_MARKERS))
def test_a_version_that_is_a_moving_marker_is_the_rolling_alias_refused(marker):
    # The §14.1 failure in triple form.  "deepseek/deepseek-flash/latest" names
    # a *target* the provider may re-point at will — exactly the bare id the
    # triple exists to refuse, wearing the shape the parser used to accept.  A
    # campaign run in August and one in September under this string can be
    # authored by different models, which is the uncontrolled heterogeneity the
    # M3 paired comparison must not be drawn from.
    with pytest.raises(RollingAliasError) as refusal:
        require_agent_model_id(f"deepseek/deepseek-flash/{marker}")
    message = str(refusal.value)
    # The refusal names the triple and the marker: the caller must be able to
    # see *which* value was refused and *why*, without bisecting the argument.
    assert "deepseek/deepseek-flash/" in message
    assert marker in message


@pytest.mark.parametrize("marker", sorted(ROLLING_VERSION_MARKERS))
def test_a_marker_in_mixed_case_is_still_a_marker(marker):
    # Case-insensitive, because "LATEST" and "Latest" name the same moving
    # target as "latest" — folding is the rule, and a case-sensitive check
    # would be a check a caller could spell around.
    with pytest.raises(RollingAliasError):
        require_agent_model_id(f"deepseek/deepseek-flash/{marker.upper()}")


def test_a_model_name_ending_in_latest_is_the_alias_the_marker_rule_catches():
    # "openai/chatgpt-4o-latest/2024-08-06" puts the marker in the *model* slot
    # and a real-looking date after it.  It is the same alias: the provider
    # re-points "chatgpt-4o-latest" at a newer snapshot while the version part
    # stays a string the row cannot recover the model from.  So the rule is not
    # only "the version is a marker": a model that *is* "latest" or *ends with*
    # "-latest" names a target too, and the version slot cannot rescue it.
    with pytest.raises(RollingAliasError) as refusal:
        require_agent_model_id("openai/chatgpt-4o-latest/2024-08-06")
    assert "chatgpt-4o-latest" in str(refusal.value)
    # ...and the bare "latest" model is caught too, not only the "-latest"
    # suffix — "latest" is a marker word whether or not anything precedes it.
    with pytest.raises(RollingAliasError):
        require_agent_model_id("openai/latest/2024-08-06")
    # Mixed case in the model slot folds the same way the version slot does.
    with pytest.raises(RollingAliasError):
        require_agent_model_id("openai/ChatGPT-4o-LATEST/2024-08-06")


def test_model_pin_construction_applies_the_same_rule_as_the_parser(make_pin):
    # The parser is the classmethod over this rule, so a pin built from three
    # arguments must be refused on the same grounds — otherwise a caller could
    # build in memory a pin whose stored form the reader would refuse.  Each
    # refusal is the feature's own vocabulary, never the standard library's.
    with pytest.raises(RollingAliasError):
        make_pin("deepseek", "deepseek-flash", "latest")
    with pytest.raises(RollingAliasError):
        make_pin("openai", "chatgpt-4o-latest", "2024-08-06")
    # ModelPin.parse is the same parse, so the read-back of such a stored
    # value refuses rather than silently answering a pin.
    with pytest.raises(RollingAliasError):
        ModelPin.parse("deepseek/deepseek-flash/latest")


@pytest.mark.parametrize(
    "version",
    ["20260401", "2026-03-01", "v4.1", "1", "2024-08-06", "fp8-2026-05"],
)
def test_a_dated_or_numbered_version_is_not_a_marker(version):
    # The near-misses the spec names: the rule is a fixed vocabulary of *words*
    # meaning "no snapshot", not a heuristic about what a version looks like.
    # A date, a dotted release and a bare number are all snapshots.
    assert require_agent_model_id(f"anthropic/claude-opus-5/{version}").version == version


@pytest.mark.parametrize(
    ("model", "version"),
    [
        ("stable-diffusion-3", "1"),
        ("autoformer", "1"),
        ("liveness-probe", "20260101"),
        ("newest-model-v2", "1"),
        ("currentness", "1"),
    ],
)
def test_a_model_that_merely_contains_a_marker_word_is_accepted(model, version):
    # A marker word *elsewhere* in a name is not a marker: "stable-diffusion-3"
    # is a model whose name contains "stable", not a name that ends in
    # "-latest".  The suffix is the load-bearing part of the model rule —
    # catching every substring would refuse real, pinned models.
    assert require_agent_model_id(f"local/{model}/{version}").model == model
