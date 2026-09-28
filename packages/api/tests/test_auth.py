"""Feature 18: the token file, the four scopes, and the two refusals.

*System requires a bearer token on every route except GET /healthz, read
from the token file NULLIUS_API_TOKENS_FILE names with each token scoped
to metrics:read, research, evaluator or risk, which returns 401 for a
missing or unknown token, 403 for a token outside the route's scope, and
refuses to start when no token is configured.*

This module holds the *loader* to that sentence — the file's shape, the
closed scope vocabulary, and the several ways a deployment can fail to
state who may ask — and :mod:`test_token_gate` holds the *dispatch* to
it, over a booted server.  The split is the same one :mod:`test_routes`
and :mod:`test_server` already draw: a unit that can be pinned without a
socket, and the law it feeds stated at the wire.

Nothing in this file — and nothing in the module it tests — ever spells a
real-looking credential.  The tokens below are obviously fixtures, which
is deliberate: a test file is one more place a leaked secret could hide,
and a plausible-looking string is the kind that gets copied.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import TEST_TOKENS, token_for
from nullius_api import (
    API_SCOPES,
    EVALUATOR,
    METRICS_READ,
    RESEARCH,
    RISK,
    ApiTokenConfigError,
    ApiTokens,
    bearer_token,
    load_tokens,
)
from nullius_api.auth import TOKENS_FILE_ENV

# -- The scope vocabulary ----------------------------------------------------------


def test_the_four_scope_words_are_the_sentence_s_own() -> None:
    """The closed vocabulary, spelled verbatim — including
    ``metrics:read``'s colon, which is the spec's asymmetry between a
    capability-over-a-surface and three actor names, not a typo to
    tidy."""
    assert API_SCOPES == ("metrics:read", "research", "evaluator", "risk")
    assert (METRICS_READ, RESEARCH, EVALUATOR, RISK) == API_SCOPES


# -- ``Bearer`` parsing ------------------------------------------------------------


@pytest.mark.parametrize("scheme", ["Bearer", "bearer", "BEARER", "BeArEr"])
def test_the_scheme_name_is_case_insensitive(scheme: str) -> None:
    """RFC 7235 makes the scheme case-insensitive, so refusing the
    lower-case spelling would refuse a caller who read the grammar
    correctly."""
    assert bearer_token(f"{scheme} abc123") == "abc123"


@pytest.mark.parametrize(
    "header",
    [
        None,
        "",
        "abc123",  # a bare token with no scheme
        "Basic abc123",  # a different scheme
        "Bearer",  # a scheme with no token after it
        "Bearer   ",  # ... and no token, in whitespace
        "Token abc123",
    ],
)
def test_a_header_with_no_usable_token_answers_none(header: str | None) -> None:
    """Every shape that presents nothing usable is the same fact to the
    dispatch — *this request carried no token* — so they share one
    answer rather than becoming a taxonomy of malformed credentials.
    Telling them apart would report on the shape of a credential rather
    than on whether it was usable."""
    assert bearer_token(header) is None


def test_a_token_is_returned_exactly_as_presented() -> None:
    """Only the framing spaces around the token are the scheme's: the
    value comes back byte for byte, never lower-cased, so a configured
    token that happens to carry case still matches."""
    assert bearer_token("Bearer CaseSensitiveToken") == "CaseSensitiveToken"


# -- The file's shape --------------------------------------------------------------


def _write(tmp_path: Path, document: object) -> str:
    """Write ``document`` as JSON to a per-test file, return its path."""
    path = tmp_path / "tokens.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return str(path)


def test_a_well_formed_file_loads_one_scope_per_token(tmp_path: Path) -> None:
    """The happy shape: scope → the tokens carrying it, in the file's
    own order (the order the constant-time scan walks)."""
    path = _write(
        tmp_path,
        {
            "metrics:read": ["m-one", "m-two"],
            "research": ["r-one"],
            "evaluator": ["e-one"],
            "risk": ["k-one"],
        },
    )
    tokens = load_tokens(path)
    assert tokens.entries == (
        ("m-one", "metrics:read"),
        ("m-two", "metrics:read"),
        ("r-one", "research"),
        ("e-one", "evaluator"),
        ("k-one", "risk"),
    )
    assert tokens.source == path
    assert len(tokens) == 5


def test_scope_lookup_answers_the_scope_or_none(tmp_path: Path) -> None:
    """``scope_for`` is the whole of authentication: a configured token
    answers the scope it carries, anything else answers ``None``."""
    path = _write(tmp_path, {"risk": ["k-one"], "research": ["r-one"]})
    tokens = load_tokens(path)
    assert tokens.scope_for("k-one") == "risk"
    assert tokens.scope_for("r-one") == "research"
    assert tokens.scope_for("k-two") is None
    assert tokens.scope_for("") is None
    # A prefix is not a match, in either direction.
    assert tokens.scope_for("k-on") is None
    assert tokens.scope_for("k-onee") is None


def test_the_scopes_property_lists_only_provisioned_scopes(tmp_path: Path) -> None:
    """A scope the deployment configured no token for is *absent* rather
    than empty — a different fact from *the surface has no scope*, and
    the one the 403's repair is about."""
    tokens = load_tokens(_write(tmp_path, {"risk": ["k-one"]}))
    assert tokens.scopes == ("risk",)

    tokens = load_tokens(
        _write(tmp_path, {"risk": ["k-one"], "research": ["r-one", "r-two"]})
    )
    assert tokens.scopes == ("risk", "research")


