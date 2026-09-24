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

**Feature 298 adds the tree's fourth class, and it is the second merit refusal
without being a face of the first.**  :class:`VoidCalibrationError` carries
*"System rejects a promotion when the campaign ``calibration_status`` is
``VOID``, because a void campaign carries no usable calibration"* — §7.4's
verdict read off the ``campaign`` row (feature 124 wrote it) and refusing the
promotion of a hypothesis that came from that campaign.  It is **not** a
:class:`PromotionBlockError`: the two are both merit refusals, and that is the
whole of their resemblance.  The block is a finding about the *pool* — §C7's
coverage ledger says the regime being deployed into is thin — and its repair is
to grow the coverage.  This one is a finding about the *evidence* — §7.4 says the
campaign's control is gone — and its repair is a judgement no coverage fix can
make, because a campaign whose nulls are detectable cannot be repaired by adding
worlds to it.  Gathering them would put two unrelated acts behind one ``except``
and would leave a caller unable to tell *the pool is thin* from *this campaign's
calibration is void*.  So the split is the repair's, the rule this module opens
with — and it is the same split feature 243 draws in another member, where
:class:`discovery.errors.VoidCampaignError` is kept out of
``CampaignPlanningError`` and out of ``CampaignOrderError`` by exactly this
argument.

It shares feature 243's **code word** (``void_campaign``), deliberately, and the
class docstring argues why: one finding, two doors, one word an operator greps.

**Feature 293 adds the tree's fifth class, and it is a recording act rather
than a merit refusal.**  :class:`PromotionDecisionError` carries *"System
persists each promotion decision into the promotion_registry with its
timestamp and criteria hash"* — the closing stamp on the row feature 291
opened, which is a *write about a promotion* and not a *judgement of one*.
It is deliberately **none** of the four beside it:

* not :class:`PromotionError` — that class carries the pre-registration's
  *ask* face, and a caller whose single ``except`` guards the decision path
  would read *the body was malformed* where the truth is *the decision was
  not recorded*;
* not :class:`PromotionStoreError` — every message in that class is about a
  *pre-registration row* that did not land, and the two acts must stay
  greppable apart: an operator who lands on ``promotion_registry_unwritable``
  is debugging feature 291's write, not this one;
* not :class:`PromotionBlockError` nor :class:`VoidCalibrationError` — those
  are the member's two *merit* refusals (§C7's coverage finding, §7.4's
  calibration verdict), and this feature judges nothing: the verdict on the
  evidence is the deciding evaluation's, the mismatch refusal is feature
  292's, and this class exists because a decision that happened and was not
  recorded is a failure nobody downstream can see.

Its faces stay **gathered** in one class, the argument the block's and the
calibration's gathered classes make one feature over each: this feature's
caller is the same **gate**, and a gate's one failure mode is silence.  A
caller whose single ``except PromotionDecisionError`` guards its promotion
path must not be able to walk through a hole because a malformed node arrived
in a different class from an unreachable database or a node nobody
pre-registered — in every case the decision stands unrecorded, which is the
state §13 item 4's epoch ledger and feature 300's forward window are built to
never have to guess about.  So the ask (a malformed node, a naive stamp), the
address, the absence (no pre-registration to close), the ordering (a stamp
that would precede the criteria it was judged against) and the write all open
with :data:`PROMOTION_DECISION_ERROR_CODE` and all name what they are about.

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
    "PROMOTION_DECISION_ERROR_CODE",
    "PROMOTION_REGISTRY_ERROR_CODE",
    "VOID_CALIBRATION_ERROR_CODE",
    "PromotionBlockError",
    "PromotionDecisionError",
    "PromotionError",
    "PromotionStoreError",
    "VoidCalibrationError",
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


#: The greppable word that opens every :class:`VoidCalibrationError` message:
#: ``void_campaign`` — feature 243's own code word
#: (:data:`discovery.manifest.VOID_CAMPAIGN_CODE`), **restated** rather than
#: imported, because no member imports another and feature 243 is the discovery
#: member's.
#:
#: The same literal is the right one here for the reason the block store gives
#: about ``coverage_below_threshold``: it names the *finding* — a campaign §7.4
#: voided, whose planted nulls the KS guard found detectable — and not the act,
#: and an operator who greps it has to land on **both** gates that refuse a void
#: campaign: feature 243's *when adding completed campaigns to the replay pool*
#: and this feature's *when promoting from one*.  Two doors, one finding, one
#: word to search for.  A second spelling invented here would send a reader
#: looking for a second kind of void campaign, which does not exist.
VOID_CALIBRATION_ERROR_CODE = "void_campaign"


