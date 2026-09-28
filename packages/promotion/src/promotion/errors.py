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
write, and it sits beside this class rather than under it —
:class:`~promotion.errors.CriteriaMismatchError`, the category's first judgement
verdict — the way :class:`regime.errors.DiversityClaimError` sits beside
:class:`regime.errors.CoverageError`.

**The one code word this feature owns.**  :data:`PROMOTION_REGISTRY_ERROR_CODE`
opens the store class's messages the way ``full_history_fit``,
``illegal_theme`` and ``pool_frozen`` open theirs: an operator greps one word
for *the registry could not be written to*.  Nothing in this class is a
refusal about a promotion's merits — a merits refusal is feature 292's, and
naming this one after it would send a reader looking for a mismatch that never
happened.

**The ask face gains the tree's one subclass, and the reason is a caller
that must decide a status.**  :class:`PromotionConflictError` refines
:class:`PromotionError` itself — the pre-registration's ask face — for the
one refusal in that class whose body is *not* malformed: a re-registration
of a node that already holds a row, stating different criteria.  Feature
291 raised that refusal as the ask's own class, and the category this class
lands with — an HTTP adapter that must answer one status per refusal —
needs to tell it from a malformed ask, because the two are not the same
answer: a malformed body is the caller's to fix and re-send, while a
conflict with a row §13 item 7 already fixed is nobody's to fix at all.
The split is therefore *downward* where every other split in this module
is sideways, and that is the third spelling of the discipline the closing
paragraph states: a sibling would have changed what a caller's standing
``except PromotionError`` catches, and the one law this refinement keeps
is that nothing a caller already wrote changes — the new class subclasses
the class raised today, so every existing clause keeps catching it, and a
caller that must decide a status catches the subclass first.  Its one
face names both criteria hashes — the one the row holds and the one the
request states — because that is what makes the conflict *decidable*: an
operator reading the message sees two digests and knows which row stands,
and an adapter reading the class knows the ask was well formed.  Every
message opens with :data:`PROMOTION_CONFLICT_ERROR_CODE`, spelled clear of
feature 292's ``criteria_mismatch`` in letter as in moment: 292 judges a
promotion against its recorded hash at decision time, while this refuses
a registration before any evaluation has run.

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

**Feature 294 adds the tree's sixth class, and it is a counting act over a
row another feature owns.**  :class:`EpochChargeError` carries *"System
persists the running promotion decision count against the serving epoch in
the epoch_ledger"* — §13 item 4's ledger column advanced, a *write about a
decision* and not a *judgement of one*.  It is deliberately **none** of the
five beside it:

* not :class:`PromotionError` — that class carries the pre-registration's
  *ask* face, and a caller whose single ``except`` guards the charge path
  would read *the body was malformed* where the truth is *the epoch stands
  uncharged*;
* not :class:`PromotionStoreError` — every message in that class is about
  a *pre-registration row* that did not land, and the two code words keep
  feature 291's insert and this feature's advance greppable apart;
* not :class:`PromotionBlockError` nor :class:`VoidCalibrationError` —
  those are the member's two *merit* refusals, findings about the pool and
  the campaign, and this feature judges nothing: whether the promotion
  stands is the deciding evaluation's verdict, and whether the epoch is
  spent is features 295-296's machinery reading the figure this act
  persists;
* not :class:`PromotionDecisionError` — the closest of the five, and the
  one the split is for.  That class reports *a decision happened and was
  not recorded*, and its repair is to a write against the registry.  This
  feature's registry reads all succeed — the decision is recorded, closed
  and stamped — and what did not land is a figure in a *different* table.
  An operator who greps ``promotion_decision_unrecorded`` lands on
  feature 293's write; ``epoch_charge_unpersisted`` is a different write
  to a different table, and conflating the two sends them debugging the
  wrong column.

Its faces stay **gathered** in one class, the same gate argument the
gathered classes before it make: a caller whose single ``except
EpochChargeError`` guards its epoch-governance path must not be able to
walk through a hole because a malformed node arrived in a different class
from an unreachable database or a missing ledger row — in every case the
epoch's count stands unpersisted, which is the state features 295-297
budget the system's whole continuation on.  So the ask (a malformed node
or epoch), the address, the two absences (no registry row to bill, or no
ledger row for the epoch it books), the shrinking count and the write all
open with :data:`EPOCH_CHARGE_ERROR_CODE` and all name what they are
about.

**Feature 300 adds the tree's seventh class, and it is a reader's refusal.**  It
carries *"System timestamps every promoted signal at promotion, which creates
its forward measurement window"* — the act of answering *what window did this
promotion open, and when does it close?* from the row feature 293 closed.  It is
deliberately **not** a face of :class:`PromotionDecisionError`, and the argument
is the split's own:

