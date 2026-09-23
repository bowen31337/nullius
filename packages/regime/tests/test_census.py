"""Feature 290's act: each stored world assigned a stratum, causally.

app_spec.xml, "Regime Coverage Strata", feature 290: *System rejects a
full-history regime fit, assigning each stored world to a stratum with
the causal rolling-window labeler.*  The PRD's leakage table
(docs/alpha-engine-prd.md, "regime labeler") is the law the first
clause enforces — *"Rolling-window fit only.  Fitting an HMM on full
history and then finding that signal X works in regime 2 is leakage,
because regime 2 was labeled with future data"* — and §C7 is why the
second clause matters: the count this census writes is the count the
promotion gate blocks on, so a stratum carved with the pool's own
future in view would make the coverage number itself leakage.

These tests pin the census against **stand-ins** for the two things it
duck-reads — a labeler that answers a deterministic pattern, worlds
that carry small dated rows — because the census's own subject is the
*seam*, not the clustering: whether the fit span is stated and finite,
whether it is strictly shorter than each world's series, whether the
vocabulary and the label space agree, whether every world is binned
exactly once.  The real labeler is this member's sibling
(:mod:`feature_store.regime_labeler`, feature 58) and no member imports
another; the suite that pins the two against each other — the real
labeler through this census, this member's refusal against the
labeler's own — is ``test_cross_member.py``, which these tests leave to
it.

The four laws stated in the module's docstring that everything here
hangs off:

* **the fit is causal or refused** — a stated unbounded window and a
  window spanning a world's whole usable series are both the
  full-history fit, refused in this member's vocabulary (the code
  ``full_history_fit`` opens the message) *before the labeler is
  called*, so the refusal is never the labeler's own class;
* **one world, one stratum, the closing one** — the last dated row's
  label, the world's closing regime, never a whole-series aggregate;
* **the seam is duck-typed and asks only what it reads** — ``k``,
  ``window``, ``label_features`` off the labeler; ``world_id`` and
  ``regime_rows`` off the world — because the module loader serves the
  composed copies under synthetic names an ``isinstance`` gate would
  refuse;
* **validation is total before the first write** — a refused census
  leaves the ledger exactly as it was, and the only mid-census
  failures are the store's own, propagating unwrapped.
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote, urlparse

import pytest
from regime import (
    DEFAULT_STRATA,
    FULL_HISTORY_FIT_CODE,
    CoverageCount,
    CoverageError,
    RegimeCoverage,
    StratumAssignment,
    StratumAssignmentError,
    assign_strata,
    census_coverage,
)

# -- The stand-ins -----------------------------------------------------------------


class _Labeler:
    """A deterministic stand-in for the feature store's causal labeler.

    Carries exactly the surface the census duck-reads — ``k``,
    ``window``, ``label_features`` — and no more (``__slots__`` so a
    stray read of anything else fails loudly rather than finding an
    attribute that was never part of the seam).  Its labelling is a
    pattern the test can reason about: every dated row labelled
    ``opening`` except the last, which is labelled ``closing`` — the
    closing label is the one label the census keeps, so the stand-in
    makes it addressable directly.
    """

    __slots__ = ("closing", "k", "opening", "window")

    def __init__(
        self, *, k: int = 3, window: int = 2, opening: int = 0, closing: int = 1
    ) -> None:
        self.k = k
        self.window = window
        self.opening = opening
        self.closing = closing

    def label_features(self, rows):
        return tuple([self.opening] * (len(rows) - 1) + [self.closing])


class _World:
    """A stand-in stored world: the pool's identity and a dated history.

    ``__slots__`` again — the census may read ``world_id`` and
    ``regime_rows`` and nothing else, and slots are what makes a read of
    anything else an error rather than a silent ``None``.
    """

    __slots__ = ("regime_rows", "world_id")

    def __init__(self, world_id: str, rows) -> None:
        self.world_id = world_id
        self.regime_rows = rows


def _rows(n: int) -> tuple[tuple[float, ...], ...]:
    """``n`` dated feature rows — two features, deterministic, finite."""
    return tuple((float(i), float(i % 5) * 0.5) for i in range(n))


def _worlds(*specs: tuple[str, int]) -> list[_World]:
    """Stand-in worlds from ``(world_id, n_rows)`` pairs."""
    return [_World(world_id, _rows(n)) for world_id, n in specs]


class _RecordingStore:
    """A store that is not a ``RegimeCoverage`` — the duck-typing pin.

    Writes land in a list rather than a table, which is enough for the
    census: it calls ``record`` per named stratum and answers with what
    the store hands back, so a stand-in with no database at all proves
    the census holds no ``isinstance`` on the store it writes through —
    the synthetic-name stance, pinned by behaviour the way
    ``test_pool_component.py`` pins the composed pool.
    """

    def __init__(self) -> None:
        self.written: list[tuple[str, int]] = []

    def record(self, stratum, world_count):
        self.written.append((stratum, world_count))
        return SimpleNamespace(stratum=stratum, world_count=world_count)


def _path_of(database_url: str) -> Path:
    """The filesystem path behind a ``sqlite:///`` URL, for a raw read."""
    parsed = urlparse(database_url)
    return Path(unquote(parsed.path).removeprefix("/"))


