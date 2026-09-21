"""Feature 178: the candidate as a rank-1 update against the factor.

app_spec.xml, "Tree & Artifact Persistence", feature 178: *System
evaluates a candidate as a rank-1 update against the precomputed
factor, which returns ir_marginal in roughly 40 microseconds.*
docs/nullius-tech-architecture.md §9.3 states it as the per-candidate
half of the replay bottleneck's answer — *"every candidate is a rank-1
update at ``O(kT + k²)`` — roughly 40 µs"* — and these tests pin the
update as seven facts, each one a way a careless version of it would
silently fail:

* **the answer is the evaluator's definition** — ``ir_marginal`` is
  §6.2's ``IR(book ∪ {v}) − IR(book)`` under the evaluator's own
  coefficient (equal weights, population ``1/T``, ``fsum``), agreeing
  with the two-ratio difference spelled by hand from the same cells,
  and every term the record carries reduces from those cells.
* **the update is the rank-1 update** — the candidate's variance
  splits into the part the book explains and the residual it adds,
  the explained part is the covariance through the book's precision,
  and the combined variance folds from the book's, the candidate's
  and the covariance between them.
* **determinism, and the factor is read-only** — two evaluations of
  one candidate answer identical floats, the order candidates are
  scored in changes nothing, and the factor's buffer is byte-identical
  after any number of updates, which is what makes threading one
  factor through a whole replay safe.
* **array indexing, not I/O** — the candidate is a row of the resident
  array aligned on the factor's own sample, a candidate that measured
  more periods than the book is scored on exactly the sample cells
  and nothing else, and a campaign whose Parquet is deleted after the
  load still scores.
* **absence is not zero, and the pivot is not patched** — a candidate
  or member that missed a sample period refuses naming it, a constant
  candidate refuses, a candidate the book already spans refuses with
  its residual named, and a candidate already committed to the book
  refuses before the arithmetic runs.
* **the triangle must be one book** — a factor and an array of
  different campaigns or horizons, a sample period the array cannot
  address, a member the array holds no row for: each refuses, because
  the update scores candidates against the covariance of one
  campaign's measurements or nothing.
* **the record is honest in both directions, and the band holds** — a
  valid value rebuilt from a real update's terms is answered, every
  lying spelling of one refuses rather than answering a marginal no
  update measured, the decline feature 176 spelled stands beside the
  update that exists because of it, and the whole call reads inside a
  five-fold band around §9.3's figure at the sizing the figure was
  measured at.
"""

from __future__ import annotations

import array as _array
import datetime as dt
import math
import random
import shutil
import time
from dataclasses import FrozenInstanceError, replace

import pytest

pytest.importorskip(
    "pyarrow", reason="the update scores rows of feature 174's Parquet load"
)
from artifacts import (
    ABSENT,
    RANK1_UPDATE_COST_MICROSECONDS,
    RANK1_UPDATE_POLICY,
    RANK1_UPDATE_SIZING_BOOK,
    RANK1_UPDATE_SIZING_SAMPLE,
    ArtifactMarginalIRDeclinedError,
    ArtifactRank1UpdateError,
    ArtifactStore,
    BookCholesky,
    CampaignReturns,
    ReturnRow,
    ReturnSeriesCache,
    SignalReturns,
    evaluate_rank1_update,
    load_campaign_returns,
    persist_signal_returns,
    precompute_book_cholesky,
)

D1 = dt.date(2026, 1, 5)
D2 = dt.date(2026, 1, 6)
D3 = dt.date(2026, 1, 7)
D4 = dt.date(2026, 1, 8)
D5 = dt.date(2026, 1, 9)
D6 = dt.date(2026, 1, 12)
D7 = dt.date(2026, 1, 13)
D8 = dt.date(2026, 1, 14)

SNAPSHOT = "snap-2026-01"
VENUE = "binance"
VERSION = "v3"

#: The working book — three members of the working campaign, the same
#: dyadic T-vectors the 177 suite factors.
BOOK = ("node-a", "node-b", "node-c")

#: The candidates the replay scores against it.
CANDIDATES = ("node-x", "node-y")

ALL_DAYS = (D1, D2, D3, D4, D5, D6, D7, D8)

