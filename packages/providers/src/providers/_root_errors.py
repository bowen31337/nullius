"""The failure modes of the frontier rotation at roots — feature 196.

app_spec.xml, "LLM Provider Tiering & Agent Pinning", feature 196: *System
persists the serving provider on every root-depth call routed to the rotated
frontier model tier.*  This module is the vocabulary of that refusal, and it
is a **seventh base class** in this package — one that deliberately shares no
ancestor with :class:`providers.ProviderError`,
:class:`providers.ModelPinError`, :class:`providers.DepthModelError`,
:class:`providers.DepthScheduleError`, :class:`providers.BatchRoutingError` or
:class:`providers.DepthCacheError`, for the same reason those six share none
with each other: a caller's ``except`` clause answers one question, and the
seven questions are different ones.

* :class:`~providers.ProviderError` answers *did the model call work?* —
  the seam's contract, violated by a provider that answered wrong.
* :class:`~providers.ModelPinError` answers *is this node's authoring
  record pinnable?* — a record that cannot be read as a model identity.
* :class:`~providers.DepthModelError` answers *may this model serve the
  depth role?* — a selection a deployment makes **before** any call is
  placed.
* :class:`~providers.DepthScheduleError` answers *when may this
  campaign's depth runs happen?*
* :class:`~providers.BatchRoutingError` answers *which endpoint does
  this call go to?*
* :class:`~providers.DepthCacheError` answers *what does the depth
  role's input cost, and what rate did this campaign measure there?*
* :class:`RootProviderError` answers *can this root call's serving
  provider be recorded at all — is it a provider the deployment
  declared it would rotate across, and is this the node the call
  authored?*

Why this is a seventh base and not a subclass of one of the six
--------------------------------------------------------------

The temptation is real in two directions, and both are wrong.

**Not under :class:`~providers.DepthModelError`.**  That base's own
docstring draws the line precisely: it answers *may this model serve the
depth role?* — and feature 196's subject is emphatically **not** the depth
role.  §14.1's tiering puts *roots* (depth 0–1) on the frontier rotation
and everything from depth 2 down on the cheap tier
(:data:`providers.LARGE_HISTORY_FROM_DEPTH`), which is why the sentence says
*root-depth* at all.  A deployment catching ``DepthModelError`` to learn its
cheap tier was refused must not have a frontier root call's provenance
answered in its place — that is exactly the collapse each of this package's
taxonomies refuses in its own docstring.

**Not under :class:`~providers.BatchRoutingError`.**  Feature 201's base
answers *which endpoint does this call go to?*, and its own docstring
reserves this ground from the other side, saying of its routing that it
*"does not persist.  Feature 196 records the serving provider … this
feature's decision is a property of a single call, and the call's own record
is where it would belong."*  Both features are about one call; they ask
different questions about it.  A routing that could not find an offering has
decided nothing about *who served*, and a provenance that cannot be recorded
has nothing to say about *which endpoint* — so they are two questions and
therefore two bases, not one.

The genuinely close neighbour is :class:`~providers.ModelPinError`, and the
distinction between them is the sharpest thing this module has to state.
Feature 203 pins ``node.agent_model_id`` — the **triple** that authored the
node, written once, at the moment the node is authored.  Feature 196 records
the **serving provider** of each root call — which of the rotated families
took *this* call.  §14.1's rotation is the whole reason the two are not the
same fact:

    Different model families carry different priors and propose
    structurally different mechanisms, at zero incremental token cost, and
    it hedges outages.

A campaign whose roots rotate across three providers writes three different
providers' calls into one campaign, and the stratum an M3 comparison is
keyed on is *which family proposed this* rather than *which node* — the axis
feature 203's own docstring names when it says §14.1's root rotation *"proposes
across exactly this axis."*  Folding this under ``ModelPinError`` would make
``except ModelPinError:`` mean two things — *this node's author moved* and
*this call's author was not recorded* — and the two have different repairs
(backfill the triple, versus declare the rotation).

The base is also raised *directly*, for the failures no subclass describes: a
call offered with no honest way to be placed at roots, a depth that is not a
depth, a serving provider name that is blank or absent.  These are malformed
*descriptions* rather than failed *provenance*, and the move is the one
:class:`providers.DepthScheduleError` makes for a peak window carrying
seconds and :class:`providers.DepthCacheError` makes for a non-finite price:
a contract violation that is genuinely none of the named cases has no
subclass to wear, and minting one class per call site is how a taxonomy stops
describing anything.

The three refusals, and why there are exactly three
----------------------------------------------------

The feature's sentence is a **conditional on the call** — *every root-depth
call routed to the rotated frontier tier* — so it fails in exactly three
ways: the call is not a root call, its serving provider is not one the
campaign rotates across, and the node the call authored is not a row the tree
holds.

* :class:`UnrotatedCampaignError` — **the call was never one the sentence
  covers.**  This is the gate that keeps the conditional honest, and it is
  the reason this module raises at all on a call that merely *looks* fine.
  The tempting misreading of the sentence is that *every* call's serving
  provider should be recorded; it should not.  §14.1 rotates providers **at
  roots** and nowhere else — depth ≥ 2 is by construction *"one cheap model
  with a 1M context"*, deliberately single so the depth economics feature 200
  measures are attributable — so a call at depth 5 has one serving provider
  and no rotation to record.  A store that recorded it anyway would fill the
  provenance column with rows that all say the same thing, and the stratum
  the rotation exists to expose would be buried in them.  The refusal names
  the depth, the boundary and the two things the caller actually wanted:
  the depth model's own gate (feature 198) and the node's authoring triple
  (feature 203).

* :class:`UnknownRootProviderError` — **the serving provider is not one the
  rotation declared.**  The record's whole value is that it can be
  *believed*: a caller reading it back learns *this root was proposed by a
  different family than the last one*, and that inference only holds if the
  rotation's set is the closed vocabulary the value comes from.  A provider
  outside it is refused rather than stored, because the alternative — accept
  anything the completion reports — would let a silent re-route write itself
  into the provenance, which is precisely the §14.1 failure the whole
  category exists to end (*"DeepSeek retired ``deepseek-v4-flash`` … while
  continuing to accept the ID, silently serving V4.1-Flash"*).  The refusal
  names the provider, the campaign and every model the rotation does declare
  — the three things needed to repair it.

* :class:`RootNotRecordedError` — **the node the call authored is not a row.**
  A provenance record is a fact about a node the discovery tree holds: feature
  97's ``node`` table is the tree's, and its rows are the discovery tree's,
  not this member's.  Writing one for an id the tree does not hold would mean
  writing a row this member does not own — the same refusal
  :class:`~providers.NodeNotRecordedError` makes from feature 203's side, for
  the same reason and under this feature's base, because a caller catching
  ``RootProviderError`` must not have a pinning refusal answered in its
  place.

And one conflict, which is not a fourth *premise* failure but the state a
re-issue finds: :class:`RootProviderConflictError`, raised when a root node
that already records a serving provider is asked to record a different one.
One root call is one call, and the provider that served it is what it is.

Stdlib-only, like the rest of this tree: these errors describe a call that
was placed at roots and a provider a deployment declared, and nothing here
dials a provider, reads a rate card, or imports an SDK.
"""

