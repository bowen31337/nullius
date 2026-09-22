"""The failure modes of a campaign's root provider rotation — feature 197.

app_spec.xml, "LLM Provider Tiering & Agent Pinning", feature 197: *System
persists a per-campaign root provider rotation, so different model families
propose structurally different mechanisms.*  This module is the vocabulary of
that refusal, and it is an **eighth base class** in this package — one that
deliberately shares no ancestor with :class:`providers.ProviderError`,
:class:`providers.ModelPinError`, :class:`providers.DepthModelError`,
:class:`providers.DepthScheduleError`, :class:`providers.BatchRoutingError`,
:class:`providers.DepthCacheError` or :class:`providers.RootProviderError`, for
the same reason those seven share none with each other: a caller's ``except``
clause answers one question, and the eight questions are different ones.

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
* :class:`~providers.RootProviderError` answers *can this root call's
  serving provider be recorded at all?* — the **record** question,
  asked about one call after the fact.
* :class:`RootRotationError` answers *which family was this campaign's
  root assigned to, and is this the rotation that made that
  assignment?* — the **assignment** question, asked about a campaign
  before and between its calls.

Why this is an eighth base, and not a subclass of the seventh
-------------------------------------------------------------

The temptation is real in one direction and it is airtight in the other.

**Not under :class:`~providers.RootProviderError`.**  That base is feature
196's, and its own docstring states the split this module is the other half of:
*"Feature 196 records the serving provider of each root call … Feature 197
persists the per-campaign rotation"*, and the module docstring of
:mod:`providers._root` says of this feature's question — *"Which of the declared
providers serves this root call is feature 197's question … a store that did
both would be deciding an assignment on the way to writing it down."*  The two
are asked at different moments about different subjects: 196's question is about
**one call**, after it was placed, and its repair is to write the row the gate
refused; 197's question is about **one campaign**, before and between its calls,
and its repair is to declare the rotation or to assign the root.  Folding this
under ``RootProviderError`` would make ``except RootProviderError:`` answer two
questions — *this call's provenance was refused* and *this campaign's rotation
was not declared / this root was never assigned* — and the two have different
repairs (record the call, versus assign the root).  A caller recording root
calls must not have an assignment refusal answered in its place, which is the
collapse each of this package's taxonomies refuses in its own docstring.

**And the dependency runs one way.**  Feature 197 *composes* feature 196: the
rotation's ``assign`` and its pair ``record_root_provider`` both call 196's
store, so a refusal raised by 196's gate travels *through* 197's call to 197's
caller.  That is exactly why the two must be distinguishable at the ``except``:
a caller of the pair reads 196's `RootNotRecordedError` to learn *this node is
not in the tree* and 197's `UnassignedRootProviderError` to learn *the rotation
never assigned this root to that family*.  Wrapping the former in the latter
would put a vague sentence in front of a precise one, and the suite pins the
propagation rather than the wrapping.

The base is also raised *directly*, for the failures no subclass describes: a
campaign id that is not a UUID, a node id that is not a UUID, a tier offered for
a campaign whose stored rows carry a different declared set, a row whose digest
is not the canonical text this feature writes.  These are malformed
*descriptions* or corrupt *rows* rather than failed *assignments*, and the move
is the one :class:`providers.RootProviderError` makes for a blank serving
provider name: a contract violation that is genuinely none of the named cases
has no subclass to wear, and minting one class per call site is how a taxonomy
stops describing anything.

The two refusals, and why there are exactly two
-----------------------------------------------

The feature's sentence has two nouns in it — a **rotation** and a **campaign**
— and one purpose clause that reads as a condition on the rotation: the rotation
exists *so* that different families propose different mechanisms.  It fails in
exactly two ways that are the store's to refuse.

* :class:`UnassignedRootProviderError` — **the call is not covered by the
  rotation.**  This is the gate that keeps the purpose clause honest, and it is
  the reason this module raises at all on a call that otherwise looks fine.  A
  root call claiming to have been served by a family that this campaign's
  rotation never assigned to that root is precisely the state §14.1 documents as
  the provenance failure — *"DeepSeek retired ``deepseek-v4-flash`` on
  2026-09-10 while continuing to accept the ID, silently serving V4.1-Flash"* —
  and a record that accepted it would write the silent re-route into the
  rotation as though a human had chosen it.  Note what is *not* refused twice:
  a serving family the declared tier does not name at all is feature 196's
  ``UnknownRootProviderError``, raised by 196's own gate when the pair calls it;
  this one is about the *assignment*, and the two coexist because they are
  different facts (the set does not name it / the rows do not cover it).

* :class:`RotationConflictError` — **the same root offered two assignments.**
  One root of one campaign was assigned one family, and that assignment is what
  the rotation is: the record the digest summarizes and the stratum the tree's
  roots are read by.  Re-issuing the **identical** assignment returns the stored
  row — a retry is the same decision arriving twice — while re-assigning the
  same root to a *different* family claims the campaign rotated across two
  families at one root, which is not an update but a contradiction.  It is named
  for the rotation rather than for the root because what a reader would have to
  repair is the rotation, not one row.

There is deliberately **no** third refusal for *"the tier is malformed"* or
*"the campaign id is not a UUID"*: those are the base's, on the ground the
section above gives, and a taxonomy that grew a class per malformation would
stop describing questions at all.

Stdlib-only, like the rest of this tree: these errors describe a decision a
deployment made about one campaign, and nothing here dials a provider, reads a
rate card, or imports an SDK.
"""

