"""Refusing further selection of a spent epoch — feature 295, §13 item 4's stop.

app_spec.xml, "Promotion & Epoch Governance", feature 295: *System rejects
further selection of a sequestered epoch once it has served three promotion
decisions.*  Its declared parent is feature 294 — the charge, whose column
this gate reads — and the law the sentence serves is
docs/alpha-engine-prd.md §13 item 4, quoted whole because both of its
sentences are this module's brief:

    Sequestered epochs are retired permanently after **3 promotion
    decisions**. Track in a ledger. When clean epochs run out, the system
    stops. That is a legitimate terminal state.

**What a selection is: the act of naming a sequestered epoch to serve a
promotion.**  A promotion spends a holdout from the moment its criteria are
fixed against one — feature 291's pre-registration books the epoch by name,
``promotion_registry.epoch_id``, before the evaluation that decides it — so
"selecting" an epoch is the caller's half of that booking: *which* sealed
holdout will this promotion be judged on.  This gate is the system's half:
*whether that epoch may still be spent*.  It stands in front of the booking
rather than inside it — the caller runs it, then pre-registers against the
row it answered with — and it is deliberately not a route: feature 291's
``POST /promotion/pre-register`` is the category's one exposure, and a second
endpoint that only refuses would be a second door to the same table with
none of the booking's obligations attached.

**The budget is three, and the comparison is ``>=``.**  :data:`SEQUESTERED_EPOCH_BUDGET`
is §13 item 4's own number, spelled once here because everything else in the
member states where it lives but not what it is — ``0110``'s docstring says
*"feature 295 reads ``promotion_decisions_served >= 3`` against exactly this
column"*, :mod:`promotion.epoch` says *"the threshold is not this module's"*
and declines to carry a predicate for it, and :class:`~promotion.epoch.ServingEpoch`
carries no budget method for the same reason.  This module is the one place
the number lives, and the comparison it makes is the one ``0110`` spells:
**``>=``**, not ``==``.  Equality is refusal because *"once it has served
three"* names the epoch that has served its whole budget — the selection the
gate refuses is the *fourth* booking, not the third; and a count *above*
three is refused because a figure past the budget is not a cleaner epoch for
exceeding it.  No writer in this member can produce a count above three (the
charge derives the figure from one row per node, and three bookings is all
§13 item 4 allows), so a higher number is a hand's edit or a future writer's
— and either way the epoch has served at least its budget, which is the
whole of the question this gate asks.

**The count is the whole of the law here, and every other value on the row
is another feature's.**  ``retired`` is feature 296's flag — the exhaustion
machinery's own persistence of the verdict this gate pronounces on the
figures — and this module deliberately does not judge it: a row flagged
retired with a count under budget is *admitted* here, because "never reusing
a retired epoch" is §13 item 4's second sentence and feature 296's reader,
while this feature is the first sentence's threshold; two modules, two
clauses, one law.  ``sealed_at`` is the sealing process's fact and judges
nothing here.  And the promotion's own merits are nowhere in the ledger at
all: whether the promotion *stands* is the deciding evaluation's verdict,
feature 292's mismatch is the only comparison against the recorded hash, and
features 298's and 299's refusals read the campaign and the coverage ledger
— tables this act never opens.  A gate that re-derived any of those would be
three features in one module with none of their suites.

**It reads the ledger through feature 294's own seam, and that is why it
owns no connection at all.**  :meth:`~promotion.epoch.EpochCharges.epoch`
already answers *this epoch's row* — the four columns, validated, with the
doubled-row and corrupt-row cases refused in the charge's vocabulary — and
a second ``SELECT`` over ``epoch_ledger`` here would be a second reading of
one table, the discipline :mod:`promotion.forward` states for the registry
and :mod:`promotion.epoch` states for its count.  So
:class:`EpochSelections` is constructed **over** an
:class:`~promotion.epoch.EpochCharges`, like :class:`~promotion.forward.PromotionWindows`
over the decision store: it holds no connection, runs no bootstrap, authors
no DDL and spells no statement — and :mod:`promotion.schema` therefore gains
**no fifth order**, because the set a bootstrap runs is the set the act's
own statements name and this act's statements name nothing at all.  The one
table the read needs is brought up by the charge store's own connect, which
is the rule's smallest illustration yet: a dependency stated as a
composition rather than as a list.

**An epoch nobody sealed is refused, never read as clean.**  ``0110``'s
``promotion_decisions_served INT NOT NULL DEFAULT 0`` exists — in its own
docstring's words — so that *"an absent row has to keep meaning 'epoch
nobody sealed', a different fact"* from a sealed epoch that has served zero.
This gate keeps the two apart the same way: ``None`` off the seam is an
epoch the sealing process never sealed, and reading it as a zero count
would make *any* never-sealed name selectable — sequestration bypassed by a
typo, which is the exact reuse §13 item 4's ledger exists to prevent,
arrived at without even the trouble of spending one.  Refused by name, with
the repair being the sealing process's act: the row *is* the sealing event,
in ``0110``'s own words, and this gate must not mint one for the same
reason the charge must not.

**It writes nothing, and the refusal is the act.**  The count is already
persisted — feature 294's charge re-supplied it, and the figure this gate
refuses on is the figure that landed; the ``retired`` flag is feature
296's to set, not this gate's; and there is no "selection" row to record,
because the booking itself — feature 291's insert, which names the epoch —
is the record of a selection that proceeded.  A refused selection leaves
the database byte-identical to a permitted one's aftermath apart from the
booking the caller went on to make, which is the stance feature 285 states
for its own verdict (*"a verdict is not a persist"*) and
:mod:`promotion.calibration` restates one member over: the evidence is
already on the row, and a second row carrying a copy of it would be a
second spelling of one fact, free to disagree with the row a reader would
check.

**The answer when it does not raise is the row itself.**  A
:class:`~promotion.epoch.ServingEpoch` — the value the judgment was made
on, with the epoch's name, its sealing instant, its standing count and its
flag — so the caller that goes on to book the epoch through feature 291's
act holds the row it was permitted under and does not read the ledger a
second time.  It is the value it compared and not a derived one: the
per-epoch remainder ``budget − served`` is arithmetic any caller can do
from the two figures, and the figure that makes exhaustion *visible* — how
many clean epochs remain, the depleting count — is a question about the
whole table and feature 297's, not this gate's answer about one row.

**The comparison is pure, and the gate is the read plus it.**
:func:`rejects_further_selection` is §13 item 4's test on its own — the
epoch and the served count a reader found, for the caller that already
holds the figure: a test judging the boundary, a report, features 296-297's
machinery reaching the row its own way.  :meth:`EpochSelections.select`
performs the read through the seam and delegates to it, so there is one
comparison in the member and the act cannot disagree with the pure
judgment a caller may use directly — the split
:func:`~promotion.calibration.rejects_void_calibration` and
:meth:`~promotion.calibration.PromotionCalibrations.rejects_void_promotion`
state for the calibration gate.

**A gate's refusals arrive in its own vocabulary, or its caller develops a
hole.**  The seam raises :class:`~promotion.errors.EpochChargeError` — a
database the member cannot speak, a ledger row that cannot be read back,
two rows where the key admits one — and every one of those is translated
here into :class:`~promotion.errors.EpochSelectionError`, the shape
:func:`promotion.epoch._translated` takes toward the decision store's own
vocabulary: a caller whose single ``except EpochSelectionError`` guards
its selection path must not be defeated by a refusal phrased for a charge
it never made.  The inner message is carried through whole; only the frame
changes, and the frame names which act was being performed.

**Repeatable, and no cache.**  Selection judges the row on every call: an
epoch under budget answers its row as many times as it is asked, and the
charge another process lands between two asks moves the answer — the stance
every store in this member takes toward its rows, taken here by a reader
toward the one row its whole verdict is a function of.

**No component, no seat, no router, no second builder.**  The member's
registered surface stays feature 291's one store, for the reason every
sibling states: a builder takes no arguments and is built on every
``create_app()`` call, while *which epochs are still clean* is a fact about
rows that move — a charge lands, an epoch spends — and no composition can
supply it.  The gate is constructed from the charge store by the caller
that has one (or from a URL through :func:`select_epoch`), and the composed
``promotion`` component is untouched and still answers one
question.

**Stdlib only, and import-cheap.**  ``os``, ``collections.abc`` and
``typing`` at module scope plus this member's own four modules — not even
``sqlite3``, because the connection is the charge store's and this module
never opens one — so the factory's scan imports this package for the
near-nothing it always did and a selection costs its caller only the store
it already held.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from .epoch import (
    PROMOTION_DECISIONS_SERVED_COLUMN,
    EpochCharges,
    ServingEpoch,
)
from .errors import (
    EPOCH_SELECTION_ERROR_CODE,
    EpochSelectionError,
    PromotionError,
)
from .pre_register import (
    DATABASE_URL_ENV,
    EPOCH_ID_COLUMN,
    _validated_epoch_id,
)
from .schema import EPOCH_LEDGER_TABLE

__all__ = [
    "SEQUESTERED_EPOCH_BUDGET",
    "EpochSelections",
    "rejects_further_selection",
    "select_epoch",
]

#: §13 item 4's number: the promotion decisions a sequestered epoch may
#: serve before the system refuses its further selection.  Spelled once,
#: here, because every other statement of the boundary in this member names
#: this feature as the number's home — ``0110``'s docstring (*"feature 295
#: reads ``promotion_decisions_served >= 3``"*), :mod:`promotion.epoch`'s
#: (*"the threshold is not this module's"*), and
#: :class:`~promotion.epoch.ServingEpoch`'s, which carries no budget
#: predicate for exactly this reason.  A second spelling anywhere else
#: would be a second place the budget lives, free to disagree with the one
#: the gate compares against.
SEQUESTERED_EPOCH_BUDGET = 3


# -- Validation --------------------------------------------------------------------


def _translated(exc: PromotionError, what: str) -> EpochSelectionError:
    """Re-raise a sibling's refusal in this feature's vocabulary.

    The seam rule this workspace states at every member boundary, applied
    *inside* one member — the shape :func:`promotion.epoch._translated`,
    :func:`promotion.decision._translated` and
    :func:`promotion.forward._translated` take toward the same validators.
    The charge store raises :class:`~promotion.errors.EpochChargeError` for
    an address it cannot speak and a ledger row it cannot read, and feature
    291's calendar raises ``PromotionError`` for a malformed name; a caller
    whose single ``except EpochSelectionError`` guards its selection path
    must not be defeated by either — it would read *the epoch stands
    uncharged* or *the ask was malformed* where the truth is *this epoch
    was not judged selectable*, and would go on to book a spent or an
    unsealed epoch, the silence §13 item 4's ledger exists to make
    impossible.  The inner message is carried through, so nothing an
    operator needs is lost; only re-framed, with the frame naming which act
    was being performed.

    ``type(exc)(...)`` is deliberately **not** used: here the class itself
    is the thing being corrected, exactly as in the three siblings.
    """
    return EpochSelectionError(
        f"{EPOCH_SELECTION_ERROR_CODE}: the {what} could not be read to "
        f"judge this selection: {exc}"
    )


def _selection_epoch_id(value: Any) -> str:
    """Return ``value`` as an epoch's name, or refuse it in *this* vocabulary.

    Feature 291's epoch validator is the one spelling this member has for
    *a name the ledger keys by* — non-empty stripped text, the near-miss a
    trailing newline would otherwise persist as a second name for one epoch
    — and the epoch being selected is exactly that value, so the rule is
    *used* rather than restated, the move every sibling makes.  What it
    raises is ``PromotionError``, the member's ask face, and that is what
    the wrapper is for: the refusal has to arrive as a *selection*
    refusal, or a caller's single ``except EpochSelectionError`` walks
    through it and the epoch stands unjudged.
    """
    try:
        return _validated_epoch_id(value)
    except PromotionError as exc:
        raise _translated(exc, EPOCH_ID_COLUMN) from exc


def _validated_served_count(value: Any, epoch: str) -> int:
    """Return ``value`` as a served count, or refuse what is not one.

    A non-negative ``int``, with ``bool`` refused first — ``True`` is ``1``
    in Python, and a flag where a count belongs would silently answer one
    decision nobody recorded.  The *rule* is
    :func:`promotion.epoch._validated_served_count`'s own, restated here
    rather than reused for the reason that module restates
    :func:`promotion.forward._validated_window_days`'s: the sibling's
    message opens with the charge's code word and names feature 294, so a
    caller who handed this gate a fraction or a flag would be told about a
    write that never happened instead of the judgment that could not be
    made.  Negative is refused because no honest count of rows is negative
    and no writer in this member could have landed one.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise EpochSelectionError(
            f"{EPOCH_SELECTION_ERROR_CODE}: {PROMOTION_DECISIONS_SERVED_COLUMN} "
            f"must be a non-negative integer — got {value!r} "
            f"({type(value).__name__}); the count is §13 item 4's budget of "
            "the promotion decisions a sequestered epoch has served, and a "
            f"figure that is not a count of rows is not one {epoch}'s row "
            "could carry — features 294's charge derives it from the closed "
            "registry rows or nothing does (feature 295)"
        )
    if value < 0:
        raise EpochSelectionError(
            f"{EPOCH_SELECTION_ERROR_CODE}: {PROMOTION_DECISIONS_SERVED_COLUMN} "
            f"must be a non-negative integer — got {value!r}. The count is "
            "derived from the closed promotion_registry rows feature 293's "
            "listing holds against the epoch, and no count of rows is "
            "negative — a negative figure handed to this gate is an edit no "
            "writer in this workspace produced, and judging a selection on "
            "it would be refusing or admitting an epoch on a number nobody "
            "derived (feature 295)"
        )
    return value


