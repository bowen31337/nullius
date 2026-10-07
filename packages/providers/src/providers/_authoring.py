"""The authoring configuration and its record — the LLM-authoring addition's foundation.

additions_spec_llm_authoring.xml, "Authoring Foundation", feature 2: *System
creates an :class:`AuthoringConfig` from the JSON file named by
``NULLIUS_AUTHORING_CONFIG`` with ``providers.load_authoring_config(env=None)``,
or answers ``None`` when the variable is unset.*  The live-providers addition
built the backends — the door, the two vendors, the registry, the budget — and
this addition makes the two LLM roles of architecture §14.1 real, which begins
with one question neither the backends nor the roles can answer alone: *which
models does this deployment author with?*  This module is the answer, as a
file the deployment states and a record every authored node carries.

Why a file, and why that variable
---------------------------------

The models are **stated, never baked**, for the reason every tiering module in
this member restates from §14.2's preamble — *"rates move monthly … the
selection logic is stable, the numbers are not"* — and :class:`FrontierTier`
spells for its own set: a model that was frontier in September is not the one
that is frontier in December, so the deployment names its pins and this module
holds only their shape.  The variable carries the ``NULLIUS_`` prefix the live
registry gives its own names (:data:`providers.LIVE_PROVIDER_ENV_VARS`), which
keeps the research deployment's configuration in one namespace and apart from
claw-forge's own bare names — and apart, too, from the credential variables
themselves, because this variable names a **path**, and a path is the one
thing a credential never is.

``env=None`` reads :data:`os.environ`, the idiom every resolver in this member
follows (:meth:`providers.FixtureStore.resolve`,
:meth:`providers.RootProviderRotation.resolve`): the caller that has its own
mapping — a composition test, a launcher — hands it in, and every other caller
reads the environment of the moment.  An empty or whitespace-only value counts
as unset, and unset answers ``None`` rather than raising, because the factory
calls every registered builder on every ``create_app()``: a deployment that
authors nothing (a CI run, an offline replay against fixtures) is a real
state, and its components answer ``None`` — the discoverable-state stance
features 8 and 10 build their builders on.

The seven keys, and what each one is worth
------------------------------------------

* ``root_tier`` — one to three ``provider/model/version`` pins with
  **distinct providers**.  §14.1's roots row is *"Frontier, rotated across
  2–3 providers"*, and the rotation's whole value is that *"different model
  families carry different priors and propose structurally different
  mechanisms"* — so two pins from one provider is one family stated twice, a
  rotation that reports diversity it does not have, and it is refused here
  rather than measured later as a convergence failure.  One pin is admitted
  for the same reason :class:`FrontierTier` admits a tier of one: a deployment
  that has added only its first family is a real state.  More than three is
  refused because §14.1's own table stops at three and a longer list is a
  fourth spelling of a tier the architecture draws no row for.
* ``depth`` — the one pin that serves the depth ≥ 2 role, §14.1's cheap
  single-model tier.  Its admission gates (features 198, 199) are later
  features' business; this file only names the model.
* ``policy`` — the one pin that revises the exploration policy in dreaming.
* ``temperature`` — in ``[0, 1]``, default ``0.7``.  Deliberately tighter than
  the ``[0, 2]`` the interface and :class:`AgentSampling` both admit: those
  ranges describe what a *call* may carry, and this one describes what an
  *author* may roll — an authored signal is source code that must survive the
  adoption gates, and dice past 1 buy noise the gates refuse at full price.
* ``max_tokens`` — the output ceiling every authoring request carries, a
  positive int, default ``8192``.
* ``max_input_tokens`` and ``max_output_tokens`` — the per-pin budget ceilings
  :class:`providers.BudgetedProvider` enforces.  Required keys with no
  default, because the two keys that *do* carry defaults in the spec's own
  sentence say so, and a budget a config author never stated is not a budget
  the deployment ever had.  Zero is legal and refuses every call — the same
  zero-is-a-statement rule :func:`providers._budget._require_ceiling` keeps.

Every pin is parsed with :func:`providers.require_agent_model_id`, so a
rolling alias (``'deepseek-flash'``) is refused on the way *into* the config
exactly as it is on the way into the store: a deployment configured with one
would author every node under a stratum the provider is free to re-point —
the §14.1 failure (``deepseek-v4-flash``, retired 2026-09-10 while still
accepted) in the deployment's own handwriting.

The one refusal, and what it names
----------------------------------

Everything this module refuses leaves as :class:`AuthoringConfigError`, whose
message opens with the greppable code word :data:`AUTHORING_CONFIG_CODE`
(``authoring_config``), on the precedent
:data:`providers.FIXTURE_MISSING_CODE` sets — and **names the key**: a missing
``depth``, a duplicate root provider, a ``temperature`` past 1, a ceiling
below zero, a ``root_tier`` of four pins, an unparseable file, each refusal
says which key (or which file) it is about, because *"which setting did I get
wrong"* is the only actionable form of that report.  A malformed *pin* arrives
as the pinning vocabulary's own :class:`~providers.RollingAliasError` and is
translated here — the error-vocabulary-at-member-seams rule — so a caller
catching this feature's error catches every way the config can be wrong, and
never a second type it did not import.

The file never holds a credential
---------------------------------

The spec's own sentence, and this module enforces it rather than documenting
it: the document's unknown keys are **refused, naming them**, so a config
carrying an ``api_key`` (or any key the seven above do not name) is refused
rather than parsed past — a parser that ignored unknown keys would accept a
credential-bearing file and the sentence would be a hope rather than a
property.  The refusal names the key and never quotes the value, for the same
reason the live registry's refusals name the variable and never its contents.
And the module reads exactly one thing: the path the environment names.  No
``NULLIUS_*_API_KEY`` is read here, no credential is held, and the record this
module defines carries none.

The record — one authoring, half its provenance
-----------------------------------------------

:class:`AuthoringRecord` is what every authoring call leaves behind: the
``node_id`` it authored, the ``campaign_id`` and ``depth`` of that node, its
``role`` (the closed set :data:`AUTHORING_ROLES` — ``root``, ``depth`` or
``policy``, the three call sites this addition wires), the ``pin`` that
served, the ``sampling`` the call rolled (an :class:`AgentSampling` built with
the config's ``temperature``), the ``usage`` summed over every call the
authoring made — including a retry's — the ``served_model`` the completion
reported, and the ``tier``: the :class:`FrontierTier` built from
``root_tier``, carried by root records because feature 196 records a root's
serving provider *against* the declared tier and the record is where the two
meet.  A depth or policy record carries ``None``, which is the absence of
that fact rather than a tier of nobody.

:meth:`AuthoringRecord.attempt_provenance_terms` answers the authoring third
of discovery's :class:`~discovery.persist.AttemptProvenance` as one mapping —
``agent_model_id`` (the pin rendered ``provider/model/version``),
``agent_sampling`` (the four settings as a mapping), and ``agent_ckpt_hash``
always ``None``, because these are hosted-API pins whose weights live
somewhere this system never hashed (§9.1's annotation on the column:
*non-null for self-hosted weights*) — ready for
``AttemptProvenance(evaluator_hash=…, snapshot_hash=…, cost_model_hash=…,
**record.attempt_provenance_terms())``.  The bridge is a mapping rather than
an import because this member depends on no other member: discovery owns the
six-column record, this module owns its authoring three, and the caller that
holds both joins them — the same seam discipline
:func:`providers.record_root_provider` keeps toward the tree.

Recognition by parts, answers re-made
-------------------------------------

The record re-makes its ``pin``, ``sampling``, ``usage`` and ``tier`` from
this module's classes on construction, recognising each **structurally**
(``object.__getattribute__`` over a parts tuple) rather than by class, for the
reason every seam in this package does: the module loader imports each member
twice, so two ``AuthoringRecord`` classes exist over one source file and a
dataclass's generated ``__eq__`` answers ``False`` between them.  A record
built by the signal agent from the importable member therefore compares equal
to one this module's tests build, whichever copy either came through.

Stdlib-only, like the rest of this tree: ``json`` for the file, the dataclass
for the two records, and no import outside this package.
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ._anthropic import EFFORT_LEVELS, NO_SAMPLING_MODE, _sampling_mode
from ._completion import Usage
from ._pin_errors import ModelPinError
from ._pinning import ModelPin, require_agent_model_id
from ._root import FrontierProvider, FrontierTier, _tier_from_parts
from ._root_errors import RootProviderError
from ._sampling import SAMPLING_KEYS, AgentSampling, require_agent_sampling

__all__ = [
    "AUTHORING_CONFIG_CODE",
    "AUTHORING_CONFIG_ENV",
    "AUTHORING_ROLES",
    "UNSUPPORTED_SAMPLING_CODE",
    "AuthoringConfig",
    "AuthoringConfigError",
    "AuthoringRecord",
    "UnsupportedSamplingError",
    "load_authoring_config",
]

#: The vendor name :mod:`providers._anthropic`'s per-model sampling table
#: applies to — the one vendor this feature's restriction concerns.  Restated
#: rather than imported from :mod:`providers._live` (``_ANTHROPIC``): that
#: module is the live registry's own private name, and this one is this
#: module's refusal's, on the same restatement discipline
#: :mod:`providers._sampling` takes for :data:`providers._pinning.SEPARATOR`-
#: adjacent facts it could import instead.
_ANTHROPIC_PROVIDER: Final[str] = "anthropic"

#: The environment variable naming the authoring configuration's file — the
#: one spelling of "which models does this deployment author with".  Carries
#: the ``NULLIUS_`` prefix the live registry gives its own names
#: (:data:`providers.LIVE_PROVIDER_ENV_VARS`), so the research deployment's
#: configuration sits in one namespace that a path shares with no credential:
#: the variable names a file, and the file holds pins and knobs, never a key.
AUTHORING_CONFIG_ENV: Final[str] = "NULLIUS_AUTHORING_CONFIG"

#: The greppable code word every :class:`AuthoringConfigError` opens with —
#: the token an operator or a CI check scans a launch log for, on the
#: precedent :data:`providers.FIXTURE_MISSING_CODE` sets for its own refusal.
#: Prefixed by the error's constructor rather than at each raise site, so the
#: token and the type are one edit and cannot drift apart.
AUTHORING_CONFIG_CODE: Final[str] = "authoring_config"

#: The three call sites this addition wires, as the closed set the record's
#: ``role`` is drawn from: §14.1's roots row (``root``), its depth tier
#: (``depth``), and dreaming's policy reviser (``policy``).  Declared as data
#: because the record's refusal and features 3's session share one spelling of
#: the set, so a fourth role cannot appear in one place and not the other.
AUTHORING_ROLES: Final[tuple[str, ...]] = ("root", "depth", "policy")

#: The default authoring temperature — the spec's own sentence states it
#: (``temperature (0..1, default 0.7)``), and it is declared here rather than
#: left as a dataclass default so the file-level parse and the record a caller
#: builds name one number: the dice a deployment that turns no knob rolls.
DEFAULT_TEMPERATURE: Final[float] = 0.7

#: The default output ceiling every authoring request carries — the spec's
#: own ``max_tokens (default 8192)``, on the same one-spelling grounds as
#: :data:`DEFAULT_TEMPERATURE`.
DEFAULT_MAX_TOKENS: Final[int] = 8192


class _TemperatureUnstated:
    """The sentinel marking "no caller stated a temperature at all".

    Distinct from every value a caller *can* state: an explicit ``None``
    (feature 5's own "no knob", written ``"temperature": null``) and every
    number in range, including :data:`DEFAULT_TEMPERATURE` itself.  It is
    :class:`AuthoringConfig`'s own field default and :meth:`from_document`'s
    answer for a document that omits the key — the one spelling both doors
    share for "this value was never typed" — and :meth:`AuthoringConfig.__post_init__`
    resolves it to :data:`DEFAULT_TEMPERATURE` or ``None`` depending on
    whether the ``depth`` and ``policy`` pins can honour the default,
    *before* the sampling cross-check runs.  That ordering is the fix: a
    value this module invented can never reach
    :func:`_require_sampling_pin_compatible` and be refused as something the
    config "states", because only a value the caller actually wrote reaches
    that check at all.
    """

    def __repr__(self) -> str:
        return "<temperature unstated>"


#: The one instance of :class:`_TemperatureUnstated` this module ever makes —
#: a sentinel is only useful if every door shares the same object, the way
#: every other closed set in this module is declared once and read everywhere.
_TEMPERATURE_UNSTATED: Final[_TemperatureUnstated] = _TemperatureUnstated()

#: The size bounds of ``root_tier``: §14.1's own roots row says *"rotated
#: across 2–3 providers"*, one is the first-family state
#: :class:`FrontierTier` admits, and three is the most the architecture draws
#: a row for.  A fourth pin is a second spelling of a tier nobody declared.
ROOT_TIER_MIN_PINS: Final[int] = 1
ROOT_TIER_MAX_PINS: Final[int] = 3

#: The eight keys the document holds, in the order the spec's own sentence
#: lists them, plus feature 5's ``effort`` (additions_spec_real_campaign_path.xml)
#: appended last, after the original seven: a document that predates feature
#: 5 names only the first seven, and nothing about their order should move
#: for an eighth key nobody wrote.  Declared as data because two readers
#: iterate it — the unknown-key refusal (the credential guard) and the
#: missing-key refusal — and a key spelled in two places is a key that can be
#: refused in one and not the other.
CONFIG_KEYS: Final[tuple[str, ...]] = (
    "root_tier",
    "depth",
    "policy",
    "temperature",
    "max_tokens",
    "max_input_tokens",
    "max_output_tokens",
    "effort",
)

#: The keys a document must hold.  The complement of the three that are
#: optional — ``temperature`` and ``max_tokens``, which carry defaults in the
#: spec's own sentence, and feature 5's ``effort``, which defaults to
#: ``None`` (no deployment is required to name one) — because a key with a
#: default cannot be missing, and a key without one is a fact the deployment
#: must state: a budget the config author never wrote down is not a budget
#: the deployment ever had.
REQUIRED_KEYS: Final[tuple[str, ...]] = (
    "root_tier",
    "depth",
    "policy",
    "max_input_tokens",
    "max_output_tokens",
)

#: The origin phrase the config's constructor-level refusals carry: the seven
#: fields are validated wherever a config is built — from a file or straight
#: from a caller's values — and a refusal raised in the constructor has no
#: file to name, so it names the value's owner instead.
_CONSTRUCTED: Final[str] = "the authoring config"

#: The origin phrase the record's own refusals carry — the record's owner,
#: for the same reason :data:`_CONSTRUCTED` names the config's.
_RECORD_ORIGIN: Final[str] = "an AuthoringRecord's"

#: The parts a usage record is recognised by, for the structural read the
#: record's construction performs — the double-import remedy every seam in
#: this package makes, spelled over the three counts :class:`Usage` carries.
_USAGE_PARTS: Final[tuple[str, ...]] = (
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
)


class AuthoringConfigError(Exception):
    """The authoring configuration could not be read as one — the addition's one refusal.

    Every way feature 2's sentence can fail, under one base and one code word:
    a file that does not parse, a document that is not an object, a missing
    key, a duplicate root provider, a pin that is a rolling alias, a value
    out of range, a key no authoring config holds.  The message opens with
    :data:`AUTHORING_CONFIG_CODE` — the greppable ``authoring_config`` token,
    on the :class:`~providers.FixtureNotFoundError` precedent — and names the
    key (or the file) it is about, because a refusal that said only "the
    config is wrong" would leave the deployment to diff seven keys by hand.

    Deliberately its own base, sharing no ancestor with
    :class:`~providers.ProviderError` or :class:`~providers.ModelPinError`:
    a config file that cannot be parsed is not a model call that failed and
    not a node that could not be pinned — it is the deployment's own
    statement that could not be read, raised before any call is placed and
    before any node exists.  A caller catching this class is catching "fix
    the file", never "retry the call".
    """

    def __init__(self, message: str) -> None:
        # Prefix the caller's sentence with the refusal's code word, so a log
        # line and the spec's own greppable token say the same thing and a
        # raise site cannot forget it.  Owned here, at the type, so the code
        # and the error are one edit.
        super().__init__(f"{AUTHORING_CONFIG_CODE}: {message}")

    @property
    def code(self) -> str:
        """The refusal's greppable code — :data:`AUTHORING_CONFIG_CODE`."""
        return AUTHORING_CONFIG_CODE


#: The greppable code word :class:`UnsupportedSamplingError` opens with —
#: additions_spec_real_campaign_path.xml feature 5's own word, distinct from
#: :data:`AUTHORING_CONFIG_CODE` because this is one specific, actionable
#: finding ("this pin does not take the knob you set") rather than "the file
#: is wrong" in general, on the precedent
#: :data:`providers._anthropic.UNSUPPORTED_TEMPERATURE_CODE` sets for the same
#: underlying fact seen from the live call's side rather than the config's.
UNSUPPORTED_SAMPLING_CODE: Final[str] = "unsupported_sampling"


class UnsupportedSamplingError(AuthoringConfigError):
    """A config states a temperature for a pin whose model does not accept one.

    :mod:`providers._anthropic`'s per-model sampling table (feature 5) marks
    ``claude-opus-5-5``, ``claude-sonnet-5-5`` and their siblings as unable to
    carry ``temperature`` at all — the vendor answers HTTP 400.  A config
    whose ``depth`` or ``policy`` pin names one of those models *and states a
    temperature* has stated a call that cannot be sent as asked, and feature
    5's own sentence is explicit about the alternative to catching this at
    the first live call: *"refused at load ... and never silently dropped"*
    — a config that loaded clean but then quietly stopped applying the
    temperature it named would be the campaign discovering its own
    misconfiguration one call at a time, which is strictly worse than one
    refusal at the deployment's own launch.

    An *omitted* key never meets this refusal, even for one of these models:
    omitting ``temperature`` states nothing, and :meth:`AuthoringConfig.__post_init__`
    resolves the omission to ``None`` for exactly this pin rather than to
    :data:`DEFAULT_TEMPERATURE` — the model's own default applies, which is
    no ``temperature`` field at all.  Only a document that writes a number
    (the default's own value included) meets this class.

    Scoped to ``depth`` and ``policy`` only, never ``root_tier``: those two
    roles are each **one** fixed pin, so "this pin accepts a knob the config
    does not turn" is a single, unambiguous fact about the deployment's own
    statement.  ``root_tier`` is a *rotation* across 2–3 providers (§14.1),
    and a single global ``temperature`` being incompatible with *one* member
    of a heterogeneous tier is not a config-level contradiction the same
    way — :mod:`providers._anthropic` already does not send the field to
    whichever member of the tier cannot take it, silently and correctly, the
    moment that member's root is actually authored.

    A subclass of :class:`AuthoringConfigError`, not a sibling: it is still
    "this authoring config could not be read as one", so a caller catching
    the base catches this refusal too, on the error-vocabulary-at-member-seams
    rule every class in this module follows — the code word is this class's
    own, not :data:`AUTHORING_CONFIG_CODE`'s, because *that* word means "the
    document is wrong in general" and an operator grepping for *this* finding
    specifically should not have to also match every missing-key and
    out-of-range refusal this module raises.
    """

    def __init__(self, message: str) -> None:
        # Bypasses AuthoringConfigError.__init__ deliberately: that prefixes
        # AUTHORING_CONFIG_CODE, and this refusal's code word is its own —
        # see the class docstring for why the two must not share one.
        Exception.__init__(self, f"{UNSUPPORTED_SAMPLING_CODE}: {message}")

    @property
    def code(self) -> str:
        """The refusal's greppable code — :data:`UNSUPPORTED_SAMPLING_CODE`."""
        return UNSUPPORTED_SAMPLING_CODE


# ── The value guards, one per key ─────────────────────────────────────────────


def _require_pin(value: object, key: str, origin: str) -> ModelPin:
    """Return ``value`` as a :class:`ModelPin`, translated to this module's refusal.

    The one place a pin enters this module — ``root_tier``'s members, ``depth``
    and ``policy`` — and it is :func:`providers.require_agent_model_id` that
    decides what a pin is, so there is one parse of the ``p/m/v`` form in this
    package and the config and the store cannot disagree about it.  A value
    the parse refuses leaves as :class:`AuthoringConfigError` naming ``key``
    and carrying the parse's own sentence (the rolling-alias wording an
    operator acts on), chained so the original type is still in the traceback
    — the error-vocabulary-at-member-seams rule: a caller catching this
    feature's error must not also catch the pinning feature's.
    """
    try:
        return require_agent_model_id(value)
    except ModelPinError as exc:
        raise AuthoringConfigError(
            f"{origin} key {key!r} does not name a pinned model: {exc} A pin "
            f"is the provider/model/version triple the node table's "
            f"agent_model_id column holds, and a value that is not one "
            f"belongs to no model stratum — so the value is refused rather "
            f"than guessed at."
        ) from exc


def _require_root_tier(value: object, origin: str) -> tuple[ModelPin, ...]:
    """Return ``value`` as the root tier's pins — one to three, distinct providers.

    Four refusals, one per rule, each naming ``root_tier`` because that is the
    key the caller wrote the wrong thing under.  A bare string or a mapping is
    refused before the iteration (a ``str`` iterates one character per pin, a
    mapping's keys look like a tier nobody declared); the count is checked
    before the members so a four-pin list is told it is too long, not that its
    fourth entry is an alias; and the members are parsed before the providers
    are compared, so a duplicate is reported as two well-formed pins from one
    family rather than as a parse error on the second.
    """
    if isinstance(value, (str, bytes, Mapping)):
        raise AuthoringConfigError(
            f"{origin} key 'root_tier' must be a list of "
            f"{ROOT_TIER_MIN_PINS} to {ROOT_TIER_MAX_PINS} "
            f"provider/model/version pins, got {value!r} "
            f"({type(value).__name__}). A bare string or a mapping is not the "
            f"collection of pins a rotation draws from — reading one as a list "
            f"would build a tier nobody declared, one pin per character or one "
            f"per key."
        )
    if not isinstance(value, Iterable):
        raise AuthoringConfigError(
            f"{origin} key 'root_tier' must be a list of "
            f"{ROOT_TIER_MIN_PINS} to {ROOT_TIER_MAX_PINS} "
            f"provider/model/version pins, got {value!r} "
            f"({type(value).__name__}), which is not iterable. The root tier "
            f"is the set of families a campaign's roots rotate across "
            f"(architecture §14.1), and a value that holds no pins holds no "
            f"tier."
        )
    pins = tuple(_require_pin(entry, "root_tier", origin) for entry in value)
    if not (ROOT_TIER_MIN_PINS <= len(pins) <= ROOT_TIER_MAX_PINS):
        raise AuthoringConfigError(
            f"{origin} key 'root_tier' must hold "
            f"{ROOT_TIER_MIN_PINS} to {ROOT_TIER_MAX_PINS} pins, got "
            f"{len(pins)}: {[str(pin) for pin in pins]}. Architecture §14.1 "
            f"rotates the frontier tier across 2–3 providers, one is the "
            f"first-family state a tier of one admits, and a list past three "
            f"is a fourth spelling of a tier the architecture draws no row "
            f"for — the rotation would spread across families nobody "
            f"diversified."
        )
    seen: dict[str, ModelPin] = {}
    for pin in pins:
        if pin.provider in seen:
            raise AuthoringConfigError(
                f"{origin} key 'root_tier' declares the provider "
                f"{pin.provider!r} twice, as {seen[pin.provider]!s} and "
                f"{pin!s}. Architecture §14.1 rotates roots across providers "
                f"because different families carry different priors and "
                f"propose structurally different mechanisms — two pins from "
                f"one provider are one family stated twice, a rotation that "
                f"reports diversity it does not have. State each family once."
            )
        seen[pin.provider] = pin
    return pins


def _require_temperature(value: object, origin: str) -> float | None:
    """Return ``value`` as the authoring temperature, in ``[0, 1]``, or ``None``.

    The ceiling is this module's own and tighter than the ``[0, 2]`` the
    interface and the sampling record both admit, because those describe what
    a *call* may carry and this describes what an *author* may roll: an
    authored signal is source code that must survive the adoption gates, and
    dice past 1 buy noise the gates refuse at the full price of the call.
    ``bool`` is refused beside the numbers (``True`` is an ``int`` in Python,
    and a config layer handing one over by accident must not be read as
    temperature 1), and a non-finite float is refused because ``json.loads``
    will happily parse ``NaN`` — a knob that is not a number the models read.

    ``None`` is feature 5's own addition (additions_spec_real_campaign_path.xml)
    and is returned unchanged, ahead of every other check: it is the
    deployment's explicit statement that this config turns no temperature
    knob at all.  Omitting the key from a document is a *different*
    statement — never this function's business at all, because an omitted
    key never calls this guard: :meth:`AuthoringConfig.from_document` hands
    :data:`_TEMPERATURE_UNSTATED` through unchanged, and
    :meth:`AuthoringConfig.__post_init__` resolves *that* sentinel to
    :data:`DEFAULT_TEMPERATURE` or ``None`` on its own, depending on whether
    the pins stated can honour the default — so a config that never typed a
    temperature can never be told it "states" one.  ``None`` is what a
    document states by writing ``"temperature": null`` outright.
    """
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise AuthoringConfigError(
            f"{origin} key 'temperature' must be a number in [0, 1], got "
            f"{value!r} ({type(value).__name__}). Temperature is the one "
            f"sampling knob the authoring config turns, and a value that is "
            f"not a number — including a bool, which Python would otherwise "
            f"read as 0 or 1 — is not a setting any pinned model can honour."
        )
    if not math.isfinite(value):
        raise AuthoringConfigError(
            f"{origin} key 'temperature' is {value!r}, and a non-finite "
            f"number is not a temperature. The knob is carried into every "
            f"authoring request and recorded in every node's agent_sampling, "
            f"and neither place can hold a value no model reads and no "
            f"record round-trips."
        )
    if not 0 <= value <= 1:
        raise AuthoringConfigError(
            f"{origin} key 'temperature' must be in [0, 1], got {value}. The "
            f"authoring path's own ceiling is tighter than the interface's "
            f"[0, 2]: an authored signal is source code that must survive the "
            f"adoption gates, and a temperature past 1 is dice the gates "
            f"refuse at the full price of the call. Pass a value in range or "
            f"leave the key out for the default {DEFAULT_TEMPERATURE}."
        )
    return float(value)


def _require_max_tokens(value: object, origin: str) -> int:
    """Return ``value`` as the output ceiling, a positive int.

    Positive rather than non-negative because ``max_tokens`` is the ceiling a
    request's answer lives under: zero is a call that can produce no answer,
    and a config that states it is refused where it is stated rather than at
    every call it would cripple.  ``bool`` is refused beside the ints, on the
    rule every counted field in this package keeps.
    """
    if not isinstance(value, int) or isinstance(value, bool):
        raise AuthoringConfigError(
            f"{origin} key 'max_tokens' must be a positive int, got "
            f"{value!r} ({type(value).__name__}). The output ceiling is a "
            f"count of tokens every authoring request carries, and a value "
            f"that is not a count is not a ceiling a model can be asked to "
            f"honour."
        )
    if value <= 0:
        raise AuthoringConfigError(
            f"{origin} key 'max_tokens' must be positive, got {value}. A "
            f"non-positive output ceiling is a call that cannot produce an "
            f"answer, so it is refused here, where the deployment can fix "
            f"the file, rather than sent to a model that would return "
            f"nothing."
        )
    return value


def _require_ceiling(value: object, key: str, origin: str) -> int:
    """Return ``value`` as one of the two budget ceilings, a non-negative int.

    Shared by ``max_input_tokens`` and ``max_output_tokens`` because they fail
    the same way and owe the caller the same explanation.  The bound is
    :func:`providers._budget._require_ceiling`'s own, restated: zero is a
    legal ceiling that refuses every call, a deployment stating one is saying "
    spend nothing" and that is a statement, not a malformation — while a
    negative ceiling describes no budget any call could be measured against.
    """
    if not isinstance(value, int) or isinstance(value, bool):
        raise AuthoringConfigError(
            f"{origin} key {key!r} must be a non-negative int, got "
            f"{value!r} ({type(value).__name__}). The two ceilings are the "
            f"per-pin token budgets :class:`providers.BudgetedProvider` "
            f"enforces, and a value that is not a count of tokens describes "
            f"no budget a call could be measured against."
        )
    if value < 0:
        raise AuthoringConfigError(
            f"{origin} key {key!r} must be non-negative, got {value}. A "
            f"ceiling below zero describes no budget any call could be "
            f"measured against; zero is the legal way to state a pin that "
            f"must spend nothing."
        )
    return value


def _require_effort(value: object, origin: str) -> str | None:
    """Return ``value`` as an output-effort level, or ``None``.

    Feature 5's own key (additions_spec_real_campaign_path.xml): the control
    :mod:`providers._anthropic`'s no-sampling models expose in place of
    temperature.  ``None`` means the config names none — a real and common
    state, since effort is meaningless for any pin the sampling table still
    sends temperature to — and is returned unchanged.  A stated value must be
    one of :data:`providers._anthropic.EFFORT_LEVELS`, imported rather than
    restated so the authoring config and the live backend cannot accept two
    different spellings of "the same five levels".
    """
    if value is None:
        return None
    if not isinstance(value, str) or value not in EFFORT_LEVELS:
        raise AuthoringConfigError(
            f"{origin} key 'effort' must be one of {sorted(EFFORT_LEVELS)!r} "
            f"or absent, got {value!r} ({type(value).__name__}). effort is "
            f"the output-effort control the sampling table's no-sampling "
            f"models expose in place of temperature, and a value outside "
            f"the vendor's closed set is not a level any model honours."
        )
    return value


def _require_sampling_pin_compatible(
    *, role: str, pin: ModelPin, temperature: float | None
) -> None:
    """Refuse a ``depth`` or ``policy`` pin that cannot honour a stated temperature.

    The config-level half of feature 5: a pin whose vendor is
    :data:`_ANTHROPIC_PROVIDER` and whose model
    :func:`providers._anthropic._sampling_mode` marks
    :data:`providers._anthropic.NO_SAMPLING_MODE` cannot carry ``temperature``
    at all, so a config that states one (``temperature`` carries one unless
    the document says ``null`` — see :func:`_require_temperature`) has stated
    a call that cannot be sent as asked, and is refused here, at load, rather
    than discovered the first time this pin is actually authored with.

    Only ``depth`` and ``policy`` call this — never a ``root_tier`` member —
    see :class:`UnsupportedSamplingError`'s docstring for why a rotation's
    members are not checked the same way.  A non-anthropic pin, or one this
    module's table admits temperature for, is never consulted past the
    vendor check: the restriction is this one vendor's, stated nowhere else.
    """
    if (
        temperature is not None
        and pin.provider == _ANTHROPIC_PROVIDER
        and _sampling_mode(pin.model) == NO_SAMPLING_MODE
    ):
        raise UnsupportedSamplingError(
            f"the authoring config's {role!r} pin {pin!s} does not accept "
            f"temperature — the sampling table in providers._anthropic marks "
            f"{pin.model!r} as a model whose vendor rejects the field "
            f"outright (HTTP 400 for the models this table names) — and the "
            f"config states {temperature!r}. Set 'temperature' to null in "
            f"the document (optionally naming an 'effort' level instead) to "
            f"author with {pin!s} for the {role!r} role, or pin a different "
            f"model there."
        )


def _pin_accepts_temperature(pin: ModelPin) -> bool:
    """Return whether ``pin``'s vendor and model can carry a temperature at all.

    The same table :func:`_require_sampling_pin_compatible` consults, read
    here for the opposite question: not "does a *stated* value clash with
    this pin" but "can an unstated temperature's default apply to this pin at
    all" — what :meth:`AuthoringConfig.__post_init__` asks of both the
    ``depth`` and ``policy`` pins before it resolves
    :data:`_TEMPERATURE_UNSTATED`, so the default it picks is never one
    either pin's vendor would reject.
    """
    return not (
        pin.provider == _ANTHROPIC_PROVIDER
        and _sampling_mode(pin.model) == NO_SAMPLING_MODE
    )


# ── The configuration ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AuthoringConfig:
    """The deployment's authoring models and knobs, as one value.

    Eight fields, one per key the file holds: the root tier's pins (in the
    file's order, because feature 3's rotation indexes them), the depth and
    policy pins, the temperature every authoring request carries (or
    ``None``, feature 5's addition, when the deployment states none), the
    output ceiling, the two per-pin budget ceilings, and feature 5's
    ``effort`` — the control a no-sampling model exposes in temperature's
    place.  Every field is validated on construction — the pins re-made
    through :func:`providers.require_agent_model_id`, the providers checked
    distinct, the ranges checked, and (feature 5) the ``depth`` and ``policy``
    pins checked against :mod:`providers._anthropic`'s per-model sampling
    table when a temperature is stated — so a config that exists is one the
    session (feature 3) can bind providers from and the recorder (feature 4)
    can take records about, and there is no second validation path for the
    file's values to drift from.

    Frozen and value-equal for the reason every record in this package is: a
    deployment's configuration is a fact about the run, not a field a caller
    tunes — a suite builds the config it expects a file to parse into and
    compares them directly.

    Construction is the door for a caller that already holds the values (a
    test, a sibling feature); :meth:`from_file` and :meth:`from_document` are
    the doors for the bytes and the parsed document, and they add the two
    refusals only a document can meet — a missing key and a key no authoring
    config holds.
    """

    root_tier: tuple[ModelPin, ...]
    depth: ModelPin
    policy: ModelPin
    temperature: float | None | _TemperatureUnstated = _TEMPERATURE_UNSTATED
    max_tokens: int = DEFAULT_MAX_TOKENS
    max_input_tokens: int = 0
    max_output_tokens: int = 0
    effort: str | None = None

    def __post_init__(self) -> None:
        # Field by field in the order the file's own sentence lists them, so a
        # config malformed in two places is refused for the first one a reader
        # would meet — the ordering every record in this package keeps.
        object.__setattr__(
            self, "root_tier", _require_root_tier(self.root_tier, _CONSTRUCTED)
        )
        object.__setattr__(
            self, "depth", _require_pin(self.depth, "depth", _CONSTRUCTED)
        )
        object.__setattr__(
            self, "policy", _require_pin(self.policy, "policy", _CONSTRUCTED)
        )
        if self.temperature is _TEMPERATURE_UNSTATED:
            # Resolved here, after the pins above are already ModelPin
            # instances and before the cross-check below runs, so the value
            # this module invents is never mistaken for one the caller
            # typed: the default applies only when both depth and policy can
            # honour it, and is None — the model's own default, no field
            # sent — the moment either cannot.
            object.__setattr__(
                self,
                "temperature",
                DEFAULT_TEMPERATURE
                if _pin_accepts_temperature(self.depth)
                and _pin_accepts_temperature(self.policy)
                else None,
            )
        else:
            object.__setattr__(
                self,
                "temperature",
                _require_temperature(self.temperature, _CONSTRUCTED),
            )
        object.__setattr__(
            self, "max_tokens", _require_max_tokens(self.max_tokens, _CONSTRUCTED)
        )
        object.__setattr__(
            self,
            "max_input_tokens",
            _require_ceiling(
                self.max_input_tokens, "max_input_tokens", _CONSTRUCTED
            ),
        )
        object.__setattr__(
            self,
            "max_output_tokens",
            _require_ceiling(
                self.max_output_tokens, "max_output_tokens", _CONSTRUCTED
            ),
        )
        object.__setattr__(
            self, "effort", _require_effort(self.effort, _CONSTRUCTED)
        )
        # The cross-check is last, and runs over the already-validated pins
        # and temperature: it is a fact about *this config's own two fields
        # agreeing with each other*, not a shape check on either alone, so it
        # has nothing to say until both sides are already known-good values.
        for role, pin in (("depth", self.depth), ("policy", self.policy)):
            _require_sampling_pin_compatible(
                role=role, pin=pin, temperature=self.temperature
            )

    # -- The file and the document ------------------------------------------

    @classmethod
    def from_document(
        cls, document: object, *, origin: str = "the authoring config document"
    ) -> AuthoringConfig:
        """Build the config a parsed JSON document holds, refusing the rest.

        The document-level refusals live here rather than in the constructor
        because only a document can meet them: a key no authoring config
        holds (the credential guard — the file holds :data:`CONFIG_KEYS` and
        no others, so an unknown one is refused *naming it* and never quoting
        its value), and a missing key from :data:`REQUIRED_KEYS` (a key with
        no default is a fact the deployment must state).  The values
        themselves are the constructor's business, so a document and a caller
        that built the same fields are judged by one set of rules.
        """
        if not isinstance(document, Mapping):
            raise AuthoringConfigError(
                f"{origin} must be a JSON object holding the keys "
                f"{list(CONFIG_KEYS)}, got a {type(document).__name__} "
                f"({document!r}). A list and a bare string both parse as JSON "
                f"and neither names a pin, a knob or a ceiling — there is no "
                f"config to read out of either."
            )
        unknown = sorted(str(key) for key in document if key not in CONFIG_KEYS)
        if unknown:
            raise AuthoringConfigError(
                f"{origin} holds {unknown!r}, which an authoring config has "
                f"no key for. The file holds exactly {list(CONFIG_KEYS)} — "
                f"and never a credential: the pins name models, the knobs "
                f"numbers, and the deployment's keys live in the environment "
                f"the live registry reads, not in this file. Remove the "
                f"unknown keys."
            )
        missing = [key for key in REQUIRED_KEYS if key not in document]
        if missing:
            raise AuthoringConfigError(
                f"{origin} is missing {missing!r}. An authoring config must "
                f"state every key except {' and '.join(sorted(set(CONFIG_KEYS) - set(REQUIRED_KEYS)))} "
                f"(which carry the defaults {DEFAULT_TEMPERATURE} and "
                f"{DEFAULT_MAX_TOKENS}): the pins name the models the "
                f"deployment authors with and the two ceilings its per-pin "
                f"budgets enforce, and a key with no default that the file "
                f"does not hold is a fact the deployment never stated — "
                f"defaulting it would be inventing a budget nobody chose."
            )
        return cls(
            root_tier=document["root_tier"],
            depth=document["depth"],
            policy=document["policy"],
            # .get, not ["temperature"]: an absent key hands the constructor
            # _TEMPERATURE_UNSTATED, which __post_init__ resolves to the
            # sentence's own default or to None depending on the pins, while
            # a key present and null is feature 5's explicit "no temperature"
            # — .get tells the two apart exactly because it only substitutes
            # on absence, and never on DEFAULT_TEMPERATURE directly, which is
            # what let a value nobody stated reach the sampling refusal.
            temperature=document.get("temperature", _TEMPERATURE_UNSTATED),
            max_tokens=document.get("max_tokens", DEFAULT_MAX_TOKENS),
            max_input_tokens=document["max_input_tokens"],
            max_output_tokens=document["max_output_tokens"],
            effort=document.get("effort"),
        )

    @classmethod
    def from_file(cls, path: object) -> AuthoringConfig:
        """Read the file ``path`` names and build the config it holds.

        The one place this module touches the filesystem: it reads the one
        path :data:`AUTHORING_CONFIG_ENV` names and nothing else — no
        credential variable, no other file.  Bytes that do not parse as JSON
        are refused as a malformed file naming the path (a truncated file, a
        half-copied deployment directory, an editor's scratch), and a
        document that parses but is not an object is refused by
        :meth:`from_document` — the split between "the file is unreadable"
        and "the file is readable but wrong", which are different problems
        with different repairs.
        """
        if isinstance(path, (str, bytes, os.PathLike)):
            file = Path(os.fspath(path))
        else:
            raise AuthoringConfigError(
                f"the file {AUTHORING_CONFIG_ENV} names must be a path, got "
                f"{path!r} ({type(path).__name__}). The variable names the "
                f"JSON file the deployment's authoring configuration lives "
                f"in, and a value that is not a path names no file to read."
            )
        origin = f"the authoring config at {file}"
        try:
            raw = file.read_text(encoding="utf-8")
        except OSError as exc:
            raise AuthoringConfigError(
                f"{origin} could not be read: {exc}. The variable "
                f"{AUTHORING_CONFIG_ENV} names this file, and a path that "
                f"cannot be read is a deployment whose authoring "
                f"configuration does not exist — point the variable at the "
                f"config file, or unset it to author nothing."
            ) from exc
        except UnicodeDecodeError as exc:
            raise AuthoringConfigError(
                f"{origin} is not UTF-8 text: {exc}. The file holds the "
                f"deployment's authoring configuration as JSON, and bytes "
                f"that are not text are not a config any parser should "
                f"guess at."
            ) from exc
        try:
            document: object = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AuthoringConfigError(
                f"{origin} is not valid JSON: {exc}. The file holds the "
                f"seven keys of an authoring configuration as one JSON "
                f"object, and bytes that do not parse hold none of them — "
                f"restore the file from the deployment that wrote it rather "
                f"than reconstructing one from a partial document."
            ) from exc
        return cls.from_document(document, origin=origin)

    # -- The derived tier ----------------------------------------------------

    @property
    def tier(self) -> FrontierTier:
        """The root tier's pins as the rotation's own value type.

        The one spelling of "the :class:`FrontierTier` built from
        ``root_tier``" — the record's ``tier`` field and feature 3's rotation
        both build it, and a second spelling of the construction is a second
        place the declared set can drift from the recorded one.  Derived
        rather than stored, so the pins and the tier cannot disagree about
        what the deployment declared; the tier sorts its own members into
        canonical order, which changes no member and no rotation decision
        (:func:`providers.rotation_index` reads the set's size alone).
        """
        return FrontierTier(
            providers=(
                FrontierProvider(provider=pin.provider, model=pin.model)
                for pin in self.root_tier
            )
        )


# ── The record ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AuthoringRecord:
    """What one authoring leaves behind — the node's author, dice and spend.

    The three tree facts (``node_id``, ``campaign_id``, ``depth``), the
    ``role`` the call served (one of :data:`AUTHORING_ROLES`), the ``pin``
    that served it, the ``sampling`` the call rolled, the ``usage`` summed
    over every call the authoring made — a retry's usage is part of what the
    authoring cost, which is why the field is a sum and not the last call's
    figure — the ``served_model`` the completion reported (the serving model,
    which a rotation may have changed from the pin's), and the ``tier``: the
    declared frontier tier, carried by root records because feature 196
    records a root's serving provider against it.  A depth or policy record
    carries ``None`` — the absence of a fact that record's role never had.

    ``sampling`` is an :class:`AgentSampling` **or** a plain JSON-safe
    mapping — feature 5's widening (additions_spec_real_campaign_path.xml): a
    call served by a no-sampling model rolled no temperature at all, and
    recording one would be recording a setting the vendor never applied.  A
    value that is an :class:`AgentSampling`, or a mapping carrying exactly
    its four keys, is judged and normalized by feature 204's own full rules
    (:func:`providers.require_agent_sampling`), unchanged from before this
    feature — a temperature-accepting model's call still rolls all four
    settings.  Anything else must still be a mapping, and is accepted as
    what the call *actually sent* — :func:`providers._anthropic.sent_sampling`
    is the one place that answer is computed — refused only if it cannot
    survive a JSON round-trip, which is the one property this record's own
    persistence (``discovery.persist.AttemptProvenance.agent_sampling``)
    demands of it.  See :func:`_require_record_sampling`.

    **A caveat for a no-sampling record today:** this record accepts and
    carries the mapping honestly, but :meth:`providers.AgentModelPins.persist_weights`
    — the store :func:`providers.record_authoring` files every record
    through — still demands feature 204's exact four keys, because that
    column's own widening is a later feature's, not this one's.  A caller
    that files a no-sampling record through :func:`providers.record_authoring`
    today meets that store's refusal; carrying the honest mapping here is
    what makes that refusal possible to raise instead of a quiet lie, and is
    the ground a later feature's widening of :mod:`providers._pin_store`
    stands on.

    Frozen, so a record that has been handed to the persistence layer cannot
    be edited into different provenance by a caller who kept a reference; and
    value-equal across the module loader's two copies of this member, because
    every nested record is re-made from this module's classes on construction
    (see the module docstring).  :meth:`attempt_provenance_terms` answers the
    authoring third of discovery's
    :class:`~discovery.persist.AttemptProvenance` as one mapping, ready to
    splat — the join is a mapping rather than an import because this member
    depends on no other member.
    """

    node_id: str
    campaign_id: str
    depth: int
    role: str
    pin: ModelPin
    sampling: AgentSampling | Mapping[str, object]
    usage: Usage
    served_model: str
    tier: FrontierTier | None = None

    def __post_init__(self) -> None:
        # Field by field in declaration order, the discipline every record in
        # this package keeps, so a record malformed in two places is refused
        # for the first one a reader would meet.  The two ids are guarded as
        # non-blank strings rather than as UUIDs: the root and depth roles
        # carry tree ids (and the stores that join them canonicalize and
        # refuse at their own seams), while the policy role's revisions are
        # not tree nodes at all, and a guard that demanded a UUID of them
        # would refuse records this addition's own reviser appends.
        object.__setattr__(
            self, "node_id", _require_identifier(self.node_id, "node_id")
        )
        object.__setattr__(
            self,
            "campaign_id",
            _require_identifier(self.campaign_id, "campaign_id"),
        )
        object.__setattr__(self, "depth", _require_record_depth(self.depth))
        if self.role not in AUTHORING_ROLES:
            raise AuthoringConfigError(
                f"an AuthoringRecord's role must be one of "
                f"{list(AUTHORING_ROLES)}, got {self.role!r}. The roles are "
                f"the three call sites this addition wires — §14.1's roots "
                f"row, its depth tier, and dreaming's policy reviser — and a "
                f"fourth is a call site nobody built, so there is no session "
                f"to draw a provider from and no store to file the record "
                f"into."
            )
        object.__setattr__(
            self, "pin", _require_pin(self.pin, "pin", _RECORD_ORIGIN)
        )
        object.__setattr__(
            self, "sampling", _require_record_sampling(self.sampling, _RECORD_ORIGIN)
        )
        object.__setattr__(self, "usage", _usage_from_parts(self.usage))
        if not isinstance(self.served_model, str) or not self.served_model:
            raise AuthoringConfigError(
                f"an AuthoringRecord's served_model must be a non-empty "
                f"string, got {self.served_model!r}. The record names the "
                f"model that served the authoring — which a rotation may "
                f"have changed from the pin's — and a blank or non-string "
                f"name is an author no account can be settled against."
            )
        if self.tier is not None:
            object.__setattr__(self, "tier", _require_record_tier(self.tier))

    def attempt_provenance_terms(self) -> dict[str, object]:
        """The authoring third of an :class:`~discovery.persist.AttemptProvenance`.

        One mapping, ready to splat beside the deployment's three hashes::

            AttemptProvenance(
                evaluator_hash=…, snapshot_hash=…, cost_model_hash=…,
                **record.attempt_provenance_terms(),
            )

        ``agent_model_id`` is the pin rendered ``provider/model/version`` —
        the column's own spelling, so the node's author lands in the stratum
        the pin names.  ``agent_sampling`` is the four settings as a mapping,
        the form discovery's record accepts and canonicalizes to the JSON
        text it stores.  ``agent_ckpt_hash`` is ``None`` and always ``None``:
        these pins are hosted-API models whose weights live somewhere this
        system never hashed, and §9.1's annotation on the column — *non-null
        for self-hosted weights* — makes the null the recorded fact rather
        than a missing one.  A fresh dict each call, so a caller that mutates
        the answer mutates nothing the record holds.
        """
        return {
            "agent_model_id": self.pin.agent_model_id,
            "agent_sampling": _record_sampling_payload(self.sampling),
            "agent_ckpt_hash": None,
        }


# ── The record's own guards ───────────────────────────────────────────────────


def _record_sampling_payload(value: AgentSampling | Mapping[str, object]) -> dict[str, object]:
    """Render ``value`` — an already-validated sampling — as a plain dict.

    ``value`` was validated by :func:`_require_record_sampling` at
    construction, so this is rendering, not a second check: an
    :class:`AgentSampling` renders through its own
    :meth:`~providers.AgentSampling.to_dict`, and a plain mapping (feature
    5's no-sampling payload) renders as a fresh ``dict`` over it — a copy, so
    a caller that mutates the answer mutates nothing this record holds.
    """
    if isinstance(value, AgentSampling):
        return value.to_dict()
    return dict(value)


def _require_record_sampling(
    value: object, origin: str
) -> AgentSampling | Mapping[str, object]:
    """Return ``value`` as the record's sampling — an AgentSampling, or what was sent.

    Two shapes, judged by two different rules, because they answer two
    different questions.  A value that **is** feature 204's four-key record —
    an :class:`AgentSampling`, a duck-typed object exposing its four named
    attributes (the double-import remedy's recognition, read on
    ``object.__getattribute__`` so an arbitrary object's ``__getattr__``
    cannot fabricate the shape), or a plain mapping carrying **exactly**
    :data:`providers.SAMPLING_KEYS` — is judged and normalized by
    :func:`providers.require_agent_sampling`'s full rules, completely
    unchanged by this feature: a temperature-accepting model's call still
    rolls all four settings, and nothing about that call's record becomes
    laxer because a sibling call, served by a different model, now rolls
    something else.

    Anything else must still be a mapping — feature 5's addition
    (additions_spec_real_campaign_path.xml): what a no-sampling model's call
    *actually sent*, which has no slot in the four-key record (an ``effort``
    is not a ``temperature``, and :class:`AgentSampling` has no key for it at
    all).  Refused only if it is not a mapping, or cannot survive a JSON
    round-trip — the one property ``discovery.persist.AttemptProvenance``
    demands of whatever lands in ``agent_sampling`` downstream, checked here
    rather than discovered the first time the record is persisted.
    """
    is_agent_sampling_shaped = False
    try:
        for part in SAMPLING_KEYS:
            object.__getattribute__(value, part)
        is_agent_sampling_shaped = True
    except AttributeError:
        if isinstance(value, Mapping) and set(value) == set(SAMPLING_KEYS):
            is_agent_sampling_shaped = True
    if is_agent_sampling_shaped:
        try:
            return require_agent_sampling(value)
        except ModelPinError as exc:
            raise AuthoringConfigError(
                f"{origin} sampling must be an AgentSampling: {exc} The "
                f"record carries the dice the authoring rolled, and a value "
                f"shaped like the four-setting record but failing its rules "
                f"is not a draw any replay could reproduce."
            ) from exc
    if not isinstance(value, Mapping):
        raise AuthoringConfigError(
            f"{origin} sampling must be an AgentSampling or a mapping of "
            f"what the call actually sent, got {value!r} "
            f"({type(value).__name__}). The record carries either feature "
            f"204's four-setting draw or, for a no-sampling model (feature "
            f"5), the settings the call actually rolled — and a value that "
            f"is neither names no draw a replay could read back."
        )
    try:
        json.dumps(dict(value), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise AuthoringConfigError(
            f"{origin} sampling must be renderable as JSON — {exc} The "
            f"column this feeds (discovery.persist.AttemptProvenance's own "
            f"agent_sampling) stores it as JSON text, and a value no JSON "
            f"renderer may emit is not a draw that record could hold."
        ) from exc
    return dict(value)


def _require_identifier(value: object, field: str) -> str:
    """Return ``value`` as a non-blank id string, refusing anything else.

    Non-blank rather than UUID-shaped, and that is a deliberate narrowing of
    the guard the tree-joining records (:class:`providers.RootCall`) apply to
    the same two names: a root or depth record's ids join feature 97's
    ``node`` table and are canonicalized by the stores that write them, while
    a policy record's ids name revisions of one module — not tree nodes, and
    not UUIDs.  The guard here is the one fact all three roles share: the
    field names a thing, and a blank names none.
    """
    if not isinstance(value, str) or not value.strip():
        raise AuthoringConfigError(
            f"{_RECORD_ORIGIN} {field} must be a non-blank string, got "
            f"{value!r} ({type(value).__name__}). The record is filed by the "
            f"two ids it carries, and an id that names nothing is a record "
            f"no store could file and no reader could join."
        )
    return value


def _require_record_depth(value: object) -> int:
    """Return ``value`` as a non-negative depth, refusing anything else.

    The same guard :func:`providers._root._require_depth` applies to a root
    call's depth, restated for the record: the depth is the tree fact §14.1's
    tiering is read off, and this module does **not** apply the root boundary
    here — the split feature 198 states for its own gate.  A record's role
    and its depth must agree, but that agreement is the author's to keep
    (feature 7 derives both from the same workspace); a value below zero,
    however, names no depth at all.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise AuthoringConfigError(
            f"{_RECORD_ORIGIN} depth must be an int, got {value!r} "
            f"({type(value).__name__}). The depth is the tree fact "
            f"architecture §14.1's tiering is read off, and a value that is "
            f"not a depth cannot be compared with any boundary."
        )
    if value < 0:
        raise AuthoringConfigError(
            f"{_RECORD_ORIGIN} depth must be non-negative, got {value}. "
            f"Depth zero is a root; there is no shallower node for a "
            f"negative depth to name."
        )
    return value


def _usage_from_parts(value: object) -> Usage:
    """Re-make the summed usage from its parts, refusing anything else.

    Recognition is structural — the three counts on
    ``object.__getattribute__`` — rather than by class, because the module
    loader gives every member two class objects over one source file and a
    dataclass's generated ``__eq__`` answers ``False`` between them: a record
    whose usage stayed the caller's class would compare unequal to every
    record the suite builds, and the spend it reports would look like a
    different spend.  Re-made through :class:`Usage`, whose own constructor
    refuses a negative count — translated here so the record's refusal stays
    this module's one vocabulary.
    """
    if isinstance(value, Usage):
        parts = (
            value.input_tokens,
            value.output_tokens,
            value.cache_read_tokens,
        )
    else:
        try:
            parts = tuple(
                object.__getattribute__(value, part) for part in _USAGE_PARTS
            )
        except AttributeError:
            raise AuthoringConfigError(
                f"{_RECORD_ORIGIN} usage must be a Usage record "
                f"({', '.join(_USAGE_PARTS)}), got {value!r} "
                f"({type(value).__name__}). The record carries the token "
                f"accounting summed over every call the authoring made, and "
                f"a value that is not that accounting is a spend no budget "
                f"could be settled against."
            ) from None
    try:
        return Usage(
            input_tokens=parts[0],
            output_tokens=parts[1],
            cache_read_tokens=parts[2],
        )
    except ValueError as exc:
        raise AuthoringConfigError(
            f"{_RECORD_ORIGIN} usage is not a token accounting: {exc} A "
            f"count below zero is a malformed figure rather than a small "
            f"one, and letting it travel into the record would carry a lie "
            f"into every budget the record settles."
        ) from exc


def _require_record_tier(value: object) -> FrontierTier:
    """Re-make the record's declared tier, translated to this module's refusal.

    The re-make itself is :func:`providers._root._tier_from_parts` — the one
    seam ``_rotation`` already imports for the same job — so the record's
    tier and the rotation's tier are normalised by the same reader, and a
    tier built from the workspace's other copy of this member lands here as
    this module's class (the double-import remedy, stated once in the place
    that already states it).  Its refusals are the root-provenance
    vocabulary's own, and they are translated here for the reason every
    guard in this module translates: a caller catching this feature's error
    catches every way the record can be wrong, and never a second type it
    did not import.
    """
    try:
        return _tier_from_parts(value)
    except RootProviderError as exc:
        raise AuthoringConfigError(
            f"{_RECORD_ORIGIN} tier is not a declared frontier tier: {exc} "
            f"The root record carries the declared tier its serving provider "
            f"is recorded against, and a record holding one that cannot be "
            f"declared would name a rotation nobody configured."
        ) from exc


# ── The door ──────────────────────────────────────────────────────────────────


def load_authoring_config(
    env: Mapping[str, str] | None = None,
) -> AuthoringConfig | None:
    """The config :data:`AUTHORING_CONFIG_ENV` names, or ``None`` when it names none.

    The addition's front door and the sentence itself: read the one variable,
    answer the config the file it names holds.  ``env=None`` reads
    :data:`os.environ`; a caller with its own mapping (a composition test, a
    launcher) hands it in, and the mapping is read **here**, at call time —
    the idiom :meth:`providers.FixtureStore.resolve` and every resolver in
    this member follow, so the answer is the environment of the moment the
    question is asked.

    An empty or whitespace-only value counts as unset, and unset answers
    ``None`` rather than raising: a deployment that authors nothing is a real
    state — a CI run, an offline replay against recorded fixtures — and its
    components answer ``None`` on exactly the discoverable-state grounds
    :func:`providers.build_fixture_store` states for its own.  The caller
    that *must* author is the caller that must not find itself in it: for
    that caller the ``None`` is a refusal to proceed, not an absence of
    configuration.

    A file that is there and wrong **raises** — :class:`AuthoringConfigError`
    naming the key — because a deployment that named a config it cannot parse
    has stated an authoring it does not have, and silently authoring nothing
    instead would be the quieter failure: the campaign would run with no
    model behind it and learn nothing, which is the spend without the search.
    """
    source = os.environ if env is None else env
    raw = source.get(AUTHORING_CONFIG_ENV, "").strip()
    if not raw:
        return None
    return AuthoringConfig.from_file(raw)