#: The working campaign's five T-vectors — all dyadic, so the float32
#: cells, the ``fsum`` means and the hand arithmetic below are exact
#: and the agreement tests compare against rounding, not luck.
WORKING_VECTORS = {
    "node-a": (0.5, -0.5, 0.25, -0.25, 0.125, -0.125, 0.0625, -0.0625),
    "node-b": (0.25, 0.25, -0.125, -0.125, 0.5, 0.5, -0.25, -0.25),
    "node-c": (-0.125, 0.375, 0.5, -0.5, 0.25, -0.25, 0.0625, 0.1875),
    "node-x": (-0.5, 0.25, 0.125, 0.375, -0.25, 0.0625, -0.375, 0.4375),
    "node-y": (0.1875, -0.375, -0.0625, 0.4375, 0.375, -0.4375, 0.25, 0.125),
}


# -- Small builders, the 174 and 177 suites' own shapes ------------------------------


def _row(
    day: dt.date,
    symbol: str,
    net: float,
    *,
    horizon: int = 1,
    charge: float = 0.001,
) -> ReturnRow:
    """One priced row at a horizon — the helper shape of the 170 suite."""
    return ReturnRow(
        rebalance_date=day,
        horizon=horizon,
        symbol=symbol,
        charge=charge,
        post_cost_return=net,
    )


def _panel(
    node_id: str,
    rows: tuple[ReturnRow, ...],
    *,
    snapshot_name: str = SNAPSHOT,
    venue: str = VENUE,
    version: str = VERSION,
) -> SignalReturns:
    """A priced panel for one node, in the identity the caller spells."""
    return SignalReturns(
        node_id=node_id,
        snapshot_name=snapshot_name,
        venue=venue,
        version=version,
        rows=rows,
    )


def _vector_panel(
    node_id: str, days: tuple[dt.date, ...], values: tuple[float, ...]
) -> SignalReturns:
    """A one-symbol panel whose T-vector is exactly ``values``."""
    return _panel(
        node_id,
        tuple(_row(day, "AAA", value) for day, value in zip(days, values)),
    )


def _working_campaign(store: ArtifactStore, campaign_id: str) -> CampaignReturns:
    """Publish the five-node working campaign and load it resident."""
    for node in (*BOOK, *CANDIDATES):
        persist_signal_returns(
            store,
            campaign_id,
            node,
            _vector_panel(node, ALL_DAYS, WORKING_VECTORS[node]),
        )
        store.commit(campaign_id, node)
    return load_campaign_returns(store, campaign_id)


def _resident(
    vectors: dict[str, tuple[float, ...]],
    days: tuple[dt.date, ...],
    *,
    campaign_id: str = "hand-built",
    horizon: int = 1,
) -> CampaignReturns:
    """A resident array built by hand — the values spelled, exactly.

    The shape feature 174's load answers, built directly so the tests
    that measure precision or cost never pay a Parquet round-trip and
    never depend on the store: dyadic values narrow to float32
    exactly, and NaN is spelled with :data:`ABSENT` where a test wants
    absence rather than a measurement.
    """
    nodes = tuple(sorted(vectors))
    cells = [value for node in nodes for value in vectors[node]]
    return CampaignReturns(
        campaign_id=campaign_id,
        snapshot_name=SNAPSHOT,
        venue=VENUE,
        version=VERSION,
        horizon=horizon,
        node_ids=nodes,
        periods=days,
        values=_array.array("f", cells),
    )


def _refused(call, *args, **kwargs) -> str:
    """The message of the refusal a call answers, as text."""
    with pytest.raises(ArtifactRank1UpdateError) as caught:
        call(*args, **kwargs)
    return str(caught.value)


# -- Hand arithmetic, the evaluator's own spelling -----------------------------------


def _information_ratio(series: list[float]) -> float:
    """The ratio feature 80 pins — mean over population std, fsum."""
    count = len(series)
    mean = math.fsum(series) / count
    variance = math.fsum((value - mean) ** 2 for value in series) / count
    return mean / math.sqrt(variance)


def _hand_ratios(
    vectors: dict[str, tuple[float, ...]], book: tuple[str, ...], candidate: str
) -> dict[str, float]:
    """The two-ratio difference spelled the way the evaluator spells it.

    Per-date equal-weight series — the book's (``1/k`` on each member)
    and the combined book-plus-candidate's (``1/(k+1)``) — each
    reduced to its information ratio the way
    :mod:`evaluator._marginal` reduces them, and differenced.  On the
    dyadic working vectors every float here is exact, so the update's
    factor-route answer is compared against the true value of its own
    definition, not against a second rounding of it.
    """
    count = len(next(iter(vectors.values())))
    book_series = [
        math.fsum(vectors[node][t] for node in book) / len(book)
        for t in range(count)
    ]
    combined_series = [
        (math.fsum(vectors[node][t] for node in book) + vectors[candidate][t])
        / (len(book) + 1)
        for t in range(count)
    ]
    candidate_series = list(vectors[candidate])
    book_ir = _information_ratio(book_series)
    combined_ir = _information_ratio(combined_series)
    return {
        "book_ir": book_ir,
        "combined_ir": combined_ir,
        "candidate_ir": _information_ratio(candidate_series),
        "ir_marginal": combined_ir - book_ir,
    }