def _raw_rows(database_url: str) -> list[tuple[object, ...]]:
    """Every ledger row, as a reader with no code in common with the
    member would read it — the instrument for "what actually landed"."""
    with closing(sqlite3.connect(_path_of(database_url))) as connection:
        cursor = connection.execute(
            "SELECT stratum, world_count FROM regime_coverage ORDER BY stratum"
        )
        try:
            return cursor.fetchall()
        finally:
            cursor.close()


# -- The assignment ----------------------------------------------------------------


class TestTheAssignment:
    """One world in, one named stratum out — the closing label's mapping."""

    def test_each_world_is_assigned_the_stratum_its_closing_label_names(
        self,
    ) -> None:
        # The one label the census keeps is the last dated row's: the
        # world's closing regime, judged by a trailing fit that saw
        # nothing after it.  Two worlds closing in different clusters
        # land in different strata, by the vocabulary's index.
        worlds = _worlds(("w-a", 5), ("w-b", 5))
        assigned = assign_strata(
            worlds, _Labeler(k=3, window=2, opening=0, closing=2)
        )
        assert assigned == (
            StratumAssignment(world_id="w-a", stratum=DEFAULT_STRATA[2]),
            StratumAssignment(world_id="w-b", stratum=DEFAULT_STRATA[2]),
        )

    def test_the_closing_label_not_the_opening_ones_names_the_stratum(
        self,
    ) -> None:
        # A world that spends its whole life in cluster 0 and closes in
        # cluster 1 is a cluster-1 world: the ledger counts worlds, not
        # world-days, and an aggregate over the whole series would be
        # the full-history smell the feature refuses.
        assigned = assign_strata(
            _worlds(("w", 6)), _Labeler(k=3, window=2, opening=0, closing=1)
        )
        assert assigned[0].stratum == DEFAULT_STRATA[1]

    def test_assignments_are_sorted_by_the_pools_own_order(self) -> None:
        # ``world_id`` is the pool's total order (the dreaming freeze's
        # commitment reads it, ``bootstrap_world`` keys it); the census
        # answers in it, so the value is a function of the set of
        # worlds rather than of the order they arrived in.
        assert assign_strata(
            _worlds(("w-c", 4), ("w-a", 4), ("w-b", 4)), _Labeler()
        ) == assign_strata(_worlds(("w-a", 4), ("w-b", 4), ("w-c", 4)), _Labeler())

    def test_every_world_is_assigned(self) -> None:
        worlds = _worlds(*[(f"w-{i}", 5) for i in range(7)])
        assigned = assign_strata(worlds, _Labeler())
        assert [assignment.world_id for assignment in assigned] == [
            f"w-{i}" for i in range(7)
        ]

    def test_names_outside_the_default_three_are_assigned_as_given(self) -> None:
        # The vocabulary is open — the coverage store's own argument
        # from the feature's *"such as"* — so a deployment that
        # configured other names has its worlds binned into them.
        assigned = assign_strata(
            _worlds(("w", 5)), _Labeler(k=3, closing=0), strata=("calm", "chop", "rage")
        )
        assert assigned[0].stratum == "calm"

    def test_an_empty_pool_assigns_nothing(self) -> None:
        # An empty pool is a fact the census reports rather than refuses
        # — the persisting half lands the named-empty row for every
        # stratum, and the pure half simply has no world to answer for.
        assert assign_strata([], _Labeler()) == ()

    def test_the_answer_names_the_pool_and_the_stratum(self) -> None:
        assignment = assign_strata(
            _worlds(("w", 5)), _Labeler(k=3, closing=1)
        )[0]
        assert assignment.row() == {
            "world_id": "w",
            "stratum": DEFAULT_STRATA[1],
        }


