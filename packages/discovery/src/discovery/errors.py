"""The discovery member's error vocabulary.

One base class (:class:`DiscoveryError`) so a caller — the campaign loop,
the dreaming loop, an operator script, a later feature in this category —
can catch every failure of the orchestrator's planning path with a single
``except``.  The subclasses split by *what the caller must do about it*,
not by which line of code raised, the discipline
:mod:`bootstrap.errors`, :mod:`nulloracle.errors` and
:mod:`artifacts._errors` state for their own trees:

* :class:`CampaignPlanningError` — the ask was malformed.  A campaign id
  that is not a UUID, a declared type that is neither of §7.3's two
  regimes, a ``workspace_count`` that is not a genuine positive integer,
  or a stored ``null_fraction`` that is not a finite real strictly inside
  ``(0, 1)``.  Every one of these is a fact about the *request*: nothing
  was read, nothing was written, and the repair is to re-consider what
  was asked for.  docs/nullius-tech-architecture.md §4.1.1's clip is
  ``clip(max(2/W, 0.15), 0.15, 0.35)``, so a ``W`` that is not a count has no
  fraction to compute, and a type that is not a regime names no world the
  orchestrator could plant.

* :class:`CampaignOrderError` — the ask was well formed and the *store's
  state* contradicts the feature's own ordering law.  Feature 232's
  sentence is *"System creates a campaign record capturing type, workspace
  count and null fraction **before any node is expanded**"*, and that
  clause is a property of the store rather than of the request: either
  the campaign's tree already holds a node (so the record was not created
  first, and creating it now would write a planning-time fact onto a
  campaign that has already been run), or a re-issued plan disagrees with
  the row already stored (§7.3 fixes a campaign's declared type and its
  workspace count at planning time, and a second declaration naming
  different ones would silently retype a world that was already planned).
  The repair differs from the first class's in kind: nothing about the
  request is wrong; the *world* is.  An operator reads this refusal to
  learn which campaign and which fact, then repairs the store or re-plans
  under a new campaign id — not by re-sending the same request.

The split matters to this member's two callers.  The *campaign loop*
(feature 232's own caller, and the features that follow it in this
category) calls :meth:`~discovery.campaign.CampaignRecords.create` before
expanding anything, and needs the two classes to be distinguishable
because the retries differ: a malformed ask is a bug in the loop's own
plumbing and will fail identically however often it is retried, while an
ordering refusal is a fact the loop *can* act on — it either joins the
existing campaign or re-plans it under a fresh id.  An *operator* auditing
a deployment's campaign table wants the second class alone: it is the one
that says a campaign was planned out of order.  Folding the two together
would make both callers catch and re-inspect something they cannot tell
apart.

Both are subclasses of :class:`DiscoveryError` and neither subclasses the
other.  This member deliberately does **not** raise
:class:`~nulloracle.errors.KsGuardError`, even though seven stores in the
null-oracle member open the very same ``campaign`` table: the workspace
contract is that no member imports another, and a caller reading
``KsGuardError`` out of a campaign *creation* would look in the wrong
module for the cause — the fraction's store refuses a write onto a
campaign nobody planned, while this member refuses a *plan* that cannot be
recorded.  Different acts, different vocabularies.
"""

from __future__ import annotations

__all__ = [
    "CampaignOrderError",
    "CampaignPlanningError",
    "DiscoveryError",
]


class DiscoveryError(Exception):
    """Base class for every failure of the discovery orchestrator's path."""


class CampaignPlanningError(DiscoveryError):
    """The campaign plan could not be formed as the caller asked for it.

    Raised before anything is read or written: an id, a type, a workspace
    count or a stored fraction that is not the kind of value this feature's
    sentence is about.  The repair is to re-consider the ask — see the
    module docstring for why this is not the same class as
    :class:`CampaignOrderError`.
    """


class CampaignOrderError(DiscoveryError):
    """The store's state contradicts the campaign's ordering law.

    Feature 232's *"before any node is expanded"* is the law, and this is
    the refusal when the store says it was broken: the campaign's tree
    already holds a node, or a re-issued plan disagrees with the row
    already recorded.  Both name the campaign and the offending fact, so
    an operator learns *what* is out of order rather than merely that
    something is.
    """
