"""Feature 291's endpoint: POST /promotion/pre-register, the pre-registration.

app_spec.xml, "Promotion & Epoch Governance", feature 291: *System exposes
POST /promotion/pre-register, which returns a criteria hash recorded before
the deciding evaluation runs.*  The spec's API summary spells the route's one
line — ``POST /promotion/pre-register — Hash and record criteria before the
deciding evaluation`` — and the schema block gives the row it writes::

    promotion_registry
      id UUID PRIMARY KEY DEFAULT gen_random_uuid()
      node_id UUID NOT NULL REFERENCES node(id)
      epoch_id TEXT NOT NULL REFERENCES epoch_ledger(epoch_id)
      criteria_hash CHAR(64) NOT NULL
      pre_registered_at TIMESTAMPTZ NOT NULL
      decided_at TIMESTAMPTZ

docs/alpha-engine-prd.md §13 states the law the route exists to serve, as
item 7 among the invariants that *"violating any of these silently
invalidates the system"*: *"Promotion criteria are pre-registered and hashed
before the evaluation that decides them."*  §M4 states the deployment it was
written for — *"Pre-register success criteria in a hashed file **before** the
shadow run starts"* — and feature 360 is the CI invariant that polices the
ordering.  This module is where the ordering is *created*, which is why it is
a route and not a helper: §13 says enforce in CI rather than in code review,
and a CI invariant can only check an ordering some component actually
performs.

**The two timestamps are the whole feature, and they are written in two
statements by two features.**  ``pre_registered_at`` is written here, by the
call this endpoint serves; ``decided_at`` is written by the promotion
decision (feature 293) when the evaluation that decides the promotion has
run.  The ordering §13 item 7 demands is therefore not a convention this
module follows but a property of the *schema*: the row is inserted while the
decision is still open, so ``decided_at`` is NULL at the moment the criteria
hash is recorded, and no later write can move the hash to a time after the
decision — the hash row already exists at an instant the decision has not yet
stamped.  That is what ``0108``'s own comment says the nullable column is
for: *"``decided_at`` is nullable because the row is written while the
decision is still open, which is the only ordering under which
pre-registration means anything."*

**The insert cannot name ``decided_at``, and that is deliberate.**  See
:data:`_INSERT_SQL`: the statement's column list is four columns, the
nullable one is absent, and the column therefore takes its ``NULL`` from the
schema rather than from a value this module passed.  A version of this
statement that wrote ``decided_at = NULL`` explicitly would be a statement
that *chose* a NULL, and a later feature editing that clause could choose
otherwise; the absent column is a statement that has no opinion to edit.  The
two-timestamp law is thus enforced by the shape of the writer, not by a check
the writer remembers to make.

**Pre-registration is once per node, and the reason is the feature's own
premise.**  A node's criteria are fixed the first time they are recorded.
Re-registering the same node with the *same* criteria is a retry — the
response was lost, the worker died, the caller posted again — and it returns
the standing row untouched, ``pre_registered_at`` included, for the reason
the coverage ledger's re-issued persist returns its standing row: the
criteria did not change, so the instant they were fixed did not either, and
re-stamping would claim a freshness the retry does not have.  Re-registering
the same node with *different* criteria is refused, and the refusal is the
feature: a criteria hash that can be rewritten after the fact records nothing
about what was expected, and §13 item 7's word *before* would be satisfied by
a timestamp while its meaning was not.  A deployment that genuinely wants to
judge one hypothesis against a second criteria set has a second hypothesis to
register, which is the honest spelling of a second question.

**That refusal is this feature's, and it is not feature 292's.**  Feature
292 — *"rejects a promotion whose recorded criteria hash differs from the
pre-registered value, which returns a criteria_mismatch error message"* —
judges a *promotion* against a *hash*, at decision time, over rows this store
has already written.  This module judges a *registration request* against the
*row it would rewrite*, before the evaluation, and its whole subject is the
write.  The two differ in when they run and in what they are about, so 292's
``criteria_mismatch`` remains its own to coin; nothing here spells that word.

**The refusal's class is the ask face's own refinement.**  The refusal was
raised as :class:`~promotion.errors.PromotionError` from the day this module
landed, and it still is caught as one — raised now as
:class:`~promotion.errors.PromotionConflictError`, a *subclass* of the ask
face rather than a sibling beside it, so every caller whose
``except PromotionError`` guards the pre-registration path keeps catching
exactly what it caught.  What the subclass adds is the one thing a caller
that must *answer a status* could not get from the message before: the ask
here is well formed — six terms, a real node, a real epoch — and the
conflict is with a row, not with the body, so a caller can tell this
refusal from a malformed request by class alone.  The message names both
criteria hashes — the standing row's and the ask's — and opens with
:data:`~promotion.errors.PROMOTION_CONFLICT_ERROR_CODE`, spelled clear of
feature 292's word in letter as in moment.

**The node and the epoch must exist, and the schema is why.**  ``node_id``
and ``epoch_id`` are foreign keys, and ``0108`` writes them as such — the
node is the hypothesis being registered and the epoch is the sequestered
holdout the eventual decision will spend (prd §13 item 4: *"Sequestered
epochs are retired permanently after 3 promotion decisions"*), so a
registration that named a node the tree does not hold, or an epoch nobody
sealed, would be a row no decision could ever complete.  The store checks
both by name *before* the insert rather than letting the database's
``IntegrityError`` surface, because the repair differs by parent and an
operator reading *"FOREIGN KEY constraint failed"* cannot tell which of the
two rows is missing.  The ordering the bootstrap runs in is the same law at
the schema level, and it is the *chain's* order rather than SQLite's demand:
SQLite does not resolve a foreign key's *parent table* until a row is written,
so it would accept ``promotion_registry`` declared before the two tables its
keys point at and then refuse the first ``INSERT`` with ``no such table:
main.node`` — a deployment that cannot pre-register anything.  ``0108``'s own
words for that are the ones to keep: *"That is a tolerance, not a licence: the
dependency is real and is stated twice."*  See :mod:`promotion.schema`, which
runs the three tables' own migrations in that order.

**This is the route's contract as a Python seam, not an HTTP server.**  The
workspace's operations surface is its composed components — every "exposes"
feature in the spec landed as one, and :class:`~ledger.debit.DebitEndpoint`
is the precedent this endpoint follows line for line:
:class:`PreRegisterEndpoint.post` takes a :class:`PreRegistrationRequest`
(the body) and returns a :class:`PreRegistrationResponse`, with
:data:`PRE_REGISTER_ROUTE` spelling the route once so the endpoint, the
spec's API summary and whatever HTTP adapter lands later cannot drift apart
on the name.  The endpoint delegates every storage decision to
:meth:`PreRegistrations.pre_register`, which holds the check-and-insert
inside one transaction on one connection: the transaction is the store's to
keep, the request/response shape is the endpoint's to say, and neither
reaches into the other's half.

**The request carries a document, not six loose keywords, and that is about
the hash.**  The body's criteria arrive as the six-term mapping
:meth:`~promotion.criteria.PromotionCriteria.document` renders, and
:func:`_criteria_from_document` refuses one that is missing a term or
carrying a term that is not one of the six.  Both refusals are load-bearing
against the same failure: the hash is taken over *every* criterion, so a body
with a misspelled key — ``min_world`` for ``min_worlds`` — that this module
quietly ignored would pre-register five terms and hash them, and the sixth
would then be free to be anything at decision time.  A document is a closed
set here for the same reason the criteria are frozen: the hash can only
vouch for what it covers.

**An absent store composes no endpoint.**  :meth:`PreRegisterEndpoint.
from_env` returns ``None`` when no ``DATABASE_URL`` is set, the same
degrade-don't-break stance the member's own builder takes — while the caller
that must pre-register a promotion before evaluating it is, again, the one
that must not find itself in that state.

Stdlib only, and import-cheap: ``sqlite3``, ``datetime``, ``urllib.parse``,
and this member's own two modules.
"""

