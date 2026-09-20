"""Feature 96's derivation: the promotion decisions each sequestered epoch has served.

app_spec.xml, "Trial Ledger Append-Only Accounting", feature 96: *System
derives epoch usage counts from the epoch_ledger, which returns how many
promotion decisions each sequestered epoch has served.*  docs/design.md
lists the figure beside the honest counter on the operator surface —
*"Trial budget burn, epoch usage, ``K_effective`` per epoch"* — and
docs/nullius-tech-architecture.md §15 makes it an operational alarm:
*"Sequestered epochs exhausted | Ledger usage count ≥ 3 | **Stop.** This
is a legitimate terminal state, not a bug to work around"* — the rule
docs/alpha-engine-prd.md §13 item 4 states in its own words:
*"Sequestered epochs are retired permanently after 3 promotion decisions.
Track in a ledger."*  This module is that ledger's read.

**Two spend meters, one per resource, and this is the second.**  Feature
93's :class:`~ledger.keffective.KEffective` counts *trials charged* per
epoch out of the append-only ``trial_ledger`` — the statistical degrees
of freedom a campaign spent.  This counts *promotion decisions served*
per epoch out of ``epoch_ledger`` — the holdout's sequestration, spent
one decision at a time, because each decision is a chance for
information about a sequestered epoch to leak into what gets promoted
(§6.1's step 2 scores a committed pick on *"a sequestered epoch it has
never observed in any world"*).  Compute and degrees of freedom are one
resource, sequestration is another, and they are spent by different
events: §6.1's step 11 debits a trial, a promotion decision debits an
epoch.  So the two figures are two reads over two tables and neither is
a re-derivation of the other — a campaign that charged a thousand
budget-charging trials in one epoch has spent that epoch's sequestration
not at all, and an epoch that has served three decisions is exhausted no
matter how few trials were ever charged against it.

**The table is feature 105's; the writer is feature 294's; the read is
this module's.**  ``epoch_ledger`` is created by the versioned migration
(``migrations/versions/0110_epoch_ledger.py``) — one row per sequestered
epoch holding when it was sealed, how many promotion decisions it has
served, and whether it is retired — and the running count against the
serving epoch is advanced by the promotion plugin's persist (feature
294).  This module owns none of that: it does not create the table, does
not advance a count, and does not decide what "used up" means.  What it
owns is the *read* of the count column, exactly as feature 93 owns the
read of ``charges_budget`` and leaves the writing of the directive to
the null oracle.  The threshold that turns a count into a refusal
(≥ 3) is feature 295's clause and the retirement flag is feature 296's
column; both read the same table on their own terms, and neither is
presumed here.

**Every sealed epoch is reported, including a fresh one at ``0``.**  The
column's ``DEFAULT 0`` ("a freshly sealed epoch has served zero promotion
decisions, which is a fact to record as a ``0``, not an absence") is why
the view lists an unspent epoch rather than omitting it: the pool is a
depleting resource, and a reader must be able to see how many clean
epochs remain *before* any of them is spent.  An omitted key would make
that figure inferable only from absence — the same reasoning feature 93
gives for reporting an all-null epoch at ``0``.

**A retired epoch still reports what it served.**  Retirement does not
erase the count, and this derivation does not filter on the flag: the
epoch spent three decisions, and its usage entry is the record of that
spend.  Hiding a retired epoch's count would make the pool's burn
understate itself at exactly the moment the operator surface is asked
how the pool got here.  (Whether an epoch may be *selected* is feature
295's question and whether one is *clean* is feature 296's; both read
the ``retired`` column directly, and this module deliberately does not
read it at all.)

**One epoch is one row, so a repeated epoch is refused rather than
resolved.**  ``epoch_id`` is the table's ``PRIMARY KEY`` — feature 105's
sentence calls for "a unique constraint on ``epoch_id``" — so a stored
epoch holds exactly one served count, and two entries for one epoch in a
derivation's input are rows the table cannot hold: a caller bug or a
reader that assembled the wrong thing.  Both silent resolutions are
wrong in the direction that matters.  Summing *invents* decisions the
epoch never served, and last-wins can *lower* a count — which is the one
error direction that lets an epoch which has served its three decisions
read as clean, exactly the failure §15's alarm exists to raise.  So the
duplicate is named and refused, the same discipline feature 93 applies
to a corrupted directive.

**An absent table is the empty usage, not an error.**  ``epoch_ledger``
comes into being with the first sealing — either the migration or the
promotion plugin's own idempotent create — so a database that holds no
such table is a deployment where no epoch was ever sequestered.  The
honest answer is a view with no epochs in it, and it is also the safe
direction: no epochs observed means no clean epoch remains, which is
§15's terminal state rather than a licence to promote.  A table that
*exists* and cannot be read is the opposite case and is loud (see
:meth:`ledger.store.TrialLedger.epoch_usage`), because a configured
store that fails must never answer a zero the ledger did not state.

Stdlib-only, like the rest of the member, and read by feature 296's
"no clean epoch remains" refusal, feature 297's depleting-epoch count and
the operator surface's epoch-usage panel.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from .errors import TrialRecordError

__all__ = ["EpochUsage", "derive_epoch_usage"]


def _validated_epoch_id(value: Any) -> str:
    """Validate one epoch's name, returning it as the table spells it.

    Unlike the trial ledger's grouping key
    (:data:`ledger.keffective.UNNAMED_EPOCH`), there is no un-named bucket
    here and ``None`` is not an acceptable answer.  ``epoch_ledger``'s
    ``epoch_id`` is ``TEXT NOT NULL PRIMARY KEY`` (feature 105): its row
    *is* the sealing event, so an epoch that cannot be named cannot have
    been sequestered, and a row whose key is empty, blank or absent is a
    corrupted account rather than a legacy one.  A trial row may predate
    feature 88's stamp and honestly name no epoch; an epoch row cannot
    predate its own identity.
    """
    if isinstance(value, str) and value.strip():
        return value
    raise TrialRecordError(
        f"an epoch-usage count must be keyed by a non-empty epoch_id; got "
        f"{value!r} ({type(value).__name__}).  epoch_ledger's epoch_id is "
        f"feature 105's TEXT NOT NULL PRIMARY KEY — a row of that table is "
        f"a sequestered epoch, so a key that names no epoch is a corrupted "
        f"account, and reporting it would give every later usage count "
        f"(feature 96) a phantom epoch of its own."
    )


def _validated_decisions(value: Any) -> int:
    """Validate one served count, so a hand-built value cannot hold an impossible one.

    A non-negative ``int``, and not a ``bool`` — ``True`` is an ``int``
    subclass equal to 1, and a count that arrived as a truth value is a
    caller bug wearing a valid number, the same discipline the row layer
    applies to ``seq`` and feature 93's derivation applies to a trial
    count.  The floor at ``0`` is the column's own: ``promotion_decisions_
    served INT NOT NULL DEFAULT 0`` counts decisions *served*, and a
    negative one is a hand that reached past the promotion plugin's
    advance (feature 294) — refused rather than served, because a
    negative count is the one value that could make a spent epoch read as
    clean.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TrialRecordError(
            f"a promotion_decisions_served count must be a non-negative "
            f"integer; got {value!r} ({type(value).__name__}).  The column "
            f"counts the promotion decisions an epoch has served (feature "
            f"105) and is advanced by the promotion plugin's persist "
            f"(feature 294); a value that is not a count of decisions is a "
            f"corrupted account, and feature 296's exhaustion check reads "
            f"this number."
        )
    return value


