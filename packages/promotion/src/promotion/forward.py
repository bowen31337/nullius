"""The forward measurement window a promotion opens — feature 300.

app_spec.xml, "Promotion & Epoch Governance", feature 300: *System timestamps
every promoted signal at promotion, which creates its forward measurement
window.*  Its declared parent is feature 293 — the decision, which placed the
stamp — and the sentence is the third clause of the loop
``docs/alpha-engine-prd.md`` §5 calls *"the only source of genuinely
uncontaminated evidence"*::

    - Every promoted signal is timestamped and its live forward IC tracked from
      the promotion date forward.
    - After 90 days, that signal has a track record on data that **did not
      exist when the hypothesis was formed**.  No purging scheme is needed; the
      data is honestly out of sample by construction.

**The three facts the sentence names are all already in the schema.**  *Which
signal* was promoted is ``promotion_registry.node_id`` — a closed row is a
promoted signal, and a node holding one is the only thing in this member's table
that is.  *When* is ``decided_at``, the stamp feature 293 placed: this feature's
own name for a column another feature writes, which is why
:data:`PROMOTED_AT_COLUMN` reads :data:`~promotion.pre_register.DECIDED_AT_COLUMN`
rather than spelling a second literal — one column, two readers' words for it,
and the member spells it once.  *How long* the window runs is the
``min_forward_days`` of the criteria whose hash the row already holds —
:mod:`promotion.criteria`'s sixth term, whose own comment calls it *"the window
feature 300 timestamps open."*

**The window's end is derived, and that is why the table has no column for it.**
:attr:`PromotionWindow.closes_at` is ``opened_at + window_days``, computed from
the two values the row and the caller supply.  A stored end date would be a second
copy of one fact — free to disagree with the stamp it was computed from, and
unqueryable in the form an audit wants (*when did this promotion go out of
sample?* is a question about the stamp plus the horizon, not about a third
number).  The argument :mod:`promotion.blocking` and :mod:`promotion.calibration`
both make for their own derived figures, one member over: the facts are stored,
the arithmetic is not.

**What this feature is *not*, and each exclusion is a boundary another module
already states.**  It does not write ``forward_record`` — that table belongs to
the ``forward`` plugin (feature 332's ``POST /forward/promote`` is its writer,
features 332-340 its category), and a promotion-side feature that wrote it would
be this member authoring another plugin's rows, including the ``observed_on`` and
``live_ic`` columns only features 333/335 fill.  It does not spell
``criteria_mismatch`` — comparing a promotion against the hash it was judged
against is feature 292's verdict, and :mod:`promotion.decision` states that
boundary at its own length.  It does not charge an epoch (feature 294's act reads
the closed rows) and it does not judge whether the promotion **stands** — that is
the deciding evaluation's verdict, and this module reads a timestamp, not an
outcome.  It writes nothing at all: there is no ``record_*`` verb here, no
``INSERT``, no ``UPDATE``, and no DDL, because the row it answers from is already
complete.

**It reads through feature 293's own seam rather than spelling a second
``SELECT``.**  :meth:`promotion.decision.PromotionDecisions.decision` already
answers *this node's row, open or closed*, and already refuses the two-row and the
corrupt-row cases in the decision's vocabulary.  A second registry read here would
be a second reading of one table — the discipline
:meth:`~promotion.decision.PromotionDecisions._registration_of` states when it
reuses :data:`~promotion.pre_register._READ_SQL` rather than restating it — and
would put two answers to *what does this node's row say?* in the tree.  So
:class:`PromotionWindows` is constructed **over** a
:class:`~promotion.decision.PromotionDecisions` and owns no connection, no
bootstrap and no statement: every fact it answers comes from the decision store's
read, and every refusal that read raises arrives already phrased for a registry
row.  Duck-typed rather than ``isinstance``-guarded, the seam
:class:`~promotion.pre_register.PreRegisterEndpoint` states — the factory's scan
imports this member under a synthetic module name, so the *composed* store is
structurally a ``PromotionDecisions`` and never the same class object a direct
import yields.

**The window's length is the caller's, and that is forced rather than chosen.**
``promotion_registry`` holds ``criteria_hash``, not the criteria document, and
sha256 is one-way — so ``min_forward_days`` cannot be recovered from the row, and
this module will not pretend otherwise.  The two alternatives are both refused on
boundaries other modules already own: putting the length on the row needs an
``ALTER TABLE`` on a table whose columns the spec declares and whose DDL stops at
``0108`` (the refusal :mod:`promotion.blocking` argues at length for its own
table, and which ``migrations/versions/**`` being core-task territory makes
unavailable here regardless), and recomputing the hash from a caller's criteria
document to check it is *feature 292's* ``criteria_mismatch``, which
:mod:`promotion.decision` explicitly declines to pronounce.  So ``forward_days``
arrives as a **required keyword with no default** — a default would be this module
inventing a horizon nobody registered, which is precisely the fitted-after-the-fact
number §13 item 7 exists to prevent — and the record **carries the row's own
``criteria_hash``**, so a later reader can see which criteria set the window was
opened against and compare the length to the one that set declares.  That field is
what makes the length auditable rather than merely asserted; the repair for a wrong
length is feature 292's comparison, run by the caller that holds the criteria
document.

**An open row opens no window, and the refusal is the load in ``depends_on="293"``.**
A pre-registered row whose ``decided_at`` is still ``NULL`` is a hypothesis whose
evaluation has not run: there is no promotion timestamp, so there is no instant for
the window to open at.  Answering one would mean choosing a start — *now*, or the
pre-registration's instant — and both are fabrications of exactly the kind §13 item
7 exists to prevent: *now* is the reader's clock and places the boundary wherever
the reading happened to land (including inside the evaluation's own span), and the
pre-registration's instant is *before* the evaluation, so the window would begin
measuring on data that existed when the hypothesis was formed.  So the case is
refused by name, naming the remedy, and
:meth:`~promotion.forward.PromotionWindows.windows` — the listing — omits an open
row for the same reason: it is a pre-registration, not a promotion.

**The interval is half-open, and the arithmetic says so at its edges.**  A window
of ``n`` days opening at instant ``t`` is open for the whole of ``t`` and closed
from ``t + n days`` onward: :meth:`PromotionWindow.open_at` answers ``False`` at the
closing instant, and that is the same asymmetry ``universe.membership`` states for
its own intervals (``valid_to`` is the first instant a membership no longer holds).
A window that included its closing instant would overlap the next span by an
instant — and here it would let a forward observation land at the moment the signal
stopped being out of sample, which is the single boundary the whole loop is built
around.

**The arithmetic is pure, and this module's acts take no clock.**  Nothing here
stamps anything — the module reads an instant that is already on the row — so there
is no ``clock`` seam to offer, unlike :mod:`promotion.decision`'s and
:mod:`promotion.blocking`'s.  What the *derived* questions need is a *reference*
instant (``elapsed_by``, ``remaining_at``, ``open_at``), and that is an argument to
the method rather than state on the store: a window's arithmetic must be a pure
function of its own figures and the instant it is asked about, so two processes
asking the same question of the same row get the same answer and a replay can ask
*was this window open on that date?* without depending on when it runs.

**No component, no seat, no router, no second builder.**  The member's registered
surface stays feature 291's one store, for the reason :mod:`promotion.blocking` and
:mod:`promotion.calibration` both state: a builder takes no arguments and is built
on every ``create_app()`` call, while this act is a function of state the factory
does not hold — a promotion that has been decided, and a horizon the caller
registered.  The seat (``src/app/modules/promotion``) is untouched and still
answers one question.

**Stdlib only, and import-cheap.**  ``datetime``, ``os`` and ``uuid`` at module
scope plus this member's own four modules — no third-party import and no import of
another workspace member, so the factory's scan imports this package for the
near-nothing it always did and a window costs its caller only the store it already
had.
"""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .decision import PromotionDecisions
from .errors import (
    PROMOTION_WINDOW_ERROR_CODE,
    PromotionError,
    PromotionStoreError,
    PromotionWindowError,
)
from .pre_register import (
    CRITERIA_HASH_COLUMN,
    DATABASE_URL_ENV,
    DECIDED_AT_COLUMN,
    EPOCH_ID_COLUMN,
    NODE_ID_COLUMN,
    PromotionRecord,
    _validated_criteria_hash,
    _validated_epoch_id,
    _validated_instant,
    _validated_uuid,
)
from .schema import PROMOTION_REGISTRY_TABLE

