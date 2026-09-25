"""The forward plugin's error taxonomy.

One base class (:class:`ForwardError`) so a caller — the pipeline step that
opens a record the moment a signal is promoted, an operator script, the
category's later features 333-340 — can catch every failure of the
forward-test path with a single ``except``.  The subclasses split by *what
the caller must do about it*, not by which line of code failed:

* :class:`ForwardRecordError` — the row contract.  A record's identity, its
  promotion instant, its observation date or — once feature 333 appends the
  rows that carry one — its live information coefficient is malformed at
  construction: a ``node_id`` that is not a UUID, a naive stamp, a ``DATE``
  that is not a date, a coefficient that is not a finite real in ``[−1, 1]``
  (a correlation is bounded by construction, and a figure outside the bound
  is a z-score or a hit rate wearing the field's name).  Or a row read back
  from the table cannot be rebuilt into a trustworthy record.  Either way
  the row is a caller bug or a corrupted record, never a runtime condition
  to catch and continue past: this is the one table in the system whose
  whole value is the *vintage* it carries (``0108``'s own docstring: *"a row
  that lost its promotion timestamp would be an observation with no vintage,
  which is exactly the thing forward testing exists to prevent"*), so a
  record whose promotion instant cannot be trusted is a record that
  measures nothing — and a record whose coefficient cannot be trusted is a
  measurement nobody made.

* :class:`ForwardStoreError` — the store contract.  The relational store is
  misrouted (a ``DATABASE_URL`` this member cannot speak) or configured and
  broken (the write failed, a parent row is absent, a row could not be read
  back).  Feature 333 adds the two states the observing write can find the
  table in: a signal that holds **no record at all** — the observation job
  ran ahead of the promote step, and the repair is feature 332's act, which
  is this feature's declared parent — and a record whose rows carry **two
  promotion instants**, which no append can extend because nobody can state
  the boundary they disagree about.  A store that is *absent* — no
  ``DATABASE_URL`` at all — is **not** this error: it is a supported,
  discoverable state in which no ``forward`` component composes (see
  :meth:`forward.record.Forwards.resolve`), because the factory's stance
  toward an unconfigured component is to degrade, not to break.

* :class:`ForwardPromotionError` — the promotion seam.  The promotion
  member's own window could not be read for the node this promotion names —
  nobody pre-registered it, its deciding evaluation has not run yet, or its
  registry row could not be read as a decision — and this row's own subject,
  the instant the window opens at, therefore does not exist.  Its repair is
  *the promotion's*, not this member's: pre-register the criteria (feature
  291) and then record the decision (feature 293).  It is a class of its own
  rather than a :class:`ForwardStoreError` because the two are read by
  different operators — a store fault sends someone to the database, this
  sends someone to the promotion pipeline — and rather than a bare
  :class:`ForwardError` because a caller whose single ``except`` guards the
  write must be able to tell *the seam refused me* from *the body was
  malformed*.

* :class:`ForwardIdentityError` — the **one-signal law**, and feature 333's
  two disagreements with a standing record.  A signal that already holds a
  forward record was asked to be promoted again with different evidence:
  docs/nullius-tech-architecture.md §13.4 makes the promotion instant the
  boundary between backtest and out-of-sample, so there is exactly one such
  boundary per signal: re-opening the record would move it, and the moved
  record would keep the same ``observed_on`` values while measuring a
  different window — the silent vintage edit this whole table exists to make
  impossible.  The observing write adds the law's two day-scale faces, both
  of them *disagreements with what stands* rather than faults in the ask: an
  observation dated **on or before the boundary day** (the boundary day is
  the opening row's own, and an earlier one measures in-sample data under an
  out-of-sample vintage), and a date that already holds an observation
  carrying a **different coefficient** (the measurement that landed on a day
  is that day's fact, and last-wins would revise it after feature 334's
  curve and feature 337's ratio may have read it).  A retry that states the
  *same* promotion — or the *same* day's *same* coefficient — is not this
  error: it is answered by the standing row, as :class:`~ledger.store.
  TrialLedger.debit` answers a retry by its prior sequence.

* :class:`ForwardReconciliationError` — the fill-cost reconciliation's own
  row contract, feature 340's table's equivalent of the law
  :class:`ForwardRecordError` holds for ``forward_record``.  A reconciliation
  is two measured figures and the difference between them, keyed by the
  rebalance they price, so the ask is refused when a book states nothing, a
  rebalance instant states no time, or a figure is not a finite real —
  including the near-misses a dynamic column would happily store: ``bool``
  where a cost belongs, a NaN that would propagate into feature 338's β₄
  recalibration, an infinity that is not a cost at all.  The read refuses a
  row no reconciliation can be rebuilt as — a moment no parser accepts, a
  sequence the ledger never minted, or a stored difference that disagrees
  with the two sides stored beside it, which is a row lying about its own
  arithmetic — for the reason the record contract refuses too: this is the
  table §16's *realized vs. modeled fill costs in bps* metric and §13.4's
  β₄ recalibration read, and a figure nobody can vouch for is worse than a
  refusal.

Every message names the offending value and the contract it broke, in the
same discipline as the promotion and trial-ledger taxonomies: these errors
are operational signals for a pipeline that runs unattended for months (the
window is 90 days by §5's own figure), so the forward path's failures must
be speakable, not merely loggable.

The member raises nothing else.  A ``sqlite3.IntegrityError`` on the write,
an ``OSError`` on the file, a promotion-side refusal from the seam — every
one of them arrives at a caller as one of these five, because a caller's
``except ForwardError`` guarding a forward record must not be defeated by a
neighbouring member's vocabulary.
"""