def _hand_moments(
    vectors: dict[str, tuple[float, ...]],
    book: tuple[str, ...],
    candidate: str,
) -> dict[str, float]:
    """The moments the update reads, spelled independently of it.

    The evaluator's coefficient: cells centered on their ``fsum``
    means, products summed with ``fsum``, population ``1/T`` — exact
    on the dyadic vectors, and independent of the module's own
    route through the factor.
    """
    count = len(next(iter(vectors.values())))
    centered = {
        node: [value - math.fsum(values) / count for value in values]
        for node, values in vectors.items()
    }
    gamma = [
        math.fsum(a * b for a, b in zip(centered[node], centered[candidate]))
        / count
        for node in book
    ]
    return {
        "means": {
            node: math.fsum(values) / count for node, values in vectors.items()
        },
        "gamma": gamma,
        "candidate_variance": math.fsum(
            a * a for a in centered[candidate]
        ) / count,
        "covariance": [
            [
                math.fsum(a * b for a, b in zip(centered[node_i], centered[node_j]))
                / count
                for node_j in book
            ]
            for node_i in book
        ],
    }


def _hand_cholesky(sigma: list[list[float]]) -> list[list[float]]:
    """Banachiewicz on the hand covariance — an independent factor."""
    k = len(sigma)
    lower = [[0.0] * k for _ in range(k)]
    for i in range(k):
        for j in range(i + 1):
            running = math.fsum(lower[i][m] * lower[j][m] for m in range(j))
            if i == j:
                lower[i][i] = math.sqrt(sigma[i][i] - running)
            else:
                lower[i][j] = (sigma[i][j] - running) / lower[j][j]
    return lower


# -- The answer is the evaluator's definition ----------------------------------------


def test_the_update_answers_the_two_ratio_difference(
    store: ArtifactStore, campaign_id: str
) -> None:
    # §6.2's definition, verified against the hand spelling: the
    # update's ir_marginal is the combined ratio less the book ratio,
    # each ratio the information ratio of its own equal-weight
    # per-date series, and the candidate's standalone ratio beside
    # them.  The factor route agrees with the per-date route to the
    # rounding of the factorization, not to the bit — two spellings of
    # one arithmetic — which is why the tolerance is relative.
    loaded = _working_campaign(store, campaign_id)
    factor = precompute_book_cholesky(loaded, BOOK)
    for candidate in CANDIDATES:
        update = evaluate_rank1_update(factor, loaded, candidate)
        hand = _hand_ratios(WORKING_VECTORS, BOOK, candidate)
        assert update.node_id == candidate
        assert update.campaign_id == campaign_id
        assert update.horizon == loaded.horizon
        assert update.node_ids == BOOK
        assert update.periods == ALL_DAYS
        assert update.book_size == len(BOOK)
        assert update.dates == len(ALL_DAYS)
        assert update.ir_marginal == pytest.approx(
            hand["ir_marginal"], rel=1e-12
        )
        assert update.book_ir == pytest.approx(hand["book_ir"], rel=1e-12)
        assert update.combined_ir == pytest.approx(
            hand["combined_ir"], rel=1e-12
        )
        assert update.candidate_ir == pytest.approx(
            hand["candidate_ir"], rel=1e-12
        )
        # the increment is the difference of the module's own two
        # ratios — the identity the record enforces on itself.
        assert update.ir_marginal == update.combined_ir - update.book_ir


