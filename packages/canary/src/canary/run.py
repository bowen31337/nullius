"""The nightly canary, run and recorded — ``python -m canary.run``.

additions_spec_operator_surfaces.xml, "Determinism Canary Operation",
feature 1: *System runs the determinism canary from* ``python -m
canary.run``, *which records every run so that "the canary ran and
passed" is a stored fact rather than the absence of a halt.*  Features
141-144 (app_spec.xml) gave this category a frozen reference pair, a
replay, a halt and a void sweep — every one of them a thing that happens
only when something is wrong.  A deployment that never breaks therefore
never touches any of their tables, and "the canary ran last night and
held" would be an inference from silence: no halt row, no void marker, no
evidence the nightly timer even fired.  :class:`CanaryRunStore` is the
fix — one append-only row per run, broken or not — and this module is the
door every run comes through.

**Two verbs, one command.**  ``--freeze-reference`` is the one-time setup
act: it freezes :data:`REFERENCE_POLICY` and :data:`REFERENCE_TREE` — the
same policy and tree :mod:`canary._replay`'s own test fixture already
pins (``canary-v1``, the three-node root/left/right tree) — as the
deployment's single *active* reference pair, with
:attr:`~canary.CanaryReferencePair.recorded_score` set to that pair's own
replay score (feature 142's constant is "recorded", not invented) and
:attr:`~canary.CanaryReferencePair.is_active` true.  Composed with no
flag, the command is feature 142's nightly act end to end: load the one
active pair, replay it, record the run, and — on a deviation past
:data:`~canary.DEFAULT_TOLERANCE` — halt dreaming (feature 143) and void
every score the break may have touched (feature 144), in that order,
*before* the line is printed.  A systemd timer calls this command with no
flag every night (``deploy/systemd/nullius-canary.timer``); an operator
calls it once with ``--freeze-reference`` to give the timer something to
replay.

**Exactly one active pair, enforced here, not in the store.**
:class:`~canary._reference_store.CanaryReferenceStore` carries no
uniqueness constraint on ``is_active`` — freezing a second pair with
``is_active=True`` would succeed at the store's own layer, and silently
leave "which pair does the nightly canary replay?" answerable two ways.
This module is where the answer is kept singular: ``--freeze-reference``
refuses outright when an active pair already exists
(:data:`CANARY_REFERENCE_EXISTS`, changing nothing), and a plain run
refuses when it finds none (:data:`CANARY_REFERENCE_ABSENT`) or more than
one (:data:`CANARY_REFERENCE_AMBIGUOUS`) — three readings of one
invariant, stated as code words a systemd ``OnFailure`` hook or an
operator's grep can tell apart without parsing prose.

**Exit 3 is reserved.**  0 is a replay recorded, broken or not;
1 is a refusal that touched no store (a bad reference-pair cardinality,
or a collaborator's own refusal); 2 is a missing ``DATABASE_URL``, a
configuration fault that is nobody's determinism problem; 3 is the one
code an ``OnFailure`` hook can trust to mean *the canary itself broke* —
never raised for any other reason, so an alert dispatcher can route it
straight to the recovery §15 names (halt dreaming; bisect the image
diff) instead of a generic on-call page.

**No store, no traceback.**  Every refusal this module raises carries its
own message as a :class:`~canary.CanaryError` (or lets a collaborator's
own subclass through), caught once in :func:`main` and printed to stderr
verbatim — never a stack trace, because a systemd unit's journal is read
at three in the morning by whoever is on call, not by whoever wrote this
module.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import sys
import uuid
from collections.abc import Callable, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote, urlparse

from ._errors import CanaryError
from ._halt import CanaryDeterminismBrokenError, halt_dreaming
from ._reference import CanaryPolicy, CanaryReferencePair, CanaryTree
from ._reference_store import REFERENCE_TABLE, CanaryReferenceStore
from ._replay import replay_pair
from ._void import void_scores_after_break

__all__ = [
    "CANARY_REFERENCE_ABSENT",
    "CANARY_REFERENCE_AMBIGUOUS",
    "CANARY_REFERENCE_EXISTS",
    "DATABASE_URL_ENV",
    "EXIT_BROKEN",
    "EXIT_CONFIG",
    "EXIT_OK",
    "EXIT_REFUSED",
    "REFERENCE_POLICY",
    "REFERENCE_POLICY_VERSION",
    "REFERENCE_TREE",
    "RUN_STORE_COMPONENT_NAME",
    "RUN_TABLE",
    "CanaryRun",
    "CanaryRunStore",
    "build_run_store",
    "main",
]

#: The environment variable naming the relational store — the one spelling
#: every store in this workspace already uses, restated here so this module
#: states its own contract rather than depending on another's.
DATABASE_URL_ENV = "DATABASE_URL"

# -- The built-in reference pair ------------------------------------------------
#
# The same policy and tree :mod:`canary._replay`'s own test fixture pins
# (``POLICY_VERSION = "canary-v1"``, the root/left/right tree whose score
# replays to ``0.8 * 0.3 + 0.6 * 0.7 == 0.66``) — moved here as module
# constants so ``--freeze-reference`` has a concrete, already-exercised pair
# to freeze rather than inventing one a deployment's first night would meet
# for the first time. Any value frozen from these two constants replays
# deterministically; nothing here reads an environment or a clock.

#: The built-in reference pair's policy version.
REFERENCE_POLICY_VERSION = "canary-v1"

#: The built-in reference pair's policy content — read by nothing
#: :func:`~canary.replay_pair` sums over (the replay scores the *tree*),
#: carried only so the frozen policy is not an empty object.
REFERENCE_POLICY: dict[str, Any] = {
    "scoring": {"weights": {"a": 0.5, "b": 0.5}},
    "threshold": 0.7,
}

#: The built-in reference pair's tree, as :meth:`~canary.CanaryTree.freeze`
#: takes it: ``node_id -> (parent_id, depth, payload)``. Replays to
#: ``0.8 * 0.3 + 0.6 * 0.7 == 0.66`` (the root's own score is ``0.0``).
REFERENCE_TREE: dict[str, tuple[Optional[str], int, dict[str, Any]]] = {
    "root": (None, 0, {"label": "root", "kind": "decision", "score": 0.0}),
    "left": ("root", 1, {"label": "left", "weight": 0.3, "score": 0.8}),
    "right": ("root", 1, {"label": "right", "weight": 0.7, "score": 0.6}),
}

# -- Refusal code words ----------------------------------------------------------

#: ``--freeze-reference`` found an active pair already on record. The
#: deployment must retire or replace it (by hand, in the store) before
#: freezing another — this command never does so on its own, because a
#: silent replacement would change which bytes the nightly canary has been
#: replaying without anyone deciding to.
CANARY_REFERENCE_EXISTS = "canary_reference_exists"

#: A plain run found no active reference pair to replay.
CANARY_REFERENCE_ABSENT = "canary_reference_absent"

#: A plain run found more than one active reference pair — an invariant this
#: module enforces (see the module docstring) that something outside it
#: violated.
CANARY_REFERENCE_AMBIGUOUS = "canary_reference_ambiguous"

# -- Exit codes --------------------------------------------------------------

#: A replay was recorded, within tolerance.
EXIT_OK = 0
#: A refusal that touched no store: a bad reference-pair cardinality, or a
#: collaborator's own refusal.
EXIT_REFUSED = 1
#: No ``DATABASE_URL`` — a configuration fault, not a determinism one.
EXIT_CONFIG = 2
#: Reserved for a broken canary and nothing else, so a systemd
#: ``OnFailure`` hook can route it straight to §15's recovery.
EXIT_BROKEN = 3


def _utc_now() -> datetime:
    """The current instant, timezone-aware UTC, second resolution.

    The same spelling every store in this package uses, restated here so
    this module states its own contract: the stamp orders runs against one
    another, and dropping — not rounding — the microseconds keeps it never
    *after* the instant observed.
    """
    return datetime.now(timezone.utc).replace(microsecond=0)


def _validated_uuid(name: str, value: Any) -> str:
    """A UUID in canonical text, or a refusal naming the field.

    The normalisation every row identity in this package applies (see
    :func:`canary._reference_store._validated_reference_id`), restated here
    rather than imported: a malformed id is a store-contract failure, not a
    value worth passing through to a ``sqlite3`` bind parameter that would
    happily store it as an unparseable string.
    """
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, str):
        text = value.strip()
        if text:
            try:
                return str(uuid.UUID(text))
            except ValueError:
                pass
    raise CanaryError(
        f"a canary run's {name} must be a UUID, got {value!r}; it is the "
        "row's own key (or the reference pair it names), and an id that "
        "cannot be a key names no row this store could hold"
    )


# -- The run store ----------------------------------------------------------

#: This member's own table — one row per run of ``python -m canary.run``,
#: append-only: unlike the halt and void-marker tables, a run is not a thing
#: that happens once and stays — it happens every night, and "the canary ran
#: and passed" has to be a fact recorded *again* each time, not a state that
#: holds until something writes it away.
RUN_TABLE = "canary_run"

#: The component name this member registers its run store under — a fifth
#: name beside the pin sweep, the reference store, the halt store and the
#: void-marker store: each answers a different question on a different
#: lifecycle, and this one answers *did the canary run, and what did it
#: find?* — not *is dreaming halted?*, which the halt store alone answers.
RUN_STORE_COMPONENT_NAME = "canary-run-store"

#: ``canary_run``'s DDL, created idempotently beside the code that reads it
#: — the same member-owned-table stance :mod:`canary._halt` and
#: :mod:`canary._void` take for their own tables, and deliberately not a
#: migration for the same reason: this table has exactly one writer and one
#: reader, both in this module.
_RUN_SCHEMA = f"""
-- Feature 1 (additions_spec_operator_surfaces.xml): one row per run of the
-- nightly canary, broken or not -- the stored fact that it ran, rather than
-- the absence of a halt. `id` is the run's own key; `reference_id` names the
-- pair it replayed. `score`, `recorded_score`, `deviation` and `tolerance`
-- are the comparison feature 142's replay carried; `within_tolerance` is its
-- verdict, so a reader can recompute it from the row's own arithmetic.
CREATE TABLE IF NOT EXISTS {RUN_TABLE} (
    id               TEXT NOT NULL PRIMARY KEY,
    reference_id     TEXT NOT NULL,
    ran_at           TEXT NOT NULL,
    score            REAL NOT NULL,
    recorded_score   REAL NOT NULL,
    deviation        REAL NOT NULL,
    tolerance        REAL NOT NULL,
    within_tolerance BOOLEAN NOT NULL
);
"""

#: The table's columns, in the order the insert names them and the read-back
#: unpacks them — spelled once so the write and the read cannot drift apart
#: on a column order.
_COLUMNS = (
    "id, reference_id, ran_at, score, recorded_score, deviation, tolerance, "
    "within_tolerance"
)


@dataclass(frozen=True)
class CanaryRun:
    """One recorded run of the nightly canary — the row :data:`RUN_TABLE` holds.

    Validated in :meth:`__post_init__` rather than only where it is built,
    because the read path (:meth:`CanaryRunStore.newest`) reconstructs one
    from a stored row: a row whose ``deviation`` does not equal
    ``abs(score - recorded_score)``, or whose ``within_tolerance`` disagrees
    with that arithmetic, fails to reconstruct rather than loading as a
    plausible-looking run — the same defence :class:`~canary.CanaryReplayResult`
    and :class:`~canary.DreamHalt` apply to their own comparisons, and the
    same reason: a stored run is what answers "did the canary pass last
    night", and a record that could disagree with its own numbers would
    answer that question wrong.
    """

    #: This run's own key.
    id: str
    #: The reference pair this run replayed.
    reference_id: str
    #: When this run happened.
    ran_at: datetime
    #: The score the replay produced.
    score: float
    #: The recorded constant the score was compared against.
    recorded_score: float
    #: ``abs(score - recorded_score)``.
    deviation: float
    #: The tolerance the comparison used.
    tolerance: float
    #: Whether the deviation was within the tolerance.
    within_tolerance: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _validated_uuid("id", self.id))
        object.__setattr__(
            self, "reference_id", _validated_uuid("reference_id", self.reference_id)
        )
        if not isinstance(self.ran_at, datetime) or self.ran_at.tzinfo is None:
            raise CanaryError(
                "a canary run's ran_at must be a timezone-aware datetime, got "
                f"{self.ran_at!r}; the stamp orders runs against one another, "
                "and a naive one would raise far from the write that set it"
            )
        for name in ("score", "recorded_score", "deviation", "tolerance"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise CanaryError(
                    f"a canary run's {name} must be a real number, got "
                    f"{value!r}"
                )
            if not math.isfinite(float(value)):
                raise CanaryError(
                    f"a canary run's {name} is not finite ({value!r}); a NaN "
                    "or ±inf would reach the run record dressed as the "
                    "arithmetic the comparison was made on"
                )
            object.__setattr__(self, name, float(value))
        if self.tolerance < 0:
            raise CanaryError(
                f"a canary run's tolerance must be non-negative, got "
                f"{self.tolerance!r}: it is an absolute deviation the score "
                "may stray by, and a negative tolerance names no band"
            )
        expected_deviation = abs(self.score - self.recorded_score)
        if self.deviation != expected_deviation:
            raise CanaryError(
                f"a canary run's deviation ({self.deviation!r}) does not "
                f"equal abs(score - recorded_score) ({expected_deviation!r}); "
                "a record whose own arithmetic disagrees with itself would "
                "lie to the operator reading it"
            )
        if not isinstance(self.within_tolerance, bool):
            raise CanaryError(
                f"a canary run's within_tolerance must be a bool, got "
                f"{self.within_tolerance!r} ({type(self.within_tolerance).__name__})"
            )
        expected_within = self.deviation <= self.tolerance
        if self.within_tolerance != expected_within:
            raise CanaryError(
                f"a canary run reports within_tolerance={self.within_tolerance!r}, "
                f"but the deviation {self.deviation!r} against the tolerance "
                f"{self.tolerance!r} makes it {expected_within!r}; a result "
                "that disagrees with its own deviation and tolerance would "
                "tell the operator the canary passed when it did not"
            )

    def to_payload(self) -> dict[str, Any]:
        """The run as a plain mapping, for a log line or an operator's report."""
        return {
            "id": self.id,
            "reference_id": self.reference_id,
            "ran_at": self.ran_at.isoformat(),
            "score": self.score,
            "recorded_score": self.recorded_score,
            "deviation": self.deviation,
            "tolerance": self.tolerance,
            "within_tolerance": self.within_tolerance,
        }


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into a filesystem path.

    The SQLAlchemy convention the workspace's ``DATABASE_URL`` already uses,
    restated here rather than imported so this module states its own
    contract, the way every store in this package already does. A
    pathless (in-memory) URL is refused: an in-memory database dies with
    the connection that opened it, and a canary run history must outlive
    the process that recorded it.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise CanaryError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: this "
            "store speaks sqlite:/// (the spec's single-machine allowance); "
            f"point {DATABASE_URL_ENV} at a sqlite database"
        )
    if parsed.netloc not in ("", "localhost"):
        raise CanaryError(
            f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
            f"{parsed.netloc!r}"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path or path == ":memory:":
        raise CanaryError(
            f"sqlite {DATABASE_URL_ENV} carries no database path: an "
            "in-memory database would die with the connection that opened "
            "it, and a canary run history must outlive the process that "
            "recorded it"
        )
    return Path(path)


class CanaryRunStore:
    """Feature 1's run history: an append-only row for every night the canary ran.

    Constructed with the database URL it writes to; :meth:`record` writes one
    row and :meth:`newest` reads the latest back. The class resolves its path
    lazily, so constructing one performs no I/O — the contract every store in
    this package states, and the reason composing the application never opens
    a database.

    Unlike :class:`~canary.CanaryHaltStore` and
    :class:`~canary.CanaryVoidMarkerStore`, this store keeps no "first write
    wins" idempotence: a halt and a void marker are facts about a break that
    happens once, but a run happens every night the timer fires, and
    recording the same verdict twice is two nights, not one re-observation.
    """

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise CanaryError(
                f"{DATABASE_URL_ENV} must be a non-empty database URL"
            )
        self._database_url = database_url.strip()
        # Resolved on first use rather than at construction: building the
        # store is composition-time work and must not touch the disk.
        self._path: Optional[Path] = None

    @classmethod
    def resolve(
        cls, env: Optional[Mapping[str, str]] = None
    ) -> Optional["CanaryRunStore"]:
        """The run store ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset. Absent is not an
        error: it is a deployment without a relational store, which composes
        no run-store component — a discoverable state, not an exception.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The database URL this store writes to."""
        return self._database_url

    @property
    def path(self) -> Path:
        """The SQLite file backing this store, resolved on first use."""
        if self._path is None:
            self._path = _sqlite_path(self._database_url)
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """Open the database and ensure the run table exists, idempotently."""
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        with connection:
            connection.executescript(_RUN_SCHEMA)
        return connection

    def ensure_schema(self) -> None:
        """Bring the database to the shape this store reads, idempotently."""
        self._connect().close()

    def record(
        self,
        reference_id: Any,
        *,
        score: float,
        recorded_score: float,
        deviation: float,
        tolerance: float,
        within_tolerance: bool,
        ran_at: Optional[datetime] = None,
    ) -> CanaryRun:
        """Persist one run of the nightly canary — append-only.

        Every call writes a new row, keyed by a freshly minted id: this is
        the one store in the package with no "first write wins" — a run is
        not a fact about a break that happens once, it is a fact about one
        night, and the next night's run is a different fact even when the
        reference pair and the verdict are unchanged.
        """
        candidate = CanaryRun(
            id=str(uuid.uuid4()),
            reference_id=_validated_uuid("reference_id", reference_id),
            ran_at=_utc_now() if ran_at is None else ran_at,
            score=score,
            recorded_score=recorded_score,
            deviation=deviation,
            tolerance=tolerance,
            within_tolerance=within_tolerance,
        )
        with closing(self._connect()) as connection, connection:
            connection.execute(
                f"INSERT INTO {RUN_TABLE} ({_COLUMNS}) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    candidate.id,
                    candidate.reference_id,
                    candidate.ran_at.isoformat(),
                    candidate.score,
                    candidate.recorded_score,
                    candidate.deviation,
                    candidate.tolerance,
                    candidate.within_tolerance,
                ),
            )
        return candidate

    def newest(self) -> Optional[CanaryRun]:
        """The most recent run on record, or ``None`` when the canary has never run.

        Ordered by ``(ran_at, id)`` descending — the stamp is the ordering
        the feature's own sentence turns on ("the canary ran *last* night"),
        and the id is a stable tie-break for two runs stamped the same
        second. Reconstructed through :class:`CanaryRun`'s own validation,
        so a row edited outside this package fails to reconstruct rather
        than loading as a plausible-looking run.
        """
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                f"SELECT {_COLUMNS} FROM {RUN_TABLE} "
                "ORDER BY ran_at DESC, id DESC LIMIT 1"
            )
            try:
                row = cursor.fetchone()
            finally:
                cursor.close()
        if row is None:
            return None
        return self._record_from_row(row)

    @staticmethod
    def _record_from_row(row: tuple) -> CanaryRun:
        return CanaryRun(
            id=row[0],
            reference_id=row[1],
            ran_at=datetime.fromisoformat(row[2]),
            score=row[3],
            recorded_score=row[4],
            deviation=row[5],
            tolerance=row[6],
            within_tolerance=bool(row[7]),
        )


