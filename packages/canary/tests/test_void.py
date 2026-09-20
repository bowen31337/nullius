"""Voiding every score produced after a determinism break — feature 144.

These tests pin :mod:`canary._void` — the half of §12's canary paragraph that
takes what a break *cost*: *"halts dreaming and marks scores produced in the
affected window as void"*.  The properties under test are the ones the module
docstring argues:

* the sweep reads the pool (``replay_score``), selects every row whose
  ``created_at`` falls in the window, and marks each one — a score produced
  after a break is void whether or not a sweep has run over it yet, so bad data
  cannot be served during the lag before the nightly sweep;
* the pool itself is never written to: the score rows are evidence, the marker
  lives in this member's own ``canary_void_marker`` table, and a second sweep
  over an already-marked pool writes nothing while reporting the same refusal;
* the window's edge is the **earliest** break on record, strictly compared, so
  a later break on another pair can only widen the affected window and a score
  once void stays void — the "does not age into good data" half of the
  sentence made structural;
* a marker cites a break, or it is refused: a canary that held has no window,
  and a score written before the break is not in it;
* the guard (:meth:`CanaryVoidMarkerStore.require_score_usable`) is the
  read-time refusal a dreaming or replay path consults, carrying the stored
  marker when it refuses.

The pairs, results and halts below are real, not mocks: the point of the
feature is that the window is opened on a break a frozen pair *actually*
produced, so every halt is written by :func:`canary.halt_dreaming` (or, where
the test is about the window rather than the decision, by
:meth:`CanaryHaltStore.halt`) off a genuinely broken
:func:`canary.replay_pair`.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from canary import (
    DETERMINISM_BROKEN,
    VOID_MARKER_COMPONENT_NAME,
    VOID_STATUS,
    VOID_TABLE,
    CanaryError,
    CanaryHaltStore,
    CanaryReferencePair,
    CanaryTree,
    CanaryVoidMarkerError,
    CanaryVoidMarkerStore,
    VoidMarker,
    VoidSweep,
    VoidWindow,
    mark_void_score,
    replay_pair,
    require_score_usable,
    unvoided_scores,
    void_scores_after_break,
)
from canary._reference import CanaryPolicy

POLICY_VERSION = "canary-v1"

#: The break's instant — the edge of every window in this suite.
DETECTED_AT = datetime(2025, 6, 1, 3, 0, 0, tzinfo=timezone.utc)
#: A score produced two hours *before* the break: not in any window.
BEFORE_BREAK = DETECTED_AT - timedelta(hours=2)
#: A score produced one second *after* the break: the first one voided.
AFTER_BREAK = DETECTED_AT + timedelta(seconds=1)
#: A second, later break on another pair, for the monotonicity tests.
LATER_BREAK = DETECTED_AT + timedelta(days=7)

#: The score the fixture tree replays to (``test_replay`` spells the same
#: expectation): ``0.8 * 0.3 + 0.6 * 0.7``, the root contributing ``0.0``.
EXPECTED_SCORE = 0.8 * 0.3 + 0.6 * 0.7


# -- Fixtures ------------------------------------------------------------------


def _policy(
    version: str = POLICY_VERSION, *, weights: dict[str, float] | None = None
) -> CanaryPolicy:
    return CanaryPolicy.freeze(
        version=version,
        policy={
            "scoring": {"weights": weights or {"a": 0.5, "b": 0.5}},
            "threshold": 0.7,
        },
    )


def _tree() -> CanaryTree:
    return CanaryTree.freeze(
        {
            "root": (None, 0, {"label": "root", "kind": "decision", "score": 0.0}),
            "left": ("root", 1, {"label": "left", "weight": 0.3, "score": 0.8}),
            "right": ("root", 1, {"label": "right", "weight": 0.7, "score": 0.6}),
        }
    )


def _broken_pair(
    *,
    recorded: float | None = None,
    version: str = POLICY_VERSION,
    weights: dict[str, float] | None = None,
) -> CanaryReferencePair:
    """A pair whose recorded constant the replayed score misses by ``0.5``.

    A deviation §12's ``1e-12`` cannot forgive — the same fixture
    ``test_halt`` builds, so the break this suite windows on is a real one.

    ``weights`` moves the policy's *content*, which is what a pair's identity
    is derived from: :meth:`CanaryPolicy.freeze` hashes the policy mapping and
    not the version label, so two pairs that differ only in label are one pair
    as far as the halt store is concerned — a truth the monotonicity test below
    depends on and would otherwise silently test nothing about.
    """
    return CanaryReferencePair(
        policy=_policy(version, weights=weights),
        tree=_tree(),
        recorded_score=EXPECTED_SCORE + 0.5 if recorded is None else recorded,
        id=None,
        is_active=True,
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )


def _break_the_canary(halts: CanaryHaltStore, **kwargs: object) -> None:
    """Halt dreaming for real: replay a broken pair and persist the break.

    The window is opened by the break the *canary* pronounced, not by a
    hand-inserted row, because that is the property feature 144 depends on —
    the edge is feature 143's own ``detected_at``.
    """
    pair = _broken_pair(**kwargs)  # type: ignore[arg-type]
    halts.halt(pair, replay_pair(pair), detected_at=DETECTED_AT)


def _seed_score(
    store: CanaryVoidMarkerStore,
    *,
    produced_at: datetime,
    score: float = 0.42,
    policy_version: str = POLICY_VERSION,
    score_id: str | None = None,
) -> str:
    """Insert one ``replay_score`` row — the pool feature 144 sweeps.

    Written through the schema the *store itself* created (called after
    :meth:`CanaryVoidMarkerStore.ensure_schema`), so the suite seeds exactly
    the pool the store will read rather than a table it happens to tolerate.
    """
    identity = score_id or str(uuid.uuid4())
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "INSERT INTO replay_score "
            "(id, policy_version, world_id, beta, score, committed_pick, "
            " is_holdout, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                identity,
                policy_version,
                str(uuid.uuid4()),
                0.5,
                score,
                None,
                0,
                produced_at.isoformat(),
            ),
        )
    return identity


@pytest.fixture
def halts(test_database_url: str) -> CanaryHaltStore:
    """Feature 143's store, pointed at the per-test database."""
    return CanaryHaltStore(test_database_url)


