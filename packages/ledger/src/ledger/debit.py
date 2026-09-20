"""Feature 95's endpoint: POST /ledger/debit, the idempotent charge.

app_spec.xml, "Trial Ledger Append-Only Accounting", feature 95: *System
exposes POST /ledger/debit appending one trial row idempotently keyed by
node_id, which returns the prior sequence on a retry.*  The spec's API
summary spells the route's one line — ``POST /ledger/debit — Append one
irreversible trial charge idempotently`` — and docs/nullius-tech-
architecture.md states why idempotence is the contract rather than a
convenience: §6.1's pipeline runs ``debit_ledger`` as step 11 *even when
the node fails* ("A failed evaluation still consumed a hypothesis"), and
§14 runs its eval workers on spot instances whose reclamation is a
scheduled event, not an accident — *"Failures retry; ledger debits are
idempotent by* ``node_id``".  A debit that double-charged on retry would
inflate the one number this whole category exists to keep honest, and it
would do so precisely on the failure path, where nobody is watching.

**The node is the key because the node is the evaluation.**  §8's row
names a charge by ``node_id`` and nothing else is needed to identify it:
one evaluation is one node is one charge is one row.  So the second
POST for a node that already holds a row is, by construction, a retry of
the same charge — the worker died after the row landed but before the
response made it back, and the worker that takes over posts again — and
the endpoint's whole job is to answer it without appending: the response
carries the *prior* sequence, the very number the original POST
returned, so the caller's account of what was spent and the ledger's
never diverge no matter how many times the retry fires.

**This is the route's contract as a Python seam, not an HTTP server.**
The workspace's operations surface is its composed components — every
"exposes" feature in the spec landed as one — and this endpoint follows:
:class:`DebitEndpoint.post` takes a :class:`DebitRequest` (the body) and
returns a :class:`DebitResponse`, with :data:`DEBIT_ROUTE` spelling the
route once so the endpoint, the spec's summary and whatever HTTP adapter
lands later cannot drift apart on the name.  The endpoint delegates
every storage decision to :meth:`ledger.store.TrialLedger.debit`, which
holds the check-and-insert inside one transaction on one connection —
the atomicity is the store's to keep, the request/response shape is the
endpoint's to say, and neither reaches into the other's half.

**The request is a frozen value, validated at construction.**  A request
whose ``node_id`` is not a UUID, whose ``ts`` is naive, or whose
``outcome`` is not one of the four a trial can end in
(:data:`~ledger.outcome.OUTCOMES`, feature 91), is refused before the
store is touched — a malformed body spends no sequence number — and the
canonical spellings (UUID text, aware-UTC stamps) mean two requests for
the same evaluation compare equal however the caller came by the
identities.  The outcome is required with no default: the retry this
endpoint exists to answer is the failure path's own charge, and a body
that cannot say how the evaluation ended would debit it unclassified.

**The response is a fact, not a receipt to reinterpret.**  ``seq`` is
the row's own sequence — fresh on the first POST, prior on every retry —
``appended`` says whether *this* call appended the row (``False`` is
what a retry looks like), and ``record`` carries the full
:class:`~ledger.record.TrialLedgerRecord` the answer was drawn from.
All three are one answer drawn one way, so a caller that posts the same
request twice and compares responses finds the sequence equal and only
``appended`` differs — the observable whole of "idempotently keyed by
``node_id``, which returns the prior sequence on a retry".

**An absent store composes no endpoint.**  :meth:`DebitEndpoint.from_env`
returns ``None`` when no ``DATABASE_URL`` is set, the same
degrade-don't-break stance the member's own builder takes — while the
evaluator whose step 11 must debit is, again, the caller that must not
find itself in that state.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Optional

from .outcome import validated_outcome
from .record import TrialLedgerRecord, _validated_instant, _validated_uuid
from .store import TrialLedger

__all__ = [
    "DEBIT_ROUTE",
    "DebitEndpoint",
    "DebitRequest",
    "DebitResponse",
]

#: The route this endpoint serves — app_spec.xml's API summary row for
#: the Trial Ledger domain, spelled once: ``POST /ledger/debit — Append
#: one irreversible trial charge idempotently``.  Carried on the class
#: (:attr:`DebitEndpoint.route`) so a composed deployment can state its
#: routes from the components it holds rather than from a string that
#: lives somewhere else.
DEBIT_ROUTE = "/ledger/debit"


@dataclass(frozen=True, slots=True)
class DebitRequest:
    """The body of one POST /ledger/debit: the charge to append.

    Two identities — the evaluated ``node_id`` (the idempotency key: the
    node is the evaluation) and the ``campaign_id`` it belongs to — the
    ``outcome`` the evaluation ended in (feature 91's stamp: one of
    'ok', 'timeout', 'error', 'tripwire_fail', required, because §6.1's
    step 11 debits even when the node fails and the charge must record
    which failure it is), plus an optional ``ts`` for the replay path,
    which debits the instant it is reproducing rather than the instant
    it ran.  Construction canonicalises the identities to UUID text and
    refuses anything that is not one, holds the outcome to the closed
    vocabulary, and normalises a given ``ts`` to aware-UTC while
    refusing a naive instant, the same row contract
    :class:`~ledger.record.TrialLedgerRecord` states: a charge that
    cannot be joined, ranged or classified is a charge no audit can
    use, and it is refused before the store is ever touched.

    Frozen, because a request is a fact the caller stated; editing one
    in flight would be posting a different charge than was validated.
    """

    #: The evaluated node — the idempotency key, canonical UUID spelling.
    node_id: str
    #: The campaign the node belongs to, canonical UUID spelling.
    campaign_id: str
    #: How the evaluation ended — one of :data:`~ledger.outcome.OUTCOMES`.
    outcome: Optional[str] = None
    #: When the charge was debited, aware-UTC; ``None`` stamps at the
    #: store's default clock when the row is appended.
    ts: Optional[dt.datetime] = None

    def __post_init__(self) -> None:
        # frozen+slots forbids plain assignment, so canonicalisation writes
        # through object.__setattr__ exactly once, at construction.  After
        # this the instance is sealed — the same discipline the record
        # layer follows.
        object.__setattr__(
            self, "node_id", _validated_uuid(self.node_id, "node_id")
        )
        object.__setattr__(
            self, "campaign_id", _validated_uuid(self.campaign_id, "campaign_id")
        )
        object.__setattr__(
            self, "outcome", validated_outcome(self.outcome)
        )
        if self.ts is not None:
            object.__setattr__(self, "ts", _validated_instant(self.ts, "ts"))

    @property
    def key(self) -> str:
        """The idempotency key this POST is answered by: the node's identity.

        Spelled out because the feature's own clause — "idempotently
        keyed by ``node_id``" — is a statement about this one column,
        and the retry semantics read off it: two requests with one key
        are one charge.
        """
        return self.node_id


@dataclass(frozen=True, slots=True)
class DebitResponse:
    """The answer to one POST /ledger/debit: the sequence, and whose it is.

    ``appended`` is whether *this* call appended the row; a retry is a
    call where it is ``False`` — the row was already there, and this
    POST changed nothing.  ``record`` is the node's row in full: fresh
    on the first POST, prior on every retry.  ``seq`` (a property, so it
    cannot drift from the record) is the number the caller accounts
    with — the feature's own clause is "returns the prior sequence on a
    retry", and on a retry this is the sequence the *original* POST
    returned, not a new one.

    Frozen, because the response is the endpoint's testimony about the
    ledger's state at one moment; two responses that differ in ``seq``
    for one request would be the endpoint revising its testimony, which
    is what idempotence exists to make impossible.
    """

    #: Whether this call appended the row — ``False`` on a retry.
    appended: bool
    #: The node's row: freshly appended, or the prior row a retry is
    #: answered by.
    record: TrialLedgerRecord

    @property
    def seq(self) -> int:
        """The charge's sequence number — the prior one, on a retry."""
        return self.record.seq

    @property
    def retry(self) -> bool:
        """Whether this POST was a retry — answered by a row already held.

        The readable spelling of ``not appended``, named for the clause
        it asserts: the feature's contract is about what a *retry*
        returns, and the caller that just posted should be able to ask
        exactly that question.
        """
        return not self.appended


