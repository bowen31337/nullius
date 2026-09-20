"""The halt of dreaming on a determinism break — feature 143.

These tests pin :mod:`canary._halt` — the two statements under §12 line 677's
``if``: ``halt_dreaming()`` and ``alert(...)``.  The properties under test are
the ones the module docstring argues:

* the decision is §12's own — a result that broke under the one threshold the
  workspace spells once halts dreaming and emits the ``determinism_broken``
  alert; a result that did not break writes nothing, raises nothing, and
  dreaming continues — the untaken branch of the ``if`` is as much the feature
  as the taken one;
* the halt is a persisted state that survives the nightly run — written
  *before* the alert is raised, so a caller that catches the alert to keep
  reporting still leaves the halt on record — and the first break is the fact
  that stays, because feature 144's void markers key on the break's instant;
* the alert is a record before it is an error: :class:`DreamHalt` carries the
  pair, the arithmetic and the instants, validates them against themselves,
  and rides on the raised error as its payload;
* the halt is monotone — nothing writes a row away — and the guard
  (:meth:`CanaryHaltStore.require_dreaming_allowed`) is the read-time refusal
  the dreaming entrypoint consults, carrying the stored record;
* a halt is pronounced only under §12's own ``1e-12``, and only against the
  pair whose constant was the one on trial.

The pairs and results below are real, not mocks: the point of the feature is
that the halt is pronounced on the score a frozen pair actually replays to, so
every broken result is produced by :func:`canary.replay_pair` over a genuinely
frozen pair whose recorded constant the replayed score does not reach.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from canary import (
    DETERMINISM_BROKEN,
    HALT_MESSAGE,
    HALT_STORE_COMPONENT_NAME,
    HALT_TABLE,
    DEFAULT_TOLERANCE,
    CanaryDeterminismBrokenError,
    CanaryError,
    CanaryHaltStore,
    CanaryReferencePair,
    CanaryTree,
    DreamHalt,
    determinism_broken_error,
    halt_dreaming,
    replay_pair,
    require_dreaming_allowed,
)
from canary._reference import CanaryPolicy

POLICY_VERSION = "canary-v1"
DETECTED_AT = datetime(2025, 6, 1, 3, 0, 0, tzinfo=timezone.utc)
HALTED_AT = datetime(2025, 6, 1, 3, 0, 1, tzinfo=timezone.utc)


# -- Fixtures ------------------------------------------------------------------


def _policy(version: str = POLICY_VERSION) -> CanaryPolicy:
    return CanaryPolicy.freeze(
        version=version,
        policy={"scoring": {"weights": {"a": 0.5, "b": 0.5}}, "threshold": 0.7},
    )


def _tree() -> CanaryTree:
    # The same fixture tree ``test_replay`` scores: each node carries a
    # canonical ``score`` and, for the leaves, a ``weight``.
    return CanaryTree.freeze(
        {
            "root": (None, 0, {"label": "root", "kind": "decision", "score": 0.0}),
            "left": ("root", 1, {"label": "left", "weight": 0.3, "score": 0.8}),
            "right": ("root", 1, {"label": "right", "weight": 0.7, "score": 0.6}),
        }
    )


def _pair(*, recorded: float | None, created_at: datetime | None = None) -> CanaryReferencePair:
    return CanaryReferencePair(
        policy=_policy(),
        tree=_tree(),
        recorded_score=recorded,
        id=None,
        is_active=True,
        created_at=created_at or datetime(2025, 1, 1, tzinfo=timezone.utc),
    )


#: The score the fixture tree replays to (``test_replay`` spells the same
#: expectation): ``0.8 * 0.3 + 0.6 * 0.7``, the root contributing ``0.0``.
EXPECTED_SCORE = 0.8 * 0.3 + 0.6 * 0.7


def _broken_pair(offset: float = 0.5) -> CanaryReferencePair:
    # A pair whose recorded constant the replayed score misses by ``offset`` —
    # a deviation §12's ``1e-12`` cannot forgive.
    return _pair(recorded=EXPECTED_SCORE + offset)


def _halt(**overrides: object) -> DreamHalt:
    # A well-formed hand-built halt, for the record's own validation tests.
    # Hand-built only where the test is *about* the record; every test about
    # the decision or the store goes through ``replay_pair``.
    fields: dict[str, object] = {
        "code_hash": "ab" * 32,
        "tree_hash": "cd" * 32,
        "alert_kind": DETERMINISM_BROKEN,
        "score": 1.5,
        "recorded_score": 1.0,
        "deviation": 0.5,
        "tolerance": DEFAULT_TOLERANCE,
        "detected_at": DETECTED_AT,
        "halted_at": HALTED_AT,
        "changed": True,
    }
    fields.update(overrides)
    return DreamHalt(**fields)  # type: ignore[arg-type]


@pytest.fixture
def store(test_database_url: str) -> CanaryHaltStore:
    """A halt store pointed at the per-test database."""
    return CanaryHaltStore(test_database_url)


# -- The decision: §12's two statements under the if ---------------------------


class TestHaltDreamingDecides:
    def test_a_broken_result_halts_and_emits(self, store: CanaryHaltStore) -> None:
        # §12's two statements, one call: the break is persisted (dreaming is
        # halted from the record on) and the alert is raised — in that order.
        pair = _broken_pair()
        result = replay_pair(pair)
        assert result.broken
        with pytest.raises(CanaryDeterminismBrokenError) as caught:
            halt_dreaming(pair, result, database_url=store.database_url)
        halt = caught.value.halt
        assert isinstance(halt, DreamHalt)
        assert halt.score == result.score
        assert halt.recorded_score == result.recorded_score
        assert halt.deviation == result.deviation
        assert halt.tolerance == DEFAULT_TOLERANCE
        assert halt.code_hash == pair.policy.code_hash
        assert halt.tree_hash == pair.tree.tree_hash
        assert store.halted()

    def test_the_row_is_written_before_the_alert_is_raised(
        self, store: CanaryHaltStore
    ) -> None:
        # A monitor that catches the alert to keep reporting (every pair, then
        # one page) still leaves the halt on record: the persist happens
        # before the raise, so catching the emission cannot un-halt dreaming.
        pair = _broken_pair()
        result = replay_pair(pair)
        with pytest.raises(CanaryDeterminismBrokenError):
            halt_dreaming(pair, result, database_url=store.database_url)
        assert store.halted()
        assert store.current_halt() is not None

    def test_a_passing_result_writes_nothing_and_raises_nothing(
        self, store: CanaryHaltStore
    ) -> None:
        # The untaken branch of line 677's ``if``: a nightly runner whose
        # canary held observes a quiet return, and the store stays empty.
        pair = _pair(recorded=EXPECTED_SCORE)
        result = replay_pair(pair)
        assert not result.broken
        assert (
            halt_dreaming(pair, result, database_url=store.database_url) is None
        )
        assert not store.halted()
        assert store.current_halt() is None

    def test_a_pair_not_yet_replayed_never_halts(self, store: CanaryHaltStore) -> None:
        # ``recorded_score`` is ``None`` — the first night records the
        # constant rather than breaking against one that does not exist.
        pair = _pair(recorded=None)
        result = replay_pair(pair)
        assert not result.broken
        assert (
            halt_dreaming(pair, result, database_url=store.database_url) is None
        )
        assert not store.halted()

    def test_nothing_names_a_store_is_refused_by_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A halt that quietly skipped its write would leave dreaming running
        # while the nightly runner believed it had stopped it — the failure
        # mode the feature exists to rule out, refused here by name.
        monkeypatch.delenv("DATABASE_URL", raising=False)
        pair = _broken_pair()
        result = replay_pair(pair)
        with pytest.raises(CanaryError, match="DATABASE_URL is unset") as caught:
            halt_dreaming(pair, result)
        # The refusal is a store-contract failure, not the alert: the break
        # has not been recorded, so the alert is not emitted either.
        assert not isinstance(caught.value, CanaryDeterminismBrokenError)

    def test_a_result_under_a_widened_tolerance_is_refused(
        self, store: CanaryHaltStore
    ) -> None:
        # §12's determinism-break row: widening the canary tolerance is never
        # the fix.  A result measured under any other band — wider or
        # narrower — is a comparison §12 never wrote, and the halt is refused.
        pair = _broken_pair(offset=3.0)
        result = replay_pair(pair, tolerance=2.0)
        assert result.broken  # ...but under a band line 677 did not write
        with pytest.raises(CanaryError, match="1e-12") as caught:
            halt_dreaming(pair, result, database_url=store.database_url)
        assert not isinstance(caught.value, CanaryDeterminismBrokenError)
        assert not store.halted()

    def test_a_result_under_a_narrowed_tolerance_is_refused(
        self, store: CanaryHaltStore
    ) -> None:
        # The refusal is symmetric: a zero tolerance would halt dreaming on a
        # deviation §12's own line forgives, and that is as much a §12 line
        # nobody wrote as the widened band above.
        pair = _broken_pair(offset=1e-9)
        result = replay_pair(pair, tolerance=0.0)
        assert result.broken
        with pytest.raises(CanaryError, match="never the fix"):
            halt_dreaming(pair, result, database_url=store.database_url)
        assert not store.halted()

    def test_a_result_compared_against_another_pairs_constant_is_refused(
        self, store: CanaryHaltStore
    ) -> None:
        # The halt is attributed to a pair, and the constant on trial must be
        # the one that pair carries — otherwise the break indicts a reference
        # whose constant was never the one compared.
        passing_pair = _pair(recorded=EXPECTED_SCORE)
        broken_result = replay_pair(_broken_pair())
        with pytest.raises(CanaryError, match="is not the pair's own"):
            halt_dreaming(
                passing_pair, broken_result, database_url=store.database_url
            )
        assert not store.halted()

    def test_the_environment_names_the_store(self, store: CanaryHaltStore) -> None:
        # ``halt_dreaming`` resolves ``DATABASE_URL`` the same way every
        # store in the workspace does, so a deployment's one variable names
        # every store alike.
        pair = _broken_pair()
        result = replay_pair(pair)
        with pytest.raises(CanaryDeterminismBrokenError):
            halt_dreaming(pair, result, env={"DATABASE_URL": store.database_url})


# -- The record: the halt is a fact that must survive its own writing ----------


class TestDreamHaltValidatesItself:
    def test_the_record_carries_both_halves_of_the_feature(self) -> None:
        # The state (a pair is halted, from ``detected_at`` on) and the alert
        # (the spec's own kind word) travel on one record, so the page an
        # operator reads and the row the store holds cannot disagree.
        halt = _halt()
        assert halt.alert_kind == DETERMINISM_BROKEN
        assert halt.changed is True
        assert halt.detected_at == DETECTED_AT
        assert halt.halted_at == HALTED_AT

    def test_the_hashes_must_be_canonical_sha256_hex(self) -> None:
        # The row is keyed by the pair's content fingerprint, and a hash of
        # the wrong width names no pair an operator could bisect.
        with pytest.raises(CanaryError, match="64-character hex digest"):
            _halt(code_hash="ab")

    def test_the_alert_kind_is_the_specs_own_word(self) -> None:
        with pytest.raises(CanaryError, match="determinism_broken"):
            _halt(alert_kind="canary_drifted")

    def test_a_non_finite_term_is_refused(self) -> None:
        # §12's comparison is False for a NaN, so a NaN is a broken reference
        # rather than a break — it must not reach the halt record dressed as
        # the arithmetic the decision was made on.
        with pytest.raises(CanaryError, match="not finite"):
            _halt(score=float("nan"), recorded_score=1.0, deviation=float("nan"))

    def test_the_deviation_must_be_the_records_own_arithmetic(self) -> None:
        # Re-derived at construction so a row edited outside this package
        # fails to reconstruct rather than loading as a plausible-looking break.
        with pytest.raises(CanaryError, match="does not equal"):
            _halt(deviation=0.4)

    def test_the_tolerance_is_section_12s_own(self) -> None:
        with pytest.raises(CanaryError, match="never the fix"):
            _halt(tolerance=1e-6)

    def test_a_deviation_at_the_band_is_not_a_break(self) -> None:
        # §12's line is strict: ``abs(score - CANARY_EXPECTED) > 1e-12``.  A
        # deviation *at* the tolerance is within it, and a halt pronounced
        # there would be a stop dreaming was never told to make.  The score
        # and constant are chosen so the difference is exactly the tolerance
        # as a double — the boundary itself, not a rounding of it.
        with pytest.raises(CanaryError, match="strict"):
            _halt(
                score=DEFAULT_TOLERANCE,
                recorded_score=0.0,
                deviation=DEFAULT_TOLERANCE,
            )

    def test_a_naive_instant_is_refused(self) -> None:
        with pytest.raises(CanaryError, match="timezone-aware"):
            _halt(detected_at=datetime(2025, 6, 1, 3, 0, 0))

    def test_changed_is_one_bit(self) -> None:
        with pytest.raises(CanaryError, match="changed must be a bool"):
            _halt(changed=1)  # type: ignore[arg-type]

    def test_the_payload_names_the_records_own_fields(self) -> None:
        halt = _halt()
        payload = halt.to_payload()
        assert set(payload) == {
            "code_hash",
            "tree_hash",
            "alert_kind",
            "score",
            "recorded_score",
            "deviation",
            "tolerance",
            "detected_at",
            "halted_at",
            "changed",
        }
        assert payload["alert_kind"] == DETERMINISM_BROKEN
        assert payload["detected_at"] == DETECTED_AT.isoformat()

    def test_the_summary_spells_the_pair_and_the_arithmetic(self) -> None:
        # "Which pair broke" is the first question §15's recovery asks, so
        # the summary names both hashes in full — an operator greps the
        # reference store by them straight off the page.
        halt = _halt()
        summary = halt.summary
        assert "ab" * 32 in summary
        assert "cd" * 32 in summary
        assert "1.5" in summary
        assert "1.0" in summary
        assert "0.5" in summary


# -- The store: the halt is persisted, monotone, and guarded --------------------


class TestTheStorePersistsTheHalt:
    def test_the_first_break_writes_the_row(self, store: CanaryHaltStore) -> None:
        pair = _broken_pair()
        result = replay_pair(pair)
        halt = store.halt(pair, result, detected_at=DETECTED_AT, halted_at=HALTED_AT)
        assert halt.changed is True
        assert halt.alert_kind == DETERMINISM_BROKEN

    def test_the_read_back_is_the_record_the_store_holds(
        self, store: CanaryHaltStore
    ) -> None:
        pair = _broken_pair()
        result = replay_pair(pair)
        written = store.halt(pair, result, detected_at=DETECTED_AT, halted_at=HALTED_AT)
        read = store.current_halt()
        assert read is not None
        assert read.code_hash == written.code_hash
        assert read.tree_hash == written.tree_hash
        assert read.score == written.score
        assert read.recorded_score == written.recorded_score
        assert read.deviation == written.deviation
        assert read.detected_at == written.detected_at
        assert read.changed is False  # a read wrote nothing

    def test_first_halt_answers_the_window_question_not_the_page_question(
        self, store: CanaryHaltStore
    ) -> None:
        # Two reads, two questions, and feature 144 turns on the difference:
        # ``current_halt`` answers the operator's *what is the halt in force?*
        # and returns the latest write, while ``first_halt`` answers *when did
        # this deployment's determinism break?* and returns the earliest.  A
        # window keyed on the latest would let a second break on another pair
        # pull its boundary forward and quietly shrink the set of scores the
        # system refuses — bad data aging into good data.
        first_pair = _broken_pair(offset=0.5)
        second_pair = CanaryReferencePair(
            policy=CanaryPolicy.freeze(
                version="canary-v2",
                policy={"scoring": {"weights": {"a": 0.25, "b": 0.75}}},
            ),
            tree=_tree(),
            recorded_score=EXPECTED_SCORE - 0.25,
            id=None,
            is_active=True,
            created_at=datetime(2025, 1, 2, tzinfo=timezone.utc),
        )
        assert second_pair.policy.code_hash != first_pair.policy.code_hash
        # Written *latest* first, so neither read can agree with the other by
        # accident of insertion order.
        store.halt(
            second_pair,
            replay_pair(second_pair),
            detected_at=DETECTED_AT + timedelta(days=7),
            halted_at=HALTED_AT + timedelta(days=7),
        )
        store.halt(
            first_pair,
            replay_pair(first_pair),
            detected_at=DETECTED_AT,
            halted_at=HALTED_AT,
        )
        earliest = store.first_halt()
        latest = store.current_halt()
        assert earliest is not None and latest is not None
        assert earliest.detected_at == DETECTED_AT
        assert earliest.code_hash == first_pair.policy.code_hash
        assert latest.detected_at == DETECTED_AT + timedelta(days=7)
        assert earliest.changed is False  # a read wrote nothing

    def test_first_halt_is_none_when_nothing_has_broken(
        self, store: CanaryHaltStore
    ) -> None:
        # An empty store is not an empty window: ``None`` is how feature 144
        # tells "the canary held" from "the canary broke and nothing was
        # produced after it".
        assert store.first_halt() is None

    def test_a_later_observation_does_not_move_the_break(
        self, store: CanaryHaltStore
    ) -> None:
        # The *first* break is the fact on record: feature 144's void markers
        # key on ``detected_at`` ("every score produced after a detected
        # determinism break"), and a refresh that moved the instant forward
        # would quietly shrink the affected window.  The later observation
        # writes nothing and reports ``changed=False``.
        pair = _broken_pair()
        result = replay_pair(pair)
        first = store.halt(pair, result, detected_at=DETECTED_AT, halted_at=HALTED_AT)
        later = store.halt(
            pair,
            result,
            detected_at=DETECTED_AT + timedelta(days=1),
            halted_at=HALTED_AT + timedelta(days=1),
        )
        assert later.changed is False
        assert later.detected_at == first.detected_at
        assert later.halted_at == first.halted_at
        assert store.current_halt().detected_at == DETECTED_AT

    def test_a_second_pair_breaking_writes_a_second_row(
        self, store: CanaryHaltStore
    ) -> None:
        # The audit holds every break; the state stays the plain §12 reading
        # — any break on record, dreaming halted.  The second pair varies its
        # policy *content* — the content hash covers the canonical policy
        # bytes, not the version label — so its fingerprint is its own.
        first_pair = _broken_pair(offset=0.5)
        second_pair = CanaryReferencePair(
            policy=CanaryPolicy.freeze(
                version="canary-v2",
                policy={"scoring": {"weights": {"a": 0.25, "b": 0.75}}},
            ),
            tree=_tree(),
            recorded_score=EXPECTED_SCORE - 0.25,
            id=None,
            is_active=True,
            created_at=datetime(2025, 1, 2, tzinfo=timezone.utc),
        )
        assert second_pair.policy.code_hash != first_pair.policy.code_hash
        store.halt(
            first_pair,
            replay_pair(first_pair),
            detected_at=DETECTED_AT,
            halted_at=HALTED_AT,
        )
        store.halt(
            second_pair,
            replay_pair(second_pair),
            detected_at=DETECTED_AT + timedelta(hours=1),
            halted_at=HALTED_AT + timedelta(hours=1),
        )
        assert store.halted()
        current = store.current_halt()
        assert current is not None
        assert current.code_hash == second_pair.policy.code_hash

    def test_a_row_edited_outside_the_package_fails_to_reconstruct(
        self, store: CanaryHaltStore
    ) -> None:
        # The read path re-derives the record's own arithmetic, so a tampered
        # row is refused rather than served as a plausible-looking break.
        pair = _broken_pair()
        store.halt(pair, replay_pair(pair), detected_at=DETECTED_AT, halted_at=HALTED_AT)
        with sqlite3.connect(store.path) as connection:
            connection.execute(
                f"UPDATE {HALT_TABLE} SET deviation = deviation / 2"
            )
        with pytest.raises(CanaryError, match="does not equal"):
            store.current_halt()

    def test_a_passing_result_is_refused_at_the_explicit_door(
        self, store: CanaryHaltStore
    ) -> None:
        # The store's ``halt`` is the "write this break down" door, and — like
        # the poison store for a verdict that passed — it accepts no passing
        # result: a store that did would halt dreaming on a canary that held.
        pair = _pair(recorded=EXPECTED_SCORE)
        result = replay_pair(pair)
        with pytest.raises(CanaryError, match="nothing to halt on"):
            store.halt(pair, result)

    def test_the_door_takes_the_pair_and_the_result_by_type(
        self, store: CanaryHaltStore
    ) -> None:
        with pytest.raises(CanaryError, match="CanaryReferencePair"):
            store.halt("not a pair", replay_pair(_broken_pair()))
        with pytest.raises(CanaryError, match="CanaryReplayResult"):
            store.halt(_broken_pair(), "not a result")


class TestTheStoreResolvesLazily:
    def test_construction_touches_no_disk(self, tmp_path: Path) -> None:
        path = tmp_path / "never-created.db"
        CanaryHaltStore(f"sqlite:///{path}")
        assert not path.exists()

    def test_an_unsupported_scheme_is_refused_by_name(
        self, tmp_path: Path
    ) -> None:
        store = CanaryHaltStore(f"postgres:///{tmp_path / 'x.db'}")
        with pytest.raises(CanaryError, match="speaks sqlite"):
            store.halt(_broken_pair(), replay_pair(_broken_pair()))

    def test_an_in_memory_url_is_refused(self) -> None:
        store = CanaryHaltStore("sqlite:///:memory:")
        with pytest.raises(CanaryError, match="in-memory"):
            store.halt(_broken_pair(), replay_pair(_broken_pair()))

    def test_resolve_answers_none_for_an_unnamed_store(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        assert CanaryHaltStore.resolve() is None
        assert CanaryHaltStore.resolve({}) is None

    def test_resolve_reads_the_environment_it_is_given(self) -> None:
        store = CanaryHaltStore.resolve({"DATABASE_URL": "sqlite:///given.db"})
        assert store is not None
        assert store.database_url == "sqlite:///given.db"


# -- The guard: the read-time refusal the dreaming entrypoint consults ----------


class TestTheGuard:
    def test_an_empty_store_allows_dreaming(self, store: CanaryHaltStore) -> None:
        store.require_dreaming_allowed()  # passes: nothing to refuse on
        assert store.halted() is False

    def test_a_halted_store_refuses_and_carries_the_record(
        self, store: CanaryHaltStore
    ) -> None:
        pair = _broken_pair()
        store.halt(pair, replay_pair(pair), detected_at=DETECTED_AT, halted_at=HALTED_AT)
        with pytest.raises(CanaryDeterminismBrokenError) as caught:
            store.require_dreaming_allowed()
        halt = caught.value.halt
        assert isinstance(halt, DreamHalt)
        assert halt.code_hash == pair.policy.code_hash
        assert halt.detected_at == DETECTED_AT

    def test_the_module_level_guard_opens_its_own_store(
        self, store: CanaryHaltStore
    ) -> None:
        pair = _broken_pair()
        with pytest.raises(CanaryDeterminismBrokenError):
            halt_dreaming(
                pair,
                replay_pair(pair),
                database_url=store.database_url,
                detected_at=DETECTED_AT,
            )
        with pytest.raises(CanaryDeterminismBrokenError, match="dreaming is halted"):
            require_dreaming_allowed(database_url=store.database_url)

    def test_an_unnamed_store_passes_vacuously(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # With no relational store there is no reference pair, no recorded
        # constant and no canary to break, so there is no halt this guard
        # could be holding — the "no store, no status" answer, kept distinct
        # from "checked and allowed".
        monkeypatch.delenv("DATABASE_URL", raising=False)
        require_dreaming_allowed()  # passes: nothing was ever recorded


# -- The alert: raising is the emission, the record is the payload --------------


class TestTheAlert:
    def test_the_alert_is_a_canary_failure(self) -> None:
        # A subclass of CanaryError, so the package's single ``except`` catches
        # every failure of the canary's assertions — this one included.
        assert issubclass(CanaryDeterminismBrokenError, CanaryError)

    def test_the_emission_carries_section_12s_own_words(
        self, store: CanaryHaltStore
    ) -> None:
        # §12 line 681's alert text, verbatim, so an operator reading a stack
        # trace reads the same words the architecture spells.
        pair = _broken_pair()
        with pytest.raises(CanaryDeterminismBrokenError, match=HALT_MESSAGE):
            halt_dreaming(
                pair, replay_pair(pair), database_url=store.database_url
            )

    def test_the_emission_names_the_recovery(self, store: CanaryHaltStore) -> None:
        # §15's recovery row is the operator's next step, and the page says
        # so: the reader is deciding what to do at three in the morning.
        pair = _broken_pair()
        with pytest.raises(
            CanaryDeterminismBrokenError, match="bisect the image diff"
        ):
            halt_dreaming(
                pair, replay_pair(pair), database_url=store.database_url
            )

    def test_the_builder_composes_the_message_from_the_record(self) -> None:
        halt = _halt()
        error = determinism_broken_error(halt)
        assert error.halt is halt
        assert HALT_MESSAGE in str(error)
        assert halt.summary in str(error)

    def test_the_builder_takes_a_record_and_nothing_else(self) -> None:
        with pytest.raises(CanaryError, match="takes a DreamHalt"):
            determinism_broken_error("not a halt")  # type: ignore[arg-type]

    def test_a_hand_built_error_carries_no_record(self) -> None:
        error = CanaryDeterminismBrokenError("hand built")
        assert error.halt is None


# -- The component name: one spelling, three places -----------------------------


class TestTheComponentName:
    def test_the_store_component_name_is_spelled_once_here(self) -> None:
        # The member's registration name, the store's constant and the app
        # seat's constant must agree; this suite pins the member's spelling
        # and ``test_app_module`` pins the seat's against it.
        assert HALT_STORE_COMPONENT_NAME == "canary-dream-halt"

    def test_the_table_is_the_members_own(self) -> None:
        # A member-owned table beside the only code that reads it — the same
        # stance the poison store takes for its audit rows.
        assert HALT_TABLE == "canary_dream_halt"