* 293's class reports a **write that did not land** — *a decision happened and
  was not recorded* — and its repair is to the database.  Nothing here writes
  anything: the row is 293's, and this feature only reads it.
* This class reports a **state that cannot answer the question**: a node nobody
  pre-registered, or one whose deciding evaluation has not run.  The repair is
  not to a write and not to a deployment — it is to the *registration state*
  (pre-register the promotion, or wait for the decision), which is 293's act or
  291's, in that order.
* Its caller is a different one.  The class above guards the promotion path's
  last line; this one guards the window's opener — the forward-model writer
  (feature 332's ``POST /forward/promote``), a report, or an operator asking
  when a promotion stops being out of sample.  A caller that gathered the two
  would read *the decision was not recorded* where the truth is *there is no
  window to open yet*, and would go looking for a failed write that never
  happened.

Its faces stay **gathered** in one class, the argument the three gathered classes
above make: this feature's caller is also a gate, and a gate's one failure mode
is silence.  A window that quietly did not open leaves the forward record's
writer with no start instant at all, which is exactly the state ``0108`` names
when it says why the table exists — *"a row that lost its promotion timestamp
would be an observation with no vintage."*  So the ask (a malformed node, a
window length that is not a positive count), the address, the absence (no
registry row, or a row still open) and the row read back corrupt all open with
:data:`PROMOTION_WINDOW_ERROR_CODE` and all name what they are about.

**Feature 295 adds the tree's eighth class, and it is the first whose
refusal *is* the act.**  :class:`EpochSelectionError` carries *"System
rejects further selection of a sequestered epoch once it has served three
promotion decisions"* — §13 item 4's threshold, read off the count feature
294 just persisted.  It is deliberately **none** of the seven beside it:

* not :class:`PromotionError` — that class carries the pre-registration's
  *ask* face, and a caller whose single ``except`` guards the selection
  path would read *the body was malformed* where the truth is *the epoch is
  spent*;
* not :class:`PromotionStoreError` — no row failed to land, because this
  feature writes nothing at all: the count landed, and that landing is
  exactly the fact the refusal stands on;
* not :class:`PromotionBlockError` nor :class:`VoidCalibrationError` — the
  two *merit* refusals are findings about the replay pool and the campaign,
  read from other members' tables.  This one's noun is the *holdout
  resource* — an epoch the system itself sequestered and has now spent —
  and its repair is unlike either merit's: select a clean epoch, or stop,
  which §13 item 4 calls *"a legitimate terminal state"* rather than a
  fault to fix;
* not :class:`PromotionDecisionError` nor :class:`EpochChargeError` —
  those are *write* faces, a stamp and a count that did not land, and their
  repair is to the database.  Here both landed; the count this refusal
  stands on is exactly the figure feature 294 persisted, and conflating the
  classes would send an operator debugging a write that succeeded when the
  finding is §13 item 4's own budget reached;
* not :class:`PromotionWindowError` — the closest of the seven, and the one
  the split is for.  That class reports a question that *cannot be
  answered* (no row, or a row still open), repaired in the registration
  state.  This one's question is answered, and the answer is *no*: the
  epoch is sealed, its count is on the row, and §13 item 4 refuses the
  fourth booking.  An operator who greps the window's word for this
  refusal would be looking for a missing write that never happened.

Its faces stay **gathered** in one class, the argument every gathered class
above makes: this feature's caller is the same **gate**, and a gate's one
failure mode is silence.  A caller whose single ``except
EpochSelectionError`` guards its selection path must not be able to walk
through a hole because a malformed epoch arrived in a different class from
an unreachable database or an epoch nobody sealed — in every case the epoch
stands unjudged and the booking it was headed for must not proceed, which
is the fourth promotion on a spent holdout that §13 item 4's ledger exists
to prevent.  So the ask (a malformed epoch name, a count that is not a
count), the address, the absence (an epoch nobody sealed), the spend (a
count that has reached the budget) and the row (one that cannot be read
back) all open with :data:`EPOCH_SELECTION_ERROR_CODE` and all name what
they are about.

