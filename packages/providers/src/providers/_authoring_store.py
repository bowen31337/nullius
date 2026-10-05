"""The authoring addition's persistence door — one record, three stores.

additions_spec_llm_authoring.xml, "Authoring Foundation", feature 4: *System
persists authoring provenance with ``providers.record_authoring(record, *,
database_url=None, env=None)`` once the record's node row exists.  It also
persists a campaign's measured depth cache hit rate with
``providers.record_campaign_cache_rate(campaign_id, records, *,
database_url=None, env=None)``.*

The addition's first three features are one chain and this module is the link
that closes it.  Feature 2 (:mod:`providers._authoring`) states what a
deployment authors with and defines the record; feature 3
(:mod:`providers._authoring_session`) binds the config's pins to the three
call sites and answers the provider a call is placed through; and this
feature is what the record is *for*: the call happened, the node row already
exists — the spec's own premise, and the reason the door asks the tree
nothing before writing — and the author, the dice and, for a root, the
serving family must land in the tables the addition's readers already read.
A record that stays in the caller's hands is provenance the next reader has
to take on faith: the model-stratum ablation reads ``agent_model_id``, §14.1's
rotation is only readable from rows that landed, and feature 200's rate only
measures usages somebody handed it.

Why a door, when every fact already has a store
-----------------------------------------------

Every fact this feature files is already owned: the pin by
:meth:`providers.AgentModelPins.persist` (feature 203), the weights and dice
by :meth:`providers.AgentModelPins.persist_weights` (feature 204), the root's
assigned and serving family by
:meth:`providers.RootRotation.record_root_provider` (features 197 and 196),
and the depth tier's cache hit rate by :meth:`providers.DepthCacheRates.measure`
(feature 200).  This module owns **no table, no schema and no new fact** — it
exists because the *order* and the *routing* of those writes are themselves a
decision the addition must state once, rather than one each caller re-derives:

* **The pin lands before the weights.**  ``persist_weights`` refuses a node
  row with no ``agent_model_id`` (:class:`~providers.NodeProvenanceError`,
  the store's own law), so this is not a preference: the author is the
  premise of the weights record, exactly as 0115's column order states.
* **The trio lands before the root pair.**  The author on the node row is
  the fact every reader of the tree is owed, and it is written even when
  the rotation's half then refuses — a serving family the rotation did not
  assign arrives *after* the author is on the row, the same stance
  :meth:`providers.RootRotation.record_root_provider` takes for its own two
  halves (*"the assignment is this feature's fact and it was decided; what
  failed is the provenance of a call that disagrees with it"*).
* **The role routes the root pair.**  A root record also files the rotation
  and provenance pair, because feature 197's rotation is a fact about roots;
  a depth record writes no root row, because the depth role is §14.1's
  single-model tier — one pin, no rotation to record; a policy record writes
  no root row, because dreaming's revisions are not tree nodes at all.

The order has one more consequence worth stating plainly: **nothing here is
a transaction.**  Three stores over three tables cannot be wrapped by a
caller that does not own them, and the idempotence below is what makes the
sequence safe to retry rather than something a wrapper could buy back.

Idempotent by construction, not by coordination
-----------------------------------------------

*Recording the same record twice is idempotent* — the spec's own sentence,
and a property every composed store already owns for its own ask: the
identical pin answers the stored row, the identical weights answer the stored
row, the identical assignment and provenance answer the stored rows, and the
identical totals answer the stored measurement — each with
``recorded=False`` and the original instants, which a retry does not move.
This door adds no state of its own — no memo, no lock, no already-filed flag
— because a door that remembered what it had filed would be a second
spelling of the rows the stores already hold, kept in sync by nobody.  The
retry is answered by the stores, and the answer is the row.

The refusals, and whose they are
--------------------------------

Almost every refusal here is **a store's own, propagated unchanged** — the
spec's word.  A node row the tree does not hold is the pin store's
:class:`~providers.NodeNotRecordedError`, verbatim; a stored triple that
disagrees with the record's pin is :class:`~providers.ModelPinConflictError`;
a family the rotation did not assign is
:class:`~providers.UnassignedRootProviderError`; an unplanned campaign is
:class:`~providers.UnplannedCampaignError`; a re-measurement that totals
differently is :class:`~providers.CacheRateConflictError`.  Each already
names the fact precisely, and re-wrapping one in this feature's vocabulary
would put a second, vaguer sentence in front of the one an operator needs.

Two refusals are this module's own:

* **The record's guards.**  The record is recognised **by its parts** and
  re-made through :class:`providers.AuthoringRecord` — the double-import
  remedy every seam in this package makes, because the module loader gives
  every member two class objects over one source file — and the re-making
  runs every guard feature 2 states: the closed role set, the pin's parse,
  the four settings, the summed usage, the tier.  A malformed record leaves
  as :class:`~providers.AuthoringConfigError`, feature 2's vocabulary,
  because the record is feature 2's value.
* **Nothing names a store.**  Refused *by name*, on the
  :func:`providers.record_root_provider` / :func:`providers.measure_cache_rate`
  precedent: ``record_authoring`` refuses with the base of the store it
  writes through first (:class:`~providers.ModelPinError`) and
  ``record_campaign_cache_rate`` with the measurement store's own
  (:class:`~providers.DepthCacheError`), each naming
  :data:`DATABASE_URL_ENV` and never quoting its value — because a
  provenance write that quietly skipped would leave a tree whose nodes carry
  no author, and a campaign whose measured rate nobody recorded.

The depth role's rate, and only the depth role's
------------------------------------------------

The sentence's second half is a measurement, and a measurement is only as
good as its filter.  ``record_campaign_cache_rate(campaign_id, records)``
passes **the usage of every depth-role record of that campaign** — and
nothing else — to :meth:`providers.DepthCacheRates.measure`, and answers the
:class:`~providers.MeasuredCacheRate`.  Records of other campaigns, and root
or policy records of this one, are ignored, for the reason the architecture
gives for measuring the rate at all: *"the saving comes almost entirely from
the depth role's cache-hit rate"* (§14.2, on the cost correction), because
*"the depth role's cost is almost entirely re-reading a large, append-only,
stable prefix"* — so the figure selects the depth model (*"select the depth
model on cache-hit price, not list price"*), and a rate diluted by the
roots tier's spend, or by dreaming's revisions, would be a rate about calls
the selection logic never makes.  Repeating the call answers the same row,
because ``measure``'s own idempotence answers identical totals with the
stored ``measured_at`` untouched.

The filter compares **canonical** campaign ids — the discipline every store
in this member applies to the keys it joins by — so a record carrying a
mixed-case spelling of the campaign belongs to it as surely as the planted
row does.  A depth record whose campaign id cannot be canonicalised at all
is refused rather than silently dropped: *"ignored"* is for records that are
provably of another campaign or of another role, and a depth record whose
campaign names no campaign is a record the filter cannot make a decision
about — a measurement that quietly excluded it would under-count the spend
the depth tier actually made.

Like the rest of this member: stdlib only, one file, and no builder — the
campaign driver that calls the author and the reviser in a loop is a later
feature's spec, and until then a caller wires these doors as that feature
does.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterable, Mapping
from typing import Any, Final

from ._authoring import AUTHORING_ROLES, AuthoringConfigError, AuthoringRecord
from ._cache import DepthCacheRates, MeasuredCacheRate
from ._cache_errors import DepthCacheError
from ._ckpt import HOSTED_API_CKPT_HASH
from ._pin_errors import ModelPinError
from ._pin_store import AgentModelPins, AgentWeights, NodePin
from ._root import FrontierProvider, RootCall, RootCallProvider
from ._rotation import RootAssignment, RootRotation

__all__ = ["record_authoring", "record_campaign_cache_rate"]

#: The environment variable naming the relational store — the one spelling every
#: store in this workspace uses, restated here (not imported from a sibling) so
#: this module states its own contract, the discipline every module in this
#: member follows even where a neighbour declares the same name.
DATABASE_URL_ENV = "DATABASE_URL"

#: The role whose records carry the rotation, as a name rather than an index
#: into :data:`~providers.AUTHORING_ROLES`: the spec's own sentence routes on
#: it (*"for a root record it also calls … a depth or policy record writes no
#: root row"*), and the suite pins the tuple's order
#: ``("root", "depth", "policy")`` so the two spellings cannot drift apart.
ROOT_ROLE: Final[str] = AUTHORING_ROLES[0]

#: The role whose usage the campaign's cache rate is measured from — §14.2's
#: own tier, held by name the same way :data:`ROOT_ROLE` is.
DEPTH_ROLE: Final[str] = AUTHORING_ROLES[1]

#: The parts an authoring record is recognised by: the three tree facts, the
#: role, the pin, the dice, the spend, the serving model and the declared tier —
#: :class:`providers.AuthoringRecord`'s own nine fields, restated here (not
#: read off the dataclass) so the recognition is a statement of this module's
#: and a field added to the record is a deliberate edit to this seam, not a
#: silent widening.
_RECORD_PARTS: Final[tuple[str, ...]] = (
    "node_id",
    "campaign_id",
    "depth",
    "role",
    "pin",
    "sampling",
    "usage",
    "served_model",
    "tier",
)


def _resolved_url(
    database_url: str | None, env: Mapping[str, str] | None
) -> str:
    """The store's URL, or ``""`` when nothing names one.

    The resolution order the module-level doors of this member share
    (:func:`providers.record_root_provider`, :func:`providers.measure_cache_rate`):
    ``database_url`` wins outright, else :data:`DATABASE_URL_ENV` read from
    ``env`` — or from :data:`os.environ` when ``env`` is ``None``, the idiom
    every resolver here follows — with an empty or whitespace-only value
    counting as unset.  The empty string is the caller's signal to refuse by
    name; stripping the value happens here so the caller never has to.
    """
    if database_url is not None:
        return database_url
    source = os.environ if env is None else env
    return source.get(DATABASE_URL_ENV, "").strip()


def _record_from_parts(value: object, what: str) -> AuthoringRecord:
    """Re-make an authoring record from its parts, refusing anything else.

    Recognition **by its parts** — the nine attributes
    :data:`_RECORD_PARTS` names, read on ``object.__getattribute__`` — rather
    than by class, because the module loader imports every member twice (once
    by file path, once as the importable member), so an ``isinstance`` gate
    would refuse the very record a caller legitimately built through the
    member's other copy.  The answer is re-made through
    :class:`providers.AuthoringRecord`, which re-runs every guard feature 2
    states and re-makes the nested pin, dice, usage and tier from this
    package's classes — so what the stores below are handed is this module's
    value, validated by the one path the record has.
    """
    try:
        parts = {
            part: object.__getattribute__(value, part) for part in _RECORD_PARTS
        }
    except AttributeError:
        raise AuthoringConfigError(
            f"{what} must be an AuthoringRecord "
            f"({', '.join(_RECORD_PARTS)}), got {value!r} "
            f"({type(value).__name__}). The record is what one authoring call "
            "leaves behind — the node it authored, the pin that served, the "
            "dice it rolled, the spend it made — and a value carrying none of "
            "those names no authoring, so there is nothing to persist and no "
            "column to persist it into. Build the record with "
            "providers.AuthoringRecord, or file the value the session that "
            "made the call appended to its records."
        ) from None
    return AuthoringRecord(**parts)


def _validated_campaign(value: Any, what: str) -> str:
    """Canonical UUID text for a campaign id, refusing anything else.

    The store's own law, restated at this seam for the one value the filter
    must compare before the store ever sees it: the campaign id keys the row
    :meth:`providers.DepthCacheRates.measure` writes, and
    :func:`providers._cache._validated_campaign_id` would refuse the same
    value for the same reason a heartbeat later — an id that cannot be
    canonicalised names no campaign the campaign table could hold.  Refusing
    it here, with this module's own sentence naming ``what`` the id came in
    as, means the caller learns it before any record is read rather than
    after all of them.
    """
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, str) and value.strip():
        try:
            return str(uuid.UUID(value.strip()))
        except ValueError:
            pass
    raise DepthCacheError(
        f"{what} {value!r} is not a UUID; a campaign's cache hit rate is "
        "measured per campaign, keyed by the id feature 104's campaign table "
        "holds, and an id that cannot be canonicalised names no campaign any "
        "measurement could belong to. Supply the id the campaign was planned "
        "under."
    )


# ── The door's first half: one record, three stores ───────────────────────────


def record_authoring(
    record: object,
    *,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[NodePin, AgentWeights, tuple[RootAssignment, RootCallProvider] | None]:
    """File one authoring record's provenance through the stores that own it.

    Feature 4's first sentence as one call: the record in, and its three (or
    four — a root record's rotation pair) facts landed in the tables their
    features own, each answered by the store's own record with its
    ``recorded`` flag saying whether *this* call wrote the row.  The answer is
    ``(node_pin, weights, root_pair)``, where ``root_pair`` is the
    ``(assignment, provenance)`` pair :meth:`providers.RootRotation.record_root_provider`
    answers for a root record and ``None`` for a depth or policy record — the
    routing the spec states as *"for a root record it also calls …; a depth or
    policy record writes no root row"*.

    The store is resolved from ``database_url``, else from
    :data:`DATABASE_URL_ENV` in ``env`` — or in :data:`os.environ` when
    ``env`` is ``None``; a deployment naming neither is refused by name
    (:class:`~providers.ModelPinError`, the base of the store this door
    writes through first) rather than silently skipping, because a node whose
    author never landed is a node the model-stratum ablation cannot place.
    The refusal names the variable and never quotes its value, the discipline
    the live registry's refusals keep for their own names.

    The record is recognised by its parts and re-made through
    :class:`providers.AuthoringRecord` (see :func:`_record_from_parts`), so a
    record built from the workspace's other copy of this member files through
    this module's classes, and a malformed one is refused by feature 2's own
    guards as :class:`~providers.AuthoringConfigError`.

    **The order of the writes is the module's other sentence, stated here
    because it is load-bearing:**

    1. ``AgentModelPins(url).persist(node_id, pin)`` — the author on the node
       row.  First, because the next call refuses a row with no author
       (:class:`~providers.NodeProvenanceError`, the store's own law), and
       because a node the tree holds but nobody authored is the one fact
       every reader below stands on.  A node row that does not exist is
       refused **here**, as the store's own
       :class:`~providers.NodeNotRecordedError`, unchanged — the spec's own
       sentence, and the door adds no wording of its own in front of it.
    2. ``persist_weights(node_id, HOSTED_API_CKPT_HASH, sampling=record.sampling)``
       — the dice beside the author, with the hosted-API checkpoint hash
       whose SQL ``NULL`` is the recorded fact that these weights live
       somewhere this system never hashed (§9.1: *non-null for self-hosted
       weights*).  The keyword is the spec's own spelling.
    3. For a root record, ``RootRotation(url).record_root_provider(
       RootCall(node_id, campaign_id, depth),
       FrontierProvider(pin.provider, pin.model), record.tier)`` — the
       assignment 197 computes and the provenance 196 writes, against the
       declared tier the record carries.  The call is made with the pin's
       family, and the session that drew the pin drew it by the same
       :func:`providers.rotation_index` arithmetic this gate re-runs, so a
       record the addition itself produced names the assigned family and the
       gate is a check, not a lottery.  A family it refuses
       (:class:`~providers.UnassignedRootProviderError`) arrives **after**
       the trio is on the row — see the module docstring for why that is the
       honest order.

    Nothing is wrapped and nothing is retried here: each store's refusal
    propagates unchanged, and each store's idempotence is what answers a
    re-recorded record — the same record filed twice answers all the same
    rows with ``recorded=False`` and moves no stored instant.
    """
    url = _resolved_url(database_url, env)
    if not url:
        raise ModelPinError(
            "record_authoring files an authoring record's provenance and "
            f"nothing names a store: {DATABASE_URL_ENV} is unset (and no "
            "database_url was supplied), so the record could not be filed. "
            "The record's author, dice and — for a root — serving family are "
            "facts that must actually land in the tables the three stores "
            "own, and a record that stays in the caller's hands is "
            "provenance the next reader has to take on faith: the "
            "model-stratum ablation reads agent_model_id (PRD §5a), and "
            "§14.1's rotation is only readable from rows that landed. Point "
            f"{DATABASE_URL_ENV} at the sqlite database the tree lives in, or "
            "pass database_url."
        )
    filed = _record_from_parts(record, "record_authoring's record")
    pins = AgentModelPins(url)
    node_pin = pins.persist(filed.node_id, filed.pin)
    weights = pins.persist_weights(
        filed.node_id, HOSTED_API_CKPT_HASH, sampling=filed.sampling
    )
    if filed.role != ROOT_ROLE:
        # The depth role is one single pin with no rotation to record and the
        # policy role's revisions are not tree nodes at all: neither has a
        # root row, and the None half of the answer states that — a caller
        # cannot mistake "no root row" for "the root row could not be read".
        return node_pin, weights, None
    root_pair = RootRotation(url).record_root_provider(
        RootCall(
            node_id=filed.node_id,
            campaign_id=filed.campaign_id,
            depth=filed.depth,
        ),
        FrontierProvider(filed.pin.provider, filed.pin.model),
        filed.tier,
    )
    return node_pin, weights, root_pair


# ── The door's second half: the depth role's rate ─────────────────────────────


def record_campaign_cache_rate(
    campaign_id: Any,
    records: Iterable,
    *,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> MeasuredCacheRate:
    """Measure and persist a campaign's depth-role cache hit rate.

    Feature 4's second sentence as one call: the campaign and the records the
    campaign's calls left behind in, the :class:`~providers.MeasuredCacheRate`
    out — feature 200's row, written for exactly the usages the sentence
    names: **the usage of every depth-role record of that campaign**, and
    nothing else.  Records of other campaigns, and root or policy records of
    this one, are ignored — each for its own reason (the module docstring
    states both), and the filter is what keeps the measured rate a fact about
    the depth tier's own spend: *"the saving comes almost entirely from the
    depth role's cache-hit rate"* (§14.2), and the figure selects the depth
    model on cache-hit price.

    The filter runs on canonical campaign ids, so a record carrying a
    mixed-case spelling of the campaign belongs to it; a depth record whose
    campaign id cannot be canonicalised is refused
    (:class:`~providers.DepthCacheError`, naming the record) rather than
    silently dropped — a measurement that quietly excluded it would
    under-count the spend the depth tier actually made.  A campaign id of the
    caller's own that cannot be canonicalised is refused the same way,
    before any record is read.

    Every entry is recognised by its parts and re-made through
    :class:`providers.AuthoringRecord`, so a malformed entry leaves as
    :class:`~providers.AuthoringConfigError` naming its position — feature
    2's vocabulary, because the record is feature 2's value, and the position
    because a caller holding a campaign's records needs to know which one to
    look at.

    The store is resolved exactly as :func:`record_authoring` resolves its
    own, and a deployment naming neither ``database_url`` nor
    :data:`DATABASE_URL_ENV` is refused by name with the measurement store's
    own :class:`~providers.DepthCacheError` — the
    :func:`providers.measure_cache_rate` precedent verbatim — rather than
    silently skipping, because a rate nobody recorded is a campaign the
    depth tier's selection has no figure for.

    What lands is the store's own law, unchanged: an unplanned campaign is
    :class:`~providers.UnplannedCampaignError`; a stream of no depth records
    is refused as *a measurement of no calls*; a usage whose cache read
    exceeds its input is refused; and a re-measurement that totals
    differently is :class:`~providers.CacheRateConflictError`.  Repeating the
    call with the same records answers the same row — ``recorded=False``,
    the stored ``measured_at`` untouched — because identical totals are
    feature 200's own idempotent ask, and this door adds no state of its own
    in front of it.
    """
    url = _resolved_url(database_url, env)
    if not url:
        raise DepthCacheError(
            "record_campaign_cache_rate measures a campaign's depth cache "
            f"hit rate and nothing names a store: {DATABASE_URL_ENV} is unset "
            "(and no database_url was supplied), so the measured rate could "
            "not be recorded. The rate keeps the depth tier cheap — §14.2 "
            "selects the depth model on cache-hit price — and a campaign "
            "whose rate nobody recorded is a campaign the selection has no "
            "figure for. Point "
            f"{DATABASE_URL_ENV} at the sqlite database the campaign lives "
            "in, or pass database_url."
        )
    campaign = _validated_campaign(campaign_id, "campaign_id")
    usages: list[Any] = []
    for position, entry in enumerate(records):
        filed = _record_from_parts(
            entry, f"records[{position}] (record_campaign_cache_rate's)"
        )
        if filed.role != DEPTH_ROLE:
            # Root and policy records are ignored by the sentence: the roots
            # tier's spend is not the depth tier's premise, and dreaming's
            # revisions are not calls the depth model made. Skipped before the
            # campaign is even compared, so a policy record's revision-scoped
            # campaign id is never asked to canonicalise.
            continue
        stated = _validated_campaign(
            filed.campaign_id, f"records[{position}].campaign_id"
        )
        if stated != campaign:
            continue
        usages.append(filed.usage)
    return DepthCacheRates(url).measure(campaign_id, usages)