@pytest.fixture
def store(test_database_url: str) -> CanaryVoidMarkerStore:
    """A void-marker store pointed at the per-test database."""
    return CanaryVoidMarkerStore(test_database_url)


# -- The window ------------------------------------------------------------------


class TestTheWindowIsOpenedByABreak:
    def test_no_break_on_record_is_no_window(self, store: CanaryVoidMarkerStore) -> None:
        # A canary that held has no affected window.  ``None`` is deliberately
        # distinct from an *empty* window: a caller must be able to tell "the
        # canary held" from "the canary broke and nothing was produced after
        # it".
        assert store.window() is None

    def test_a_break_opens_the_window_at_its_own_instant(
        self, store: CanaryVoidMarkerStore, halts: CanaryHaltStore
    ) -> None:
        _break_the_canary(halts)
        window = store.window()
        assert window is not None
        assert window.detected_at == DETECTED_AT
        assert window.alert_kind == DETERMINISM_BROKEN
        assert window.status == VOID_STATUS

    def test_the_window_carries_the_broken_pair_identity(
        self, store: CanaryVoidMarkerStore, halts: CanaryHaltStore
    ) -> None:
        pair = _broken_pair()
        _break_the_canary(halts)
        window = store.window()
        assert window is not None
        assert window.code_hash == pair.policy.code_hash
        assert window.tree_hash == pair.tree.tree_hash

    def test_the_edge_is_strict(self, store: CanaryVoidMarkerStore, halts: CanaryHaltStore) -> None:
        # §12 line 677's own `>` is strict, and feature 144's word is *after*:
        # a score written at the very instant the break was detected was
        # produced *as* the break, not after it.
        _break_the_canary(halts)
        window = store.window()
        assert window is not None
        assert not window.contains(DETECTED_AT)
        assert not window.contains(DETECTED_AT - timedelta(seconds=1))
        assert window.contains(DETECTED_AT + timedelta(seconds=1))

    def test_the_edge_follows_the_earliest_break_not_the_latest(
        self, store: CanaryVoidMarkerStore, halts: CanaryHaltStore
    ) -> None:
        # The property that stops bad data aging into good data: a second,
        # later break on another pair must not pull the boundary *forward* and
        # shrink the set of scores this system refuses.
        _break_the_canary(halts)
        pair = _broken_pair(
            version="canary-v2", weights={"a": 0.25, "b": 0.75}
        )
        assert pair.policy.code_hash != _broken_pair().policy.code_hash
        halts.halt(pair, replay_pair(pair), detected_at=LATER_BREAK)
        window = store.window()
        assert window is not None
        assert window.detected_at == DETECTED_AT
        assert window.code_hash != pair.policy.code_hash  # the earliest pair's
        # ...and the *latest* break is still what the operator's page shows:
        # the two reads answer two different questions and are not the same
        # read under two names.
        latest = halts.current_halt()
        assert latest is not None
        assert latest.detected_at == LATER_BREAK

    def test_the_window_is_a_validated_value(self) -> None:
        # A window naming anything but §12's break or the workspace's one
        # spelling of VOID is refused: the window and the markers it produces
        # carry one verdict, and a window disagreeing with them would open onto
        # markers it did not describe.
        with pytest.raises(CanaryVoidMarkerError):
            VoidWindow(
                detected_at=DETECTED_AT,
                code_hash="ab" * 32,
                tree_hash="cd" * 32,
                alert_kind="something_else",
                status=VOID_STATUS,
            )
        with pytest.raises(CanaryVoidMarkerError):
            VoidWindow(
                detected_at=DETECTED_AT,
                code_hash="ab" * 32,
                tree_hash="cd" * 32,
                alert_kind=DETERMINISM_BROKEN,
                status="void",
            )

    def test_a_naive_edge_is_refused_at_construction(self) -> None:
        # The window is a comparison; an aware/naive one raises far from the
        # write that set it, so the record refuses it where the field is named.
        with pytest.raises(CanaryVoidMarkerError):
            VoidWindow(
                detected_at=datetime(2025, 6, 1, 3, 0, 0),
                code_hash="ab" * 32,
                tree_hash="cd" * 32,
                alert_kind=DETERMINISM_BROKEN,
                status=VOID_STATUS,
            )


