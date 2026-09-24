"""The terminal verdict: §13 item 4's stop, judged over the whole ledger.

Feature 296's sentence — *"System blocks promotion when no clean sequestered
epoch remains, which returns a terminal state rather than reusing a retired
epoch."* — and the file where *the whole-table stop* is the claim.  Where
feature 295 answers *may this epoch still be spent?* about one row, this
feature answers *may the system continue at all?* about the whole table: it
judges whether every sequestered epoch has served §13 item 4's budget of
three promotion decisions, and when every epoch has — or when the ledger
holds no epoch at all — it declares the terminal state the PRD's second
sentence calls legitimate.

**The verdict is derived, not persisted.**  It writes nothing, spells no
DDL, authors no statement, opens no connection and gains no order in
:mod:`promotion.schema` — the `retired` flag is the exhaustion machinery's
*persistence* of this verdict, and this module is the *judgment* that
precedes it, not a second spelling of it.  So it must not read the `retired`
flag to decide (that would be this feature's own reader reading itself — a
circularity the terminal state is built to avoid), must not read `sealed_at`
(the sealing process's fact, which judges nothing here), and must not read a
pool, a score, a coverage ledger, a calibration status or any promotion
merit — whether the promotion *stands* is the deciding evaluation's verdict
(feature 292's mismatch is the only comparison against the recorded hash, and
features 298's and 299's refusals read the campaign and the coverage ledger),
tables this act never opens.

**The budget is feature 295's number, used here.**  Three, spelled once in
:func:`promotion.selection.SEQUESTERED_EPOCH_BUDGET` and *used* rather than
restated — a second spelling of ``3`` would be a second place the budget
lives, free to disagree with the one the selection gate compares against.
The comparison is ``>=``, the spelling ``0110``'s own docstring gives feature
295 (``promotion_decisions_served >= 3``), so an epoch that has *exceeded*
its budget counts as spent on the same comparison rather than falling
through an equality pin.

**The verdict is not the conjunction of feature 295's per-epoch refusals.**
When every epoch is spent the verdict refuses with ``no_clean_epoch_remains``
and names the whole ledger; when one epoch is spent and another is clean it
does **not** refuse — it answers that the system may continue (the clean
epoch), leaving the per-epoch refusal to feature 295's gate at the moment
that spent epoch is selected.  The verdict is a question about the *system's*
continuation, not about any one epoch's spend, and that difference is what
the tests pin hardest: a suite that only tested "every epoch spent" would
pass for a module that had quietly become ``all(select(e))`` — the
conjunction of the selection gate's refusals — rather than its own
whole-table judgment.

The split this module states, the one :func:`promotion.selection.
rejects_further_selection` and :class:`promotion.selection.EpochSelections`
state for the selection gate:

* :func:`blocks_when_no_clean_epoch_remains` is the *pure* half — the
  feature's whole sentence as one comparison, and the seam for the caller
  that **already holds the figure**: it takes the ledger's rows and either
  the system may continue or it may not.
* :class:`TerminalStates` is the *gate* — constructed over an
  :class:`~promotion.epoch.EpochCharges` (or anything with its ``epochs``
  seam), it performs the whole-table read through feature 294's own store
  and delegates to the pure judgment, so there is one comparison in the
  member and this act cannot disagree with the pure judgment a caller may use
  directly.
* :func:`block_when_no_clean_epoch_remains` is the module-level spelling —
  the feature's sentence as one call for the caller that wants the verdict
  without holding stores, resolving the charge store from a URL exactly as
  :func:`promotion.selection.select_epoch` resolves its gate.

The rows are duck-read — ``epoch_id`` and ``promotion_decisions_served`` — so
the composed listing and a test's stand-ins judge identically, and the
verdict holds no cache of counts this process had already judged, for the
reason every store in this member states for its rows: the ledger is the only
record of what the epochs have served, so it is the only thing a verdict is
drawn from, judged on every call, in every process.

Stdlib only, and import-cheap: ``os``, ``collections.abc`` and ``typing`` at
module scope plus this member's own modules (:mod:`promotion.epoch` for the
budget and the ``epochs`` seam, :mod:`promotion.errors` for the shared base)
— not even ``sqlite3``, because the connection is the charge store's and this
module never opens one — so the factory's scan imports this package for the
near-nothing it always did.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from typing import Any

from .epoch import EpochCharges
from .errors import (
    NO_CLEAN_EPOCH_REMAINS_CODE,
    PromotionBlockedError,
)
from .pre_register import DATABASE_URL_ENV
from .selection import SEQUESTERED_EPOCH_BUDGET

__all__ = [
    "TerminalStates",
    "block_when_no_clean_epoch_remains",
    "blocks_when_no_clean_epoch_remains",
]


# -- Validation --------------------------------------------------------------------


def _validated_served_count(value: Any, epoch: str) -> int:
    """Return ``value`` as a served count, or refuse what is not one.

    A non-negative ``int``, with ``bool`` refused first — ``True`` is ``1``
    in Python, and a flag where a count belongs would silently answer one
    decision nobody recorded.  Negative is refused because no honest count
    of rows is negative and no writer in this member could have landed one,
    and a non-integer — a fraction, text — is refused because a figure
    nobody derived is not one epoch's row could carry.  The *rule* is
    :func:`promotion.epoch._validated_served_count`'s own, restated here
    rather than reused for the reason :func:`promotion.selection.
    _validated_served_count` restates it: that module's message opens with
    the selection's code word and names feature 295, so a caller who handed
    this verdict a fraction or a flag would be told about a selection that
    never happened instead of the whole-table judgment that could not be
    made.  What it raises is this feature's own vocabulary, so a caller whose
    single ``except PromotionBlockedError`` guards its promotion path is not
    defeated by a refusal phrased for a selection it never asked about.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise PromotionBlockedError(
            f"{NO_CLEAN_EPOCH_REMAINS_CODE}: "
            "promotion_decisions_served must be a non-negative integer — got "
            f"{value!r} ({type(value).__name__}); the count is §13 item 4's "
            "budget of the promotion decisions a sequestered epoch has "
            "served, and a figure that is not a count of rows is not one "
            f"{epoch}'s row could carry — feature 294's charge derives it "
            "from the closed registry rows or nothing does (feature 296)"
        )
    if value < 0:
        raise PromotionBlockedError(
            f"{NO_CLEAN_EPOCH_REMAINS_CODE}: "
            "promotion_decisions_served must be a non-negative integer — got "
            f"{value!r}. The count is derived from the closed "
            "promotion_registry rows feature 293's listing holds against the "
            "epoch, and no count of rows is negative — a negative figure "
            "handed to this verdict is an edit no writer in this workspace "
            "produced, and judging the system's continuation on it would be "
            "blocking or admitting promotion on a number nobody derived "
            "(feature 296)"
        )
    return value


