"""bug_spec_pipeline_cross_section.xml, bug 2 — the permutation must respect listings.

*"The null oracle's block permutation moves symbols onto dates where they do
not exist, so a planted null can never be scored on a snapshot with
listings, and FDR calibration is impossible."*

Root cause, as the spec states it: ``block_indices`` is a permutation of
*positions*, and every caller that reconciled it against a cross-sectional
panel (``nulloracle.__init__``'s ``_stored_permutation``,
``orchestrator.__init__``'s ``_sidecar_backed_endpoint``) did it by swapping
whole date-rows — the entire cross-section of one date for the entire
cross-section of another. A symbol that only exists in one of the two rows
rides along anyway: HYPEUSDT's late-September returns, shuffled onto an
early-September date, are a target for a bar HYPEUSDT never had on that date.
:func:`evaluator.gate_targets`'s support rule (``evaluator._gate._check_support``)
refuses exactly that — every date's supplied cross-section must equal that
date's *aligned* one, no wider and no narrower — so every null node over a
snapshot whose universe changes inside the window fails the gate, and the KS
guard never sees a null score.

:func:`nulloracle.blockpermute.block_permute_cross_section` is the fix: it
permutes each symbol's own run of observations — the dates *that symbol* is
present on — rather than swapping whole rows between dates. A date's permuted
row therefore carries a symbol if and only if the unpermuted panel carries
that symbol on that date; membership never moves, so the result equals every
date's own cross-section exactly, which is what makes it pass
``gate_targets``'s strict support rule (not merely a subset of it — a
*subset* would still be refused as "missing", and a superset as "extra";
member­ship-preserving is the one shape that is neither).

Five claims, one test class each:

* a symbol listed in the last block is never placed on an earlier date;
* a symbol delisted mid-window is never placed after its delisting;
* a symbol present on every date is permuted exactly as the whole-row
  algorithm the fix replaces would have permuted it, under the same seed —
  no silent behaviour change for the dense, no-listings case;
* the same seed and block length reproduce the same panel;
* a null node's response, built from this permutation, passes
  :func:`evaluator.gate_targets` against the alignment it was asked on, for
  a window that includes a listing.

No test opens a network connection or writes outside a pytest temporary
directory (none is used — the whole suite is in-memory dates and floats),
and none shares mutable state across tests, so it is safe under
pytest-xdist.
"""

from __future__ import annotations

import datetime as dt
import sys
import uuid
from pathlib import Path

import pytest
from nulloracle import (
    OK,
    NullAssignment,
    NullSidecar,
    TargetEndpoint,
    TargetRequest,
)
from nulloracle.blockpermute import (
    DEFAULT_BLOCK_DAYS,
    block_indices,
    block_permute_cross_section,
)
from nulloracle.errors import KsGuardError

# This suite is the one place in the member that gates a null node's answer
# through the evaluator's own ``gate_targets`` — the cross-member seam the
# repo's Makefile names explicitly ("PP = extra colon-separated src roots
# for cross-member imports").  ``uv sync --all-packages`` already installs
# every workspace member editable into the one shared venv, so this import
# resolves under ``uv run`` with no extra wiring; the fallback below only
# matters for a bare ``pytest`` invocation that never synced the workspace.
try:
    import evaluator  # noqa: F401
except ImportError:  # pragma: no cover - exercised only outside the uv venv
    _EVALUATOR_SRC = str(
        Path(__file__).resolve().parents[2] / "evaluator" / "src"
    )
    if _EVALUATOR_SRC not in sys.path:
        sys.path.insert(0, _EVALUATOR_SRC)

from evaluator import (
    HORIZONS,
    AlignedTargets,
    EvaluatorGateError,
    OracleResponse,
    TargetSeries,
    gate_targets,
)

# -- Fixtures: a 45-day panel with one late listing, one mid-window delisting ----

FIRST_DAY = dt.date(2026, 1, 1)
PANEL_DAYS = 45
LISTING_POSITION = 40  # HYPEUSDT's first bar — inside the trailing block
DELISTING_POSITION = 10  # ZROUSDT's last bar — inside the first block


def _days(count: int = PANEL_DAYS) -> list[dt.date]:
    return [FIRST_DAY + dt.timedelta(days=i) for i in range(count)]