from __future__ import annotations

__all__ = [
    "ForwardError",
    "ForwardIdentityError",
    "ForwardPromotionError",
    "ForwardReconciliationError",
    "ForwardRecordError",
    "ForwardStoreError",
]

#: The greppable word that opens every :class:`ForwardStoreError` message:
#: the record was asked for and the *store* could not serve it.  Spelled
#: after the promotion member's own convention
#: (``promotion_registry_unwritable``) and deliberately distinct from every
#: word beside it in this member, because an operator greps one word per
#: fault: ``forward_record_unwritable`` sends them to the database,
#: ``forward_promotion_unstamped`` sends them to the promotion pipeline, and
#: landing on the wrong one wastes the one thing a 90-day loop cannot give
#: back — the day it happened on.
FORWARD_RECORD_ERROR_CODE = "forward_record_unwritable"

#: The greppable word that opens every :class:`ForwardPromotionError` message:
#: the promotion this record is opened against has no instant to open at.
FORWARD_PROMOTION_ERROR_CODE = "forward_promotion_unstamped"

#: The greppable word that opens every :class:`ForwardIdentityError` message:
#: the signal already holds a forward record and the request asked to move it.
FORWARD_IDENTITY_ERROR_CODE = "forward_record_already_open"

#: The greppable word that opens every :class:`ForwardReconciliationError`
#: message: the reconciliation's own terms were not met — a book, an instant
#: or a figure that states nothing measurable, or a stored row no
#: reconciliation can be rebuilt as.  Deliberately not
#: ``forward_record_unwritable``'s vocabulary, because that word sends an
#: operator to the database while this one sends them to the figures the
#: execution path handed over — two repairs for two faults, which is the
#: whole reason the classes split.
FORWARD_RECONCILIATION_ERROR_CODE = "forward_reconciliation_malformed"


class ForwardError(Exception):
    """Base class for every failure of the forward-test path.

    One ``except`` for the whole member, so a pipeline step that opens a
    forward record — and the features 333-340 that read, extend and reconcile
    it afterwards — can guard the act without enumerating four classes whose
    sets will grow as the category lands.  Subclasses are caught by name where
    the *repair* differs, which is the only distinction that earns a class
    here.
    """