# -- The fit is refused ------------------------------------------------------------


class TestTheFitIsRefused:
    """Feature 290's headline: the full-history fit, refused at the seam."""

    def test_an_unbounded_window_is_the_full_history_fit(self) -> None:
        # ``None`` is the spelling of an unbounded span — the labeler's
        # own constructor refuses it in the same words, and the census
        # refuses it here, in this member's vocabulary, before any
        # world is read.
        with pytest.raises(StratumAssignmentError, match="unbounded"):
            assign_strata(_worlds(("w", 5)), _Labeler(window=None))

    def test_a_labeler_that_states_no_window_is_refused_as_the_same_face(self) -> None:
        # At this seam a span that cannot be read and a span that is
        # unbounded are indistinguishable; the census refuses both
        # rather than guess which one it was handed.
        labeler = SimpleNamespace(k=3, label_features=lambda rows: (0,) * len(rows))
        with pytest.raises(StratumAssignmentError, match="no ``window``"):
            assign_strata(_worlds(("w", 5)), labeler)

    @pytest.mark.parametrize("window", [True, 4.0, 0, -3])
    def test_a_window_that_is_not_a_finite_positive_integer(
        self, window
    ) -> None:
        # The configuration guard restated: the window is the whole
        # subject of a causal fit, and anything that is not a number of
        # trailing rows is a span the census cannot vouch for.
        with pytest.raises(StratumAssignmentError, match=FULL_HISTORY_FIT_CODE):
            assign_strata(_worlds(("w", 5)), _Labeler(window=window))

    def test_a_window_spanning_one_worlds_whole_series_is_refused(self) -> None:
        # The degeneracy face: with window == n the single fit behind
        # the world's stratum *is* its entire history.  Refused naming
        # the world and both numbers, so an operator reads which world
        # and which span.
        with pytest.raises(
            StratumAssignmentError, match="world 'w'.*window=6"
        ) as caught:
            assign_strata(_worlds(("w", 6)), _Labeler(k=3, window=6))
        assert "6 usable feature vectors" in str(caught.value)

    def test_a_window_longer_than_a_worlds_series_is_refused(self) -> None:
        with pytest.raises(StratumAssignmentError, match="full_history_fit"):
            assign_strata(_worlds(("w", 4)), _Labeler(k=3, window=9))

    def test_a_one_dated_row_world_can_never_be_binned(self) -> None:
        # The degeneracy face's hardest case: a window of 1 is the
        # smallest legal span, and it still spans a one-row world's
        # whole history — so a world with a single dated row has no
        # causal stratum, and the census says so rather than fitting
        # its one and only row.
        with pytest.raises(StratumAssignmentError, match="world 'w'"):
            assign_strata(_worlds(("w", 1)), _Labeler(k=3, window=1))

    def test_the_refusal_is_this_members_vocabulary_not_the_labelers(
        self,
    ) -> None:
        # The labeler's own guard is a ``ValueError`` subclass this
        # member never imported; a caller's ``except`` over this census
        # must catch this member's class and never the labeler's.  A
        # sibling of CoverageError, not a child: nothing failed to
        # persist here.
        with pytest.raises(StratumAssignmentError) as caught:
            assign_strata(_worlds(("w", 6)), _Labeler(k=3, window=6))
        assert isinstance(caught.value, Exception)
        assert not isinstance(caught.value, ValueError)
        assert not isinstance(caught.value, CoverageError)

    def test_the_full_history_refusal_fires_before_the_labeler_is_called(
        self,
    ) -> None:
        # The census refuses on the span it can name — the stated window
        # against the world's rows — so the labeler's ``label_features``
        # is never reached by a refused ask.  A canary callable proves
        # it: if the census had delegated first, the labeler's own
        # guard (or this canary) would have been what raised.

        def _never_called(rows):  # pragma: no cover - the canary itself
            raise AssertionError("a refused census must not label")

        labeler = SimpleNamespace(k=3, window=None, label_features=_never_called)
        with pytest.raises(StratumAssignmentError, match="unbounded"):
            assign_strata(_worlds(("w", 5)), labeler)

    def test_the_second_worlds_degeneracy_is_refused_too(self) -> None:
        # The guard is per world — a pool where the first world is long
        # enough and the second is not is still a pool holding a world
        # whose stratum would be a full-history fit.
        with pytest.raises(StratumAssignmentError, match="world 'w-short'"):
            assign_strata(
                _worlds(("w-long", 9), ("w-short", 3)), _Labeler(k=3, window=4)
            )


