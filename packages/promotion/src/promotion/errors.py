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

**Feature 299's block is the tree's first sibling, and it is gathered.**
:class:`PromotionBlockError` carries feature 299's one act — *System persists a
blocking reason for a promotion whose deployment regime coverage sits below
threshold* — and it is a **new class** rather than a face of either of the two
above, because its noun is different: not *the ask was malformed* and not *the
registry row did not land*, but *this promotion is blocked on coverage and the
reason it is blocked was not recorded*.  The first promotion in this member
that is refused on **merit** rather than on form, and its repair is neither a
corrected body nor a corrected deployment: it is to grow the coverage, or to
deploy into a regime the pool does cover — an act of the census (feature 290)
and the backfill (feature 287), in another member entirely.

Its four faces stay **gathered in one class**, and the argument is feature
285's, restated because this member's caller is the same *gate*: a gate's one
failure mode is silence.  A caller whose single ``except PromotionBlockError``
guards its promotion path must not be able to walk through a hole because a
malformed threshold arrived in a different class from an unreachable database —
in either case the promotion is blocked and the reason is not on a row, and the
caller that cannot tell *which* still must not proceed.  So the address, the
ask, the absence and the write all open with
:data:`PROMOTION_BLOCK_ERROR_CODE` and all name what they are about.  This is
the one place in the member where the split-by-repair rule is *overridden* by
the caller's position, and :mod:`regime.errors` records the same override for
the same reason one member over.

**The tree is open, and that is the seam 292-296 land on.**  The category's
next features extend this module with siblings — feature 292's
``criteria_mismatch`` verdict, 295's retirement refusal, 296's terminal state —
and the discipline is the one stated above: a new class is a sibling when its
repair differs, and a face of an existing one when the caller's position is
the same.  Nothing here presumes which of the two any later feature is.
"""

from __future__ import annotations

__all__ = [
    "PROMOTION_BLOCK_ERROR_CODE",
    "PROMOTION_REGISTRY_ERROR_CODE",
    "PromotionBlockError",
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


#: The greppable word that opens every :class:`PromotionBlockError` message:
#: ``coverage_below_threshold`` — feature 285's own code word, **restated**
#: rather than imported, because no member imports another and the promotion
#: plugin's features are another member's (``regime.promotion`` says so from
#: its own side and names this feature as the reason the literal exists).
#:
#: The word names the *finding*, not this feature's act: the promotion was
#: pointed at a deployment regime and the replay pool does not cover it.  An
#: operator greps one word and lands on both halves of §C7's promotion block —
#: the refusal feature 285 raises and the reason feature 299 records — which is
#: the whole point of restating a literal instead of inventing a second name
#: for one finding.
PROMOTION_BLOCK_ERROR_CODE = "coverage_below_threshold"


class PromotionBlockError(PromotionError):
    """A promotion blocked on regime coverage could not be recorded as blocked.

    Feature 299's class, and the member's first *merit* refusal: every other
    failure in this tree is about a form (a malformed ask, a bad address) or
    about a write, while this one is about a promotion's *evidence* — the
    target deployment regime's stored-world count is below the threshold the
    deployment configured, so §C7 blocks the promotion and this member persists
    the reason.

    Four faces, **gathered** rather than split, because the caller is a gate
    and a gate's one failure mode is silence (the argument is in the module
    docstring, and it is feature 285's):

    * **the ask** — a malformed node, epoch, regime or threshold, or a
      ``count`` that is not a count of worlds.  Nothing was read and nothing
      was written; the repair is to re-send the ask.
    * **the address** — a ``DATABASE_URL`` this member cannot speak.  The
      repair is to the deployment.
    * **the absence** — no ``promotion_registry`` row for the node, so there is
      no decision for this reason to be the blocking reason *of*.  The repair
      is to pre-register first (feature 291), which is §13 item 7's ordering
      and not an incidental precondition.
    * **the write** — the row did not land, or the read-back disagreed with
      what was written.  The repair is to the database.

    Every message opens with :data:`PROMOTION_BLOCK_ERROR_CODE` and names the
    node the block was about, so an operator's log line says which promotion
    was blocked and in which of the four ways.

    Deliberately **not** a face of :class:`PromotionStoreError`.  A caller that
    gathered the two would read *the registry could not be written to* where
    the truth is *the pool does not cover the regime this promotion is aimed
    at* — two different repairs, and the second is the one §C7 exists to make
    visible.  The split is the repair's, not the code path's; that the two
    classes share a code word on purpose is the *finding's* identity, not a
    licence to collapse them.
    """