from __future__ import annotations

__all__ = [
    "RootNotRecordedError",
    "RootProviderConflictError",
    "RootProviderError",
    "UnknownRootProviderError",
    "UnrotatedCampaignError",
]


class RootProviderError(Exception):
    """Base of the root-rotation provenance taxonomy — a root call's serving provider could not be recorded.

    One base class so a deployment's root-call recorder and a suite can
    catch every failure of feature 196's sentence — a call that is not a
    root call, a serving provider the rotation does not declare, a node
    the tree does not hold, a root already served by a different
    provider — with a single ``except``, the way
    :class:`providers.ProviderError` gives the call seam one handle and
    :class:`providers.ModelPinError` gives the authoring record one.  The
    base is deliberately unrelated to all six of the others: recording
    which provider served a root call is not a call that failed, not a
    node whose author cannot be named, not a depth model that was
    refused, not a window that could not be found, not an endpoint that
    went unchosen, and not a rate that was never measured — and a caller
    catching any of those must not have this answered in their place.

    Its nearest neighbour is :class:`providers.ModelPinError`, and the
    module docstring states the distinction in full: feature 203 pins
    *which model authored this node*, feature 196 records *which of the
    rotated families took this root call*.  A campaign rotating across
    three providers writes three providers into one campaign, which is
    the fact an M3 comparison stratifies on and the fact a node's author
    triple cannot express.

    Also raised directly for the malformations no subclass describes — a
    call offered with no campaign, a depth that is not a depth, a serving
    provider name that is blank or not a string — on the grounds the
    module docstring gives: those are bad *descriptions* rather than
    failed *provenance*, and the taxonomy splits by question, not by call
    site.
    """