# -- The vocabulary is refused -----------------------------------------------------


class TestTheVocabularyIsRefused:
    """The ledger's names and the labeler's clusters must agree in number."""

    def test_a_count_that_differs_from_the_label_space(self) -> None:
        # The agreement ``test_cross_member.py`` pins from the data side
        # (DEFAULT_K == len(DEFAULT_STRATA)); this is the same law from
        # the asking side — a labeler carving four clusters would label
        # worlds no ledger row holds, a vocabulary naming two could not
        # bin the third cluster's worlds.
        with pytest.raises(
            StratumAssignmentError, match="names 2 strata and the.*carves 3"
        ):
            assign_strata(
                _worlds(("w", 5)), _Labeler(k=3), strata=("calm", "chop")
            )

    def test_a_duplicate_name_would_double_count(self) -> None:
        with pytest.raises(StratumAssignmentError, match="twice"):
            assign_strata(
                _worlds(("w", 5)),
                _Labeler(k=3),
                strata=("calm", "chop", "chop"),
            )

    @pytest.mark.parametrize("name", ["", "   ", 5, None])
    def test_a_name_that_cannot_be_one(self, name) -> None:
        with pytest.raises(StratumAssignmentError, match="non-empty text"):
            assign_strata(
                _worlds(("w", 5)), _Labeler(k=3), strata=("calm", "chop", name)
            )

    def test_a_bare_string_is_one_name_not_a_vocabulary(self) -> None:
        with pytest.raises(StratumAssignmentError, match="not a vocabulary"):
            assign_strata(_worlds(("w", 5)), _Labeler(k=3), strata="crash")

    def test_a_labeler_that_cannot_state_its_label_space(self) -> None:
        # ``k`` is what the vocabulary is checked against; a labeler
        # that cannot state it cannot be checked.
        labeler = SimpleNamespace(window=2, label_features=lambda rows: (0,) * len(rows))
        with pytest.raises(StratumAssignmentError, match="``k``"):
            assign_strata(_worlds(("w", 5)), labeler)

    @pytest.mark.parametrize("k", [True, 3.0, 1])
    def test_a_label_space_that_is_not_a_carving(self, k) -> None:
        # The labeler's own construction law (``k >= 2``, an integer),
        # restated at the seam because the census reads the value off an
        # object it did not construct — a duck-typed stand-in with k=1
        # would answer that the pool is covered by every world it holds.
        with pytest.raises(StratumAssignmentError, match="``k``"):
            assign_strata(_worlds(("w", 5)), _Labeler(k=k))

    def test_a_labeler_with_no_labelling_to_call(self) -> None:
        labeler = SimpleNamespace(k=3, window=2)
        with pytest.raises(StratumAssignmentError, match="label_features"):
            assign_strata(_worlds(("w", 5)), labeler)


# -- The world is refused ----------------------------------------------------------


