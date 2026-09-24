"""Feature 267's law, second half — the store: one row per campaign, in
the relational store ``DATABASE_URL`` names, read back as the projection
of the pair it carries.

*System persists FDR_deploy per campaign, computed by reweighting
sensitivity and specificity to a deployment base rate of 0.9*
(app_spec.xml, "Objective Scoring & CVaR Aggregation").  The arithmetic
is ``test_fdr.py``'s subject; this suite pins the half the feature's
verb owns — *persists, per campaign*:

* **the round trip** — what :meth:`~scoring.FdrDeployStore.persist`
  writes, :meth:`~scoring.FdrDeployStore.fdr` reads back to the bit,
  rebuilt from the pair the row carries rather than trusted from the
  denormalised column;
* **the key** — one row per campaign, the id canonicalized through
  ``uuid.UUID`` so every spelling parses to the one row;
* **refresh, not append** — a re-run of a campaign's close-out is the
  same measurement written twice: the measured columns refresh and the
  first ``computed_at`` stands, because it is a fact about the trend's
  history a retry must not rewrite;
* **the ordering of the ask** — the campaign, the pair and the
  reweighting are all validated before a connection is opened, so a
  malformed ask never reaches the store;
* **the store's own failures** — no configured ``DATABASE_URL``, a
  scheme the store cannot speak (refused at first use, never at
  construction), a database that will not open: all surfaced in this
  member's vocabulary with the original chained;
* **the tamper refusals** — a stored figure that disagrees with its own
  pair, a base rate that is not the deployment's, a corrupt pair
  column: each refused by name, because a corrupt row is a figure no
  dashboard and no M3 gate could rely on.

The fixtures come from the suite's conftest: the campaign's measured
pair (figure 0.9 exactly) and the two campaign ids.  The store's
database is a real SQLite file in a tmp directory — the persistence law
is honestly testable only against the thing it persists into.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
import uuid
from pathlib import Path

import pytest
from conftest import (  # type: ignore[import-not-found] - suite-local
    CAMPAIGN_ONE,
    CAMPAIGN_TWO,
    StandInFigures,
)
from scoring import (
    DEPLOYMENT_BASE_RATE,
    FDR_DEPLOY_TABLE,
    CalibrationFigures,
    FdrDeployError,
    FdrDeployStore,
    ScoringError,
    fdr_deploy,
)


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    """The store's database file, inside pytest's tmp directory."""
    return tmp_path / "fdr-store.db"


@pytest.fixture
def store_url(store_path: Path) -> str:
    """The ``DATABASE_URL`` spelling of the store's path.

    The workspace's one convention, and the reason a single formula
    serves: three slashes name a path relative to the working
    directory, and an absolute path — ``tmp_path``'s — carries its own
    leading slash, making four, so the URL's parsed path keeps the one
    slash an absolute path needs.
    """
    return f"sqlite:///{store_path}"


@pytest.fixture
def store(store_url: str) -> FdrDeployStore:
    """The store itself, constructed and unopened."""
    return FdrDeployStore(store_url)


def _tamper(path: Path, statement: str, parameters: tuple) -> None:
    """Corrupt one row behind the store's back.

    A read law is tested by breaking the thing it reads: one direct
    sqlite3 write in the spelling an operator's hand-repair would take,
    bypassing every validation the store performs, so the read that
    follows proves the store rebuilds rather than trusts.
    """
    connection = sqlite3.connect(path)
    with connection:
        connection.execute(statement, parameters)
    connection.close()


# -- The round trip ----------------------------------------------------------------


def test_a_campaign_round_trips_to_the_bit(
    store: FdrDeployStore, figures: CalibrationFigures
) -> None:
    # What persist writes, fdr reads back — the same float, to the bit,
    # because the read recomputes the projection from the stored pair
    # under the one constant and the arithmetic is deterministic: the
    # same three products, sum and division answer the same figure.
    written = store.persist(CAMPAIGN_ONE, figures)
    assert store.fdr(CAMPAIGN_ONE) == written == 0.9


def test_persist_answers_the_figure_it_wrote(
    store: FdrDeployStore, figures: CalibrationFigures
) -> None:
    # The verb returns the number it stored — the same figure the free
    # verb answers for the pair — so a caller that persists gets the
    # figure without computing it twice, and the two spellings of the
    # arithmetic cannot disagree because there is one of it.
    assert store.persist(CAMPAIGN_ONE, figures) == fdr_deploy(figures)


def test_a_second_store_reads_the_firsts_rows(
    store: FdrDeployStore, store_url: str, figures: CalibrationFigures
) -> None:
    # The store holds no cache of the figures it wrote — the URL is the
    # state, the rows live in the database — so a store composed afresh
    # in the same process reads the first one's rows: a figure read
    # back is a fact about the world, not about this process's history.
    store.persist(CAMPAIGN_ONE, figures)
    fresh = FdrDeployStore(store_url)
    assert fresh.fdr(CAMPAIGN_ONE) == 0.9


def test_the_store_is_a_holder_not_a_value() -> None:
    # Hand-written slots and nothing beside them: no shadow state
    # beside the URL for a caller to park a figure in — and no slot
    # that could hold a label or a sidecar key, the shape of the
    # barrier this feature's store keeps by construction.
    assert FdrDeployStore.__slots__ == ("_database_url", "_path")


# -- The key ------------------------------------------------------------------------


def test_the_row_is_keyed_per_campaign(
    store: FdrDeployStore, figures: CalibrationFigures
) -> None:
    # The feature's own unit: per campaign.  Two campaigns, two rows,
    # each read by its own id — the second campaign measured a pair
    # that projects to 0.0 exactly (found every real, committed no
    # null), so the two figures differ and the keying is checkable.
    store.persist(CAMPAIGN_ONE, figures)
    store.persist(CAMPAIGN_TWO, CalibrationFigures(sensitivity=1.0, specificity=1.0))
    assert store.fdr(CAMPAIGN_ONE) == 0.9
    assert store.fdr(CAMPAIGN_TWO) == 0.0
    assert len(store.history()) == 2


def test_the_campaign_id_joins_in_any_spelling_uuid_parses(
    store: FdrDeployStore, figures: CalibrationFigures
) -> None:
    # The key is canonical UUID text — the spelling that joins
    # ``node.campaign_id`` and the discovery member's campaign record —
    # canonicalized through ``uuid.UUID`` so a mixed-case, braced, URN
    # or padded spelling upserts onto the one row rather than making
    # one campaign look like two.  Written as a UUID object, read in
    # every spelling, one row at the end.
    spellings = (
        uuid.UUID(CAMPAIGN_ONE),
        CAMPAIGN_ONE,
        CAMPAIGN_ONE.upper(),
        f"{{{CAMPAIGN_ONE}}}",
        f"urn:uuid:{CAMPAIGN_ONE}",
        f"  {CAMPAIGN_ONE}  ",
    )
    for spelling in spellings:
        store.persist(spelling, figures)
        assert store.fdr(spelling) == 0.9
    assert len(store.history()) == 1
    assert store.history()[0][0] == CAMPAIGN_ONE


def test_a_non_uuid_campaign_is_refused_with_the_join_named(
    store: FdrDeployStore, figures: CalibrationFigures
) -> None:
    # An id that cannot join the tree's campaign key names no campaign
    # a figure could be persisted for, and the refusal says so — the
    # repair (the caller's key) differs from a pair that could not be
    # reweighted.
    for bad in ("not-a-uuid", "campaign-01", 123, None):
        with pytest.raises(FdrDeployError) as narrowed:
            store.persist(bad, figures)  # type: ignore[arg-type]
        assert "campaign" in str(narrowed.value)


# -- Refresh, not append --------------------------------------------------------------


def test_a_rerun_refreshes_rather_than_appends_and_keeps_the_first_instant(
    store: FdrDeployStore, figures: CalibrationFigures
) -> None:
    # The figures are deterministic in the plant and the picks, so a
    # re-run of a campaign's close-out that agrees is the same
    # measurement written twice: the upsert refreshes the measured
    # columns — here a genuinely different pair, the honest shape of a
    # re-run over a corrected plant — and deliberately does not touch
    # ``computed_at``, because the first instant the row was computed
    # is a fact about the trend's history a retry must not rewrite.
    store.persist(CAMPAIGN_ONE, figures, computed_at="2026-01-01T00:00:00")
    rerun = CalibrationFigures(sensitivity=1.0, specificity=1.0)
    store.persist(CAMPAIGN_ONE, rerun, computed_at="2026-06-01T00:00:00")
    history = store.history()
    assert len(history) == 1
    campaign_id, figure, computed_at = history[0]
    assert campaign_id == CAMPAIGN_ONE
    assert figure == fdr_deploy(rerun) == 0.0
    assert computed_at == "2026-01-01T00:00:00"


def test_history_answers_oldest_first_with_the_instant_tie_broken_by_campaign(
    store: FdrDeployStore, figures: CalibrationFigures
) -> None:
    # The trend read, in the direction prd §12's M3 exit reads it
    # ("FDR_deploy improves at π₀ = 0.9" — a falling sequence): ordered
    # by the row's instant, the campaign id breaking a tie an honest
    # same-second close-out can produce.
    store.persist(CAMPAIGN_ONE, figures, computed_at="2026-03-04T09:00:00")
    store.persist(CAMPAIGN_TWO, figures, computed_at="2026-03-04T08:00:00")
    store.persist(CAMPAIGN_ONE, figures, computed_at="2026-03-04T10:00:00")
    assert [row[0] for row in store.history()] == [CAMPAIGN_TWO, CAMPAIGN_ONE]
    # The tie: two campaigns closed out in the same second — the id
    # breaks it, ascending, so the order is deterministic however close
    # the close-outs ran.  Fresh campaigns, because a refresh never
    # rewrites the first instant (the law above), so a tie is made only
    # by two rows born in it.
    tie_one = "1a2b3c4d-5e6f-4778-89ab-cdef00000020"
    tie_two = "1a2b3c4d-5e6f-4778-89ab-cdef00000021"
    store.persist(tie_one, figures, computed_at="2026-03-05T09:00:00")
    store.persist(tie_two, figures, computed_at="2026-03-05T09:00:00")
    assert [row[0] for row in store.history()[-2:]] == [tie_one, tie_two]


def test_an_unknown_campaign_is_none_not_zero(store: FdrDeployStore) -> None:
    # ``None`` is the honest answer for a campaign whose close-out never
    # persisted: a discoverable state, not an exception, and never a
    # zero — ``0.0`` is a measurement (a campaign that projected to no
    # false discoveries) where ``None`` is an absence, and a caller that
    # cannot tell them apart is the caller §4.1.3's under-skeptical
    # policy was made of.
    assert store.fdr(CAMPAIGN_ONE) is None


def test_an_empty_history_is_empty(store: FdrDeployStore) -> None:
    # A deployment that has never closed a campaign out has no trend —
    # a discoverable state, not an exception and not a fabricated
    # first point.
    assert store.history() == []


# -- The ordering of the ask ----------------------------------------------------------


def test_the_ask_is_validated_before_the_store_is_opened(
    store: FdrDeployStore, figures: CalibrationFigures, store_path: Path
) -> None:
    # Campaign, pair, reweighting, instant — validated whole, before a
    # connection is opened: a malformed ask never reaches the store, so
    # a refused close-out leaves no half-written row and no database
    # file at all.  Each refusal face in turn, the file never appearing.
    corrupt_pair = StandInFigures(sensitivity=0.5, specificity=0.5)
    object.__setattr__(corrupt_pair, "sensitivity", 47)
    faces = (
        ("not-a-uuid", figures),
        (CAMPAIGN_ONE, 0.5),
        (CAMPAIGN_ONE, object()),
        (CAMPAIGN_ONE, StandInFigures(sensitivity=0.0, specificity=1.0)),
        (CAMPAIGN_ONE, corrupt_pair),
    )
    for campaign, pair in faces:
        with pytest.raises(FdrDeployError):
            store.persist(campaign, pair)
    # An empty explicit instant is an ask face too, and it also never
    # reaches the store.
    with pytest.raises(FdrDeployError):
        store.persist(CAMPAIGN_ONE, figures, computed_at="   ")
    assert not store_path.exists()


def test_construction_performs_no_io(store_url: str, store_path: Path) -> None:
    # Constructing a store is composition-time work — the builder runs
    # on every ``create_app()`` — so it must not touch the disk: the
    # URL is held, the path is resolved lazily, and the database file
    # appears at the first verb that needs it, not before.
    FdrDeployStore(store_url)
    assert not store_path.exists()


def test_computed_at_defaults_to_now_and_accepts_the_closeouts_instant(
    store: FdrDeployStore, figures: CalibrationFigures
) -> None:
    # The row's label defaults to the wall clock's now — UTC, second
    # resolution, the spelling whose string order is chronological —
    # and a caller that closed the campaign out at a known instant
    # passes it, so the row's label matches the close-out rather than
    # the write.  Both faces, read off the one row each wrote.
    before = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    store.persist(CAMPAIGN_ONE, figures)
    after = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    _, figure, computed_at = store.history()[0]
    assert figure == 0.9
    assert before <= computed_at <= after
    assert computed_at.endswith("+00:00")

    store.persist(CAMPAIGN_TWO, figures, computed_at="2026-09-24T12:00:00")
    assert {row[0]: row[2] for row in store.history()}[CAMPAIGN_TWO] == (
        "2026-09-24T12:00:00"
    )


# -- The store's own failures ----------------------------------------------------------


def test_resolve_answers_none_where_nothing_names_a_store(
    monkeypatch: pytest.MonkeyPatch, store_url: str
) -> None:
    # Absent is not an error: it is a deployment without a relational
    # store, which composes no FDR_deploy component — a discoverable
    # state the caller that needs a row must refuse on, not an
    # exception the builder raised.  Empty and whitespace count as
    # unset; a named store resolves, from the environment and from a
    # mapping handed to the seam.
    from scoring import DATABASE_URL_ENV

    assert FdrDeployStore.resolve() is None
    monkeypatch.setenv(DATABASE_URL_ENV, store_url)
    resolved = FdrDeployStore.resolve()
    assert isinstance(resolved, FdrDeployStore)
    assert resolved.database_url == store_url
    assert FdrDeployStore.resolve({}) is None
    assert FdrDeployStore.resolve({DATABASE_URL_ENV: "   "}) is None
    assert FdrDeployStore.resolve({DATABASE_URL_ENV: store_url}).database_url == (
        store_url
    )


def test_a_url_the_store_cannot_speak_is_refused_at_use_not_construction(
    tmp_path: Path,
) -> None:
    # The builder runs in every process and must never fail composition,
    # so construction holds whatever it was handed and the refusal
    # lands at the first verb that needs a database — where the
    # operator's repair (a misrouted ``DATABASE_URL``) belongs.  A
    # Postgres URL is refused loudly, never silently mis-parsed into a
    # mysterious file; so is a host the URL must not carry, and a URL
    # with no path at all.
    store = FdrDeployStore("postgres://metrics.internal:5432/nullius")
    with pytest.raises(FdrDeployError) as narrowed:
        store.persist(
            "1a2b3c4d-5e6f-4778-89ab-cdef00000010",
            CalibrationFigures(sensitivity=1.0, specificity=0.0),
        )
    assert "postgres" in str(narrowed.value)
    assert not (tmp_path / "metrics.internal").exists()
    for bad in ("sqlite://host.example/store.db", "sqlite:///", ""):
        with pytest.raises(FdrDeployError):
            FdrDeployStore(bad).history()


def test_a_database_that_will_not_open_surfaces_chained(
    tmp_path: Path,
) -> None:
    # The store's own failure — here a path a directory occupies —
    # surfaces in this member's vocabulary with the original chained,
    # because the caller's single ``except ScoringError`` must catch a
    # figure that measured but never landed, and the operator still
    # needs the database's own words.  Never swallowed, never answered
    # around.
    as_directory = tmp_path / "occupied"
    as_directory.mkdir()
    store = FdrDeployStore(f"sqlite:///{as_directory}")
    with pytest.raises(FdrDeployError) as narrowed:
        store.persist(
            "1a2b3c4d-5e6f-4778-89ab-cdef00000010",
            CalibrationFigures(sensitivity=1.0, specificity=0.0),
        )
    assert isinstance(narrowed.value.__cause__, sqlite3.Error)
    with pytest.raises(ScoringError):
        store.history()


# -- The tamper refusals ----------------------------------------------------------------


def test_a_stored_figure_that_disagrees_with_its_own_pair_is_refused(
    store: FdrDeployStore,
    store_path: Path,
    figures: CalibrationFigures,
) -> None:
    # The pair is the row's truth and the figure a derived view over
    # it, so the read rebuilds — and a row whose stored ``fdr_deploy``
    # the stored pair does not recompute to is refused by name, never
    # read: a corrupt row is a figure no dashboard and no M3 gate could
    # rely on, and refusing it is how the rest of the trend stays
    # trustworthy.  The refusal lands on the one-campaign read and the
    # whole-history read alike.
    store.persist(CAMPAIGN_ONE, figures)
    _tamper(
        store_path,
        f"UPDATE {FDR_DEPLOY_TABLE} SET fdr_deploy = ? WHERE campaign_id = ?",
        (0.123, CAMPAIGN_ONE),
    )
    with pytest.raises(FdrDeployError) as narrowed:
        store.fdr(CAMPAIGN_ONE)
    assert CAMPAIGN_ONE in str(narrowed.value)
    with pytest.raises(FdrDeployError):
        store.history()


def test_a_stored_base_rate_that_is_not_the_deployments_is_refused(
    store: FdrDeployStore,
    store_path: Path,
    figures: CalibrationFigures,
) -> None:
    # §16's own line carries the qualifier — "FDR_deploy at π₀ = 0.9" —
    # and a reader must never guess which projection a stored number
    # was.  A row reweighted at a rate nobody pinned is a number nobody
    # targeted: refused, never recomputed at the rate the row happens
    # to hold, because that would answer a figure no close-out wrote.
    store.persist(CAMPAIGN_ONE, figures)
    _tamper(
        store_path,
        f"UPDATE {FDR_DEPLOY_TABLE} SET base_rate = ? WHERE campaign_id = ?",
        (0.25, CAMPAIGN_ONE),
    )
    with pytest.raises(FdrDeployError) as narrowed:
        store.fdr(CAMPAIGN_ONE)
    assert str(DEPLOYMENT_BASE_RATE) in str(narrowed.value)


def test_a_corrupt_pair_column_is_refused_by_the_figures_own_law(
    store: FdrDeployStore,
    store_path: Path,
    figures: CalibrationFigures,
) -> None:
    # The read's narrowing is the write's: a pair column that is not a
    # finite real in ``[0, 1]`` — here a sensitivity a count of nodes
    # could wear — is refused in the seam's figure vocabulary rather
    # than reaching the arithmetic unvalidated, and the field is named.
    store.persist(CAMPAIGN_ONE, figures)
    _tamper(
        store_path,
        f"UPDATE {FDR_DEPLOY_TABLE} SET sensitivity = ? WHERE campaign_id = ?",
        (47.0, CAMPAIGN_ONE),
    )
    with pytest.raises(FdrDeployError) as narrowed:
        store.fdr(CAMPAIGN_ONE)
    assert "sensitivity" in str(narrowed.value)