def build_run_store(
    env: Optional[Mapping[str, str]] = None,
) -> Optional[CanaryRunStore]:
    """Build the run store the composed application carries.

    The one-shot convenience the component builder uses, kept beside the
    class so a test and the factory construct it the same way. Resolves
    rather than strict: the factory builds this component on every
    ``create_app()``, so it must succeed without a ``DATABASE_URL`` and
    compose ``None`` where the deployment has no relational store — a
    discoverable state, not an exception.
    """
    return CanaryRunStore.resolve(env)


# -- The CLI: `python -m canary.run` ---------------------------------------------


def _active_reference_ids(store: CanaryReferenceStore) -> tuple[str, ...]:
    """The reference ids whose ``canary_reference`` row is active, sorted.

    Reads :data:`~canary._reference_store.REFERENCE_TABLE` directly rather
    than through :class:`~canary.CanaryReferenceStore`'s own API, which has
    no "find the active pair" verb (see the module docstring for why that
    search lives here and not in the store). A database the store has never
    touched — no file, or a file with no ``canary_reference`` table yet — has
    no active pair, read as the empty tuple rather than an error: this
    function is a read, and reading before the first freeze must not create
    anything or raise.
    """
    path = store.path
    if not path.exists():
        return ()
    with closing(sqlite3.connect(path)) as connection:
        try:
            rows = connection.execute(
                f"SELECT reference_id FROM {REFERENCE_TABLE} WHERE is_active = 1 "
                "ORDER BY reference_id"
            ).fetchall()
        except sqlite3.OperationalError:
            return ()
    return tuple(row[0] for row in rows)