from __future__ import annotations

import datetime as dt
import os
import sqlite3
import uuid
from collections.abc import Callable, Mapping
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .criteria import CRITERIA_FIELDS, PromotionCriteria, criteria_hash
from .errors import (
    PROMOTION_CONFLICT_ERROR_CODE,
    PROMOTION_REGISTRY_ERROR_CODE,
    PromotionConflictError,
    PromotionError,
    PromotionStoreError,
)
from .schema import PROMOTION_REGISTRY_TABLE, bootstrap_schema

__all__ = [
    "DATABASE_URL_ENV",
    "PRE_REGISTER_ROUTE",
    "PreRegisterEndpoint",
    "PreRegistrationRequest",
    "PreRegistrationResponse",
    "PreRegistrations",
    "PromotionRecord",
    "utc_now",
]

#: The environment variable naming the relational store — the one spelling
#: every store in this workspace already uses (the trial ledger's, the
#: campaign planner's, the coverage ledger's), restated here so this store
#: states its own contract and imports nobody else's.
DATABASE_URL_ENV = "DATABASE_URL"

#: The route this endpoint serves — app_spec.xml's API summary row for the
#: Promotion domain, spelled once: ``POST /promotion/pre-register — Hash and
#: record criteria before the deciding evaluation``.  Carried on the class
#: (:attr:`PreRegisterEndpoint.route`) so a composed deployment can state its
#: routes from the components it holds rather than from a string that lives
#: somewhere else.
PRE_REGISTER_ROUTE = "/promotion/pre-register"

#: The node this registration is about — prd §13 item 7's hypothesis, and the
#: key the row is read back by.
NODE_ID_COLUMN = "node_id"

#: The sequestered epoch the eventual decision will spend — prd §13 item 4's
#: depleting resource, named by the registration so the decision that
#: completes this row has a holdout to charge.
EPOCH_ID_COLUMN = "epoch_id"

#: The hash of the criteria as they were written — :func:`promotion.criteria.
#: criteria_hash`'s 64 lowercase hex characters, the spelling ``0108``
#: declares ``CHAR(64) NOT NULL``.
CRITERIA_HASH_COLUMN = "criteria_hash"

#: When the criteria were fixed — the first of the two timestamps an auditor
#: compares, written by *this* feature and never moved afterwards.
PRE_REGISTERED_AT_COLUMN = "pre_registered_at"

#: When the promotion was decided — the second timestamp, written by feature
#: 293's decision and ``NULL`` for the whole of the row's life up to that
#: point.  Named here for the read-back and for the row's rendering; the
#: insert deliberately does not name it (see :data:`_INSERT_SQL`).
DECIDED_AT_COLUMN = "decided_at"

#: The insert, whose column list is the whole of the two-timestamp law: four
#: columns, and ``decided_at`` is not one of them.  The nullable column takes
#: its ``NULL`` from the schema, so this statement has no clause a later
#: feature could edit into a decision — a pre-registration row is born open,
#: and only feature 293's decision closes it.  The ``id`` is likewise absent:
#: ``0108`` declares a ``DEFAULT`` that mints a UUID on both dialects, and a
#: writer-supplied identity would be a second minter of a value the table
#: already mints.
_INSERT_SQL = (
    f"INSERT INTO {PROMOTION_REGISTRY_TABLE} "
    f"({NODE_ID_COLUMN}, {EPOCH_ID_COLUMN}, {CRITERIA_HASH_COLUMN}, "
    f"{PRE_REGISTERED_AT_COLUMN}) VALUES (?, ?, ?, ?)"
)

#: The read-back, column by column rather than ``SELECT *``: the order
#: :func:`_record_from_row` unpacks must be the order this names, so a future
#: migration that appends a column cannot silently shift the fields.
_READ_SQL = (
    f"SELECT id, {NODE_ID_COLUMN}, {EPOCH_ID_COLUMN}, {CRITERIA_HASH_COLUMN}, "
    f"{PRE_REGISTERED_AT_COLUMN}, {DECIDED_AT_COLUMN} "
    f"FROM {PROMOTION_REGISTRY_TABLE} WHERE {NODE_ID_COLUMN} = ?"
)

#: The two parent probes.  Both name the table they read rather than trusting
#: a foreign key to complain, because the repair differs by parent and the
#: database's own message names neither.
_NODE_EXISTS_SQL = 'SELECT 1 FROM "node" WHERE id = ? LIMIT 1'
_EPOCH_EXISTS_SQL = (
    'SELECT 1 FROM "epoch_ledger" WHERE epoch_id = ? LIMIT 1'
)


# -- Validation -------------------------------------------------------------------