def test_every_term_reduces_from_the_cells(
    store: ArtifactStore, campaign_id: str
) -> None:
    # The record carries its terms so the scalar can be checked; these
    # tests check the terms.  Every moment is the evaluator's own
    # coefficient applied to the same cells the factor was precomputed
    # over: the means, the candidate's variance, the book–candidate
    # covariance, and the variance split at the book.
    loaded = _working_campaign(store, campaign_id)
    factor = precompute_book_cholesky(loaded, BOOK)
    candidate = "node-x"
    update = evaluate_rank1_update(factor, loaded, candidate)
    moments = _hand_moments(WORKING_VECTORS, BOOK, candidate)
    k = len(BOOK)
    means = moments["means"]
    assert update.candidate_mean == means[candidate]
    assert update.candidate_std == pytest.approx(
        math.sqrt(moments["candidate_variance"]), rel=1e-12
    )
    assert update.book_mean == pytest.approx(
        math.fsum(means[node] for node in BOOK) / k, rel=1e-15
    )
    assert update.combined_mean == pytest.approx(
        (k * update.book_mean + update.candidate_mean) / (k + 1), rel=1e-15
    )
    assert update.book_candidate_covariance == pytest.approx(
        math.fsum(moments["gamma"]), rel=1e-15
    )
    # The rank-1 split: explained plus residual is the candidate's
    # variance, and each half is non-negative.
    assert update.explained_variance >= 0.0
    assert update.residual_variance > 0.0
    assert update.explained_variance + update.residual_variance == (
        pytest.approx(moments["candidate_variance"], rel=1e-12)
    )
    # The explained half is the candidate's covariance with the book
    # through the book's precision — γᵀΣ⁻¹γ, spelled by solving an
    # independently factored hand covariance the way the module solves
    # the precomputed one.
    lower = _hand_cholesky(moments["covariance"])
    coordinates = [0.0] * k
    for i in range(k):
        coordinates[i] = (
            moments["gamma"][i]
            - math.fsum(lower[i][j] * coordinates[j] for j in range(i))
        ) / lower[i][i]
    assert update.explained_variance == pytest.approx(
        math.fsum(value * value for value in coordinates), rel=1e-9
    )
    # The combined variance folds from the book's, the candidate's and
    # the covariance between them — the identity the record enforces
    # on itself, verified here against the hand-spelled moments.
    combined_quadratic = (k + 1) ** 2 * update.combined_std**2
    book_variance = k * k * update.book_std**2
    assert combined_quadratic == pytest.approx(
        book_variance + 2.0 * update.book_candidate_covariance
        + moments["candidate_variance"],
        rel=1e-12,
    )


def test_a_constant_candidate_refuses(
    store: ArtifactStore, campaign_id: str
) -> None:
    # A candidate that never varied has no information ratio to
    # contribute — the evaluator's own stance on a constant side,
    # refused here before the solve ever runs.
    loaded = _working_campaign(store, campaign_id)
    factor = precompute_book_cholesky(loaded, BOOK)
    constant = _resident(
        {**WORKING_VECTORS, "node-flat": (0.25,) * len(ALL_DAYS)},
        ALL_DAYS,
        campaign_id=campaign_id,
    )
    message = _refused(evaluate_rank1_update, factor, constant, "node-flat")
    assert "node-flat" in message
    assert "constant" in message
    assert "undefined" in message


# -- The update is the rank-1 update -------------------------------------------------


def test_the_spanned_candidate_refuses_with_its_residual_named() -> None:
    # The verdict the precompute takes on a dependent member, taken
    # here on the candidate.  A hand-built factor whose covariance is
    # not this array's makes the arithmetic discover a candidate the
    # "book" explains more of than the candidate holds — residual
    # below zero, robustly, because the factor and the array disagree
    # by construction rather than by a rounding.
    days = (D1, D2, D3, D4)
    vectors = {
        "node-a": (1.0, -1.0, 2.0, -2.0),
        "node-x": (0.5, -0.5, 1.0, -1.0),
    }
    loaded = _resident(vectors, days)
    lying = BookCholesky(
        campaign_id="hand-built",
        horizon=1,
        node_ids=("node-a",),
        periods=days,
        factor=_array.array("d", [1.0]),
    )
    message = _refused(evaluate_rank1_update, lying, loaded, "node-x")
    assert "node-x" in message
    assert "residual variance" in message
    assert "no jitter" in message