class TestTheWorldIsRefused:
    """A world that cannot be binned is refused naming the world."""

    @pytest.mark.parametrize("world_id", ["", "   ", 7, None])
    def test_an_id_that_cannot_be_one(self, world_id) -> None:
        with pytest.raises(StratumAssignmentError, match="non-empty text"):
            assign_strata([_World(world_id, _rows(5))], _Labeler())

    def test_a_world_that_names_nothing(self) -> None:
        with pytest.raises(StratumAssignmentError, match="world_id"):
            assign_strata(
                [SimpleNamespace(regime_rows=_rows(5))], _Labeler()
            )

    def test_a_world_that_carries_no_history(self) -> None:
        with pytest.raises(StratumAssignmentError, match="regime feature rows"):
            assign_strata([_World("w", None)], _Labeler())
        with pytest.raises(StratumAssignmentError, match="regime feature rows"):
            assign_strata([SimpleNamespace(world_id="w")], _Labeler())

    def test_an_empty_history_has_no_closing_regime(self) -> None:
        with pytest.raises(StratumAssignmentError, match="empty regime history"):
            assign_strata([_World("w", ())], _Labeler())

    def test_a_ragged_history_is_not_one_series(self) -> None:
        rows = ((1.0, 2.0), (1.0, 2.0, 3.0), (1.0, 2.0))
        with pytest.raises(StratumAssignmentError, match="'w'.*ragged"):
            assign_strata([_World("w", rows)], _Labeler())

    def test_a_history_of_empty_vectors_is_refused(self) -> None:
        with pytest.raises(StratumAssignmentError, match="no features"):
            assign_strata([_World("w", ((), ()))], _Labeler())

    @pytest.mark.parametrize("cell", [float("nan"), float("inf"), float("-inf")])
    def test_a_value_nobody_computed(self, cell) -> None:
        # The usable-row contract drops un-computable values before they
        # arrive; a nan or infinity that survived it is a stand-in, and
        # a stratum read off it is a number the market never printed.
        rows = ((1.0,), (cell,), (2.0,), (3.0,), (4.0,))
        with pytest.raises(StratumAssignmentError, match="'w'.*not finite"):
            assign_strata([_World("w", rows)], _Labeler())

    @pytest.mark.parametrize("cell", [True, "0.1", None])
    def test_a_value_that_is_not_a_measurement(self, cell) -> None:
        rows = ((1.0,), (cell,), (2.0,), (3.0,), (4.0,))
        with pytest.raises(StratumAssignmentError, match="not a real number"):
            assign_strata([_World("w", rows)], _Labeler())

    def test_a_one_pass_iterable_is_not_a_dated_history(self) -> None:
        # The labeler revisits the window at every date, so the rows
        # arrive as a sequence in date order; a generator would be
        # exhausted by the second date and the census refuses it rather
        # than find out inside the labeler.
        rows = (cell for cell in (1.0, 2.0, 3.0, 4.0, 5.0))
        with pytest.raises(StratumAssignmentError, match="sequence"):
            assign_strata([_World("w", rows)], _Labeler())

    def test_a_world_counted_twice_is_refused(self) -> None:
        # The pool's key is its identity, and a census that counted one
        # world twice would report coverage the pool does not hold.
        with pytest.raises(StratumAssignmentError, match="'w'.*twice"):
            assign_strata(_worlds(("w", 5), ("w", 5)), _Labeler())

    def test_an_id_with_surrounding_whitespace_is_the_same_world(self) -> None:
        # The strip is what makes the near-miss honest: " w " is the
        # pool's "w", not a second world, so handing both is the
        # duplicate this census refuses rather than a count of two.
        with pytest.raises(StratumAssignmentError, match="twice"):
            assign_strata(
                [_World("w", _rows(5)), _World(" w ", _rows(5))], _Labeler()
            )


# -- The labels are refused --------------------------------------------------------


