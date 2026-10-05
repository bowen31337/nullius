"""Feature 2's foundation: the authoring config file, and the record it feeds.

additions_spec_llm_authoring.xml, "Authoring Foundation", feature 2: *System
creates an ``AuthoringConfig`` from the JSON file named by
``NULLIUS_AUTHORING_CONFIG`` with ``providers.load_authoring_config(env=None)``,
or answers ``None`` when the variable is unset.*  This file holds the whole of
that sentence: the door (the variable, the file, the ``None``), the seven keys
the document holds, every refusal the spec names — a malformed file, a missing
key, a duplicate root provider, an out-of-range value, each as
``AuthoringConfigError`` under the code word ``authoring_config`` — and the
record the authoring path leaves behind, with the provenance terms that carry
its author into discovery's attempt record.

**The split of the addition's labour, so a reader knows what is not here.**
The session that binds providers to the config's three roles is feature 3
(``test_authoring_session.py``); the store that files the record is feature 4
(``test_authoring_store.py``).  What this suite pins is the value both of them
stand on: a deployment states one file, the file parses into one config or
refuses naming the key it refused, and the config is the one place the root
tier, the two single pins and the two budgets are declared.

**The sentence's most load-bearing refusal is the unknown key.**  The spec
says *the file never holds a credential*, and a parser that ignored keys it
did not know would accept a credential-bearing file and the sentence would be
a hope rather than a property.  So the test below refuses an ``api_key`` key
**by name** — with a value that is not a credential (``"not-a-credential"``)
and an assertion that the value never appears in the refusal, because the
live registry's own refusals name the variable and never its contents.

**No test here opens a connection or reads a key.**  The only filesystem these
tests touch is pytest's per-test ``tmp_path``; the only provider names are the
architecture's own model spellings, which are pins and not credentials; and
the one environment variable read is the feature's own.  Model calls are not
made at all — this is the config, before any call exists.
"""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest
from providers import (
    AgentSampling,
    AuthoringConfig,
    AuthoringConfigError,
    AuthoringRecord,
    FrontierProvider,
    FrontierTier,
    ModelPin,
    ModelPinError,
    ProviderError,
    Usage,
    load_authoring_config,
)

#: The environment variable the sentence names, spelled in the test module
#: rather than imported, so a rename of the member's constant is a failing
#: test about the *feature text* rather than a suite that follows the code.
VARIABLE = "NULLIUS_AUTHORING_CONFIG"

#: The code word every refusal opens with — the spec's own spelling, pinned
#: the same way as :data:`VARIABLE`.
CODE_WORD = "authoring_config"

#: The three call sites the record's ``role`` is drawn from, in the spec's
#: order: the roots row, the depth tier, and dreaming's policy reviser.
ROLES = ("root", "depth", "policy")

#: The two keys the spec's own sentence gives defaults, with those defaults —
#: ``temperature (0..1, default 0.7)`` and ``max_tokens (default 8192)``.
DEFAULTED = {"temperature": 0.7, "max_tokens": 8192}

#: The five keys a document must hold: the sentence states defaults for
#: exactly two keys, so the other five are facts the deployment states.
REQUIRED = (
    "root_tier",
    "depth",
    "policy",
    "max_input_tokens",
    "max_output_tokens",
)

#: §14.2's own roots row, as the pin strings a deployment writes — the three
#: families the architecture's rate card names for the roots tier, each with
#: the snapshot suffix that makes it a pin rather than a rolling alias.
ROOT_PINS = (
    "anthropic/claude-opus-5/20260401",
    "openai/gpt-5.6-sol/20260701",
    "google/gemini-3.1-pro/20260801",
)

#: The depth and policy pins of a full document — §14.2's own depth row for
#: the one, the third frontier family for the other, so a fixture reads like
#: the deployment it stands in for.
DEPTH_PIN = "deepseek/deepseek-v4-flash/20260910"
POLICY_PIN = "google/gemini-3.1-pro/20260801"


def document(**overrides) -> dict:
    """A full authoring document, with any key overridden or added.

    The one builder every document-level test starts from, so the seven keys
    are spelled in one place and a test that overrides one key is a test
    about *that key* — not about a document that happens to be missing the
    rest.
    """
    base = {
        "root_tier": list(ROOT_PINS),
        "depth": DEPTH_PIN,
        "policy": POLICY_PIN,
        "temperature": 0.4,
        "max_tokens": 4096,
        "max_input_tokens": 60000,
        "max_output_tokens": 8192,
    }
    base.update(overrides)
    return base