class ForwardRecordError(ForwardError):
    """A ``forward_record`` row's identity, instant, date or coefficient is
    malformed.

    Raised at construction, where the cause can still be named, and at the
    read, where a row that cannot be rebuilt into a
    :class:`~forward.record.ForwardRecord` is refused rather than served —
    the coefficient gate (a finite real in ``[−1, 1]``) running on both
    paths, so a hand-edited ``2.5`` served to feature 334's curve is refused
    as loudly as one handed to feature 333's writer.

    **Why the read refuses too.**  SQLite's columns are dynamically typed, so
    a hand-edited or corrupted row is reachable here — and this is the one
    table whose *promoted_at* is the system's boundary between in-sample and
    out-of-sample.  A reader that served a row whose promotion instant was
    unreadable would be handing a report a forward window nobody can place on
    a calendar, and §5's *"after 90 days, that signal has a track record on
    data that did not exist when the hypothesis was formed"* would be a claim
    about a duration nothing can measure.  Refusing is the only honest
    answer, for the reason :class:`~promotion.errors.
    PromotionWindowError` refuses an open registry row rather than defaulting
    its instant: the alternative is a fabricated vintage.
    """


class ForwardStoreError(ForwardError):
    """The forward record's store is misrouted, or its write failed.

    A ``DATABASE_URL`` whose scheme this member does not speak, a sqlite URL
    with a host or without a path, an absent parent row, or a configured
    store whose ``INSERT`` failed.  Feature 333's append adds the state no
    insert can repair past: a signal whose record was never opened (nothing
    to observe onto — the repair is feature 332's ``POST /forward/promote``,
    not a retry) and a record whose rows carry two promotion instants (a
    vintage nobody can state, which appending would only compound).  The
    write-failure case is raised rather than
    swallowed because a record that silently failed to land is exactly the
    state feature 332 exists to prevent: the signal is promoted, the
    evaluation that decided it has been charged, and the row that says *this
    signal went out of sample at this instant* is missing — so the day that
    would have been the first day of the track record passes unrecorded and
    nothing in the system looks wrong.

    A store that is *absent* — no ``DATABASE_URL`` — is not this error.  It
    is a deployment without a relational store, which composes no ``forward``
    component at all: a discoverable state rather than an exception, the same
    stance every store in this workspace takes.  The caller that must open a
    record is the caller that must not find itself in it.
    """


class ForwardPromotionError(ForwardError):
    """The promotion a forward record is opened against has no instant.

    Raised by :meth:`forward.record.Forwards.open_record` — and by the
    module-level spelling beside it — when the ``promotion`` member's own
    window read refuses the node: nobody pre-registered it, its deciding
    evaluation has not run yet, or its registry row could not be read as a
    decision.  All three are feature 300's
    :class:`~promotion.errors.PromotionWindowError`, and all three mean the
    same thing here: **there is no promotion instant**, so the one fact this
    feature's row exists to carry does not exist.

    **Its repair is the promotion pipeline's, and that is why it is its own
    class.**  The member's tree splits by the repair, and this refusal's
    repair is unlike the two beside it:

    * not :class:`ForwardStoreError` — nothing is wrong with the database
      this member writes into, and nothing failed to land.  The record was
      never attempted, because the instant it would carry could not be read.
      An operator sent to the database by this refusal would find a perfectly
      healthy table;
    * not :class:`ForwardRecordError` — the body was well formed.  The node
      is a real identity, the observation date is a real date; what is
      missing is a fact about a *different* member's row, and re-sending the
      same request cannot produce it.

    So the class names the seam, and the message names the repair in feature
    291's and feature 293's own terms: pre-register the criteria before the
    deciding evaluation, then record the decision once it has run.  Nothing
    in this member can be fixed, and nothing in this member should be
    retried, until that has happened.

    The alternative — stamping the row with the clock at hand — is refused by
    name in the store's own message, because it is the one repair that looks
    like it works: `datetime.now()` always answers, the row always lands, and
    every later reader is told the signal went out of sample at whatever
    instant the worker happened to run.  If that worker ran before the
    evaluation finished, the record measures a window that began *inside*
    in-sample data, which is the contamination ``0108``'s forward record
    exists to exclude.
    """


