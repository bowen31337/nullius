"""Feature 349's seam: one structured log record per replay.

app_spec.xml, "Observability & Dashboards", feature 349
(``depends_on="341"``): *System emits one structured log record per
replay carrying policy version, world id, beta, score and committed
pick.*  docs/nullius-tech-architecture.md §16 states it as the second
half of the section's structured-logging pair — *"every evaluation
emits one record carrying the full provenance triple plus ``node_id``
and ``campaign_id``.  Every replay emits ``(policy_version, world_id,
beta, score, committed_pick)``"* — so the feature is an **emission**,
and the member's own registration reserved the shape when feature 341
landed (*"348-349's structured log records arrive as emission
seams"*).  This module is the replay half of that pair; the evaluation
half (348) is this seam's sibling-to-come under the same member.

**What the record is, and why one media and not the other.**  The five
fields §16 names are the five columns of the replay member's own row
— feature 255's ``replay_score``, whose docstring quotes this same
sentence for the persistence half, and whose carrier (feature 249's
:class:`~replay.TerminalPick`) is the carrier this seam reads — so the
row and the record are *one fact in two media*: the row is the
queryable history an operator holds the miss rate and the
per-``(policy, world)`` verdict against, and the record is the
testimony a log stream ships per replay, at the moment the replay
finished.  Feature 255's sentence says *persists* and names a store;
this feature's says *emits* and names none — and that split is the
design, not an omission.  §16's stack line leaves the sink to the
deployment (*"Prometheus + Grafana, or a single Postgres metrics table
with a Streamlit dashboard … At this scale the simpler option is
defensible"*), so what the seam owes is the one structured record, and
what the deployment owes it is a handler — the same stance feature
253's alert takes for its own durability (*"what makes the alert
durable is the caller's logger or monitor"*).  A second table here
would be a second spelling of the row feature 255 already owns, and a
second ``DATABASE_URL`` reader in this member would be a second thing
to keep in sync with a store contract this module never needed.

**Structured means the five fields ride the record as named, typed
values.**  The emission is exactly one stdlib :class:`logging.LogRecord`
per call — :func:`emit_replay_log` resolves the member's named logger
(:data:`REPLAY_LOG_LOGGER_NAME`), emits at :data:`REPLAY_LOG_LEVEL`,
and passes the five fields as ``extra``, which the logging
infrastructure attaches to the record as attributes: a deployment
pointing a structured formatter (python-json-logger, vector, any
handler that reads ``record.<name>``) at the stream gets the fields
without parsing anything, and a plain-text handler still gets them,
because the record's message is the stable ``key=value`` line
:attr:`ReplayLogRecord.line` derives from the same mapping.  The
message is deliberately **not** the serialization: the miss's score is
``-inf``, and the two spellings a JSON encoder would offer it are both
lossy in different ways (``-Infinity`` is the Python encoder's
non-standard extension, and a string ``"-inf"`` makes the field's type
depend on its value), so the seam carries the five values typed and
leaves their serialization to the deployment's formatter — the one
place the deployment's JSON policy gets to decide how the floor is
spelled.

**The record is testimony, not a verdict — the miss is emitted, never
refused.**  The parent law is feature 249's, and feature 255 states it
for the row this record mirrors: a policy that emitted no pick is
*scored* ``-inf`` — the total order's floor — and the miss is a score
the comparison keeps.  A log seam that refused the miss would be worse
than the store one, because the log stream is where a dreaming cycle's
miss *rate* is counted in the first place (200 worlds × 40 policy
revisions is §10.4's own arithmetic — the records that never appear
are exactly the replays the rate is about).  So the miss constructs
and emits like any other record: ``score`` carries ``-inf``,
``committed_pick`` carries ``None``, and the derived flag
:attr:`ReplayLogRecord.committed` answers ``False`` — the flag and the
pick readable separately, the split feature 249's own record states
for the dreaming loop that logs per run.  A NaN is refused, for the
reason 255 refuses one at the write: it compares false against
everything and would read as "no scoring".  What is refused is the
*ask* — an id that names nothing, a beta no reader could reproduce
the scoring under, a carrier that is not the terminal answer — and
every refusal fires **before anything is emitted** (the ordering law:
245's refusal before the tree is read, 255's before the store is
touched, and this one before the logger is asked), so a refused ask
puts nothing on the stream at all.

**The carrier is feature 249's :class:`~replay.TerminalPick`, read
duck-typed — a member never imports another member.**  The seam reads
what a TerminalPick *is* — a carrier with a ``pick`` attribute
(absent-able, ``None`` for a policy that emitted none) and a ``score``
attribute (always present) — and a carried pick is read through its
one ``node_id``, feature 222's address, exactly the reads 255's writer
performs on the same carrier for the same five facts.  No
``isinstance`` anywhere: the module loader imports a member under a
synthetic name and re-executes it, so the answer a *composed*
application's replay path produced can be a second class object of the
same name, and an ``isinstance`` would refuse the very answer the
deployment measured.  The two readers refuse what is not a terminal
answer — a carrier with no ``score``, a pick that names no node — and
the record's own construction refuses values it could not honestly
carry, so a record built by hand (a test, a later adapter over
recorded answers) is held to the same law the emission path already
passed: a frozen value that validated nothing would lend the seam's
guarantees to testimony nobody stood behind.

**No clock of this module's own.**  §16's tuple names five fields and
no instant, and the one timestamp the emission carries is the
:class:`logging.LogRecord`'s own ``created`` — the logging
infrastructure's clock, read where the record is made.  The module
reads no ``datetime`` and no ``time``: a record stamped by the
infrastructure that emitted it is labelled by the same hand that
sequenced it, and a second timestamp of the member's own would be a
second clock the stream's order could disagree with.

**No component, no store — the sentence demands no state a deployment
holds.**  The member's registration-grows-per-feature law (*"each
composes only if its sentence demands state a deployment holds"*)
lands this one as a pure emission seam: no ``@register`` builder, no
``DATABASE_URL``, no schema — nothing here can spend I/O inside
``create_app()``, and the member's three composed components (the
route, the dashboard, the live-metrics store) are untouched.  The
caller that runs replays reaches this seam by importing the member —
the same reach the fdr-deploy route's own docstring describes for the
operator surface — and the logger's name is the deployment's routing
handle: one handler on ``"ops"`` captures every record this member
emits, and 348's evaluation records will nest beside these under the
same parent when that seam lands.

Stdlib only — :mod:`dataclasses` for the record, :mod:`logging` for
the one emission, :mod:`math` for the finite and NaN checks,
:mod:`typing` for the seam — the member's import stays cheap on every
factory scan, and nothing here can grow a dependency the replay path
would pay for.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

from .errors import ReplayLogError

__all__ = [
    "REPLAY_LOG_LEVEL",
    "REPLAY_LOG_LOGGER_NAME",
    "ReplayLogRecord",
    "emit_replay_log",
]

#: Sentinel distinguishing *the carrier carried no attribute at all*
#: from *the carrier carried the attribute with value* ``None`` — the
#: same distinction feature 249's own ``_ABSENT`` draws between a read
#: that carried no ``pick`` and one that carried ``pick = None``, for
#: the same reason: the two facts have different repairs (fix the
#: carrier, versus carry the miss), and a seam that answered one for
#: the other would log broken wiring as an honest terminal answer.
_ABSENT = object()

#: The logger this seam emits on — a literal, not ``__name__``, because
#: the module loader imports a member under a synthetic name and
#: re-executes it, so the name a re-executed copy would read is not the
#: name the deployment needs to configure.  Dotted under ``"ops"`` so
#: the member's records nest under one parent: a deployment's single
#: handler on ``"ops"`` captures these records and the evaluation
#: records feature 348 will emit beside them, and the parent's level is
#: the one knob that says whether the system's structured log ships.
REPLAY_LOG_LOGGER_NAME = "ops.replay_log"

#: The level the record is emitted at — INFO, the level of routine
#: testimony.  §10.4's arithmetic makes the volume argument: 200 worlds
#: × 40 policy revisions is ~8000 replays per dreaming cycle, so
#: WARNING would page an operator eight thousand times a cycle for
#: records the sentence says the system *emits*, while DEBUG would
#: default them off in every deployment that had not opted in — and a
#: record the feature exists to emit must survive a default logger
#: config.  INFO is the opt-in level: the stream ships exactly where a
#: deployment points a handler at ``"ops"``.
REPLAY_LOG_LEVEL = logging.INFO


@dataclass(frozen=True, slots=True)
class ReplayLogRecord:
    """The structured record one replay emits — §16's five fields.

    Frozen, because testimony that could move would be a score that
    changed after the replay finished: the replay member's own terminal
    answer states the law for its two consumers (*"the replay writes
    one row (feature 255) and one log record (§913) from one answer,
    and the row, the record and the value must not drift"*), and this
    is the record half of that pair — the row is 255's, the value is
    249's, and this value holds the same five facts in the order §16's
    tuple spells them.

    Construction holds the record to what a log stream can honestly
    carry, and every refusal is :class:`~ops.errors.ReplayLogError`:

    * **policy_version**, **world_id** — non-empty strings.  An id that
      names nothing writes testimony no ``(policy, world)`` pair
      names, and the pair is the identity every downstream count — the
      miss rate, the per-pair verdict, the argmax — groups by.
    * **beta** — a finite number (``bool`` refused, as everywhere in
      this workspace).  A beta that is not finite is a hyperparameter
      no reader could reproduce the scoring under.
    * **score** — a real number or ``-inf``.  A NaN is refused (it
      compares false against everything and would read as "no
      scoring"); ``-inf`` is *not* refused, because it is the miss —
      the floor feature 249 scores a policy that emitted no pick, and
      the record an operator counts that miss by.
    * **committed_pick** — the node id the policy committed to, or
      ``None`` for the miss.  ``None`` is not a stand-in for an
      unknown id: the decision that was never made stays
      distinguishable from one that was, the same polarity migration
      0109's nullable column legislates for the row this record
      mirrors.  An id that is not a non-empty string is refused — the
      record carries the address as the pick made it and refuses one
      it would have to re-spell.

    The five fields are the whole record.  No trend, no duration
    (252's record carries one), no threshold (253's alert judges one),
    no holdout flag (255's row carries one, because a row is queried
    by it; a log record is *counted*, and §16's tuple is the count's
    schema) — a field here that §16 did not name would be a second
    place the stream's schema could grow opinions the deployment's
    parser then has to track.
    """

    #: The policy revision under test — the ``policy_version`` of
    #: §16's tuple, and of the ``replay_score`` row this record
    #: mirrors.
    policy_version: str

    #: The world the policy was replayed against — the ``world_id`` of
    #: §16's tuple.
    world_id: str

    #: The beta the scoring was made at — the hyperparameter the score
    #: is reproducible under.
    beta: float

    #: The termination's score — a real number, or ``-inf`` for the
    #: miss.  Always present, never NaN: the miss is a score.
    score: float

    #: The node id the policy committed to, or ``None`` for the miss.
    committed_pick: str | None

    def __post_init__(self) -> None:
        # The ask, validated field by field — every refusal fires here,
        # at construction, which is *before* the emitter asks the
        # logger for anything: a refused ask puts no record on the
        # stream at all, the ordering law this member's other seams
        # state for the stores they touch.
        _require_id(self.policy_version, "policy version")
        _require_id(self.world_id, "world id")
        _require_beta(self.beta)
        _require_score(self.score)
        _require_pick(self.committed_pick)

    @property
    def fields(self) -> dict[str, Any]:
        """The five fields as a mapping — the record's one schema.

        §16's tuple spelled as a mapping, in the tuple's own order, so
        the emission (``extra``), the derived :attr:`line` and any
        formatter or test reading the record all share **one** spelling
        of the five names — a second list of them anywhere in this
        module would be a second thing to keep in sync with the
        sentence.  A fresh ``dict`` per call, deliberately not a frozen
        proxy: the deployment's serializer owns this mapping's next
        step, and a proxy is a type ``json.dumps`` refuses.  Treat it
        as read-only testimony; the record it came from does not move.
        """
        return {
            "policy_version": self.policy_version,
            "world_id": self.world_id,
            "beta": self.beta,
            "score": self.score,
            "committed_pick": self.committed_pick,
        }

    @property
    def line(self) -> str:
        """The record's message — every field, once, in §16's order.

        ``"replay policy_version=… world_id=… beta=… score=…
        committed_pick=…"``, derived from :attr:`fields` so the line
        and the mapping cannot disagree (the ``-inf`` miss renders as
        ``score=-inf``, the miss's pick as ``committed_pick=None`` —
        the honest spellings, no dashes and no zeros standing in for
        either).  This is the line a plain-text handler prints and the
        string a raw stream greps; it is not the serialization, and
        the structured consumers read :attr:`fields` off the emitted
        record instead.
        """
        return "replay " + " ".join(
            f"{name}={value}" for name, value in self.fields.items()
        )

    @property
    def committed(self) -> bool:
        """Whether the replay's policy emitted a pick — computed, never
        stored.

        ``committed_pick is not None``, spelled for the caller that
        wants the fact and not the address: feature 249's own record
        documents the split for exactly this consumer (*"a dreaming
        loop logging ``(score, committed_pick)`` per run reads the
        flag and the pick separately"*).  Not a requirement read — an
        uncommitted termination is not an error state, and the record
        answers ``False`` for one the same way it answers ``-inf`` for
        the score: the miss is testimony, not a refusal.
        """
        return self.committed_pick is not None


def emit_replay_log(
    pick: Any,
    policy_version: Any,
    world_id: Any,
    beta: Any,
) -> ReplayLogRecord:
    """Emit one structured log record for one replay; return the record.

    Feature 349's sentence as one call: read the replay's terminal
    answer (feature 249's :class:`~replay.TerminalPick` — the pick,
    absent-able, and the score, always present), and emit exactly one
    stdlib log record on :data:`REPLAY_LOG_LOGGER_NAME` at
    :data:`REPLAY_LOG_LEVEL`, carrying the policy version under test,
    the world it was replayed against, the beta it was scored at, the
    resulting score and the committed pick — §16's tuple, all five
    fields, as ``extra`` on the record and as the derived
    ``key=value`` line in its message.

    **One call, one record.**  The call is the seam's whole
    transaction: the ask is validated first (the carrier reads, then
    the record's own construction), and only a record that passed
    reaches the logger — one :class:`logging.LogRecord` per call, so a
    caller invoking this once per replay emits one structured record
    per replay, and a refused ask emits nothing at all.

    Args:
        pick: Feature 249's :class:`~replay.TerminalPick` — the
            terminal answer the replay's round loop produced.  Read
            duck-typed (a member never imports another member, and the
            loader's synthetic-name wrinkle means an ``isinstance``
            would refuse the very answer a composed application
            produced): a carrier with no ``score`` attribute is refused
            as not a terminal answer, and a carried pick is read
            through its ``node_id``, refused if it names none.
        policy_version: The policy revision under test — a non-empty
            string.
        world_id: The world the policy was replayed against — a
            non-empty string.
        beta: The beta the scoring was made at — a finite number.

    Returns:
        The :class:`ReplayLogRecord` emitted — frozen testimony the
        caller can hold beside the row it persisted (feature 255's
        writer answers the row's id for the same reason: name what you
        just made, so it never has to be re-read to be known).

    Raises:
        ReplayLogError: The ask, refused — a carrier that is not a
            terminal answer, a pick that names no node, an id that is
            not a non-empty string, a beta that is not finite, a score
            that is not a real number or ``-inf`` (a NaN is refused;
            the miss never is).  Every refusal fires before the logger
            is asked, so a refused ask puts nothing on the stream.
    """
    # The ask first, the stream second: the carrier is read and the
    # record constructed (which validates every field it holds) before
    # the logger is asked for anything — the ordering this member's
    # other seams hold toward the stores they touch, held here toward
    # the one stream this seam owns.
    node_id = _committed_node_id(pick)
    score = _score_of(pick)
    record = ReplayLogRecord(
        policy_version=policy_version,
        world_id=world_id,
        beta=beta,
        score=score,
        committed_pick=node_id,
    )
    logging.getLogger(REPLAY_LOG_LOGGER_NAME).log(
        REPLAY_LOG_LEVEL, record.line, extra=record.fields
    )
    return record


# -- the carrier, read duck-typed ---------------------------------------------------------


def _committed_node_id(pick: Any) -> Any:
    """The committed pick's node id — or None for the miss.

    A committing policy's pick is feature 222's
    :class:`~policy_runtime.CommittedPick`, read through its one
    ``node_id`` — the same read feature 255's writer performs on the
    same carrier for the row's ``committed_pick`` column.  A policy
    that emitted no pick (``pick is None``) answers ``None``: the
    decision that was never made stays distinguishable from one that
    was.  A carried pick with no ``node_id`` is refused, naming what
    arrived — a pick that names no node is a decision no address
    answers, and testimony of one would be a committed pick no node
    could back.  The value is passed through as read, never
    re-spelled: the record's own construction refuses an id it could
    not carry as the address the pick made.
    """
    carried = getattr(pick, "pick", None)
    if carried is None:
        # The miss: no pick was emitted.  Carried as None — the miss
        # is emitted, never refused, exactly as the row carries it.
        return None
    node_id = getattr(carried, "node_id", _ABSENT)
    if node_id is _ABSENT:
        raise ReplayLogError(
            f"the committed pick has no node id — got {carried!r} "
            f"({type(carried).__name__}) from {pick!r}. The record's "
            "committed_pick is the node the policy committed to "
            "(feature 222's CommittedPick.node_id), and a pick that "
            "names no node is a decision no address answers — hand the "
            "terminal answer the replay's requirement produced "
            "(feature 349, docs §16)"
        )
    return node_id


def _score_of(pick: Any) -> Any:
    """The score to carry — read off the terminal answer, as-is.

    The score is read from what a TerminalPick *is*: a carrier with a
    ``score`` attribute answering a real number or ``-inf``.  A
    carrier with no ``score`` is not a terminal answer at all, and is
    refused naming what arrived — the record is shaped around the pair
    the terminal requirement answers (the pick absent-able, the score
    always present), and a carrier with no score answers no completed
    scoring.  The value is passed through as read; whether it is a
    number, and whether it is the miss or a NaN, is the record's own
    law, stated where the record's other fields are held to theirs.
    """
    score = getattr(pick, "score", _ABSENT)
    if score is _ABSENT:
        raise ReplayLogError(
            f"a replay's log record is emitted from feature 249's "
            f"TerminalPick — got {pick!r} ({type(pick).__name__}), "
            "which has no `score`. The record carries §16's five "
            "fields, and the score is the one that is always present "
            "— a carrier with no score answers no completed scoring; "
            "hand the terminal answer the requirement produced "
            "(feature 349, docs §16)"
        )
    return score


# -- the record's own law ------------------------------------------------------------------


def _require_id(value: Any, what: str) -> None:
    """An id that names something — a non-empty string.

    The law feature 255's writer states for the row's two ids, held
    here for the record's: an id that names nothing writes testimony
    no ``(policy, world)`` pair names, and the pair is the identity
    every downstream count groups by.  ``bool`` needs no separate
    refusal — it is not a ``str``.
    """
    if not isinstance(value, str) or not value.strip():
        raise ReplayLogError(
            f"a replay log record's {what} is a non-empty string — got "
            f"{value!r} ({type(value).__name__}). The record names the "
            "replay it is testimony of, and an id that is not a "
            "non-empty string names no replay — the record would be "
            "structured testimony of a scoring that cannot be "
            "identified (feature 349, docs §16)"
        )


def _require_beta(beta: Any) -> None:
    """A beta a reader could reproduce the scoring under — finite.

    A beta that is not finite is not a hyperparameter; it is a value
    outside the space the scoring was made in, and no reader of the
    record could reproduce the score under it.  ``bool`` is refused
    first, as everywhere in this workspace: ``True`` is ``1``, and a
    flag where a hyperparameter belongs would silently name a beta
    nobody set.
    """
    if isinstance(beta, bool) or not isinstance(beta, (int, float)):
        raise ReplayLogError(
            f"a replay log record's beta is a finite number — got "
            f"{beta!r} ({type(beta).__name__}). The beta is the "
            "hyperparameter the score was earned under, and a value "
            "that is not a number names no scoring a reader could "
            "reproduce (feature 349, docs §16)"
        )
    if not math.isfinite(beta):
        raise ReplayLogError(
            f"a replay log record's beta is a finite number — got "
            f"{beta!r}. An infinity is not a hyperparameter — it is a "
            "value outside the space the scoring was made in, which no "
            "reader of the record could reproduce the score under "
            "(feature 349, docs §16)"
        )


def _require_score(score: Any) -> None:
    """A score — a real number, or ``-inf`` for the miss.

    The value law feature 249 states and 255 holds at the write: the
    miss is ``-inf`` and is *kept* — the record an operator counts the
    miss rate by — while a NaN compares false against everything and
    would read as "no scoring", which is the one reading testimony
    must never support.  ``bool`` is refused first (``True`` is ``1``,
    and a flag where a verdict belongs is not a verdict).  ``-inf``
    needs no case of its own: it is a number, and it is not NaN.
    """
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise ReplayLogError(
            f"a replay log record's score is a real number or -inf — "
            f"got {score!r} ({type(score).__name__}). The score is the "
            "verdict the record exists to carry, and a value that is "
            "not a number names no scoring; the miss is -inf, not a "
            "non-number (feature 349, docs §16)"
        )
    if math.isnan(score):
        raise ReplayLogError(
            f"a replay log record's score cannot be NaN — got "
            f"{score!r}. A NaN compares false against everything and "
            "would read as 'no scoring' rather than a score — the same "
            "reading feature 249 refuses to score and the row's writer "
            "refuses to persist; the miss is -inf, and the record "
            "carries it (feature 349, docs §16)"
        )


def _require_pick(committed_pick: Any) -> None:
    """The committed pick — a node id, or ``None`` for the miss.

    ``None`` is the miss and is carried, never refused — the polarity
    migration 0109's nullable column legislates for the row this
    record mirrors.  A carried id must be a non-empty string, read as
    the pick made it: the record refuses an id it would have to
    re-spell (a number, a blank), because testimony that re-spelled
    its own address would be an address the pick never made.
    """
    if committed_pick is None:
        return
    if not isinstance(committed_pick, str) or not committed_pick.strip():
        raise ReplayLogError(
            f"a replay log record's committed pick is a node id or "
            f"None for the miss — got {committed_pick!r} "
            f"({type(committed_pick).__name__}). The pick is the "
            "address the policy committed to, read as the pick made "
            "it; None is the miss, and a value that is neither names "
            "no decision the record could testify to (feature 349, "
            "docs §16)"
        )