def test_a_candidate_the_book_nearly_spans_answers_nothing_measurable() -> None:
    # The boundary the span refusal cuts: a scaled member is in the
    # book's span exactly, so the update either refuses it (the
    # residual computed at or below zero) or answers a marginal
    # indistinguishable from zero — both are honest, and neither
    # invents a score.  Whichever side the rounding lands on, it lands
    # on it deterministically for one factor and one candidate.
    loaded = _resident(WORKING_VECTORS, ALL_DAYS)
    factor = precompute_book_cholesky(loaded, BOOK)
    scaled = _resident(
        {
            **WORKING_VECTORS,
            "node-double-a": tuple(2 * v for v in WORKING_VECTORS["node-a"]),
        },
        ALL_DAYS,
    )
    outcomes = []
    for _ in range(2):
        try:
            outcomes.append(
                evaluate_rank1_update(
                    factor, scaled, "node-double-a"
                ).ir_marginal
            )
        except ArtifactRank1UpdateError:
            outcomes.append("refused")
    if outcomes[0] != "refused":
        assert outcomes[0] == pytest.approx(0.0, abs=1e-9)
    assert len(set(map(repr, outcomes))) == 1


# -- Determinism, and the factor is read-only ----------------------------------------


def test_two_evaluations_answer_identical_floats(
    store: ArtifactStore, campaign_id: str
) -> None:
    # §10.4's "fully deterministic" replay rests on this: fsum is
    # exactly rounded and order-independent, the axes are the factor's
    # canonical ones, and nothing outside the arguments enters the
    # arithmetic — so the same factor, array and candidate answer the
    # same value, bit for bit, however often the replay asks.
    loaded = _working_campaign(store, campaign_id)
    factor = precompute_book_cholesky(loaded, BOOK)
    for candidate in CANDIDATES:
        first = evaluate_rank1_update(factor, loaded, candidate)
        second = evaluate_rank1_update(factor, loaded, candidate)
        assert first == second
        with pytest.raises(FrozenInstanceError):
            first.ir_marginal = 0.0  # type: ignore[misc]


def test_the_order_candidates_are_scored_in_changes_nothing(
    store: ArtifactStore, campaign_id: str
) -> None:
    # The update is a pure function of its arguments: no candidate
    # leaves state behind for the next one to read — the property that
    # lets one replay score a campaign's candidates in any order the
    # policy reveals them.
    loaded = _working_campaign(store, campaign_id)
    factor = precompute_book_cholesky(loaded, BOOK)
    forward = {
        candidate: evaluate_rank1_update(factor, loaded, candidate)
        for candidate in CANDIDATES
    }
    backward = {
        candidate: evaluate_rank1_update(factor, loaded, candidate)
        for candidate in reversed(CANDIDATES)
    }
    assert forward == backward


def test_the_factor_is_read_never_written(
    store: ArtifactStore, campaign_id: str
) -> None:
    # The book is fixed during a replay, so nothing downstream may
    # grow, shrink or perturb the factor a whole replay threads: its
    # buffer's bytes are identical after the updates, and the answer
    # carries no augmented factor to tempt a caller into threading
    # one — the next replay precomputes its own.
    loaded = _working_campaign(store, campaign_id)
    factor = precompute_book_cholesky(loaded, BOOK)
    before = bytes(factor.factor)
    for candidate in CANDIDATES:
        update = evaluate_rank1_update(factor, loaded, candidate)
        assert not hasattr(update, "factor")
        assert not hasattr(update, "coordinates")
    assert bytes(factor.factor) == before
    assert factor.node_ids == BOOK


# -- Array indexing, not I/O ---------------------------------------------------------


def test_extra_periods_a_candidate_measured_do_not_enter() -> None:
    # The sample is the factor's — the periods every member measured —
    # and the update aligns the candidate on exactly those columns: a
    # candidate that measured a longer window is scored on the sample
    # cells and nothing else, answering the identical value the
    # shorter measurement answers.  The extra days exist only in the
    # candidate's row (the members carry ABSENT there), so the shared
    # sample — and therefore the whole update — is the original one.
    extra_days = ALL_DAYS + (
        dt.date(2026, 1, 15),
        dt.date(2026, 1, 16),
        dt.date(2026, 1, 19),
    )
    wider_vectors = {
        node: WORKING_VECTORS[node] + (ABSENT, ABSENT, ABSENT)
        for node in BOOK
    }
    wider_vectors.update(
        {
            node: values + (9.5, -9.5, 7.25)
            for node, values in WORKING_VECTORS.items()
            if node not in BOOK
        }
    )
    narrower = _resident(WORKING_VECTORS, ALL_DAYS)
    wider = _resident(wider_vectors, extra_days)
    on_sample = evaluate_rank1_update(
        precompute_book_cholesky(narrower, BOOK), narrower, "node-x"
    )
    on_wider = evaluate_rank1_update(
        precompute_book_cholesky(wider, BOOK), wider, "node-x"
    )
    assert on_wider.periods == ALL_DAYS
    assert on_wider == on_sample