def utc_now() -> dt.datetime:
    """The current instant, timezone-aware UTC — the default pre-registration clock.

    Second resolution, microseconds dropped rather than rounded, the same
    stamp the trial ledger's own clock mints and for the same reason: the
    stamp orders one pre-registration against another and nothing reads
    finer than a second out of it, while a sub-second component would make
    two registrations that are "the same instant" for every practical
    purpose compare as different.  Dropping — not rounding — keeps the stamp
    never *after* the instant observed, which matters more here than there:
    §13 item 7's law is an inequality between two instants, and a clock that
    rounded forward could stamp a pre-registration into the future of a
    decision that had already run.
    """
    return dt.datetime.now(dt.UTC).replace(microsecond=0)


def _validated_uuid(value: Any, field_name: str) -> str:
    """Validate an identity column, returning its canonical UUID spelling.

    Accepts a :class:`~uuid.UUID` or any text :func:`uuid.UUID` parses
    (hyphenated or not, any case), and returns the one spelling the table
    stores: hyphenated lowercase.  The same discipline the trial ledger's
    record layer applies to ``node_id``, restated here because no member
    imports another — and because a registration that cannot be joined to
    its node is a registration no decision can complete.
    """
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, str):
        try:
            return str(uuid.UUID(value))
        except (ValueError, AttributeError) as exc:
            raise PromotionError(
                f"{field_name} must be a UUID — got {value!r}: {exc}. The "
                f"registration names the hypothesis being pre-registered, and "
                f"{PROMOTION_REGISTRY_TABLE}.{NODE_ID_COLUMN} is a foreign key "
                "to the node table: an identity that is not a UUID names no "
                "row any decision could complete (feature 291)"
            ) from exc
    raise PromotionError(
        f"{field_name} must be a UUID — got {value!r} "
        f"({type(value).__name__}); the registration names the hypothesis "
        "being pre-registered, and a registration no node can be joined to "
        "is a registration no decision can complete (feature 291)"
    )


def _validated_epoch_id(value: Any) -> str:
    """Validate the sequestered epoch's name, returning it as the table spells it.

    Non-empty text, stripped — the near-miss a trailing newline would
    otherwise persist as a second name for one epoch, against a foreign key
    whose parent is keyed by the name itself.  ``None`` and blank are both
    refused: the epoch is a depleting resource (prd §13 item 4) and the row
    being written is the *booking* of that resource for this promotion, so a
    registration that cannot name its epoch books nothing.
    """
    if not isinstance(value, str) or not value.strip():
        raise PromotionError(
            f"{EPOCH_ID_COLUMN} must be non-empty text — got {value!r} "
            f"({type(value).__name__}); the registration books the "
            "sequestered epoch the deciding evaluation will spend, and "
            f"{PROMOTION_REGISTRY_TABLE}.{EPOCH_ID_COLUMN} is a foreign key to "
            "the sealing ledger — an epoch nobody named is an epoch no "
            "decision can charge (feature 291)"
        )
    return value.strip()


def _validated_instant(value: Any, field_name: str) -> dt.datetime:
    """Validate a stamp, returning it aware-UTC.

    Accepts a timezone-aware :class:`~datetime.datetime` (any offset — an
    aware instant in another offset names the same instant, so it is
    normalised rather than rejected) or its ISO-8601 text, the form the
    table stores, so a row read back revalidates through this same check.  A
    naive datetime is refused: §13 item 7 compares this stamp against the
    decision's, and a naive/aware comparison raises :class:`TypeError` far
    from the write that omitted the offset.
    """
    instant: dt.datetime
    if isinstance(value, dt.datetime):
        instant = value
    elif isinstance(value, str):
        try:
            instant = dt.datetime.fromisoformat(value)
        except ValueError as exc:
            raise PromotionError(
                f"{field_name} must be an ISO-8601 datetime or a datetime — "
                f"got {value!r}: {exc}. The pre-registration's instant is "
                "compared against the decision's, and text that does not "
                "parse is not an instant that comparison can range "
                "(feature 291)"
            ) from exc
    else:
        raise PromotionError(
            f"{field_name} must be a timezone-aware datetime — got "
            f"{value!r} ({type(value).__name__}); §13 item 7's law is an "
            "ordering between two instants, and a pre-registration stamped "
            "with something that is not one cannot be ordered against "
            "anything (feature 291)"
        )
    if instant.tzinfo is None or instant.tzinfo.utcoffset(instant) is None:
        raise PromotionError(
            f"{field_name} must be timezone-aware — got the naive datetime "
            f"{instant.isoformat()!r}. §13 item 7 orders the pre-registration "
            "against the deciding evaluation, and a naive stamp has no "
            "offset to compare with — pass an aware UTC instant (see "
            "utc_now()) (feature 291)"
        )
    return instant.astimezone(dt.UTC)


def _criteria_from_document(document: Any) -> PromotionCriteria:
    """Build the criteria from the body's six-term document, or refuse it.

    The document is the mapping :meth:`PromotionCriteria.document` renders —
    :data:`~promotion.criteria.CRITERIA_FIELDS`' six keys to their values —
    and this function is the *inverse* of that method, so a document a
    criteria rendered is a criteria a document rebuilds and the two spellings
    hash identically.  A carrier with a callable ``document()`` is unwrapped
    through it first, so a Python caller holding the value passes the value.

    **The set is closed in both directions, and each direction is its own
    failure.**  A document *missing* a term would register five criteria and
    hash them, leaving the sixth free to be anything at decision time: the
    hash would vouch for a criteria set that is not the one the deployment
    thought it fixed.  A document carrying a term that is *not* one of the
    six would have that term silently dropped by the same argument, and the
    caller would be told the registration succeeded.  Both are refused by
    name, with the offending key or the missing list in the message, because
    a body's typo is a one-character repair and the message should make it
    that.

    A non-mapping is refused in the same class and for the same reason: the
    criteria arrive as a document because the document is what the hash is
    taken over, and there is no honest reading of an arbitrary object as six
    named terms.
    """
    supplied_document = getattr(document, "document", None)
    if callable(supplied_document):
        document = supplied_document()
    if not isinstance(document, Mapping):
        raise PromotionError(
            "a promotion's pre-registered criteria arrive as the six-term "
            f"document of {len(CRITERIA_FIELDS)} named terms — got "
            f"{document!r} ({type(document).__name__}). The criteria hash is "
            "taken over every term, so a body that is not a document of them "
            "cannot be hashed (feature 291)"
        )
    missing = [field for field in CRITERIA_FIELDS if field not in document]
    if missing:
        raise PromotionError(
            "a promotion's pre-registered criteria must state every one of "
            f"the {len(CRITERIA_FIELDS)} terms; this body is missing "
            f"{', '.join(repr(field) for field in missing)}. A criterion "
            "recorded without a term is a criterion whose hash does not cover "
            "it, which would leave that term free to be anything at decision "
            f"time — state all of {', '.join(CRITERIA_FIELDS)} (feature 291)"
        )
    unknown = sorted(str(key) for key in document if key not in CRITERIA_FIELDS)
    if unknown:
        raise PromotionError(
            "a promotion's pre-registered criteria are exactly "
            f"{', '.join(CRITERIA_FIELDS)}; this body also carries "
            f"{', '.join(repr(key) for key in unknown)}. A term the hash does "
            "not cover is a term nobody registered, and accepting it would "
            "report a successful registration of criteria that were never "
            "fixed (feature 291)"
        )
    return PromotionCriteria(
        theta=document["theta"],
        alpha=document["alpha"],
        max_fdr_deploy=document["max_fdr_deploy"],
        min_worlds=document["min_worlds"],
        min_coverage_strata=document["min_coverage_strata"],
        min_forward_days=document["min_forward_days"],
    )