def _freeze_reference(database_url: str) -> str:
    """``--freeze-reference``'s whole act: freeze the built-in pair, once.

    Refuses with :data:`CANARY_REFERENCE_EXISTS` when an active pair is
    already on record, naming it, and changes nothing in that case — no
    table is touched, because a refusal that wrote anything would leave an
    operator re-running the command unsure what state it left behind.
    Otherwise freezes :data:`REFERENCE_POLICY` and :data:`REFERENCE_TREE`
    under :data:`REFERENCE_POLICY_VERSION`, replays the pair once to learn
    its own score, and freezes it again — a pair whose recorded constant
    *is* its own replay score, so the first plain run after this one finds a
    pair already within tolerance of itself — and returns the minted
    ``reference_id``.
    """
    store = CanaryReferenceStore(database_url)
    existing = _active_reference_ids(store)
    if existing:
        raise CanaryError(
            f"{CANARY_REFERENCE_EXISTS}: an active canary reference pair is "
            f"already on record ({existing[0]!r}); freezing a second active "
            "pair would leave the nightly canary unable to say which one to "
            "replay, so nothing was changed"
        )
    policy = CanaryPolicy.freeze(
        version=REFERENCE_POLICY_VERSION, policy=REFERENCE_POLICY
    )
    tree = CanaryTree.freeze(REFERENCE_TREE)
    instant = _utc_now()
    provisional = CanaryReferencePair(
        policy=policy,
        tree=tree,
        recorded_score=None,
        id=None,
        is_active=True,
        created_at=instant,
    )
    score = replay_pair(provisional).score
    pair = CanaryReferencePair(
        policy=policy,
        tree=tree,
        recorded_score=score,
        id=None,
        is_active=True,
        created_at=instant,
    )
    record = store.freeze(pair)
    return record.reference_id