class TestTheLabelsAreRefused:
    """The census validates what it reads off the labeler it was handed."""

    @staticmethod
    def _labeler(answer):
        labeler = SimpleNamespace(k=3, window=2)
        labeler.label_features = lambda rows: answer
        return labeler

    def test_an_answer_not_parallel_to_the_rows(self) -> None:
        with pytest.raises(StratumAssignmentError, match="parallel"):
            assign_strata(_worlds(("w", 5)), self._labeler((0, 0, 0)))

    def test_an_answer_that_is_not_a_sequence(self) -> None:
        with pytest.raises(StratumAssignmentError, match="sequence of labels"):
            assign_strata(_worlds(("w", 5)), self._labeler(0))

    def test_a_world_that_closes_with_no_stratum(self) -> None:
        # ``None`` is the labeler's spelling of *no trailing window was
        # full*; at the closing date it means the world's history never
        # reached a full window — and the census pre-checked that it
        # did, so the stand-in answered something it was not asked to.
        with pytest.raises(StratumAssignmentError, match="ends with no stratum"):
            assign_strata(
                _worlds(("w", 5)), self._labeler((0, 0, 0, 0, None))
            )

    @pytest.mark.parametrize("closing", [True, 1.0, "1"])
    def test_a_closing_label_that_is_not_a_cluster_index(self, closing) -> None:
        with pytest.raises(StratumAssignmentError, match="closing label"):
            assign_strata(
                _worlds(("w", 5)), self._labeler((0, 0, 0, 0, closing))
            )

    @pytest.mark.parametrize("closing", [3, -1])
    def test_a_closing_label_the_vocabulary_cannot_name(self, closing) -> None:
        with pytest.raises(StratumAssignmentError, match="outside the 3-stratum"):
            assign_strata(
                _worlds(("w", 5)), self._labeler((0, 0, 0, 0, closing))
            )


# -- The record --------------------------------------------------------------------


class TestTheRecord:
    """The assignment value: frozen, keyed by its own fields, self-validating."""

    def test_the_record_is_frozen(self) -> None:
        assignment = StratumAssignment(world_id="w", stratum="crash")
        with pytest.raises(FrozenInstanceError):
            assignment.stratum = "calm"  # type: ignore[misc]

    def test_the_record_validates_its_own_fields(self) -> None:
        # ``dataclasses.replace`` and unpickling rebuild instances past
        # a factory's nose — the argument the coverage count states for
        # its own ``__post_init__``.
        with pytest.raises(StratumAssignmentError, match="non-empty text"):
            StratumAssignment(world_id="w", stratum="  ")
        with pytest.raises(StratumAssignmentError, match="non-empty text"):
            StratumAssignment(world_id="", stratum="crash")

    def test_row_is_keyed_by_the_records_own_fields(self) -> None:
        assert StratumAssignment(world_id="w", stratum="crash").row() == {
            "world_id": "w",
            "stratum": "crash",
        }


# -- The census (the persisting half) ----------------------------------------------


