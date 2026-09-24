"""The promotion member's error vocabulary — one tree, split by repair.

One base class (:class:`PromotionError`) so a caller — the epoch governance of
features 293-296, an operator script, the endpoint's own adapter — can catch
every failure of this member's path with a single ``except``.  The subclasses
split by *what the caller must do about it*, never by which line raised: the
rule :mod:`discovery.errors`, :mod:`regime.errors`, :mod:`bootstrap.errors` and
:mod:`nulloracle.errors` state for their own trees.

Feature 291 — *System exposes POST /promotion/pre-register, which returns a
criteria hash recorded before the deciding evaluation runs* — opens the tree
with two classes and no more, because its one act has exactly two failure
modes a caller can act on:

* :class:`PromotionError` itself carries **the ask** — a body that is not the
  six terms §13.7 pre-registers, or a criteria document that is not the
  document ``criteria_hash`` is a hash *of*.  Nothing was read and nothing was
  written; the repair is to re-send the ask.
* :class:`PromotionStoreError` carries **the address and the write** — a
  ``DATABASE_URL`` this member cannot speak, a database it cannot bring to the
  revision the row needs, or a row that did not land.  The repair is to the
  deployment.

**Why the store's faces are gathered and not split.**  The same argument
:class:`regime.errors.CoverageError` makes for its own three faces: the
caller's position is the same in all of them — *the pre-registration row was
not recorded* — and the next step is to read which face the message names.
The contrast is with the judgement refusals the category's later features add:
feature 292's ``criteria_mismatch`` is a *verdict* about evidence, not a failed
write, and it will sit beside this class rather than under it, the way
:class:`regime.errors.DiversityClaimError` sits beside
:class:`regime.errors.CoverageError`.

**The one code word this feature owns.**  :data:`PROMOTION_REGISTRY_ERROR_CODE`
opens the store class's messages the way ``full_history_fit``,
``illegal_theme`` and ``pool_frozen`` open theirs: an operator greps one word
for *the registry could not be written to*.  Nothing in this class is a
refusal about a promotion's merits — a merits refusal is feature 292's, and
naming this one after it would send a reader looking for a mismatch that never
happened.

**The tree is open, and that is the seam 293-296 land on.**  The category's
next features extend this module with siblings — feature 292's
``criteria_mismatch`` verdict, 295's retirement refusal, 296's terminal state —
and the discipline is the one stated above: a new class is a sibling when its
repair differs, and a face of an existing one when the caller's position is
the same.  Nothing here presumes which of the two any later feature is.
"""

from __future__ import annotations

__all__ = [
    "PROMOTION_REGISTRY_ERROR_CODE",
    "PromotionError",
    "PromotionStoreError",
]


class PromotionError(Exception):
    """Base class for every failure of the promotion member's path."""


#: The greppable word that opens every :class:`PromotionStoreError` message:
#: the registry row could not be written, so nothing was recorded.  Distinct
#: from feature 292's ``criteria_mismatch`` by design — that one is a verdict
#: about a promotion, this one is a report about the store.
PROMOTION_REGISTRY_ERROR_CODE = "promotion_registry_unwritable"


class PromotionStoreError(PromotionError):
    """A pre-registration row could not be recorded as asked.

    Raised for the address (a ``DATABASE_URL`` this member cannot speak), for
    the schema (a database that cannot be brought to the revision
    ``promotion_registry`` needs), and for the write (the row did not land, or
    the read-back disagreed with what was written).  Every message opens with
    :data:`PROMOTION_REGISTRY_ERROR_CODE` and names the node the row was about,
    so an operator's log line says which registration failed and in which of
    the three ways.

    Deliberately not a face of :class:`PromotionError`'s ask: a malformed body
    is refusable without a database at all, and a caller that gathered the two
    would read *the store refused me* where the truth is *the body was not the
    six terms*.  The split is the repair's, not the code path's.
    """