# -- The verdict -------------------------------------------------------------------


def rejects_further_selection(
    epoch_id: Any, promotion_decisions_served: Any
) -> int:
    """Refuse further selection of a spent epoch — feature 295's judgment.

    Takes the sequestered epoch and the served count a reader found on its
    ledger row, and either the epoch may be selected or it may not.  This
    is the whole of the feature's sentence — *"System rejects further
    selection of a sequestered epoch once it has served three promotion
    decisions"* — as one comparison, and it is the seam for the caller that
    **already holds the figure**: a test judging the boundary, a report, a
    later feature that reached the row its own way.  The caller that holds
    only the epoch's name asks :meth:`EpochSelections.select` instead,
    which performs the read through feature 294's own seam and then
    delegates here, so there is one comparison in the member and not two.

    **It raises** :class:`~promotion.errors.EpochSelectionError` when the
    count has reached :data:`SEQUESTERED_EPOCH_BUDGET` — ``>=``, the
    spelling ``0110``'s own docstring gives this feature, so an epoch that
    has *exceeded* its budget is refused on the same comparison rather
    than falling through an equality pin — and returns the count otherwise.
    Raising rather than answering a boolean is the stance
    :func:`promotion.calibration.rejects_void_calibration` takes for
    exactly this caller: the gate is the last line before the epoch is
    booked, so the stop has to be the function's own act rather than a
    branch every caller must remember to make, and the caller that forgets
    is precisely a fourth promotion judged on a holdout that had already
    served three.

    **What it returns when it does not raise** is the count it judged, so
    the caller that wants to log or carry it does not read the row a second
    time.  It is the value it compared and not a derived one: the remaining
    budget is arithmetic from the two figures, and the depleting count of
    clean epochs — the figure that shows exhaustion coming — is feature
    297's question about the whole table, not this judgment about one row.

    Refuses, in this order, each naming what it is about and both in
    :class:`~promotion.errors.EpochSelectionError`:

    1. an ``epoch_id`` that is not non-empty text — the refusal must name
       *which* epoch was spent, and a name that states nothing names no row
       an operator could go and read;
    2. a ``promotion_decisions_served`` that is not a non-negative count —
       there is no budget to compare, and neither refusing nor admitting an
       epoch on a figure nobody derived would be honest.
    """
    epoch = _selection_epoch_id(epoch_id)
    served = _validated_served_count(promotion_decisions_served, epoch)
    if served < SEQUESTERED_EPOCH_BUDGET:
        return served
    raise _spent_selection(epoch, served)