class VoidCalibrationError(PromotionError):
    """A promotion was refused because its campaign's calibration is void.

    app_spec.xml feature 298: *"System rejects a promotion when the campaign
    ``calibration_status`` is ``VOID``, because a void campaign carries no
    usable calibration."*  Raised by
    :func:`promotion.calibration.rejects_void_calibration` and
    :meth:`promotion.calibration.PromotionCalibrations.rejects_void_promotion`
    when the campaign a promoted hypothesis came from carries
    :data:`~promotion.calibration.CALIBRATION_STATUS_VOID` — the verdict §7.4's
    KS guard (feature 124) wrote onto the ``campaign`` row.

    **Its noun is evidence, not form, and that is why it is its own class.**  The
    member's tree splits by *the repair the caller must make*, and this refusal's
    repair is unlike any of the three beside it:

    * not :class:`PromotionError` — the ask was well formed, and the campaign was
      read before anything was judged.  Re-sending a corrected body is not the
      repair, because there is no correction to make to the request;
    * not :class:`PromotionStoreError` — nothing failed to write, and the row the
      judgement was made on is exactly as it was.  The deployment is fine;
    * not :class:`PromotionBlockError` — the subject is a different campaign
      fault with a different reading behind it (§C7's coverage ledger versus
      §7.4's calibration verdict) and a different repair, so gathering the two
      would put one ``except`` behind two unrelated acts.  The block store's own
      docstring reserves that class for the coverage finding by name.

    A **void campaign** is not a form the caller can fix and not a store that
    failed: it is a campaign whose planted nulls the agent may have learned to
    identify, which — in the PRD's own words — voids **all** of that campaign's
    calibration.  So this sits beside the other three as the tree's fourth
    top-level sibling, and its repair is a judgement the caller must make:
    re-plan the campaign under a fresh id, investigate the block length and
    permutation scheme §4.3 indicts, or promote from a campaign that stands.

    **Four faces, gathered**, the argument :class:`PromotionBlockError` states one
    feature over and :class:`regime.errors.PromotionCoverageError` states one
    member over: this feature's caller is the same **gate**, and a gate's one
    failure mode is silence.  A caller whose single ``except VoidCalibrationError``
    guards its promotion path must not be able to walk through a hole because a
    malformed node id arrived in a different class from an unreachable database —
    in every case the promotion is unjudged and must not proceed.  So the ask
    (a malformed node or campaign identity, a status that is not text), the
    address (a ``DATABASE_URL`` this member cannot speak), and the two absences
    (a node the tree does not hold; a node whose campaign row is absent) all open
    with :data:`VOID_CALIBRATION_ERROR_CODE` and all name what they are about.

    Deliberately **not** a face of :class:`PromotionBlockError` even though both
    are merit refusals: §C7's coverage block and §7.4's calibration verdict are
    different findings about different facts, read from different tables, with
    different repairs — and a caller that had to distinguish *the pool is thin*
    from *this campaign's control is gone* would be unable to, behind one class.
    That the two classes carry *different* code words is what makes each
    greppable; that feature 243 and this class carry the *same* one is the
    finding's identity, and no licence to collapse the classes.
    """


#: The greppable word that opens every :class:`PromotionDecisionError` message:
#: the promotion was decided and the decision was not recorded — the row
#: feature 291 opened is still open.  Spelled after the store's own word
#: (``promotion_registry_unwritable``) and beside it in meaning but not in
#: letter, because the two are two *acts* over one table: an operator greps
#: the registry's word for *a pre-registration did not land* and this one for
#: *a decision did not land*, and landing on the wrong one sends them
#: debugging the wrong write.
PROMOTION_DECISION_ERROR_CODE = "promotion_decision_unrecorded"


class PromotionDecisionError(PromotionError):
    """A promotion decision could not be persisted as asked.

    Feature 293's class: *"System persists each promotion decision into the
    promotion_registry with its timestamp and criteria hash."*  Raised by
    :func:`promotion.decision.record_decision` and
    :meth:`promotion.decision.PromotionDecisions.record_decision` when the
    closing stamp could not be placed on the row feature 291's pre-registration
    opened — and by the module's reads, for the malformed asks and the
    unreachable store they share with the act.

    **Its noun is a record, not a judgement, and that is why it is its own
    class.**  The member's tree splits by *the repair the caller must make*,
    and this refusal's repair is unlike any of the four beside it:

    * not :class:`PromotionError` — that class carries the pre-registration's
      ask face, and gathering the two would put one ``except`` behind two
      acts whose callers are different processes entirely (§13 item 7's whole
      shape: the feature that writes the first timestamp is not the feature
      that writes the second);
    * not :class:`PromotionStoreError` — the store class's every message is
      about a *pre-registration row* that did not land, and the code word is
      the operator's way between the two writes: collapsing the classes would
      make the member's two halves of §13 item 7's record indistinguishable
      exactly where distinguishing them is the point;
    * not the block's class nor the calibration's — those are the member's
      two *merit* refusals, findings about the pool and the campaign, and
      this feature judges nothing: whether the promotion *stands* is the
      deciding evaluation's verdict, and feature 292's mismatch refusal is
      the only one that compares a promotion against its hash.

    Five faces, **gathered** rather than split, because the caller is a gate
    and a gate's one failure mode is silence — the argument
    :class:`PromotionBlockError` states one feature over and
    :class:`VoidCalibrationError` states one feature over that:

    * **the ask** — a malformed node identity, or a stamp that is not an
      aware instant.  Nothing was opened and nothing was written; the repair
      is to re-send the ask.
    * **the address** — a ``DATABASE_URL`` this member cannot speak, or a
      database that cannot be brought to the revision the row needs.  The
      repair is to the deployment.
    * **the absence** — no ``promotion_registry`` row for the node, so there
      is no open promotion for this decision to close.  The repair is to
      pre-register first (feature 291), which is §13 item 7's ordering and
      not an incidental precondition.
    * **the ordering** — a decision stamped before the criteria were fixed,
      which would write a row whose own two columns state the reverse of
      §13 item 7; feature 360's CI finding, refused at the write instead of
      at the merge.
    * **the write** — the row did not close, or could not be read back as
      closed.  The repair is to the database.

    In every one of them the decision stands unrecorded, and that is the
    state the class exists to make loud: §13 item 4 charges sequestered
    epochs by *"3 promotion decisions"* — events recorded in this table, in
    ``0110``'s own words — feature 300 opens the forward measurement window
    at this stamp, and feature 360's invariant reads the two timestamps off
    the row.  A caller whose single ``except PromotionDecisionError`` guards
    its promotion path must not be able to walk through a hole because a
    malformed node arrived in a different class from an unreachable database.

    Every message opens with :data:`PROMOTION_DECISION_ERROR_CODE` and names
    the node the decision was about, so an operator's log line says which
    promotion went unrecorded and in which of the five ways.
    """