def _validated_criteria_hash(value: Any) -> str:
    """Validate a stored ``criteria_hash``, returning it as the column spells it.

    A 64-character lowercase-hex string — the spelling :func:`promotion.
    criteria.criteria_hash` produces and ``0108`` declares ``CHAR(64)``.
    ``CHAR`` in SQLite is an affinity, not a width, so a raw ``INSERT`` from
    another tool can land anything in the column; a read that returned it
    unexamined would hand feature 292 a value to compare against that no
    hash could ever equal, and the comparison would refuse a promotion for a
    corruption it never mentions.  Refused here instead, naming the node the
    row was about.
    """
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise PromotionStoreError(
            f"{PROMOTION_REGISTRY_ERROR_CODE}: {CRITERIA_HASH_COLUMN} must be "
            f"64 lowercase hex characters — got {value!r}. The column is the "
            "sha256 digest of the criteria as they were written, and a stored "
            "value that is not one is a row this member could not have written "
            "(feature 291)"
        )
    return value


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into the filesystem path it names.

    The same convention every store in this workspace restates — the
    SQLAlchemy spelling ``DATABASE_URL`` already uses, with this member's own
    refusal vocabulary, because a caller's ``except PromotionStoreError``
    must not be defeated by a translation error raised in another member's
    words.  A non-SQLite scheme and a pathless URL are refused by name; an
    in-memory database is refused because the whole point of the row is that
    it outlives the call that wrote it — the deciding evaluation runs in
    another process entirely, and feature 360's invariant reads the row after
    both have finished.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise PromotionStoreError(
            f"{PROMOTION_REGISTRY_ERROR_CODE}: unsupported "
            f"{DATABASE_URL_ENV} scheme {parsed.scheme!r}. This store speaks "
            "sqlite:/// (the spec's single-machine allowance); the Postgres "
            "registry arrives with the versioned migration tree, and "
            "pretending to speak it here would hide a misrouted URL behind a "
            "mysterious file (feature 291)"
        )
    if parsed.netloc not in ("", "localhost"):
        raise PromotionStoreError(
            f"{PROMOTION_REGISTRY_ERROR_CODE}: sqlite {DATABASE_URL_ENV} must "
            f"not carry a host, got {parsed.netloc!r} (feature 291)"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path or path == ":memory:":
        raise PromotionStoreError(
            f"{PROMOTION_REGISTRY_ERROR_CODE}: sqlite {DATABASE_URL_ENV} "
            "carries no database path. An in-memory registry would die with "
            "the connection that opened it, and a pre-registration must "
            "outlive the call that recorded it — the deciding evaluation runs "
            "in another process, and §13 item 7's ordering is checked after "
            "both have finished (feature 291)"
        )
    return Path(path)


# -- The record -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PromotionRecord:
    """One ``promotion_registry`` row, as the table holds it.

    The six fields are the table's six columns.  Frozen, so a row that has
    been read back cannot be edited into different criteria by a caller who
    kept a reference — the discipline every record in this workspace states,
    and the one that matters most here: this value is the record of what was
    expected of a promotion, and a mutable one would let a caller retype the
    criteria in memory while the hash on the row said otherwise.

    Validated in :meth:`__post_init__` rather than only through the store,
    because ``dataclasses.replace`` and unpickling both rebuild instances
    past a factory's nose — and because the *read* path needs the same check
    the write path does: SQLite's columns are dynamically typed, so a corrupt
    row is reachable here, and a registry read that swallowed one would
    report criteria nobody registered.
    """

    #: The row's own identity, as the table minted it (``0108``'s ``DEFAULT``).
    id: str
    #: The hypothesis being pre-registered.
    node_id: str
    #: The sequestered epoch the eventual decision will spend.
    epoch_id: str
    #: The sha256 digest of the criteria as they were written.
    criteria_hash: str
    #: When the criteria were fixed — §13 item 7's first instant.
    pre_registered_at: Any
    #: When the promotion was decided — the second instant, ``None`` while
    #: the decision is open, which is every row this feature writes.
    decided_at: Any = None

    def __post_init__(self) -> None:
        # frozen+slots forbids plain assignment, so canonicalisation writes
        # through object.__setattr__ exactly once, at construction — the same
        # discipline the criteria value and the trial ledger's record follow.
        object.__setattr__(self, "id", _validated_uuid(self.id, "id"))
        object.__setattr__(
            self, "node_id", _validated_uuid(self.node_id, NODE_ID_COLUMN)
        )
        object.__setattr__(
            self, "epoch_id", _validated_epoch_id(self.epoch_id)
        )
        object.__setattr__(
            self,
            "criteria_hash",
            _validated_criteria_hash(self.criteria_hash),
        )
        object.__setattr__(
            self,
            "pre_registered_at",
            _validated_instant(self.pre_registered_at, PRE_REGISTERED_AT_COLUMN),
        )
        if self.decided_at is not None:
            object.__setattr__(
                self,
                "decided_at",
                _validated_instant(self.decided_at, DECIDED_AT_COLUMN),
            )

    @property
    def open(self) -> bool:
        """Whether the decision this row precedes is still open.

        ``True`` for every row this feature writes — the insert cannot name
        ``decided_at`` — and it is a *fact about the row* rather than a
        judgement over it: closing the row is feature 293's decision, and
        whether the promotion then stands or is refused is feature 292's
        question.  The property exists so the state has a readable name at
        the seam, the role ``CoverageCount.empty`` plays for the named-empty
        stratum.
        """
        return self.decided_at is None

    def row(self) -> dict[str, Any]:
        """The record as a store-shaped mapping — a fresh dict per call.

        The column names are the table's own, the discipline every record in
        this workspace follows: a rendered mapping names the same things the
        same way the row does.
        """
        return {
            "id": self.id,
            NODE_ID_COLUMN: self.node_id,
            EPOCH_ID_COLUMN: self.epoch_id,
            CRITERIA_HASH_COLUMN: self.criteria_hash,
            PRE_REGISTERED_AT_COLUMN: self.pre_registered_at,
            DECIDED_AT_COLUMN: self.decided_at,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"{type(self).__name__}(node_id={self.node_id!r}, "
            f"epoch_id={self.epoch_id!r}, "
            f"criteria_hash={self.criteria_hash!r}, "
            f"pre_registered_at={self.pre_registered_at!r}, "
            f"decided_at={self.decided_at!r})"
        )


# -- The request and the response -------------------------------------------------


@dataclass(frozen=True, slots=True)
class PreRegistrationRequest:
    """The body of one POST /promotion/pre-register: the criteria to fix.

    Three things and one optional stamp.  The ``node_id`` is the hypothesis
    the criteria are about — and, because §13 item 7 makes the criteria
    immutable once fixed, the row's effective key (see
    :meth:`PreRegistrations.pre_register`).  The ``epoch_id`` is the
    sequestered holdout the eventual decision will spend.  The ``criteria``
    is the six-term document :meth:`PromotionCriteria.document` renders (or
    the criteria value itself, unwrapped through its own ``document()``), and
    :func:`_criteria_from_document` holds it to the closed set of six — a
    body missing a term or carrying one that is not a term is refused before
    the store is touched, because the hash covers every term and can only
    vouch for what it covers.

    ``pre_registered_at`` defaults to :func:`utc_now`, and is a field rather
    than a hidden call so that a replay, a backfill or a test can state the
    instant the criteria were fixed — the same role ``ts`` plays on
    :class:`~ledger.debit.DebitRequest`.  It is *not* a knob for convenience:
    nothing in this module reads it back to check the ordering, and the
    ordering is created by the insert's shape rather than by this value (see
    the module docstring).

    Construction canonicalises the identities to UUID text and the epoch name
    to stripped text, refuses anything that is not one, and refuses a naive
    stamp — so two requests stating the same registration compare equal
    however the caller came by the identities.  Frozen, because a request is
    a fact the caller stated; editing one in flight would be posting a
    different set of criteria than was validated, which is the one thing a
    pre-registration must not permit.
    """

    #: The hypothesis being pre-registered — canonical UUID spelling.
    node_id: str
    #: The sequestered epoch the deciding evaluation will spend, in the
    #: sealing process's own spelling.
    epoch_id: str
    #: The criteria as the six-term document (or the criteria value itself).
    criteria: Any
    #: When the criteria were fixed, aware-UTC; ``None`` stamps at the
    #: endpoint's default clock.
    pre_registered_at: dt.datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "node_id", _validated_uuid(self.node_id, NODE_ID_COLUMN)
        )
        object.__setattr__(
            self, "epoch_id", _validated_epoch_id(self.epoch_id)
        )
        # The document is rebuilt into the member's own criteria value here,
        # at the wire, so a malformed body is refused before the store is
        # touched and the endpoint holds a value whose hash is already
        # decidable.  A carrier with its own document() is unwrapped inside
        # the helper, which is what lets a Python caller pass the value.
        object.__setattr__(
            self, "criteria", _criteria_from_document(self.criteria)
        )
        if self.pre_registered_at is not None:
            object.__setattr__(
                self,
                "pre_registered_at",
                _validated_instant(
                    self.pre_registered_at, PRE_REGISTERED_AT_COLUMN
                ),
            )

    @property
    def criteria_hash(self) -> str:
        """The hash this body asks to be recorded — §13 item 7's digest.

        A property rather than a field, so the hash cannot drift from the
        criteria it is a hash of: it is computed from the value the
        constructor canonicalised, every time it is asked for.  This is the
        figure the feature's own sentence says the route returns.
        """
        return criteria_hash(self.criteria)