# -- The file's refusals, one repair each ------------------------------------------


def test_an_unknown_scope_word_is_refused_naming_the_four(
    tmp_path: Path,
) -> None:
    """A near-miss scope (``metric:read``) would otherwise be a token
    that silently authenticates nobody: the deployment would believe it
    had provisioned a credential and the dispatch would never match it.
    Refused at load, naming all four words."""
    path = _write(tmp_path, {"metric:read": ["m-one"]})
    with pytest.raises(ApiTokenConfigError) as raised:
        load_tokens(path)
    message = str(raised.value)
    assert "metric:read" in message
    for scope in API_SCOPES:
        assert scope in message
    assert "Traceback" not in message


def test_a_scope_holding_no_tokens_is_refused(tmp_path: Path) -> None:
    """An empty list is a surface no credential reaches — a deployment
    fact worth stating by omitting the key, not by an empty list that
    reads as though a token had been forgotten."""
    path = _write(tmp_path, {"risk": []})
    with pytest.raises(ApiTokenConfigError) as raised:
        load_tokens(path)
    assert "risk" in str(raised.value)


@pytest.mark.parametrize("value", ["k-one", {"token": "k-one"}, 7, None])
def test_a_scope_value_that_is_not_a_list_is_refused(
    tmp_path: Path, value: object
) -> None:
    """Each scope *holds a list*; a bare string or an object is a shape
    the loader will not guess at."""
    path = _write(tmp_path, {"risk": value})
    with pytest.raises(ApiTokenConfigError) as raised:
        load_tokens(path)
    assert "risk" in str(raised.value)


@pytest.mark.parametrize("token", [7, None, True, ["nested"]])
def test_a_token_that_is_not_a_string_is_refused(
    tmp_path: Path, token: object
) -> None:
    """A non-string cannot be compared to a credential at all, so it is
    refused rather than coerced — ``str()`` of the wrong thing is how a
    config typo becomes a credential nobody meant to configure."""
    path = _write(tmp_path, {"risk": [token]})
    with pytest.raises(ApiTokenConfigError) as raised:
        load_tokens(path)
    assert "string" in str(raised.value)


def test_an_empty_token_is_refused(tmp_path: Path) -> None:
    """An empty string is a credential every caller already holds."""
    path = _write(tmp_path, {"risk": [""]})
    with pytest.raises(ApiTokenConfigError) as raised:
        load_tokens(path)
    assert "empty" in str(raised.value)