@dataclass(frozen=True, slots=True)
class EpochUsage:
    """Feature 96's derived view: promotion decisions served, per epoch.

    ``counts`` is the view's whole content — one ``(epoch, served)`` pair
    per sequestered epoch, each number the count that epoch's
    ``epoch_ledger`` row holds.  Held as a tuple of pairs rather than a
    mapping so the value is genuinely immutable *and* hashable (a ``dict``
    field would make a frozen instance unhashable), and sorted by epoch
    spelling so two derivations over the same rows are equal values and
    read back in one order.

    Construction validates, so an instance is trustworthy by
    construction: :func:`derive_epoch_usage` builds the member's view
    through this constructor, and a caller that hand-builds one gets the
    same refusals — including the refusal of a repeated epoch, which no
    row of the table could have produced.  Frozen, because the view is a
    statement about the pool at the moment it was read — re-deriving it
    from the same rows yields an equal value, and nothing here is a knob
    to adjust.
    """

    #: One ``(epoch, decisions served)`` pair per sequestered epoch,
    #: ascending by epoch spelling.
    counts: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        # frozen+slots forbids plain assignment, so normalisation writes
        # through object.__setattr__ exactly once, at construction — the
        # same discipline the row layer follows.
        served: dict[str, int] = {}
        for pair in self.counts:
            try:
                epoch_value, count_value = pair
            except (TypeError, ValueError) as exc:
                raise TrialRecordError(
                    f"an epoch-usage count must be an (epoch, served) pair; "
                    f"got {pair!r}: {exc}"
                ) from exc
            epoch = _validated_epoch_id(epoch_value)
            count = _validated_decisions(count_value)
            # One epoch is one row (feature 105's primary key on
            # epoch_id), so a second entry for an epoch is rows the table
            # cannot hold — and both ways of resolving it silently would
            # misreport a depleting resource.  See the module docstring.
            if epoch in served:
                raise TrialRecordError(
                    f"epoch {epoch!r} appears twice in one epoch-usage "
                    f"derivation ({served[epoch]} decisions served, then "
                    f"{count}).  epoch_ledger holds one row per sequestered "
                    f"epoch — epoch_id is its PRIMARY KEY (feature 105) — so "
                    f"one epoch has one served count and this input is a row "
                    f"the table cannot hold.  Summing the entries would "
                    f"invent decisions the epoch never served and keeping "
                    f"the last would lower a count feature 296's exhaustion "
                    f"check reads, so the duplicate is refused rather than "
                    f"resolved."
                )
            served[epoch] = count
        object.__setattr__(
            self, "counts", tuple(sorted(served.items(), key=lambda item: item[0]))
        )

    @property
    def by_epoch(self) -> Mapping[str, int]:
        """The counts as a read-only mapping from epoch to decisions served.

        A fresh mapping on each access, over an immutable backing — the
        value stays frozen, and a caller that mutates what it is handed
        cannot reach back into the view.
        """
        return MappingProxyType(dict(self.counts))

    @property
    def epochs(self) -> tuple[str, ...]:
        """Every sequestered epoch this view reports, in the view's order.

        Includes an epoch that has served nothing — a freshly sealed one is
        reported at ``0`` and listed here, because "this epoch is clean"
        is a fact the pool's remaining-epoch figure depends on being told
        rather than left to infer from an omission.
        """
        return tuple(epoch for epoch, _ in self.counts)

    @property
    def total(self) -> int:
        """Decisions served across the whole pool — the sum of the epochs.

        The pool-wide burn, for the operator surface's epoch-usage panel:
        how many promotion decisions the sequestered epochs have served
        between them.  It is deliberately *not* a count of trials and not
        a count of epochs — :meth:`of` answers per epoch and :func:`len`
        answers how many epochs the pool holds.
        """
        return sum(count for _, count in self.counts)

    def of(self, epoch_id: Any) -> int:
        """Decisions served by one epoch — ``0`` when the view never saw it.

        An epoch no row was read for answers ``0``, the same honest count a
        freshly sealed epoch reports, and for the same reason feature 93
        gives: the two answers differing would make a reader's arithmetic
        depend on whether the epoch had been sealed in *this* database.
        That answer is also the safe one for §15's alarm — an epoch this
        ledger cannot find is an epoch it cannot vouch for as clean.

        The name is validated like any other, so asking about an epoch
        that names no epoch (``None``, an empty string) is refused rather
        than answered, because ``epoch_id`` is ``TEXT NOT NULL`` and such
        a question has no referent in the table.
        """
        return dict(self.counts).get(_validated_epoch_id(epoch_id), 0)

    def __bool__(self) -> bool:
        """Whether the pool holds any sequestered epoch at all.

        ``False`` only when no epoch has been sealed — an empty table, or
        no table.  Note the contrast with :class:`~ledger.keffective.
        KEffective`, whose falsiness turns on budget *spent*: there, an
        epoch nobody charged is indistinguishable from no epoch, so the
        two must answer alike.  Here the epochs are the pool itself, and a
        pool of freshly sealed epochs is a real, non-empty, entirely
        unspent resource — reporting it falsy would tell an operator the
        pool is gone at the moment it is fullest.
        """
        return len(self.counts) > 0

    def __len__(self) -> int:
        """How many sequestered epochs the pool holds — the view's size."""
        return len(self.counts)