def write_config(tmp_path, payload) -> str:
    """Write ``payload`` as the config file and return the path to hand the door.

    ``payload`` may be any JSON-serialisable value, so the malformed-file and
    not-an-object cases write their own bytes the same way the good one does.
    """
    target = tmp_path / "authoring.json"
    target.write_text(
        payload if isinstance(payload, str) else json.dumps(payload),
        encoding="utf-8",
    )
    return str(target)


# ── The door: one variable, one file, one None ────────────────────────────────


def test_an_unset_variable_answers_none():
    # The sentence's other half: unset is not an error, because a deployment
    # that authors nothing is a real state and its builders answer None.
    assert load_authoring_config(env={}) is None


def test_a_blank_variable_counts_as_unset():
    # Empty and whitespace-only are the spellings of "named nothing" — the
    # idiom every resolver in this member follows — and both answer None
    # rather than raising, for the same reason unset does.
    for raw in ("", "   "):
        assert load_authoring_config(env={VARIABLE: raw}) is None


def test_the_door_reads_os_environ_when_env_is_none(tmp_path, monkeypatch):
    # ``env=None`` is the composition-time spelling: the caller hands no
    # mapping and the door reads the environment of the moment.  Both
    # directions are pinned — set reads it, unset answers None — because the
    # builders features 8 and 10 register call exactly this form.
    path = write_config(tmp_path, document())
    monkeypatch.setenv(VARIABLE, path)
    assert load_authoring_config() == AuthoringConfig.from_document(document())
    monkeypatch.delenv(VARIABLE, raising=False)
    assert load_authoring_config() is None


def test_a_named_file_loads(tmp_path):
    path = write_config(tmp_path, document())
    config = load_authoring_config(env={VARIABLE: path})
    assert config == AuthoringConfig.from_document(document())


def test_a_file_that_is_not_there_names_the_path(tmp_path):
    missing = str(tmp_path / "absent.json")
    with pytest.raises(AuthoringConfigError) as raised:
        load_authoring_config(env={VARIABLE: missing})
    assert missing in str(raised.value)
    assert VARIABLE in str(raised.value)


# ── The document: seven keys, and nothing else ────────────────────────────────


def test_the_two_defaulted_keys_carry_the_sentence_defaults(tmp_path):
    # The sentence states defaults for exactly two keys; a document that
    # omits both parses with 0.7 and 8192, and nothing else is defaulted —
    # the five required keys are refused below when they are missing.
    minimal = {key: value for key, value in document().items() if key in REQUIRED}
    config = AuthoringConfig.from_document(minimal)
    assert config.temperature == DEFAULTED["temperature"]
    assert config.max_tokens == DEFAULTED["max_tokens"]


def test_every_stated_key_is_honoured(tmp_path):
    config = AuthoringConfig.from_document(document())
    assert config.root_tier == tuple(ModelPin(*pin.split("/")) for pin in ROOT_PINS)
    assert config.depth == ModelPin(*DEPTH_PIN.split("/"))
    assert config.policy == ModelPin(*POLICY_PIN.split("/"))
    assert config.temperature == 0.4
    assert config.max_tokens == 4096
    assert config.max_input_tokens == 60000
    assert config.max_output_tokens == 8192


def test_bytes_that_do_not_parse_are_refused_as_a_malformed_file(tmp_path):
    path = write_config(tmp_path, '{"root_tier": ["anthropic/claude-opus-5')
    with pytest.raises(AuthoringConfigError) as raised:
        load_authoring_config(env={VARIABLE: path})
    assert path in str(raised.value)


def test_a_document_that_is_not_an_object_is_refused(tmp_path):
    # A JSON array parses and names no pin, no knob and no ceiling — there is
    # no config to read out of it, and the refusal says what it got.
    path = write_config(tmp_path, [ROOT_PINS[0]])
    with pytest.raises(AuthoringConfigError) as raised:
        load_authoring_config(env={VARIABLE: path})
    assert "list" in str(raised.value)


def test_a_key_no_authoring_config_holds_is_refused_by_name():
    # The credential guard: the file holds seven keys and no others, so an
    # unknown one is refused rather than parsed past — and the refusal names
    # the key while never quoting the value, so a credential-bearing file is
    # refused without the refusal becoming a second place the value appears.
    with pytest.raises(AuthoringConfigError) as raised:
        AuthoringConfig.from_document(document(api_key="not-a-credential"))
    assert "api_key" in str(raised.value)
    assert "not-a-credential" not in str(raised.value)