def _replay_active_reference(database_url: str) -> tuple[dict[str, Any], bool]:
    """A plain run's whole act: load, replay, record, and halt on a break.

    Refuses with :data:`CANARY_REFERENCE_ABSENT` or
    :data:`CANARY_REFERENCE_AMBIGUOUS` when the reference-pair cardinality
    this module enforces (see the module docstring) is not exactly one —
    before anything is replayed or recorded. Otherwise replays the single
    active pair, records one :class:`CanaryRun` row unconditionally, and —
    only on a deviation past tolerance — calls
    :func:`~canary.halt_dreaming` (swallowing the
    :class:`~canary.CanaryDeterminismBrokenError` it raises after writing
    the halt row; that raise *is* feature 143's alert, not a refusal this
    command reports as one) and :func:`~canary.void_scores_after_break`, in
    that order, before returning. Returns the printed payload and whether
    the run broke.
    """
    reference_store = CanaryReferenceStore(database_url)
    active_ids = _active_reference_ids(reference_store)
    if not active_ids:
        raise CanaryError(
            f"{CANARY_REFERENCE_ABSENT}: no active canary reference pair is "
            "on record; freeze one with `python -m canary.run "
            "--freeze-reference` before running the nightly canary"
        )
    if len(active_ids) > 1:
        raise CanaryError(
            f"{CANARY_REFERENCE_AMBIGUOUS}: {len(active_ids)} active canary "
            f"reference pairs are on record ({', '.join(active_ids)}); "
            "exactly one must be active for the nightly canary to know "
            "which pair to replay"
        )
    reference_id = active_ids[0]
    pair = reference_store.load(reference_id).pair
    result = replay_pair(pair)
    run_record = CanaryRunStore(database_url).record(
        reference_id,
        score=result.score,
        recorded_score=result.recorded_score,
        deviation=result.deviation,
        tolerance=result.tolerance,
        within_tolerance=result.within_tolerance,
    )
    broken = not result.within_tolerance
    if broken:
        try:
            halt_dreaming(pair, result, database_url=database_url)
        except CanaryDeterminismBrokenError:
            # The raise *is* feature 143's determinism_broken alert, already
            # persisted by halt_dreaming before it raised — not a refusal
            # this command reports as EXIT_REFUSED. Feature 144's sweep
            # still runs, and the broken JSON line is still printed, below.
            pass
        void_scores_after_break(database_url=database_url)
    payload = {
        "reference_id": run_record.reference_id,
        "score": run_record.score,
        "recorded_score": run_record.recorded_score,
        "deviation": run_record.deviation,
        "within_tolerance": run_record.within_tolerance,
        "ran_at": run_record.ran_at.isoformat(),
    }
    return payload, broken


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m canary.run",
        description=(
            "Run the nightly determinism canary: replay the active frozen "
            "reference pair, record the run, and halt dreaming on a "
            "deviation beyond tolerance. --freeze-reference instead freezes "
            "the built-in reference pair as the deployment's active one."
        ),
    )
    parser.add_argument(
        "--freeze-reference",
        action="store_true",
        help=(
            "freeze the built-in reference pair as the active reference, "
            "instead of replaying it"
        ),
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    emit: Callable[[str], object] = print,
) -> int:
    """``python -m canary.run [--freeze-reference]``.

    Checks ``DATABASE_URL`` before anything else — absent, this exits
    :data:`EXIT_CONFIG` with one line naming it, because an unconfigured
    deployment is a configuration fault, not a determinism one.  With
    ``--freeze-reference``, freezes the built-in pair
    (:func:`_freeze_reference`) and prints the minted ``reference_id`` bare
    — not as JSON, because it is the one output this command emits that is
    not a record of a replay.  With no flag, replays the active pair
    (:func:`_replay_active_reference`), prints one JSON line (``reference_id``,
    ``score``, ``recorded_score``, ``deviation``, ``within_tolerance``,
    ``ran_at``) and returns :data:`EXIT_BROKEN` when the run broke,
    :data:`EXIT_OK` otherwise.

    Either verb's refusal — a bad reference-pair cardinality, a
    collaborator's own :class:`~canary.CanaryError` — is caught here,
    printed to stderr with no traceback, and answered :data:`EXIT_REFUSED`.
    A :class:`~canary.CanaryDeterminismBrokenError` never reaches this
    ``except``: it is swallowed where it is raised, inside
    :func:`_replay_active_reference`, because that raise is feature 143's
    alert (already acted on) and not a refusal this command reports as one.

    ``env`` and ``emit`` are this command's seams, read and written exactly
    as the other operator CLIs in this workspace take them.
    """
    arguments = _build_parser().parse_args(argv)
    source = os.environ if env is None else env

    database_url = source.get(DATABASE_URL_ENV, "").strip()
    if not database_url:
        print(
            f"{DATABASE_URL_ENV} must name the database the nightly canary "
            "reads its reference pair from and writes its run history to",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    if arguments.freeze_reference:
        try:
            reference_id = _freeze_reference(database_url)
        except CanaryError as exc:
            print(str(exc), file=sys.stderr)
            return EXIT_REFUSED
        emit(reference_id)
        return EXIT_OK

    try:
        payload, broken = _replay_active_reference(database_url)
    except CanaryError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_REFUSED

    emit(json.dumps(payload))
    return EXIT_BROKEN if broken else EXIT_OK


if __name__ == "__main__":  # pragma: no cover - the module's own door
    raise SystemExit(main())