def derive_epoch_usage(rows: Iterable[tuple[Any, Any]]) -> EpochUsage:
    """Count promotion decisions served per epoch — feature 96, in one pass.

    ``rows`` is an iterable of ``(epoch_id, promotion_decisions_served)``
    pairs: the epoch's name (feature 105's primary key) and the running
    count its ``epoch_ledger`` row carries (advanced by feature 294's
    persist).  The pair is the projection a reader makes from one ledger
    row, which is why it is the input shape: the *definition* — "one
    served count per sequestered epoch" — is stated here over the two
    columns it is a statement about, and
    :meth:`ledger.store.TrialLedger.epoch_usage` is the wiring that reads
    the table into that projection.

    Each pair contributes its own epoch's count verbatim.  Nothing is
    filtered, summed down or thresholded: an epoch at ``0`` is reported at
    ``0`` (a sealed, clean epoch is a fact the pool's size depends on), an
    epoch past three decisions is reported at what it served (retirement
    is feature 296's column, read there), and a repeated epoch is refused
    because the table's primary key makes it impossible for real rows to
    produce one.

    Both columns are validated through this module's own checks rather
    than trusted: an ``epoch_id`` that is empty, blank or absent names no
    sequestered epoch, and a count that is negative, not an integer or a
    truth value is not a count of decisions — a corrupted row is refused
    rather than served, the same discipline feature 93 applies to a
    stored budget directive.  The refusal direction matters here too: a
    count quietly read as "not spent" would let an exhausted epoch be
    selected again, which is the failure §15's terminal state exists to
    prevent.
    """
    return EpochUsage(tuple(rows))