# -- The sweep: feature 144's verb -----------------------------------------------


class TestTheSweepVoidsTheAffectedWindow:
    def test_every_score_after_the_break_is_marked(
        self, store: CanaryVoidMarkerStore, halts: CanaryHaltStore
    ) -> None:
        store.ensure_schema()
        before = _seed_score(store, produced_at=BEFORE_BREAK)
        after_one = _seed_score(store, produced_at=AFTER_BREAK)
        after_two = _seed_score(store, produced_at=AFTER_BREAK + timedelta(hours=1))
        _break_the_canary(halts)
        sweep = store.sweep()
        assert sweep is not None
        assert sweep.refused_score_ids == (after_one, after_two)
        assert before not in sweep.refused_score_ids
        assert sweep.pool_size == 3

    def test_no_break_means_nothing_is_void(self, store: CanaryVoidMarkerStore) -> None:
        # The untaken branch, through this feature: a canary that held has no
        # window, so the sweep is a quiet return and the pool is untouched.
        store.ensure_schema()
        _seed_score(store, produced_at=BEFORE_BREAK)
        _seed_score(store, produced_at=AFTER_BREAK)
        assert store.sweep() is None
        assert store.markers() == ()

    def test_the_pool_is_never_written_to(
        self, store: CanaryVoidMarkerStore, halts: CanaryHaltStore
    ) -> None:
        # The score rows are evidence — ``0109``'s own word — and this feature
        # is forbidden from rewriting the reason a past policy revision was
        # selected.  The marker is a row in this member's own table.
        store.ensure_schema()
        score_id = _seed_score(store, produced_at=AFTER_BREAK)
        _break_the_canary(halts)
        store.sweep()
        with sqlite3.connect(store.path) as connection:
            rows = connection.execute("SELECT * FROM replay_score").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == score_id
        assert store.voided(score_id)

    def test_a_second_sweep_writes_nothing_and_refuses_the_same_scores(
        self, store: CanaryVoidMarkerStore, halts: CanaryHaltStore
    ) -> None:
        # Idempotence: running the sweep twice is observably the same refusal,
        # which is what lets a nightly runner call it unconditionally.
        store.ensure_schema()
        _seed_score(store, produced_at=AFTER_BREAK)
        _seed_score(store, produced_at=AFTER_BREAK + timedelta(hours=1))
        _break_the_canary(halts)
        first = store.sweep()
        second = store.sweep()
        assert first is not None and second is not None
        assert first.newly_marked_count == 2
        assert second.newly_marked_count == 0
        assert second.refused_score_ids == first.refused_score_ids
        assert len(second.already_marked) == 2
        assert all(not marker.changed for marker in second.already_marked)

    def test_the_sweep_reports_the_window_it_applied(
        self, store: CanaryVoidMarkerStore, halts: CanaryHaltStore
    ) -> None:
        store.ensure_schema()
        _seed_score(store, produced_at=AFTER_BREAK)
        _break_the_canary(halts)
        sweep = store.sweep()
        assert isinstance(sweep, VoidSweep)
        assert sweep.window.detected_at == DETECTED_AT
        assert sweep.window.alert_kind == DETERMINISM_BROKEN

    def test_an_empty_pool_sweeps_to_an_empty_account(
        self, store: CanaryVoidMarkerStore, halts: CanaryHaltStore
    ) -> None:
        # A break with nothing produced after it: the window exists, and it
        # refused nothing — a real answer, and the one that must not be
        # confused with ``None``.
        store.ensure_schema()
        _break_the_canary(halts)
        sweep = store.sweep()
        assert sweep is not None
        assert sweep.refused == ()
        assert sweep.pool_size == 0

    def test_the_sweep_reads_rows_oldest_first(
        self, store: CanaryVoidMarkerStore, halts: CanaryHaltStore
    ) -> None:
        # A deterministic account: the report of a voided window reads in
        # production order so two nights' reports can be compared.
        store.ensure_schema()
        third = _seed_score(store, produced_at=AFTER_BREAK + timedelta(hours=2))
        first = _seed_score(store, produced_at=AFTER_BREAK)
        second = _seed_score(store, produced_at=AFTER_BREAK + timedelta(hours=1))
        _break_the_canary(halts)
        sweep = store.sweep()
        assert sweep is not None
        assert sweep.refused_score_ids == (first, second, third)


