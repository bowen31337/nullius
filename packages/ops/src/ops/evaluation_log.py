"""Feature 348's seam: one structured log record per evaluation.

app_spec.xml, "Observability & Dashboards", feature 348
(``depends_on="341"``): *System emits one structured log record per
evaluation carrying the full provenance triple plus node_id and
campaign_id.*  docs/nullius-tech-architecture.md §16 states it as the
first half of the section's structured-logging pair — *"every
evaluation emits one record carrying the full provenance triple plus
``node_id`` and ``campaign_id``.  Every replay emits
``(policy_version, world_id, beta, score, committed_pick)``"* — and
the member's own registration reserved the shape when feature 341
landed (*"348-349's structured log records arrive as emission
seams"*).  This module is the evaluation half of that pair; the replay
half (349) landed as :mod:`ops.replay_log`, and the two ship beside
each other under the same parent logger, one deployment knob for the
pair.

**What the record is, and why one media and not the other.**  The five
fields §16 names are five identity columns of the ledger's own row —
the ``trial_ledger`` row §8 declares, whose provenance terms feature
87 stamps (*"System stamps every trial_ledger row with
evaluator_hash, snapshot_hash and cost_model_hash"*) and whose
identity columns are ``node_id UUID NOT NULL`` and ``campaign_id UUID
NOT NULL`` — so the row and the record are *one fact in two media*:
the row is the queryable charge an operator holds the budget spend
and the deflation count against, and the record is the testimony a
log stream ships per evaluation, at the moment the evaluation was
booked.  Feature 87's sentence says *stamps* and names a store; this
feature's says *emits* and names none — and that split is the design,
not an omission, the same split the replay half of the pair takes
(feature 255's row persists, 349's record emits).  §16's stack line
leaves the sink to the deployment (*"Prometheus + Grafana, or a
single Postgres metrics table with a Streamlit dashboard … At this
scale the simpler option is defensible"*), so what the seam owes is
the one structured record, and what the deployment owes it is a
handler — the same stance feature 253's alert takes for its own
durability (*"what makes the alert durable is the caller's logger or
monitor"*).  A second table here would be a second spelling of the
row the ledger already owns, and a second ``DATABASE_URL`` reader in
this member would be a second thing to keep in sync with a store
contract this module never needed.

**The triple is the evaluation's provenance, and each term names one
axis of it.**  §14.1 ranks the three — *"`evaluator_hash`,
``snapshot_hash`` and ``cost_model_hash`` pin everything except the
thing that wrote the code"* — and each is the sha256 hexdigest its
owning feature computed: feature 70's over the container image
digest plus the resolved configuration (*which frozen evaluator
scored the trial*), §4.2's seal's over the sorted file hashes, the
universe definition and the schema version (*which sealed snapshot
the trial was scored against*), and feature 60's over the loaded
§6.2 cost-model document (*which fee-and-fill regime priced it*).
Together they are what makes a charge reproducible — feature 71
refuses a comparison between two scores whose evaluator hashes
differ, a refusal that can only mean what it says when every record
names its triple — so the record carries all three or is refused:
testimony that omitted a term would be provenance no audit could
replay a charge from.

**Structured means the five fields ride the record as named, typed
values.**  The emission is exactly one stdlib :class:`logging.LogRecord`
per call — :func:`emit_evaluation_log` resolves the member's named
logger (:data:`EVALUATION_LOG_LOGGER_NAME`), emits at
:data:`EVALUATION_LOG_LEVEL`, and passes the five fields as ``extra``,
which the logging infrastructure attaches to the record as attributes:
a deployment pointing a structured formatter (python-json-logger,
vector, any handler that reads ``record.<name>``) at the stream gets
the fields without parsing anything, and a plain-text handler still
gets them, because the record's message is the stable ``key=value``
line :attr:`EvaluationLogRecord.line` derives from the same mapping.
The message is deliberately **not** the serialization, for the same
reason the replay half states: the deployment's formatter is the one
place its JSON policy gets to decide how values are spelled, and a
seam that pre-serialised would have opinions the parser then has to
track.

**The record is identity, not verdict.**  §16's sentence names the
triple and the two ids and no outcome, no score, no charge — and the
omission is the schema: the trial's own row carries the outcome
because a count of outcomes is what the ledger is *for*, while this
record is the per-evaluation testimony a stream counts evaluations
by, and a field here the sentence did not name would be a second
place the stream's schema could grow.  An evaluation that failed is
still an evaluation — §8's outcome vocabulary exists because *"a
failed trial is as chargeable a fact as a successful one"* — and its
record ships the same five fields a successful one's does, because
the identity the record carries exists whatever the verdict was.
What is refused is the *ask* — a carrier that does not state all five
fields, a triple term that is ``None``, a hash that is not the sha256
hexdigest's own spelling, an id that is not a UUID — and every
refusal fires **before anything is emitted** (the ordering law:
feature 87's refusal before the ledger is touched, 349's before the
logger is asked, and this one before the logger is asked), so a
refused ask puts nothing on the stream at all.

**The carrier is the charge the evaluation was booked as, read
duck-typed — a member never imports another member.**  An evaluation
culminates in §6.1 step 11's budget debit, and the append that books
it answers the ledger's own record — a carrier that states all five
fields this seam reads (the triple feature 87 stamps, plus the two
identity columns) and six more facts (``seq``, ``ts``, ``outcome``,
``charges_budget``, ``charge_units``, ``epoch_id``) this seam does
not.  The seam
reads what such a record *is* — the five attributes the sentence
names — and ignores everything else the carrier carries, because the
record's schema is the sentence's, not the row's.  No ``isinstance``
anywhere: the module loader imports a member under a synthetic name
and re-executes it, so the answer a *composed* application's charge
path produced can be a second class object of the same name, and an
``isinstance`` would refuse the very charge the deployment booked.
The reader refuses a carrier that does not state a field — naming
what arrived — and refuses a triple term of ``None``: ``None`` is the
*read's* spelling for a ledger row that predates feature 87's stamp,
a statement about the ledger's history rather than provenance an
evaluation ran under, and the ledger's own write seams refuse the
same absence for the same reason (*a charge that cannot name its
triple is a charge no replay can reproduce*).

**The spellings are canonical, because the record must join the row
it mirrors.**  A log stream is counted and joined — the record's
triple grouped against the ledger's, its ids against the tree's — so
a record that shipped its own casing would drift from its own row at
the join: the three hash terms are folded to the lowercase 64-hex
spelling §8's ``CHAR(64)`` columns hold (either case accepted and
normalised away, surrounding whitespace stripped, a ``sha256:``
-prefixed digest refused as an *image reference* rather than the
hash computed over it — the one shape the ledger's own stamp holds
all three columns to), and the two ids to the canonical hyphenated
lowercase UUID spelling §8's ``UUID`` columns store, accepting a
:class:`uuid.UUID` or any text :func:`uuid.UUID` parses.  The record's
own construction holds a record built by hand (a test, a later
adapter over the charge path) to the same law the emission path
already passed: a frozen value that validated nothing would lend the
seam's guarantees to testimony nobody stood behind.

**No clock of this module's own.**  §16's sentence names five fields
and no instant, and the one timestamp the emission carries is the
:class:`logging.LogRecord`'s own ``created`` — the logging
infrastructure's clock, read where the record is made.  The module
reads no ``datetime`` and no ``time``: a record stamped by the
infrastructure that emitted it is labelled by the same hand that
sequenced it, and a second timestamp of the member's own would be a
second clock the stream's order could disagree with — while the
charge's own ``ts`` stays what it is, the ledger's fact, read where
the ledger wrote it.

**No component, no store — the sentence demands no state a deployment
holds.**  The member's registration-grows-per-feature law (*"each
composes only if its sentence demands state a deployment holds"*)
lands this one as a pure emission seam: no ``@register`` builder, no
``DATABASE_URL``, no schema — nothing here can spend I/O inside
``create_app()``, and the member's three composed components (the
route, the dashboard, the live-metrics store) are untouched.  The
caller that books evaluations reaches this seam by importing the
member — the same reach the replay half describes for its own caller
— and the logger's name is the deployment's routing handle: one
handler on ``"ops"`` captures every record this member emits, the
evaluation records this seam ships and the replay records its sibling
ships beside them, and the parent's level is the one knob that says
whether the system's structured log ships.

Stdlib only — :mod:`dataclasses` for the record, :mod:`logging` for
the one emission, :mod:`uuid` for the ids' canonical spelling,
:mod:`typing` for the seam — the member's import stays cheap on every
factory scan, and nothing here can grow a dependency the charge path
would pay for.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from .errors import EvaluationLogError

__all__ = [
    "EVALUATION_LOG_LEVEL",
    "EVALUATION_LOG_LOGGER_NAME",
    "EvaluationLogRecord",
    "emit_evaluation_log",
]

#: Sentinel distinguishing *the carrier carried no attribute at all*
#: from *the carrier carried the attribute with value* ``None`` — the
#: same distinction feature 249's own ``_ABSENT`` draws for the same
#: reason: the two facts have different repairs (fix the carrier,
#: versus carry the pre-stamp absence to the refusal that names it),
#: and a seam that answered one for the other would log broken wiring
#: as an honest charge.
_ABSENT = object()

#: The logger this seam emits on — a literal, not ``__name__``, because
#: the module loader imports a member under a synthetic name and
#: re-executes it, so the name a re-executed copy would read is not the
#: name the deployment needs to configure.  Dotted under ``"ops"`` so
#: the member's records nest under one parent: a deployment's single
#: handler on ``"ops"`` captures these records beside the replay
#: records :mod:`ops.replay_log` ships, and the parent's level is the
#: one knob that says whether the system's structured log ships.
EVALUATION_LOG_LOGGER_NAME = "ops.evaluation_log"

#: The level the record is emitted at — INFO, the level of routine
#: testimony, and the level the replay half of the pair already ships
#: at.  The volume argument is the ledger's own grain: one row per
#: evaluation is the system's unit of accounting, so the record's
#: volume is the charge volume by construction — WARNING would page an
#: operator once per trial for records the sentence says the system
#: *emits*, while DEBUG would default them off in every deployment
#: that had not opted in, and a record the feature exists to emit must
#: survive a default logger config.  INFO is the opt-in level, and one
#: level for the pair is what makes the parent's single knob a single
#: knob: evaluation records and replay records ship or sink together.
EVALUATION_LOG_LEVEL = logging.INFO

#: The one shape all three of §8's provenance columns hold: the
#: ``CHAR(64)`` the DDL declares, which is the sha256 hexdigest's own
#: 64-character hex spelling.  Spelled once here so the validator and
#: the tests cannot drift apart on how long a provenance hash is.
_HASH_LENGTH = 64

#: The hexdigest's alphabet, lowercase — the case every accepted
#: spelling is folded to before it is compared against this set.
_HEX = frozenset("0123456789abcdef")


@dataclass(frozen=True, slots=True)
class EvaluationLogRecord:
    """The structured record one evaluation emits — §16's five fields.

    Frozen, because testimony that could move would be an identity
    that changed after the evaluation was booked: the row this record
    mirrors is append-only (*"No UPDATE, no DELETE"*, §8's own comment
    on the table), and this is the record half of that pair — the row
    is the ledger's, the triple is feature 87's stamp, and this value
    holds the same five facts in the order §16's sentence spells them:
    the full provenance triple, then the two ids the sentence adds.

    Construction holds the record to what a log stream can honestly
    carry, and every refusal is
    :class:`~ops.errors.EvaluationLogError`:

    * **evaluator_hash**, **snapshot_hash**, **cost_model_hash** —
      each the sha256 hexdigest its owning feature computed (feature
      70's, §4.2's seal's, feature 60's), as 64 hexadecimal
      characters, folded to the lowercase spelling §8's ``CHAR(64)``
      columns hold.  Either case is accepted and normalised away — a
      hash pasted from a database, a log line or a report is commonly
      uppercase, means the same value, and is folded rather than
      refused, the same treatment the ledger's own stamp gives the
      columns this record mirrors.  A ``sha256:``-prefixed digest is
      refused on its own ground: that spelling belongs to an *image
      reference*, and accepting it here would let a stream-side join
      compare a digest against a hash and get "different" for the
      wrong reason.  A short hash, a truncated value or a non-hex
      token is refused — it names no evaluator, snapshot or cost
      model this system recorded.
    * **node_id**, **campaign_id** — §8's ``UUID`` columns, in the
      canonical hyphenated lowercase spelling the row joins against
      the tree store.  A :class:`uuid.UUID` or any text
      :func:`uuid.UUID` parses (hyphenated or not, any case) is
      accepted and canonicalised; anything else is refused, because
      an id that is not a UUID names no evaluation the ledger could
      join, and testimony that re-spelled its own identity would be
      an identity nothing answers.

    The five fields are the whole record.  No outcome (the row
    carries one, because a count of outcomes is what the ledger is
    for; a log record is *counted* by its identity, and §16's sentence
    is the count's schema), no score, no charge, no epoch — a field
    here that §16 did not name would be a second place the stream's
    schema could grow opinions the deployment's parser then has to
    track.
    """

    #: The frozen evaluator that scored the trial — feature 70's
    #: sha256 over the container image digest plus the resolved
    #: configuration, the ``evaluator_hash`` of §8's triple.
    evaluator_hash: str

    #: The sealed snapshot the trial was scored against — §4.2's
    #: seal's sha256 over the sorted file hashes, the universe
    #: definition and the schema version.
    snapshot_hash: str

    #: The fee-and-fill regime that priced the trial — feature 60's
    #: sha256 over the loaded §6.2 cost-model document.
    cost_model_hash: str

    #: The evaluated node, canonical UUID spelling (§8: ``node_id
    #: UUID NOT NULL``).
    node_id: str

    #: The campaign the node belongs to, canonical UUID spelling
    #: (§8: ``campaign_id UUID NOT NULL``).
    campaign_id: str

    def __post_init__(self) -> None:
        # The ask, validated and canonicalised field by field — every
        # refusal fires here, at construction, which is *before* the
        # emitter asks the logger for anything: a refused ask puts no
        # record on the stream at all, the ordering law this member's
        # other seams hold toward the things they write.  frozen+slots
        # forbids plain assignment, so the canonicalisation writes
        # through object.__setattr__ exactly once, at construction;
        # after this the instance is sealed.
        object.__setattr__(
            self,
            "evaluator_hash",
            _canonical_hash(self.evaluator_hash, "evaluator_hash"),
        )
        object.__setattr__(
            self,
            "snapshot_hash",
            _canonical_hash(self.snapshot_hash, "snapshot_hash"),
        )
        object.__setattr__(
            self,
            "cost_model_hash",
            _canonical_hash(self.cost_model_hash, "cost_model_hash"),
        )
        object.__setattr__(self, "node_id", _canonical_uuid(self.node_id, "node_id"))
        object.__setattr__(
            self, "campaign_id", _canonical_uuid(self.campaign_id, "campaign_id")
        )

    @property
    def fields(self) -> dict[str, Any]:
        """The five fields as a mapping — the record's one schema.

        §16's sentence spelled as a mapping, in the sentence's own
        order (the triple in §8's declaration order, then the two ids
        the sentence adds), so the emission (``extra``), the derived
        :attr:`line` and any formatter or test reading the record all
        share **one** spelling of the five names — a second list of
        them anywhere in this module would be a second thing to keep
        in sync with the sentence.  A fresh ``dict`` per call,
        deliberately not a frozen proxy: the deployment's serializer
        owns this mapping's next step, and a proxy is a type
        ``json.dumps`` refuses.  Treat it as read-only testimony; the
        record it came from does not move.
        """
        return {
            "evaluator_hash": self.evaluator_hash,
            "snapshot_hash": self.snapshot_hash,
            "cost_model_hash": self.cost_model_hash,
            "node_id": self.node_id,
            "campaign_id": self.campaign_id,
        }

    @property
    def line(self) -> str:
        """The record's message — every field, once, in §16's order.

        ``"evaluation evaluator_hash=… snapshot_hash=…
        cost_model_hash=… node_id=… campaign_id=…"``, derived from
        :attr:`fields` so the line and the mapping cannot disagree,
        and spelled from the canonical values the record holds, so the
        line a raw stream greps names the evaluation in the same
        spelling the row it mirrors stores.  This is the line a
        plain-text handler prints; it is not the serialization, and
        the structured consumers read :attr:`fields` off the emitted
        record instead.
        """
        return "evaluation " + " ".join(
            f"{name}={value}" for name, value in self.fields.items()
        )


def emit_evaluation_log(trial: Any) -> EvaluationLogRecord:
    """Emit one structured log record for one evaluation; return the
    record.

    Feature 348's sentence as one call: read the charge the evaluation
    was booked as (the record §6.1 step 11's debit answers — a carrier
    stating the provenance triple feature 87 stamps plus the ``node_id``
    and ``campaign_id`` §8 declares), and emit exactly one stdlib log
    record on :data:`EVALUATION_LOG_LOGGER_NAME` at
    :data:`EVALUATION_LOG_LEVEL`, carrying the frozen evaluator that
    scored the trial, the sealed snapshot it was scored against, the
    cost model that priced it, the node that was evaluated and the
    campaign it belongs to — §16's five fields, the full triple plus
    the two ids, as ``extra`` on the record and as the derived
    ``key=value`` line in its message.

    **One call, one record.**  The call is the seam's whole
    transaction: the ask is validated first (the carrier reads, then
    the record's own construction), and only a record that passed
    reaches the logger — one :class:`logging.LogRecord` per call, so a
    caller invoking this once per evaluation emits one structured
    record per evaluation, and a refused ask emits nothing at all.

    Args:
        trial: The charge the evaluation was booked as — the record
            the ledger's own append answers, or any carrier stating
            the same five facts.  Read duck-typed (a member never
            imports another member, and the loader's synthetic-name
            wrinkle means an ``isinstance`` would refuse the very
            charge a composed application produced): a carrier that
            does not state one of the five fields is refused as naming
            no evaluation the ledger could join, a triple term of
            ``None`` is refused as the pre-stamp read's spelling
            rather than provenance an evaluation ran under, and
            everything else the carrier carries is ignored, because
            the record's schema is the sentence's, not the row's.

    Returns:
        The :class:`EvaluationLogRecord` emitted — frozen testimony
        the caller can hold beside the row it booked (the ledger's
        append answers the record for the same reason: name what you
        just made, so it never has to be re-read to be known).

    Raises:
        EvaluationLogError: The ask, refused — a carrier that does
            not state all five fields, a triple term that is ``None``
            or not the sha256 hexdigest's own 64-hex spelling, an id
            that is not a UUID.  Every refusal fires before the logger
            is asked, so a refused ask puts nothing on the stream.
    """
    # The ask first, the stream second: the carrier is read and the
    # record constructed (which validates and canonicalises every
    # field it holds) before the logger is asked for anything — the
    # ordering this member's other seams hold toward the things they
    # write, held here toward the one stream this seam owns.
    record = EvaluationLogRecord(
        evaluator_hash=_term_of(trial, "evaluator_hash"),
        snapshot_hash=_term_of(trial, "snapshot_hash"),
        cost_model_hash=_term_of(trial, "cost_model_hash"),
        node_id=_term_of(trial, "node_id"),
        campaign_id=_term_of(trial, "campaign_id"),
    )
    logging.getLogger(EVALUATION_LOG_LOGGER_NAME).log(
        EVALUATION_LOG_LEVEL, record.line, extra=record.fields
    )
    return record


# -- the carrier, read duck-typed ---------------------------------------------------------


def _term_of(trial: Any, name: str) -> Any:
    """One of the five fields, read off the charge as the carrier
    states it.

    The read is the whole of the seam's knowledge of the carrier: an
    attribute lookup, absent-able, through the one name the sentence
    spells.  A carrier that does not state the field is refused,
    naming what arrived — it names no evaluation the ledger could
    join, and testimony of one would be structured record nobody
    booked.  The value is passed through as read, never re-spelled:
    whether it is the shape the record can carry is the record's own
    law, stated where the record's other fields are held to theirs.
    """
    value = getattr(trial, name, _ABSENT)
    if value is _ABSENT:
        raise EvaluationLogError(
            f"an evaluation's log record is emitted from the charge the "
            f"evaluation was booked as — got {trial!r} "
            f"({type(trial).__name__}), which has no `{name}`. The record "
            "carries §16's five fields (the provenance triple plus "
            "node_id and campaign_id), and a carrier that does not "
            f"state `{name}` names no evaluation the ledger could join; "
            "hand the record the evaluation's debit answered (feature "
            "348, docs §16)"
        )
    return value


# -- the record's own law ------------------------------------------------------------------


def _canonical_hash(value: Any, column: str) -> str:
    """One term of the provenance triple, in canonical lowercase hex.

    The one shape the ledger's own stamp holds all three columns to,
    restated here because a member never imports another member: the
    sha256 hexdigest's own 64-character spelling, folded to the
    lowercase §8's ``CHAR(64)`` columns hold so the record joins the
    row it mirrors at a stream-side join.  Surrounding whitespace is
    stripped and either case is folded — the pasted-from-a-report
    courtesy the ledger and the evaluator member both extend — while
    a ``sha256:``-prefixed digest is refused on its own ground (that
    spelling is an *image reference*, not the hash computed over it),
    ``None`` is refused as the pre-stamp read's spelling rather than
    provenance an evaluation ran under, and a short hash, a truncated
    value, a non-hex token or a non-string is refused because it
    names no evaluator, snapshot or cost model this system recorded.
    """
    if value is None:
        raise EvaluationLogError(
            f"an evaluation log record's {column} is required — got None. "
            "None is the read's spelling for a ledger row that predates "
            "feature 87's stamp, a statement about the ledger's history "
            "rather than provenance an evaluation ran under: the "
            "evaluator that scored the trial, the snapshot it was "
            "scored against and the cost model that priced it are three "
            "facts about the evaluation that nothing else on the record "
            "states, and testimony that omitted one would be a charge "
            "no replay can reproduce (feature 348, docs §16)"
        )
    if isinstance(value, str):
        text = value.strip()
        if ":" in text:
            raise EvaluationLogError(
                f"an evaluation log record's {column} {value!r} carries "
                "an algorithm prefix; a sha256:<hex> digest is an "
                "*image reference*, not the hash computed over it — "
                "pass the 64 hex characters themselves. A record "
                "stamped with a reference would name no evaluator, "
                "snapshot or cost model this system recorded, and the "
                "stream would drift from the row it mirrors at the "
                "join (feature 348, docs §16)"
            )
        if len(text) == _HASH_LENGTH and set(text.lower()) <= _HEX:
            return text.lower()
    raise EvaluationLogError(
        f"an evaluation log record's {column} is "
        f"{_HASH_LENGTH} hexadecimal characters — the sha256 digest of "
        f"one term of the evaluation's provenance (feature 87's stamp: "
        "§8's evaluator_hash, snapshot_hash and cost_model_hash "
        f"CHAR(64) columns), got {value!r} ({type(value).__name__}). A "
        "short hash, a truncated value or a non-hex token names no "
        "evaluator, snapshot or cost model this system recorded, and a "
        "record stamped with it would be provenance no audit can "
        "replay (feature 348, docs §16)"
    )


def _canonical_uuid(value: Any, field: str) -> str:
    """One of the two identity columns, in canonical UUID spelling.

    §8 declares ``node_id UUID NOT NULL`` and ``campaign_id UUID
    NOT NULL``, and the row stores the canonical hyphenated lowercase
    spelling so it joins against the tree store; the record mirrors
    the row, so it holds the same spelling for the same reason — a
    testimony that named the evaluation in another casing would drift
    from its own row at the join.  A :class:`uuid.UUID` or any text
    :func:`uuid.UUID` parses (hyphenated or not, any case) is
    accepted and canonicalised; anything else is a caller bug at the
    emission, and coercing it would bless it.
    """
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, str):
        try:
            return str(uuid.UUID(value))
        except (ValueError, AttributeError, TypeError) as exc:
            raise EvaluationLogError(
                f"an evaluation log record's {field} is a UUID — §8's "
                f"column is `{field} UUID`, and the canonical "
                "hyphenated lowercase spelling is what joins the row "
                "this record mirrors against the tree store; got "
                f"{value!r}: {exc}. An id that is not a UUID names no "
                "evaluation the ledger could join, and testimony that "
                "re-spelled its own identity would be an identity "
                "nothing answers (feature 348, docs §16)"
            ) from exc
    raise EvaluationLogError(
        f"an evaluation log record's {field} is a UUID or its text "
        "spelling — §8's column is "
        f"`{field} UUID`, and the record mirrors the row that joins "
        "against the tree store; got "
        f"{value!r} ({type(value).__name__}). An id that is not a "
        "UUID names no evaluation the ledger could join (feature 348, "
        "docs §16)"
    )