__all__ = [
    "CLOSES_AT_COLUMN",
    "FORWARD_WINDOW_TABLE",
    "OPENS_AT_COLUMN",
    "PROMOTED_AT_COLUMN",
    "WINDOW_DAYS_COLUMN",
    "PromotionWindow",
    "PromotionWindows",
    "promotion_window",
    "promotion_windows",
    "window_closes_at",
]

#: The table a window is read off — the registry, because a promotion's timestamp
#: is the decision's stamp and the decision's stamp is a column of that row.  Read
#: from :mod:`promotion.schema` rather than spelled again, for the reason every
#: table name in this member is: one literal, one owner.
FORWARD_WINDOW_TABLE = PROMOTION_REGISTRY_TABLE

#: When the signal was promoted — this feature's name for
#: :data:`~promotion.pre_register.DECIDED_AT_COLUMN`, read rather than re-spelled.
#: One column, two readers' words for it: feature 293 writes *the instant the
#: decision was recorded*, and the forward loop reads the same value as *the
#: instant the window opens*.  A second literal here would be a second thing to
#: keep in sync in a module whose whole subject is one column.
PROMOTED_AT_COLUMN = DECIDED_AT_COLUMN

#: The horizon the window runs for, in whole days — the record's own field name.
#: Deliberately *not* a column anywhere: ``promotion_registry`` holds the criteria
#: *hash* and sha256 is one-way, so the length arrives from the caller (see the
#: module docstring) and is carried on the record beside the hash it was read
#: under.  Named here so :meth:`PromotionWindow.row` spells the one value the table
#: does not hold in the same vocabulary as the four it does.
WINDOW_DAYS_COLUMN = "window_days"

#: The instant the window opens — the promotion stamp, named for the question this
#: feature asks rather than for the act that wrote it.
OPENS_AT_COLUMN = "opens_at"

#: The instant the window closes — derived, never stored, and named as a column so
#: a rendered row reads as the pair a caller compares: *opened here, closes there*.
#: It is a property of the record, so a row carrying a value for it would be
#: carrying a second copy of ``opened_at + window_days``.
CLOSES_AT_COLUMN = "closes_at"

#: The largest instant a ``datetime`` can represent, used **only** to phrase the
#: overflow refusal below.  It is not a bound any horizon is checked against —
#: see :func:`_validated_window_days` for why no static bound would be correct.
#: Aware, because every instant this module handles is aware: the refusal is read
#: beside the promotion stamp, and a message pairing an aware stamp with a naive
#: ceiling would be quoting two different clocks.
_LATEST_INSTANT = dt.datetime.max.replace(tzinfo=dt.UTC)


# -- Validation --------------------------------------------------------------------


def _translated(exc: PromotionError, what: str) -> PromotionWindowError:
    """Re-raise a sibling's refusal in this feature's vocabulary.

    The seam rule this workspace states at every member boundary, applied *inside*
    one member — the shape :func:`promotion.decision._translated`,
    :func:`promotion.blocking._translated` and
    :func:`promotion.calibration._translated` take toward the same validators.
    Feature 291's calendar of refusals raises ``PromotionError`` for a malformed
    identity, an unreadable instant or an unreadable criteria hash, and feature
    293's store raises ``PromotionDecisionError`` for a row it cannot read; a
    caller whose single ``except PromotionWindowError`` guards the window it is
    about to open must not be defeated by a refusal phrased for one of those acts —
    it would read *the decision was not recorded* where the truth is *this window
    could not be opened*, and would go on to answer a forward question against an
    instant nobody produced.  The inner message is carried through, so nothing an
    operator needs is lost; only re-framed, with the frame naming which act was
    being performed.

    ``type(exc)(...)`` is deliberately **not** used: here the class itself is the
    thing being corrected, exactly as in the three siblings.
    """
    return PromotionWindowError(
        f"{PROMOTION_WINDOW_ERROR_CODE}: the {what} could not be read to open "
        f"this promotion's forward window: {exc}"
    )