# -- The refusal ------------------------------------------------------------------


class TestAMarkerCitesABreakOrItIsRefused:
    def test_marking_with_no_break_on_record_is_refused(
        self, store: CanaryVoidMarkerStore
    ) -> None:
        # Feature 144 voids scores *after a detected determinism break*.  A
        # marker written with no break behind it would taint good data against
        # a canary that held — the one thing this feature must never do.
        store.ensure_schema()
        with pytest.raises(CanaryVoidMarkerError) as caught:
            store.mark(uuid.uuid4(), AFTER_BREAK)
        assert "no determinism break is on record" in str(caught.value)
        assert store.markers() == ()

    def test_marking_a_score_before_the_break_is_refused(
        self, store: CanaryVoidMarkerStore, halts: CanaryHaltStore
    ) -> None:
        # A score that predates the break is not in the window: the break did
        # not touch it, and marking it would refuse good data.
        store.ensure_schema()
        score_id = _seed_score(store, produced_at=BEFORE_BREAK)
        _break_the_canary(halts)
        with pytest.raises(CanaryVoidMarkerError) as caught:
            store.mark(score_id, BEFORE_BREAK)
        assert "not after the determinism break" in str(caught.value)
        assert store.markers() == ()

    def test_marking_a_score_at_the_edge_is_refused(
        self, store: CanaryVoidMarkerStore, halts: CanaryHaltStore
    ) -> None:
        # Strict: the score produced *as* the break was not produced after it.
        store.ensure_schema()
        _break_the_canary(halts)
        with pytest.raises(CanaryVoidMarkerError):
            store.mark(uuid.uuid4(), DETECTED_AT)

    def test_marking_a_score_after_the_break_is_persisted(
        self, store: CanaryVoidMarkerStore, halts: CanaryHaltStore
    ) -> None:
        store.ensure_schema()
        score_id = _seed_score(store, produced_at=AFTER_BREAK)
        _break_the_canary(halts)
        marker = store.mark(score_id, AFTER_BREAK)
        assert isinstance(marker, VoidMarker)
        assert marker.changed
        assert marker.status == VOID_STATUS
        assert marker.alert_kind == DETERMINISM_BROKEN
        assert marker.detected_at == DETECTED_AT
        assert store.voided(score_id)

    def test_a_malformed_score_id_is_refused(
        self, store: CanaryVoidMarkerStore, halts: CanaryHaltStore
    ) -> None:
        # A marker keyed by something that cannot join the pool's key is a
        # taint on no row: the caller would be told a score was voided while
        # the pool went on serving it.
        store.ensure_schema()
        _break_the_canary(halts)
        for bad in ("", "   ", "not-a-uuid", None, 17):
            with pytest.raises(CanaryVoidMarkerError):
                store.mark(bad, AFTER_BREAK)

    def test_a_naive_produced_at_is_refused(
        self, store: CanaryVoidMarkerStore, halts: CanaryHaltStore
    ) -> None:
        store.ensure_schema()
        _break_the_canary(halts)
        with pytest.raises(CanaryVoidMarkerError):
            store.mark(uuid.uuid4(), datetime(2025, 6, 1, 3, 0, 1))

    def test_a_uuid_object_and_its_text_spelling_are_one_key(
        self, store: CanaryVoidMarkerStore, halts: CanaryHaltStore
    ) -> None:
        # Canonicalization: the value joins a UUID primary key, and a
        # mixed-case or braced spelling of one score would read as two — so a
        # re-sweep would write a second marker for a score already marked.
        store.ensure_schema()
        identity = uuid.uuid4()
        _break_the_canary(halts)
        first = store.mark(identity, AFTER_BREAK)
        second = store.mark(str(identity).upper(), AFTER_BREAK)
        assert first.score_id == second.score_id
        assert second.changed is False

    def test_a_re_marking_returns_the_stored_record(
        self, store: CanaryVoidMarkerStore, halts: CanaryHaltStore
    ) -> None:
        # First write wins: the stored record — not the new observation — is
        # what the caller gets back, so a re-sweep does not read as a new
        # refusal.
        store.ensure_schema()
        score_id = _seed_score(store, produced_at=AFTER_BREAK)
        _break_the_canary(halts)
        first = store.mark(score_id, AFTER_BREAK, marked_at=DETECTED_AT + timedelta(minutes=1))
        second = store.mark(score_id, AFTER_BREAK, marked_at=DETECTED_AT + timedelta(days=1))
        assert second.changed is False
        assert second.marked_at == first.marked_at