def _panel_with_listing_and_delisting() -> dict[dt.date, dict[str, float]]:
    """A panel where one symbol lists late and another delists early.

    ``AAVEUSDT`` is present on every day (the always-present control symbol
    the dense-case test pins). ``HYPEUSDT`` has its first bar at
    :data:`LISTING_POSITION`. ``ZROUSDT`` has its last bar at
    :data:`DELISTING_POSITION`. The values are distinct per symbol and
    position so a test can recover exactly which (date, symbol) pair a given
    value belongs to.
    """
    days = _days()
    panel: dict[dt.date, dict[str, float]] = {}
    for position, day in enumerate(days):
        row: dict[str, float] = {"AAVEUSDT": 0.001 * position}
        if position <= DELISTING_POSITION:
            row["ZROUSDT"] = 10.0 + 0.001 * position
        if position >= LISTING_POSITION:
            row["HYPEUSDT"] = 100.0 + 0.001 * position
        panel[day] = row
    return panel


def _dense_panel(seed_offset: float = 0.0) -> dict[dt.date, dict[str, float]]:
    """A panel where every symbol is present on every date — the "old algorithm" case."""
    days = _days()
    return {
        day: {
            "AAAUSDT": seed_offset + float(position),
            "BBBUSDT": seed_offset - float(position),
            "CCCUSDT": seed_offset + float(position) * 0.5,
        }
        for position, day in enumerate(days)
    }


def _old_whole_row_algorithm(
    panel: dict, *, seed: int, block_days: int
) -> dict[dt.date, dict[str, float]]:
    """The buggy whole-row swap this fix replaces, reimplemented for comparison.

    The same algorithm ``nulloracle.__init__._stored_permutation`` and
    ``orchestrator.__init__._sidecar_backed_endpoint._permute`` wrote: the
    day axis's block order is computed once with :func:`block_indices`, and
    each destination day is handed the *entire* row of whichever day the
    order drew — no regard for whether the drawn row's symbols are the
    destination day's own. Reproduced here (not imported — it lives in two
    files this bug's touches_files does not include) purely as the
    dense-case baseline :func:`block_permute_cross_section` must still match.
    """
    days = list(panel)
    rows = [panel[day] for day in days]
    order = block_indices(range(len(days)), seed=seed, block_days=block_days)
    return {days[p]: dict(rows[order[p]]) for p in range(len(days))}


# -- A symbol listed in the last block is never placed on an earlier date --------


class TestALateListingNeverMovesBeforeItsListing:
    def test_hype_never_appears_before_its_listing_position(self) -> None:
        days = _days()
        panel = _panel_with_listing_and_delisting()
        permuted = block_permute_cross_section(panel, seed=42, block_days=20)
        hype_days = [day for day in days if "HYPEUSDT" in permuted[day]]
        assert hype_days, "the listed symbol must still appear somewhere"
        assert all(days.index(day) >= LISTING_POSITION for day in hype_days)

    def test_every_date_hype_existed_on_still_carries_it(self) -> None:
        # Membership is exact, not merely "never too early": a date HYPEUSDT
        # really traded on must still carry it after permutation, or the
        # gate would refuse the answer as missing a symbol it asked for.
        days = _days()
        panel = _panel_with_listing_and_delisting()
        permuted = block_permute_cross_section(panel, seed=42, block_days=20)
        for position, day in enumerate(days):
            assert ("HYPEUSDT" in permuted[day]) == (position >= LISTING_POSITION)

    def test_hype_values_are_real_hype_values_not_invented(self) -> None:
        # Every value served for HYPEUSDT came from some date HYPEUSDT was
        # actually on — never zero-filled, never another symbol's value.
        days = _days()
        panel = _panel_with_listing_and_delisting()
        permuted = block_permute_cross_section(panel, seed=42, block_days=20)
        real_hype_values = {panel[day]["HYPEUSDT"] for day in days if "HYPEUSDT" in panel[day]}
        served_hype_values = {
            permuted[day]["HYPEUSDT"] for day in days if "HYPEUSDT" in permuted[day]
        }
        assert served_hype_values <= real_hype_values


# -- A symbol delisted mid-window is never placed after its delisting ------------