class UnrotatedCampaignError(RootProviderError):
    """A depth call that is not a root call, offered for a serving-provider record.

    Feature 196's sentence is a conditional on the *call*: *"every
    **root-depth** call routed to the rotated frontier model tier"*.
    §14.1's tiering is what *root-depth* means — the role table puts the
    *"signal agent, roots (depth 0–1)"* on *"Frontier, **rotated across
    2–3 providers**"* and everything from depth 2 down on one cheap model
    with a 1M context — and the two tiers are not a continuum a record
    can be made over.  A depth call has **one** serving provider and no
    rotation to record; a store that recorded it anyway would fill the
    provenance column with rows that all say the same thing, and the
    stratum the rotation exists to expose would be buried among them.

    Raised by :meth:`providers.RootProviderRotation.record`, naming the
    depth it was handed and the boundary
    (:data:`providers.ROOT_TIER_MAX_DEPTH`), so the refusal tells the
    caller which tier its call belongs to rather than merely that the
    number was wrong.

    The repair is the other store, not the other provider: a depth call's
    model is chosen by feature 198's gate and its node's author is
    feature 203's triple.  What is never available is recording a depth
    call here, because the record would be true and useless — and a
    provenance table carrying rows nobody stratified on is a table an
    auditor has to filter before it can be read.
    """


class UnknownRootProviderError(RootProviderError):
    """A serving provider the campaign's root rotation does not declare.

    The record's whole value is that it can be *believed*: a caller
    reading it back learns *this root was proposed by a different family
    than the last one*, and §14.1 spends that inference as the cheapest
    mitigation the system has for the convergence failure mode —

        **Rotating providers at roots is the cheapest mitigation
        available** for the convergence failure mode.  Different model
        families carry different priors and propose structurally
        different mechanisms, at zero incremental token cost, and it
        hedges outages.

    — which only holds if the rotation's declared set is the closed
    vocabulary the recorded value comes from.  A provider outside it is
    refused rather than stored, because the alternative — accept
    whatever the completion reports — is exactly how §14.1's documented
    provenance failure arrives: *"DeepSeek retired ``deepseek-v4-flash``
    on 2026-09-10 while continuing to accept the ID, silently serving
    V4.1-Flash.  See §14.1 — this is the provenance failure, not a
    hypothetical."*  A record that accepted an undeclared provider would
    write that re-route into the provenance as though a human had chosen
    it.

    Raised by :meth:`providers.RootProviderRotation.record` **before any
    row is written**, naming the provider, the campaign and every model
    the rotation does declare — the three facts a repair needs.

    The repair is the rotation, not the record: add the provider to the
    campaign's declared set if it genuinely belongs in the rotation, or
    serve the call from one that is already declared.  What is never
    available is recording a provider the deployment did not agree to
    rotate across, because then the set the stratum is keyed on is the
    set of whatever the providers happened to answer.
    """


class RootNotRecordedError(RootProviderError):
    """A node the discovery tree does not hold, offered as a root call's author.

    A serving-provider record is a fact about a node: which of the
    rotated families proposed *this* node's mechanism.  The node is a row
    of feature 97's ``node`` table — the discovery tree's, not this
    member's — and a record written for an id the tree does not hold
    would mean writing a row this member does not own.  The refusal is
    the same fact :class:`~providers.NodeNotRecordedError` states from
    feature 203's side, spelled for this feature's base rather than
    shared with the pin store's, because a caller catching
    ``RootProviderError`` to learn its provenance was refused must not
    have a pinning refusal answered in its place — the taxonomy splits by
    question even where the premise is the same one.

    Raised by :meth:`providers.RootProviderRotation.record`, and named
    for the node it was handed, so the caller learns which id is missing
    rather than which store it asked.

    The repair is the tree, not the record: expand the root first
    (feature 239), then record the provider that proposed it.  A record
    written ahead of its node would be a provenance row for a mechanism
    nobody authored.
    """


class RootProviderConflictError(RootProviderError):
    """A root node already served by a declared provider, recorded again as another.

    One root call is one call, and the provider that served it is what it
    is: the §14.1 rotation assigns each root call to one family, and the
    assignment is the fact the stratum is read off.  Re-issuing the
    **identical** record returns the stored one — a retry is the same
    record arriving twice, and the row is the fact — while recording a
    *different* provider against the same root claims one call was served
    by two families, which is not an update but a contradiction.  Raised
    by :meth:`providers.RootProviderRotation.record`, naming both
    providers, the campaign and the node, the same shape
    :class:`~providers.ModelPinConflictError` gives a triple pinned twice
    and :class:`~providers.CacheRateConflictError` gives a rate measured
    twice — because the caller learns which value is stored and which it
    asked for, and that is the difference between an actionable refusal
    and a complaint.

    The repair is to read the stored record
    (:meth:`.RootProviderRotation.get`) — or, if the root genuinely was
    proposed twice under two families, to record the second proposal as
    its own node, so each record names one call.
    """