# -- The reads --------------------------------------------------------------------


class TestTheRefusalIsDerivedNotJustMarked:
    def test_a_score_after_the_break_is_refused_before_any_sweep(
        self, store: CanaryVoidMarkerStore, halts: CanaryHaltStore
    ) -> None:
        # The lag hole: a design that refused only what a sweep had already
        # marked would serve a bad score for as long as the nightly sweep was
        # late — exactly the window §12 says nobody notices.
        store.ensure_schema()
        score_id = _seed_score(store, produced_at=AFTER_BREAK)
        _break_the_canary(halts)
        assert not store.voided(score_id)  # no marker written yet
        assert store.unvoided_scores() == ()  # ...and it is still refused
        with pytest.raises(CanaryVoidMarkerError) as caught:
            store.require_score_usable(score_id)
        assert "no marker has been written" in str(caught.value)

    def test_unvoided_scores_is_the_refusal_applied_for_the_caller(
        self, store: CanaryVoidMarkerStore, halts: CanaryHaltStore
    ) -> None:
        store.ensure_schema()
        before = _seed_score(store, produced_at=BEFORE_BREAK)
        _seed_score(store, produced_at=AFTER_BREAK)
        _break_the_canary(halts)
        survivors = store.unvoided_scores()
        assert [row["id"] for row in survivors] == [before]

    def test_every_score_survives_a_canary_that_held(
        self, store: CanaryVoidMarkerStore
    ) -> None:
        store.ensure_schema()
        _seed_score(store, produced_at=BEFORE_BREAK)
        _seed_score(store, produced_at=AFTER_BREAK)
        assert len(store.unvoided_scores()) == 2

    def test_the_guard_passes_a_score_outside_the_window(
        self, store: CanaryVoidMarkerStore, halts: CanaryHaltStore
    ) -> None:
        store.ensure_schema()
        before = _seed_score(store, produced_at=BEFORE_BREAK)
        _break_the_canary(halts)
        assert store.require_score_usable(before) is None

    def test_the_guard_refuses_a_marked_score_and_carries_the_record(
        self, store: CanaryVoidMarkerStore, halts: CanaryHaltStore
    ) -> None:
        # A caller that aggregates a void score has not been told it was fine;
        # it has skipped the one door this feature leaves open.
        store.ensure_schema()
        score_id = _seed_score(store, produced_at=AFTER_BREAK)
        _break_the_canary(halts)
        store.sweep()
        with pytest.raises(CanaryVoidMarkerError) as caught:
            store.require_score_usable(score_id)
        marker = caught.value.args[1]
        assert isinstance(marker, VoidMarker)
        assert marker.score_id == score_id
        assert VOID_STATUS in str(caught.value)

    def test_the_guard_passes_an_unknown_score(
        self, store: CanaryVoidMarkerStore, halts: CanaryHaltStore
    ) -> None:
        # An id naming no pool row carries no taint: refusing it would be this
        # feature indicting a row it never saw.
        store.ensure_schema()
        _break_the_canary(halts)
        assert store.require_score_usable(uuid.uuid4()) is None

    def test_markers_read_back_oldest_first(
        self, store: CanaryVoidMarkerStore, halts: CanaryHaltStore
    ) -> None:
        store.ensure_schema()
        _seed_score(store, produced_at=AFTER_BREAK + timedelta(hours=2))
        _seed_score(store, produced_at=AFTER_BREAK)
        _seed_score(store, produced_at=AFTER_BREAK + timedelta(hours=1))
        _break_the_canary(halts)
        store.sweep()
        produced = [marker.produced_at for marker in store.markers()]
        assert produced == sorted(produced)
        assert all(not marker.changed for marker in store.markers())

    def test_voided_answers_the_marker_question_not_the_window_question(
        self, store: CanaryVoidMarkerStore, halts: CanaryHaltStore
    ) -> None:
        # The two are deliberately distinct: keeping them apart is what lets an
        # operator see the difference between a sweep that has run and one that
        # has not.
        store.ensure_schema()
        score_id = _seed_score(store, produced_at=AFTER_BREAK)
        _break_the_canary(halts)
        assert not store.voided(score_id)
        store.sweep()
        assert store.voided(score_id)


