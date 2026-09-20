"""Feature 93's derivation: ``K_effective``, the honest count of budget charges.

app_spec.xml, "Trial Ledger Append-Only Accounting", feature 93: *System
derives K_effective per epoch by counting only rows with charges_budget
true, so null nodes never inflate the trial count.*  docs/nullius-tech-
architecture.md §8 names the derived view in its own sentence — *"Derived
views: ``K_effective`` per epoch (filtered on ``charges_budget``) …"* —
and §7.2 states the fact the filter encodes: a null node's signal *"was
never compared to real forward returns, so it consumed agent calls and
CPU but* **no statistical degrees of freedom**. *It must not inflate
``K`` in the deflation term"*.  This module is that filter, and nothing
else: the number §8's honest counter exists to make honest.

**The filter is the feature.**  Every clause of the sentence hangs off
"counting only rows with ``charges_budget`` true".  A row stamped
``True`` (feature 90's directive — a real trial that consumed statistical
degrees of freedom) contributes one to its epoch's count; a row stamped
``False`` (a null node) contributes nothing, no matter how many of them a
campaign ran.  So ``K_effective`` is never the number of rows the ledger
holds: :meth:`ledger.store.TrialLedger.count` is that number and stays
deliberately plain, while this is the count *of the trials that spent
statistical budget*, and the two diverge by exactly the null nodes.  That
divergence is the feature — the reason ``charges_budget`` had to cross
the null-oracle barrier as an opaque directive (feature 90) is so this
number could be computed without anyone learning which rows were null.

**The count is of *outcomes*, not of successes.**  A trial that ended
'timeout', 'error' or 'tripwire_fail' consumed a hypothesis exactly as a
successful one did — §6.1's step 11 debits *even when the node fails* —
so the outcome stamp (feature 91) plays no part in this filter.  Only
``charges_budget`` decides, because only ``charges_budget`` names the
resource being counted.  An epoch whose every trial failed still has a
``K_effective``, and it is not zero.

**Every observed epoch is reported, including the ones that charged
nothing.**  An epoch whose trials were all null nodes is reported with a
count of ``0`` rather than omitted: that ``0`` is the feature's whole
point made visible — the deflation term must be told *this epoch
contributed no degrees of freedom*, and a key a reader has to infer from
its absence is a key a reader can silently get wrong.  It also keeps
:meth:`KEffective.of` and the ``by_epoch`` mapping in agreement: both
answer ``0`` for an epoch no budget-charging trial reached, whether the
epoch was observed or never named at all.

**The epoch dimension arrives with feature 88, and this module reads it
when it is there.**  ``epoch_id`` is feature 88's stamp: *System records
epoch_id naming which sequestered epoch a trial charged, which rejects a
write whose epoch_id is absent.*  That is a *write* seam — the column, the
required argument, the refusal to append without one — and this module
deliberately owns none of it.  What this module owns is the *read*: the
grouping key is taken from the row's ``epoch_id`` when the table carries
the column, and every row is grouped under the un-named epoch
(``None``) when it does not.  The consequence is that the derivation is
correct before feature 88 lands (one bucket, honestly labelled "no epoch
named") and becomes a genuine per-epoch view the moment 88's column
appears, with no edit to this file.  Feature 88 writes the stamp; feature
93 counts by it; neither reaches into the other's half.

**A corrupted directive is refused, not silently discounted.**  The
budget value is read back through
:func:`ledger.budget.validated_charges_budget` — the same check the row
layer and the store's read path use — so a stored ``0``/``1`` is coerced
to its bool and a value that is neither (a hand-edit, a corruption) is
refused with :class:`~ledger.errors.TrialRecordError` rather than being
counted as "not true" and quietly shrinking the deflation input.  That
refusal happens for a null-looking row too: a row that cannot say whether
it charged budget is a row no audit can classify, and the safe-looking
default (skip it) is the one that understates ``K`` — the single
direction the honest counter must never move by accident.

Stdlib-only, like the rest of the member, and read by feature 94's
``GET /ledger/k-effective`` route and by feature 259's deflation term,
which §7.2 requires to take ``K_effective`` rather than a raw trial
count.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Optional

from .budget import validated_charges_budget
from .errors import TrialRecordError

__all__ = ["KEffective", "derive_k_effective"]

#: The mapping key a row carries when the ledger's table has no
#: ``epoch_id`` column yet — i.e. before feature 88's stamp lands.  Spelled
#: as ``None`` rather than a placeholder string so it cannot be mistaken
#: for an epoch a caller named, and so a reader that later sees real epoch
#: keys cannot confuse the two.
UNNAMED_EPOCH: Optional[str] = None


def _validated_epoch(value: Any) -> Optional[str]:
    """Validate a grouping key, returning it as the epoch's own spelling.

    ``None`` is the un-named epoch (:data:`UNNAMED_EPOCH`) and passes
    through untouched.  Any other value must be a non-empty, non-blank
    :class:`str`: feature 88's ``epoch_id`` is ``TEXT NOT NULL`` (§8), so
    an empty or whitespace-only spelling names no epoch, and refusing it
    here keeps a mis-spelled stamp from becoming a bucket of its own that
    every later count would report as a real, separate epoch.
    """
    if value is None:
        return None
    if isinstance(value, str) and value.strip():
        return value
    raise TrialRecordError(
        f"an epoch_id grouping key must be a non-empty string (or None for "
        f"the trials that predate feature 88's stamp); got {value!r} "
        f"({type(value).__name__}). K_effective is derived per epoch "
        f"(feature 93), so a key that names no epoch would be reported as "
        f"an epoch of its own."
    )


def _validated_count(value: Any) -> int:
    """Validate a count, so a hand-built value cannot hold an impossible one.

    A non-negative ``int``, and not a ``bool`` — ``True`` is an ``int``
    subclass equal to 1, and a count that arrived as a truth value is a
    caller bug wearing a valid number, the same discipline the row layer
    applies to ``seq``.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TrialRecordError(
            f"a K_effective count must be a non-negative integer; got "
            f"{value!r} ({type(value).__name__})"
        )
    return value