# -- The gate ----------------------------------------------------------------------


class EpochSelections:
    """The gate that refuses a spent epoch's further selection — 295's act.

    Constructed **over** an :class:`~promotion.epoch.EpochCharges` (or
    anything with its ``epoch`` seam), never over a URL: every fact this
    gate judges comes from feature 294's own read, so it holds no
    connection, runs no bootstrap, authors no DDL and spells no statement.
    The wiring is the shape :class:`~promotion.forward.PromotionWindows`
    takes toward the decision store, and it is duck-checked rather than
    ``isinstance``-guarded for the reason that class states: the factory's
    scan imports this member under a synthetic module name, so the
    *composed* charge store is structurally an ``EpochCharges`` but never
    the same class object a direct import yields, and a class check here
    would refuse the very component the factory hands out.

    **There is no state to hold.**  A memo of counts this process had
    already judged would make *may this epoch still be selected?* a
    question about this process's history — and the answer moves: a charge
    lands in another process a moment after this one asked, and the epoch
    that was clean is spent.  The ledger row is the only record of what an
    epoch has served, so it is the only thing a verdict is drawn from, on
    every call, in every process.
    """

    #: The one verb of feature 294's read seam this gate drives, and the
    #: whole of what it requires: ``epoch`` for one epoch's ledger row.
    #: Duck-typed as a *set of verbs* rather than class-checked, for the
    #: reason the class docstring gives — the composed store and the
    #: directly imported one are different class objects with the same
    #: seam, and either is a valid thing to judge through.
    _SEAM = ("epoch",)

    def __init__(self, charges: EpochCharges) -> None:
        """Wire the gate to the charge store it reads through.

        The seam is checked here, before any call, because it is a fact
        about the *gate* rather than about any one selection: a reader with
        nothing to read through names no ledger, and one that accepted it
        would fail identically on every judgment — the wrong place to
        discover a wiring fault.  A ``TypeError`` rather than an
        :class:`~promotion.errors.EpochSelectionError`, because a gate
        that cannot read is a *programming* error and not a promotion
        state: no operator can fix it by sealing or spending anything.
        """
        missing = [
            verb
            for verb in self._SEAM
            if not callable(getattr(charges, verb, None))
        ]
        # A *class* exposes its methods as plain functions, so it passes
        # the verb check above and then fails on the first call with a
        # missing positional argument — a confusing way to learn that the
        # instance was never built.  ``type`` is the one thing that is
        # never a composed store, so the check costs no duck-typing
        # latitude.
        if isinstance(charges, type):
            missing = missing or ["<an instance, not the class>"]
        if missing:
            raise TypeError(
                "EpochSelections reads a charge store — something exposing "
                f"{' and '.join(self._SEAM)} — got {type(charges).__name__}, "
                f"which is missing {', '.join(missing)}. A selection is "
                "judged on the ledger row feature 294's own read answers "
                "with, so this gate reads through that store rather than a "
                "second reading of the table (feature 295)"
            )
        self._charges = charges

    # -- Construction -------------------------------------------------------

    @classmethod
    def from_env(
        cls, env: Mapping[str, str] | None = None
    ) -> EpochSelections | None:
        """The gate over the charge store ``DATABASE_URL`` names, or ``None``.

        Resolves the charge store exactly as the member's own builder
        resolves its registry (:meth:`~promotion.epoch.EpochCharges.
        resolve`), so the epochs a caller judges selectable and the counts
        the deployment charged always point at the same database.  No
        ``DATABASE_URL`` composes no gate — an unconfigured deployment is a
        discoverable state, not an error — while the caller whose promotion
        must be booked against a clean epoch is, again, the one that must
        not find itself in it.
        """
        charges = EpochCharges.resolve(env)
        return None if charges is None else cls(charges)

    @property
    def charges(self) -> EpochCharges:
        """The charge store this gate reads through — feature 294's seam."""
        return self._charges

    # -- Feature 295: the selection -------------------------------------------

    def select(self, epoch_id: Any) -> ServingEpoch:
        """Judge one epoch selectable — feature 295's act.

        The steps, in the order they must happen:

        1. **Validate the ask** — the epoch as a name — before anything is
           read, so a malformed selection is refused without touching a
           database and a refused call leaves no file behind.
        2. **Read the epoch's ledger row** through feature 294's own seam.
           An absent row is refused by name — there is no sequestered
           epoch to select, and the repair is the sealing process's act,
           not a booking; reading the absence as a zero count would make
           any never-sealed name selectable, sequestration bypassed by a
           typo.  A refusal the seam raises — an address the member cannot
           speak, a row that cannot be read back — arrives translated into
           this feature's vocabulary.
        3. **Delegate the comparison** to :func:`rejects_further_selection`,
           so the member has one spelling of §13 item 4's test and this
           act cannot disagree with the pure judgment a caller may use
           directly.

        **The answer is the epoch as selected**: the
        :class:`~promotion.epoch.ServingEpoch` the judgment was made on,
        with its standing count and its flag — the row the caller books
        against through feature 291's act, held rather than re-read.  The
        count it carries is the figure the comparison cleared, and the
        flag is carried faithfully and judged nowhere: retirement's
        persistence is feature 296's machinery, and this gate's whole law
        is the count.

        **It writes nothing.**  The count was feature 294's to persist, the
        ``retired`` flag is feature 296's to set, and the record of a
        selection that *proceeded* is the booking itself — feature 291's
        row, which names the epoch.  A refused selection leaves the
        database exactly as it was.

        Refuses, in this order, each naming what it is about and all in
        :class:`~promotion.errors.EpochSelectionError`: a malformed epoch
        name, then — from the seam — a ``DATABASE_URL`` this member cannot
        speak or a ledger row that cannot be read back, then an epoch
        nobody sealed, then the spend itself: a count that has reached
        :data:`SEQUESTERED_EPOCH_BUDGET`.
        """
        epoch = _selection_epoch_id(epoch_id)
        standing = self._epoch_of(epoch)
        if standing is None:
            raise _unsealed_epoch(epoch)
        rejects_further_selection(epoch, standing.promotion_decisions_served)
        return standing

    # -- The words ----------------------------------------------------------

    def _epoch_of(self, epoch: str) -> ServingEpoch | None:
        """One epoch's ledger row, or ``None`` when the table holds none.

        Feature 294's own read spelling —
        :meth:`~promotion.epoch.EpochCharges.epoch` — used rather than
        restated, so the row this gate refuses on and the row the charge
        answered with cannot be two readings of one table, the discipline
        :meth:`~promotion.forward.PromotionWindows._decision_of` states
        toward the same seam.  A refusal the read raises is translated
        here for the reason every wrapper in this member exists: a caller
        whose single ``except EpochSelectionError`` guards the selection
        must not be defeated by a refusal phrased for a charge it never
        made — it would read *the epoch stands uncharged* where the truth
        is *this epoch was not judged selectable*.

        ``None`` means the ledger holds no row for the epoch at all — a
        different fact from a sealed epoch that has served zero, which is
        why the caller refuses it rather than collapsing it into the
        clean case.
        """
        try:
            return self._charges.epoch(epoch)
        except EpochSelectionError:
            raise
        except PromotionError as exc:
            raise _translated(exc, "epoch's ledger row") from exc

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"{type(self).__name__}(charges={self._charges!r})"