def _spent_count(served: int, budget: int) -> bool:
    """Whether one epoch has served §13 item 4's budget — ``served >= budget``.

    The whole-table verdict's one comparison, spelled here so the pure
    judgment and the gate share it and it cannot drift.  ``>=``, the spelling
    ``0110``'s own docstring gives feature 295, so an epoch that has
    *exceeded* its budget counts as spent on the same comparison rather than
    falling through an equality pin — a figure past the budget is not a
    cleaner epoch for exceeding it.
    """
    return served >= budget


# -- The pure judgment ---------------------------------------------------------------


def blocks_when_no_clean_epoch_remains(
    rows: Iterable[Any], *, budget: int = SEQUESTERED_EPOCH_BUDGET
) -> int:
    """Judge whether the system may continue — feature 296's whole-table act.

    Takes the ledger's rows — each duck-read as ``epoch_id`` and
    ``promotion_decisions_served``, so the composed listing and a test's
    stand-ins judge identically — and either the system may continue or it
    may not.  This is the whole of the feature's sentence — *"System blocks
    promotion when no clean sequestered epoch remains"* — as one comparison,
    and it is the seam for the caller that **already holds the figure**: a
    report, a later feature that reached the rows its own way, a test
    judging the boundary.  The caller that holds only the charge store asks
    :meth:`TerminalStates.blocks` instead, which performs the whole-table
    read through feature 294's own seam and then delegates here, so there is
    one comparison in the member and not two.

    **It raises** :class:`~promotion.errors.PromotionBlockedError` when the
    system may not continue — every sequestered epoch has served ``budget``
    (``served >= budget``, the spelling ``0110``'s own docstring gives
    feature 295), **or the ledger holds no epoch at all** — and returns the
    count of clean epochs remaining otherwise.  Raising rather than answering
    a boolean is the stance :func:`promotion.selection.
    rejects_further_selection` takes for exactly this caller: the verdict is
    the last line before the system stops, so the stop has to be the
    function's own act rather than a branch every caller must remember to
    make, and the caller that forgets is precisely a system that quietly had
    no clean epoch to run on.

    **The empty ledger is refused, not read as "all clean".**  No sequestered
    epoch at all is a distinct, terminal fact: there is no epoch to spend, so
    promotion has nothing to run on, and reading the absence as "zero spent,
    all clean" would let a deployment that never sequestered an epoch book a
    promotion against nothing.  The refusal names the sealing process's act
    as the repair, keeping feature 295's two answers apart at the
    whole-table level — an absent row is *nobody sealed it*, not a clean
    epoch.

    **What it returns when it does not raise** is the count of clean epochs
    remaining — the figure feature 297's depleting count reports and this
    verdict agrees with, so the caller that wants to log or carry it does not
    read the table a second time.  It is the count of rows that have *not*
    served ``budget``, and it is the value the verdict compared and not a
    derived remainder: the remaining budget per epoch is arithmetic from the
    two figures, and this verdict is a question about the *system's*
    continuation, not about any one epoch's spend.

    **It is not the conjunction of feature 295's per-epoch refusals.**  When
    one epoch is spent and another is clean the verdict does **not** refuse —
    it answers that the system may continue (the clean epoch), leaving the
    per-epoch refusal to feature 295's gate at the moment that spent epoch is
    selected.  A verdict that refused here would be answering *may this epoch
    still be spent?* about one row, which is feature 295's question, not the
    whole-table *may the system continue?* this feature answers.

    Refuses, in this order, each naming what it is about and both in
    :class:`~promotion.errors.PromotionBlockedError`:

    1. a ``promotion_decisions_served`` that is not a non-negative count —
       there is no budget to compare, and neither blocking nor admitting the
       system on a figure nobody derived would be honest;
    2. the verdict itself — every epoch spent, or the ledger empty.
    """
    spent = 0
    total = 0
    for row in rows:
        epoch = getattr(row, "epoch_id", None)
        served = getattr(row, "promotion_decisions_served", None)
        total += 1
        if _spent_count(_validated_served_count(served, epoch), budget):
            spent += 1
    if total == 0 or spent == total:
        raise _blocked(spent, total)
    return total - spent


