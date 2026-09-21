"""Feature 177: the book Cholesky factor, precomputed once per replay.

app_spec.xml, "Tree & Artifact Persistence", feature 177: *System
precomputes the book Cholesky factor once per replay, which returns a
reusable factor for every candidate.*  docs/nullius-tech-architecture.md
§9.3 states it as the arithmetic half of the replay bottleneck's
answer — *"the book is **fixed during a replay**, so precompute the
book's Cholesky factor once at ``O(k³)`` and every candidate is a
rank-1 update at ``O(kT + k²)`` — roughly 40 µs"* — and these tests
pin the precompute half as six facts, each one a way a careless
version of it would silently fail:

* **the factor is the factorization of the book's covariance** — the
  members' rows of the resident array, centered on their means,
  population ``1/T`` (the evaluator's own ``ddof=0`` coefficient),
  computed over the periods **every** member measured, factored into
  a lower triangle with a strictly positive diagonal whose product
  with its transpose is that covariance.
* **once means once** — two precomputes over one book answer
  identical bytes, whatever order the membership was spelled in and
  whether the array is the one held or a fresh load of the same
  campaign; and the factor takes no candidate, holds no residence
  and touches no I/O, so "once per replay" is a shape, not a hope.
* **the axis is the membership, canonically** — sorted, each member
  once, the campaign array's own row order, with the shared sample
  spelled beside it so feature 178's update aligns on the columns the
  factor was measured over.
* **positive definiteness is required, not patched** — a member that
  never varied, a duplicate, a linear combination, a book wider than
  its sample: each refuses naming the member or the shape, and no
  jitter is ever added, because a patched factor would feed every
  candidate an invented covariance and break the determinism §10.4
  pins.
* **the book must be a book of this campaign** — no members at all,
  a member named twice, a member the array holds no row for, members
  sharing no period every one measured: each refuses with the
  campaign and the member named.
* **the record is honest in both directions** — a valid value built
  by hand is answered, and every lying spelling of one (a ragged
  buffer, a non-zero upper triangle, a non-positive diagonal, a
  non-finite cell, an axis out of order, a sample too short for the
  membership) refuses rather than answering a book nobody factored.
"""

from __future__ import annotations

import array as _array
import datetime as dt
import inspect
import math
import shutil
from dataclasses import FrozenInstanceError

import pytest