def _window_node_id(value: Any) -> str:
    """Return ``value`` as a node identity, or refuse it in *this* vocabulary.

    Feature 291's identity validator is the one spelling this member has for *an id
    that joins the tree*, and the window's node is exactly that value — so the rule
    is *used* rather than restated, the move both siblings make.  What it raises is
    ``PromotionError``, the member's ask face, and that is what the wrapper is for:
    the refusal has to arrive as a *window* refusal, or a caller's single ``except
    PromotionWindowError`` walks through it and answers a forward question against
    a hypothesis nobody named.
    """
    try:
        return _validated_uuid(value, NODE_ID_COLUMN)
    except PromotionError as exc:
        raise _translated(exc, "node identity") from exc


def _validated_window_days(value: Any) -> int:
    """Return ``value`` as the window's length in days, or refuse what is not one.

    A **positive** count of whole days, and the strictness is this feature's, not a
    habit inherited from the criteria' own validator.  Feature 291's
    :func:`~promotion.criteria._validated_count` admits zero, deliberately: a
    criterion of *zero worlds* is a bad pre-registration but a registerable one,
    and refusing it there would be the pre-registration judging a decision that
    belongs to the evaluation.  Here zero is not a bad window, it is **not a
    window**: ``closes_at`` would equal ``opened_at``, the half-open interval would
    be empty, and a forward record opened against it could never hold a single
    observation — a caller asking for something that cannot exist rather than
    registering a horizon that is merely unwise.  So the rule is restated here with
    its own boundary and its own message rather than borrowed, and a negative length
    is refused by the same check.

    ``bool`` is refused first, for the reason every count validator in this
    workspace refuses it: ``True`` is ``1`` in Python, and a flag where a horizon
    belongs would silently open a one-day window — the shortest a window can be, and
    a length nobody stated.

    The *type* check is this module's own too, rather than delegated to
    :func:`~promotion.criteria._validated_count`: that validator's message speaks of
    *a promotion criterion's fish* and names feature 291, so a caller who passed a
    fraction as a horizon would be told about the wrong act.  The two disagree only
    on the boundary (zero), so the reuse would buy one clause and cost a misleading
    frame.

    **There is deliberately no upper bound here, and the reason is that no static
    one would be correct.**  ``dt.timedelta(days=n)`` overflows above roughly
    ``2.7e6`` years, and ``opened_at + timedelta`` overflows again as the sum
    passes ``datetime.max`` — so the reachable limit on a horizon *depends on the
    stamp it is added to*.  A length of ``999_999_999`` days is a legal
    ``timedelta`` and still explodes against any real stamp.  A constant here
    would therefore be either too tight (refusing spans the arithmetic can take)
    or too loose (admitting the very ``OverflowError`` it was meant to stop), so
    the check lives where the sum is actually taken —
    :func:`_closes_at`, which both :attr:`PromotionWindow.closes_at` and
    :func:`window_closes_at` go through, and which is the only place that has
    both figures in hand.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise PromotionWindowError(
            f"{PROMOTION_WINDOW_ERROR_CODE}: {WINDOW_DAYS_COLUMN} must be a "
            f"positive integer number of days — got {value!r} "
            f"({type(value).__name__}); the forward window is the span a promoted "
            "signal is measured over on data that did not exist when the hypothesis "
            "was formed, and a horizon that is a flag or a fraction names no span a "
            "forward record could be opened against. Read it from the promotion's "
            "pre-registered ``min_forward_days`` (feature 291's criteria) (feature "
            "300)"
        )
    if value <= 0:
        raise PromotionWindowError(
            f"{PROMOTION_WINDOW_ERROR_CODE}: {WINDOW_DAYS_COLUMN} must be positive "
            f"— got {value!r}; a window of zero days opens and closes at the same "
            "instant, so it holds no observation and is not a measurement window at "
            "all. The horizon is the promotion's pre-registered ``min_forward_days`` "
            "(feature 291's criteria): read it from the criteria the promotion was "
            "registered under, and do not invent one the registration does not carry "
            "(feature 300)"
        )
    return value


def _instant_of(value: Any, field_name: str) -> dt.datetime:
    """Return ``value`` as an instant on this member's one calendar, or refuse it.

    The promotion stamp read off the row, and every reference instant a caller
    asks a window about, held to the member's one instant rule (aware, normalised
    to UTC, ISO-8601 text accepted so a row read back revalidates) and re-framed in
    this feature's vocabulary — the same seam :func:`_window_node_id` takes over
    the identity validator.  A naive stamp is refused rather than defaulted:
    :attr:`PromotionWindow.closes_at` adds a ``timedelta`` to this value, and adding
    a span to a naive instant produces an instant with no offset that no later
    comparison can place on a calendar.

    The field name is a parameter rather than a constant because the rule is
    applied in two places that name different things: the row's stamp is
    ``opens_at`` to this feature, while *an instant a caller asks about* is just
    that.  Both are held to the identical rule, so a reference instant cannot be a
    different kind of value from the stamp it is compared against — the property
    the arithmetic depends on and the reason the reuse is of the *rule* rather than
    of a blessed subset of it.
    """
    try:
        return _validated_instant(value, field_name)
    except PromotionError as exc:
        raise _translated(exc, field_name) from exc


def _window_epoch_id(value: Any) -> str:
    """Return ``value`` as the epoch's name, or refuse it in this vocabulary.

    ``epoch_ledger``'s ``TEXT`` primary key: non-empty stripped text, the same
    rule :class:`~promotion.pre_register.PromotionRecord` applies and, until this
    wrapper existed, the one field of this record that leaked a sibling's
    ``PromotionError`` straight through.  The wrapper is the same seam
    :func:`_window_node_id` takes over the identity validator, and it is here for
    the same reason: a window font built from a corrupt row must refuse *the
    window*, not a pre-registration the caller never mentioned.
    """
    try:
        return _validated_epoch_id(value)
    except PromotionError as exc:
        raise _translated(exc, EPOCH_ID_COLUMN) from exc


def _closes_at(opened_at: dt.datetime, days: Any) -> dt.datetime:
    """``opened_at + days`` — the one place the window's arithmetic is taken.

    Both :attr:`PromotionWindow.closes_at` and :func:`window_closes_at` go through
    here, so the sum is written once and neither can drift from the other; the
    horizon is validated *first*, so a malformed length is refused as a length
    rather than surfacing from inside ``timedelta``.

    **The ``OverflowError`` is caught here and nowhere else, because this is the
    only frame holding both figures.**  ``timedelta`` can represent far more days
    than any real stamp can be added to, so the reachable limit depends on
    ``opened_at`` and no validation of ``days`` alone can bound it — the argument
    :func:`_validated_window_days` states.  Without this catch, a length that is a
    legal span but an impossible sum escapes as a bare ``OverflowError`` from
    inside a property access, which is exactly the failure mode the horizon rule
    exists to prevent: a caller whose single ``except PromotionWindowError``
    guards the window read sails straight through it and is left holding a window
    whose end cannot be computed.

    The message names *both* figures, because the repair depends on which one is
    wrong — an operator with a sane stamp needs to know the horizon is the absurd
    one, and one whose registry row carries a corrupt stamp needs to know that.
    """
    horizon = _validated_window_days(days)
    try:
        return opened_at + dt.timedelta(days=horizon)
    except OverflowError as exc:
        raise PromotionWindowError(
            f"{PROMOTION_WINDOW_ERROR_CODE}: the window opening at "
            f"{opened_at.isoformat()} cannot be measured over "
            f"{WINDOW_DAYS_COLUMN} {horizon!r} — the sum passes the largest "
            f"instant the calendar can represent "
            f"({_LATEST_INSTANT.isoformat()}), "
            f"so this window would have no computable end: {exc}. The promotion "
            "instant and the horizon are each within range; it is the *sum* that "
            "is not, which is why the repair is one of the two figures rather "
            "than the arithmetic. Check that the horizon is the promotion's "
            "pre-registered ``min_forward_days`` (feature 291's criteria) and that "
            "the stamp is feature 293's own (feature 300)"
        ) from exc


def _stored_criteria_hash(value: Any) -> str:
    """Return the row's ``criteria_hash``, or refuse it in this vocabulary.

    The shape check is feature 291's own
    (:func:`~promotion.pre_register._validated_criteria_hash`, 64 lowercase hex
    characters) *used* rather than restated, and the re-framing is the seam every
    wrapper here takes — it raises ``PromotionStoreError``, the member's *a row
    could not be written or read back* face, which is exactly what a corrupt hash on
    a row is.  It earns its place at this act specifically: the hash is what the
    window reports as *the criteria set this horizon came from*, so a corrupt one
    handed on unexamined would tell a reader that a window was opened under criteria
    nobody registered — the same fabrication
    :meth:`~promotion.pre_register.PreRegistrations._require_parent` refuses at the
    other end of the row's life.
    """
    try:
        return _validated_criteria_hash(value)
    except PromotionStoreError as exc:
        raise _translated(exc, CRITERIA_HASH_COLUMN) from exc


# -- The record --------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PromotionWindow:
    """One promoted signal's forward measurement window — feature 300's value.

    Five fields and five derived questions.  ``node_id`` is the signal,
    ``opened_at`` is the promotion instant (feature 293's ``decided_at``, read off
    the row), ``window_days`` is the horizon the caller registered,
    ``criteria_hash`` is the criteria set the row was registered under — carried so
    the horizon can be audited against it — and ``epoch_id`` is the sequestered
    epoch the promotion was registered against.  ``closes_at`` is derived, and the
    questions (*how much has elapsed, how much remains, is it open, how many whole
    days*) are methods taking the instant they are asked about.

    **Frozen**, because this value is a *statement about when a signal stopped being
    measured on in-sample data*: a caller who could edit ``opened_at`` in memory
    would move the boundary between backtest and out-of-sample that ``0108``'s own
    docstring calls the point of the forward record.  The discipline every record in
    this workspace states, and it matters most here.  Frozen also buys *equality over
    the five stored fields*, which is what makes two reads of one promotion
    comparable — the property :mod:`promotion.forward`'s own suite relies on when it
    asserts a module-level read and a store read agree.

    Validated in :meth:`__post_init__` rather than only through the store, for the
    reason :class:`~promotion.pre_register.PromotionRecord` states: ``dataclasses.
    replace`` and unpickling both rebuild instances past a factory's nose, and the
    *read* path needs the same check the caller's path does — SQLite's columns are
    dynamically typed, so a hand-edited row is reachable here, and a window rebuilt
    from one without revalidation would report a horizon nobody registered.

    The derived figures are **properties and not fields**, which is what keeps them
    out of the value's identity: two windows agree when the five facts agree, and
    ``closes_at`` — a pure function of two of them — is not a sixth thing to compare.

    **The arithmetic is pure**, and that is a decision rather than an accident: no
    method here reads a clock, so two processes asking the same question of the same
    window get the same answer and a replay can ask *was this window open on that
    date?* without depending on when it runs.
    """

    #: The hypothesis the window belongs to — the node whose row feature 293
    #: closed.  Validated through feature 291's identity rule, since it is a
    #: foreign key to the same ``node`` the registry row references.
    node_id: Any
    #: The sha256 digest of the criteria the promotion was registered under —
    #: the *row's* copy, carried so the caller's horizon can be audited against
    #: the criteria set it was read under.  Nothing here recomputes or compares
    #: it; that verdict is feature 292's.
    criteria_hash: Any
    #: The sequestered epoch the promotion was registered against —
    #: ``epoch_ledger``'s ``TEXT`` primary key, which is why it is validated as
    #: non-empty text rather than as a UUID.
    epoch_id: Any
    #: When the promotion was decided: feature 293's stamp, and the instant this
    #: window opens.  The one field whose name differs from the table's, which is
    #: the point — see :data:`PROMOTED_AT_COLUMN`.
    opened_at: Any
    #: How long the window runs, in whole days.  The caller's figure, because the
    #: row holds a one-way digest rather than the criteria document; a required
    #: keyword on every surface that builds one, and positive here.
    window_days: Any

    def __post_init__(self) -> None:
        # frozen+slots forbids plain assignment, so canonicalisation writes
        # through object.__setattr__ exactly once, at construction — the same
        # discipline the criteria value, the trial ledger's record and every
        # sibling record in this member follow.
        object.__setattr__(self, "node_id", _window_node_id(self.node_id))
        object.__setattr__(
            self, "criteria_hash", _stored_criteria_hash(self.criteria_hash)
        )
        object.__setattr__(self, "epoch_id", _window_epoch_id(self.epoch_id))
        object.__setattr__(
            self, "opened_at", _instant_of(self.opened_at, OPENS_AT_COLUMN)
        )
        object.__setattr__(
            self, "window_days", _validated_window_days(self.window_days)
        )
        # The sum is taken **at construction**, not deferred to the first read of
        # ``closes_at``.  A record built with a horizon it cannot be measured
        # over would be a value whose own derived field raises — the constructor
        # succeeding and the failure surfacing somewhere else entirely, which is
        # the worst shape a validation bug can take here.  Taking it here means
        # the refusal arrives naming the record the caller just built, and every
        # later read of ``closes_at`` is then infallible.
        _closes_at(self.opened_at, self.window_days)

    # -- The derived five ---------------------------------------------------

    @property
    def closes_at(self) -> dt.datetime:
        """When the window ends — the promotion instant plus the horizon.

        Derived rather than stored, and the closing instant is excluded from the
        interval: the window is open for the whole of :attr:`opened_at` and closed
        from this instant onward, the asymmetry :meth:`open_at` states and
        ``universe.membership`` states for its own intervals.  A stored copy of this
        value would be a second spelling of one fact, free to disagree with the two
        it is computed from.

        Infallible on a constructed window: :meth:`__post_init__` already took this
        exact sum, so the ``OverflowError`` this would otherwise raise has been
        refused by the time a caller can reach this property.
        """
        return _closes_at(self.opened_at, self.window_days)

    @property
    def horizon(self) -> dt.timedelta:
        """The window's length as a span — ``window_days`` as days.

        The bridge between the integer a caller registered and the arithmetic the
        questions below do, so ``timedelta(days=...)`` is spelt once rather than in
        each of them, and so :func:`window_closes_at` and :attr:`closes_at` provably
        add the same span.
        """
        return dt.timedelta(days=self.window_days)

    def elapsed_by(self, instant: Any) -> dt.timedelta:
        """How much of the window had passed by ``instant``.

        **Zero rather than negative before the window opens**, because the question is
        *how much of the window has elapsed* and a window that has not opened has had
        none of it elapse.  At and after :attr:`closes_at` the answer is the full
        horizon and no more: an elapsed span that kept growing would be a figure about
        how long ago the promotion was, which is a different question — and the part a
        caller actually wants past the boundary is answered by :meth:`remaining_at`
        returning zero and :meth:`open_at` returning ``False``.
        """
        reference = _instant_of(instant, "reference instant")
        if reference <= self.opened_at:
            return dt.timedelta(0)
        if reference >= self.closes_at:
            return self.horizon
        return reference - self.opened_at

    def remaining_at(self, instant: Any) -> dt.timedelta:
        """How much of the window is left at ``instant``.

        The complement of :meth:`elapsed_by` over the horizon, with the same two
        clamps: the whole horizon before the window opens — a window that has not
        begun has all of itself remaining — and zero at and after :attr:`closes_at`.
        Never negative, for the reason ``elapsed_by`` is never negative: a signed
        remainder would make *how long is left* a question whose answer means *how
        long ago it ran out*, and the two must not collapse into one figure.
        """
        return self.horizon - self.elapsed_by(instant)

    def open_at(self, instant: Any) -> bool:
        """Whether the window is open at ``instant`` — the half-open interval.

        ``opened_at <= instant < closes_at``, and **the closing instant is excluded
        on purpose**.  A window of ``n`` days that included its own closing instant
        would overlap the next span by one instant, and here that instant is the exact
        boundary the whole forward loop is built around: §5's *"after 90 days, that
        signal has a track record on data that did not exist when the hypothesis was
        formed."*  At 90 days the signal **has** the track record — the window is what
        produced it, and a forward observation landing at that instant must not be
        counted as still out of sample.  The same asymmetry ``universe.membership``
        states for ``valid_to``.
        """
        reference = _instant_of(instant, "reference instant")
        return self.opened_at <= reference < self.closes_at

    def elapsed_days(self, instant: Any) -> int:
        """The whole days of the window elapsed by ``instant``.

        The figure a report prints and the one §5's *"after 90 days"* is compared
        against, as an integer rather than as a ``timedelta``: a horizon is stated in
        whole days and a partial day has not elapsed *as a day*.  Truncated rather
        than rounded, so the count never runs ahead of the instant it is asked about.
        """
        return self.elapsed_by(instant).days

    def row(self) -> dict[str, Any]:
        """The window as a store-shaped mapping — a fresh dict per call.

        The column names are the table's own where the value has one (``node_id``,
        ``epoch_id``, ``criteria_hash``) plus this feature's own for the three the
        table does not hold: ``opens_at`` (the table's ``decided_at`` under the name
        this feature asks about), ``window_days`` (the caller's horizon) and
        ``closes_at`` (derived).  A rendered mapping names the same things the same
        way the row does, the discipline every record in this workspace follows.
        """
        return {
            NODE_ID_COLUMN: self.node_id,
            EPOCH_ID_COLUMN: self.epoch_id,
            CRITERIA_HASH_COLUMN: self.criteria_hash,
            OPENS_AT_COLUMN: self.opened_at,
            WINDOW_DAYS_COLUMN: self.window_days,
            CLOSES_AT_COLUMN: self.closes_at,
        }

    # No ``__repr__`` here: ``@dataclass`` generates one over the five stored
    # fields, which is exactly the rendering a debugging caller wants and is the
    # one the sibling records in this member rely on — hand-writing it would be a
    # second spelling of the same fields, free to fall out of step with them.


def window_closes_at(opened_at: Any, days: Any) -> dt.datetime:
    """When a window opening at ``opened_at`` for ``days`` closes — the arithmetic.

    The module-level spelling of :attr:`PromotionWindow.closes_at`, for a caller that
    holds the promotion stamp and the horizon but has not built the record — a report
    computing a boundary, a forward writer deciding whether an observation falls in
    window.  Both arguments go through the same rules the record applies — the same
    instant rule and the same length rule, and then the same sum through
    :func:`_closes_at` — so the standalone answer and the record's cannot disagree.
    In particular the clock arithmetic and its ``OverflowError`` catch live in that
    one function, so this spelling cannot be the one that leaks what the record
    refuses.
    """
    return _closes_at(_instant_of(opened_at, OPENS_AT_COLUMN), days)


# -- The store ---------------------------------------------------------------------


class PromotionWindows:
    """Answers the forward window a promotion opened — feature 300's act.

    Constructed **over** a :class:`~promotion.decision.PromotionDecisions` (or
    anything with its ``decision`` seam), never over a URL: every fact this store
    answers comes from feature 293's own read, so it holds no connection, runs no
    bootstrap, authors no DDL and spells no ``SELECT``.  The wiring is the shape
    :class:`~promotion.pre_register.PreRegisterEndpoint` takes toward the registry,
    and it is duck-checked rather than ``isinstance``-guarded for the reason that
    class states: the factory's scan imports this member under a synthetic module
    name, so the composed decision store is structurally a ``PromotionDecisions`` but
    never the same class object a direct import yields, and a class check here would
    refuse the very component the factory hands out.

    **There is no state to hold.**  A memo of windows this process had already
    computed would make *when did this signal go out of sample?* a question about this
    process's history — and the readers that ask it (the forward member opening a
    record, a report, an operator months later) all run somewhere else entirely.  The
    row is the only record, so it is the only thing an answer is drawn from, on every
    call, in every process.
    """

    #: The two verbs of feature 293's read seam this store drives, and the whole
    #: of what it requires: ``decision`` for one node's row and ``decisions`` for
    #: the listing.  Both are required, because :meth:`window` and
    #: :meth:`windows` each use one and a store missing either would fail on half
    #: its questions — the silent half, since the failure would be an
    #: ``AttributeError`` from inside the act rather than a wiring fault at
    #: construction.  Duck-typed as a *set of verbs* rather than class-checked,
    #: for the reason the class docstring gives.
    _SEAM = ("decision", "decisions")

    def __init__(self, decisions: PromotionDecisions) -> None:
        """Wire the window reader to the decision store it reads through.

        The seam is checked here, before any call, because it is a fact about the
        *store* rather than about any one window: a reader with nothing to read
        through names no registry, and one that accepted it would fail identically on
        every question — the wrong place to discover a wiring fault.  A ``TypeError``
        rather than a :class:`~promotion.errors.PromotionWindowError`, because a
        store that cannot answer is a *programming* error and not a promotion state:
        no operator can fix it by pre-registering or deciding anything.
        """
        missing = [
            verb
            for verb in self._SEAM
            if not callable(getattr(decisions, verb, None))
        ]
        # A *class* exposes its methods as plain functions, so it passes the
        # verb check above and then fails on the first call with a missing
        # positional argument — a confusing way to learn that the instance was
        # never built.  ``type`` is the one thing that is never a composed
        # store, so the check costs no duck-typing latitude.
        if isinstance(decisions, type):
            missing = missing or ["<an instance, not the class>"]
        if missing:
            raise TypeError(
                "PromotionWindows reads a decision store — something exposing "
                f"{' and '.join(self._SEAM)} — got {type(decisions).__name__}, which "
                f"is missing {', '.join(missing)}. A window opens at the stamp "
                "feature 293 placed, so this store answers through that store's own "
                "read rather than a second reading of the registry row (feature 300)"
            )
        self._decisions = decisions

    # -- Construction -------------------------------------------------------

    @classmethod
    def from_env(
        cls, env: Mapping[str, str] | None = None
    ) -> PromotionWindows | None:
        """The reader over the decisions ``DATABASE_URL`` names, or ``None``.

        Resolves the decision store exactly as the member's own builder does
        (:meth:`~promotion.decision.PromotionDecisions.resolve`), so the windows a
        caller opens and the decisions the deployment recorded always point at the
        same database.  No ``DATABASE_URL`` composes no reader — an unconfigured
        deployment is a discoverable state, not an error — while the caller whose
        forward record must be opened against a promotion instant is, again, the one
        that must not find itself in it.
        """
        decisions = PromotionDecisions.resolve(env)
        return None if decisions is None else cls(decisions)

    @property
    def decisions(self) -> PromotionDecisions:
        """The decision store this reader reads through."""
        return self._decisions

    # -- Feature 300: the window --------------------------------------------

    def window(
        self,
        node_id: Any,
        *,
        forward_days: Any,
    ) -> PromotionWindow:
        """The forward window one promoted signal opened — feature 300's act.

        The steps, in the order they must happen:

        1. **Validate the ask** — the node as an identity, the horizon as a positive
           count of days — *before* the row is read, so a malformed ask is refused
           without touching a database.
        2. **Read the node's row** through feature 293's own seam.  An absent row is
           *this node holds no pre-registration* — there is no promotion whose window
           this could be — and is refused by name, the repair being feature 291's act
           first and feature 293's after it.  A row that is still **open** is refused
           too: its deciding evaluation has not run, so there is no promotion instant
           for a window to open at, and the repair is feature 293's act.  Both are
           the load in this feature's ``depends_on="293"``.
        3. **Answer with the window**, built from the row's own facts (the node, its
           epoch, its criteria hash) plus the row's ``decided_at`` as the opening
           instant and the caller's horizon.

        **The answer is drawn from the row, not from the arguments.**  The criteria
        hash the window carries is the row's, and the opening instant is the stamp
        feature 293 placed.  The caller supplies exactly one thing: the horizon,
        because the table holds the criteria' *hash* and not its document (see the
        module docstring).  A caller that believes the horizon came from somewhere
        else has feature 292's comparison to run, not this store to overrule.

        **What this act never does.**  It writes nothing — there is no ``INSERT``, no
        ``UPDATE`` and no DDL in this module, and the row it reads is already
        complete.  It never judges the promotion: whether the signal *stands* is the
        deciding evaluation's verdict, and nothing here reads a score, a pool or a
        forward record.  It never charges an epoch (feature 294's act reads the closed
        rows) and never opens the forward record itself — that is feature 332's
        ``POST /forward/promote``, which reads this window's instant.

        Refuses, in this order, each naming what it is about and every one in
        :class:`~promotion.errors.PromotionWindowError`: a malformed node, a horizon
        that is not a positive count of days, then — from the read — a node holding no
        registry row, a node whose row is still open, and a row that could not be read
        back as a decision.
        """
        node = _window_node_id(node_id)
        horizon = _validated_window_days(forward_days)
        record = self._decision_of(node)
        if record is None:
            raise _absent_promotion(node)
        if record.open:
            raise _open_promotion(node, record)
        return self._window_of(record, horizon)

    def windows(self, *, forward_days: Any) -> tuple[PromotionWindow, ...]:
        """Every window this deployment's promotions have opened, by node.

        The *every* of the feature's sentence made enumerable: one window per
        promoted signal, each carrying its promotion instant, its horizon and the
        criteria hash it was registered under — the listing a report reads and the
        precondition feature 332's forward writer checks before opening a record.  A
        tuple rather than a live cursor, because the answer is a value the caller
        keeps rather than a view that changes under it, and ordered by the decision
        store's own listing order (the table's key), so two reads of one store are
        comparable.

        **An open row is deliberately absent**, and that is this method's one
        judgement rather than a filter for convenience: a pre-registration is not a
        promotion, so it has no window to be listed among.  The refusal :meth:`window`
        raises for that case is not reachable here — a listing has no single node to
        name a repair to — so the row is skipped in the same way
        :meth:`~promotion.decision.PromotionDecisions.decisions` skips it one feature
        over.

        The horizon is validated once, before any row is read, so a malformed one is
        refused without touching the database and every window in the tuple carries
        the same length.
        """
        horizon = _validated_window_days(forward_days)
        return tuple(
            self._window_of(record, horizon)
            for record in self._decisions.decisions()
        )

    # -- The words ----------------------------------------------------------

    def _decision_of(self, node: str) -> PromotionRecord | None:
        """One node's registry row, through feature 293's own read.

        Used rather than restated, so the row this feature opens a window from and the
        row feature 293 answered with cannot be two readings of one table — the
        discipline
        :meth:`~promotion.decision.PromotionDecisions._registration_of` states toward
        feature 291's read, applied one step further along.  A refusal the decision
        store raises (a node holding two rows, a corrupt row) arrives in *its*
        vocabulary, and it is translated here so a caller whose single ``except
        PromotionWindowError`` guards the window it is about to open is not defeated by
        a refusal phrased for a decision it never asked about.

        ``None`` means the node holds no row at all — a different fact from a row that
        is still open, which is why the two are kept apart by the caller rather than
        collapsed here.  The decision store already refuses a blank or non-text id
        rather than answering ``None``, so *no row* here can only mean a well-formed
        node nobody pre-registered.
        """
        try:
            return self._decisions.decision(node)
        except PromotionWindowError:
            raise
        except PromotionError as exc:
            raise _translated(exc, "registry row") from exc

    def _window_of(self, record: PromotionRecord, horizon: int) -> PromotionWindow:
        """Build one window from a closed row and the caller's horizon.

        The row's facts plus the horizon: the node, the epoch and the criteria hash are
        the table's own, and the opening instant is the row's ``decided_at``.  A row
        whose stamp cannot be read as an instant is refused by this module's own
        ``_instant_of``, which names ``opens_at`` — so an operator learns *which figure
        on which promotion's window is unreadable* rather than that some row somewhere
        is.

        ``decided_at`` is not asserted non-``None`` here.  The two callers establish
        that before arriving — :meth:`window` refuses an open row by name, and
        :meth:`windows` is handed only closed rows by the decision store's listing — so
        a check here would be a third spelling of a condition two other places already
        state, and it would report a pre-registration as a *corrupt* window rather than
        as the absence it is.
        """
        return PromotionWindow(
            node_id=record.node_id,
            criteria_hash=record.criteria_hash,
            epoch_id=record.epoch_id,
            opened_at=record.decided_at,
            window_days=horizon,
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"{type(self).__name__}(decisions={self._decisions!r})"


def _absent_promotion(node: str) -> PromotionWindowError:
    """The absence refusal: no pre-registration, so no promotion, so no window.

    The first half of this feature's ``depends_on="293"`` made load bearing — and,
    before it, ``depends_on="291"``.  §13 item 7 fixes a promotion's criteria *before*
    the evaluation that decides them, so the row a window is read off has to exist
    before there is a window.  A node nobody pre-registered has no promotion to have
    opened one, and answering with a window whose instant was defaulted would be
    inventing a start for a signal that was never promoted — the *observation with no
    vintage* ``0108``'s own docstring says forward testing exists to prevent.

    The repair is specific and ordered: pre-register the promotion (feature 291) and
    then record its decision (feature 293), because a window opens at the decision's
    stamp and not at the registration's.
    """
    return PromotionWindowError(
        f"{PROMOTION_WINDOW_ERROR_CODE}: {FORWARD_WINDOW_TABLE} holds no row for "
        f"{NODE_ID_COLUMN} {node}, so there is no promotion whose forward window this "
        "could be. A window opens at the instant a promotion was decided — feature "
        "293's stamp on the row feature 291's act opened — so a node nobody "
        "pre-registered has no promotion and no window, and answering with a start "
        "instant of the reader's choosing would be inventing the boundary between "
        "backtest and out-of-sample for a signal that was never promoted. Pre-register "
        "the promotion (feature 291), then record its decision once the deciding "
        "evaluation has run (feature 293)"
    )


def _open_promotion(node: str, record: PromotionRecord) -> PromotionWindowError:
    """The open-row refusal: a pre-registration is not yet a promotion.

    The second half of this feature's ``depends_on="293"``, and the case that makes the
    dependency a *gate* rather than a formality.  ``decided_at`` is ``NULL`` exactly
    while the deciding evaluation has not run — ``0108``'s own schema comment says the
    column is nullable *"because the row is written while the decision is still open,
    which is the only ordering under which pre-registration means anything."*  There is
    therefore no promotion instant, and a window needs one: every honest alternative is
    a fabrication.  *Now* is the reader's clock, not the promotion's, and would place
    the window's start wherever the reading happened to land — including inside the
    evaluation's own span.  The pre-registration's instant is worse: it is *before* the
    evaluation, so a window opened there would begin measuring on data that existed
    when the hypothesis was formed, which is precisely the contamination §5's loop and
    ``0108``'s forward record exist to exclude.

    So the row is refused, the node is named, and the repair is feature 293's act —
    record the decision, after the evaluation has run — with the instant the row *was*
    opened at and the criteria it was registered under reported, so an operator can see
    the row is real and merely unfinished.
    """
    return PromotionWindowError(
        f"{PROMOTION_WINDOW_ERROR_CODE}: {FORWARD_WINDOW_TABLE} holds an **open** row "
        f"for {NODE_ID_COLUMN} {node} — pre-registered at "
        f"{record.pre_registered_at.isoformat()} under criteria "
        f"{record.criteria_hash}, with no deciding stamp — so this promotion has no "
        "forward window yet. A window opens at the instant the promotion was decided, "
        "and until feature 293's stamp lands there is no such instant: opening one at "
        "the reader's clock would place the boundary wherever the reading happened to "
        "land, and opening one at the pre-registration's instant would start measuring "
        "on data that existed when the hypothesis was formed — the contamination the "
        "forward record exists to exclude. Refusing to guess is the whole of this "
        "store's job here. Record the decision once the deciding evaluation has run "
        "(feature 293), then read the window"
    )


# -- The module-level spellings -----------------------------------------------------


def _resolved_decisions(
    database_url: str | None, env: Mapping[str, str] | None
) -> PromotionDecisions:
    """The decision store the module-level spellings read through, or a refusal.

    The same seam :func:`promotion.decision._resolved_url` resolves, restated in this
    feature's vocabulary: an explicit URL wins, else ``DATABASE_URL``, and a deployment
    that names neither is refused *by name* rather than silently answering nothing.  The
    silence would be the dangerous failure here and not the refusal: a deployment that
    could not answer where a window opens leaves the forward record's writer choosing
    its own start instant, which is the state ``0108``'s forward record exists to make
    impossible.

    A decision store is constructed rather than resolved, so a blank URL is *reported as
    blank* by this message rather than as *a path this member cannot speak* by the
    store's — the repair for the caller is to name a database, not to fix a path.
    """
    source = os.environ if env is None else env
    url = (
        database_url
        if database_url is not None
        else source.get(DATABASE_URL_ENV, "").strip()
    )
    if not url or not str(url).strip():
        raise PromotionWindowError(
            f"{PROMOTION_WINDOW_ERROR_CODE}: no database is named — "
            f"{DATABASE_URL_ENV} is unset (and no database_url was supplied), so the "
            "promotion's forward window cannot be read. The window opens at the stamp "
            "feature 293 recorded on the registry row, and a store resolved from "
            "nothing is a refusal rather than a silent answer of the reader's own "
            "choosing (feature 300)"
        )
    return PromotionDecisions(url)


def promotion_window(
    node_id: Any,
    *,
    forward_days: Any,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> PromotionWindow:
    """The forward window one promoted signal opened — the module-level spelling.

    The feature's sentence as one call, for the caller that wants the window without
    holding a store — the forward member opening a record against a promotion's
    instant, a report, an operator asking when a signal goes out of sample.  The
    decision store is resolved from ``database_url``, else from ``DATABASE_URL``,
    exactly as :func:`promotion.decision.record_decision` and
    :func:`promotion.blocking.record_block` resolve theirs.

    A :class:`~promotion.errors.PromotionWindowError` from the read or the resolution
    propagates unwrapped: the refusal already names the node and the fact, and
    re-wrapping it here would put a second message in front of the one an operator
    needs.
    """
    return PromotionWindows(_resolved_decisions(database_url, env)).window(
        node_id, forward_days=forward_days
    )


def promotion_windows(
    *,
    forward_days: Any,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[PromotionWindow, ...]:
    """Every window this deployment's promotions opened — the module-level listing.

    For the caller that holds a URL rather than a store: a report enumerating what is
    currently out of sample, an operator auditing which signals have run their full
    horizon.  Resolved the same way :func:`promotion_window` resolves its store, so the
    caller that reads through one spelling and the other is reading the same rows.
    """
    return PromotionWindows(_resolved_decisions(database_url, env)).windows(
        forward_days=forward_days
    )