def _blocked(spent: int, total: int) -> PromotionBlockedError:
    """The terminal-state refusal, naming the exhausted ledger.

    One spelling for the two faces that block promotion — every epoch spent,
    or the ledger empty — gathered in one message, for the reason the class
    docstring gives: this feature's caller is a gate, and a gate's one
    failure mode is silence.  The message states how many epochs were judged,
    how many were spent, the terminal state §13 item 4 calls legitimate, and
    the repair — stop, there is no clean epoch to select.
    """
    if total == 0:
        return PromotionBlockedError(
            f"{NO_CLEAN_EPOCH_REMAINS_CODE}: no sequestered epoch remains to "
            "run on — the ledger holds no epoch, so promotion has nothing to "
            "book against. §13 item 4 budgets sequestered epochs by exactly "
            "the promotion decisions they serve, and a ledger with no epoch "
            "has no budget to spend: this is the terminal state §13 item 4 "
            "calls legitimate rather than a fault to fix. The repair is to "
            "stop — or, to run again, to sequester an epoch (the sealing "
            "process's act) before promotion is asked for (feature 296)"
        )
    return PromotionBlockedError(
        f"{NO_CLEAN_EPOCH_REMAINS_CODE}: every sequestered epoch is spent — "
        f"{spent} of {total} have served §13 item 4's budget of "
        f"{SEQUESTERED_EPOCH_BUDGET} promotion decisions, so no clean epoch "
        "remains to run on. This is the legitimate terminal state §13 item 4 "
        "calls for rather than a fault to fix: the epochs the system itself "
        "sequestered have each served their budget, and there is no clean one "
        "left to select. The repair is to stop — the system has run out of "
        "sequestered epochs, and reusing a retired one is the reuse §13 item "
        "4's ledger exists to prevent (feature 296)"
    )