# -- The record -------------------------------------------------------------------


class TestTheMarkerIsAValidatedRecord:
    def _marker(self, **overrides: object) -> VoidMarker:
        fields: dict[str, object] = {
            "score_id": str(uuid.uuid4()),
            "produced_at": AFTER_BREAK,
            "detected_at": DETECTED_AT,
            "code_hash": "ab" * 32,
            "tree_hash": "cd" * 32,
            "alert_kind": DETERMINISM_BROKEN,
            "status": VOID_STATUS,
            "marked_at": AFTER_BREAK,
            "changed": True,
        }
        fields.update(overrides)
        return VoidMarker(**fields)  # type: ignore[arg-type]

    def test_a_well_formed_marker_summarises_itself(self) -> None:
        marker = self._marker()
        assert marker.status in marker.summary
        assert marker.score_id in marker.summary
        assert marker.code_hash in marker.summary

    def test_a_marker_whose_produced_at_is_not_after_its_edge_is_refused(self) -> None:
        # A row edited outside this package fails to reconstruct rather than
        # loading as a plausible-looking taint: what downstream trusts is the
        # stored record.
        with pytest.raises(CanaryVoidMarkerError):
            self._marker(produced_at=DETECTED_AT)
        with pytest.raises(CanaryVoidMarkerError):
            self._marker(produced_at=BEFORE_BREAK)

    def test_a_marker_naming_a_hash_of_the_wrong_shape_is_refused(self) -> None:
        for bad in ("ab", "AB" * 32, "zz" * 32, 17):
            with pytest.raises(CanaryVoidMarkerError):
                self._marker(code_hash=bad)

    def test_a_marker_carrying_another_verdict_is_refused(self) -> None:
        # The workspace spells this verdict one way, and a marker carrying any
        # other word is a row no reader of VOID could find.
        with pytest.raises(CanaryVoidMarkerError):
            self._marker(status="void")
        with pytest.raises(CanaryVoidMarkerError):
            self._marker(alert_kind="tripwire")

    def test_a_tampered_row_fails_to_reconstruct(
        self, store: CanaryVoidMarkerStore, halts: CanaryHaltStore
    ) -> None:
        # The read path re-validates, so a row edited in the database — here,
        # an edge moved after its own score — raises rather than loading as a
        # plausible-looking taint.
        store.ensure_schema()
        score_id = _seed_score(store, produced_at=AFTER_BREAK)
        _break_the_canary(halts)
        store.mark(score_id, AFTER_BREAK)
        with sqlite3.connect(store.path) as connection:
            connection.execute(
                f"UPDATE {VOID_TABLE} SET detected_at = ? WHERE score_id = ?",
                ((AFTER_BREAK + timedelta(days=1)).isoformat(), score_id),
            )
        with pytest.raises(CanaryVoidMarkerError):
            store.markers()

    def test_the_payload_round_trips_its_own_instants(self) -> None:
        payload = self._marker().to_payload()
        assert payload["status"] == VOID_STATUS
        assert datetime.fromisoformat(payload["produced_at"]) == AFTER_BREAK
        assert payload["changed"] is True