**The tree is open, and that is the seam 292 and 296 land on.**  The
category's remaining features extend this module with siblings — feature
292's ``criteria_mismatch`` verdict, 296's terminal state — and the
discipline is the one stated above: a new class is a sibling when its
repair differs, and a face of an existing one when the caller's position is
the same — with the one third spelling the conflict class adds, a
*subclass* of the class raised today when the refinement must not change
what a caller's standing ``except`` catches.  Nothing here presumes which
of the three any later feature is.
"""

from __future__ import annotations

__all__ = [
    "CRITERIA_MISMATCH_ERROR_CODE",
    "EPOCH_CHARGE_ERROR_CODE",
    "EPOCH_SELECTION_ERROR_CODE",
    "NO_CLEAN_EPOCH_REMAINS_CODE",
    "PROMOTION_BLOCK_ERROR_CODE",
    "PROMOTION_CONFLICT_ERROR_CODE",
    "PROMOTION_DECISION_ERROR_CODE",
    "PROMOTION_PARENT_ABSENT_ERROR_CODE",
    "PROMOTION_REGISTRY_ERROR_CODE",
    "PROMOTION_WINDOW_ERROR_CODE",
    "VOID_CALIBRATION_ERROR_CODE",
    "CriteriaMismatchError",
    "EpochChargeError",
    "EpochSelectionError",
    "PromotionBlockedError",
    "PromotionBlockError",
    "PromotionConflictError",
    "PromotionDecisionError",
    "PromotionError",
    "PromotionParentAbsentError",
    "PromotionStoreError",
    "PromotionWindowError",
    "VoidCalibrationError",
]


class PromotionError(Exception):
    """Base class for every failure of the promotion member's path."""


#: The greppable word that opens every :class:`PromotionConflictError`
#: message: a node already holds a pre-registration and the request states
#: different criteria.  Spelled clear of feature 292's
#: ``criteria_mismatch`` in letter as in moment — that word names a
#: *decision-time verdict* over a promotion, this one a *registration-time
#: refusal* of a write — so an operator who greps either word lands on the
#: act they are debugging: 292's comparison at the deciding evaluation, or
#: 291's store refusing to revise a row §13 item 7 already fixed.  A second
#: spelling that echoed 292's would send a reader looking for a judgement
#: that has not run.
PROMOTION_CONFLICT_ERROR_CODE = "promotion_criteria_conflict"


class PromotionConflictError(PromotionError):
    """A re-registration stated criteria that differ from the node's recorded ones.

    The ask face's one refinement, for the caller that must decide a
    status: *"System raises PromotionConflictError, a subclass of
    PromotionError, when a node is re-registered with different criteria,
    which returns an error message naming both criteria hashes, so a caller
    can tell a conflict from a malformed request."*  Raised by
    :meth:`promotion.pre_register.PreRegistrations._answer_standing` when
    the node already holds a ``promotion_registry`` row whose
    ``criteria_hash`` differs from the digest of the criteria this request
    states — the body is well formed, the store is reachable, and the
    write is refused all the same, because §13 item 7 fixed those criteria
    the moment the first registration landed.

    **The tree's one subclass, and the reason it is not a sibling.**  Every
    other class in this module splits *sideways*, by the repair the caller
    must make; this one splits *downward*, inside the ask face, because the
    refinement's first law is compatibility itself:

    * the refusal is not new — feature 291 raised it as
      :class:`PromotionError` from the day the store landed, and a
      caller's standing ``except PromotionError`` over the
      pre-registration path has been catching it since.  A sibling would
      have silently changed what that clause catches; a subclass keeps
      every existing caller's catch true, which is the constraint this
      class exists under: *subclass the class raised today*;
    * the repair is not a new one either — the ask face already carries it
      (*stop asking; register the second criteria set against the
      hypothesis it is really about*), and what is new is only that a
      caller which must *answer a status* — the HTTP adapter, an operator
      script dividing retryable from fatal — can tell this refusal from a
      malformed ask by class alone, where before both wore one class and
      the only tell was parsing the message;
    * not a face of :class:`PromotionStoreError` — nothing failed to
      write or to read back: the store found the standing row cleanly and
      refused on what it found.  The store's word is about a row that did
      not land; this refusal is about a row that must not be replaced;
    * not :class:`CriteriaMismatchError` — the closest in *subject* and
      the farthest in *moment*.  Feature 292 judges a promotion against
      its recorded hash when the deciding evaluation has run; this refuses
      a registration before any evaluation has started.  292's word is
      deliberately not spelled here, and
      :mod:`promotion.pre_register` pins that by test.

    **One face**, and its message names everything the decision needs:
    both criteria hashes — the standing row's and the request's — so the
    conflict is decidable from the log line alone (two digests, one row
    that stands, one ask that was refused), the node, and the repair.
    Every message opens with :data:`PROMOTION_CONFLICT_ERROR_CODE`, so an
    operator greps one word for *the registry refused to rewrite fixed
    criteria* and finds neither a failed write nor a moved bar.
    """


