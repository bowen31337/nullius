"""The depleting count of clean epochs remaining — feature 297, §13 item 4's gauge.

Feature 297's sentence — *"System reports remaining clean epochs as a depleting
count, which returns the figure so exhaustion is visible well before it
arrives."* — and the file where *how many clean epochs remain* is the whole of
the act.  Where feature 295 answers *may this epoch still be spent?* about one
row, and feature 296 answers *may the system continue at all?* about the whole
table, this feature answers *how many clean epochs are left?* about the whole
table — and it is the feature that makes exhaustion *visible well before it
arrives*, the thing the sentence asks for and the two before it do not provide.

**The verdict and the gauge are two acts over one table.**  Feature 296's
verdict is a *stop*: it raises when no clean epoch remains and is silent about
everything short of the end — a ledger with one clean epoch left and a ledger
with fifty both answer "the system may continue", and the verdict gives the
caller no way to tell the two apart.  That is the right behaviour for a stop
and the wrong one for a gauge: a gauge that only fires at zero is a warning
lamp that lights the instant the engine seizes.  This feature is the gauge —
it returns *the number*, the count of epochs that have not yet served §13 item
4's budget, so a caller watching it sees the figure fall from fifty to one and
knows exhaustion is coming long before feature 296's stop has anything to say.
The two are deliberately **not** one module: 296 raises and this one returns,
296 is the last line and this one is the running readout, and a module that
raised at zero would be 296 again while a module that returned at zero would be
a stop every caller had to remember to branch on — the failure
:func:`promotion.selection.rejects_further_selection` and :func:`promotion.
terminal.blocks_when_no_clean_epoch_remains` both refuse by raising rather than
answering a boolean.

**The count is derived, and it is the same derivation feature 296 makes.**  A
clean epoch is one that has *not* served the budget — ``served < budget``, the
complement of feature 296's ``served >= budget`` — and the count of clean
epochs is the count of rows that have not reached it.  The budget is feature
295's number, used here rather than restated, and the comparison is the same
``>=`` ``0110``'s own docstring gives feature 295, so an epoch that has
*exceeded* its budget counts as spent on the same comparison rather than
falling through an equality pin.  This module states the derivation once as a
pure function and shares it with feature 296's verdict — so the number this
gauge returns and the number feature 296's verdict reports between refusals are
one figure, not two readings of one table.

**It writes nothing, and the count is not a thing to persist.**  The number is
a function of the ledger rows and nothing else — a fresh read of the same table
answers the same figure — so there is no column for it, no order in
:mod:`promotion.schema`, no DDL, no statement and no connection of its own.
The ``retired`` flag is feature 296's exhaustion machinery's persistence of the
terminal verdict, not of this gauge's running readout, and this module
deliberately does not read it: retirement is the exhaustion machinery's later
act, and a gauge that read the flag would be reporting *what was retired*
rather than *how many are clean* — two different questions, and the flag is
absent until the very end, so a gauge that leaned on it would answer "all
clean" for every epoch right up to the moment they were all retired.  It does
not read ``sealed_at`` either (the sealing process's fact, which judges nothing
here), and it does not read a pool, a score, a coverage ledger, a calibration
status or any promotion merit — whether the promotion *stands* is the deciding
evaluation's verdict (feature 292's mismatch is the only comparison against the
recorded hash, and features 298's and 299's refusals read the campaign and the
coverage ledger), tables this act never opens.

The split this module states, the one :func:`promotion.terminal.
blocks_when_no_clean_epoch_remains` and :class:`promotion.terminal.
TerminalStates` state for the terminal verdict:

* :func:`clean_epochs_remaining` is the *pure* half — the feature's whole
  sentence as one count, and the seam for the caller that **already holds the
  figure**: it takes the ledger's rows and returns how many are clean.  It
  never raises on the count — a ledger that is empty or wholly spent answers
  ``0``, not an exception, because a gauge's job is to report the figure even
  at the end, and the caller that wants a stop asks feature 296.
* :class:`RemainingCleanEpochs` is the *gate* — constructed over an
  :class:`~promotion.epoch.EpochCharges` (or anything with its ``epochs``
  seam), it performs the whole-table read through feature 294's own store and
  delegates to the pure count, so there is one count in the member and this act
  cannot disagree with the pure figure a caller may use directly.
* :func:`remaining_clean_epochs` is the module-level spelling — the feature's
  sentence as one call for the caller that wants the figure without holding
  stores, resolving the charge store from a URL exactly as :func:`promotion.
  terminal.block_when_no_clean_epoch_remains` resolves its verdict.

The rows are duck-read — ``epoch_id`` and ``promotion_decisions_served`` — so
the composed listing and a test's stand-ins count identically, and the gauge
holds no cache of counts this process had already judged, for the reason every
store in this member states for its rows: the ledger is the only record of what
the epochs have served, so it is the only thing a count is drawn from, judged on
every call, in every process.

**Zero is an answer, not a refusal, and that is the whole point of the gauge.**
A ledger that is empty, or whose every epoch has served the budget, answers
``0`` — the figure the caller asked for, and the visible exhaustion the sentence
promises.  This is the deliberate contrast with feature 296: that verdict
refuses the empty ledger as a distinct terminal fact (no epoch to spend is not
"all clean"), because a *stop* that answered "continue" on an unsequestered
deployment would book a promotion against nothing.  This gauge is not a stop:
it reports *how many are clean*, and the honest answer to "how many clean
epochs?" when none were ever sealed is *zero*, not an error.  A caller that
wants to distinguish *never sequestered* from *all spent* reads the ledger's
rows — the gauge gives it the count, and the two facts stay apart in the table
it read them from.

Stdlib only, and import-cheap: ``os``, ``collections.abc`` and ``typing`` at
module scope plus this member's own modules (:mod:`promotion.epoch` for the
budget and the ``epochs`` seam, :mod:`promotion.selection` for the shared
derivation, :mod:`promotion.errors` for the shared base) — not even
``sqlite3``, because the connection is the charge store's and this module never
opens one — so the factory's scan imports this package for the near-nothing it
always did.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from typing import Any

from .epoch import EpochCharges
from .errors import EPOCH_CHARGE_ERROR_CODE, EpochChargeError
from .pre_register import DATABASE_URL_ENV
from .selection import SEQUESTERED_EPOCH_BUDGET
from .terminal import _spent_count

__all__ = [
    "RemainingCleanEpochs",
    "clean_epochs_remaining",
    "remaining_clean_epochs",
]


# -- The pure count ------------------------------------------------------------------


def clean_epochs_remaining(
    rows: Iterable[Any], *, budget: int = SEQUESTERED_EPOCH_BUDGET
) -> int:
    """The count of clean epochs remaining — feature 297's whole act.

    Takes the ledger's rows — each duck-read as ``epoch_id`` and
    ``promotion_decisions_served``, so the composed listing and a test's
    stand-ins count identically — and returns how many have **not** served
    ``budget`` promotion decisions: the clean epochs a caller may still spend.
    This is the whole of the feature's sentence — *"System reports remaining
    clean epochs as a depleting count"* — as one count, and it is the seam for
    the caller that **already holds the figure**: a report, a dashboard, a
    later feature that reached the rows its own way, a test judging the gauge.
    The caller that holds only the charge store asks
    :meth:`RemainingCleanEpochs.remaining` instead, which performs the
    whole-table read through feature 294's own seam and then delegates here, so
    there is one count in the member and not two.

    **A clean epoch is one that has not served the budget** — ``served <
    budget``, the complement of feature 296's ``served >= budget`` — and the
    count is the number of such rows.  The derivation is shared with feature
    296's verdict through :func:`promotion.selection._spent_count`, so the
    figure this gauge returns and the clean remainder feature 296 reports
    between its refusals are one figure, computed the same way, and cannot
    drift.  The budget is feature 295's number, used rather than restated, and
    the comparison is the same ``>=`` ``0110``'s own docstring gives feature
    295, so an epoch that has *exceeded* its budget counts as spent on the same
    comparison rather than falling through an equality pin.

    **It returns ``0`` at the end and never raises on the count.**  A ledger
    that is empty, or whose every epoch has served the budget, answers ``0`` —
    the figure the caller asked for, and the visible exhaustion the sentence
    promises.  This is the gauge's whole point, and the deliberate contrast
    with feature 296: that verdict *raises* when no clean epoch remains,
    because a stop that stayed silent at zero would let a caller book a
    promotion against a spent ledger; this gauge *reports* zero, because a
    readout that only spoke at the end would not make exhaustion visible before
    it arrives.  A caller that wants the stop asks feature 296; a caller that
    wants the number asks this.

    **It is not the count of spent epochs, and not a boolean.**  The figure is
    *how many are clean*, not *how many are spent* (feature 296's ``_blocked``
    names the spent count) and not *may the system continue* (feature 296's
    whole question).  It is the count of rows that have not reached the budget,
    and it is the value the gauge compared and not a derived remainder: the
    remaining budget *per epoch* is arithmetic from the two figures, and this
    count is a question about the *system's* remaining headroom, not about any
    one epoch's spend.

    **It does not validate the count.**  The rows it is handed arrive from
    feature 294's own ``epochs`` seam, which validates each served count as it
    reads it — a non-negative integer, with ``bool`` refused first — so a
    second validation here would be the store confirming itself.  The pure
    count takes the rows as feature 294 already answered them, the move
    :func:`promotion.terminal.blocks_when_no_clean_epoch_remains` makes toward
    the same seam.  A caller that hands it a figure nobody derived gets the
    count of that figure, because the gauge reports what the ledger says rather
    than judging whether the ledger is honest — that judgment is feature 294's
    write and feature 296's verdict, not this readout.
    """
    return sum(
        1 for row in rows if not _spent_count(_served(row), budget)
    )


def _served(row: Any) -> Any:
    """The served count a row carries, read the same way feature 296 reads it.

    Duck-read off ``promotion_decisions_served`` — the attribute the composed
    listing and a test's stand-in both expose — so the count this gauge returns
    and the count feature 296's verdict judges are read from the same field.
    The complement of :func:`promotion.terminal.blocks_when_no_clean_epoch_remains`'
    ``getattr(row, "promotion_decisions_served", None)``: one spelling of the
    read, shared by the two whole-table acts rather than restated in each.
    """
    return getattr(row, "promotion_decisions_served", None)


# -- The gate ------------------------------------------------------------------------


class RemainingCleanEpochs:
    """The gauge that counts clean epochs remaining — feature 297's act.

    Constructed **over** an :class:`~promotion.epoch.EpochCharges` (or anything
    with its ``epochs`` seam), never over a URL: every fact this gauge counts
    comes from feature 294's own whole-table read, so it holds no connection,
    runs no bootstrap, authors no DDL and spells no statement.  The wiring is
    the shape :class:`promotion.terminal.TerminalStates` takes toward the charge
    store, and it is duck-checked rather than ``isinstance``-guarded for the
    reason that class states: the factory's scan imports this member under a
    synthetic module name, so the *composed* charge store is structurally an
    ``EpochCharges`` but never the same class object a direct import yields, and
    a class check here would refuse the very component the factory hands out.

    **There is no state to hold.**  A memo of counts this process had already
    judged would make *how many clean epochs remain?* a question about this
    process's history — and the answer moves: a charge lands in another process
    a moment after this one asked, and the epoch that was clean is spent.  The
    ledger is the only record of what the epochs have served, so it is the only
    thing a count is drawn from, on every call, in every process.
    """

    #: The one verb of feature 294's whole-table read this gauge drives, and
    #: the whole of what it requires: ``epochs`` for every ledger row.
    #: Duck-typed as a *set of verbs* rather than class-checked, for the reason
    #: the class docstring gives — the composed store and the directly imported
    #: one are different class objects with the same seam, and either is a valid
    #: thing to count through.
    _SEAM = ("epochs",)

    def __init__(self, charges: EpochCharges) -> None:
        """Wire the gauge to the charge store it reads through — 294's seam.

        The seam is checked here, before any call, because it is a fact about
        the *gauge* rather than about any one count: a reader with nothing to
        read through names no ledger, and one that accepted it would fail
        identically on every count — the wrong place to discover a wiring
        fault.  A ``TypeError`` rather than a promotion error, because a gauge
        that cannot read is a *programming* error and not a promotion state: no
        operator can fix it by sequestering or spending anything.
        """
        missing = [
            verb
            for verb in self._SEAM
            if not callable(getattr(charges, verb, None))
        ]
        # A *class* exposes its methods as plain functions, so it passes the
        # verb check above and then fails on the first call with a missing
        # positional argument — a confusing way to learn that the instance was
        # never built.  ``type`` is the one thing that is never a composed
        # store, so the check costs no duck-typing latitude.
        if isinstance(charges, type):
            missing = missing or ["<an instance, not the class>"]
        if missing:
            raise TypeError(
                "RemainingCleanEpochs reads a charge store — something exposing "
                f"{' and '.join(self._SEAM)} — got {type(charges).__name__}, "
                f"which is missing {', '.join(missing)}. The count is judged on "
                "the whole ledger feature 294's own read answers with, so this "
                "gauge reads through that store rather than a second reading of "
                "the table (feature 297)"
            )
        self._charges = charges

    # -- Construction -------------------------------------------------------

    @classmethod
    def from_env(
        cls, env: Mapping[str, str] | None = None
    ) -> RemainingCleanEpochs | None:
        """The gauge over the charge store ``DATABASE_URL`` names, or ``None``.

        Resolves the charge store exactly as the member's own builder resolves
        its registry (:meth:`~promotion.epoch.EpochCharges.resolve`), so the
        epochs a gauge counts and the counts the deployment charged always
        point at the same database.  No ``DATABASE_URL`` composes no gauge — an
        unconfigured deployment is a discoverable state, not an error — while
        the caller whose dashboard must show depletion coming is, again, the one
        that must not find itself without the figure.
        """
        charges = EpochCharges.resolve(env)
        return None if charges is None else cls(charges)

    @property
    def charges(self) -> EpochCharges:
        """The charge store this gauge reads through — feature 294's seam."""
        return self._charges

    # -- Feature 297: the count -----------------------------------------------

    def remaining(self) -> int:
        """The count of clean epochs remaining — feature 297's act.

        The steps, in the order they must happen:

        1. **Read the whole ledger** through feature 294's own ``epochs`` seam
           — every sequestered epoch's row, the count feature 294 persisted and
           the flag feature 296 reads — so the count is a function of the rows
           the charge answered with and cannot be a second reading of one
           table.
        2. **Delegate to the pure count** — :func:`clean_epochs_remaining` over
           the rows — so there is one count in the member and this act cannot
           disagree with the pure figure a caller may use directly.

        A refusal the read raises (a doubled row, an unreadable count, an
        unreachable database) propagates in *its* vocabulary — the count is
        judged on the rows, and a row that cannot be read is a different fact
        from one that is spent.  Unlike feature 296's verdict, this count never
        raises on the figure itself: a ledger that is empty or wholly spent
        answers ``0``, the visible exhaustion the sentence promises.

        **It returns** the count of clean epochs remaining — the figure this
        feature exists to report, the same figure feature 296's verdict reports
        between its refusals, so the dashboard that shows depletion coming and
        the verdict that stops at zero agree on the number.
        """
        return clean_epochs_remaining(self._charges.epochs())