class TestAMidWindowDelistingNeverMovesPastIt:
    def test_zro_never_appears_after_its_delisting_position(self) -> None:
        days = _days()
        panel = _panel_with_listing_and_delisting()
        permuted = block_permute_cross_section(panel, seed=9, block_days=20)
        zro_days = [day for day in days if "ZROUSDT" in permuted[day]]
        assert zro_days
        assert all(days.index(day) <= DELISTING_POSITION for day in zro_days)

    def test_every_date_zro_existed_on_still_carries_it(self) -> None:
        days = _days()
        panel = _panel_with_listing_and_delisting()
        permuted = block_permute_cross_section(panel, seed=9, block_days=20)
        for position, day in enumerate(days):
            assert ("ZROUSDT" in permuted[day]) == (position <= DELISTING_POSITION)


# -- The result is exactly each date's own cross-section, for every symbol -------


class TestEveryDatesPermutedCrossSectionMatchesItsOwn:
    def test_membership_is_exact_for_the_whole_panel(self) -> None:
        # Not a subset-or-equal hedge: for this fix, the permuted row's
        # symbols equal the real row's symbols on every date, which is what
        # lets a null node pass evaluator.gate_targets's strict support rule.
        panel = _panel_with_listing_and_delisting()
        permuted = block_permute_cross_section(panel, seed=3, block_days=20)
        for day, row in panel.items():
            assert set(permuted[day]) == set(row)

    def test_the_whole_panel_s_dates_are_carried_and_no_others(self) -> None:
        panel = _panel_with_listing_and_delisting()
        permuted = block_permute_cross_section(panel, seed=3, block_days=20)
        assert set(permuted) == set(panel)


# -- Always-present symbols: no silent behaviour change ---------------------------


class TestAlwaysPresentSymbolsMatchTheOldAlgorithm:
    def test_a_fully_dense_panel_matches_the_whole_row_algorithm(self) -> None:
        panel = _dense_panel()
        new = block_permute_cross_section(panel, seed=1234, block_days=20)
        old = _old_whole_row_algorithm(panel, seed=1234, block_days=20)
        assert new == old

    def test_dense_symbols_match_even_beside_a_sparse_one(self) -> None:
        # The sparse symbol (HYPEUSDT, listed late) is permuted differently
        # from the whole-row algorithm by design — that is the fix. The
        # dense symbols sharing the same panel must still agree with it
        # exactly: this function's per-symbol treatment must not perturb a
        # symbol that was never the problem.
        panel = _panel_with_listing_and_delisting()
        new = block_permute_cross_section(panel, seed=1234, block_days=20)
        old = _old_whole_row_algorithm(panel, seed=1234, block_days=20)
        for day in panel:
            assert new[day]["AAVEUSDT"] == old[day]["AAVEUSDT"]

    def test_a_different_block_length_still_matches_when_dense(self) -> None:
        panel = _dense_panel(seed_offset=100.0)
        new = block_permute_cross_section(panel, seed=55, block_days=7)
        old = _old_whole_row_algorithm(panel, seed=55, block_days=7)
        assert new == old

    def test_the_default_block_length_is_used_when_omitted(self) -> None:
        panel = _dense_panel()
        assert block_permute_cross_section(panel, seed=1) == block_permute_cross_section(
            panel, seed=1, block_days=DEFAULT_BLOCK_DAYS
        )


# -- Determinism under the stored seed --------------------------------------------


class TestDeterminismUnderTheSeed:
    def test_the_same_seed_reproduces_the_same_panel(self) -> None:
        panel = _panel_with_listing_and_delisting()
        once = block_permute_cross_section(panel, seed=777, block_days=20)
        twice = block_permute_cross_section(panel, seed=777, block_days=20)
        assert once == twice

    def test_two_seeds_shuffle_differently(self) -> None:
        panel = _dense_panel()

        def _fold(permuted: dict) -> tuple:
            return tuple(
                (day, tuple(sorted(row.items())))
                for day, row in sorted(permuted.items())
            )

        outcomes = {
            _fold(block_permute_cross_section(panel, seed=seed, block_days=20))
            for seed in range(1, 11)
        }
        assert len(outcomes) > 1

    def test_within_block_adjacency_survives_for_a_dense_symbol(self) -> None:
        # The defining property block_permute itself pins, restated at the
        # panel grain: a symbol's own values inside one input block stay
        # adjacent and in order in the output, even though the block's
        # position among the others has moved.
        days = _days(60)
        panel = {
            day: {"AAAUSDT": float(position)} for position, day in enumerate(days)
        }
        permuted = block_permute_cross_section(panel, seed=8, block_days=15)
        ordered_values = [permuted[day]["AAAUSDT"] for day in days]
        successors = {
            (ordered_values[i], ordered_values[i + 1])
            for i in range(len(ordered_values) - 1)
        }
        for i in range(0, 60, 15):
            for j in range(i, i + 15 - 1):
                assert (float(j), float(j + 1)) in successors