#: The greppable word that opens every :class:`CriteriaMismatchError` message:
#: a promotion was decided against criteria that are not the ones its row was
#: pre-registered with. The category's first *judgement* verdict, and the one
#: every sibling module defers to: feature 291's store names it as the refusal
#: it deliberately does not coin, feature 293's decision names it as the
#: verdict it declines to pronounce, and features 295-300 name it as the only
#: comparison against the recorded hash. Spelled beside the base class rather
#: than under the store's word, because a mismatch is not a failed write — the
#: row was written and read back cleanly — and an operator who greps
#: ``promotion_registry_unwritable`` is debugging feature 291's insert, while
#: one who greps this word is reading a verdict that a promotion was judged
#: against the wrong bar. The split is the repair's, which is the rule this
#: module opens with.
CRITERIA_MISMATCH_ERROR_CODE = "criteria_mismatch"


class CriteriaMismatchError(PromotionError):
    """A promotion was decided against criteria that differ from its pre-registered ones.

    Feature 292's class: *"System rejects a promotion whose recorded criteria
    hash differs from the pre-registered value, which returns a criteria_mismatch
    error message."*  Raised by :func:`promotion.criteria_check.
    rejects_mismatched_criteria` and :meth:`promotion.criteria_check.
    CriteriaChecks.rejects_mismatched_criteria` when the digest of the criteria
    the promotion is being decided under does not equal the digest feature 291
    recorded on the row before the evaluation ran.

    **Its noun is a verdict, not a form and not a write, and that is why it is
    the category's first sibling rather than a face of any of the others.**  The
    member's tree splits by *the repair the caller must make*, and this refusal's
    repair is unlike every one beside it:

    * not :class:`PromotionError` — that class carries the pre-registration's
      *ask* face, and a caller whose single ``except`` guards the promotion path
      would read *the body was malformed* where the truth is *this promotion was
      judged against the wrong criteria*;
    * not :class:`PromotionStoreError` — nothing failed to write or read back,
      and the row the judgement was made on is exactly as feature 291 left it.
      The store's word sends an operator to feature 291's insert, which is a
      different act entirely;
    * not :class:`PromotionBlockError` nor :class:`VoidCalibrationError` — the
      two *merit* refusals are findings about the pool's coverage and the
      campaign's calibration, read from other members' tables.  This one is a
      finding about the *decision's own form*: not whether the promotion was
      *good* (that is the deciding evaluation's verdict) but whether it was made
      against the criteria that were fixed for it.  §13 item 7's whole promise is
      that the criteria cannot change after the fact, and this class is the act
      that enforces that promise at decision time — the comparison every sibling
      module explicitly declines to make.
    * not :class:`PromotionDecisionError`, :class:`EpochChargeError`,
      :class:`PromotionWindowError`, :class:`EpochSelectionError` nor
      :class:`PromotionBlockedError` — those report a stamp, a count, a window, a
      budget or a terminal state over the registry and ledger rows; this feature
      writes nothing and reads one column to compare.  An operator who greps any
      of those words for this refusal would be looking for a write that never
      happened, or a resource that was never the problem.

    **Two faces, gathered**, because this feature's caller is the same **gate**,
    and a gate's one failure mode is silence — the argument every gathered class
    in this module states:

    * **the mismatch** — the recomputed hash of the criteria the promotion is
      being decided under differs from the digest feature 291 recorded.  The
      repair is to re-run the deciding evaluation against the pre-registered
      criteria, or to pre-register the criteria the promotion was actually judged
      under against the hypothesis it is really about.
    * **the absence** — no recorded hash to compare against: the node was never
      pre-registered, or its row is still open.  Refused in this class rather than
      the registry's, because the repair is feature 291's or feature 293's act,
      not a criteria fix — and a caller whose single ``except CriteriaMismatchError``
      guards its promotion path must read *this promotion was never registered*
      and not *the registry could not be read*.

    In every one of them the promotion is refused, and that is the state the class
    exists to make loud: a promotion decided against a bar moved after the result
    was known is precisely the post-hoc criterion §13 item 7's *before* exists to
    prevent, and the silence of a boolean a caller forgets to branch on is how it
    would slip through.

    Every message opens with :data:`CRITERIA_MISMATCH_ERROR_CODE` and names the
    node the promotion was about — and, on a mismatch, both hashes — so an
    operator's log line says which promotion was refused, what its criteria were
    fixed as, and what they were decided against.
    """


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


#: The greppable word that opens every :class:`PromotionParentAbsentError`
#: message: a pre-registration named a ``node`` or ``epoch_ledger`` row that
#: the database does not hold, so the registry row has no parent to reference.
#: Spelled beside the store's own word (``promotion_registry_unwritable``) but
#: not in its letter, because the two are two *states of the store* over one
#: table: an operator greps the store's word for *the registry could not be
#: written* and this one for *the row this registration would reference does
#: not exist*, and landing on the wrong one sends them debugging a write that
#: was never the problem.
PROMOTION_PARENT_ABSENT_ERROR_CODE = "promotion_parent_absent"