# -- The refusals ------------------------------------------------------------------


def _spent_selection(epoch: str, served: int) -> EpochSelectionError:
    """The spend refusal: §13 item 4's budget has been served, and the stop is here.

    The feature's own case, phrased with both figures and the repair in
    it.  The budget is not this gate's invention to loosen — it is the
    PRD's own number, and the sentence after it names what happens when
    the clean epochs run out: the system stops, and that is *a legitimate
    terminal state* — so the repair this refusal offers is never "spend it
    anyway" and never a reuse dressed as a retry: it is a clean epoch, or
    the stop.  Nothing is written by the refusal itself; the count stands
    as feature 294 persisted it, and the flag that would record the
    retirement is feature 296's to place.
    """
    return EpochSelectionError(
        f"{EPOCH_SELECTION_ERROR_CODE}: {EPOCH_ID_COLUMN} {epoch} has "
        f"served {served} promotion decision{'s' if served != 1 else ''} "
        f"against §13 item 4's budget of {SEQUESTERED_EPOCH_BUDGET}, so "
        "further selection of this sequestered epoch is refused. "
        "docs/alpha-engine-prd.md §13 item 4: *Sequestered epochs are "
        "retired permanently after 3 promotion decisions. Track in a "
        "ledger. When clean epochs run out, the system stops. That is a "
        "legitimate terminal state.* Every promotion decision spends a "
        "little of the holdout it was judged on — each decision is a "
        "chance for information about the epoch to leak into what gets "
        "promoted — so an epoch selected again after serving its budget "
        "is exactly the reuse the ledger exists to prevent, arrived at "
        "one booking later. Nothing was written: the count stands as "
        "feature 294's charge persisted it, and the ``retired`` flag is "
        "feature 296's machinery, not this gate's. Select a clean epoch "
        "(feature 297's depleting count reports how many remain), and "
        "when none remains, stop — the terminal state §13 item 4 calls "
        "legitimate rather than a reuse it forbids (feature 295)"
    )