# -- The gate ------------------------------------------------------------------------


class TerminalStates:
    """The gate that blocks promotion when no clean epoch remains — 296's act.

    Constructed **over** an :class:`~promotion.epoch.EpochCharges` (or
    anything with its ``epochs`` seam), never over a URL: every fact this
    gate judges comes from feature 294's own whole-table read, so it holds no
    connection, runs no bootstrap, authors no DDL and spells no statement.
    The wiring is the shape :class:`~promotion.selection.EpochSelections`
    takes toward the charge store, and it is duck-checked rather than
    ``isinstance``-guarded for the reason that class states: the factory's
    scan imports this member under a synthetic module name, so the *composed*
    charge store is structurally an ``EpochCharges`` but never the same class
    object a direct import yields, and a class check here would refuse the
    very component the factory hands out.

    **There is no state to hold.**  A memo of counts this process had already
    judged would make *may the system continue?* a question about this
    process's history — and the answer moves: a charge lands in another
    process a moment after this one asked, and the epoch that was clean is
    spent.  The ledger is the only record of what the epochs have served, so
    it is the only thing a verdict is drawn from, on every call, in every
    process.
    """

    #: The one verb of feature 294's whole-table read this gate drives, and
    #: the whole of what it requires: ``epochs`` for every ledger row.
    #: Duck-typed as a *set of verbs* rather than class-checked, for the
    #: reason the class docstring gives — the composed store and the directly
    #: imported one are different class objects with the same seam, and
    #: either is a valid thing to judge through.
    _SEAM = ("epochs",)

    def __init__(self, charges: EpochCharges) -> None:
        """Wire the gate to the charge store it reads through — 294's seam.

        The seam is checked here, before any call, because it is a fact about
        the *gate* rather than about any one verdict: a reader with nothing
        to read through names no ledger, and one that accepted it would fail
        identically on every judgment — the wrong place to discover a wiring
        fault.  A ``TypeError`` rather than a
        :class:`~promotion.errors.PromotionBlockedError`, because a gate that
        cannot read is a *programming* error and not a promotion state: no
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
                "TerminalStates reads a charge store — something exposing "
                f"{' and '.join(self._SEAM)} — got {type(charges).__name__}, "
                f"which is missing {', '.join(missing)}. The verdict is judged "
                "on the whole ledger feature 294's own read answers with, so "
                "this gate reads through that store rather than a second "
                "reading of the table (feature 296)"
            )
        self._charges = charges

    # -- Construction -------------------------------------------------------

    @classmethod
    def from_env(
        cls, env: Mapping[str, str] | None = None
    ) -> TerminalStates | None:
        """The gate over the charge store ``DATABASE_URL`` names, or ``None``.

        Resolves the charge store exactly as the member's own builder
        resolves its registry (:meth:`~promotion.epoch.EpochCharges.
        resolve`), so the epochs a verdict judges and the counts the
        deployment charged always point at the same database.  No
        ``DATABASE_URL`` composes no gate — an unconfigured deployment is a
        discoverable state, not an error — while the caller whose promotion
        must not proceed on an exhausted ledger is, again, the one that must
        not find itself in it.
        """
        charges = EpochCharges.resolve(env)
        return None if charges is None else cls(charges)

    @property
    def charges(self) -> EpochCharges:
        """The charge store this gate reads through — feature 294's seam."""
        return self._charges

    # -- Feature 296: the verdict ---------------------------------------------------

    def blocks(self) -> int:
        """Judge whether the system may continue — feature 296's act.

        The steps, in the order they must happen:

        1. **Read the whole ledger** through feature 294's own ``epochs``
           seam — every sequestered epoch's row, the count feature 294
           persisted and the flag feature 296 reads — so the verdict is a
           function of the rows the charge answered with and cannot be a
           second reading of one table.
        2. **Delegate to the pure judgment** — :func:`blocks_when_no_clean_epoch_remains`
           over the rows — so there is one comparison in the member and this
           act cannot disagree with the pure judgment a caller may use
           directly.

        An :class:`~promotion.errors.PromotionBlockedError` from the judgment
        propagates unwrapped: the refusal already names the exhausted ledger,
        and re-wrapping it here would put a second message in front of the one
        an operator needs.  A refusal the read raises (a doubled row, an
        unreadable count, an unreachable database) propagates in *its*
        vocabulary — the verdict is judged on the rows, and a row that cannot
        be read is a different fact from one that is spent.

        **It returns** the count of clean epochs remaining — the figure
        feature 297's depleting count reports and this verdict agrees with —
        when the system may continue.
        """
        return blocks_when_no_clean_epoch_remains(self._charges.epochs())