@pytest.mark.parametrize("key", REQUIRED)
def test_a_missing_required_key_is_refused_by_name(key):
    payload = document()
    del payload[key]
    with pytest.raises(AuthoringConfigError) as raised:
        AuthoringConfig.from_document(payload)
    assert key in str(raised.value)


# ── root_tier: one to three pins, distinct providers ──────────────────────────


@pytest.mark.parametrize("count", [1, 2, 3])
def test_one_to_three_pins_is_the_tier_the_architecture_draws(count):
    # §14.1's roots row says "rotated across 2–3 providers"; one is the
    # first-family state FrontierTier admits, and three is the most the
    # architecture's own table names.  All three counts parse, in file order
    # — feature 3's rotation indexes the pins as they are stated.
    pins = list(ROOT_PINS[:count])
    config = AuthoringConfig.from_document(document(root_tier=pins))
    assert config.root_tier == tuple(ModelPin(*pin.split("/")) for pin in pins)


def test_four_pins_is_a_tier_nobody_drew():
    fourth = "deepseek/deepseek-v4-flash/20260910"
    with pytest.raises(AuthoringConfigError) as raised:
        AuthoringConfig.from_document(document(root_tier=[*ROOT_PINS, fourth]))
    assert "root_tier" in str(raised.value)


def test_an_empty_tier_declares_nobody():
    with pytest.raises(AuthoringConfigError) as raised:
        AuthoringConfig.from_document(document(root_tier=[]))
    assert "root_tier" in str(raised.value)


def test_a_duplicate_root_provider_is_one_family_stated_twice():
    # Same provider, different models: the rotation would report diversity
    # it does not have — §14.1's reason for rotating is that different
    # families propose structurally different mechanisms.  The refusal names
    # root_tier and the provider it saw twice.
    duplicate = "anthropic/claude-haiku-4-5/20251001"
    with pytest.raises(AuthoringConfigError) as raised:
        AuthoringConfig.from_document(
            document(root_tier=[ROOT_PINS[0], duplicate])
        )
    assert "root_tier" in str(raised.value)
    assert "anthropic" in str(raised.value)


def test_a_bare_string_is_not_a_tier():
    # A str iterates one character per pin and a mapping's keys look like a
    # tier nobody declared — both are refused before any member is parsed.
    for shape in (ROOT_PINS[0], {"providers": list(ROOT_PINS)}):
        with pytest.raises(AuthoringConfigError) as raised:
            AuthoringConfig.from_document(document(root_tier=shape))
        assert "root_tier" in str(raised.value)


# ── The pins: one parse, translated at the seam ───────────────────────────────


@pytest.mark.parametrize("key", ["root_tier", "depth", "policy"])
def test_a_rolling_alias_is_translated_to_the_configs_refusal(key):
    # A two-part name is the §14.1 failure in the deployment's own
    # handwriting: a stratum the provider is free to re-point.  The pinning
    # feature refuses it as its own error; the config translates that into
    # AuthoringConfigError naming the key, so a caller catching the config's
    # error catches every way the file can be wrong.
    alias = "deepseek/deepseek-v4-flash"
    payload = document()
    payload[key] = [alias, ROOT_PINS[1]] if key == "root_tier" else alias
    with pytest.raises(AuthoringConfigError) as raised:
        AuthoringConfig.from_document(payload)
    assert key in str(raised.value)
    assert not isinstance(raised.value, ModelPinError)


# ── The ranges: two knobs and two ceilings ────────────────────────────────────


@pytest.mark.parametrize(
    "value",
    [1.5, -0.1, "0.7", True, float("nan"), float("inf")],
)
def test_a_temperature_out_of_range_is_refused(value):
    # The authoring path's own ceiling is tighter than the interface's
    # [0, 2]: dice past 1 buy noise the adoption gates refuse at full price.
    # A bool is refused beside the numbers (Python would read True as 1) and
    # a non-finite float too — json.loads will happily parse NaN.
    with pytest.raises(AuthoringConfigError) as raised:
        AuthoringConfig.from_document(document(temperature=value))
    assert "temperature" in str(raised.value)


@pytest.mark.parametrize("value", [0, 1, 0.35])
def test_the_temperature_boundaries_are_admitted(value):
    assert AuthoringConfig.from_document(document(temperature=value)).temperature == value


