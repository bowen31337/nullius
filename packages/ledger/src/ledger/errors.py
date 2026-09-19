"""The ledger plugin's error taxonomy.

One base class (:class:`TrialLedgerError`) so a caller — the evaluator's
debit step, an operator script, a later feature in this category — can
catch every failure of the accounting path with a single ``except``.  The
subclasses split by *which contract* was violated, not by which line of
code failed:

* :class:`TrialRecordError` — the row contract (app_spec.xml feature 86).
  A trial row's identity or stamp is malformed at the write — a
  ``node_id`` that is not a UUID, a naive ``ts``, a ``clock`` that is not
  callable — or a row read back from the table cannot be rebuilt into a
  trustworthy record.  Either way the row is a caller bug or a corrupted
  account, never a runtime condition to catch and continue past: a ledger
  that shrugs off a malformed charge is a ledger whose count of ``K`` is
  fiction, and ``K`` fiction is the one failure this whole category
  exists to make impossible (docs/nullius-tech-architecture.md §8: "The
  honest ``K`` counter").
* :class:`TrialStoreError` — the store contract.  The relational store is
  misrouted (a ``DATABASE_URL`` this member cannot speak) or configured
  and broken (the append's write failed).  A store that is *absent* — no
  ``DATABASE_URL`` at all — is not this error: it is a supported,
  discoverable state in which no ledger component composes (see
  :meth:`ledger.store.TrialLedger.resolve`), because the factory's stance
  toward an unconfigured component is to degrade, not to break.
* :class:`TrialImmutableError` — the immutability contract (app_spec.xml
  feature 92).  A statement that would UPDATE or DELETE a ``trial_ledger``
  row was refused before it ran.  The refusal is enforced at the store's
  connection — the SQLite spelling of feature 103's Postgres role grants
  that deny UPDATE and DELETE — so it meets every client, not merely the
  ones this package knows how to write.  A mutated row would restate a
  past charge, and the honest ``K`` counter (§8) does not restate.

Every message names the offending value and the contract it broke, in the
same discipline as the snapshot member's taxonomy: these errors are
operational signals for a pipeline whose step 11 (§6.1, ``debit_ledger``)
happens *even when the node fails*, so the debit path's failures must be
speakable, not merely loggable.
"""

from __future__ import annotations

__all__ = [
    "TrialLedgerError",
    "TrialRecordError",
    "TrialStoreError",
    "TrialImmutableError",
]


class TrialLedgerError(Exception):
    """Base class for every failure of the trial-ledger accounting path."""


class TrialRecordError(TrialLedgerError):
    """A trial_ledger row's identity or stamp was malformed.

    Raised at the write, where the cause can still be named (a ``node_id``
    that is not a UUID cannot be joined to the tree store later, so it is
    refused before any sequence number is spent on it), and at the read,
    where a row that cannot be rebuilt into a :class:`~ledger.record.
    TrialLedgerRecord` is refused rather than served — an unreadable row
    in an append-only log is evidence of tampering or corruption, and
    papering over it would silently under-count the trials the deflation
    term is computed over.
    """


class TrialStoreError(TrialLedgerError):
    """The trial ledger's store is misrouted, or its write failed.

    A ``DATABASE_URL`` whose scheme this member does not speak, a sqlite
    URL with a host or without a path, or a configured store whose INSERT
    failed.  The last case is raised rather than swallowed because a
    debit that silently failed to persist is exactly the state feature 86
    exists to prevent: an evaluation that consumed a hypothesis while the
    honest counter looked away.
    """


class TrialImmutableError(TrialLedgerError):
    """A statement that would mutate a ``trial_ledger`` row was refused.

    Raised by the store's connection layer (feature 92), before the
    statement runs, when the statement would UPDATE or DELETE a row of the
    ``trial_ledger`` table.  The refusal is enforced at the connection the
    store opens for every operation, so it holds for every client that
    reaches the table through this store — a raw connection, a second
    package, an operator script, a bug — and not merely for the append and
    debit methods, which never mutate by their own convention.  That is
    the SQLite spelling of feature 103's Postgres "role grants that deny
    UPDATE and DELETE": where the production database denies the privilege
    to the writing role, this member denies the statement at the seam that
    speaks to the database, because SQLite has no roles to grant to.

    The message names the table and the verb refused, so an operator
    reading a stack trace understands not merely that the statement failed
    but *why it must*: a mutated row would restate a past charge, and the
    honest ``K`` counter is append-only by enforcement, not by request.
    """
