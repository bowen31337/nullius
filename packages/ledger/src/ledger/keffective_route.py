"""Feature 94's endpoint: GET /ledger/k-effective, the deflation input.

app_spec.xml, "Trial Ledger Append-Only Accounting", feature 94: *System
exposes GET /ledger/k-effective which returns K_effective per epoch as the
deflation input.*  The spec's API summary spells the route's one line —
``GET /ledger/k-effective — Return budget-charging trial counts per
epoch`` — and docs/nullius-tech-architecture.md fixes what the answer is
*for*: §8 counts it among the ledger's derived views and names the
consumer in the same breath — *"deflation inputs for ``β₃``"* — while
§10.3 writes the term the consumer computes, ``− β₃·deflation(K_eff)``,
beside the two penalized siblings it must never be confused with
(``− β₁·trials_charged``, ``− β₂·null_pick_rate``).

**The route exists so the deflation term never reaches for the wrong
number.**  Feature 93 already states the honest count
(:func:`ledger.keffective.derive_k_effective`, read off the store as
:meth:`ledger.store.TrialLedger.k_effective`); what this feature adds is
the *surface* a scoring process consumes it through.  §10.3's score keeps
two separate ledger terms — ``trials_charged`` and ``K_effective`` — and
they differ by exactly the null nodes, so
:meth:`ledger.store.TrialLedger.count` answers the first while this route
answers the second.  The endpoint therefore reaches only for the
``k_effective`` seam and never for the plain count: a route that fell back
to the row count would inflate the deflation input by every null node a
campaign ran, silently, under a route name that promises the opposite —
which is precisely the failure §7.2's opaque budget directive (feature
90) exists to make impossible.

**Neither an absent store nor a failed read is ever answered with a
number.**  No ``DATABASE_URL`` composes no endpoint
(:meth:`KEffectiveEndpoint.from_env` returns ``None``), the same
degrade-don't-break stance the store's own builder and feature 95's
endpoint take — and the reason is sharper here than there.  A debit that
fails to land raises where someone is watching; a deflation input that
quietly fell back to zero would read as *"this campaign consumed no
statistical budget"*, which is the one direction that lets a false
discovery through.  So a configured store whose read *fails* propagates
rather than being caught: this endpoint adds no fallback, because every
fallback it could add is a number the ledger never stated.  (An unreadable
row is refused by the derivation for the same reason: a charge that cannot
say whether it spent budget understates ``K`` if skipped, so it is an
error instead.)

**This is the route's contract as a Python seam, not an HTTP server.**
The workspace's operations surface is its composed components — every
"exposes" feature in the spec landed as one, feature 95's
:class:`~ledger.debit.DebitEndpoint` most recently — and this endpoint
follows: :meth:`KEffectiveEndpoint.get` takes no arguments (a GET over the
whole log has no body and no filter to state) and returns a
:class:`KEffectiveResponse`, with :data:`KEFFECTIVE_ROUTE` spelling the
route once so the endpoint, the spec's summary and whatever HTTP adapter
lands later cannot drift apart on the name.  The endpoint delegates the
whole derivation to :meth:`ledger.store.TrialLedger.k_effective`, which
owns the filter, the grouping and the refusals; the request/response shape
is this module's to say and neither half reaches into the other's.

**The response is feature 93's derivation, framed as the input its
consumer wants.**  It holds the :class:`~ledger.keffective.KEffective`
value the store answered with — one answer drawn one way, never
re-derived from the rows — and exposes the three reads §10.3's term
needs: ``counts`` (the per-epoch pairs, the clause's "per epoch"),
``total`` (the pooled ``K_effective`` when the consumer is asked for one
figure) and :meth:`KEffectiveResponse.of` (one epoch's honest count,
``0`` for an epoch that charged none).  Every one of them is the view's
own answer passed through, so a route figure and a store figure cannot
disagree; the rest of feature 93's API — ``by_epoch``, ``epochs``, the
falsiness of an all-null ledger — stays reachable through
:attr:`KEffectiveResponse.view` rather than being respelled here.

**An epoch the response reports at ``0`` is a fact, not an omission.**  A
route that listed only the epochs that charged budget would make "this
epoch contributed no degrees of freedom" inferable from a missing key,
and a key a reader has to infer is a key a reader can silently get wrong —
so an all-null epoch is reported, at ``0``, exactly as the derivation
reports it.  The response writes nothing on top of the derivation's
ordering either: unnamed epoch first, then ascending spelling.

Stdlib-only, like the rest of the member, and read by feature 259's
deflation term, which §10.3 requires to take ``K_effective`` rather than a
raw trial count.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Optional

from .keffective import KEffective
from .store import TrialLedger

__all__ = [
    "KEFFECTIVE_ROUTE",
    "KEffectiveEndpoint",
    "KEffectiveResponse",
]

#: The route this endpoint serves — app_spec.xml's API summary row for the
#: Trial Ledger domain, spelled once: ``GET /ledger/k-effective — Return
#: budget-charging trial counts per epoch``.  Carried on the class
#: (:attr:`KEffectiveEndpoint.route`) so a composed deployment can state
#: its routes from the components it holds rather than from a string that
#: lives somewhere else.
KEFFECTIVE_ROUTE = "/ledger/k-effective"


@dataclass(frozen=True, slots=True)
class KEffectiveResponse:
    """The answer to one GET /ledger/k-effective: the deflation input.

    ``view`` is feature 93's derivation as the store answered it — the
    per-epoch counts of budget-charging trials, the pooled total, and the
    derivation's own refusals — so the response is one answer drawn one
    way rather than a second computation of the same figure.  ``counts``,
    ``total`` and :meth:`of` are that derivation's own answers passed
    through (``total`` is a property, so it cannot drift from the pairs it
    sums), and anything else feature 93 states is reachable through
    ``view``.

    There is deliberately no raw trial count on this value.  §10.3's score
    penalizes ``trials_charged`` and deflates by ``K_effective``, and the
    two are different numbers; a response that also carried the row count
    would invite the substitution feature 259 rejects.

    Frozen, because the response is the route's testimony about the
    ledger's state at the moment it was read: re-reading the same log
    yields an equal value, and nothing here is a knob to adjust.
    """

    #: The store's answer: ``K_effective`` per epoch (feature 93).
    view: KEffective

    def __post_init__(self) -> None:
        # Duck-checked rather than isinstance-guarded, for the reason the
        # endpoint's own check gives: the factory's scan imports this
        # member under an alias module, so a *composed* store answers with
        # a KEffective that is structurally this one and never the same
        # class object a direct import yields.  The contract is the
        # derivation's three reads, and those are what is checked.
        if not callable(getattr(self.view, "of", None)) or not hasattr(
            self.view, "counts"
        ):
            raise TypeError(
                "KEffectiveResponse speaks a KEffective (something with "
                f"counts and of(epoch)); got {type(self.view).__name__}.  A "
                "response is the deflation input, so it is drawn from the "
                "derivation of feature 93 and never from a plain count."
            )

    @property
    def counts(self) -> tuple[tuple[Optional[str], int], ...]:
        """``K_effective`` per epoch — the clause, in the derivation's order.

        One ``(epoch, count)`` pair per observed epoch, the un-named epoch
        first, then ascending epoch spelling.  An epoch whose trials were
        all null nodes appears with a count of ``0`` rather than being
        omitted: the deflation term must be *told* that epoch contributed
        no degrees of freedom.
        """
        return self.view.counts

    @property
    def total(self) -> int:
        """``K_effective`` over the whole ledger — the sum of the epochs.

        The single figure a consumer asks for when it wants one number
        rather than a breakdown.  It is the derivation's own total, and it
        equals the ledger's row count only when no null node was ever
        charged.
        """
        return self.view.total

    def of(self, epoch: Optional[str]) -> int:
        """``K_effective`` for one epoch — ``0`` when the epoch charged none.

        An epoch this response never observed answers ``0``, exactly as an
        observed all-null epoch does, because ``0`` is the honest count
        either way.
        """
        return self.view.of(epoch)

    def __len__(self) -> int:
        """How many epochs the response reports — the size of the breakdown."""
        return len(self.view.counts)


class KEffectiveEndpoint:
    """Serves GET /ledger/k-effective over one :class:`~ledger.store.TrialLedger`.

    Constructed with the store it reads; :meth:`get` is the route.  The
    endpoint holds no state of its own — no cache of a previous answer, no
    memo of a total — because the deflation input must be the ledger's
    state at the moment it is asked for: a campaign that charges a trial
    between two reads must move the second answer, and a cached total
    would make the deflation term depend on when the scoring process
    happened to start.  The rows in the table are the only record of what
    was charged, so they are the only thing the answer is drawn from, on
    every request, in every process.
    """

    #: The route this endpoint serves — :data:`KEFFECTIVE_ROUTE`, pinned as
    #: a class attribute so ``KEffectiveEndpoint.route`` states the
    #: contract without an instance.
    route = KEFFECTIVE_ROUTE

    def __init__(self, ledger: TrialLedger) -> None:
        # Duck-checked rather than isinstance-guarded, exactly as feature
        # 95's endpoint is and for the same reason: the factory's scan
        # imports this member under an alias module, so the *composed*
        # ledger component is structurally a TrialLedger but never the same
        # class object a direct import yields.  The contract is the
        # k_effective seam, and that is what is checked — an object that can
        # only count rows is refused here rather than answering the route
        # with the number §10.3 penalizes separately.
        if not callable(getattr(ledger, "k_effective", None)):
            raise TypeError(
                "KEffectiveEndpoint speaks a TrialLedger (something with a "
                "k_effective() derivation); got "
                f"{type(ledger).__name__}.  The route returns the "
                "budget-charging count per epoch (feature 93), not the "
                "ledger's plain row count."
            )
        self._ledger = ledger

    # -- Construction -------------------------------------------------------

    @classmethod
    def from_env(
        cls, env: Optional[Mapping[str, str]] = None
    ) -> Optional["KEffectiveEndpoint"]:
        """The endpoint over the ledger ``DATABASE_URL`` names, or ``None``.

        Resolves the store exactly as the member's own builder does
        (:meth:`ledger.store.TrialLedger.resolve`), so the endpoint, the
        composed ``ledger`` component and feature 95's debit endpoint always
        point at the same database.  No ``DATABASE_URL`` composes no
        endpoint — an unconfigured store is a discoverable state, not an
        error — while a deployment whose deflation term must read a
        ``K_effective`` is the one that must not find itself in it.
        """
        ledger = TrialLedger.resolve(env)
        return None if ledger is None else cls(ledger)

    @property
    def ledger(self) -> TrialLedger:
        """The store this endpoint reads."""
        return self._ledger

    # -- The route ----------------------------------------------------------

    def get(self) -> KEffectiveResponse:
        """Answer one GET /ledger/k-effective: ``K_effective`` per epoch.

        The whole of feature 94 at its seam.  The route takes no arguments:
        a GET over the append-only log has no body, and the spec's own words
        ask for the figure *per epoch* — a breakdown, not a filtered one —
        so the answer is the whole derived view every time.  A caller that
        wants one epoch's number asks the response
        (:meth:`KEffectiveResponse.of`), which draws it from the same
        derivation rather than from a second read.

        The counts are feature 93's: only rows whose stored
        ``charges_budget`` is true contribute, grouped by the ``epoch_id``
        stamp when the table carries one (feature 88) and under the
        un-named epoch when it does not.  Null nodes never inflate the
        figure, however many a campaign ran — the route's entire reason for
        existing beside :meth:`ledger.store.TrialLedger.count`.

        Refusals are the store's: an unreadable directive or an epoch key
        that names no epoch raises :class:`~ledger.errors.TrialRecordError`
        from the derivation, and a read that fails propagates.  Nothing
        here is caught, because the alternative — answering a deflation
        input this route did not read — is the error direction that lets a
        false discovery through.
        """
        return KEffectiveResponse(self._ledger.k_effective())