@pytest.mark.parametrize("value", [0, -1, "8192", True])
def test_a_non_positive_max_tokens_is_refused(value):
    # The output ceiling a request's answer lives under: zero is a call that
    # can produce no answer, refused where it is stated.
    with pytest.raises(AuthoringConfigError) as raised:
        AuthoringConfig.from_document(document(max_tokens=value))
    assert "max_tokens" in str(raised.value)


@pytest.mark.parametrize("key", ["max_input_tokens", "max_output_tokens"])
def test_a_ceiling_below_zero_is_refused(key):
    # Zero is the legal way to state a pin that must spend nothing — the
    # same zero-is-a-statement rule the budget's own ceiling guard keeps —
    # and anything that is not a non-negative int describes no budget.
    for value in (-5, "x", False):
        with pytest.raises(AuthoringConfigError) as raised:
            AuthoringConfig.from_document(document(**{key: value}))
        assert key in str(raised.value)
    assert AuthoringConfig.from_document(document(**{key: 0}))


# ── The constructor and the declared tier ─────────────────────────────────────


def test_the_constructor_takes_values_a_caller_already_holds():
    # from_file and from_document are the doors for bytes and documents;
    # the constructor is the door for a caller holding the values — and it
    # judges them by the same rules, so the two paths cannot drift.
    built = AuthoringConfig(
        root_tier=tuple(ModelPin(*pin.split("/")) for pin in ROOT_PINS),
        depth=ModelPin(*DEPTH_PIN.split("/")),
        policy=ModelPin(*POLICY_PIN.split("/")),
        temperature=0.4,
        max_tokens=4096,
        max_input_tokens=60000,
        max_output_tokens=8192,
    )
    assert built == AuthoringConfig.from_document(document())
    with pytest.raises(AuthoringConfigError):
        AuthoringConfig(
            root_tier=tuple(ModelPin(*pin.split("/")) for pin in ROOT_PINS),
            depth=ModelPin(*DEPTH_PIN.split("/")),
            policy=ModelPin(*POLICY_PIN.split("/")),
            max_input_tokens=60000,
            max_output_tokens=8192,
            temperature=1.5,
        )


def test_the_declared_tier_is_derived_from_the_pins():
    # "The FrontierTier built from root_tier" is derived, never stored, so
    # the pins and the tier cannot disagree about what the deployment
    # declared.  The tier sorts its own members into canonical order, which
    # changes no member and no rotation decision.
    config = AuthoringConfig.from_document(document())
    expected = FrontierTier(
        providers=(
            FrontierProvider(provider="anthropic", model="claude-opus-5"),
            FrontierProvider(provider="openai", model="gpt-5.6-sol"),
            FrontierProvider(provider="google", model="gemini-3.1-pro"),
        )
    )
    assert config.tier == expected
    assert FrontierProvider(provider="openai", model="gpt-5.6-sol") in config.tier


# ── The record: one authoring, half its provenance ────────────────────────────


def make_record(**overrides) -> AuthoringRecord:
    """A root record with sensible defaults, any field overridden.

    The defaults are the shape feature 7's caller builds: the root tier
    derived from the config, an AgentSampling with the config's temperature,
    and the summed usage of the calls the authoring made.
    """
    fields = {
        "node_id": "7be0d3b2-1c4f-4a2e-9d10-5f6a8b2c4e01",
        "campaign_id": "0d1e2a3b-4c5d-6e7f-8a9b-0c1d2e3f4a5b",
        "depth": 0,
        "role": "root",
        "pin": ModelPin(*ROOT_PINS[0].split("/")),
        "sampling": AgentSampling(temperature=0.7),
        "usage": Usage(input_tokens=120, output_tokens=340),
        "served_model": "claude-opus-5-20260401",
        "tier": AuthoringConfig.from_document(document()).tier,
    }
    fields.update(overrides)
    return AuthoringRecord(**fields)


def test_one_authoring_as_a_record():
    record = make_record()
    assert record.role == "root"
    assert record.pin.agent_model_id == ROOT_PINS[0]
    assert record.tier == AuthoringConfig.from_document(document()).tier


def test_a_record_is_frozen():
    # A record handed to the persistence layer cannot be edited into
    # different provenance by a caller who kept a reference.
    record = make_record()
    with pytest.raises(FrozenInstanceError):
        record.served_model = "some-other-model"


def test_a_role_outside_the_three_call_sites_is_refused():
    with pytest.raises(AuthoringConfigError) as raised:
        make_record(role="frontier")
    assert "role" in str(raised.value)
    for role in ROLES:
        make_record(role=role)