from __future__ import annotations

__all__ = [
    "RootRotationError",
    "RotationConflictError",
    "UnassignedRootProviderError",
]


class RootRotationError(Exception):
    """Base of the root-rotation taxonomy — a campaign's root provider rotation could not be decided or persisted.

    One base class so a deployment's rotation recorder and a suite can
    catch every failure of feature 197's sentence — a campaign whose
    rotation is stated two ways, a root the rotation does not cover, a
    re-assignment that contradicts the row it would overwrite — with a
    single ``except``, the way :class:`providers.RootProviderError` gives
    feature 196's record one handle and
    :class:`providers.ModelPinError` gives the authoring record one.  The
    base is deliberately unrelated to all seven of the others: a rotation
    that could not be decided is not a call that failed, not a node whose
    author cannot be named, not a depth model that was refused, not a
    window that could not be found, not an endpoint that went unchosen,
    not a rate that was never measured, and not a root call's provenance
    that could not be written — and a caller catching any of those must
    not have this answered in their place.

    Its nearest neighbour is :class:`providers.RootProviderError`, and the
    module docstring states the distinction in full: feature 196 answers
    *can this root call's serving provider be recorded?* about **one call,
    after it was placed**; feature 197 answers *which family was this
    campaign's root assigned to, and is this the rotation that made that
    assignment?* about **one campaign, before and between its calls**.
    Feature 197 composes 196's store, so the two vocabularies travel
    through one call — which is exactly why a caller's ``except`` must be
    able to tell them apart, and why this base shares no ancestor with
    that one.

    Also raised directly for the failures no subclass describes — a
    campaign id or a node id that is not a UUID, a tier offered for a
    campaign whose stored rows carry a different declared set, a row whose
    digest is not the text this feature writes — on the grounds the module
    docstring gives: those are bad *descriptions* or corrupt *rows* rather
    than failed *assignments*, and the taxonomy splits by question, not by
    call site.
    """


class UnassignedRootProviderError(RootRotationError):
    """A root call served from a family this campaign's rotation never assigned it.

    Feature 197's sentence exists *so that* different families propose
    structurally different mechanisms, and the rotation is the written
    decision that makes that true of a campaign: each root is assigned one
    family, and the family that serves it is the one assigned.  A call
    reporting any other serving provider is refused rather than recorded,
    because accepting it is exactly how §14.1's documented silent re-route
    writes itself into the campaign's provenance as though a human had
    chosen it —

        DeepSeek retired ``deepseek-v4-flash`` on 2026-09-10 while
        continuing to accept the ID, silently serving V4.1-Flash.  See
        §14.1 — this is the provenance failure, not a hypothetical.

    — and because the assignment is what feature 215's ``tree_diversity``
    reads per authoring model: a rotation whose served families are
    whatever the providers happened to answer is a rotation that measures
    nothing.

    **Raised for a different fact than
    :class:`~providers.UnknownRootProviderError`.**  That one is feature
    196's, and it answers *the campaign's declared set does not name this
    provider at all*; this one answers *the set may name it, but this root
    was assigned another family*.  Both are raised by the pair
    :meth:`providers.RootRotation.record_root_provider`, the first by
    feature 196's gate inside it and the second by feature 197's own check
    before it, and the distinction is the repair: add the provider to the
    declared set, versus correct the rotation (or the call).

    Raised **before any row is written**, naming the root, the campaign,
    the family the rotation assigned that root and the family the call
    reports — the four facts a repair needs, and the reason the refusal is
    actionable rather than a complaint.

    The repair is the rotation, not the provenance: assign the root to the
    family that actually served it (a new assignment, if this is a genuine
    re-routing the campaign intends to record), or serve the call from the
    family the rotation covers.  What is never available is recording a
    serving family the rotation did not assign, because then the rotation
    record — and the digest feature 214 keys a campaign by, and the
    per-family stratum feature 215 counts — would describe a plan the
    campaign did not follow.
    """


class RotationConflictError(RootRotationError):
    """One root of one campaign assigned to two different families.

    The rotation is a decision about one campaign, and per root it is one
    decision: the campaign rotates its roots across the declared families,
    each root is assigned one of them, and that assignment is what the
    stored row-set records and what the digest summarizes.  Re-issuing the
    **identical** assignment returns the stored row — a retry is the same
    decision arriving twice, and the row is the decision — while assigning
    the same root to a *different* family claims the campaign planned two
    families at one root, which is not an update but a contradiction: a
    rotation read back would answer two families for a root that proposed
    one mechanism, and the stratum it is read by would put that mechanism
    in both.

    Raised by :meth:`providers.RootRotation.assign` (and therefore by the
    pair :meth:`providers.RootRotation.record_root_provider`), naming both
    families, the campaign and the node, the same shape
    :class:`~providers.RootProviderConflictError` gives a provenance row
    recorded twice and :class:`~providers.CacheRateConflictError` gives a
    rate measured twice — because the caller learns which value is stored
    and which it asked for, and that is the difference between an
    actionable refusal and a complaint.

    Named for the *rotation* rather than for the root: the value a reader
    would have to repair is the campaign's rotation, not one row of it —
    and a root that genuinely was proposed twice under two families is two
    proposals, which the tree records as two nodes, each assigned its own
    family.
    """