def test_the_update_touches_no_store_and_no_files(
    store: ArtifactStore, campaign_id: str
) -> None:
    # §9.3's "array indexing plus a rank-1 update" is a claim about
    # cost as much as arithmetic: the update reads two arguments and
    # answers a value, so a campaign whose Parquet is deleted after
    # the load still scores — the resident array and the factor are
    # the whole of the update's world.
    loaded = _working_campaign(store, campaign_id)
    factor = precompute_book_cholesky(loaded, BOOK)
    before = evaluate_rank1_update(factor, loaded, "node-x").ir_marginal
    shutil.rmtree(store.root)
    after = evaluate_rank1_update(factor, loaded, "node-x").ir_marginal
    assert after == before


# -- Absence is not zero, and the pivot is not patched -------------------------------


def test_a_candidate_that_missed_a_sample_period_refuses_named() -> None:
    # Feature 75's absence rule, restated for the candidate: a hole in
    # the resident array is not a zero return, and the refusal names
    # every period the candidate did not measure.
    holed = dict(WORKING_VECTORS)
    holed["node-x"] = tuple(
        ABSENT if day in (D2, D6) else value
        for day, value in zip(ALL_DAYS, WORKING_VECTORS["node-x"])
    )
    loaded = _resident(holed, ALL_DAYS)
    factor = precompute_book_cholesky(loaded, BOOK)
    message = _refused(evaluate_rank1_update, factor, loaded, "node-x")
    assert "node-x" in message
    assert D2.isoformat() in message
    assert D6.isoformat() in message
    assert "hole" in message


def test_a_member_that_missed_a_sample_period_refuses_as_a_foreign_factor() -> None:
    # The precompute's sample is by construction the periods every
    # member measured, so a member hole on the sample can only mean
    # the factor was not precomputed over this array's cells — the
    # update says that, and refuses to score candidates against a
    # covariance the book never had.
    honest = _resident(WORKING_VECTORS, ALL_DAYS)
    factor = precompute_book_cholesky(honest, BOOK)
    holed = dict(WORKING_VECTORS)
    holed["node-b"] = tuple(
        ABSENT if day in (D3, D7) else value
        for day, value in zip(ALL_DAYS, WORKING_VECTORS["node-b"])
    )
    mismatched = _resident(holed, ALL_DAYS)
    message = _refused(evaluate_rank1_update, factor, mismatched, "node-x")
    assert "node-b" in message
    assert D3.isoformat() in message
    assert "precomputed over this array" in message


# -- The triangle must be one book ---------------------------------------------------


def test_a_factor_of_another_campaign_refuses() -> None:
    loaded = _resident(WORKING_VECTORS, ALL_DAYS, campaign_id="one")
    other = _resident(WORKING_VECTORS, ALL_DAYS, campaign_id="two")
    factor = precompute_book_cholesky(loaded, BOOK)
    message = _refused(evaluate_rank1_update, factor, other, "node-x")
    assert "'one'" in message
    assert "'two'" in message
    assert "another campaign" in message


def test_a_factor_of_another_horizon_refuses() -> None:
    loaded = _resident(WORKING_VECTORS, ALL_DAYS)
    factor = precompute_book_cholesky(loaded, BOOK)
    other = _resident(WORKING_VECTORS, ALL_DAYS, horizon=5)
    message = _refused(evaluate_rank1_update, factor, other, "node-x")
    assert "horizon 1" in message
    assert "horizon 5" in message


def test_a_sample_period_the_array_cannot_address_refuses() -> None:
    loaded = _resident(WORKING_VECTORS, ALL_DAYS)
    factor = precompute_book_cholesky(loaded, BOOK)
    narrower_axis = _resident(
        {node: values[:7] for node, values in WORKING_VECTORS.items()},
        ALL_DAYS[:7],
    )
    message = _refused(evaluate_rank1_update, factor, narrower_axis, "node-x")
    assert D8.isoformat() in message
    assert "column axis" in message


def test_a_member_the_array_holds_no_row_for_refuses() -> None:
    loaded = _resident(WORKING_VECTORS, ALL_DAYS)
    factor = precompute_book_cholesky(loaded, BOOK)
    thinner = _resident(
        {
            node: values
            for node, values in WORKING_VECTORS.items()
            if node != "node-b"
        },
        ALL_DAYS,
    )
    message = _refused(evaluate_rank1_update, factor, thinner, "node-x")
    assert "'node-b'" in message
    assert "holds no row" in message


