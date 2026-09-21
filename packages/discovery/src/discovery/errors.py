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

Feature 241 adds a third class, and it sits **beside** the first two rather
than under either of them.  :class:`IllegalThemeError` is raised when a
research theme is assigned (or a legal set is configured) and the value is
not in the configured legal set — the refusal app_spec.xml names with the
code ``illegal_theme``.  It is not a
:class:`CampaignPlanningError` because the offending fact is not about the
*request*: a perfectly well-formed theme name is refused here solely
because the **deployment's configured space** does not contain it, and the
repair is to widen ``NULLIUS_LEGAL_THEMES`` or to pick a different theme —
not, as with a malformed ``W`` or a mistyped regime, to re-send a corrected
ask.  PRD §9 states the distinction from the other side: *"Choosing the
space is the highest-value human input in the system, and it should be
encoded as the set of legal ``theme_root`` values."*  A caller that catches
:class:`DiscoveryError` gets every failure of this member's path, which is
the one ``except`` the base class exists for.
"""

from __future__ import annotations

__all__ = [
    "CampaignOrderError",
    "CampaignPlanningError",
    "DiscoveryError",
    "IllegalThemeError",
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


class IllegalThemeError(DiscoveryError):
    """A research theme is not in the deployment's configured legal set.

    app_spec.xml feature 241: *"System rejects a root theme outside the
    configured legal set when assigning a research theme."*  Every message
    this class carries begins with the code
    :data:`discovery.themes.ILLEGAL_THEME` (``illegal_theme``) — the one
    spelling the spec names — so an operator grepping a log for the
    rejection finds it by the feature's own word, the convention §7.3's
    ``heterogeneous_world`` and §7.1's ``is_null_column`` refusals already
    follow in this workspace.

    The class carries **both** faces of that one question, the way
    :class:`~canary.CanaryImportError` carries both faces of §12's
    determinism floor:

    * a theme being *assigned* that the configured set does not admit —
      feature 241's own sentence, refused before any node is planted; and
    * a term in a *configured* legal set that is not a theme identifier at
      all — refused at configuration, because a legal set is how the space
      is enforced and a term it cannot judge is one no assignment could be
      checked against.

    They are one class because they are one predicate — *can this value be
    a legal theme here?* — split by *who* got it wrong (the planner's
    assignment, or the operator's configuration), and because the two
    refusals a caller acts on are "widen the set" and "pick a legal theme",
    which is one repair decision read from either side.

    Deliberately **not** a subclass of
    :class:`CampaignPlanningError`, and the reason is the repair rather
    than the shape: a malformed ask is fixed by re-sending a corrected one,
    while an illegal theme is a fact about a *configured space* that a
    well-formed ask ran into.  Kept out of :class:`CampaignOrderError` for
    the same reason: nothing about the store's state is in question — the
    theme is refused before any row or node exists.
    """