pytest.importorskip(
    "pyarrow", reason="the factor precomputes over feature 174's Parquet load"
)
from artifacts import (
    BOOK_FACTOR_POLICY,
    FACTOR_TYPECODE,
    ArtifactBookFactorError,
    ArtifactCacheError,
    ArtifactPinError,
    ArtifactsError,
    ArtifactStore,
    ArtifactStoreError,
    BookCholesky,
    CampaignPins,
    CampaignReturns,
    ReturnRow,
    SignalReturns,
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

#: The working book — three members, one world, dyadic values chosen
#: so every float in the pipeline (float32 cells, ``fsum`` means,
#: centered products) is exact and the refusals below fire on exact
#: zero pivots rather than on rounding luck.
BOOK = ("node-a", "node-b", "node-c")

#: The candidates the replay scores against the book — nodes of the
#: same campaign the factor deliberately takes no notice of.
CANDIDATES = ("node-x", "node-y")


# -- Small builders, the 174 suite's own shapes -------------------------------------


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
    """A one-symbol panel whose T-vector is exactly ``values``.

    One symbol per date, so the equal-weight per-date mean feature
    174 densifies is the single ``post_cost_return`` itself — the
    cell the factor's arithmetic runs on is the value spelled here.
    """
    return _panel(
        node_id,
        tuple(_row(day, "AAA", value) for day, value in zip(days, values)),
    )


def _published(
    store: ArtifactStore,
    campaign_id: str,
    *panels: SignalReturns,
) -> None:
    """Persist and commit each panel — the state §9.3's load sweeps."""
    for panel in panels:
        persist_signal_returns(store, campaign_id, panel.node_id, panel)
        store.commit(campaign_id, panel.node_id)


ALL_DAYS = (D1, D2, D3, D4, D5, D6, D7, D8)

#: The working campaign's five T-vectors — three book members, two
#: candidates, all dyadic (every value a multiple of 1/16), so the
#: float32 cells, the ``fsum`` means and the centered products are
#: all exact and the hand arithmetic below mirrors the module's to
#: the last bit.
WORKING_VECTORS = {
    "node-a": (0.5, -0.5, 0.25, -0.25, 0.125, -0.125, 0.0625, -0.0625),
    "node-b": (0.25, 0.25, -0.125, -0.125, 0.5, 0.5, -0.25, -0.25),
    "node-c": (-0.125, 0.375, 0.5, -0.5, 0.25, -0.25, 0.0625, 0.1875),
    "node-x": (-0.5, 0.25, 0.125, 0.375, -0.25, 0.0625, -0.375, 0.4375),
    "node-y": (0.1875, -0.375, -0.0625, 0.4375, 0.375, -0.4375, 0.25, 0.125),
}


def _working_campaign(store: ArtifactStore, campaign_id: str) -> CampaignReturns:
    """Publish the five-node working campaign and load it resident."""
    _published(
        store,
        campaign_id,
        *(
            _vector_panel(node, ALL_DAYS, WORKING_VECTORS[node])
            for node in (*BOOK, *CANDIDATES)
        ),
    )
    return load_campaign_returns(store, campaign_id)


# -- Hand arithmetic, the module's own coefficient -----------------------------------


def _hand_covariance(
    loaded: CampaignReturns,
    members: tuple[str, ...],
    periods: tuple[dt.date, ...],
) -> list[list[float]]:
    """The book's covariance as §9.3's sentence implies it: by hand.

    The evaluator's own coefficient, spelled independently of the
    module: the members' cells over the sample columns (the float32
    cells the array holds, widened exactly), centered on their
    ``fsum`` means, products summed with ``fsum``, population ``1/T``.
    """
    column_of = {day: column for column, day in enumerate(loaded.periods)}
    rows = {node: loaded.row(node) for node in members}
    count = len(periods)
    centered = {}
    for node in members:
        cells = [rows[node][column_of[day]] for day in periods]
        mean = math.fsum(cells) / count
        centered[node] = [value - mean for value in cells]
    k = len(members)
    sigma = [[0.0] * k for _ in range(k)]
    for i in range(k):
        for j in range(k):
            sigma[i][j] = (
                math.fsum(
                    centered[members[i]][t] * centered[members[j]][t]
                    for t in range(count)
                )
                / count
            )
    return sigma


def _reconstructed(factor: BookCholesky) -> list[list[float]]:
    """``L·Lᵀ`` — the covariance the lower triangle factors, rebuilt."""
    k = factor.shape[0]
    cells = factor.factor
    return [
        [
            math.fsum(
                cells[i * k + m] * cells[j * k + m]
                for m in range(min(i, j) + 1)
            )
            for j in range(k)
        ]
        for i in range(k)
    ]


def _refused(call, *args, **kwargs) -> str:
    """The message of the refusal a call answers, as text."""
    with pytest.raises(ArtifactBookFactorError) as caught:
        call(*args, **kwargs)
    return str(caught.value)


# -- The factor is the factorization of the book's covariance ------------------------


def test_the_factor_factors_the_book_covariance(
    store: ArtifactStore, campaign_id: str
) -> None:
    # §9.3's precompute, verified against the arithmetic it claims to
    # precompute: L is lower-triangular with a strictly positive
    # diagonal, and L·Lᵀ is the members' centered population
    # covariance (1/T, the evaluator's ddof=0) over the shared sample.
    loaded = _working_campaign(store, campaign_id)
    factor = precompute_book_cholesky(loaded, BOOK)
    sigma = _hand_covariance(loaded, BOOK, ALL_DAYS)
    assert factor.shape == (3, 3)
    assert factor.node_ids == BOOK
    assert factor.periods == ALL_DAYS
    assert factor.campaign_id == campaign_id
    assert factor.horizon == 1
    k = 3
    cells = factor.factor
    for i in range(k):
        assert cells[i * k + i] > 0.0
        for j in range(k):
            assert j <= i or cells[i * k + j] == 0.0
    rebuilt = _reconstructed(factor)
    for i in range(k):
        for j in range(k):
            assert rebuilt[i][j] == pytest.approx(sigma[i][j], rel=1e-12)


def test_a_one_member_book_factors_its_own_variance(
    store: ArtifactStore, campaign_id: str
) -> None:
    # The smallest book: k = 1 over T = 8, where the factor is one
    # cell — the square root of the member's own population variance,
    # the same arithmetic ir_standalone's denominator is made of.  The
    # module's op order is mirrored exactly, so the equality is exact.
    loaded = _working_campaign(store, campaign_id)
    factor = precompute_book_cholesky(loaded, ("node-a",))
    row = loaded.row("node-a")
    mean = math.fsum(row) / len(row)
    deviations = [value - mean for value in row]
    variance = math.fsum(d * d for d in deviations) / len(row)
    assert factor.shape == (1, 1)
    assert factor.factor[0] == math.sqrt(variance)


def test_the_sample_is_the_periods_every_member_measured(
    store: ArtifactStore, campaign_id: str
) -> None:
    # The resident array is the union axis with NaN for absence, and a
    # covariance is defined over one sample measured together — so the
    # factor's sample is the intersection of the members' measured
    # columns, and the covariance is computed over exactly those,
    # never over the union with absence dressed as zero.
    _published(
        store,
        campaign_id,
        _vector_panel("node-a", (D1, D2, D3, D4, D5), (0.5, -0.25, 0.125, -0.5, 0.25)),
        _vector_panel("node-b", (D3, D4, D5, D6, D7), (-0.5, 0.25, 0.125, -0.375, 0.4375)),
    )
    loaded = load_campaign_returns(store, campaign_id)
    factor = precompute_book_cholesky(loaded, ("node-a", "node-b"))
    shared = (D3, D4, D5)
    assert factor.periods == shared
    sigma = _hand_covariance(loaded, ("node-a", "node-b"), shared)
    rebuilt = _reconstructed(factor)
    for i in range(2):
        for j in range(2):
            assert rebuilt[i][j] == pytest.approx(sigma[i][j], rel=1e-12)


def test_the_axis_is_the_membership_in_canonical_order(
    store: ArtifactStore, campaign_id: str
) -> None:
    # A policy commits to its book in an order; the commit order is
    # not part of the factor's identity.  The axis is the membership
    # in the campaign array's own sorted order, so two spellings of
    # one book answer one factor — determinism (§10.4) that does not
    # depend on the caller remembering how it spelled the book.
    loaded = _working_campaign(store, campaign_id)
    forward = precompute_book_cholesky(loaded, BOOK)
    shuffled = precompute_book_cholesky(loaded, ("node-c", "node-a", "node-b"))
    as_list = precompute_book_cholesky(loaded, ["node-b", "node-c", "node-a"])
    assert forward.node_ids == shuffled.node_ids == as_list.node_ids == BOOK
    assert forward == shuffled == as_list


# -- Once means once: reusable for every candidate, pure over the array ----------------


def test_two_precomputes_over_one_book_answer_identical_bytes(
    store: ArtifactStore, campaign_id: str
) -> None:
    # §9.3's "precompute ... once" rests on the precompute being a
    # pure function of the resident array and the membership: every
    # sum is fsum, so the arithmetic is exactly rounded, and the
    # second precompute — of the same array, or of a fresh load of
    # the same campaign — answers the buffer the first one did, byte
    # for byte.
    loaded = _working_campaign(store, campaign_id)
    first = precompute_book_cholesky(loaded, BOOK)
    second = precompute_book_cholesky(loaded, BOOK)
    fresh_load = load_campaign_returns(store, campaign_id)
    third = precompute_book_cholesky(fresh_load, BOOK)
    assert first == second == third
    assert first.factor == second.factor == third.factor


def test_the_factor_is_pure_over_the_resident_array(
    store: ArtifactStore, campaign_id: str
) -> None:
    # The precompute touches no store and no filesystem — it is a
    # function of the array the caller holds, which is the point of
    # running it over the pinned buffer: the campaign's Parquet can
    # be cold by the time the book is fixed, and the factor still
    # answers.
    loaded = _working_campaign(store, campaign_id)
    before = precompute_book_cholesky(loaded, BOOK)
    shutil.rmtree(store.root / campaign_id)
    after = precompute_book_cholesky(loaded, BOOK)
    assert after == before


def test_one_factor_serves_every_candidate(
    store: ArtifactStore, campaign_id: str
) -> None:
    # The feature's sentence, as one behaviour: the factor is computed
    # from the book alone, before any candidate is named, and the
    # same object is what every candidate evaluation consults — the
    # candidates are rows of the same array, and none of them is an
    # input to the precompute.
    loaded = _working_campaign(store, campaign_id)
    factor = precompute_book_cholesky(loaded, BOOK)
    assert factor.node_ids == BOOK
    for candidate in CANDIDATES:
        assert candidate in loaded.node_ids
        assert candidate not in factor.node_ids
        assert factor.shape == (3, 3)
        assert factor.campaign_id == campaign_id
    parameters = inspect.signature(precompute_book_cholesky).parameters
    assert set(parameters) == {"returns", "node_ids"}
    assert "candidate" not in parameters


# -- Positive definiteness is required, not patched -----------------------------------


def test_a_duplicate_member_refuses_with_the_pivot_named(
    store: ArtifactStore, campaign_id: str
) -> None:
    # A book holding a signal twice — the exact accident §14.1's
    # anti-convergence clause expects search to keep proposing — has
    # a singular covariance: the duplicate's pivot is exactly zero
    # (the values are dyadic and orthogonal, so the arithmetic is
    # exact, not lucky), and the refusal names the member and refuses
    # to patch: no jitter, ever.
    _published(
        store,
        campaign_id,
        _vector_panel("node-a", ALL_DAYS[:4], (0.5, -0.5, 0.5, -0.5)),
        _vector_panel("node-b", ALL_DAYS[:4], (0.25, 0.25, -0.25, -0.25)),
        _vector_panel("node-c", ALL_DAYS[:4], (0.5, -0.5, 0.5, -0.5)),
    )
    loaded = load_campaign_returns(store, campaign_id)
    message = _refused(precompute_book_cholesky, loaded, BOOK)
    assert "node-c" in message
    assert "linearly dependent" in message
    assert "not positive" in message
    assert "no jitter is added" in message


def test_a_member_that_never_varied_refuses(
    store: ArtifactStore, campaign_id: str
) -> None:
    # A constant signal has zero variance — there is no factor of a
    # constant, and the refusal names the member rather than dividing
    # by a zero the arithmetic would have to invent.
    _published(
        store,
        campaign_id,
        _vector_panel("node-a", ALL_DAYS[:4], (0.5, -0.5, 0.5, -0.5)),
        _vector_panel("node-z", ALL_DAYS[:4], (0.25, 0.25, 0.25, 0.25)),
    )
    loaded = load_campaign_returns(store, campaign_id)
    message = _refused(precompute_book_cholesky, loaded, ("node-a", "node-z"))
    assert "node-z" in message
    assert "never varied" in message
    assert campaign_id in message


def test_a_book_wider_than_its_sample_refuses(
    store: ArtifactStore, campaign_id: str
) -> None:
    # Centering leaves each member's T-vector in the (T − 1)-dimensional
    # subspace orthogonal to the ones vector, so k independent members
    # need T ≥ k + 1 — a shape fact, refused before the arithmetic
    # tries, because the covariance of a book this wide over a sample
    # this short is singular by construction.
    _published(
        store,
        campaign_id,
        _vector_panel("node-a", ALL_DAYS[:3], (0.5, -0.5, 0.25)),
        _vector_panel("node-b", ALL_DAYS[:3], (-0.25, 0.5, -0.5)),
        _vector_panel("node-c", ALL_DAYS[:3], (0.125, -0.25, 0.5)),
    )
    loaded = load_campaign_returns(store, campaign_id)
    message = _refused(precompute_book_cholesky, loaded, BOOK)
    assert campaign_id in message
    assert "3 members over 3 shared periods" in message
    assert "T ≥ k + 1" in message


# -- The book must be a book of this campaign ------------------------------------------


def test_the_empty_book_refuses(store: ArtifactStore, campaign_id: str) -> None:
    # An empty book has no covariance to factor — the evaluator's own
    # stance (feature 83 refuses a book of zero signals the same way),
    # with the instead spelled out: the candidate-alone question is
    # feature 80's ir_standalone, and the replay precomputes when the
    # book holds its first committed member.
    loaded = _working_campaign(store, campaign_id)
    message = _refused(precompute_book_cholesky, loaded, ())
    assert "holds no members" in message
    assert "ir_standalone" in message


def test_a_member_named_twice_refuses(
    store: ArtifactStore, campaign_id: str
) -> None:
    # A repeated member would ask one T-vector to carry two dimensions
    # of the book — the covariance is singular by construction, and
    # the refusal fires before the arithmetic tries, naming the node.
    loaded = _working_campaign(store, campaign_id)
    message = _refused(
        precompute_book_cholesky, loaded, ("node-a", "node-b", "node-a")
    )
    assert "node-a" in message
    assert "each committed once" in message
    assert "singular by construction" in message


def test_a_member_the_array_does_not_hold_refuses(
    store: ArtifactStore, campaign_id: str
) -> None:
    # The book's members are picks this campaign measured — rows of
    # the very array the replay pinned — and a foreign node id is
    # refused naming it and the campaign rather than answered as a
    # row of zeros no panel measured.
    loaded = _working_campaign(store, campaign_id)
    message = _refused(
        precompute_book_cholesky, loaded, ("node-a", "node-elsewhere")
    )
    assert "node-elsewhere" in message
    assert campaign_id in message
    assert "holds no row for" in message


def test_members_sharing_no_period_refuse(
    store: ArtifactStore, campaign_id: str
) -> None:
    # A covariance is defined over one sample measured together: two
    # members whose measured windows never overlap are measurements
    # no single factor is defined over, and the refusal spells each
    # member's coverage so the caller can see the gap.
    _published(
        store,
        campaign_id,
        _vector_panel("node-p", (D1, D2), (0.5, -0.25)),
        _vector_panel("node-q", (D5, D6), (-0.5, 0.25)),
    )
    loaded = load_campaign_returns(store, campaign_id)
    message = _refused(precompute_book_cholesky, loaded, ("node-p", "node-q"))
    assert campaign_id in message
    assert "share no period every one of them measured" in message
    assert D1.isoformat() in message
    assert D5.isoformat() in message


def test_a_non_resident_array_refuses(
    store: ArtifactStore, campaign_id: str
) -> None:
    # The precompute's only input contract: it runs over one resident
    # campaign array — feature 174's load, feature 175's pin — and a
    # caller handing it anything else is refused before any member is
    # examined, because there is no second decoder to trust.
    message = _refused(
        precompute_book_cholesky,
        {"campaign_id": campaign_id},  # type: ignore[arg-type]
        ("node-a",),
    )
    assert "CampaignReturns" in message
    assert "dict" in message


# -- The record is honest in both directions -------------------------------------------


def _hand_factor() -> _array.array:
    """A valid 2×2 lower triangle: diag 0.5 and 0.25, mirror zero."""
    return _array.array(FACTOR_TYPECODE, [0.5, 0.0, 0.0, 0.25])


def _hand_built(factor: _array.array) -> BookCholesky:
    return BookCholesky(
        campaign_id="camp",
        horizon=1,
        node_ids=("node-a", "node-b"),
        periods=(D1, D2, D3, D4),
        factor=factor,
    )


def test_a_valid_hand_built_factor_is_answered() -> None:
    # The record is public and validates rather than gates: a value
    # that IS a factor — float64, k² cells, zero above the diagonal,
    # strictly positive on it, over a sample wide enough for the
    # membership — is answered as the factor it is, shape and
    # footprint included.
    record = _hand_built(_hand_factor())
    assert record.shape == (2, 2)
    assert record.node_ids == ("node-a", "node-b")
    assert record.periods == (D1, D2, D3, D4)
    assert record.factor == _hand_factor()
    assert record.footprint_bytes == 4 * 8


@pytest.mark.parametrize(
    "lie,expected",
    [
        (("node-b", "node-a"), "sorted"),  # axis out of canonical order
        (("node-a", "node-a"), "each committed once"),  # a member twice
        ((), "holds no members"),  # no book at all
    ],
    ids=["unsorted-axis", "repeated-member", "empty-membership"],
)
def test_lying_axes_refuse(lie: tuple[str, ...], expected: str) -> None:
    with pytest.raises(ArtifactBookFactorError, match=expected):
        _hand_built_with_members(lie)


def _hand_built_with_members(members: tuple[str, ...]) -> BookCholesky:
    return BookCholesky(
        campaign_id="camp",
        horizon=1,
        node_ids=members,
        periods=(D1, D2, D3, D4),
        factor=_hand_factor() if len(members) == 2 else _array.array(
            FACTOR_TYPECODE, [0.5]
        ),
    )


def test_a_sample_too_short_for_the_membership_refuses() -> None:
    # The record's own copy of the shape rule the precompute refuses
    # by: k members need T ≥ k + 1 shared periods, because centering
    # leaves each T-vector in T − 1 dimensions.
    with pytest.raises(ArtifactBookFactorError) as caught:
        BookCholesky(
            campaign_id="camp",
            horizon=1,
            node_ids=("node-a", "node-b"),
            periods=(D1, D2),
            factor=_hand_factor(),
        )
    message = str(caught.value)
    assert "at least 3 periods" in message
    assert "singular by construction" in message


def test_an_empty_sample_refuses() -> None:
    with pytest.raises(ArtifactBookFactorError, match="cannot be empty"):
        BookCholesky(
            campaign_id="camp",
            horizon=1,
            node_ids=("node-a",),
            periods=(),
            factor=_array.array(FACTOR_TYPECODE, [0.5]),
        )


@pytest.mark.parametrize(
    "factor,expected",
    [
        (_array.array("f", [0.5, 0.0, 0.0, 0.25]), "float64"),
        (_array.array(FACTOR_TYPECODE, [0.5, 0.0, 0.0]), "4 cells"),
        ([0.5, 0.0, 0.0, 0.25], "array.array"),
        (_array.array(FACTOR_TYPECODE, [0.5, 0.25, 0.0, 0.25]), "above the diagonal"),
        (_array.array(FACTOR_TYPECODE, [0.0, 0.0, 0.0, 0.25]), "strictly positive"),
        (_array.array(FACTOR_TYPECODE, [-0.5, 0.0, 0.0, 0.25]), "strictly"),
        (_array.array(FACTOR_TYPECODE, [float("nan"), 0.0, 0.0, 0.25]), "non-finite"),
        (_array.array(FACTOR_TYPECODE, [float("inf"), 0.0, 0.0, 0.25]), "non-finite"),
    ],
    ids=[
        "float32-typecode",
        "ragged-length",
        "not-an-array",
        "upper-triangle-nonzero",
        "zero-diagonal",
        "negative-diagonal",
        "nan-cell",
        "inf-cell",
    ],
)
def test_lying_buffers_refuse(factor: object, expected: str) -> None:
    # The buffer must be the factor the precompute answers: float64,
    # k² cells, zero above the diagonal, strictly positive on it, and
    # finite throughout — each lie named with the cell and member it
    # is about, so a hand-built value fails here rather than
    # downstream, inside feature 178's update.
    with pytest.raises(ArtifactBookFactorError) as caught:
        _hand_built(factor)  # type: ignore[arg-type]
    assert expected in str(caught.value)


def test_a_sample_of_instants_or_out_of_order_refuses() -> None:
    # A datetime is a date in Python and would pass a naive check,
    # but a column keyed by an instant is one no rebalance date can
    # address — and an unsorted or repeated sample is not the axis
    # the precompute answers.
    with pytest.raises(ArtifactBookFactorError, match="calendar dates"):
        BookCholesky(
            campaign_id="camp",
            horizon=1,
            node_ids=("node-a",),
            periods=(D1, dt.datetime(2026, 1, 6, 12, 0, tzinfo=dt.UTC), D3),
            factor=_array.array(FACTOR_TYPECODE, [0.5]),
        )
    with pytest.raises(ArtifactBookFactorError, match="sorted shared sample"):
        BookCholesky(
            campaign_id="camp",
            horizon=1,
            node_ids=("node-a",),
            periods=(D2, D1, D3),
            factor=_array.array(FACTOR_TYPECODE, [0.5]),
        )


def test_a_factor_that_cannot_name_its_campaign_refuses() -> None:
    with pytest.raises(ArtifactBookFactorError, match="names the campaign"):
        BookCholesky(
            campaign_id="  ",
            horizon=1,
            node_ids=("node-a",),
            periods=(D1, D2),
            factor=_array.array(FACTOR_TYPECODE, [0.5]),
        )


def test_a_bogus_horizon_refuses_by_the_loads_own_rule() -> None:
    # The horizon is feature 174's axis and keeps its one spelling of
    # the rule: a horizon that is not a positive period count is
    # refused by the load's own vocabulary, not re-spelled here.
    with pytest.raises(ArtifactStoreError):
        BookCholesky(
            campaign_id="camp",
            horizon=0,
            node_ids=("node-a",),
            periods=(D1, D2),
            factor=_array.array(FACTOR_TYPECODE, [0.5]),
        )


def test_the_record_is_frozen() -> None:
    # The value a replay threads to every candidate is immutable —
    # there is no state to release and no field to edit into a
    # different book's factor mid-replay.
    record = _hand_built(_hand_factor())
    with pytest.raises(FrozenInstanceError):
        record.campaign_id = "other"  # type: ignore[misc]


# -- float64, the footprint, and the pin the replay holds ------------------------------


def test_the_factor_keeps_float64_and_measures_its_footprint(
    store: ArtifactStore, campaign_id: str
) -> None:
    # The resident array narrowed to float32 because §9.3 sizes its
    # residency; the factor is the arithmetic and keeps the double —
    # k² cells × 8 B, measured, so an operator accounting a replay's
    # residence reads the array's footprint and the factor's side by
    # side.  At the k = 500 §9.3's sizing never asks of a book, that
    # arithmetic is 2,000,000 bytes — 2 MB beside the 4 MB array.
    loaded = _working_campaign(store, campaign_id)
    factor = precompute_book_cholesky(loaded, BOOK)
    assert FACTOR_TYPECODE == "d"
    assert factor.factor.typecode == FACTOR_TYPECODE
    assert factor.factor.itemsize == 8
    assert factor.footprint_bytes == 3 * 3 * 8
    assert 500 * 500 * 8 == 2_000_000


def test_the_factor_composes_with_a_pin_and_outlives_it(
    store: ArtifactStore, campaign_id: str
) -> None:
    # The replay reaches the precompute through the hold §9.3 says
    # several consumers share (the sweep, this factor, feature 178's
    # updates), and the factor is a value, not a residence: releasing
    # the pin returns the array's RAM to the arena's accounting and
    # leaves the derived factor exactly what it was — the replay owns
    # it for the duration of its run, and nothing here outlives that.
    _working_campaign(store, campaign_id)
    arena = CampaignPins(store)
    with arena.pin(campaign_id) as resident:
        inside = precompute_book_cholesky(resident, BOOK)
    assert arena.footprint_bytes == 0
    assert inside.shape == (3, 3)
    assert inside.footprint_bytes == 3 * 3 * 8
    again = precompute_book_cholesky(arena.pin(campaign_id).returns, BOOK)
    assert again == inside


# -- The vocabularies around the feature -----------------------------------------------


def test_refusals_are_their_own_class_in_the_taxonomy() -> None:
    # Feature 177's contract is its own class in the member's
    # taxonomy — the honesty of one derived arithmetic, split from
    # the cache's content policy (176) and the pins' lifetime policy
    # (175) the way they split from each other — and catchable by the
    # member's base like all of them.
    assert issubclass(ArtifactBookFactorError, ArtifactsError)
    assert not issubclass(ArtifactBookFactorError, ArtifactCacheError)
    assert not issubclass(ArtifactBookFactorError, ArtifactPinError)
    with pytest.raises(ArtifactsError):
        precompute_book_cholesky("not-an-array", ("node-a",))  # type: ignore[arg-type]


def test_the_policy_is_spelled_once() -> None:
    # The precompute's policy is a sentence, not a type, and it is
    # quoted by every seam that states it — pinned here so the
    # module's docstrings and the feature's sentence cannot drift
    # apart on what precomputing once means.
    assert BOOK_FACTOR_POLICY == (
        "precompute the book's Cholesky factor once per replay at O(k³), "
        "over the covariance of its members' T-vectors on the periods they "
        "share, and hand every candidate the same reusable factor — no "
        "book-keyed factor residence exists"
    )


def test_the_module_surface_is_the_record_the_precompute_and_the_policy() -> None:
    # The structural half of the value-not-residence policy: the
    # module's public surface is exactly the record, the precompute
    # and the policy/typecode spellings — there is no entry point for
    # installing a value nothing asked for, no keyed residence for a
    # book, and no second spelling of the precompute a later feature
    # could grow here by accident.
    from artifacts import _factor

    assert set(_factor.__all__) == {
        "BOOK_FACTOR_POLICY",
        "FACTOR_TYPECODE",
        "BookCholesky",
        "precompute_book_cholesky",
    }
    record = BookCholesky.__new__(BookCholesky)  # no I/O
    for second_spelling in (
        "update",
        "rank_one",
        "cache",
        "put",
        "store",
        "memoize",
        "evict",
        "install",
        "marginal_ir",
    ):
        assert not hasattr(record, second_spelling), second_spelling


def test_the_new_names_are_exported_from_the_member() -> None:
    # The public API feature 178's updates and the replay path reach.
    # A name that exists in ``_factor`` and not here is a spelling
    # callers would have to reach into a private module for.
    import artifacts

    for name in (
        "BOOK_FACTOR_POLICY",
        "FACTOR_TYPECODE",
        "BookCholesky",
        "precompute_book_cholesky",
        "ArtifactBookFactorError",
    ):
        assert name in artifacts.__all__, name
        assert hasattr(artifacts, name), name