class DebitEndpoint:
    """Serves POST /ledger/debit over one :class:`~ledger.store.TrialLedger`.

    Constructed with the store it debits; :meth:`post` is the route.  The
    endpoint holds no state of its own — no memo of debited nodes, no
    cache of sequences — because idempotence that lived in the endpoint
    would be idempotence that a second process, a restart or a reclaimed
    spot instance silently voids.  The row in the table is the only
    record of what was charged, so it is the only thing the answer is
    drawn from, on every request, in every process.
    """

    #: The route this endpoint serves — :data:`DEBIT_ROUTE`, pinned as a
    #: class attribute so ``DebitEndpoint.route`` states the contract
    #: without an instance.
    route = DEBIT_ROUTE

    def __init__(self, ledger: TrialLedger) -> None:
        # Duck-checked rather than isinstance-guarded: the factory's scan
        # imports this member under an alias module, so the *composed*
        # ledger component is structurally a TrialLedger but never the
        # same class object a direct import yields — an isinstance here
        # would refuse the very component the factory hands out.  The
        # contract is the debit seam, and that is what is checked.
        if not callable(getattr(ledger, "debit", None)):
            raise TypeError(
                "DebitEndpoint speaks a TrialLedger (something with a "
                f"debit(node_id, campaign_id) seam); got "
                f"{type(ledger).__name__}"
            )
        self._ledger = ledger

    # -- Construction -------------------------------------------------------

    @classmethod
    def from_env(
        cls, env: Optional[Mapping[str, str]] = None
    ) -> Optional["DebitEndpoint"]:
        """The endpoint over the ledger ``DATABASE_URL`` names, or ``None``.

        Resolves the store exactly as the member's own builder does
        (:meth:`ledger.store.TrialLedger.resolve`), so the endpoint and
        the composed ``ledger`` component always point at the same
        database.  No ``DATABASE_URL`` composes no endpoint — an
        unconfigured store is a discoverable state, not an error — while
        the caller whose pipeline must debit is, again, the one that
        must not find itself in it.
        """
        ledger = TrialLedger.resolve(env)
        return None if ledger is None else cls(ledger)

    @property
    def ledger(self) -> TrialLedger:
        """The store this endpoint debits."""
        return self._ledger

    # -- The route ----------------------------------------------------------

    def post(
        self,
        request: DebitRequest,
        *,
        clock: Optional[Callable[[], dt.datetime]] = None,
    ) -> DebitResponse:
        """Answer one POST /ledger/debit: append the charge, or return the prior row.

        The whole of feature 95 at its seam, carrying feature 91's
        stamp.  The request's node is the idempotency key: when the
        node holds no row the charge is appended — one row, one fresh
        sequence, the outcome it ended with — and when it holds one
        (the worker died after the row landed; the response was lost;
        the retry fired) nothing is written and the response carries
        the *prior* sequence and the *prior* row, so the caller
        accounts with the number the original POST returned.  ``clock``
        overrides the default stamp the store would use when the
        request carries no ``ts`` (tests and replays route their own
        time through it).

        Refusals are the request's own (a malformed body never reaches
        the store) and the store's (a configured store whose write fails
        raises :class:`~ledger.errors.TrialStoreError` rather than
        letting a debit silently not land).
        """
        record, appended = self._ledger.debit(
            request.node_id,
            request.campaign_id,
            request.outcome,
            ts=request.ts,
            clock=clock,
        )
        return DebitResponse(appended=appended, record=record)