class ForwardIdentityError(ForwardError):
    """A request disagrees with a row an identity already holds.

    Feature 332's one-signal law, feature 333's two day-scale faces of the
    same refusal, and feature 340's per-rebalance face — three spellings of
    one law: an identity holds one row, and a second claim that *disagrees*
    with it is refused rather than resolved.  §13.4 makes the
    *promoted_at* / *observed_on* pair carry a row's vintage, and
    docs/nullius-tech-architecture.md's Loop 3 makes the promotion instant the
    boundary between backtest and out-of-sample: a signal has exactly one
    such boundary, so it has exactly one forward record — and an observation
    dated on or before that boundary, or a second coefficient claiming a day
    that already holds one, disagrees with the record exactly as a second
    promotion instant does.  A rebalance is the same shape one grain over: it
    happened once, its legs filled once, and the reconciliation of its
    realized against its modeled cost is one fact — a second reconciliation
    naming *different* figures for a rebalance that already holds one is two
    claims about one rebalance's costs, and the store refuses to choose
    between them for the same reason it refuses to choose between two
    promotion instants.

    **The naive alternative is the dangerous one.**  A store that appended a
    second row on every ``POST /forward/promote`` would satisfy the feature's
    sentence read literally — a record is created, and it carries the
    promotion instant — while destroying the property the sentence is for: a
    reader asking *when did this signal go out of sample?* would find two
    instants and no way to choose, and a decay curve (feature 334) drawn over
    both would be drawn over two overlapping windows whose observations
    double-count.  §13.4's whole promise is that the boundary is *fixed*.

    **A retry is not this error.**  The same request arriving twice — the
    worker died after the row landed but before the response made it back, and
    the worker that takes over posts again — is answered by the standing row
    with ``created=False``, the semantics
    :meth:`ledger.store.TrialLedger.debit` establishes one member over.  This
    class is raised only when the standing record and the request **disagree**
    about the promotion: a different promotion instant, or an observation date
    the standing row does not already carry.  Two identical requests are one
    promotion; two different ones are two claims about one signal's vintage,
    and the store refuses to choose between them.

    Deliberately not a :class:`ForwardError` subclass only by omission — the
    class *is* one, and it is separate from :class:`ForwardStoreError`
    because nothing failed: the database answered, the row is intact, and the
    caller's repair is to stop asking rather than to fix anything.
    """


class ForwardReconciliationError(ForwardError):
    """A fill-cost reconciliation's figures, key or stored row are malformed.

    Feature 340's row contract, held the way :class:`ForwardRecordError`
    holds ``forward_record``'s: at the write for the ask's own terms, and at
    the read for a row no reconciliation can be rebuilt as.

    **The ask face.**  A reconciliation is *two measured figures and the
    difference between them*, keyed by the rebalance they price, so the ask
    is refused when the book states nothing (non-empty text names the book
    the order path hashed its client order identifiers from), when the
    rebalance's instant is not a timezone-aware datetime (a naive stamp
    cannot say when the rebalance was for, and two books' rebalances would
    file in one order or none), or when either figure is not a finite real.
    ``bool`` is refused first, for the reason every numeric validator in
    this workspace refuses it; a NaN is refused because it would propagate
    into feature 338's β₄ recalibration and into every operator trend line
    drawn over these rows, and an infinity is not a cost at all.  No sign is
    bound, and that absence is deliberate: a realized figure can be negative
    (fills that improved on their benchmark), a modeled one can be (a venue
    that rebates), and the *sign of the difference* — the model understated,
    or overcharged — is the very fact the reconciliation exists to persist.

    **The read face.**  SQLite's columns are dynamically typed, so a
    hand-edited or foreign-written row is reachable here, and the table's
    readers (feature 338's β₄ recalibration, §16's live metric, §15's
    *reconcile the cost model* repair) all run later and elsewhere.  A row
    whose moment no parser accepts, whose sequence the ledger never minted,
    or whose stored difference disagrees with the two sides stored beside it
    — a row lying about its own arithmetic — is refused rather than served,
    naming the row it came from so an operator gets a row to repair instead
    of a complaint about a value with no address.
    """