@dataclass(frozen=True, slots=True)
class KEffective:
    """Feature 93's derived view: budget-charging trials, per epoch.

    ``counts`` is the view's whole content — one ``(epoch, count)`` pair
    per observed epoch, each count the number of rows that epoch holds
    whose ``charges_budget`` is ``True``.  Held as a tuple of pairs rather
    than a mapping so the value is genuinely immutable *and* hashable (a
    ``dict`` field would make a frozen instance unhashable), and sorted
    with the un-named epoch first so two derivations over the same trials
    are equal values and read back in one order.

    Construction validates, so an instance is trustworthy by
    construction: :func:`derive_k_effective` builds the member's view
    through this constructor, and a caller that hand-builds one gets the
    same refusals.  Frozen, because the view is a statement about the
    ledger at the moment it was read — re-deriving it from the same rows
    yields an equal value, and nothing here is a knob to adjust.
    """

    #: One ``(epoch, count)`` pair per observed epoch, un-named epoch
    #: first, then ascending epoch spelling.
    counts: tuple[tuple[Optional[str], int], ...]

    def __post_init__(self) -> None:
        # frozen+slots forbids plain assignment, so normalisation writes
        # through object.__setattr__ exactly once, at construction — the
        # same discipline the row layer follows.
        totals: dict[Optional[str], int] = {}
        for pair in self.counts:
            try:
                epoch_value, count_value = pair
            except (TypeError, ValueError) as exc:
                raise TrialRecordError(
                    f"a K_effective count must be an (epoch, count) pair; got "
                    f"{pair!r}: {exc}"
                ) from exc
            epoch = _validated_epoch(epoch_value)
            # Each pair is one trial, so a repeated epoch accumulates —
            # summing rather than replacing is what "count of trials"
            # means when a caller hands the pairs in a flat sequence.
            totals[epoch] = totals.get(epoch, 0) + _validated_count(count_value)
        ordered = tuple(
            sorted(totals.items(), key=lambda item: (item[0] is not None, item[0] or ""))
        )
        object.__setattr__(self, "counts", ordered)

    @property
    def by_epoch(self) -> Mapping[Optional[str], int]:
        """The counts as a read-only mapping from epoch to ``K_effective``.

        A fresh mapping on each access, over an immutable backing — the
        value stays frozen, and a caller that mutates what it is handed
        cannot reach back into the view.
        """
        return MappingProxyType(dict(self.counts))

    @property
    def epochs(self) -> tuple[Optional[str], ...]:
        """Every observed epoch, in the view's own order.

        Includes an epoch all of whose trials were null nodes — it is
        reported with a count of ``0``, and it is listed here, because
        "this epoch contributed no degrees of freedom" is a fact the
        deflation term needs stated rather than implied by an omission.
        """
        return tuple(epoch for epoch, _ in self.counts)

    @property
    def total(self) -> int:
        """``K_effective`` over the whole ledger — the sum of the epochs.

        The number the deflation term consumes when it is asked for one
        figure rather than a breakdown, and the number that makes the
        feature's point arithmetic: it equals the ledger's row count only
        when no null node was ever charged.
        """
        return sum(count for _, count in self.counts)

    def of(self, epoch: Optional[str]) -> int:
        """``K_effective`` for one epoch — ``0`` when the epoch charged none.

        An epoch this view never observed answers ``0``, exactly as an
        observed all-null epoch does: ``0`` is the honest count of
        budget-charging trials either way, and the two answers differing
        would make a reader's arithmetic depend on whether a campaign had
        bothered to run the epoch's null nodes.
        """
        return dict(self.counts).get(_validated_epoch(epoch), 0)

    def __bool__(self) -> bool:
        """Whether any trial charged budget at all.

        ``False`` for an empty ledger *and* for a ledger of nothing but
        null nodes — the two states a caller checking "has anything spent
        statistical budget?" must not be able to confuse, because in both
        the honest answer is no.
        """
        return self.total > 0

    def __len__(self) -> int:
        """How many epochs the view reports — the size of the breakdown."""
        return len(self.counts)