@dataclass(frozen=True, slots=True)
class PreRegistrationResponse:
    """The answer to one POST /promotion/pre-register: the hash, and its row.

    ``created`` is whether *this* call appended the row; a retry is a call
    where it is ``False`` — the node already held a pre-registration with
    these criteria, and this POST changed nothing.  ``record`` is the node's
    row in full: freshly written on the first POST, the standing one on every
    retry.  ``criteria_hash`` (a property, so it cannot drift from the
    record) is the figure the feature's own sentence promises — *"returns a
    criteria hash recorded before the deciding evaluation runs"* — and
    ``open`` is the ordering stated as a fact about the row.

    Frozen, because the response is the endpoint's testimony about the
    registry's state at one moment; two responses that differ in
    ``criteria_hash`` for one request would be the endpoint revising its
    testimony, which is what pre-registration exists to make impossible.
    """

    #: Whether this call wrote the row — ``False`` on a retry.
    created: bool
    #: The node's row: freshly written, or the standing row a retry is
    #: answered by.
    record: PromotionRecord

    @property
    def criteria_hash(self) -> str:
        """The recorded hash of the criteria as they were written."""
        return self.record.criteria_hash

    @property
    def pre_registered_at(self) -> dt.datetime:
        """When the criteria were fixed — §13 item 7's first instant."""
        return self.record.pre_registered_at

    @property
    def decided_at(self) -> Any:
        """When the promotion was decided — ``None``, for a fresh row."""
        return self.record.decided_at

    @property
    def open(self) -> bool:
        """Whether the deciding evaluation has yet to close this row."""
        return self.record.open

    @property
    def retry(self) -> bool:
        """Whether this POST was a retry — answered by a row already held.

        The readable spelling of ``not created``, named for the clause it
        asserts, exactly as :attr:`~ledger.debit.DebitResponse.retry` is.
        """
        return not self.created


# -- The store --------------------------------------------------------------------