def test_arguments_that_are_not_the_triangle_refuse() -> None:
    loaded = _resident(WORKING_VECTORS, ALL_DAYS)
    factor = precompute_book_cholesky(loaded, BOOK)
    assert "BookCholesky" in _refused(
        evaluate_rank1_update, loaded, loaded, "node-x"
    )
    assert "CampaignReturns" in _refused(
        evaluate_rank1_update, factor, factor, "node-x"
    )
    assert "node id" in _refused(evaluate_rank1_update, factor, loaded, 42)
    assert "node id" in _refused(evaluate_rank1_update, factor, loaded, "")
    assert "'node-zz'" in _refused(
        evaluate_rank1_update, factor, loaded, "node-zz"
    )
    assert "holds no row" in _refused(
        evaluate_rank1_update, factor, loaded, "node-zz"
    )


def test_a_candidate_the_book_already_holds_refuses() -> None:
    # A rank-1 update appends a signal the book does not have; the
    # precompute would refuse the doubled member, and the update
    # refuses the doubled candidate for the same reason — before any
    # arithmetic runs.
    loaded = _resident(WORKING_VECTORS, ALL_DAYS)
    factor = precompute_book_cholesky(loaded, BOOK)
    message = _refused(evaluate_rank1_update, factor, loaded, "node-a")
    assert "'node-a'" in message
    assert "already holds" in message


# -- The record is honest in both directions -----------------------------------------


def test_a_value_rebuilt_from_a_real_update_s_terms_is_answered(
    store: ArtifactStore, campaign_id: str
) -> None:
    # The record's own constructor is the defence: rebuilding the
    # value from a real update's fields — every term, unchanged —
    # answers an equal value, so the constructor refuses nothing an
    # honest caller could build.
    loaded = _working_campaign(store, campaign_id)
    factor = precompute_book_cholesky(loaded, BOOK)
    update = evaluate_rank1_update(factor, loaded, "node-x")
    assert replace(update) == update


def test_every_lying_spelling_of_a_record_refuses(
    store: ArtifactStore, campaign_id: str
) -> None:
    # The terms check the scalar: a ratio that is not its own mean
    # over its own standard deviation, an increment that is not the
    # difference, a mean that is not the fold, a split that does not
    # sum, a variance that does not fold, a residual the update would
    # never answer — each refuses, naming the term that lied.
    loaded = _working_campaign(store, campaign_id)
    factor = precompute_book_cholesky(loaded, BOOK)
    update = evaluate_rank1_update(factor, loaded, "node-x")

    def lies(**changes) -> str:
        return _refused(
            lambda **fields: type(update)(**{**update.__dict__, **fields}),
            **changes,
        )

    assert "ir_marginal" in lies(ir_marginal=update.ir_marginal + 1e-9)
    assert "book_ir" in lies(book_ir=update.book_ir * 1.0000001)
    assert "combined_ir" in lies(combined_ir=update.combined_ir + 1e-6)
    assert "candidate_ir" in lies(candidate_ir=update.candidate_ir - 1e-6)
    assert "combined_mean" in lies(combined_mean=update.combined_mean + 1e-9)
    assert "the book explains" in lies(
        explained_variance=0.5 * update.explained_variance
    )
    assert "strictly positive" in lies(residual_variance=0.0)
    assert "strictly positive" in lies(residual_variance=-1e-12)
    assert "their sum is not" in lies(
        residual_variance=update.residual_variance * 4
    )
    assert "strictly positive" in lies(book_std=0.0)
    assert "not finite" in lies(combined_std=float("nan"))
    assert "a number" in lies(book_mean="0.3")
    assert "book holds" in lies(book_size=len(BOOK) + 1)
    assert "dates" in lies(dates=update.dates + 1)
    assert "already holds the candidate" in lies(node_id="node-a")
    assert "too few" in lies(periods=update.periods[: len(BOOK) + 1])
    assert "sorted" in lies(node_ids=tuple(reversed(BOOK)))
    assert "campaign" in lies(campaign_id=" ")
    assert "candidate" in lies(node_id="")