class TestTheSweepIsAValidatedAccount:
    def test_a_sweep_refusing_a_row_outside_its_window_is_refused(
        self, store: CanaryVoidMarkerStore, halts: CanaryHaltStore
    ) -> None:
        # An account disagreeing with its own window would refuse a score the
        # break did not touch — the direction that matters.  The marker itself
        # is well-formed (its own edge is earlier still, so its ``produced_at``
        # *is* after it); what the sweep refuses is the pairing.
        store.ensure_schema()
        _break_the_canary(halts)
        window = store.window()
        assert window is not None
        outside = VoidMarker(
            score_id=str(uuid.uuid4()),
            produced_at=BEFORE_BREAK,
            detected_at=BEFORE_BREAK - timedelta(hours=1),
            code_hash="ab" * 32,
            tree_hash="cd" * 32,
            alert_kind=DETERMINISM_BROKEN,
            status=VOID_STATUS,
            marked_at=AFTER_BREAK,
            changed=True,
        )
        assert not window.contains(outside.produced_at)
        with pytest.raises(CanaryVoidMarkerError):
            VoidSweep(
                window=window,
                marked=(),
                already_marked=(),
                refused=(outside,),
                pool_size=1,
            )

    def test_a_sweep_whose_parts_disagree_with_its_whole_is_refused(
        self, store: CanaryVoidMarkerStore, halts: CanaryHaltStore
    ) -> None:
        store.ensure_schema()
        _seed_score(store, produced_at=AFTER_BREAK)
        _break_the_canary(halts)
        window = store.window()
        assert window is not None
        marker = VoidMarker(
            score_id=str(uuid.uuid4()),
            produced_at=AFTER_BREAK,
            detected_at=DETECTED_AT,
            code_hash="ab" * 32,
            tree_hash="cd" * 32,
            alert_kind=DETERMINISM_BROKEN,
            status=VOID_STATUS,
            marked_at=AFTER_BREAK,
            changed=True,
        )
        with pytest.raises(CanaryVoidMarkerError):
            VoidSweep(
                window=window,
                marked=(marker,),
                already_marked=(),
                refused=(),
                pool_size=1,
            )

    def test_a_sweep_refusing_more_than_the_pool_holds_is_refused(
        self, store: CanaryVoidMarkerStore, halts: CanaryHaltStore
    ) -> None:
        store.ensure_schema()
        _break_the_canary(halts)
        window = store.window()
        assert window is not None
        marker = VoidMarker(
            score_id=str(uuid.uuid4()),
            produced_at=AFTER_BREAK,
            detected_at=DETECTED_AT,
            code_hash="ab" * 32,
            tree_hash="cd" * 32,
            alert_kind=DETERMINISM_BROKEN,
            status=VOID_STATUS,
            marked_at=AFTER_BREAK,
            changed=True,
        )
        with pytest.raises(CanaryVoidMarkerError):
            VoidSweep(
                window=window,
                marked=(marker,),
                already_marked=(),
                refused=(marker,),
                pool_size=0,
            )


# -- The store's contract ---------------------------------------------------------