@pytest.mark.parametrize("token", ["has space", "has\ttab", "trailing\n", " lead"])
def test_a_token_containing_whitespace_is_refused(
    tmp_path: Path, token: str
) -> None:
    """A token with whitespace could not survive the ``Bearer`` scheme's
    own framing, so storing it would be storing a secret nobody can
    present — refused at load rather than accepted into a credential
    that never matches."""
    path = _write(tmp_path, {"risk": [token]})
    with pytest.raises(ApiTokenConfigError) as raised:
        load_tokens(path)
    assert "whitespace" in str(raised.value)


def test_one_token_under_two_scopes_is_refused(tmp_path: Path) -> None:
    """The ambiguity rule: a token with two scopes is not a credential
    with two rights but an ambiguity about which one applies, and the
    loader refuses it rather than resolving it to whichever it saw
    last — the same stance the codec takes on two keys that would spell
    one text."""
    path = _write(tmp_path, {"metrics:read": ["shared"], "risk": ["shared"]})
    with pytest.raises(ApiTokenConfigError) as raised:
        load_tokens(path)
    message = str(raised.value)
    assert "metrics:read" in message
    assert "risk" in message


def test_a_top_level_that_is_not_an_object_is_refused(tmp_path: Path) -> None:
    """A list, a string, a number — none of them can be a scope map."""
    path = _write(tmp_path, ["risk"])
    with pytest.raises(ApiTokenConfigError) as raised:
        load_tokens(path)
    assert "object" in str(raised.value)


def test_a_file_that_is_not_json_is_refused_without_echoing_it(
    tmp_path: Path,
) -> None:
    """Malformed JSON is refused by name; the file's own bytes are never
    repeated into the message, because a token file is exactly the
    document whose contents must not travel."""
    path = tmp_path / "tokens.json"
    path.write_text('{"risk": ["k-one"', encoding="utf-8")
    with pytest.raises(ApiTokenConfigError) as raised:
        load_tokens(path)
    message = str(raised.value)
    assert "not JSON" in message
    assert "k-one" not in message


def test_a_file_configuring_no_token_is_refused(tmp_path: Path) -> None:
    """An empty object is the open server by a longer route — refused
    for the same reason an unset variable is."""
    path = _write(tmp_path, {})
    with pytest.raises(ApiTokenConfigError) as raised:
        load_tokens(path)
    assert "no token" in str(raised.value)


def test_a_missing_file_is_refused_naming_the_path(tmp_path: Path) -> None:
    """The path is the operator's own variable coming back, and it is
    the one thing they must act on — so it is named, in a startup
    message that never reaches a response body."""
    missing = tmp_path / "absent.json"
    with pytest.raises(ApiTokenConfigError) as raised:
        load_tokens(str(missing))
    message = str(raised.value)
    assert str(missing) in message
    assert "Traceback" not in message


def test_a_directory_where_a_file_was_named_is_refused(tmp_path: Path) -> None:
    """A read that fails for any other reason is still one plain
    sentence naming the path, never the underlying traceback."""
    with pytest.raises(ApiTokenConfigError) as raised:
        load_tokens(str(tmp_path))
    message = str(raised.value)
    assert str(tmp_path) in message
    assert "Traceback" not in message


# -- Absence is a refusal to start, not an open server -----------------------------