def test_a_sample_too_short_for_the_augmented_book_answers_nothing(
    store: ArtifactStore, campaign_id: str
) -> None:
    # k members plus the candidate leave centering's (T − 1)-dimensional
    # subspace no room: at T = k + 1 the augmented covariance is
    # singular *exactly*, so the update refuses — through the span
    # refusal or the shape refusal, whichever the rounding reaches
    # first, and both name the same fact: there is no candidate this
    # book over this sample can measure.  (The record's own shape
    # refusal is the hand-built spelling of the same boundary.)
    days = (D1, D2, D3, D4)
    vectors = {
        "node-a": (1.0, -0.5, 0.25, -0.125),
        "node-b": (-0.5, 0.25, -1.0, 0.5),
        "node-c": (0.25, 0.5, -0.25, -0.5),
        "node-x": (0.125, -0.25, 0.5, 1.0),
    }
    loaded = _resident(vectors, days)
    factor = precompute_book_cholesky(loaded, BOOK)
    message = _refused(evaluate_rank1_update, factor, loaded, "node-x")
    assert "singular by construction" in message or "residual variance" in message


# -- The decline stands beside the update --------------------------------------------


def test_the_decline_stands_beside_the_update(
    store: ArtifactStore, campaign_id: str
) -> None:
    # Feature 176's decline and feature 178's update are one decision
    # spoken twice: the marginal IR is *computed* against a book that
    # is an argument (here, per candidate, at O(kT + k²)) and never
    # *cached* against a canonical one.  The update softens nothing —
    # the cache's decline answers the same verdict after any number of
    # updates have run.
    loaded = _working_campaign(store, campaign_id)
    factor = precompute_book_cholesky(loaded, BOOK)
    for candidate in CANDIDATES:
        evaluate_rank1_update(factor, loaded, candidate)
    cache = ReturnSeriesCache(store)
    with pytest.raises(ArtifactMarginalIRDeclinedError) as caught:
        cache.marginal_ir(campaign_id, "node-x", ",".join(BOOK))
    assert "declined_marginal_ir" in str(caught.value)


def test_the_policy_and_the_sizing_spell_the_sentence() -> None:
    # The decision, the figure and the shape it was read at, spelled
    # once so the docstrings, the constants and the timing test cannot
    # drift apart: O(kT + k²) at a six-member book over 48 shared
    # periods is 324 element operations — the count §9.3's "roughly
    # 40 µs" prices.
    assert "O(kT + k²)" in RANK1_UPDATE_POLICY
    assert "no canonical-book cache" in RANK1_UPDATE_POLICY
    assert RANK1_UPDATE_SIZING_BOOK == 6
    assert RANK1_UPDATE_SIZING_SAMPLE == 48
    assert (
        RANK1_UPDATE_SIZING_BOOK * RANK1_UPDATE_SIZING_SAMPLE
        + RANK1_UPDATE_SIZING_BOOK**2
        == 324
    )
    assert RANK1_UPDATE_COST_MICROSECONDS == 40.0


# -- The band holds ------------------------------------------------------------------


def test_the_whole_call_reads_inside_the_roughly_band() -> None:
    # §9.3's figure made checkable: at the sizing the figure was read
    # at, the whole call — validation, arithmetic and the answer's own
    # construction checks — reads at roughly twice the figure on the
    # reference interpreter, and the band holds it at five-fold, so a
    # regression to the O(k²T) covariance rebuild, the O(k³)
    # refactorisation or a per-candidate reload leaves the band by
    # multiples.  The reading is the minimum of a series of calls: the
    # minimum is the only estimator of a computation's own cost that
    # background load on a busy machine cannot inflate.
    rng = random.Random(178)
    k = RANK1_UPDATE_SIZING_BOOK
    count = RANK1_UPDATE_SIZING_SAMPLE
    days = tuple(
        dt.date(2026, 1, 5) + dt.timedelta(days=i) for i in range(count)
    )
    nodes = [f"node-{i:02d}" for i in range(k + 1)]
    vectors = {
        node: tuple(round(rng.gauss(0.0, 0.01), 6) for _ in range(count))
        for node in nodes
    }
    loaded = _resident(vectors, days, campaign_id="sizing")
    factor = precompute_book_cholesky(loaded, tuple(nodes[:k]))
    candidate = nodes[k]
    evaluate_rank1_update(factor, loaded, candidate)  # warm the paths
    best = math.inf
    for _ in range(31):
        started = time.perf_counter()
        evaluate_rank1_update(factor, loaded, candidate)
        best = min(best, time.perf_counter() - started)
    microseconds = best * 1e6
    assert microseconds >= 1.0, microseconds
    assert microseconds <= 5 * RANK1_UPDATE_COST_MICROSECONDS, microseconds