# -- The module-level spelling -------------------------------------------------------


def remaining_clean_epochs(
    rows_or_url: Any,
    *,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> int:
    """The count of clean epochs remaining — the module-level spelling of 297's act.

    The feature's sentence as one call, for the caller that wants the figure
    without holding stores — a report, a dashboard, an operator watching
    depletion.  The gauge is resolved from ``database_url``, else from
    ``DATABASE_URL``, exactly as :func:`promotion.terminal.
    block_when_no_clean_epoch_remains` resolves its verdict, and it is composed
    over the charge store the same URL wires — one database by construction,
    never two the caller has to keep consistent.  The whole-table read is
    performed through feature 294's own ``epochs`` seam and delegated to the
    pure count, so there is one count in the member.

    An :class:`~promotion.errors.EpochChargeError` from the read propagates
    unwrapped: the refusal already names the row that could not be read, and
    re-wrapping it here would put a second message in front of the one an
    operator needs.  The count itself never raises — a spent or empty ledger
    answers ``0``.
    """
    url = _resolved_url(database_url, env)
    return RemainingCleanEpochs(EpochCharges(url)).remaining()


def _resolved_url(
    database_url: str | None, env: Mapping[str, str] | None
) -> str:
    """The URL the module-level spelling acts on, or a refusal naming the gap.

    The same seam :func:`promotion.terminal._resolved_url` and
    :func:`promotion.selection._resolved_url` resolve, restated in this
    feature's vocabulary: an explicit URL wins, else ``DATABASE_URL``, and a
    caller that names neither — or names one that is only whitespace, which
    names no database either — is refused *by name* rather than silently doing
    nothing.  The silence is the dangerous failure here and not the refusal: a
    gauge that quietly returned nothing would leave a dashboard showing a full
    ledger while the epochs ran out unseen, which is the state §13 item 4's
    ledger exists to make visible rather than hide.
    """
    source = os.environ if env is None else env
    url = (
        database_url
        if database_url is not None
        else source.get(DATABASE_URL_ENV, "")
    )
    if not isinstance(url, str) or not url.strip():
        raise EpochChargeError(
            f"{EPOCH_CHARGE_ERROR_CODE}: no database is named — neither a "
            f"database_url nor {DATABASE_URL_ENV} states one, so there is no "
            "ledger to count the clean epochs remaining from. §13 item 4 "
            "budgets sequestered epochs by exactly that count, and a gauge "
            "resolved from nothing is a refusal rather than a silent no-op — a "
            "dashboard that quietly showed a full ledger while the epochs ran "
            "out unseen is the state the ledger exists to make visible, not "
            "hide (feature 297)"
        )
    return url.strip()