def derive_k_effective(
    trials: Iterable[tuple[Any, Any]],
) -> KEffective:
    """Count budget-charging trials per epoch — feature 93, in one pass.

    ``trials`` is an iterable of ``(epoch, charges_budget)`` pairs: the
    epoch the trial charged (feature 88's stamp, or ``None`` when the row
    predates it) and the opaque budget directive it carries (feature 90).
    The pair is the projection a reader makes from one ledger row, which
    is why it is the input shape: the *definition* — "count only the rows
    whose directive is true, grouped by epoch" — is stated here over the
    two columns it is a statement about, and
    :meth:`ledger.store.TrialLedger.k_effective` is the wiring that reads
    a table into that projection.

    A pair whose directive is not ``True`` adds nothing to its epoch's
    count — that is the clause the feature turns on, and it is why a
    campaign may run any number of null nodes without moving this number
    by one.  Its epoch is still recorded, at ``0`` when nothing else
    charged there, so the epoch's existence is not erased by its
    frugality.

    The directive is validated through :func:`ledger.budget.
    validated_charges_budget` — the same check the row layer applies — so
    a stored ``0``/``1`` reads as its bool and a value that is neither is
    refused rather than treated as "not true".  The refusal is deliberate
    even for a row that would have contributed nothing: silently skipping
    an unreadable directive can only ever understate ``K``, and
    understating the deflation input is the error direction that lets a
    false discovery through.
    """
    counts: dict[Optional[str], int] = {}
    for pair in trials:
        try:
            epoch_value, budget_value = pair
        except (TypeError, ValueError) as exc:
            raise TrialRecordError(
                f"a trial must be an (epoch, charges_budget) pair; got "
                f"{pair!r}: {exc}"
            ) from exc
        epoch = _validated_epoch(epoch_value)
        charged = validated_charges_budget(budget_value)
        counts.setdefault(epoch, 0)
        if charged:
            counts[epoch] += 1
    return KEffective(tuple(counts.items()))