def test_the_policy_roles_ids_are_names_not_uuids():
    # Feature 9's revisions are keyed "revision-N" in campaign
    # "policy-development" — not tree nodes and not UUIDs — so the record's
    # ids are guarded as names, and the stores that join tree ids
    # canonicalize them at their own seams.
    record = make_record(
        node_id="revision-3", campaign_id="policy-development", role="policy", tier=None
    )
    assert record.node_id == "revision-3"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("node_id", "  "),
        ("node_id", 7),
        ("campaign_id", ""),
        ("depth", -1),
        ("depth", True),
        ("served_model", ""),
        ("served_model", 5),
    ],
)
def test_a_malformed_field_is_refused(field, value):
    with pytest.raises(AuthoringConfigError):
        make_record(**{field: value})


def test_duck_typed_values_are_re_made_into_the_members_classes():
    # The module loader imports every member twice, so a dataclass's
    # generated __eq__ answers False across the two copies.  The record
    # recognises its nested values structurally and re-makes them from this
    # module's classes, so a record built from pin text, a sampling mapping
    # and a duck-typed usage compares equal to one built from the values.
    duck = make_record(
        pin=ROOT_PINS[0],
        sampling={"temperature": 0.7, "top_p": 1.0, "thinking": False, "seed": 0},
        usage=SimpleNamespace(
            input_tokens=120, output_tokens=340, cache_read_tokens=0
        ),
    )
    typed = make_record()
    assert duck == typed
    assert isinstance(duck.pin, ModelPin)
    assert isinstance(duck.sampling, AgentSampling)
    assert isinstance(duck.usage, Usage)


def test_a_depth_or_policy_record_carries_no_tier():
    # None is the absence of the tier fact, not a tier of nobody: only the
    # root role's records carry the declared rotation.
    assert make_record(role="depth", tier=None).tier is None
    assert make_record(role="policy", tier=None).tier is None


def test_attempt_provenance_terms_answers_the_authoring_third():
    # The three terms discovery's AttemptProvenance holds beyond the
    # deployment's three hashes: the pin rendered p/m/v, the four settings
    # as a mapping, and a checkpoint hash that is None and always None —
    # hosted-API weights live somewhere this system never hashed.
    terms = make_record().attempt_provenance_terms()
    assert terms == {
        "agent_model_id": ROOT_PINS[0],
        "agent_sampling": {
            "temperature": 0.7,
            "top_p": 1.0,
            "thinking": False,
            "seed": 0,
        },
        "agent_ckpt_hash": None,
    }


def test_the_terms_splat_into_a_provenance_signature():
    # The bridge is a mapping rather than an import: discovery owns the
    # six-column record, this module owns its authoring three, and the
    # caller that holds both joins them with one splat.
    def provenance(
        evaluator_hash, snapshot_hash, cost_model_hash, *, agent_model_id,
        agent_sampling, agent_ckpt_hash,
    ):
        return (evaluator_hash, agent_model_id, agent_ckpt_hash)

    assert provenance(
        "eval", "snap", "cost", **make_record().attempt_provenance_terms()
    ) == ("eval", ROOT_PINS[0], None)


def test_the_terms_answer_a_fresh_mapping_each_call():
    # A caller that mutates the answer mutates nothing the record holds.
    record = make_record()
    first = record.attempt_provenance_terms()
    first["agent_ckpt_hash"] = "mutated"
    assert record.attempt_provenance_terms()["agent_ckpt_hash"] is None


# ── The refusal vocabulary ────────────────────────────────────────────────────


def test_every_refusal_opens_with_the_code_word(tmp_path):
    # The greppable token an operator scans a launch log for, prefixed by
    # the error's own constructor so a raise site cannot forget it.
    with pytest.raises(AuthoringConfigError) as exc:
        load_authoring_config(env={VARIABLE: str(tmp_path / "absent.json")})
    assert str(exc.value).startswith(f"{CODE_WORD}: ")
    assert exc.value.code == CODE_WORD


def test_the_error_is_its_own_base():
    # A config file that cannot be parsed is not a model call that failed
    # (ProviderError) and not a node that could not be pinned (ModelPinError)
    # — it is the deployment's own statement that could not be read, and a
    # caller catching it is catching "fix the file", never "retry the call".
    assert not issubclass(AuthoringConfigError, ProviderError)
    assert not issubclass(AuthoringConfigError, ModelPinError)