def _unsealed_epoch(epoch: str) -> EpochSelectionError:
    """The absence refusal: there is no sequestered epoch here to select.

    ``0110``'s ``DEFAULT 0`` exists so that *freshly sealed* and *never
    sealed* stay two answers, and this gate keeps them apart: an absent
    row is an epoch the sealing process never sealed, not a clean one, and
    a gate that read the absence as a zero count would make any
    never-sealed name selectable — sequestration bypassed by a typo, which
    is the reuse §13 item 4's ledger exists to prevent arrived at without
    even spending an epoch.  Refused rather than repaired, because the one
    repair this gate must not offer is creating the row: ``sealed_at`` is
    the sealing process's fact, and a selection that minted one would be
    fabricating the moment of sequestration — the same refusal
    :func:`promotion.epoch._absent_epoch` makes for the charge's read.
    """
    return EpochSelectionError(
        f"{EPOCH_SELECTION_ERROR_CODE}: {EPOCH_LEDGER_TABLE} holds no row "
        f"for {EPOCH_ID_COLUMN} {epoch}, so there is no sequestered epoch "
        "to select. 0110 declares promotion_decisions_served INT NOT NULL "
        "DEFAULT 0 precisely so that a freshly sealed epoch's zero stays "
        "apart from an epoch nobody sealed — the zero is a fact feature "
        "297's remainder reads, and the absence is a fact this gate "
        "refuses rather than reads as clean, because a never-sealed name "
        "selected is sequestration bypassed by a typo. Seal the epoch "
        "first — the sealing process's act, and the row *is* the sealing "
        "event in 0110's own words, which this gate must not mint any more "
        "than the charge may — then select it (feature 295)"
    )