@pytest.mark.parametrize("value", [None, "", "   "])
def test_an_unset_or_blank_variable_refuses_to_start(
    value: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """*A missing token file is a refusal to start, not an open server* —
    the constraint's own law, raised before anything binds.  Unset,
    empty and whitespace-only are one fact: this deployment named no
    token file."""
    env = {} if value is None else {TOKENS_FILE_ENV: value}
    with pytest.raises(ApiTokenConfigError) as raised:
        ApiTokens.from_env(env)
    message = str(raised.value)
    assert TOKENS_FILE_ENV in message
    for scope in API_SCOPES:
        assert scope in message
    assert "Traceback" not in message


def test_the_variable_is_read_from_the_environment_it_is_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``from_env`` resolves against the mapping it is handed, and the
    process environment is only the default — the same stance
    ``ApiConfig.resolve`` takes for the bind address."""
    path = _write(tmp_path, {"risk": ["k-one"]})
    tokens = ApiTokens.from_env({TOKENS_FILE_ENV: f"  {path}  "})
    assert tokens.scope_for("k-one") == "risk"


# -- Building a set in memory ------------------------------------------------------


def test_a_set_can_be_built_from_one_token_per_scope() -> None:
    """``from_scope_tokens`` is the loader's in-memory inverse, and it
    applies the same rules — which is what makes the suite's own
    :data:`conftest.TEST_TOKENS` a credential shaped like a real one."""
    tokens = ApiTokens.from_scope_tokens({"risk": "k-one", "research": "r-one"})
    assert tokens.scope_for("k-one") == "risk"
    assert tokens.scope_for("r-one") == "research"
    assert tokens.scopes == ("risk", "research")


def test_building_in_memory_cannot_launder_a_bad_scope() -> None:
    """The ambiguity the file refuses is refused here too: building
    in memory rather than reading a file must not be a way to configure
    something the file format rejects."""
    with pytest.raises(ApiTokenConfigError):
        ApiTokens.from_scope_tokens({"metric:read": "m-one"})
    with pytest.raises(ApiTokenConfigError):
        ApiTokens.from_scope_tokens({"risk": ""})
    with pytest.raises(ApiTokenConfigError):
        ApiTokens.from_scope_tokens({"risk": "has space"})


def test_a_hand_built_set_is_checked_by_the_type_itself() -> None:
    """``ApiTokens`` is a plain frozen dataclass, so the constructors
    are not the only way in — the invariants are re-asserted in
    ``__post_init__`` rather than trusted to callers, because the whole
    point of the type is that a server holding one cannot be open."""
    with pytest.raises(ApiTokenConfigError):
        ApiTokens(entries=(("", "risk"),))
    with pytest.raises(ApiTokenConfigError):
        ApiTokens(entries=(("k-one", "not-a-scope"),))
    with pytest.raises(ApiTokenConfigError):
        ApiTokens(entries=(("dup", "risk"), ("dup", "research")))
    with pytest.raises(ApiTokenConfigError):
        ApiTokens(entries=())


# -- No token ever reaches a message -----------------------------------------------


@pytest.mark.parametrize(
    "document",
    [
        {"risk": ["super-secret-value"]},  # valid: the message on success
        {"metric:read": ["super-secret-value"]},  # bad scope
        {"risk": ["super-secret-value", "super-secret-value"]},  # duplicated
        {"risk": ["super secret value"]},  # whitespace
        {"risk": []},  # empty list
    ],
)
def test_no_refusal_ever_repeats_a_token(
    tmp_path: Path, document: object
) -> None:
    """Whatever is wrong with the file, the token is not the answer and
    is never repeated — a refusal is read by an operator and kept in a
    log, and a credential belongs in neither."""
    path = _write(tmp_path, document)
    try:
        loaded = load_tokens(path)
    except ApiTokenConfigError as exc:
        assert "super-secret-value" not in str(exc)
    else:  # pragma: no cover - only the valid document takes this arm
        assert "super-secret-value" not in repr(loaded)


def test_the_suite_s_own_tokens_are_shaped_like_real_ones() -> None:
    """The fixture the other suites authenticate with is built through
    the same constructor a deployment would use, so a test cannot pass
    against a credential the loader would have refused."""
    assert set(TEST_TOKENS.scopes) == set(API_SCOPES)
    for scope in API_SCOPES:
        assert TEST_TOKENS.scope_for(token_for(scope)) == scope