class PreRegistrations:
    """The store that records pre-registrations: one row per node, written open.

    Constructed with the database URL the registry lives in;
    :meth:`pre_register` records one node's criteria and answers with the row
    the table holds.  The class resolves its path lazily, so constructing one
    performs no I/O: composition-time work must not touch the disk, the
    contract every store in this workspace states.

    The store holds no cache of the rows it wrote: the row is the only record
    of what was pre-registered, so it is the only thing an answer is drawn
    from — and the stance is stronger here than elsewhere, because
    §13 item 7's whole promise is that the criteria cannot change after the
    fact.  A memo of recorded hashes living in one process would make *what
    were these criteria registered as?* a question about that process's
    history; the deciding evaluation, and the CI invariant that polices the
    ordering, both run somewhere else.
    """

    def __init__(self, database_url: str) -> None:
        """Wire the store to the database the registry lives in.

        The URL is validated here, before any call, because it is a fact
        about the *store* rather than about any one registration: a URL that
        is not a non-empty string names no registry, and a store that
        accepted one would fail identically on every pre-registration — the
        wrong place for a deployment to discover a wiring fault.
        """
        if not isinstance(database_url, str) or not database_url.strip():
            raise PromotionStoreError(
                f"{PROMOTION_REGISTRY_ERROR_CODE}: {DATABASE_URL_ENV} must be "
                "a non-empty database URL. The registry is a table in the "
                "database the deployment names, and a store pointed at "
                "nothing has nowhere to record criteria (feature 291)"
            )
        self._database_url = database_url.strip()
        # Resolved on first use rather than at construction: building the
        # store is composition-time work and must not touch the disk.
        self._path: Path | None = None

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(cls, env: Mapping[str, str] | None = None) -> PreRegistrations | None:
        """The registry ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset, the same way every
        store in this workspace treats its configuration.  Absent is not an
        error: it is a deployment without a relational store, which composes
        no promotion component — a discoverable state, not an exception —
        while the caller that must pre-register criteria before evaluating
        them is the caller that must not find itself in it.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The database URL this store records into."""
        return self._database_url

    @property
    def path(self) -> Path:
        """The SQLite file behind the registry, resolved on first use.

        Nothing is created at construction — the URL is translated (and a URL
        this member cannot speak is refused by name) the first time an
        operation needs it.
        """
        if self._path is None:
            self._path = _sqlite_path(self._database_url)
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """Open the registry's database and bring it to the revision the row needs.

        Two statements of intent, in the order that matters.

        **The schema.** :func:`promotion.schema.bootstrap_schema` runs the
        *migrations'* own ``statements("sqlite")`` for the three tables this
        write needs — ``node`` (0118), ``epoch_ledger`` (0110) and
        ``promotion_registry`` (0108) — so this store authors no DDL, spells
        no column and cannot drift from the schema's owner.  All three are
        ``CREATE TABLE IF NOT EXISTS``, so a fresh database, a fully migrated
        one and one this store created earlier all take the same path and
        running the migrations over a database this store created changes
        nothing.  The order is the chain's, not SQLite's demand — SQLite
        defers a foreign key's parent *table* to the first row written, so a
        registry-only database is declared happily and then refuses every
        ``INSERT`` with ``no such table: main.node``; the dependency is real
        even where the engine is tolerant.

        **The foreign keys.** ``PRAGMA foreign_keys = ON`` — SQLite's own
        default is off, so a store that skipped this would insert a
        registration naming a node that does not exist and discover it never.
        The parent *rows* are checked by name before the insert regardless
        (see :meth:`pre_register`), because the repair differs by parent; the
        pragma is what makes the check a redundancy rather than the only
        guard, and it is what makes the constraint hold against a hand that
        reaches past this store with a raw connection.

        The caller owns the connection; use it as a context manager to
        commit, which is what the write here does.
        """
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            with connection:
                bootstrap_schema(connection)
        except PromotionError:
            connection.close()
            raise
        except sqlite3.Error as exc:
            connection.close()
            raise PromotionStoreError(
                f"{PROMOTION_REGISTRY_ERROR_CODE}: the database at {path} "
                f"could not be brought to the revision "
                f"{PROMOTION_REGISTRY_TABLE} needs: {exc}. The table is "
                "created by migrations/versions/0108_forward_and_universe_"
                "tables.py and the two tables its foreign keys point at by "
                "0118 and 0110; this store runs those files' own statements "
                "and authors none of its own (feature 291)"
            ) from exc
        return connection

    # -- Feature 291: the pre-registration ----------------------------------

    def pre_register(
        self,
        node_id: Any,
        epoch_id: Any,
        criteria: Any,
        *,
        pre_registered_at: dt.datetime | None = None,
        clock: Callable[[], dt.datetime] | None = None,
    ) -> tuple[PromotionRecord, bool]:
        """Record one node's criteria before the deciding evaluation — feature 291.

        The steps, in the order they must happen:

        1. **Validate the ask** — the node and the epoch as identities, the
           criteria as the six-term document — before anything is opened, so
           a malformed pre-registration is refused without touching a
           database, so a refused body leaves no row and no file behind.
        2. **Read the node's row.**  §13 item 7 makes the criteria immutable
           once fixed, so the node's standing row is the whole of what the
           store knows about this registration — and it is the row that
           decides between the three outcomes below.
        3. **Answer the retry, or refuse the rewrite, or write.**  A standing
           row whose hash is *this* hash is the same registration arriving
           twice: the standing row is returned untouched, ``pre_registered_at``
           included, because the criteria did not change and so the instant
           they were fixed did not either.  A standing row whose hash differs
           is refused — see below.  An absent row takes the insert.
        4. **Read back and answer with the row**, inside the same transaction
           as the write, so the hash, the minted ``id`` and the stamps in the
           answer are the table's own.

        **The refusal of a differing re-registration is the feature.**  The
        caller asked to fix one set of criteria for a node that already holds
        a different set, and granting it would make the recorded hash a
        record of the last thing anyone said rather than of what was expected
        before the evaluation ran.  §13 item 7's word *before* would still be
        satisfied by both timestamps while its meaning was destroyed.  The
        repair is not to fix the body and not to fix the store — there is
        nothing wrong with either — it is to stop asking, and to register the
        second criteria set against the second hypothesis it is really about.

        **The parents are checked by name, not left to the foreign key.**  A
        node the tree does not hold and an epoch nobody sealed are two
        different missing rows with two different repairs, and SQLite's
        ``IntegrityError`` says neither.  Both are refused before the insert,
        naming the column and the value, and the ``IntegrityError`` is
        translated anyway as a backstop for the case the pragma caught
        something the probes did not.

        Refuses, in this order, each naming what it is about: a malformed
        identity, a malformed epoch or a malformed body
        (:class:`~promotion.errors.PromotionError`, the ask face); a
        re-registration with different criteria
        (:class:`~promotion.errors.PromotionConflictError`, the ask face's
        own subclass — feature 292's ``criteria_mismatch`` is a *different*
        refusal at a different moment, the message names both criteria
        hashes so the conflict is decidable, and a caller's standing
        ``except PromotionError`` catches this one exactly as before); and
        a ``DATABASE_URL`` this member
        cannot speak, an absent parent row, or a row that could not be read
        back or is corrupt (:class:`~promotion.errors.PromotionStoreError`,
        all three opening :data:`~promotion.errors.
        PROMOTION_REGISTRY_ERROR_CODE`).

        ``pre_registered_at`` states the instant the criteria were fixed, and
        ``clock`` supplies the default when it is absent — tests and replays
        route their own time through it, the same seam
        :meth:`~ledger.debit.DebitEndpoint.post` offers.
        """
        node = _validated_uuid(node_id, NODE_ID_COLUMN)
        epoch = _validated_epoch_id(epoch_id)
        fixed = _criteria_from_document(criteria)
        digest = criteria_hash(fixed)
        stamped = (
            _validated_instant(pre_registered_at, PRE_REGISTERED_AT_COLUMN)
            if pre_registered_at is not None
            else (clock or utc_now)()
        )
        with closing(self._connect()) as connection, connection:
            standing = self._node_records(connection, node)
            if standing:
                return self._answer_standing(standing[0], node, digest), False
            self._require_parent(connection, _NODE_EXISTS_SQL, node, NODE_ID_COLUMN, "node")
            self._require_parent(
                connection, _EPOCH_EXISTS_SQL, epoch, EPOCH_ID_COLUMN, "epoch_ledger"
            )
            try:
                connection.execute(
                    _INSERT_SQL, (node, epoch, digest, stamped.isoformat())
                )
            except sqlite3.IntegrityError as exc:
                raise PromotionStoreError(
                    f"{PROMOTION_REGISTRY_ERROR_CODE}: the pre-registration of "
                    f"node {node} could not be written: {exc}. The row names a "
                    "node and a sequestered epoch by foreign key, and this "
                    "store checked both before writing — so a constraint that "
                    "refused anyway is a database whose tables are not the "
                    "ones this deployment migrated (feature 291)"
                ) from exc
            written = self._node_records(connection, node)
        if not written:
            raise PromotionStoreError(
                f"{PROMOTION_REGISTRY_ERROR_CODE}: the pre-registration of "
                f"node {node} could not be read back after the write. A "
                "criteria hash must be accounted for — §13 item 7 makes the "
                "recorded row the thing the deciding evaluation is checked "
                "against — and a row that cannot be re-read is a registration "
                "this store cannot vouch for (feature 291)"
            )
        return written[0], True

    # -- The words ----------------------------------------------------------

    def _node_records(
        self, connection: sqlite3.Connection, node: str
    ) -> list[PromotionRecord]:
        """Every registry row this node holds, as records — at most one, by law.

        More than one is refused rather than resolved, and the argument is
        the one :func:`ledger.epochusage.derive_epoch_usage` makes about a
        repeated epoch: §13 item 7 makes a node's criteria the criteria they
        were fixed as, so a node holding two rows holds two answers to *what
        were these criteria registered as?* and feature 292's comparison
        against *the* pre-registered value would become a choice between
        them.  Both silent resolutions are wrong: summing invents criteria
        nobody registered, and last-wins would let a later row overwrite the
        hash the promotion is actually checked against — which is precisely
        the post-hoc edit the whole feature exists to make impossible.
        Nothing this store writes can produce the state, so a second row is a
        hand that reached past it, and the message says so.
        """
        cursor = connection.execute(_READ_SQL, (node,))
        try:
            rows = cursor.fetchall()
        finally:
            cursor.close()
        if len(rows) > 1:
            raise PromotionStoreError(
                f"{PROMOTION_REGISTRY_ERROR_CODE}: node {node} holds "
                f"{len(rows)} {PROMOTION_REGISTRY_TABLE} rows. §13 item 7 "
                "fixes a node's criteria once, so the table must hold one row "
                "per node — this store writes exactly one and updates none — "
                "and a node holding two would make feature 292's comparison "
                "against the pre-registered value a choice between hashes "
                "nobody decided (feature 291)"
            )
        return [_record_from_row(row, node) for row in rows]

    def _answer_standing(
        self, standing: PromotionRecord, node: str, digest: str
    ) -> PromotionRecord:
        """Resolve a node that already holds a row: the retry, or the refusal.

        The two outcomes are the same row read two ways and the difference is
        the hash.  Equal hashes are one registration arriving twice, which is
        not an error and must not move ``pre_registered_at``.  Different
        hashes are an attempt to revise criteria that §13 item 7 already
        fixed, which the store refuses in
        :class:`~promotion.errors.PromotionConflictError` — the ask face's
        own subclass, so a caller's standing ``except PromotionError`` keeps
        catching the refusal while a caller that must answer a status tells
        it from a malformed ask by class alone.  The message names both
        hashes, because two digests are what make the conflict decidable
        rather than merely loud: the one the row holds is the bar the
        promotion will be judged under, the one the request states is the
        ask that was refused.
        """
        if standing.criteria_hash == digest:
            return standing
        raise PromotionConflictError(
            f"{PROMOTION_CONFLICT_ERROR_CODE}: node {node} was "
            f"pre-registered with criteria {standing.criteria_hash} at "
            f"{standing.pre_registered_at!r} and this request states "
            f"{digest}. §13 item 7 fixes a promotion's criteria before the "
            "evaluation that decides them, so a second registration of the "
            "same node would replace the record of what was expected with "
            "the record of what was asked for afterwards — and the hash "
            "would no longer be evidence of anything. Register the second "
            "criteria set against the hypothesis it is really about, in "
            "its own node (feature 291)"
        )

    def _require_parent(
        self,
        connection: sqlite3.Connection,
        statement: str,
        value: str,
        column: str,
        parent_table: str,
    ) -> None:
        """Refuse a registration whose parent row is absent, naming which.

        ``node`` and ``epoch_ledger`` are the row's two foreign keys, and the
        repairs differ: a missing node is a hypothesis the tree does not hold
        — the caller has the wrong identity, or the discovery loop has not
        written the node yet — while a missing epoch is a holdout nobody
        sealed, which is a deployment that has not sequestered the resource
        the decision will spend.  SQLite's own ``IntegrityError`` names
        neither, so the probe names both the column and the value, and the
        refusal is the store's class rather than the ask's: the body is
        well-formed, and the database is not in the state the write needs.
        """
        cursor = connection.execute(statement, (value,))
        try:
            present = cursor.fetchone() is not None
        finally:
            cursor.close()
        if not present:
            raise PromotionStoreError(
                f"{PROMOTION_REGISTRY_ERROR_CODE}: {parent_table} holds no row "
                f"for {column} {value!r}, so this pre-registration has no "
                f"parent to reference. {PROMOTION_REGISTRY_TABLE}.{column} is "
                "a foreign key: the criterion row must be joinable to what it "
                "is about, and a registration naming a row the database does "
                "not hold is a registration no deciding evaluation could "
                "complete (feature 291)"
            )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"{type(self).__name__}(database_url={self._database_url!r})"


