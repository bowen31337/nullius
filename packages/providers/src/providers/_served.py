"""The depth role's verification layer — feature 199's gate.

app_spec.xml, "LLM Provider Tiering & Agent Pinning", feature 199: *System
rejects a depth model whose verified served context limit is below the campaign
history size, rather than trusting a published figure.*  Feature 198's gate
(:func:`providers.require_depth_model`) decides whether a model may take the
depth role's calls at all, against a **fixed one-million-token bar** read off
the candidate's **declared** rate card.  This module is the second layer of the
same criterion, and it rests on a sentence of architecture §14.1 that sits in
the very paragraph the 256K clause comes from:

    **A model with a 256K window physically cannot execute the defining prompt
    of this system in a mature wide campaign.** Such models are confined to
    early-depth nodes, narrow campaigns, and the §10.6 bootstrap worlds, where
    histories are short and self-contained. **Verify the served context limit
    (``--max-model-len``), not the marketing number.**

Two things in that sentence are the whole of this feature.  The first is
**verify the served context limit** — the fact is not what a rate card
publishes, it is what the deployment that will actually take the calls has been
configured to attend over.  The second is that the bar is **the campaign's
history size**, not a constant: a self-hosted 262K tier is refused for a wide
campaign and admitted for a narrow one, which is precisely how §14.1's own list
of roles resolves the 256K clause.

Why this is a second module and not a third conjunct of feature 198
-------------------------------------------------------------------

Feature 198's gate reads three fields of a candidate's own description and
compares one of them to a bar this package spells as data.  Everything here is
different: the fact is *measured* (or admitted as unmeasured), the bar is the
*call's* own history, and the answer carries the *margin* between them.  A gate
that folded both layers into one function would have to take a campaign's
history as an argument for the fixed-bar check to ignore — and a parameter a
check does not read is a parameter that drifts.

The two layers also fail differently and are repaired differently: 198 refuses
a model that cannot do the role *at any campaign size*, and its repair is
another model; this layer refuses a model for *one campaign's* history, and its
repair is a narrower campaign, a shorter history, or a larger served window
(§14.1's confinement list, applied per campaign).  :mod:`providers._depth`
already reserves this ground in as many words — its docstring hands feature 199
*"the verification layer … measured against a specific campaign's history
rather than the 1M bar"* — and this module is that handed-over layer.

The published figure is not an input
------------------------------------

:class:`providers.DepthModel` carries ``context_tokens``: the window a rate card
or spec sheet states.  **This module never reads it.**  That is the feature's
whole content — the criterion must not run on the published number — and it is
why the two records are separate types with no field in common except the model
name.  A caller holding a :class:`DepthModel` is holding a *candidate*, and a
:class:`ServedContextLimit` is what a *deployment* answers when asked what it
serves; the gate takes the second and has no way to reach the first.

This is also why there is **no upper-bound cross-check** against the published
figure.  Refusing a verified measurement because it exceeds what the card
claims would put the published number back inside the criterion, and it would
fail in the worst direction: a stale registry entry would then refuse a
*correct* measurement, which is the opposite of what the sentence asks.  The
precedent for a stated fact doing real work here is feature 202's ``duration``
— the scheduler has no run length of its own to know, so the caller that knows
it states it — and the honest limit of that comparison is stated plainly rather
than papered over: **a caller can hand this gate a fabricated measurement.**  A
law that closed that gap would need a fact about the served model this module
does not hold (a probe transcript, a config hash); feature 206 closed its
analogous gap with a *recomputed code hash*, because there the whole input was
in the caller's hands.  Here the input is a number about a remote deployment,
so the gate reads the provenance the caller states and says in its message what
it did.

Why ``verified`` is a stated state and not a flag a caller forgets
------------------------------------------------------------------

The sentence's *rather than trusting a published figure* is only enforceable if
the two states are **representable**, so :class:`ServedContextLimit` carries
``verified`` as a **strict ``bool`` with no default**.  A field that defaulted
to ``True`` would make the published figure admissible by omission — a caller
who read a spec sheet and never probed anything would pass the gate by saying
nothing, which is the §14.1 trap arriving through a default.  A field that
defaulted to ``False`` would make the honest flat case awkward and would still
be a state a caller did not choose.  So the state is *required*, and
:func:`published_figure` exists to name the refused one at the call site — the
:func:`providers.flat_pricing` move, for the same reason: the null is
load-bearing, and a caller who has only the marketing number should have to
**say so**.

The shape of the criterion
--------------------------

The property is a conjunction — *a verified served limit* **and** *at or above
the campaign's history* — so it fails in exactly two ways, and the order is a
decision rather than a convenience:

1. **shape** — the record's parts, then the history as a positive token count.
   A malformed description is the base
   :class:`~providers.DepthModelError`, not a named refusal, on the grounds
   :mod:`providers._depth_errors` states for its own trivia.
2. **verified?** — an unverified figure raises
   :class:`~providers.ServedContextUnverifiedError`.  **An unverified number
   cannot be compared at all**, so this is checked before the comparison and
   independently of it: a published figure that looks large enough is not a
   measurement that cleared the bar, and one that looks too small is not a
   measurement that failed it.
3. **at or above the history?** — ``served_tokens >= history_tokens``, refused
   as :class:`~providers.ServedContextBelowHistoryError`.  The boundary is
   "at least", the same one feature 198's bar keeps and for the same reason: a
   window that holds the history exactly holds the whole of it.

The answer is :class:`VerifiedServedContext` — the model, the served limit, the
history and the **headroom** between them.  The margin is derived and never
stored (the :attr:`providers.MeasuredCacheRate.hit_rate` discipline), and it is
the figure the refusals' own reasoning runs on: §14.1 argues in margins, where
a 1M window faces ~600K of late-call history, and a caller deciding whether a
campaign can grow three more rounds needs the slack, not a boolean.  That is
why the gate answers with a record rather than admitting a candidate unchanged.

What this feature deliberately does not do
------------------------------------------

* It does not **read the history**.  Its operand is the history's *size* in
  tokens, taken as the caller's declared figure.  Whether the history was read
  **in full** — every prior proposal, not a sample — is feature 206's law
  (:class:`signal_agent.ProposalHistory`), a different question about a
  different object, and a gate that tokenized proposals here would be the
  second spelling of a read the assembler already made.
* It does not **select on price**.  Feature 200 owns the cache-hit economics,
  and §14.1's ordering is that the window comes first because a model that
  physically cannot hold the history fails on physics, so what it would have
  cost never becomes relevant.
* It does not **dial anything**.  There is no probe, no HTTP, no config read:
  the served limit arrives as a fact the caller states, which is what makes
  this criterion free and runnable before any call is placed.

Recognition across the workspace's double import
------------------------------------------------

Every entry point recognises a caller's measurement **by its parts, not its
class**, and re-makes it from this module's class — the move
:func:`providers.require_depth_model` makes for candidates, for the same
load-bearing reason: the module loader imports every member twice (once by file
path under ``_nullius_scanned_<dir>``, once as the importable member), so two
``ServedContextLimit`` classes exist over one source file, a dataclass's
generated ``__eq__`` answers ``False`` between them for every value, and an
``isinstance`` gate would refuse the very record the caller legitimately built.
Anything carrying the three parts is the measurement; the answer is always this
module's classes, so equality downstream means what it says.

Stdlib-only, like the rest of this tree: two ints, a string, a ``bool``, and
the rule that compares them to a caller's declared history.  No provider is
dialed, no price list is read, and the gate runs before any call is placed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ._depth import LARGE_HISTORY_FROM_DEPTH
from ._depth_errors import (
    DepthModelError,
    ServedContextBelowHistoryError,
    ServedContextUnverifiedError,
)

__all__ = [
    "UNVERIFIED_SERVED_LIMIT",
    "ServedContextLimit",
    "VerifiedServedContext",
    "published_figure",
    "require_served_context",
]

#: The value ``verified`` holds when the figure is a **published number** — the
#: marketing figure off a spec sheet or rate card — rather than a limit the
#: deployment was observed to serve.  A named ``False`` so the refused state has
#: a spelling at every call site (:func:`published_figure`), the
#: :data:`providers.FLAT_AT_ANY_CONTEXT` move for the same reason: the null is
#: load-bearing, and a caller who has only the card should have to say so
#: rather than leave a flag out.
UNVERIFIED_SERVED_LIMIT: bool = False

#: The parts a measurement is recognised by, in declaration order.  Declared as
#: data because the duck-typed recognition below iterates it and the suite pins
#: the record's surface by it, so a field added to the record is a field the
#: recognition and the tests notice rather than one only the constructor knows
#: about — the discipline :data:`providers._depth._DEPTH_PARTS` keeps.
_SERVED_PARTS: tuple[str, ...] = ("model", "served_tokens", "verified")


def published_figure() -> bool:
    """The ``verified`` of a context figure that was **not** measured.

    Returns ``False`` (:data:`UNVERIFIED_SERVED_LIMIT`), and exists so the
    refused state has a *name* at every call site —
    :func:`providers.flat_pricing`'s move, for the same reason.
    ``ServedContextLimit("ornith-1.5-35b-a3b", 1_000_000, False)`` and
    ``ServedContextLimit("ornith-1.5-35b-a3b", 1_000_000,
    published_figure())`` pass the same value, and that is the point: the two
    read differently to a person, and the second says *I know this is the
    card's number* while the first may be a flag the caller never considered.

    It is worth a function because the distinction is the feature.
    Architecture §14.1 does not prefer the measurement, it instructs the
    reader to *"verify the served context limit (``--max-model-len``), not the
    marketing number"*, and the two figures differ in kind: a card states what
    a model *can* do, and ``--max-model-len`` states what the process actually
    serving the calls *has been configured to* do.  A self-hosted deployment
    is the case that makes it concrete — the checkpoint's card may advertise a
    million tokens while the vLLM config serves 262K — and §14.1's own 256K
    clause is that gap's consequence.

    Returns ``False`` rather than a sentinel object so the value compares the
    way every reader of a boolean already reads it, and so the record stays
    constructible from plain config data.
    """
    return UNVERIFIED_SERVED_LIMIT


def _require_model_name(value: object) -> str:
    """Return ``value`` as a measured model's name, refusing anything else.

    Shape only — whether the named model may serve a campaign is the gate's
    question, and a name this function refuses is a name no campaign could
    ask about.  Left as :class:`DepthModelError` (the base) rather than a
    subclass, on the grounds :mod:`providers._depth_errors` states for its own
    trivia: a malformed description is not a failed criterion, and the
    taxonomy splits by question rather than by call site.

    Stripped of surrounding whitespace, the canonicalization
    :func:`providers._batch._require_provider_name` applies to its own lookup
    key and for the same reason: this name is what a refusal quotes back and
    what a deployment matches a served process against, so a name carried with
    a config file's stray spaces is one name, not two.
    """
    if not isinstance(value, str):
        raise DepthModelError(
            f"a served context limit's model must be a string, got {value!r} "
            f"({type(value).__name__}). Feature 199 judges whether the limit a "
            f"deployment serves can hold a campaign's history, and the "
            f"measurement is *of a model* — a non-string is not a name any "
            f"refusal could quote back to the caller who offered it."
        )
    if not value.strip():
        raise DepthModelError(
            f"a served context limit's model must be a non-empty string, got "
            f"{value!r}. A measurement that names no model cannot be checked "
            f"against a campaign's history — a refusal of nothing in particular "
            f"is not an answer a caller can act on, and an admission of nothing "
            f"in particular would be a model the campaign never actually "
            f"served."
        )
    return value.strip()


def _require_token_count(value: object, field: str, what: str) -> int:
    """Return ``value`` as a positive token count, refusing anything else.

    One guard for the record's counted field and the gate's history argument,
    because they fail the same way and owe the caller the same explanation:
    both are input-token counts — a window a deployment serves, a history a
    campaign has accumulated — and both refuse non-ints, ``bool`` (an ``int``
    subclass in Python, and one a config layer can hand over by accident), and
    non-positive values.  A count of zero or below is refused as *data
    nonsense* rather than as a failed comparison: a served window of zero
    tokens and a history of zero tokens are not values one of which is smaller
    than the other, they are descriptions that cannot be compared at all, and
    reading either as merely too small would hide the malformation inside a
    criterion it does not belong to.

    The same split :func:`providers._depth._require_token_count` makes, and
    deliberately a separate function from it: each module states its own
    contract (:func:`providers._cache._validated_campaign_id`'s precedent), so
    this one's refusals name this feature's question rather than feature 198's
    bar.
    """
    if not isinstance(value, int) or isinstance(value, bool):
        raise DepthModelError(
            f"{field} must be an int — {what} — got {value!r} "
            f"({type(value).__name__}). Token counts are what feature 199's "
            f"verification compares, and a count that is not a count cannot be "
            f"held against a campaign's history: guessing an interpretation "
            f"would be admitting or refusing a model nobody measured."
        )
    if value <= 0:
        raise DepthModelError(
            f"{field} must be a positive token count, got {value:,}. "
            f"{what.capitalize()}, and a count of zero or fewer tokens "
            f"describes nothing to hold against anything — not one count too "
            f"small for the other (that refusal is the gate's, and it names "
            f"both) but a description that cannot be checked at all."
        )
    return value


def _require_verified(value: object) -> bool:
    """Return ``value`` as whether the figure is a served limit, refusing the rest.

    A **strict ``bool``**, checked by identity rather than by ``isinstance``
    alone, because ``bool`` is an ``int`` subclass in Python and a config layer
    can hand over ``1`` or a truthy string by accident: accepting either would
    let a coerced value decide the one question the feature turns on.  The same
    guard :func:`providers._batch._require_availability` applies to its own
    stated boolean, and for the same reason — this is a **state a caller
    states**, not a flag it forgets.

    There is deliberately no default on :class:`ServedContextLimit.verified`.
    A default of ``True`` would admit the published figure by omission, which
    is the §14.1 trap arriving through a constructor signature; a default of
    ``False`` would still be a state nobody chose.  The caller must say, and
    :func:`published_figure` is how it says the refused one.
    """
    if value is not True and value is not False:
        raise DepthModelError(
            f"a served context limit's verified must be a bool (True or "
            f"False), got {value!r} ({type(value).__name__}). Whether a window "
            f"was measured or read off a spec sheet is the one fact feature 199 "
            f"turns on — architecture §14.1: *verify the served context limit "
            f"(--max-model-len), not the marketing number* — and a value that "
            f"is neither True nor False cannot state it, so it would be read as "
            f"one of the two by a coercion the caller never chose."
        )
    return value


@dataclass(frozen=True)
class ServedContextLimit:
    """What a deployment serves for one model: a window and its provenance.

    The three facts this feature's criterion reads, and no others: the
    ``model``'s name, the ``served_tokens`` limit the deployment was observed
    to attend over, and ``verified`` — ``True`` when that figure is a served
    measurement (a ``--max-model-len`` the process is actually running under),
    :data:`UNVERIFIED_SERVED_LIMIT` (``False``, best spelled
    :func:`published_figure`) when it is the published marketing number.

    Construction validates *shape* — the name is a non-empty string, the count
    is a positive int, ``verified`` is a strict ``bool`` — and deliberately not
    the comparison: a measurement of a 262K served window is a well-formed
    measurement, because describing a limit is not judging it against a
    campaign.  §14.1's own registry serves such a window for early-depth nodes,
    narrow campaigns and the bootstrap worlds, and those roles state their
    measurement with this record too.  Whether it may serve a *particular*
    campaign is :func:`require_served_context`'s question, asked with the
    history in hand — the record/gate split feature 198 states for
    :class:`providers.DepthModel`.

    **``verified`` has no default.**  It is the feature's subject rather than a
    detail of the record, and a default would answer it silently; see
    :func:`_require_verified`.

    Frozen and value-equal for the reasons this package's other records are: a
    measurement is an observation, not a field a caller tunes, and equality by
    value is what lets a suite — and a caller auditing which model served which
    campaign — compare a measurement to the one a probe produced without
    holding the same object.
    """

    model: str
    served_tokens: int
    verified: bool

    def __post_init__(self) -> None:
        # Shape only, field by field in declaration order, so a measurement
        # malformed in two places is refused for the first one a reader would
        # meet — the same ordering providers.DepthModel uses for its parts.
        # The comparison is the gate's, not here.
        object.__setattr__(self, "model", _require_model_name(self.model))
        object.__setattr__(
            self,
            "served_tokens",
            _require_token_count(
                self.served_tokens,
                "served_tokens",
                "the window of tokens the deployment actually serves",
            ),
        )
        object.__setattr__(self, "verified", _require_verified(self.verified))

    @property
    def is_verified(self) -> bool:
        """Whether the figure is a served measurement rather than a card's claim.

        A read of :attr:`verified` under the name a caller asks the question
        with, so a monitoring caller writes ``limit.is_verified`` rather than
        restating the feature's vocabulary, and a caller grepping for the
        refusal's cause finds the same word here.  Derived, never stored — the
        :attr:`providers.MeasuredCacheRate.hit_rate` discipline: there is one
        fact and this is its name, not a second copy of it.
        """
        return self.verified


@dataclass(frozen=True)
class VerifiedServedContext:
    """A verified measured limit that holds a campaign's history — the answer.

    What :func:`require_served_context` returns when it admits: the ``model``,
    the ``served_tokens`` limit that was verified, the ``history_tokens`` the
    campaign declared, and — derived, never stored — the ``headroom_tokens``
    between them.

    The answer is a record rather than the admitted measurement unchanged,
    because the admitted fact is a *relation*: the same measurement whose
    window clears one campaign's history fails another's, so a caller holding
    the pair knows which campaign the verification was made for.  It is the
    same reason :class:`providers.RoutedCall` answers with the rate multiple
    rather than a boolean — a caller that must account for the saving needs the
    number.

    ``headroom_tokens`` is the figure this feature's own reasoning runs on.
    §14.1 argues in margins — a one-million-token window facing roughly 600K of
    late-call history in a 500-node campaign (§14.2's own measurement: ~300K on
    the average depth call, beyond 600K on the late ones) — and the margin is
    what tells a caller whether the campaign can grow further rounds before its
    history outruns the window again.  It is non-negative by construction: a
    record of this type only exists past the gate.

    Construction validates the row's own arithmetic — both counts positive
    ints, the served limit never below the history it admitted — so a
    hand-built record cannot smuggle past a reader a pair the gate would have
    refused, the discipline :class:`providers.MeasuredCacheRate` keeps for its
    own two counts.

    Frozen, so an admission cannot be edited into a different one by a caller
    who kept a reference.
    """

    model: str
    served_tokens: int
    history_tokens: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "model", _require_model_name(self.model))
        object.__setattr__(
            self,
            "served_tokens",
            _require_token_count(
                self.served_tokens,
                "served_tokens",
                "the window of tokens the deployment actually serves",
            ),
        )
        object.__setattr__(
            self,
            "history_tokens",
            _require_token_count(
                self.history_tokens,
                "history_tokens",
                "the campaign's history as the caller declared it",
            ),
        )
        if self.served_tokens < self.history_tokens:
            raise DepthModelError(
                f"the verified served context of {self.model!r} is "
                f"{self.served_tokens:,} tokens, below the "
                f"{self.history_tokens:,}-token history it is recorded as "
                f"holding. This record only exists past feature 199's gate, so "
                f"the pair was not produced by it — and reading it back as an "
                f"admission would launder a refusal into the record a "
                f"campaign's fitness to run is audited by."
            )

    @property
    def headroom_tokens(self) -> int:
        """The tokens of window left over the campaign's history — the margin.

        Derived from the two counts the record carries and never stored beside
        them: the pair is the admission and this is the slack between it, the
        derived-not-stored split :attr:`providers.MeasuredCacheRate.hit_rate`
        makes, answered as the type that keeps it exact.  Non-negative by
        construction (see the class), and the number §14.1's own reasoning
        reads — how much further a campaign's history can grow before it
        outruns the window that just admitted it.
        """
        return self.served_tokens - self.history_tokens


def _candidate_parts_or_none(value: object) -> tuple[Any, ...] | None:
    """The three parts of ``value`` if it is shaped like a measurement, else ``None``.

    Recognition is structural — the three attributes :data:`_SERVED_PARTS`
    names, read on ``object.__getattribute__`` — rather than by class, because
    the module loader gives every member two class objects over one source file
    (see :func:`require_served_context`).  ``object.__getattribute__`` rather
    than ``getattr`` so an arbitrary object's ``__getattr__`` cannot fabricate
    a measurement: this function decides what may be checked against a
    campaign's history, and a hook that answered three parts would be a hook
    that offered a probe result.

    The parts are read whatever their types and handed to the constructor,
    which refuses a malformed one precisely — a stub carrying
    ``served_tokens="1M"`` is told its window is not an int, not that it is
    "not a measurement" — so recognition stays cheap and the validation stays
    single-sourced: there is one shape check, the record's own.
    """
    try:
        return tuple(object.__getattribute__(value, part) for part in _SERVED_PARTS)
    except AttributeError:
        return None


def require_served_context(
    limit: object,
    *,
    history_tokens: object,
) -> VerifiedServedContext:
    """Admit a model for one campaign's history, or refuse it — feature 199's gate.

    The question is the feature's own sentence read as a criterion: *does the
    context limit this deployment **verified it serves** hold **this
    campaign's** history?*  A measurement is admitted only if it is
    **verified** and its ``served_tokens`` is **at least** ``history_tokens`` —
    the boundary is "at least", the same one feature 198's fixed bar keeps and
    for the same reason: a window that holds the history exactly holds the
    whole of it.  The answer is a
    :class:`VerifiedServedContext` — the pair plus its margin — so a caller
    holds one record whatever it offered.

    ``history_tokens`` is the campaign's history size, **taken as an argument
    the caller states** rather than derived here.  The precedent is
    :func:`providers.choose_run_window`'s ``duration``: the scheduler *"has no
    length of its own to know"*, so the launcher that knows its own expected
    span states it — and this module has no tokenizer, no artifact reader and
    no business inventing one.  §14.1 reasons about the figure (*"at ~1k tokens
    per ``proposal.md`` plus its ``score.json``, a 500-node campaign carries
    roughly 500K tokens of history by the late rounds"*), and a module that
    baked that estimate in would be asserting a measurement about a campaign it
    has never seen.  So **this module carries no numeric bar at all** — the bar
    here is the campaign's own, and it changes per campaign — which is the
    sharpest contrast with feature 198, whose whole surface is a bar spelled as
    data.

    The refusals are the two ways the sentence's one property can be missing,
    and **the order is a decision**, not a convenience:

    * A figure that is not **verified** — the published marketing number, best
      spelled :func:`published_figure` — raises
      :class:`~providers.ServedContextUnverifiedError`.  This check comes
      first and is independent of the counts, because **an unverified number
      cannot be compared at all**: a card's claim that happens to look large
      enough is not a measurement that cleared the bar, and one that looks too
      small is not a measurement that failed it.  You cannot conclude *this
      deployment's served limit is below the history* from a spec sheet, and
      that inference is precisely what the sentence forbids.

    * A verified limit below the history raises
      :class:`~providers.ServedContextBelowHistoryError`, naming both counts —
      the difference between them is the margin the campaign would have to shed
      or the window it would have to gain, and that number is the repair.

    Anything that is not a measurement at all — a bare model string, a dict, a
    :class:`providers.DepthModel`, a ``None`` — is refused as the base
    :class:`~providers.DepthModelError` rather than guessed at.  A
    :class:`providers.DepthModel` in particular carries a **published**
    ``context_tokens`` and no served limit and no provenance: it is the very
    value this gate exists to refuse as evidence, and it is turned away for
    carrying none of the three parts rather than misread as a measurement.

    A measurement is recognised **by its parts, not its class**, and the answer
    is re-made from this module's classes.  The workspace's module loader
    imports every member twice — once by file path under
    ``_nullius_scanned_<dir>``, once as the importable member — so two
    ``ServedContextLimit`` classes exist over one source file, and a dataclass's
    generated ``__eq__`` answers ``False`` between them for every value.  An
    ``isinstance`` gate would therefore refuse the very record the caller
    legitimately built from the member, and a pass-through would return a value
    still carrying the other class, silently unequal to every record this
    module's answer is compared against.  Recognition by shape, answers in one
    class — the same move :func:`providers.require_depth_model` makes for
    candidates, for the same reason.
    """
    parts = _candidate_parts_or_none(limit)
    if parts is None:
        raise DepthModelError(
            f"a served-context measurement must be a ServedContextLimit "
            f"({', '.join(_SERVED_PARTS)}), got {limit!r} "
            f"({type(limit).__name__}). Feature 199 checks the limit a "
            f"deployment verified it serves against a campaign's history, and "
            f"a value that is not the record carries no measured window and no "
            f"provenance to check — padding the missing parts with guesses "
            f"would be admitting a model nobody measured."
        )
    # Re-made from the parts, never passed through: the offered class may be
    # the workspace's other copy (see above), and the constructor's shape
    # guard is the single validation — a stub's parts get checked here too.
    measured = ServedContextLimit(
        model=parts[0],
        served_tokens=parts[1],
        verified=parts[2],
    )
    history = _require_token_count(
        history_tokens,
        "history_tokens",
        "the campaign's history as the caller declared it",
    )
    if not measured.verified:
        raise ServedContextUnverifiedError(
            f"the context limit of {measured.model!r} is a published figure "
            f"({measured.served_tokens:,} tokens), not a verified served "
            f"limit. Architecture §14.1: *verify the served context limit "
            f"(--max-model-len), not the marketing number* — a card states "
            f"what a model can do, and ``--max-model-len`` states what the "
            f"process actually serving the calls has been configured to do, "
            f"which for self-hosted weights is routinely smaller (a 262K "
            f"server behind a checkpoint advertised at a million). Calls at "
            f"depth {LARGE_HISTORY_FROM_DEPTH} or greater carry the campaign's "
            f"whole history, so the "
            f"figure this role runs on has to be the one the deployment "
            f"serves: probe the served model and state what it answered, or "
            f"state the figure with published_figure() to refuse it here "
            f"deliberately. The "
            f"{history:,}-token history this campaign declared cannot be "
            f"checked against a number nobody measured."
        )
    if measured.served_tokens < history:
        raise ServedContextBelowHistoryError(
            f"a depth model must serve a context at least as large as the "
            f"campaign's history, got {measured.model!r} verified at "
            f"{measured.served_tokens:,} tokens against a "
            f"{history:,}-token history — short by "
            f"{history - measured.served_tokens:,} tokens. The C3 prompt reads "
            f"every prior proposal.md in full, so the history is the prompt: "
            f"at ~1k tokens per proposal plus its score.json a 500-node "
            f"campaign carries roughly 500K tokens of it by the late rounds, "
            f"and the average depth call carries ~300K with late calls beyond "
            f"600K (architecture §14.1, §14.2). A served window smaller than "
            f"the history physically cannot execute the defining prompt of "
            f"this system: such a model is confined to early-depth nodes, "
            f"narrow campaigns and the §10.6 bootstrap worlds, where histories "
            f"are short and self-contained — narrow the campaign or serve a "
            f"larger window."
        )
    return VerifiedServedContext(
        model=measured.model,
        served_tokens=measured.served_tokens,
        history_tokens=history,
    )