# -- A null node over such a snapshot passes gate_targets -------------------------


def _as_oracle(panel: dict, *, seed: int, block_days: int):
    """A null branch's oracle seam: this fix's permutation, restricted to the ask.

    Mirrors what a real deployment's composed route does (§7.2): permute the
    whole panel once with the stored seed and block length, then answer only
    the dates and symbols the request actually named — the same restriction
    :class:`nulloracle.target.TargetEndpoint` makes against ``targets`` and
    ``symbols`` before the branch is served.
    """
    permuted = block_permute_cross_section(panel, seed=seed, block_days=block_days)

    def _oracle(request: object) -> OracleResponse:
        first, last = request.date_range  # type: ignore[attr-defined]
        asked = set(request.symbols)  # type: ignore[attr-defined]
        served = {
            day: {symbol: value for symbol, value in row.items() if symbol in asked}
            for day, row in permuted.items()
            if first <= day <= last
        }
        return OracleResponse(target_series=served, charges_budget=False)

    return _oracle


def _alignment_over(panel: dict, *, snapshot_name: str = "snap") -> AlignedTargets:
    """An :class:`AlignedTargets` carrying ``panel`` at horizon 1, empty elsewhere.

    ``gate_targets`` only asks the oracle for a horizon with coverage
    (``alignment.targets(horizon).dates()``), so pinning the panel at
    horizon 1 and leaving the other four horizons empty asks the oracle
    exactly once — the one ask this suite is about.
    """
    series = {
        horizon: TargetSeries(
            horizon=horizon,
            snapshot_name=snapshot_name,
            values=panel if horizon == 1 else {},
        )
        for horizon in HORIZONS
    }
    return AlignedTargets(
        snapshot_name=snapshot_name,
        rebalance_dates=tuple(sorted(panel)),
        series=series,
    )


class TestANullNodeOverSuchASnapshotPassesTheGate:
    def test_a_listing_and_a_delisting_both_pass_gate_targets(self) -> None:
        panel = _panel_with_listing_and_delisting()
        alignment = _alignment_over(panel)
        oracle = _as_oracle(panel, seed=11, block_days=20)
        gated = gate_targets(
            alignment, oracle, node_id="node-1", campaign_id="campaign-1", depth=3
        )
        assert gated.charges_budget is False
        assert gated.targets(1).dates() == alignment.targets(1).dates()

    def test_the_whole_row_algorithm_would_have_failed_the_same_gate(self) -> None:
        # The regression this suite guards: the algorithm this fix replaces
        # fails exactly the way the bug report quotes — an extra symbol on a
        # date that never had it. Pinned here so the fix cannot regress back
        # to the whole-row reading without this suite noticing.
        panel = _panel_with_listing_and_delisting()
        alignment = _alignment_over(panel)
        permuted = _old_whole_row_algorithm(panel, seed=11, block_days=20)

        def _broken_oracle(request: object) -> OracleResponse:
            first, last = request.date_range  # type: ignore[attr-defined]
            served = {
                day: dict(row) for day, row in permuted.items() if first <= day <= last
            }
            return OracleResponse(target_series=served, charges_budget=False)

        with pytest.raises(EvaluatorGateError, match="cross-section"):
            gate_targets(
                alignment,
                _broken_oracle,
                node_id="node-1",
                campaign_id="campaign-1",
                depth=3,
            )

    def test_a_dense_snapshot_with_no_listings_still_passes(self) -> None:
        # The control case: a snapshot with no universe change passes the
        # gate under the fix exactly as it did before — this is not a fix
        # that only works when something is wrong.
        panel = _dense_panel()
        alignment = _alignment_over(panel)
        oracle = _as_oracle(panel, seed=4, block_days=20)
        gated = gate_targets(
            alignment, oracle, node_id="node-2", campaign_id="campaign-1", depth=1
        )
        assert gated.charges_budget is False


# -- The permutation still refuses what block_permute refuses --------------------