class TestTheStoreStatesItsOwnContract:
    def test_construction_touches_no_disk(self, tmp_path: Path) -> None:
        # Composition-time work must not open a database: the factory builds
        # every registered component on every create_app().
        path = tmp_path / "never-created.db"
        store = CanaryVoidMarkerStore(f"sqlite:///{path}")
        assert store.path == path
        assert not path.exists()

    def test_an_empty_database_url_is_refused(self) -> None:
        with pytest.raises(CanaryVoidMarkerError):
            CanaryVoidMarkerStore("")
        with pytest.raises(CanaryVoidMarkerError):
            CanaryVoidMarkerStore("   ")

    def test_a_non_sqlite_scheme_is_refused_by_name(self) -> None:
        store = CanaryVoidMarkerStore("postgresql://localhost/nullius")
        with pytest.raises(CanaryVoidMarkerError) as caught:
            store.window()
        assert "postgresql" in str(caught.value)

    def test_an_in_memory_url_is_refused(self) -> None:
        # A marker written to an in-memory database is gone the moment the
        # caller looks: a score that reads as void while the pool goes on
        # serving it.
        store = CanaryVoidMarkerStore("sqlite:///:memory:")
        with pytest.raises(CanaryVoidMarkerError) as caught:
            store.window()
        assert "in-memory" in str(caught.value)

    def test_a_halt_store_on_another_database_is_refused(
        self, store: CanaryVoidMarkerStore, tmp_path: Path
    ) -> None:
        # A window opened on another database's break would void the wrong
        # scores — or none — while the record showed the deployment halted.
        other = CanaryHaltStore(f"sqlite:///{tmp_path / 'other.db'}")
        pointing_elsewhere = CanaryVoidMarkerStore(
            store.database_url, halt_store=other
        )
        with pytest.raises(CanaryVoidMarkerError):
            pointing_elsewhere.window()

    def test_ensure_schema_creates_both_shapes_idempotently(
        self, test_database_url: str
    ) -> None:
        store = CanaryVoidMarkerStore(test_database_url)
        store.ensure_schema()
        store.ensure_schema()
        with sqlite3.connect(store.path) as connection:
            names = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
        assert {"replay_score", VOID_TABLE, "canary_dream_halt"} <= names

    def test_resolve_reads_the_environment(self, tmp_path: Path) -> None:
        assert CanaryVoidMarkerStore.resolve({}) is None
        assert CanaryVoidMarkerStore.resolve({"DATABASE_URL": "  "}) is None
        resolved = CanaryVoidMarkerStore.resolve(
            {"DATABASE_URL": f"sqlite:///{tmp_path / 'r.db'}"}
        )
        assert resolved is not None
        assert resolved.path == tmp_path / "r.db"


# -- The module-level spellings ---------------------------------------------------


class TestTheModuleLevelSpellings:
    def test_the_sweep_refuses_by_name_when_no_store_is_named(self) -> None:
        # A voiding that silently went nowhere would leave the pool serving
        # exactly the scores this feature refuses — the failure mode this whole
        # feature exists to rule out.
        with pytest.raises(CanaryVoidMarkerError) as caught:
            void_scores_after_break(env={})
        assert "DATABASE_URL" in str(caught.value)

    def test_the_read_refuses_by_name_when_no_store_is_named(self) -> None:
        # An unconfigured deployment is not the same fact as one whose canary
        # held.
        with pytest.raises(CanaryVoidMarkerError):
            unvoided_scores(env={})

    def test_the_explicit_mark_refuses_by_name_when_no_store_is_named(self) -> None:
        with pytest.raises(CanaryVoidMarkerError):
            mark_void_score(uuid.uuid4(), AFTER_BREAK, env={})

    def test_the_guard_passes_vacuously_with_no_store(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # No relational store, no reference pair, no nightly canary, no break,
        # no window — the same "no store, no status" answer
        # ``require_dreaming_allowed`` gives.
        monkeypatch.delenv("DATABASE_URL", raising=False)
        assert require_score_usable(uuid.uuid4()) is None

    def test_the_sweep_through_the_module_level_spelling(
        self, store: CanaryVoidMarkerStore, halts: CanaryHaltStore
    ) -> None:
        store.ensure_schema()
        score_id = _seed_score(store, produced_at=AFTER_BREAK)
        _break_the_canary(halts)
        sweep = void_scores_after_break(database_url=store.database_url)
        assert sweep is not None
        assert sweep.refused_score_ids == (score_id,)
        assert unvoided_scores(database_url=store.database_url) == ()

    def test_the_sweep_through_the_environment(
        self, store: CanaryVoidMarkerStore, halts: CanaryHaltStore
    ) -> None:
        store.ensure_schema()
        _seed_score(store, produced_at=AFTER_BREAK)
        _break_the_canary(halts)
        sweep = void_scores_after_break(env={"DATABASE_URL": store.database_url})
        assert sweep is not None
        assert len(sweep.refused) == 1

    def test_a_held_canary_makes_the_module_level_sweep_a_quiet_return(
        self, store: CanaryVoidMarkerStore
    ) -> None:
        store.ensure_schema()
        _seed_score(store, produced_at=AFTER_BREAK)
        assert void_scores_after_break(env={"DATABASE_URL": store.database_url}) is None

    def test_the_marker_error_is_a_canary_error(self) -> None:
        # The package's single ``except`` still catches every failure of the
        # canary's assertions.
        assert issubclass(CanaryVoidMarkerError, CanaryError)

    def test_the_component_name_is_the_fourth_name(self) -> None:
        assert VOID_MARKER_COMPONENT_NAME == "canary-void-marker"
        assert VOID_TABLE == "canary_void_marker"
        assert VOID_STATUS == "VOID"
