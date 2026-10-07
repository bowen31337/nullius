"""The sampling record — feature 204's second half, and the dice it pins.

app_spec.xml, "LLM Provider Tiering & Agent Pinning", feature 204: *System
persists ``agent_ckpt_hash`` for self-hosted weights plus ``agent_sampling``
recording temperature, top_p, thinking and seed.*  :mod:`providers._pinning`
gives a node the identity of the model that authored it; :mod:`providers._ckpt`
gives it the identity of the weights; this module gives it the identity of the
**draw** — the four settings that turned one model into one node.

Why four keys, and why a record always has all four
---------------------------------------------------

The list is the spec's and not this module's: the PRD's provenance block spells
``agent_sampling: dict  # temperature, top_p, thinking, seed`` and architecture
§9.1's column comment spells it back — ``-- {temperature, top_p, thinking,
seed}`` — so the four keys are the one thing the requirement, the schema's own
comment and this module must agree on, and there is no fifth *required* key —
see "The no-sampling extension" below for the one optional key a record may
also carry.

The mandate is the interesting half, and it comes from the column's own
justification.  ``agent_sampling`` is ``JSONB NOT NULL``, and ``0115``'s
docstring says why: *"the sampling parameters are known at authoring time even
when they are defaults: there is no node whose dice are unknown, only
unrecorded ones."*  A two-key record is therefore not a smaller answer than a
four-key one — it is a **wrong** answer, because the only thing a reader can do
with it is assume the settings it omits.  And the one it would most often omit
is ``seed``: ``{"temperature": 0.0, "top_p": 1.0}`` reads as a fully
deterministic draw and leaves replay unable to reproduce anything.

So the record is total, and it is total in both directions:

* :meth:`AgentSampling.to_dict` **always emits all four keys**, so a reader of
  the stored column never has to decide whether a missing key means "default"
  or "unrecorded".
* :func:`require_agent_sampling` **requires all four of a document** — a value
  parsed out of the column, or a mapping a caller built from a config file.  A
  document that names three of them is refused, naming the one it left out,
  and that refusal is the feature: a document is a *record*, and a record that
  omits a setting is a record of a different draw.

**The constructor's defaults are not the same thing, and the difference is
worth stating plainly.**  ``AgentSampling()`` and ``AgentSampling(seed=7)``
work, because a constructor call is a *call* and Python's own keyword-default
convention already means "I did not set this" — and there is no copy of the
call to be read back later by someone who was not there.  A document is the
opposite: it is precisely the artifact a stranger reads months later, which is
what ``0115`` means by *"there is no node whose dice are unknown, only
unrecorded ones"*.  So the defaults are declared once, in
:data:`DEFAULT_SAMPLING`, and a config author who wants them writes
``AgentSampling(**DEFAULT_SAMPLING)`` or the four keys out in full — one of
which the refusal's message names.

The reading of ``seed``
-----------------------

``seed=0`` is a seed, not an absence.  The temptation is to treat a zero as
"unseeded" and refuse it, and that would be wrong twice over: it would refuse
the default the deployment's prompts actually send, and it would make the
*recorded* form of a perfectly reproducible draw unwritable.  What is refused
is ``None`` — a sampling that names no seed at all — because a record with no
seed is precisely the case where replay cannot reproduce the node, which is the
property §14 demands be recordable.  ``sandbox.seed.resolve_seed`` draws the
same line for the node seed itself: a record naming no seed is refused, never
backfilled with one.

The bound on ``seed`` is storability rather than arithmetic, and it is
``sandbox.seed.SEED_MAX``'s: ``2**63 - 1``, the top of the signed 64-bit range
a relational column can hold.  The two bounds are one law about one number —
§12 requires randomness be storable before it is usable — and the value is
restated here rather than imported, because this member depends on no other
member, the same restatement :func:`providers._pin_store._sqlite_path` makes of
the workspace's ``DATABASE_URL`` convention.

Ranges, and where each one comes from
-------------------------------------

* ``temperature`` in ``[0, 2]`` — :class:`providers.Request`'s own ceiling,
  restated.  A record that admitted a temperature the *interface* refuses would
  describe a call this member could not have made, and a store accepting one
  would persist a value its own member forbids.
* ``top_p`` in ``(0, 1]`` — a probability.  Zero is excluded deliberately:
  nucleus sampling at ``top_p=0`` keeps no tokens, so it is not a setting a
  model can be asked to honour, while ``1.0`` is "keep the whole distribution",
  the default every prompt sends.
* ``thinking`` a strict :class:`bool` — a closed set of two, like the
  completion's ``finish_reason`` and the request's roles.  The check runs
  *before* the numeric ones and is exact, because ``isinstance(True, int)`` is
  true in Python: a validator that asked "is this a number?" first would record
  ``thinking=1`` as a temperature and ``temperature=False`` as a number.
* ``seed`` a non-negative :class:`int` in ``[0, 2**63 - 1]``.  ``bool`` is
  refused here too, for the same reason and by the same check.

The no-sampling extension
-------------------------

Feature 5 of ``additions_spec_real_campaign_path.xml`` added models this
module's four keys could not describe honestly: ``claude-opus-5-5`` and
``claude-sonnet-5-5`` reject ``temperature`` and ``top_p`` outright, their
``thinking`` is adaptive rather than a flag the caller turns on or off, and the
knob they do read — ``output_config.effort`` — is none of the original four.
Recording the four required keys as if the call had sent a temperature and a
top_p it never received would be the same fabrication this module refuses
everywhere else, so the fix widens two keys and adds one optional one rather
than minting a second record shape:

* ``temperature`` and ``top_p`` each additionally accept ``None``, meaning
  "not sent — the model's own default applied".  ``None`` is not a fifth
  spelling of a number; it is the honest record of a call this backend could
  not make, the same distinction ``seed=0`` draws against "no seed at all".
* ``thinking`` additionally accepts the string ``"adaptive"`` — still a closed
  set, now of three spellings instead of two, for the one family whose
  reasoning is not a setting the caller chose.
* ``effort`` is the record's one **optional** key, present only when a draw
  sent one.  A document that omits it is not missing a setting — there was no
  effort to record — so :func:`require_agent_sampling` never lists it in a
  "missing" refusal the way it does the four required keys.  A document that
  spells it is checked against :data:`EFFORT_LEVELS`, the same closed set
  ``providers._anthropic.EFFORT_LEVELS`` reads off the wire.

Every record valid before this extension — the four required keys, no
``effort``, no ``None`` and no ``"adaptive"`` among them — parses unchanged and
renders to the identical canonical JSON: the extension widens what the four
keys accept and adds a key nobody wrote before; it does not change what
anything already written means.

No coercion anywhere, in either direction.  ``"0.0"`` is not a temperature,
``0`` is not a ``bool`` and ``True`` is not a seed: each is a caller who passed
the wrong type, and a record that silently converted would store a setting the
caller never chose and could never notice.  ``None`` and ``"adaptive"`` are
not coercions either — they are the two extra, exact spellings the no-sampling
extension recognises, not a looser reading of the originals.

The stored form
---------------

Canonical JSON — :func:`json.dumps` with ``sort_keys=True`` and the compact
separators, the spelling :func:`cost_model.identity.canonical_cost_model` and
:func:`artifacts._execution._render_trace` both use — so two equal samplings are
one stored string, key order is never part of a node's dice, and the value a
reader compares is the value a writer wrote.  ``allow_nan=False`` for
:func:`artifacts._execution._render_trace`'s reason: ``NaN`` is not JSON, is not
even equal to itself, and a stored draw no parser round-trips is a record of
nothing.

The inverse is strict about the *document* as well as about the settings inside
it: a non-string, a JSON array, a bare number and a document carrying a
non-finite float are each refused by name.  A reader that "recovered" a
sampling record from ``'0.7'`` would be inventing three settings, which is the
same fabrication :func:`providers.require_agent_model_id` refuses for a rolling
alias.

Stdlib-only: ``json``, the dataclass and ``collections.abc``.  This module
touches no store, no transport and no provider SDK.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ._pin_errors import AgentSamplingMalformedError

__all__ = [
    "AGENT_SAMPLING_COLUMN",
    "DEFAULT_SAMPLING",
    "EFFORT_LEVELS",
    "MAX_TEMPERATURE",
    "SAMPLING_KEYS",
    "SEED_MAX",
    "AgentSampling",
    "require_agent_sampling",
]

#: The ``node`` column the record is persisted into — feature 100's, spelled by
#: the spec's own schema block and created by revision ``0115``.  Named here for
#: the reason :data:`providers.AGENT_MODEL_ID_COLUMN` is: the store, the
#: refusals and the suite share one string.
AGENT_SAMPLING_COLUMN = "agent_sampling"

#: The four settings, in the order the PRD's provenance block and architecture
#: §9.1's column comment both list them.  Declared as data because more than the
#: rendering iterates it: the refusals build their messages from it, the
#: canonical spelling sorts by it, and the suite pins the *order* by it — so the
#: list cannot quietly become three settings, or the same four in another order,
#: and leave a stored record meaning something else.
SAMPLING_KEYS: tuple[str, ...] = ("temperature", "top_p", "thinking", "seed")

#: The largest seed this record accepts: ``2**63 - 1``, the top of the signed
#: 64-bit range.  ``sandbox.seed.SEED_MAX`` states the same bound in the same
#: words — *"the bound is not arithmetic caution ... it is storability"* — and
#: the two must agree, because they are one law about one number seen from the
#: two ends of the same row.  Restated rather than imported: this member depends
#: on no other member.
SEED_MAX = 2**63 - 1

#: The sampling temperature ceiling — :class:`providers.Request`'s own
#: ``_MAX_TEMPERATURE``, restated here.  A record admitting a temperature the
#: request refuses would describe a call the interface could not have carried.
MAX_TEMPERATURE = 2.0

#: The closed set ``effort`` accepts — the control a no-sampling model reads
#: in place of ``temperature`` and ``top_p`` (feature 5 of
#: ``additions_spec_real_campaign_path.xml``).  Restated from
#: ``providers._anthropic.EFFORT_LEVELS`` rather than imported, for the reason
#: :data:`SEED_MAX` and :data:`MAX_TEMPERATURE` are restated above: this
#: member depends on no other member.
EFFORT_LEVELS: frozenset[str] = frozenset({"low", "medium", "high", "xhigh", "max"})

#: The record at all four defaults, as the column stores it.  This is what a
#: deployment that turns none of the knobs records, and it is declared as data
#: rather than left implicit for two reasons: the refusal that names a missing
#: key names *this* value as the thing to write, and the suite pins it against
#: both :meth:`AgentSampling.to_dict` and ``0115``'s own fixtures — so the
#: defaults a deployment sends and the defaults the schema's tests plant cannot
#: drift apart.
DEFAULT_SAMPLING: dict[str, Any] = {
    "temperature": 0.0,
    "top_p": 1.0,
    "thinking": False,
    "seed": 0,
}

#: The JSON spelling's settings — the canonical form every member of this
#: workspace that writes JSON for a hash or a comparison uses.  Sorted keys and
#: compact separators, so indentation and key order are never part of a node's
#: dice.
_JSON_KWARGS: dict[str, Any] = {
    "sort_keys": True,
    "separators": (",", ":"),
    "allow_nan": False,
}


def _require_settings(values: Mapping[str, Any], origin: str) -> dict[str, Any]:
    """Return ``values`` as the four required settings plus ``effort``, or refuse it.

    The one place the record's rules live, shared by the constructor and the
    parse, so a record built from four arguments and one read back out of the
    column are judged by one set of rules — the drift
    :func:`providers.require_agent_model_id` refuses on its own seam.

    The order of the checks is the order a reader meets the fields, and it is
    load-bearing in one place: ``thinking`` is checked *first* of the two kinds
    of value, because :class:`bool` is a subclass of :class:`int` in Python and
    a validator that asked "is this a number?" first would accept
    ``thinking=1`` as a flag and ``temperature=False`` as a temperature.  Both
    are callers passing the wrong type, and both are refused by name.

    ``effort`` is read with :meth:`~collections.abc.Mapping.get` rather than
    ``values["effort"]``: it is the no-sampling extension's one optional key,
    so its absence is not a caller's omission the way a missing ``temperature``
    would be — see :func:`_require_effort`.
    """
    allowed = set(SAMPLING_KEYS) | {"effort"}
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise AgentSamplingMalformedError(
            f"an agent_sampling record carries {unknown!r}, which the record "
            f"has no key for, in {origin}. Feature 204 records exactly "
            f"{', '.join(SAMPLING_KEYS)} (PRD §4's provenance block; "
            f"architecture §9.1's column comment), plus the one optional key "
            f"the no-sampling extension added — 'effort', one of "
            f"{sorted(EFFORT_LEVELS)!r} — so a key outside that set is a "
            f"setting no reader of the column knows to look for, and storing "
            f"it would make the same column mean one thing to a writer and "
            f"another to the ablation that reads it."
        )
    return {
        "thinking": _require_thinking(values["thinking"], origin),
        "temperature": _require_temperature(values["temperature"], origin),
        "top_p": _require_top_p(values["top_p"], origin),
        "seed": _require_seed(values["seed"], origin),
        "effort": _require_effort(values.get("effort"), origin),
    }


def _require_thinking(value: Any, origin: str) -> bool | str:
    """Return ``value`` as a strict flag or ``"adaptive"``, refusing anything else.

    Exact rather than truthy: ``isinstance(value, bool)`` and nothing else, or
    the one extra string the no-sampling extension recognises.  ``1``,
    ``"true"`` and ``"yes"`` are how three config formats spell ``true``, and a
    record that accepted any of them would store a value this module chose
    rather than one the caller wrote — while a *truthiness* test would also
    accept ``[]`` and ``0``, which nobody passes meaning "do not think".
    """
    if isinstance(value, str) and value == "adaptive":
        return value
    if not isinstance(value, bool):
        raise AgentSamplingMalformedError(
            f"an agent_sampling record's thinking must be a bool or the "
            f"string 'adaptive', got {value!r} ({type(value).__name__}), in "
            f"{origin}. Thinking is one of feature 204's four settings; the "
            f"no-sampling extension widens its closed set from two spellings "
            f"to three, for the one family whose reasoning is adaptive rather "
            f"than a flag the caller turns on or off — so a value that is "
            f"none of the three is refused rather than interpreted, because "
            f"interpreting it would store a setting the caller never wrote."
        )
    return value


def _require_temperature(value: Any, origin: str) -> float | None:
    """Return ``value`` as a temperature in range, ``None``, or refuse it.

    ``None`` means "not sent — the model's own default applied", the
    no-sampling extension's reading for a model that rejects the field
    outright.  It is not a fifth spelling of a number: a record that
    defaulted it to ``0.0`` would claim the vendor received a temperature it
    never did.  Otherwise the ceiling is :class:`providers.Request`'s,
    restated: this member would otherwise hold a record of a call the
    interface refuses, and a store that accepted one would be persisting a
    value its own member forbids.  The floor is zero — a negative temperature
    is not a sampling regime any model exposes, and it is refused rather than
    clamped, because a clamped value is a record that disagrees with the call
    it describes.
    """
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise AgentSamplingMalformedError(
            f"an agent_sampling record's temperature must be a number or "
            f"null, got {value!r} ({type(value).__name__}), in {origin}. "
            f"Temperature is a sampling knob a pinned model reads, or null for "
            f"a no-sampling model that was sent none at all; a non-number — "
            f"including a bool, which Python would otherwise accept as 0 or 1 "
            f"— is not a setting it can honour."
        )
    if not math.isfinite(value):
        raise AgentSamplingMalformedError(
            f"an agent_sampling record's temperature is {value!r}, in {origin}. "
            f"The record is stored as canonical JSON, which has no form for a "
            f"non-finite number, and NaN is not even equal to itself — so a "
            f"record carrying one could not be read back as the settings that "
            f"produced the node."
        )
    if not (0 <= value <= MAX_TEMPERATURE):
        raise AgentSamplingMalformedError(
            f"an agent_sampling record's temperature must be in "
            f"[0, {MAX_TEMPERATURE}] or null, got {value}, in {origin}. A "
            f"temperature outside that range is a sampling regime neither the "
            f"provider interface nor the models the deployment pins exposes, "
            f"so it is refused here rather than stored as a draw that could "
            f"not have happened."
        )
    return float(value)


def _require_top_p(value: Any, origin: str) -> float | None:
    """Return ``value`` as a nucleus-sampling probability in ``(0, 1]``, ``None``, or refuse it.

    ``None`` means "not sent — the model's own default applied", the same
    no-sampling reading :func:`_require_temperature` gives it.  Otherwise
    zero is excluded and the exclusion is the interesting half: ``top_p=0``
    keeps no tokens, so it is not a setting a model can be asked to honour, and
    a record carrying one would be a stored draw no model could have produced.
    ``1.0`` is the other end and is legal — "keep the whole distribution", the
    default every prompt sends — so the bound is half-open and the refusal says
    which end was wrong.
    """
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise AgentSamplingMalformedError(
            f"an agent_sampling record's top_p must be a number or null, got "
            f"{value!r} ({type(value).__name__}), in {origin}. top_p is the "
            f"nucleus probability the draw sampled from, or null for a "
            f"no-sampling model that was sent none at all; a non-number is "
            f"not one."
        )
    if not math.isfinite(value):
        raise AgentSamplingMalformedError(
            f"an agent_sampling record's top_p is {value!r}, in {origin}. The "
            f"record is stored as canonical JSON, which has no form for a "
            f"non-finite number, so a record carrying one could not be read "
            f"back as the settings that produced the node."
        )
    if not (0 < value <= 1):
        raise AgentSamplingMalformedError(
            f"an agent_sampling record's top_p must be in (0, 1] or null, got "
            f"{value}, in {origin}. Nucleus sampling keeps the smallest set of "
            f"tokens whose probability mass reaches top_p, so 0 keeps no "
            f"tokens at all — it is not a setting any model can honour, and a "
            f"stored draw carrying it could not have happened. 1.0 is legal "
            f"and is the whole distribution."
        )
    return float(value)


def _require_effort(value: Any, origin: str) -> str | None:
    """Return ``value`` as one of :data:`EFFORT_LEVELS`, or ``None`` if absent.

    ``effort`` is the record's one **optional** key: present only when a draw
    sent one to a no-sampling model in place of ``temperature`` and ``top_p``.
    ``None`` means no effort was sent, and that is not a refusal the way a
    missing required setting is — there is nothing to record. A value that is
    present but outside the closed set is refused, by the same no-coercion
    rule the four required settings follow.
    """
    if value is None:
        return None
    if not isinstance(value, str) or value not in EFFORT_LEVELS:
        raise AgentSamplingMalformedError(
            f"an agent_sampling record's effort must be one of "
            f"{sorted(EFFORT_LEVELS)!r} or absent, got {value!r} "
            f"({type(value).__name__}), in {origin}. effort is the optional "
            f"control a no-sampling model reads in place of temperature and "
            f"top_p; a spelling outside that set is not a level any backend "
            f"honours."
        )
    return value


def _require_seed(value: Any, origin: str) -> int:
    """Return ``value`` as a seed inside the range a relational store can hold.

    ``0`` is accepted and is a seed, not an absence — see the module docstring.
    ``None`` is refused, and it is the refusal that matters most in this
    function: a sampling record naming no seed is exactly the case where replay
    cannot reproduce the node, and defaulting one in would make the record
    *look* reproducible.  The upper bound is :data:`SEED_MAX`.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise AgentSamplingMalformedError(
            f"an agent_sampling record's seed must be an int, got {value!r} "
            f"({type(value).__name__}), in {origin}. Seed is the one of feature "
            f"204's four settings that makes a replay reproduce the node, so it "
            f"is recorded or it is not — None and every non-integer spelling "
            f"are refused here rather than defaulted, because a defaulted seed "
            f"would make the record look reproducible when nothing about the "
            f"draw could be reproduced from it."
        )
    if not (0 <= value <= SEED_MAX):
        raise AgentSamplingMalformedError(
            f"an agent_sampling record's seed must be in [0, {SEED_MAX}], got "
            f"{value}, in {origin}. The bound is storability rather than "
            f"arithmetic: §12 requires the seed be persisted with the node, so "
            f"a seed outside the signed 64-bit range a relational column holds "
            f"is a draw whose randomness could never be written down."
        )
    return value