class TestThePanelPermutationRefusesLikeItsSeriesTwin:
    def test_a_non_mapping_panel_is_refused(self) -> None:
        with pytest.raises(KsGuardError, match="mapping"):
            block_permute_cross_section([1.0, 2.0], seed=1, block_days=20)

    def test_an_empty_panel_is_refused(self) -> None:
        with pytest.raises(KsGuardError, match="non-empty"):
            block_permute_cross_section({}, seed=1, block_days=20)

    def test_a_non_mapping_row_is_refused(self) -> None:
        with pytest.raises(KsGuardError, match="symbol to forward"):
            block_permute_cross_section(
                {FIRST_DAY: [1.0, 2.0]}, seed=1, block_days=20
            )

    def test_a_non_finite_target_is_refused(self) -> None:
        with pytest.raises(KsGuardError, match="finite"):
            block_permute_cross_section(
                {FIRST_DAY: {"AAAUSDT": float("nan")}}, seed=1, block_days=20
            )

    def test_a_zero_block_length_is_refused(self) -> None:
        with pytest.raises(KsGuardError, match="positive integer"):
            block_permute_cross_section(
                {FIRST_DAY: {"AAAUSDT": 1.0}}, seed=1, block_days=0
            )

    def test_a_negative_seed_is_refused(self) -> None:
        with pytest.raises(KsGuardError, match="non-negative integer"):
            block_permute_cross_section(
                {FIRST_DAY: {"AAAUSDT": 1.0}}, seed=-1, block_days=20
            )


# -- The reproduction, literally: POST /target for a null node -------------------


class TestCallingTheTargetRouteForANullNode:
    """The bug report's own reproduction steps, against the real route.

    *"Call the target route for a null node over forward returns where one
    symbol is present only in the last block. The permuted series names
    that symbol on dates in earlier blocks."* Wires
    :func:`block_permute_cross_section` in as :class:`TargetEndpoint`'s
    ``permute`` seam — exactly how a deployment composes it (see
    ``nulloracle.__init__._stored_permutation``) — and posts a real request
    for a node the sidecar holds sealed as null.
    """

    def _request_for(self, node_id: str, days: list, all_symbols: list) -> TargetRequest:
        return TargetRequest(
            node_id=node_id,
            campaign_id=str(uuid.uuid4()),
            depth=3,
            horizon=1,
            symbols=all_symbols,
            date_range=(days[0], days[-1]),
        )

    def test_the_route_never_serves_hype_before_its_listing(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        days = _days()
        panel = _panel_with_listing_and_delisting()
        all_symbols = sorted({symbol for row in panel.values() for symbol in row})
        test_sidecar.write(
            [NullAssignment(node_id=node_id, is_null=True, perm_seed=11)]
        )
        endpoint = TargetEndpoint(
            test_sidecar,
            targets=lambda request: panel,
            permute=block_permute_cross_section,
        )
        response = endpoint.post(self._request_for(node_id, days, all_symbols))
        assert response.status == OK
        assert response.charges_budget is False
        for position, day in enumerate(days):
            served_day = response.target_series.get(day, {})
            assert ("HYPEUSDT" in served_day) == (position >= LISTING_POSITION)
            assert ("ZROUSDT" in served_day) == (position <= DELISTING_POSITION)

    def test_the_response_shape_is_identical_for_a_real_and_a_null_node(
        self, test_sidecar: NullSidecar, node_ids
    ) -> None:
        # PRD §4.2: nothing about the response's *shape* may vary with
        # is_null — same type, same fields, same dates and symbols covered.
        # Only the values (which this test never compares — that would be
        # the client-side null detector principle P2 forbids) and the
        # charges_budget directive may differ.
        real_node, null_node = node_ids(2)
        days = _days()
        panel = _panel_with_listing_and_delisting()
        all_symbols = sorted({symbol for row in panel.values() for symbol in row})
        test_sidecar.write(
            [
                NullAssignment(node_id=real_node, is_null=False, perm_seed=5),
                NullAssignment(node_id=null_node, is_null=True, perm_seed=5),
            ]
        )
        endpoint = TargetEndpoint(
            test_sidecar,
            targets=lambda request: panel,
            permute=block_permute_cross_section,
        )
        real_response = endpoint.post(self._request_for(real_node, days, all_symbols))
        null_response = endpoint.post(self._request_for(null_node, days, all_symbols))

        assert type(real_response) is type(null_response)
        assert real_response.status == null_response.status == OK
        assert real_response.charges_budget is True
        assert null_response.charges_budget is False
        assert set(real_response.target_series) == set(null_response.target_series)
        for day in real_response.target_series:
            assert set(real_response.target_series[day]) == set(
                null_response.target_series[day]
            )