class TestTheCensus:
    """Assign first, then one row per named stratum — zeros included."""

    def test_records_one_row_per_named_stratum_zeros_included(
        self, store, database_url
    ) -> None:
        # §C7's example ledger writes ``crash: 0``; a vocabulary stratum
        # no world landed in is the named-empty row feature 286's
        # warning fires on, so the census lands it rather than leaving
        # the stratum absent — a different fact, per 0107 detail 1.
        rows = census_coverage(
            _worlds(("w-b", 5), ("w-a", 5), ("w-c", 5)),
            _Labeler(k=3, window=2, closing=1),
            store,
        )
        assert [row.stratum for row in rows] == list(DEFAULT_STRATA)
        assert [row.world_count for row in rows] == [0, 3, 0]
        assert _raw_rows(database_url) == sorted(
            (name, 3 if name == DEFAULT_STRATA[1] else 0) for name in DEFAULT_STRATA
        )

    def test_the_answer_is_the_rows_the_table_holds(self, store) -> None:
        # The row is the record: the census answers with what ``record``
        # read back, never a count assembled from the assignment — the
        # discipline every write in this member states.
        rows = census_coverage(
            _worlds(("w", 5)), _Labeler(k=3, window=2, closing=2), store
        )
        for row in rows:
            standing = store.get(row.stratum)
            assert standing is not None
            assert standing.world_count == row.world_count
            assert standing.updated_at == row.updated_at

    def test_a_rerun_is_idempotent_byte_for_byte(self, store) -> None:
        first = census_coverage(
            _worlds(("w", 5), ("x", 5)), _Labeler(k=3, window=2, closing=0), store
        )
        time.sleep(1.1)  # cross the database clock's second boundary
        again = census_coverage(
            _worlds(("w", 5), ("x", 5)), _Labeler(k=3, window=2, closing=0), store
        )
        # The counts did not change, so the instants they were last true
        # did not either — the store's own retry law, inherited by the
        # census that re-issues the same counts.
        assert [
            (row.stratum, row.world_count, row.updated_at) for row in again
        ] == [(row.stratum, row.world_count, row.updated_at) for row in first]

    def test_a_lower_count_is_persisted_not_refused(
        self, store, database_url
    ) -> None:
        # §C6's excision removes worlds from the pool between censuses;
        # the ledger records what is true now.  The vintage moves with
        # the change — the re-stamp is the writer contract the store
        # owns and the census inherits by writing through it.
        standing = store.record(DEFAULT_STRATA[1], 5)
        time.sleep(1.1)
        rows = census_coverage(
            _worlds(("w", 5)), _Labeler(k=3, window=2, closing=1), store
        )
        shrunk = next(row for row in rows if row.stratum == DEFAULT_STRATA[1])
        assert shrunk.world_count == 1
        assert shrunk.updated_at != standing.updated_at

    def test_validation_is_total_before_the_first_write(
        self, store, database_url
    ) -> None:
        # The second world is degenerate; the refusal must land with
        # the ledger exactly as it was — no table, no partial census —
        # because every refusal the assignment can raise fires before
        # the first record.  The only failures that can land mid-census
        # are the store's own.
        with pytest.raises(StratumAssignmentError, match="world 'w-bad'"):
            census_coverage(
                _worlds(("w-ok", 9), ("w-bad", 3)),
                _Labeler(k=3, window=4),
                store,
            )
        with closing(sqlite3.connect(_path_of(database_url))) as connection:
            cursor = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name = 'regime_coverage'"
            )
            try:
                assert cursor.fetchone() is None
            finally:
                cursor.close()

    def test_the_store_is_duck_typed_not_isinstance_checked(self) -> None:
        # The module loader serves the composed store under a synthetic
        # module name — a second ``RegimeCoverage`` class object — so
        # the census holds no ``isinstance`` on the store it writes
        # through.  A stand-in with a ``record`` and no database at all
        # is written through exactly as the real one is.
        recording = _RecordingStore()
        rows = census_coverage(
            _worlds(("w", 5), ("x", 5)),
            _Labeler(k=3, window=2, closing=0),
            recording,
        )
        assert recording.written == [
            (DEFAULT_STRATA[0], 2),
            (DEFAULT_STRATA[1], 0),
            (DEFAULT_STRATA[2], 0),
        ]
        assert len(rows) == 3

    def test_an_object_that_is_not_a_store_is_refused_in_the_stores_vocabulary(
        self,
    ) -> None:
        # A fault about the store is the store's to name — the
        # persisting half's refusals stay in the store's vocabulary,
        # and an assignment error here would send the caller looking
        # for a fit problem where the problem is the object handed as
        # the ledger.
        with pytest.raises(CoverageError, match="no.*record"):
            census_coverage(_worlds(("w", 5)), _Labeler(), object())

    def test_the_stores_own_refusals_propagate_unwrapped(self) -> None:
        # An address the store cannot speak is refused by the store on
        # its first record, and the census does not wrap it: the
        # CoverageError already names the fact, and a second message in
        # front of it would hide the one an operator needs.
        store = RegimeCoverage("sqlite://ledger-host/regime.db")
        with pytest.raises(CoverageError, match="must not carry a host"):
            census_coverage(_worlds(("w", 5)), _Labeler(), store)

    def test_an_empty_pool_lands_the_named_empty_row_for_every_stratum(
        self, store, database_url
    ) -> None:
        # An empty pool is zero coverage everywhere, and that is a fact
        # the ledger should hold — not an error, and not silence: every
        # named stratum lands its named-empty row, which is exactly the
        # state feature 286's ``empty_stratum`` warning reads.
        rows = census_coverage([], _Labeler(), store)
        assert [row.world_count for row in rows] == [0, 0, 0]
        assert len(_raw_rows(database_url)) == 3


# -- The read-back type ------------------------------------------------------------


class TestTheAnswer:
    """What the persisting half hands back, and what it is typed as."""

    def test_the_rows_come_back_typed_as_the_ledgers_own(
        self, store
    ) -> None:
        rows = census_coverage(_worlds(("w", 5)), _Labeler(k=3, window=2), store)
        assert all(isinstance(row, CoverageCount) for row in rows)
        assert all(row.world_count in (0, 1) for row in rows)
