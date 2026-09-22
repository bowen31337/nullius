"""The depth role's selection criterion — feature 198's gate.

app_spec.xml, "LLM Provider Tiering & Agent Pinning", feature 198: *System
rejects a depth model without a 1 million token context at flat pricing,
because calls at depth 2 or greater carry a large history.*  Feature 192
gives the deployment one seam every model call passes through; this module
is the criterion that decides which model may take the **depth half** of it
— and it is the reason the category is called *tiering* at all.  §14.1
splits the signal agent's calls by an asymmetry: at roots a weak model's
failure mode is convergence, which nothing downstream catches, so roots go
to a rotated frontier tier; at depth the work is narrow — given a mechanism
and a diagnostic, make a targeted change — and is verified downstream, so
depth goes to a cheap model.  Cheap is where the criterion earns its place,
because the cheap model still has to hold the whole campaign in its window.

Why one million, and why flat
-----------------------------

The C3 prompt requires reading every prior ``proposal.md`` **in full** — not
a sample, not recent cycles.  At ~1k tokens per proposal plus its
``score.json``, a 500-node campaign carries roughly 500K tokens of history
by the late rounds; §14.2 measures the **average** depth call at ~300K
tokens of context and late calls beyond 600K.  A one-million-token window is
the bar that covers those calls, and §14.1's role table states it as the
depth tier's own line — *min context 1M* — while §14.1's prose gives the
reason the bar is hard: *"a model with a 256K window physically cannot
execute the defining prompt of this system in a mature wide campaign."*

Flat pricing is the other half of the same requirement, because a window
the model can hold is worthless at a price the campaign cannot afford to
pay at volume.  §14.2's surcharge table lists the providers whose rate cards
reprice the **entire request** above an input threshold — 272K on OpenAI's
tiers, 200K on Gemini Pro — and both thresholds sit *under* the modal depth
call.  The trap is spelled out: a cheap tier's headline $0.20/$1.20 becomes
$0.40/$1.80 for the whole request once history crosses 272K, which it does
by roughly node 220.  So the depth role's one property is a conjunction —
*a 1 million token context* **and** *at flat pricing* — and
:func:`require_depth_model` refuses a candidate missing either conjunct:
:class:`~providers.InsufficientContextError` for the window,
:class:`~providers.LongContextSurchargeError` for the pricing shape, the
window first, because a model that physically cannot hold the history fails
on physics and what it would have cost never becomes relevant.

The record describes; the gate admits
-------------------------------------

:class:`DepthModel` is a *candidate description*, not an admission: it
validates that its fields are a name, a positive token count and a threshold
or the flat case, and nothing more.  A 262K-window model constructs happily,
because describing one is not serving one — §14.1's registry lists exactly
such a model (the self-hosted tier) as the right choice for early-depth
nodes, narrow campaigns and the bootstrap worlds, and a record that refused
it at construction would leave those roles no way to name their model.  The
bar is the *gate's* to apply, against the role the gate is asked about;
:func:`require_depth_model` is where "may this model serve depth ≥ 2" is
asked and answered.  This is the same split :mod:`providers._pinning`
makes: :class:`~providers.ModelPin` validates the triple's shape, and the
store's refusal of a conflicting pin is a separate question asked with the
row in hand.

The flat case is stated, not omitted
------------------------------------

``surcharge_threshold`` is ``None`` for the flat case — no long-context
surcharge, flat at any context — and :func:`flat_pricing` exists so that
flatness is a decision a caller **states** rather than a field it forgets.
The precedent is :func:`providers.hosted_api_weights`, whose ``None`` is a
positive fact and whose function exists so the fact has a name at every call
site.  The two ``None``s carry the same discipline for the same reason: a
caller who writes ``surcharge_threshold=None`` may have *meant* flat, or may
have simply not thought about the field, and a rate card silently read as
flat when it was never checked is the trap §14.2 documents arriving through
the config file instead of the price list.

What this feature deliberately does not check
---------------------------------------------

The bar here is fixed and the facts are the candidate's own: the window and
the threshold *as declared*.  Two sibling features own the checks that
would be premature here.  Feature 199 — *rejects a depth model whose
verified served context limit is below the campaign history size, rather
than trusting a published figure* — is the verification layer: §14.1's
*"verify the served context limit (``--max-model-len``), not the marketing
number"*, measured against a specific campaign's history rather than the
1M bar.  It lives in :mod:`providers._served`, it reads a
:class:`~providers.ServedContextLimit` rather than a candidate, and its two
refusals join this module's base (:class:`~providers.DepthModelError`)
because they ask this gate's one question of a measured fact — so a caller
that runs both layers still writes one ``except``.  Feature 200 is the
cache-hit economics layer — §14.1's *select the depth model on cache-hit
price, not list price* — which is why this record carries no price at all:
a field this criterion does not read is a field that would drift, and the
price the depth role is selected on is not the list price in any case.

Recognition across the workspace's double import
------------------------------------------------

:func:`require_depth_model` recognises a candidate **by its parts, not its
class**, and re-makes it from this module's class — the same move
:func:`providers.require_agent_model_id` makes for pins, for the same
load-bearing reason: the module loader imports every member twice (once by
file path under ``_nullius_scanned_<dir>``, once as the importable member),
so two ``DepthModel`` classes exist over one source file, a dataclass's
generated ``__eq__`` answers ``False`` between them for every value, and an
``isinstance`` gate would refuse the very record the caller legitimately
built.  Anything carrying the three parts is the candidate; the answer is
always one class, so equality downstream means what it says.

Stdlib-only, like the rest of this tree: two ints, a string, an optional
third int, and the rule that compares them to a bar.  No provider is dialed,
no price list is read, and the criterion runs before any call is placed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ._depth_errors import (
    DepthModelError,
    InsufficientContextError,
    LongContextSurchargeError,
)

__all__ = [
    "FLAT_AT_ANY_CONTEXT",
    "LARGE_HISTORY_FROM_DEPTH",
    "MIN_DEPTH_CONTEXT_TOKENS",
    "DepthModel",
    "flat_pricing",
    "require_depth_model",
]

#: The bar the spec's sentence names — one million tokens of context.  §14.1's
#: role table states it as the depth tier's own line (*min context 1M*), and
#: it is the number that covers the history the role's calls carry: ~300K on
#: the average depth call, beyond 600K on the late ones, roughly 500K in a
#: 500-node campaign by the last rounds.  Spelled as data because the gate,
#: both refusal messages and the suite all read the same bar, and a bar two
#: places spell is a bar that can drift.
MIN_DEPTH_CONTEXT_TOKENS = 1_000_000

#: The depth whose calls carry the large history — the feature's own clause,
#: *"calls at depth 2 or greater"*.  §14.1's tiering puts roots (depth 0–1)
#: on the frontier rotation and everything from 2 down on the cheap tier, so
#: this is where the window stops being a convenience and becomes the
#: binding constraint.  Declared as data because the refusals quote it: a
#: caller told "depth 2 or greater" is told which calls the bar is for.
LARGE_HISTORY_FROM_DEPTH = 2

#: The value ``surcharge_threshold`` holds when the rate card is flat — no
#: long-context surcharge, at any context.  A named ``None`` so the flat case
#: is a fact a caller states (see :func:`flat_pricing`) rather than a field
#: it leaves out; the shape is §14.2's table's own "Flat at any context, to
#: 1M, on every tier" row.
FLAT_AT_ANY_CONTEXT: None = None

#: The parts a candidate is recognised by, in declaration order.  Declared as
#: data because the duck-typed recognition below iterates it and the suite
#: pins the record's surface by it, so a field added to the record is a field
#: the recognition and the tests notice, rather than one only the constructor
#: knows about.
_DEPTH_PARTS: tuple[str, ...] = ("model", "context_tokens", "surcharge_threshold")


def flat_pricing() -> None:
    """The ``surcharge_threshold`` of a rate card that is flat at any context.

    Returns ``None``, and exists so the flat case has a *name* at every call
    site.  ``DepthModel("deepseek-flash", 1_000_000, None)`` and
    ``DepthModel("deepseek-flash", 1_000_000, flat_pricing())`` pass the same
    value, and that is the point: the two read differently to a person, and
    the second says *this was checked* while the first may be a field the
    caller never thought about — which matters because an unchecked
    ``None`` read as flat is the §14.2 trap arriving through configuration
    rather than the price list.

    It is worth a function for the same reason
    :func:`providers.hosted_api_weights` is: the null is load-bearing.  §14.2
    distinguishes providers that are *"flat at any context, to 1M, on every
    tier"* from providers that reprice the whole request above a threshold,
    and the depth role is admitted only on the first kind.  ``None`` here is
    the positive claim *no threshold exists*, not the absence of a claim —
    and a caller who does not know which kind of rate card they hold does
    not have a flat one.

    Returns ``None`` rather than a sentinel object so the value compares the
    way every reader of an optional threshold already reads it (``is None``),
    and so the record stays constructible from plain config data.
    """
    return FLAT_AT_ANY_CONTEXT


def _require_model_name(value: object) -> str:
    """Return ``value`` as a candidate's name, refusing anything else.

    Shape only — whether the named model may serve the depth role is the
    gate's question, not the record's, and a name this function refuses is a
    name no role could ask about.  Left as :class:`DepthModelError` (the
    base) rather than a subclass, on the grounds
    :mod:`providers._pin_errors` states for its own trivia: a malformed
    description is not a failed criterion, and the taxonomy splits by
    question rather than by call site.
    """
    if not isinstance(value, str):
        raise DepthModelError(
            f"a depth model's name must be a string, got {value!r} "
            f"({type(value).__name__}). Feature 198 admits or refuses a "
            f"candidate for the depth role, and the candidate is named — a "
            f"non-string is not a name any refusal could quote back to the "
            f"caller who offered it."
        )
    if not value:
        raise DepthModelError(
            f"a depth model's name must be a non-empty string, got {value!r}. "
            f"A candidate that names no model cannot be checked against the "
            f"{MIN_DEPTH_CONTEXT_TOKENS:,}-token bar — a refusal of nothing "
            f"in particular is not an answer a caller can act on, and an "
            f"admission of nothing in particular would be a model the "
            f"campaign never actually selected."
        )
    return value


def _require_token_count(value: object, field: str, what: str) -> int:
    """Return ``value`` as a positive token count, refusing anything else.

    One guard for the record's two counted fields, because they fail the
    same way and owe the caller the same explanation: a window and a
    threshold are both input-token counts a rate card or a spec sheet
    states, and both refuse non-ints, ``bool`` (an ``int`` subclass in
    Python, and one a config layer can hand over by accident), and
    non-positive values.  A threshold of zero or below is refused as *data
    nonsense* rather than failed flatness: it says every request reprices,
    which is not a long-context threshold but a rate card this field has no
    shape for, and treating it as merely unflat would hide the malformation
    inside a criterion it does not belong to.
    """
    if not isinstance(value, int) or isinstance(value, bool):
        raise DepthModelError(
            f"a depth model's {field} must be an int — {what} — got "
            f"{value!r} ({type(value).__name__}). Token counts are what the "
            f"depth criterion compares, and a count that is not a count "
            f"cannot be compared to the {MIN_DEPTH_CONTEXT_TOKENS:,}-token "
            f"bar: guessing an interpretation would be admitting or refusing "
            f"a model nobody described."
        )
    if value <= 0:
        raise DepthModelError(
            f"a depth model's {field} must be a positive token count, got "
            f"{value:,}. {what.capitalize()}, and a count of zero or fewer "
            f"tokens is a rate card or a window that describes nothing — "
            f"not a candidate too small for the depth role (that refusal is "
            f"the gate's, and it names the bar) but a description that "
            f"cannot be checked at all."
        )
    return value


@dataclass(frozen=True)
class DepthModel:
    """A candidate for the depth role, as the model registry describes it.

    The three facts feature 198's criterion reads, and no others: the
    ``model``'s name, the ``context_tokens`` window it serves, and the
    ``surcharge_threshold`` its rate card reprices the whole request above —
    :data:`FLAT_AT_ANY_CONTEXT` (``None``, best spelled
    :func:`flat_pricing`) when there is no threshold and the card is flat at
    any context.  A threshold at or above the window it belongs to is legal
    and means flat through the whole window; the criterion below reads only
    whether a threshold sits under the bar.

    Construction validates *shape* — the name is a non-empty string, both
    counts are positive ints — and deliberately not the bar: a 262K-window
    model is a well-formed candidate, because describing one is not serving
    one.  §14.1's registry lists exactly such models for early-depth nodes,
    narrow campaigns and the bootstrap worlds, and those roles name their
    model with this record too.  Whether a candidate may serve the depth ≥ 2
    role is :func:`require_depth_model`'s question, asked with the role in
    hand.

    Frozen and value-equal for the reasons this package's other records are:
    a rate card is a fact about a provider's pricing, not a field a caller
    tunes, and equality by value is what lets a suite — and the sibling
    features that will select on this record — compare a candidate to the
    one the registry declares without holding the same object.
    """

    model: str
    context_tokens: int
    surcharge_threshold: int | None = FLAT_AT_ANY_CONTEXT

    def __post_init__(self) -> None:
        # Shape only, field by field in declaration order, so a candidate
        # malformed in two places is refused for the first one a reader
        # would meet — the same ordering :class:`providers.ModelPin` uses
        # for its parts.  The bar is applied by the gate, not here.
        object.__setattr__(self, "model", _require_model_name(self.model))
        object.__setattr__(
            self,
            "context_tokens",
            _require_token_count(
                self.context_tokens,
                "context_tokens",
                "the window of tokens the model can attend over",
            ),
        )
        if self.surcharge_threshold is not None:
            object.__setattr__(
                self,
                "surcharge_threshold",
                _require_token_count(
                    self.surcharge_threshold,
                    "surcharge_threshold",
                    "the input-token count above which the whole request reprices",
                ),
            )


def _candidate_parts_or_none(value: object) -> tuple[Any, ...] | None:
    """The three parts of ``value`` if it is shaped like a candidate, else ``None``.

    Recognition is structural — the three attributes :data:`_DEPTH_PARTS`
    names, read on ``object.__getattribute__`` — rather than by class,
    because the module loader gives every member two class objects over one
    source file (see :func:`require_depth_model`).  ``object.__getattribute__``
    rather than ``getattr`` so an arbitrary object's ``__getattr__`` cannot
    fabricate a candidate: this function decides what may be checked against
    the depth bar, and a hook that answered three parts would be a hook that
    offered a model.

    The parts are read whatever their types and handed to the constructor,
    which refuses a malformed one precisely — a stub carrying
    ``context_tokens="1M"`` is told its window is not an int, not that it is
    "not a candidate" — so recognition stays cheap and the validation stays
    single-sourced: there is one shape check, the record's own.
    """
    try:
        return tuple(
            object.__getattribute__(value, part) for part in _DEPTH_PARTS
        )
    except AttributeError:
        return None


def require_depth_model(candidate: object) -> DepthModel:
    """Admit a candidate for the depth ≥ 2 role, or refuse it — feature 198's gate.

    The question is the feature's own sentence read as a criterion: *may this
    model take the depth role's calls, which at depth
    :data:`LARGE_HISTORY_FROM_DEPTH` and greater carry a large history?*  A
    candidate is admitted only if it has **a 1 million token context at flat
    pricing** — the window at least :data:`MIN_DEPTH_CONTEXT_TOKENS`, and no
    surcharge threshold below that bar — and the answer is the candidate
    itself, re-made from this module's class, so a caller holds one
    :class:`DepthModel` whatever it offered.

    The refusals are the two ways the sentence's one property can be
    missing, and the window is checked first because the ordering is a
    decision: a model that physically cannot hold the history fails on
    physics (§14.1: *"a model with a 256K window physically cannot execute
    the defining prompt of this system in a mature wide campaign"*), and
    what it would have cost never becomes relevant.  A cheap tier that is
    short *and* surcharged is told the lack no pricing choice can repair.

    * A window below the bar — including the 262K self-hosted tier, which is
      the right model for early depth, narrow campaigns and the bootstrap
      worlds and is refused for this role only — raises
      :class:`~providers.InsufficientContextError`.

    * A threshold below the bar on a window that clears it — §14.2's
      whole-request repricing, whose 272K and 200K thresholds sit under the
      ~300K average depth call — raises
      :class:`~providers.LongContextSurchargeError`.  A threshold *at* the
      bar admits: repricing starts above it, so every token of the bar the
      role relies on is priced flat, which is the whole of what the
      criterion asks of the card.

    Anything that is not a candidate at all — a bare model string, a dict, a
    ``None`` — is refused as the base :class:`DepthModelError` rather than
    guessed at: feature 198 checks a described rate card against a bar, and
    a value carrying no description cannot be checked, only turned away.

    A candidate is recognised **by its parts, not its class**, and the
    answer is re-made from this module's class.  The workspace's module
    loader imports every member twice — once by file path under
    ``_nullius_scanned_<dir>``, once as the importable member — so two
    ``DepthModel`` classes exist over one source file, and a dataclass's
    generated ``__eq__`` answers ``False`` between them for every value.  An
    ``isinstance`` gate would therefore refuse the very record the caller
    legitimately built from the member, and a pass-through would return it
    still carrying the other class, silently unequal to every record this
    module's answer is compared against.  Recognition by shape, answers in
    one class — the same move :func:`providers.require_agent_model_id` makes
    for pins, for the same reason.

    This gate reads the candidate's *declared* window and threshold, and
    nothing else.  Verifying the served limit (§14.1's
    ``--max-model-len``, not the marketing number) and measuring it against
    a campaign's history is feature 199's layer —
    :func:`providers.require_served_context`, which takes a
    :class:`~providers.ServedContextLimit` and a declared history and shares
    this gate's base — and selecting on cache-hit input price is feature
    200's; a caller wanting those answers runs those checks, which is why
    this one states its facts rather than deriving them.
    """
    parts = _candidate_parts_or_none(candidate)
    if parts is None:
        raise DepthModelError(
            f"a depth-model candidate must be a DepthModel "
            f"({', '.join(_DEPTH_PARTS)}), got {candidate!r} "
            f"({type(candidate).__name__}). Feature 198 checks a described "
            f"rate card against the "
            f"{MIN_DEPTH_CONTEXT_TOKENS:,}-token bar, and a value that is "
            f"not the record carries no window and no threshold to check — "
            f"padding the missing fields with guesses would be admitting a "
            f"model nobody described."
        )
    # Re-made from the parts, never passed through: the offered class may be
    # the workspace's other copy (see above), and the constructor's shape
    # guard is the single validation — a stub's parts get checked here too.
    record = DepthModel(
        model=parts[0],
        context_tokens=parts[1],
        surcharge_threshold=parts[2],
    )
    if record.context_tokens < MIN_DEPTH_CONTEXT_TOKENS:
        raise InsufficientContextError(
            f"a depth model must serve at least "
            f"{MIN_DEPTH_CONTEXT_TOKENS:,} tokens of context, got "
            f"{record.model!r} at {record.context_tokens:,}. Calls at depth "
            f"{LARGE_HISTORY_FROM_DEPTH} or greater carry the campaign's "
            f"whole history — the C3 prompt reads every prior proposal in "
            f"full, so a 500-node campaign holds roughly 500K tokens of it "
            f"by the late rounds and the average depth call ~300K "
            f"(architecture §14.1, §14.2) — and a window smaller than the "
            f"history physically cannot execute the defining prompt of this "
            f"system. Context is a hard selection criterion, not a "
            f"spec-sheet line: such a model is confined to the roles whose "
            f"histories are short — early-depth nodes, narrow campaigns, "
            f"the bootstrap worlds — and may not serve the depth role."
        )
    if (
        record.surcharge_threshold is not None
        and record.surcharge_threshold < MIN_DEPTH_CONTEXT_TOKENS
    ):
        raise LongContextSurchargeError(
            f"a depth model's pricing must be flat through "
            f"{MIN_DEPTH_CONTEXT_TOKENS:,} tokens, got {record.model!r} "
            f"whose whole request reprices above "
            f"{record.surcharge_threshold:,} input tokens. Calls at depth "
            f"{LARGE_HISTORY_FROM_DEPTH} or greater carry a large history — "
            f"~300K tokens on the average call, beyond 600K on the late "
            f"ones (architecture §14.2) — so a threshold below the bar sits "
            f"under the modal depth call, not the tail, and the headline "
            f"rate is not the rate this role pays: §14.2's own example is a "
            f"cheap tier whose per-request price doubles once history "
            f"crosses 272K, which a wide campaign does by roughly node 220. "
            f"Pass surcharge_threshold=flat_pricing() only when the card is "
            f"genuinely flat at any context."
        )
    return record