# -- The module-level spelling -------------------------------------------------------


def block_when_no_clean_epoch_remains(
    rows_or_url: Any,
    *,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> int:
    """Judge whether the system may continue — the module-level spelling of 296's act.

    The feature's sentence as one call, for the caller that wants the verdict
    without holding stores.  The gate is resolved from ``database_url``, else
    from ``DATABASE_URL``, exactly as :func:`promotion.selection.select_epoch`
    resolves its gate, and it is composed over the charge store the same URL
    wires — one database by construction, never two the caller has to keep
    consistent.  The whole-table read is performed through feature 294's own
    ``epochs`` seam and delegated to the pure judgment, so there is one
    comparison in the member.

    An :class:`~promotion.errors.PromotionBlockedError` from the judgment
    propagates unwrapped: the refusal already names the exhausted ledger, and
    re-wrapping it here would put a second message in front of the one an
    operator needs.
    """
    url = _resolved_url(database_url, env)
    return TerminalStates(EpochCharges(url)).blocks()


def _resolved_url(
    database_url: str | None, env: Mapping[str, str] | None
) -> str:
    """The URL the module-level spelling acts on, or a refusal naming the gap.

    The same seam :func:`promotion.epoch.charge_epoch` and
    :func:`promotion.selection._resolved_url` resolve, restated in this
    feature's vocabulary: an explicit URL wins, else ``DATABASE_URL``, and a
    caller that names neither — or names one that is only whitespace, which
    names no database either — is refused *by name* rather than silently
    doing nothing.  The silence is the dangerous failure here and not the
    refusal: a verdict that quietly went unjudged is an exhausted ledger read
    as clean, which is the state §13 item 4's ledger exists to make
    impossible.
    """
    source = os.environ if env is None else env
    url = (
        database_url
        if database_url is not None
        else source.get(DATABASE_URL_ENV, "")
    )
    if not isinstance(url, str) or not url.strip():
        raise PromotionBlockedError(
            f"{NO_CLEAN_EPOCH_REMAINS_CODE}: no database is named — neither a "
            f"database_url nor {DATABASE_URL_ENV} states one, so there is no "
            "ledger to read the epochs' served counts from. §13 item 4 budgets "
            "sequestered epochs by exactly that count, and a verdict resolved "
            "from nothing is a refusal rather than a silent no-op — a system "
            "that quietly had no clean epoch to run on is the state the ledger "
            "exists to make impossible (feature 296)"
        )
    return url.strip()