# -- The module-level spellings -----------------------------------------------------


def _resolved_url(
    database_url: str | None, env: Mapping[str, str] | None
) -> str:
    """The URL the module-level spellings act on, or a refusal naming the gap.

    The same seam :func:`promotion.epoch.charge_epoch` and
    :func:`promotion.calibration.rejects_void_promotion` resolve, restated
    in this feature's vocabulary: an explicit URL wins, else
    ``DATABASE_URL``, and a caller that names neither — or names one that
    is only whitespace, which names no database either — is refused *by
    name* rather than silently doing nothing.  The silence is the
    dangerous failure here and not the refusal: a selection that quietly
    went unjudged is a spent epoch read as clean, which is the state
    §13 item 4's ledger exists to make impossible.
    """
    source = os.environ if env is None else env
    url = (
        database_url
        if database_url is not None
        else source.get(DATABASE_URL_ENV, "")
    )
    if not isinstance(url, str) or not url.strip():
        raise EpochSelectionError(
            f"{EPOCH_SELECTION_ERROR_CODE}: no database is named — neither "
            f"a database_url nor {DATABASE_URL_ENV} states one, so there "
            "is no ledger row to read this epoch's served count from. "
            "§13 item 4 budgets sequestered epochs by exactly that count, "
            "and a gate resolved from nothing is a refusal rather than a "
            "silent no-op — a selection that quietly went unjudged is a "
            "spent epoch read as clean (feature 295)"
        )
    return url.strip()


def select_epoch(
    epoch_id: Any,
    *,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> ServingEpoch:
    """Judge one epoch selectable — the module-level spelling of 295's act.

    The feature's sentence as one call, for the caller that wants the gate
    without holding stores — the promotion path's line before feature
    291's booking names the epoch.  The gate is resolved from
    ``database_url``, else from ``DATABASE_URL``, exactly as
    :func:`promotion.epoch.charge_epoch` and
    :func:`promotion.calibration.rejects_void_promotion` resolve theirs,
    and it is composed over the charge store the same URL wires — one
    database by construction, never two the caller has to keep
    consistent.

    An :class:`~promotion.errors.EpochSelectionError` from the gate or the
    resolution propagates unwrapped: the refusal already names the epoch
    and the fact, and re-wrapping it here would put a second message in
    front of the one an operator needs.
    """
    url = _resolved_url(database_url, env)
    return EpochSelections(EpochCharges(url)).select(epoch_id)