class PromotionParentAbsentError(PromotionStoreError):
    """A pre-registration named a parent row the database does not hold.

    Raised by :meth:`promotion.pre_register.PreRegistrations.pre_register` —
    through its :meth:`~promotion.pre_register.PreRegistrations._require_parent`
    probe — when the node or the epoch a registration names has no row in the
    table its foreign key points at: a ``node`` the tree does not hold, or an
    ``epoch_ledger`` row nobody sealed.  The body is well formed — six terms, a
    real UUID, a real epoch name — and the store is reachable, and the write is
    refused all the same, because a registry row that references nothing is a
    row no deciding evaluation could ever complete.

    **The tree's second subclass, and the reason it is not a sibling and not a
    new face.**  The store class gathers three faces — the address, the schema
    and the write — and this refusal's repair is unlike every one of them:

    * not the *address* — :class:`PromotionStoreError`'s ``DATABASE_URL`` this
      member cannot speak: the database is reachable here, and the refusal is
      not about reaching it;
    * not the *schema* — a database that cannot be brought to the revision the
      row needs: the tables are all present and migrated, and the write would
      succeed against any parent that existed;
    * not the *write* — the row did not land, or the read-back disagreed:
      nothing was attempted, because the parent was missing before the insert
      was ever reached.

    The repair for all three of those is to the deployment — the URL, the
    migration, the database.  The repair for *this* one is to the
    **registration state**: pre-register the node that was named, or seal the
    epoch, or correct the identity to one that exists.  Gathering it into the
    store's faces would let an operator read *the registry could not be
    written* where the truth is *the thing this registration is about does not
    exist yet* — and those are not the same phone call.

    So the split is *downward*, inside the store class, for the same law the
    conflict class states: **subclass the class raised today**.  The refusal
    was raised as :class:`PromotionStoreError` from the day the store landed,
    and a caller's standing ``except PromotionStoreError`` over the
    pre-registration path has been catching it since; a subclass keeps every
    existing caller's catch true, and a caller that must *answer a status* —
    the HTTP adapter, a script dividing "fix the deployment" from "fix the
    registration" — can now tell a missing parent from an unwritable store by
    class alone, where before both wore one class and the only tell was
    parsing the message.  Its one face names the absent parent table and the
    value that was not found, because that is what makes the refusal
    decidable: an operator reading the message sees *which* of the two foreign
    keys is dangling and *what* name it points at, and knows the repair is to
    the row, not to the database.

    Every message opens with :data:`PROMOTION_PARENT_ABSENT_ERROR_CODE`,
    spelled clear of the store's word in letter as in moment — that one names
    a write that did not land, this one a row that does not exist — so an
    operator greps one word for *the parent this pre-registration named is
    absent* and finds neither a failed write nor a moved bar.
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


#: The greppable word that opens every :class:`EpochChargeError` message:
#: an epoch served a promotion decision and the count §13 item 4 budgets it
#: by did not land in the ledger.  Spelled beside the decision's own word
#: (``promotion_decision_unrecorded``) but not in its letter, because the
#: two are two *writes* to two tables one decision apart: an operator greps
#: the decision's word for *a stamp did not land* and this one for *a count
#: did not land*, and landing on the wrong one sends them debugging the
#: wrong column of the wrong table.
EPOCH_CHARGE_ERROR_CODE = "epoch_charge_unpersisted"


class EpochChargeError(PromotionError):
    """An epoch's running promotion decision count could not be persisted.

    Feature 294's class: *"System persists the running promotion decision
    count against the serving epoch in the epoch_ledger."*  Raised by
    :func:`promotion.epoch.charge_epoch` and
    :meth:`promotion.epoch.EpochCharges.charge` when the count of decided
    ``promotion_registry`` rows an epoch has served could not be re-supplied
    to its ``promotion_decisions_served`` column — and by the module's
    reads, for the malformed asks and the corrupt rows they share with the
    act.

    **Its noun is a count derived from another feature's rows, and that is
    why it is its own class.**  The member's tree splits by *the repair the
    caller must make*, and this refusal's repair is unlike any of the five
    beside it:

    * not :class:`PromotionError` — that class carries the pre-registration's
      *ask* face, and a caller that gathered the two would read *the body was
      malformed* where the truth is *the epoch stands uncharged*;
    * not :class:`PromotionStoreError` — the store's word sends an operator
      to feature 291's insert, and this feature's registry reads are not the
      write that failed;
    * not :class:`PromotionBlockError` nor :class:`VoidCalibrationError` —
      those are the member's two *merit* refusals, findings about the pool
      and the campaign.  This feature judges nothing: the verdict is the
      deciding evaluation's, and the threshold and the retirement are
      features 295-296's machinery reading the figure this act persists;
    * not :class:`PromotionDecisionError` — the closest, and the one the
      split is for.  That class reports *a decision happened and was not
      recorded*, and its repair is to a write against ``promotion_registry``.
      Here the decision *is* recorded, closed and stamped; what did not land
      is a figure in ``epoch_ledger`` — a different write to a different
      table, debugged through a different word.

    Six faces, **gathered** rather than split, because the caller is a gate
    and a gate's one failure mode is silence — the argument the decision's
    and the window's gathered classes state beside it:

    * **the ask** — a malformed node or epoch identity.  Nothing was read and
      nothing was written; the repair is to re-send the ask.
    * **the address** — a ``DATABASE_URL`` this member cannot speak, or a
      database that cannot be brought to the revision the ledger needs.  The
      repair is to the deployment.
    * **the registration absence** — no ``promotion_registry`` row for the
      node, or a row still **open**, so the epoch has served no decision for
      it yet.  The repair is to pre-register first (feature 291) and record
      the decision (feature 293) — the load in this feature's
      ``depends_on="293"``, not an incidental precondition.
    * **the ledger absence** — a decided row booking an epoch whose ledger
      row is gone, reachable only by a write that bypassed this member's
      pragma.  Refused rather than repaired, because recreating the row
      would mean minting a ``sealed_at`` this act must never author.
    * **the shrinking count** — a derivation below the standing figure,
      which only decided rows vanishing can produce; persisting it would
      let feature 295's threshold read a spent epoch as clean.  The repair
      is to the database.
    * **the write** — the count did not land, or could not be read back as
      the derived figure.  The repair is to the database.

    In every one of them the count stands unpersisted, and that is the state
    the class exists to make loud: §13 item 4 retires sequestered epochs
    after *"3 promotion decisions. Track in a ledger. When clean epochs run
    out, the system stops."*  Features 295-297 read exactly this column to
    refuse selection, to declare the terminal state and to deplete the
    remainder — an epoch whose charge quietly did not land reads cleaner
    than it is, which is the reuse the ledger exists to prevent, arrived at
    by silence.

    Every message opens with :data:`EPOCH_CHARGE_ERROR_CODE` and names the
    epoch or the node the charge was about, so an operator's log line says
    which epoch stands uncounted and in which of the six ways.
    """


#: The greppable word that opens every :class:`PromotionWindowError` message:
#: the promotion was asked about and the window it opened could not be
#: answered.  Spelled after the decision's own word
#: (``promotion_decision_unrecorded``) and beside it in meaning but not in
#: letter, because the two are two *acts* over one row: an operator greps the
#: decision's word for *a stamp did not land* and this one for *a window could
#: not be opened*, and landing on the wrong one sends them debugging a write
#: that never happened.
PROMOTION_WINDOW_ERROR_CODE = "promotion_window_unopened"


class PromotionWindowError(PromotionError):
    """A promoted signal's forward measurement window could not be answered.

    app_spec.xml feature 300: *"System timestamps every promoted signal at
    promotion, which creates its forward measurement window."*  Raised by
    :func:`promotion.forward.promotion_window` and
    :meth:`promotion.forward.PromotionWindows.window` when the window a node's
    promotion opened cannot be read off its registry row — because the node was
    never pre-registered, because its deciding evaluation has not run yet, or
    because the row could not be read as a decision at all.

    **Its noun is a reader's question, not a writer's failure, and that is why
    it is its own class.**  The member's tree splits by *the repair the caller
    must make*, and this refusal's repair is unlike any of the six beside it:

    * not :class:`PromotionError` — that class carries the pre-registration's
      *ask* face, and a caller whose single ``except`` guards the window read
      would read *the body was malformed* where the truth is *there is no window
      to open for this node*;
    * not :class:`PromotionStoreError` — nothing was written and no
      pre-registration row failed to land.  The store's word sends an operator
      to feature 291's write, which is a different act entirely;
    * not :class:`PromotionDecisionError` — that class reports a decision that
      *happened and was not recorded*, and its repair is to the write.  This
      feature writes nothing: the row is feature 293's, ``decided_at`` is
      already on it, and what failed is the *reading* of a window off it.  The
      two repairs are different acts performed by different operators — restore
      a record, versus pre-register a promotion or wait for its evaluation;
    * not :class:`EpochChargeError` — that class too reports a write that did
      not land (the ledger's count), while this one reads no ledger and writes
      nowhere: the window is derived entirely from the registry row's own
      stamps, and an operator greps the charge's word for *a count did not
      land* against this one for *a window could not be opened*;
    * not :class:`PromotionBlockError` nor :class:`VoidCalibrationError` — those
      are the member's two *merit* refusals, findings about the pool and the
      campaign.  This feature judges nothing: whether a promotion *stands* is
      the deciding evaluation's verdict and the mismatch check is feature 292's.

    Four faces, **gathered** rather than split, because the caller is a gate and
    a gate's one failure mode is silence — the argument
    :class:`PromotionDecisionError` states and :class:`PromotionBlockError`
    states before it:

    * **the ask** — a malformed node identity, or a window length that is not a
      positive count of days.  Nothing was read; the repair is to re-send the
      ask.
    * **the address** — a ``DATABASE_URL`` this member cannot speak, or a
      database that cannot be brought to the revision the row needs.  The
      repair is to the deployment.
    * **the absence** — no ``promotion_registry`` row for the node, so there is
      no promotion whose window this is; or a row that is still **open**, so the
      deciding evaluation has not run and there is no promotion timestamp yet.
      The repair is to pre-register first (feature 291) or to record the
      decision (feature 293) — §13 item 7's ordering, not an incidental
      precondition.
    * **the row** — a registry row that cannot be read back as a decision.  The
      repair is to the database.

    In every one of them the window is unopened, and that is the state the class
    exists to make loud: the row this feature reads is the one feature 332's
    ``POST /forward/promote`` starts a signal's forward record from, and a
    forward record whose start instant was silently defaulted is precisely the
    *"observation with no vintage"* ``0108``'s own docstring says forward
    testing exists to prevent.

    Every message opens with :data:`PROMOTION_WINDOW_ERROR_CODE` and names the
    node the window was asked about, so an operator's log line says which
    promotion's window could not be opened and in which of the four ways.
    """


#: The greppable word that opens every :class:`EpochSelectionError` message:
#: the epoch's §13 item 4 budget is spent and further selection of it is
#: refused.  Spelled beside the charge's own word
#: (``epoch_charge_unpersisted``) but not in its letter, because the two are
#: the *write* and the *refusal* over one column: an operator greps the
#: charge's word for *a count did not land* and this one for *a count reached
#: its budget*, and landing on the wrong one sends them debugging a write
#: that succeeded when the finding is §13 item 4's own law.
EPOCH_SELECTION_ERROR_CODE = "epoch_budget_spent"


class EpochSelectionError(PromotionError):
    """Further selection of a sequestered epoch was refused: its budget is spent.

    Feature 295's class: *"System rejects further selection of a sequestered
    epoch once it has served three promotion decisions."*  Raised by
    :func:`promotion.selection.rejects_further_selection` and
    :meth:`promotion.selection.EpochSelections.select` when the count feature
    294 persists against an epoch has reached §13 item 4's budget of three —
    and by the module's own paths for the malformed asks, the unreachable
    addresses and the unreadable rows they share with the act.

    **Its noun is a resource the system has spent, and that is why it is its
    own class.**  The member's tree splits by *the repair the caller must
    make*, and this refusal's repair is unlike any of the seven beside it:

    * not :class:`PromotionError` — the pre-registration's *ask* face.  The
      selection's ask may be well formed; what is wrong is the epoch's
      history, and re-sending the ask cannot fix that;
    * not :class:`PromotionStoreError` — nothing failed to write, because
      this feature writes nothing at all.  The count is on the row; the
      refusal is the point, not a failure;
    * not :class:`PromotionBlockError` nor :class:`VoidCalibrationError` —
      the two *merit* refusals are findings about the pool's coverage and
      the campaign's calibration, read from other members' tables.  This
      one's noun is the sequestered holdout itself — the system's own
      depleting resource — and its repair is not to grow coverage or to
      re-plan a campaign: it is to select a clean epoch, or to stop, the
      terminal state §13 item 4 explicitly legitimates;
    * not :class:`PromotionDecisionError` nor :class:`EpochChargeError` —
      the closest pair, and the ones the split is for.  Those report a
      stamp and a count that *did not land*, and their repair is to the
      database.  Here both landed; the figure this refusal stands on is
      exactly the one feature 294 persisted, and conflating the classes
      would send an operator debugging a write that succeeded when the
      finding is that §13 item 4's budget has been served;
    * not :class:`PromotionWindowError` — that class reports a question
      that *cannot be answered* (a node nobody registered, a row still
      open), with a repair in the registration state.  This one's question
      is answered: the epoch is sealed, its count is on the row, and the
      answer is *no*.  An operator who greps the window's word for this
      refusal would be looking for a missing write that never happened.

    Five faces, **gathered** rather than split, because the caller is a gate
    and a gate's one failure mode is silence — the argument every gathered
    class above states one feature over the last:

    * **the ask** — a malformed epoch name, or a served count that is not a
      non-negative count.  Nothing was read and nothing was judged; the
      repair is to re-send the ask.
    * **the address** — a ``DATABASE_URL`` this member cannot speak.  The
      repair is to the deployment.
    * **the absence** — no ``epoch_ledger`` row for the epoch, which is
      *nobody sealed it*, a different fact from a sealed epoch serving
      zero.  The repair is the sealing process's act, not a booking.
    * **the spend** — the count has reached §13 item 4's budget of three.
      The repair is a clean epoch (feature 297's depleting count reports
      how many remain) or the stop §13 item 4 calls legitimate.
    * **the row** — a ledger row that cannot be read back.  The repair is
      to the database.

    In every one of them the epoch stands unjudged for selection, and that
    is the state the class exists to make loud: a spent epoch that quietly
    went unjudged is read as clean and booked a fourth time, which is the
    exact reuse §13 item 4's ledger exists to prevent, arrived at by
    silence rather than by decision.

    Every message opens with :data:`EPOCH_SELECTION_ERROR_CODE` and names
    the epoch the selection was about, so an operator's log line says which
    sequestered epoch was refused and in which of the five ways.
    """


NO_CLEAN_EPOCH_REMAINS_CODE = "no_clean_epoch_remains"


class PromotionBlockedError(PromotionError):
    """Promotion was blocked: no clean sequestered epoch remains to run on.

    Feature 296's class: *"System blocks promotion when no clean sequestered
    epoch remains, which returns a terminal state rather than reusing a
    retired epoch."*  Raised by :func:`promotion.terminal.
    blocks_when_no_clean_epoch_remains` and :meth:`promotion.terminal.
    TerminalStates.blocks` when every sequestered epoch has served §13 item
    4's budget of three — or when the ledger holds no epoch at all — and by
    the module's own paths for the malformed asks and the unreachable
    addresses they share with the act.

    **Its noun is the exhausted holdout itself, and that is why it is its
    own class.**  The member's tree splits by *the repair the caller must
    make*, and this refusal's repair is unlike any of the eight beside it:

    * not :class:`PromotionError` — the pre-registration's *ask* face.  The
      ask may be well formed; what is wrong is the whole ledger, and
      re-sending the ask cannot fix that;
    * not :class:`PromotionStoreError` — nothing failed to write, because
      this feature writes nothing at all.  Every count is on its row, and
      that landing is exactly the fact the refusal stands on;
    * not :class:`PromotionBlockError` nor :class:`VoidCalibrationError` —
      the two *merit* refusals are findings about the pool's coverage and
      the campaign's calibration, read from other members' tables.  This
      one's noun is the sequestered holdout itself — the system's own
      depleting resource — and its repair is not to grow coverage or to
      re-plan a campaign: it is to stop, the terminal state §13 item 4
      explicitly legitimates;
    * not :class:`PromotionDecisionError` nor :class:`EpochChargeError` —
      those report a stamp and a count that *did not land*, and their repair
      is to the database.  Here both landed on every row; the figure this
      refusal stands on is exactly the one feature 294 persisted, and
      conflating the classes would send an operator debugging a write that
      succeeded when the finding is that §13 item 4's budget has been served
      on every epoch;
    * not :class:`EpochSelectionError` — the closest of the eight, and the
      one the split is for.  That class reports *one epoch's budget is
      spent*, with a repair of *select a clean epoch*.  This one reports
      *every epoch is spent*, with **no clean epoch left to select** — the
      terminal state, not a selection to redirect.  An operator who greps
      :data:`EPOCH_SELECTION_ERROR_CODE` for this refusal would be looking
      for a clean epoch that does not exist;
    * not :class:`PromotionWindowError` — that class reports a question that
      *cannot be answered* (a node nobody registered, a row still open), with
      a repair in the registration state.  This one's question is answered,
      and the answer is *no*: every epoch is spent, or there was never one to
      spend.  An operator who greps the window's word for this refusal would
      be looking for a missing write that never happened.

    Two faces, **gathered** rather than split, because the caller is a gate
    and a gate's one failure mode is silence — the argument every gathered
    class above states one feature over the last:

    * **the verdict** — every sequestered epoch has served §13 item 4's
      budget, or the ledger holds no epoch at all.  The repair is to stop,
      the terminal state §13 item 4 calls legitimate.
    * **the ask** — a served count that is not a non-negative count.  Nothing
      was judged; the repair is to re-send the ask.

    In every one of them promotion is blocked and the caller must not
    proceed, and that is the state the class exists to make loud: a system
    that quietly had no clean epoch to run on would book a promotion against
    nothing, which is the reuse §13 item 4's ledger exists to prevent,
    arrived at by silence rather than by decision.

    Every message opens with :data:`NO_CLEAN_EPOCH_REMAINS_CODE` and names
    the exhausted ledger — how many epochs were judged, how many were spent,
    and the terminal state §13 item 4 calls legitimate — so an operator's log
    line says the system has stopped and in which of the two ways.
    """