def _record_from_row(row: tuple[Any, ...], node: str) -> PromotionRecord:
    """Build a :class:`PromotionRecord` from a row, with the node named.

    The read path's one constructor, so every read-back in the store builds
    the value the same way.  A validation refusal raised from the row names
    the node it came off — the difference between an operator learning *this
    registration is corrupt* and learning only that some row somewhere is not
    a registration.  A store refusal (the hash column, the address) is
    re-raised in the same class with the node in front of it, for the same
    reason.
    """
    try:
        return PromotionRecord(
            id=row[0],
            node_id=row[1],
            epoch_id=row[2],
            criteria_hash=row[3],
            pre_registered_at=row[4],
            decided_at=row[5],
        )
    except PromotionError as exc:
        raise type(exc)(
            f"the {PROMOTION_REGISTRY_TABLE} row for node {node} could not be "
            f"read as a pre-registration: {exc}"
        ) from exc


# -- The endpoint -----------------------------------------------------------------


class PreRegisterEndpoint:
    """Serves POST /promotion/pre-register over one :class:`PreRegistrations`.

    Constructed with the store it writes into; :meth:`post` is the route.
    The endpoint holds no state of its own — no memo of registered nodes, no
    cache of hashes — because a pre-registration remembered in the endpoint
    would be one a second process, a restart or a recycled worker silently
    loses sight of, and the deciding evaluation runs in another process
    entirely.  The row in the table is the only record of what was
    pre-registered, so it is the only thing the answer is drawn from, on
    every request, in every process.
    """

    #: The route this endpoint serves — :data:`PRE_REGISTER_ROUTE`, pinned as
    #: a class attribute so ``PreRegisterEndpoint.route`` states the contract
    #: without an instance.
    route = PRE_REGISTER_ROUTE

    def __init__(self, registry: PreRegistrations) -> None:
        # Duck-checked rather than isinstance-guarded: the factory's scan
        # imports this member under an alias module, so the *composed* store
        # is structurally a PreRegistrations but never the same class object a
        # direct import yields — an isinstance here would refuse the very
        # component the factory hands out.  The contract is the pre_register
        # seam, and that is what is checked.
        if not callable(getattr(registry, "pre_register", None)):
            raise TypeError(
                "PreRegisterEndpoint speaks a PreRegistrations (something with "
                "a pre_register(node_id, epoch_id, criteria) seam); got "
                f"{type(registry).__name__}"
            )
        self._registry = registry

    # -- Construction -------------------------------------------------------

    @classmethod
    def from_env(
        cls, env: Mapping[str, str] | None = None
    ) -> PreRegisterEndpoint | None:
        """The endpoint over the registry ``DATABASE_URL`` names, or ``None``.

        Resolves the store exactly as the member's own builder does
        (:meth:`PreRegistrations.resolve`), so the endpoint and the composed
        ``promotion`` component always point at the same database.  No
        ``DATABASE_URL`` composes no endpoint — an unconfigured store is a
        discoverable state, not an error — while the caller whose pipeline
        must pre-register criteria before evaluating them is, again, the one
        that must not find itself in it.
        """
        registry = PreRegistrations.resolve(env)
        return None if registry is None else cls(registry)

    @property
    def registry(self) -> PreRegistrations:
        """The store this endpoint records into."""
        return self._registry

    # -- The route ----------------------------------------------------------

    def post(
        self,
        request: PreRegistrationRequest,
        *,
        clock: Callable[[], dt.datetime] | None = None,
    ) -> PreRegistrationResponse:
        """Answer one POST /promotion/pre-register: fix the criteria, or return the prior row.

        The whole of feature 291 at its seam.  The request's criteria are
        hashed — 64 lowercase hex characters over the canonical document — and
        the hash is recorded against the node in ``promotion_registry`` with
        ``pre_registered_at`` set and ``decided_at`` left NULL, which is the
        ordering §13 item 7 demands: the criteria exist as a row at an instant
        the deciding evaluation has not yet stamped.  The response carries that
        hash and the row it was recorded in, so the caller holds the figure the
        decision will later be checked against.

        A node that already holds a pre-registration with *these* criteria is
        a retry: nothing is written, and the response carries the standing row
        and ``created=False``, so the caller sees the ``pre_registered_at``
        the criteria were actually fixed at rather than the instant its retry
        happened to fire.  A node that holds a *different* hash is refused as
        :class:`~promotion.errors.PromotionConflictError`, naming both hashes
        — see :meth:`PreRegistrations.pre_register`, where the argument is.

        ``clock`` overrides the default stamp the store would use when the
        request carries no ``pre_registered_at`` (tests and replays route
        their own time through it).

        Refusals are the request's own (a malformed body — a missing or
        unknown criterion, an absent epoch — never reaches the store), the
        registry's (a store that cannot be reached or brought to the revision
        the row needs), and the store's own on state (an absent parent row, a
        re-registration with different criteria —
        :class:`~promotion.errors.PromotionConflictError`, which a caller
        can tell from the malformed-ask refusals by class alone).
        """
        record, created = self._registry.pre_register(
            request.node_id,
            request.epoch_id,
            request.criteria,
            pre_registered_at=request.pre_registered_at,
            clock=clock,
        )
        return PreRegistrationResponse(created=created, record=record)