@dataclass(frozen=True)
class AgentSampling:
    """The four required settings plus ``effort`` — feature 204's dice, extended.

    ``temperature``, ``top_p``, ``thinking`` and ``seed`` are required and
    validated on construction, the way feature 204 shipped them; ``effort`` is
    the one optional key the no-sampling extension added.  Frozen and
    value-equal for the reason every record in this package is: it is a fact
    about a generation that already happened, and equality is by value, so a
    suite can assert ``load_provenance(node).sampling == AgentSampling(...)``
    rather than reaching into fields.

    The keyword defaults are the *call site's* convenience — a caller
    describing a call it is making says ``AgentSampling(seed=7)`` — and they are
    not a licence for a *document* to omit a required key:
    :func:`require_agent_sampling` requires all four of anything parsed, which
    is the difference the module docstring sets out. ``effort`` has no such
    requirement to omit, because it is optional in a document the same way it
    is here.  :meth:`to_dict` always emits the four required keys, plus
    ``effort`` when it is not ``None``, so what lands in the column is total
    whichever way the record was built.
    """

    temperature: float | None = 0.0
    top_p: float | None = 1.0
    thinking: bool | str = False
    seed: int = 0
    effort: str | None = None

    def __post_init__(self) -> None:
        # Validated through the same helper the parse uses, so a record built
        # from arguments and one read back out of the column are judged by one
        # set of rules — there is no second validation path to drift.  The
        # validated values are assigned back onto the record, so an ``int``
        # temperature is stored as the ``float`` it means and two records built
        # two ways compare equal.
        values = _require_settings(
            {
                "temperature": self.temperature,
                "top_p": self.top_p,
                "thinking": self.thinking,
                "seed": self.seed,
                "effort": self.effort,
            },
            origin="the sampling record being built",
        )
        for key, value in values.items():
            object.__setattr__(self, key, value)

    # -- The stored form ----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """The record as the column stores it: the four required keys, always, plus ``effort`` when set.

        A fresh :class:`dict` rather than something over ``__dict__``, so a
        caller that mutates the result mutates nothing this record holds; that
        is what lets the record stay frozen while its rendering is a plain
        mapping a JSON encoder can carry.  ``effort`` is omitted entirely when
        it is ``None`` rather than rendered as a null, so a record built before
        the no-sampling extension renders to the identical four-key document it
        always has.
        """
        document: dict[str, Any] = {
            "temperature": self.temperature,
            "top_p": self.top_p,
            "thinking": self.thinking,
            "seed": self.seed,
        }
        if self.effort is not None:
            document["effort"] = self.effort
        return document

    def to_json(self) -> str:
        """The record as the canonical JSON text the column stores.

        The one byte spelling: sorted keys and compact separators, so two equal
        samplings render to equal bytes and key order is never part of a node's
        identity.  ``allow_nan=False`` cannot fire for a record that validated
        on construction — but a value this renderer may not emit is refused here
        rather than stored as half a record, and stating the refusal where the
        encoding happens is cheaper than trusting a rule stated elsewhere.

        The separators are passed as a tuple and restored to a list by
        :func:`json.dumps` internally, which is why the round trip through
        :func:`require_agent_sampling` sees a document with the same four keys
        and the same values whatever the caller did with whitespace.
        """
        try:
            return json.dumps(self.to_dict(), **_JSON_KWARGS)
        except (TypeError, ValueError) as exc:  # pragma: no cover - guarded above
            raise AgentSamplingMalformedError(
                f"an agent_sampling record must be renderable as canonical "
                f"JSON — {exc}; the column holds this text and every reader "
                f"parses it back, so a value no JSON renderer may emit is not a "
                f"set of dice that can be recorded beside the node."
            ) from exc

    @property
    def agent_sampling(self) -> str:
        """The record as the ``node.agent_sampling`` column stores it.

        A property rather than ``__str__`` alone, so the value a store writes is
        named by the column it goes into — the same reason
        :attr:`providers.ModelPin.agent_model_id` is one.
        """
        return self.to_json()

    @classmethod
    def parse(cls, value: object) -> AgentSampling:
        """Read a stored ``agent_sampling`` back into the record it names.

        The classmethod spelling of :func:`require_agent_sampling`, for a caller
        holding the value type rather than the free function.  It delegates
        rather than re-implementing: there is one parse of the stored form in
        this package, so the write path and the read path cannot disagree about
        what ``{"seed": 0, ...}`` means.
        """
        return require_agent_sampling(value)

    def __str__(self) -> str:
        return self.to_json()


def _stored_document(value: object, origin: str) -> Mapping[str, Any]:
    """Return ``value`` as a JSON object, refusing anything that is not one.

    The stored column holds *text*, and this is where the text is read, so the
    refusals here are about the document rather than about the settings inside
    it — :func:`_require_settings` handles those.  A JSON array, a bare number
    and a bare string are all parseable JSON and none of them is a sampling
    record, and a reader that accepted one would be answering *which dice
    produced this node?* with something that has no dice in it.
    """
    if isinstance(value, (bytes, bytearray, str)):
        text = value.decode("utf-8") if not isinstance(value, str) else value
        try:
            document: object = json.loads(text)
        except (ValueError, UnicodeDecodeError) as exc:
            raise AgentSamplingMalformedError(
                f"an agent_sampling record must be JSON, but {origin} holds "
                f"{text!r}, which does not parse: {exc}. The column holds "
                f"feature 204's four settings as canonical JSON (architecture "
                f"§9.1: {{temperature, top_p, thinking, seed}}), and a value "
                f"that is not that document names none of them."
            ) from exc
    else:
        document = value
    if not isinstance(document, Mapping):
        raise AgentSamplingMalformedError(
            f"an agent_sampling record must be a JSON object with feature 204's "
            f"four keys, but {origin} holds a {type(document).__name__} "
            f"({document!r}). A list, a number and a bare string all parse as "
            f"JSON and none of them names a temperature, a top_p, a thinking or "
            f"a seed."
        )
    return document


def _record_fields_or_none(value: object) -> Mapping[str, Any] | None:
    """A sampling *record* as its fields, or ``None`` if it is not one.

    A record is recognised by its **attributes, not its class**, and that is not
    stylistic — it is the workspace's module loader.  The loader imports every
    member twice, once by file path under ``_nullius_scanned_<dir>`` and once as
    the importable member, so ``AgentSampling`` exists as two distinct class
    objects over one source file and an ``isinstance`` check answers ``False``
    for a record a caller legitimately built from the other copy.  Feature 203
    shipped exactly that defect and its fix is the precedent this follows: the
    checked shape is what matters, and a value carrying the four required
    settings *is* the record whichever module object it came from.

    Checked on ``object.__getattribute__`` rather than ``getattr``, so an
    arbitrary object's ``__getattr__`` cannot fabricate four settings — this
    function is a gate, and a hook that answered four names would be a hook that
    recorded a draw.  The values are *not* re-validated here: they are validated
    by :func:`_require_settings` at the one seam that builds a record, and a
    second check here would be a rule to drift from.

    ``effort`` is read the same way but is allowed to be missing — it reads as
    ``None`` rather than disqualifying the value as a record, because it is
    the one optional field and a stand-in built before the no-sampling
    extension would not carry it.
    """
    fields: dict[str, Any] = {}
    try:
        for key in SAMPLING_KEYS:
            fields[key] = object.__getattribute__(value, key)
    except AttributeError:
        return None
    try:
        fields["effort"] = object.__getattribute__(value, "effort")
    except AttributeError:
        fields["effort"] = None
    return fields


def require_agent_sampling(value: object) -> AgentSampling:
    """Return ``value`` as an :class:`AgentSampling`, refusing anything else.

    The one parse of the stored form, and feature 204's second gate.  Accepts
    the column's text, a mapping a caller built, or a record built from either
    copy of this module — and **requires all four required settings of a
    document**, which is the rule the module docstring argues for: a document
    is a record, and a record missing a required setting is a record of a
    different draw.  ``effort`` stays optional throughout: it is never listed
    as missing, because a document that sent no effort is not a document that
    forgot one.

    Deliberately unaccommodating in the three directions a caller meets it:

    * **A partial document is refused.**  ``{"temperature": 0.3}`` is the shape
      a caller reaches for, and storing it would record one of four settings
      while every reader assumed the other three.  The refusal names the keys
      it did not get and the values to write in their place, because *"which
      setting did you forget"* is the only actionable form of that report.
    * **``None`` for a seed is refused**, though ``0`` is accepted: a record
      naming no seed cannot be replayed, and defaulting one in is exactly the
      lie the mandate exists to prevent.  ``None`` for ``temperature`` or
      ``top_p`` is accepted, by contrast — the no-sampling extension's reading
      of "not sent", not an absence of the kind ``seed`` refuses.
    * **A value of the wrong type is refused rather than coerced.**  ``"0.7"``
      is not a temperature and ``1`` is not a flag; both are a caller who
      passed the wrong thing, and both would otherwise store a setting the
      caller never chose.

    A record built from *this* module's class is returned unchanged: it was
    validated when it was constructed, and re-making it would be four
    conversions on a path that only renders it.
    """
    if isinstance(value, AgentSampling):
        return value
    record = _record_fields_or_none(value)
    if record is not None:
        # The other copy of this module's record class, or a duck-typed stand-in
        # carrying the four settings.  Re-made through *this* module's class so
        # everything downstream — equality, the value a caller gets back — is
        # one class; two dataclasses of the same shape compare unequal across
        # classes however equal their fields, and the store's idempotence check
        # would then report a conflict whose two sides are the same draw.
        return AgentSampling(**_require_settings(record, "a sampling record"))
    origin = "the value being recorded"
    document = _stored_document(value, origin)
    missing = [key for key in SAMPLING_KEYS if key not in document]
    if missing:
        raise AgentSamplingMalformedError(
            f"an agent_sampling record is missing {missing!r}, in {origin}. "
            f"Feature 204 records all four of {', '.join(SAMPLING_KEYS)} (PRD "
            f"§4's provenance block; architecture §9.1's column comment), and "
            f"the column is NOT NULL for the reason 0115 gives: *the sampling "
            f"parameters are known at authoring time even when they are "
            f"defaults — there is no node whose dice are unknown, only "
            f"unrecorded ones*. A record naming three settings is not a smaller "
            f"answer than one naming four, it is a wrong one: every reader of "
            f"the column can only assume what it leaves out, and the setting "
            f"most often left out is seed — the one that makes a replay "
            f"reproduce the node. Write "
            f"{ {key: DEFAULT_SAMPLING[key] for key in missing} !r} if the draw "
            f"used the defaults. (effort is not among these four: it is "
            f"optional, and a document naming none of it is not missing "
            f"anything.)"
        )
    return AgentSampling(**_require_settings(document, origin))
