"""Feature 126 — the label-permutation probe, against the properties it pins.

app_spec.xml: *"System scores a candidate against label-permuted targets as a
second independent leakage probe, which returns a pass or fail verdict."*  The
sentence has four parts and each one has tests below: it *scores*, the targets
are *label-permuted*, it is a *second* probe rather than a restatement of the
first, and it returns a *pass or fail verdict* rather than an exception.

**The complementarity tests are the load-bearing ones**, and they are the
reason this file is not a second copy of ``test_time_shuffle.py``.  A probe
that merely re-ran the first one would pass every "is it a derangement" and
"does it reject leakage" assertion here and still be worthless, so the two
tests that matter most are
:func:`test_a_whole_sample_symbol_leak_escapes_the_label_probe` — feature 133's
canonical leak, which the first probe rejects at better than 2x its bar and
this one lets through — and
:func:`test_a_date_local_cross_sectional_leak_escapes_the_time_shuffle`, its
mirror, which the first probe cannot see at all and this one rejects at better
than 3x.  Each names the *other* probe's verdict in the same test, so neither
claim can be satisfied by weakening the probe under test alone.

The module's other pinned claims are tested beside those: the per-date
derangement (every label moves, within its own date, independently per date),
the threshold's delegation to feature 125's closed form, the ten field names
feature 131 reads a poisoning from, the no-wall-clock determinism contract of
§12, and the refusals — which must be *refusals* and not ``False``, because a
ledger has to tell "the probe measured and passed" from "the probe could not
measure at all".
"""

from __future__ import annotations

import datetime as dt
import math
import random

import pytest
from _panels import gaussian_panel, monday, symbols
from tripwires import (
    DEFAULT_LABEL_LEVEL,
    DEFAULT_LABEL_SEED,
    DEFAULT_SHUFFLE_LEVEL,
    HORIZONS,
    LABEL_PERMUTE_NAME,
    TIME_SHUFFLE_NAME,
    TRIPWIRE_OUTCOMES,
    LabelPermuteVerdict,
    TimeShuffleTripwire,
    TripwirePanelError,
    TripwireStatisticError,
    label_permute_pairing,
    label_permute_threshold,
    permuted_book_sharpe,
    run_label_permute_tripwire,
    run_time_shuffle_tripwire,
)


def _clean_candidate(
    grid: list[dt.date], names: list[str], *, seed: int = 3
) -> tuple[dict, dict]:
    """A candidate with no relationship to its targets — scores, bundle.

    The targets are drawn once and the scores from a *different* stream, so
    the two panels are independent by construction: this is the null the probe
    is supposed to pass.  The bundle carries every horizon feature 80 pins,
    all pointing at the one series, so the horizon-resolution policy is
    exercised rather than sidestepped — and it resolves to 1, the shortest.
    """
    targets = gaussian_panel(grid, names, seed=seed + 1)
    scores = gaussian_panel(grid, names, seed=seed + 2)
    return scores, {horizon: targets for horizon in HORIZONS}


def _date_local_leak(
    grid: list[dt.date], names: list[str], *, seed: int = 5, load: float = 1.0
) -> tuple[dict, dict]:
    """The leak the *time shuffle* cannot see — scores, targets.

    Each date draws one cross-sectional component that is **the same on every
    symbol in that date**, and both panels carry it: the returns have a
    date-local factor and the scores are a date-level reading of it.  This is
    the shape of a cross-sectional normalisation the candidate was never
    supposed to see — it knows which date it is, not which symbol — so
    re-dating whole cross-sections (feature 125's permutation) cannot disturb
    the pairing while permuting labels *within* a date destroys it.

    ``load`` scales the date-local component's share of the returns against a
    symbol-local noise floor, so a caller can build the diluted version as
    well as the pure one.
    """
    rng = random.Random(seed)
    level = {day: rng.gauss(0.0, 1.0) for day in grid}
    scores = {day: {name: level[day] for name in names} for day in grid}
    targets = {
        day: {
            name: load * level[day] + rng.gauss(0.0, 1.0) for name in names
        }
        for day in grid
    }
    return scores, {horizon: targets for horizon in HORIZONS}


# -- The permutation moves every label, within its own date --------------------


def test_the_pairing_moves_every_label_within_its_own_date(
    grid: list[dt.date], symbols: list[str]
) -> None:
    pairing = label_permute_pairing(
        {day: symbols for day in grid}, seed=DEFAULT_LABEL_SEED
    )
    assert set(pairing) == set(grid)
    for labels in pairing.values():
        # A permutation of *this* date's labels, not of some other date's:
        # the values are the same symbol set as the keys.
        assert set(labels) == set(symbols)
        assert set(labels.values()) == set(symbols)
        # ...and a derangement: no symbol keeps its own return.
        assert all(source != moved for source, moved in labels.items())


def test_each_date_draws_its_own_permutation(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # One permutation per date, not one global relabelling. A global rename
    # would pair the same two symbols on every date, which leaves a per-symbol
    # cross-date structure reproducible — exactly what a date-local leak can
    # hide behind. Distinct draws across dates are the observable signature.
    pairing = label_permute_pairing(
        {day: symbols for day in grid}, seed=DEFAULT_LABEL_SEED
    )
    drawn = [tuple(sorted(labels.items())) for labels in pairing.values()]
    assert len(set(drawn)) > 1


def test_the_pairing_is_a_pure_function_of_the_grid_and_the_seed(
    grid: list[dt.date], symbols: list[str]
) -> None:
    sections = {day: symbols for day in grid}
    first = label_permute_pairing(sections, seed=DEFAULT_LABEL_SEED)
    second = label_permute_pairing(sections, seed=DEFAULT_LABEL_SEED)
    assert first == second
    # ...and the mapping order the caller happened to use does not matter,
    # because the draw is over sorted dates and sorted symbols.
    shuffled = {day: list(reversed(symbols)) for day in reversed(grid)}
    assert label_permute_pairing(shuffled, seed=DEFAULT_LABEL_SEED) == first


def test_a_different_seed_is_a_different_permutation(
    grid: list[dt.date], symbols: list[str]
) -> None:
    sections = {day: symbols for day in grid}
    assert label_permute_pairing(sections, seed=1) != label_permute_pairing(
        sections, seed=2
    )


def test_the_pairing_accepts_iso_date_keys(grid: list[dt.date], symbols: list[str]) -> None:
    # The courtesy every evaluator step extends the rebalance grid.
    pairing = label_permute_pairing(
        {day.isoformat(): symbols for day in grid}, seed=DEFAULT_LABEL_SEED
    )
    assert set(pairing) == set(grid)


def test_a_two_symbol_cross_section_is_permuted_by_swapping(
    grid: list[dt.date],
) -> None:
    # The smallest cross-section a derangement exists over, and the case an
    # implementation that samples naively loops forever on.
    pairing = label_permute_pairing(
        {day: ["A", "B"] for day in grid}, seed=DEFAULT_LABEL_SEED
    )
    assert all(labels == {"A": "B", "B": "A"} for labels in pairing.values())


def test_a_one_symbol_cross_section_is_refused() -> None:
    with pytest.raises(TripwirePanelError, match="at least two"):
        label_permute_pairing({dt.date(2024, 1, 1): ["A"]})


def test_the_pairing_refuses_a_non_integer_seed(symbols: list[str]) -> None:
    with pytest.raises(TripwirePanelError, match="integer"):
        label_permute_pairing({dt.date(2024, 1, 1): symbols}, seed="0")  # type: ignore[arg-type]
    # A bool is an int to Python and names no stream to draw from.
    with pytest.raises(TripwirePanelError, match="integer"):
        label_permute_pairing({dt.date(2024, 1, 1): symbols}, seed=True)  # type: ignore[arg-type]


def test_the_pairing_refuses_a_bare_iterable_of_sections(
    grid: list[dt.date], symbols: list[str]
) -> None:
    with pytest.raises(TripwirePanelError, match="mapping of rebalance date"):
        label_permute_pairing([symbols, symbols])  # type: ignore[arg-type]


def test_the_pairing_refuses_an_empty_grid() -> None:
    with pytest.raises(TripwirePanelError, match="at least one rebalance date"):
        label_permute_pairing({})


def test_the_pairing_refuses_a_date_carried_twice_under_two_spellings(
    symbols: list[str],
) -> None:
    day = dt.date(2024, 1, 1)
    with pytest.raises(TripwirePanelError, match="twice"):
        label_permute_pairing({day: symbols, day.isoformat(): symbols})


def test_the_pairing_refuses_a_symbol_carried_twice() -> None:
    with pytest.raises(TripwirePanelError, match="twice"):
        label_permute_pairing({dt.date(2024, 1, 1): ["A", "B", "A"]})


def test_the_pairing_refuses_a_string_as_a_cross_section() -> None:
    with pytest.raises(TripwirePanelError, match="iterable"):
        label_permute_pairing({dt.date(2024, 1, 1): "AB"})


def test_the_pairing_refuses_a_datetime_key() -> None:
    with pytest.raises(TripwirePanelError, match="day-granular"):
        label_permute_pairing(
            {dt.datetime(2024, 1, 1, 9, 30, tzinfo=dt.UTC): ["A", "B"]}
        )


# -- The statistic and the threshold -------------------------------------------


def test_the_threshold_is_the_delegated_closed_form() -> None:
    # One arithmetic, one home: the bar is feature 125's closed form, computed
    # by feature 125's function. The parallelism is asserted at two levels so
    # a re-implementation that drifted by a factor would fail both.
    assert label_permute_threshold(
        120, level=DEFAULT_LABEL_LEVEL
    ) == pytest.approx(2.5758293035489004 / math.sqrt(120))
    from tripwires import time_shuffle_threshold

    assert label_permute_threshold(
        120, level=0.05
    ) == time_shuffle_threshold(120, level=0.05)


def test_a_tighter_level_is_a_wider_bar() -> None:
    assert label_permute_threshold(120, level=0.001) > label_permute_threshold(
        120, level=DEFAULT_LABEL_LEVEL
    )


def test_the_threshold_refuses_a_level_outside_the_open_unit_interval() -> None:
    for level in (0.0, 1.0, -0.1, 1.5):
        with pytest.raises(TripwirePanelError, match="level"):
            label_permute_threshold(120, level=level)


def test_the_threshold_refuses_a_grid_below_two_dates() -> None:
    with pytest.raises(TripwirePanelError, match="at least two"):
        label_permute_threshold(1)


def test_the_statistic_reads_the_permuted_label_not_the_own_one(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # The assertion that separates a real permutation from a loop that quietly
    # returns the identity: the statistic is recomputed here from first
    # principles over the *same* pairing, and separately over the identity, and
    # the two must not agree. A fixed-point-free pairing scores something else
    # by construction, so "the statistic is what the permutation says it is"
    # is checkable without pinning the draw.
    targets = {
        day: {name: float(index) for index, name in enumerate(symbols)}
        for day in grid
    }
    scores = {
        day: {
            name: math.sin(index + day.toordinal()) for index, name in enumerate(symbols)
        }
        for day in grid
    }
    pairing = label_permute_pairing(
        {day: symbols for day in grid}, seed=DEFAULT_LABEL_SEED
    )
    expected = _sharpe(
        [
            sum(
                scores[day][symbol] * targets[day][pairing[day][symbol]]
                for symbol in symbols
            )
            / len(symbols)
            for day in grid
        ]
    )
    assert permuted_book_sharpe(scores, targets, pairing) == pytest.approx(expected)
    # ...and the identity pairing — every symbol keeping its own return — reads
    # a *different* book, so the equality above is not an identity pairing in
    # disguise.
    own = _sharpe(
        [
            sum(scores[day][symbol] * targets[day][symbol] for symbol in symbols)
            / len(symbols)
            for day in grid
        ]
    )
    assert permuted_book_sharpe(scores, targets, pairing) != pytest.approx(own)


def _sharpe(per_date: list[float]) -> float:
    """The statistic's closed form, restated in the test so it can be checked."""
    mean = math.fsum(per_date) / len(per_date)
    variance = math.fsum((value - mean) ** 2 for value in per_date) / len(per_date)
    return mean / math.sqrt(variance)


def test_the_statistic_refuses_a_pairing_that_fixes_a_symbol(
    grid: list[dt.date], symbols: list[str]
) -> None:
    scores = gaussian_panel(grid, symbols, seed=1)
    targets = gaussian_panel(grid, symbols, seed=2)
    identity = {day: {name: name for name in symbols} for day in grid}
    with pytest.raises(TripwirePanelError, match="fixes"):
        permuted_book_sharpe(scores, targets, identity)


def test_the_statistic_refuses_a_pairing_that_is_not_a_permutation(
    grid: list[dt.date], symbols: list[str]
) -> None:
    scores = gaussian_panel(grid, symbols, seed=1)
    targets = gaussian_panel(grid, symbols, seed=2)
    # On one date, two symbols are sent to the same label and one is sent
    # nowhere: the keys and the values are different symbol sets, so some
    # symbol's return is handed out twice and another's not at all.
    broken = {
        day: dict(labels)
        for day, labels in label_permute_pairing(
            {day: symbols for day in grid}, seed=DEFAULT_LABEL_SEED
        ).items()
    }
    broken[grid[0]][symbols[1]] = broken[grid[0]][symbols[0]]
    with pytest.raises(TripwirePanelError, match="not a permutation"):
        permuted_book_sharpe(scores, targets, broken)


def test_the_statistic_refuses_a_pairing_over_the_wrong_dates(
    grid: list[dt.date], symbols: list[str]
) -> None:
    scores = gaussian_panel(grid, symbols, seed=1)
    targets = gaussian_panel(grid, symbols, seed=2)
    pairing = label_permute_pairing(
        {day: symbols for day in grid[:-1]}, seed=DEFAULT_LABEL_SEED
    )
    with pytest.raises(TripwirePanelError, match="exactly the dates"):
        permuted_book_sharpe(scores, targets, pairing)


def test_the_statistic_refuses_a_pairing_that_covers_another_cross_section(
    grid: list[dt.date], symbols: list[str]
) -> None:
    scores = gaussian_panel(grid, symbols, seed=1)
    targets = gaussian_panel(grid, symbols, seed=2)
    pairing = label_permute_pairing(
        {day: symbols[:10] for day in grid}, seed=DEFAULT_LABEL_SEED
    )
    with pytest.raises(TripwirePanelError, match="joined cross-section carries"):
        permuted_book_sharpe(scores, targets, pairing)


def test_the_statistic_refuses_a_non_finite_cell(
    grid: list[dt.date], symbols: list[str]
) -> None:
    scores = gaussian_panel(grid, symbols, seed=1)
    scores[grid[0]][symbols[0]] = float("nan")
    targets = gaussian_panel(grid, symbols, seed=2)
    pairing = label_permute_pairing(
        {day: symbols for day in grid}, seed=DEFAULT_LABEL_SEED
    )
    with pytest.raises(TripwirePanelError, match="not finite"):
        permuted_book_sharpe(scores, targets, pairing)


def test_the_statistic_refuses_zero_dispersion(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # Every score the same on every date: the book returns one value every
    # date, so there is no reward-to-variance ratio to read. A refusal, not a
    # ZeroDivisionError and not a "pass" — the distinction the category exists
    # to preserve.
    scores = {day: {name: 1.0 for name in symbols} for day in grid}
    targets = {day: {name: float(index) for index, name in enumerate(symbols)} for day in grid}
    pairing = label_permute_pairing(
        {day: symbols for day in grid}, seed=DEFAULT_LABEL_SEED
    )
    with pytest.raises(TripwireStatisticError, match="dispersion"):
        permuted_book_sharpe(scores, targets, pairing)


# -- The verdict ---------------------------------------------------------------


def test_a_clean_candidate_passes(grid: list[dt.date], symbols: list[str]) -> None:
    scores, targets = _clean_candidate(grid, symbols)
    verdict = run_label_permute_tripwire(scores, targets, node_id="node-clean")
    assert verdict.rejected is False
    assert verdict.outcome == "ok"
    assert abs(verdict.surviving_sharpe) <= verdict.threshold


def test_a_leak_the_probe_owns_is_rejected(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # The probe must reject *something*, or a suite of it is indistinguishable
    # from a suite of a broken probe. The leak here is the one this probe owns
    # — a date-local cross-sectional component the candidate can read — and it
    # is asserted at better than 2x the bar so a probe that merely wobbled past
    # the threshold could not satisfy it. (The other direction, the whole-sample
    # symbol leak this probe *escapes*, is pinned in the complementarity
    # section below, where both probes' verdicts are asserted together.)
    scores, targets = _date_local_leak(grid, symbols)
    verdict = run_label_permute_tripwire(scores, targets, node_id="node-leak")
    assert verdict.rejected is True
    assert verdict.outcome == "tripwire_fail"
    assert abs(verdict.surviving_sharpe) > 2.0 * verdict.threshold


def test_the_verdict_satisfies_feature_131s_structural_check(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # Feature 131 validates a failure *structurally* — by the ten field names
    # — because the factory's scan gives one source file two class objects and
    # isinstance cannot hold across that seam. It then re-derives
    # ``abs(surviving_sharpe) > threshold`` itself, so these names are a
    # contract and not a preference: a label-permute rejection must be one the
    # poison store can judge correctly.
    scores, targets = _date_local_leak(grid, symbols)
    verdict = run_label_permute_tripwire(scores, targets, node_id="node-leak")
    for field in (
        "node_id",
        "tripwire",
        "horizon",
        "dates",
        "seed",
        "level",
        "surviving_sharpe",
        "threshold",
        "rejected",
        "outcome",
    ):
        assert hasattr(verdict, field), field
    assert verdict.tripwire == LABEL_PERMUTE_NAME
    assert verdict.outcome == "tripwire_fail"
    assert abs(verdict.surviving_sharpe) > verdict.threshold


def test_the_verdict_names_its_own_probe_not_the_first(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # The two probes share the ten field names but must never share the name a
    # persisted record uses to say which one fired.
    scores, targets = _clean_candidate(grid, symbols)
    verdict = run_label_permute_tripwire(scores, targets, node_id="node")
    assert verdict.tripwire == "label-permute"
    assert verdict.tripwire != TIME_SHUFFLE_NAME


def test_the_verdict_carries_the_pairing_it_scored_against(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # The evidence, so a persisted rejection is auditable from the record's
    # own terms: the seed rebuilds the pairing, and the pairing here is the
    # one the statistic was read over.
    scores, targets = _clean_candidate(grid, symbols)
    verdict = run_label_permute_tripwire(scores, targets, node_id="node")
    rebuilt = label_permute_pairing(
        {day: sorted(set(scores[day]) & set(targets[1][day])) for day in verdict.pairing},
        seed=verdict.seed,
    )
    assert verdict.pairing == rebuilt
    assert verdict.dates == len(verdict.pairing)


def test_the_verdict_survives_a_round_trip_equality(
    grid: list[dt.date], symbols: list[str]
) -> None:
    scores, targets = _clean_candidate(grid, symbols)
    first = run_label_permute_tripwire(scores, targets, node_id="node")
    second = run_label_permute_tripwire(scores, targets, node_id="node")
    assert first == second
    # __hash__ consistent with __eq__, which the nested mapping would break
    # without the tuple fold.
    assert hash(first) == hash(second)
    assert len({first, second}) == 1


def test_the_verdict_carries_no_wall_clock(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # §12 determinism: two runs of the same candidate must return the same
    # verdict bit-for-bit, so a computed-at field would be a defect. A
    # timestamp is the obvious thing to add to an audit record and the one
    # thing that would make the replay path unreproducible — so the field set
    # is pinned *exactly*, which also pins the ten names feature 131 reads and
    # admits no eleventh term.
    scores, targets = _clean_candidate(grid, symbols)
    verdict = run_label_permute_tripwire(scores, targets, node_id="node")
    import dataclasses

    assert {field.name for field in dataclasses.fields(verdict)} == {
        "node_id",
        "tripwire",
        "horizon",
        "dates",
        "seed",
        "level",
        "surviving_sharpe",
        "threshold",
        "rejected",
        "outcome",
        "pairing",
    }


def test_the_verdict_refuses_a_pairing_that_fixes_a_symbol(
    grid: list[dt.date], symbols: list[str]
) -> None:
    scores, targets = _clean_candidate(grid, symbols)
    good = run_label_permute_tripwire(scores, targets, node_id="node")
    broken = {day: dict(labels) for day, labels in good.pairing.items()}
    broken[grid[0]][symbols[0]] = symbols[0]
    with pytest.raises(TripwirePanelError, match="fixes"):
        LabelPermuteVerdict(
            node_id=good.node_id,
            tripwire=good.tripwire,
            horizon=good.horizon,
            dates=good.dates,
            seed=good.seed,
            level=good.level,
            surviving_sharpe=good.surviving_sharpe,
            threshold=good.threshold,
            rejected=good.rejected,
            outcome=good.outcome,
            pairing=broken,
        )


def test_the_verdict_refuses_a_lying_rejection(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # A record that disagrees with its own arithmetic is one the node store
    # would trust and be wrong by, so it cannot be constructible.
    scores, targets = _clean_candidate(grid, symbols)
    good = run_label_permute_tripwire(scores, targets, node_id="node")
    with pytest.raises(TripwirePanelError, match="decide otherwise"):
        LabelPermuteVerdict(
            node_id=good.node_id,
            tripwire=good.tripwire,
            horizon=good.horizon,
            dates=good.dates,
            seed=good.seed,
            level=good.level,
            surviving_sharpe=good.surviving_sharpe,
            threshold=good.threshold,
            rejected=True,
            outcome="tripwire_fail",
            pairing=good.pairing,
        )


def test_the_verdict_refuses_a_lying_threshold(
    grid: list[dt.date], symbols: list[str]
) -> None:
    scores, targets = _clean_candidate(grid, symbols)
    good = run_label_permute_tripwire(scores, targets, node_id="node")
    with pytest.raises(TripwirePanelError, match="threshold"):
        LabelPermuteVerdict(
            node_id=good.node_id,
            tripwire=good.tripwire,
            horizon=good.horizon,
            dates=good.dates,
            seed=good.seed,
            level=good.level,
            surviving_sharpe=good.surviving_sharpe,
            threshold=good.threshold * 2.0,
            rejected=good.rejected,
            outcome=good.outcome,
            pairing=good.pairing,
        )


def test_the_verdict_refuses_an_outcome_that_disagrees_with_the_rejection(
    grid: list[dt.date], symbols: list[str]
) -> None:
    scores, targets = _date_local_leak(grid, symbols)
    good = run_label_permute_tripwire(scores, targets, node_id="node")
    assert good.rejected is True
    with pytest.raises(TripwirePanelError, match="outcome"):
        LabelPermuteVerdict(
            node_id=good.node_id,
            tripwire=good.tripwire,
            horizon=good.horizon,
            dates=good.dates,
            seed=good.seed,
            level=good.level,
            surviving_sharpe=good.surviving_sharpe,
            threshold=good.threshold,
            rejected=good.rejected,
            outcome="ok",
            pairing=good.pairing,
        )


def test_the_verdict_refuses_the_other_probes_name(
    grid: list[dt.date], symbols: list[str]
) -> None:
    scores, targets = _clean_candidate(grid, symbols)
    good = run_label_permute_tripwire(scores, targets, node_id="node")
    with pytest.raises(TripwirePanelError, match="tripwire is"):
        LabelPermuteVerdict(
            node_id=good.node_id,
            tripwire=TIME_SHUFFLE_NAME,
            horizon=good.horizon,
            dates=good.dates,
            seed=good.seed,
            level=good.level,
            surviving_sharpe=good.surviving_sharpe,
            threshold=good.threshold,
            rejected=good.rejected,
            outcome=good.outcome,
            pairing=good.pairing,
        )


def test_the_verdict_refuses_an_unnamed_node(
    grid: list[dt.date], symbols: list[str]
) -> None:
    scores, targets = _clean_candidate(grid, symbols)
    good = run_label_permute_tripwire(scores, targets, node_id="node")
    with pytest.raises(TripwirePanelError, match="name the node"):
        LabelPermuteVerdict(
            node_id="  ",
            tripwire=good.tripwire,
            horizon=good.horizon,
            dates=good.dates,
            seed=good.seed,
            level=good.level,
            surviving_sharpe=good.surviving_sharpe,
            threshold=good.threshold,
            rejected=good.rejected,
            outcome=good.outcome,
            pairing=good.pairing,
        )


def test_the_verdict_refuses_a_date_count_that_contradicts_its_pairing(
    grid: list[dt.date], symbols: list[str]
) -> None:
    scores, targets = _clean_candidate(grid, symbols)
    good = run_label_permute_tripwire(scores, targets, node_id="node")
    with pytest.raises(TripwirePanelError, match="denominator"):
        LabelPermuteVerdict(
            node_id=good.node_id,
            tripwire=good.tripwire,
            horizon=good.horizon,
            dates=good.dates - 1,
            seed=good.seed,
            level=good.level,
            surviving_sharpe=good.surviving_sharpe,
            threshold=label_permute_threshold(good.dates - 1, level=good.level),
            rejected=good.rejected,
            outcome=good.outcome,
            pairing=good.pairing,
        )


def test_the_verdict_refuses_a_horizon_outside_the_pinned_set(
    grid: list[dt.date], symbols: list[str]
) -> None:
    scores, targets = _clean_candidate(grid, symbols)
    good = run_label_permute_tripwire(scores, targets, node_id="node")
    with pytest.raises(TripwirePanelError, match="not one of the horizons"):
        LabelPermuteVerdict(
            node_id=good.node_id,
            tripwire=good.tripwire,
            horizon=3,
            dates=good.dates,
            seed=good.seed,
            level=good.level,
            surviving_sharpe=good.surviving_sharpe,
            threshold=good.threshold,
            rejected=good.rejected,
            outcome=good.outcome,
            pairing=good.pairing,
        )


def test_the_verdict_refuses_a_non_finite_statistic(
    grid: list[dt.date], symbols: list[str]
) -> None:
    scores, targets = _clean_candidate(grid, symbols)
    good = run_label_permute_tripwire(scores, targets, node_id="node")
    with pytest.raises(TripwirePanelError, match="not finite"):
        LabelPermuteVerdict(
            node_id=good.node_id,
            tripwire=good.tripwire,
            horizon=good.horizon,
            dates=good.dates,
            seed=good.seed,
            level=good.level,
            surviving_sharpe=float("nan"),
            threshold=good.threshold,
            rejected=good.rejected,
            outcome=good.outcome,
            pairing=good.pairing,
        )


# -- The probe: horizon resolution and refusals --------------------------------


def test_the_probe_resolves_the_shortest_covered_horizon(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # The member's pinned policy: the fastest-turning horizon is the one the
    # bundle actually covers, so two deployments running the same node return
    # the same verdict without a knob deciding it.
    targets = gaussian_panel(grid, symbols, seed=2)
    scores = gaussian_panel(grid, symbols, seed=3)
    verdict = run_label_permute_tripwire(
        scores, {2: targets, 10: targets}, node_id="node"
    )
    assert verdict.horizon == 2
    full = run_label_permute_tripwire(
        scores, {horizon: targets for horizon in HORIZONS}, node_id="node"
    )
    assert full.horizon == 1


def test_the_probe_refuses_an_unnamed_node(
    grid: list[dt.date], symbols: list[str]
) -> None:
    scores, targets = _clean_candidate(grid, symbols)
    with pytest.raises(TripwirePanelError, match="name the node"):
        run_label_permute_tripwire(scores, targets, node_id="")


def test_the_probe_refuses_a_bundle_sharing_no_horizon(
    grid: list[dt.date], symbols: list[str]
) -> None:
    scores = gaussian_panel(grid, symbols, seed=1)
    other = monday(len(grid), start=dt.date(2025, 1, 1))
    targets = {1: gaussian_panel(other, symbols, seed=2)}
    with pytest.raises(TripwirePanelError, match="shares no horizon"):
        run_label_permute_tripwire(scores, targets, node_id="node")


def test_the_probe_refuses_a_bundle_with_no_horizon_the_spec_names(
    grid: list[dt.date], symbols: list[str]
) -> None:
    scores, targets = _clean_candidate(grid, symbols)
    with pytest.raises(TripwirePanelError, match="not one of the horizons"):
        run_label_permute_tripwire(scores, {3: targets[1]}, node_id="node")


def test_the_probe_refuses_a_panel_with_no_cross_section(
    symbols: list[str],
) -> None:
    _, targets = _clean_candidate(monday(4), symbols)
    with pytest.raises(TripwirePanelError, match="no rebalance date"):
        run_label_permute_tripwire({}, targets, node_id="node")


def test_the_probe_refuses_a_one_symbol_join(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # Strictly stricter than feature 125: a date needs two symbols for a
    # derangement to exist, where re-dating whole cross-sections is content
    # with one. This is the refusal the module docstring says is spelled here
    # rather than borrowed from feature 125's runner.
    scores = {day: {symbols[0]: float(index)} for index, day in enumerate(grid)}
    targets = {horizon: scores for horizon in HORIZONS}
    with pytest.raises(TripwirePanelError, match="two or more symbols"):
        run_label_permute_tripwire(scores, targets, node_id="node")


def test_the_probe_refuses_a_grid_below_two_dates(
    symbols: list[str],
) -> None:
    day = dt.date(2024, 1, 1)
    scores = {day: {name: float(index) for index, name in enumerate(symbols)}}
    targets = {horizon: scores for horizon in HORIZONS}
    with pytest.raises(TripwirePanelError, match="two or more symbols|at least two"):
        run_label_permute_tripwire(scores, targets, node_id="node")


def test_the_probe_ignores_dates_the_pair_of_panels_does_not_share(
    grid: list[dt.date], symbols: list[str]
) -> None:
    scores, targets = _clean_candidate(grid, symbols)
    extra = monday(5, start=dt.date(2025, 6, 1))
    scores = dict(scores)
    scores.update(gaussian_panel(extra, symbols, seed=9))
    verdict = run_label_permute_tripwire(scores, targets, node_id="node")
    assert verdict.dates == len(grid)
    assert set(verdict.pairing) == set(grid)


def test_the_probe_measures_a_two_by_two_grid(symbols: list[str]) -> None:
    # The smallest admissible grid, and the case most likely to expose a
    # derangement loop or a threshold edge: two dates, two symbols.
    days = monday(2)
    scores = {
        days[0]: {symbols[0]: 1.0, symbols[1]: -0.4},
        days[1]: {symbols[0]: -0.2, symbols[1]: 0.9},
    }
    targets = {
        horizon: {
            days[0]: {symbols[0]: 0.5, symbols[1]: -0.3},
            days[1]: {symbols[0]: -0.6, symbols[1]: 0.8},
        }
        for horizon in HORIZONS
    }
    verdict = run_label_permute_tripwire(scores, targets, node_id="node")
    assert verdict.dates == 2
    assert all(labels == {symbols[0]: symbols[1], symbols[1]: symbols[0]}
               for labels in verdict.pairing.values())
    assert verdict.outcome in TRIPWIRE_OUTCOMES


# -- The second probe is independent of the first ------------------------------


def test_a_whole_sample_symbol_leak_escapes_the_label_probe(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # Feature 133's corpus — the four whole-sample per-symbol statistics, each
    # aligned with its symbol on every date — run through *both* probes. This
    # is the *negative* half of the independence claim, and it is asserted
    # against the corpus itself rather than a lookalike fixture, because the
    # corpus is the closed, auditable set of leaks the category guarantees
    # about: re-labelling within a date removes a whole-sample statistic
    # entirely, while re-dating whole cross-sections cannot.
    from tripwires import planted_signals

    measured = 0
    for signal in planted_signals():
        label = run_label_permute_tripwire(
            signal.scores, signal.targets, node_id=signal.node_id
        )
        shuffle = run_time_shuffle_tripwire(
            signal.scores, signal.targets, node_id=signal.node_id
        )
        # The first probe catches it, with the margin feature 133's suite
        # asserts for its own probe.
        assert shuffle.rejected is True, signal.leak_kind
        assert abs(shuffle.surviving_sharpe) > 2.0 * shuffle.threshold, (
            signal.leak_kind
        )
        # ...and this probe reads it flat: not merely "fails to catch" but
        # removed, the surviving statistic falling to a tenth of the bar.
        assert label.rejected is False, signal.leak_kind
        assert abs(label.surviving_sharpe) < 0.2 * label.threshold, (
            signal.leak_kind
        )
        measured += 1
    assert measured == 4, "the corpus's four leak kinds were all measured"


def test_a_date_local_cross_sectional_leak_escapes_the_time_shuffle(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # The mirror: a date-local cross-sectional component, the same on every
    # symbol in its date. Re-dating cross-sections cannot disturb a function
    # of the date; re-labelling within a date destroys it. This is the
    # direction that makes the second probe worth running at all — the leak
    # feature 125's bar cannot see.
    scores, targets = _date_local_leak(grid, symbols)

    shuffle = run_time_shuffle_tripwire(scores, targets, node_id="node")
    label = run_label_permute_tripwire(scores, targets, node_id="node")

    assert shuffle.rejected is False
    assert abs(shuffle.surviving_sharpe) < 0.8 * shuffle.threshold
    assert label.rejected is True
    assert abs(label.surviving_sharpe) > 1.5 * label.threshold


def test_the_two_probes_agree_on_a_clean_candidate(
    grid: list[dt.date], symbols: list[str]
) -> None:
    # Independence is not disagreement: on a candidate with no leak both
    # probes pass, which is what keeps the pair from being two alarms that
    # always fire together.
    scores, targets = _clean_candidate(grid, symbols, seed=17)
    label = run_label_permute_tripwire(scores, targets, node_id="node")
    shuffle = run_time_shuffle_tripwire(scores, targets, node_id="node")
    assert label.rejected is False
    assert shuffle.rejected is False


def test_the_component_exposes_the_second_probe() -> None:
    # The app seat's duck-checked seam: the probe is a *method* on feature
    # 125's component rather than a component of its own, so the member's
    # registered set is unchanged and a caller holding the composed probe has
    # both sentences of §6.1 step 10.
    component = TimeShuffleTripwire()
    scores = gaussian_panel(monday(8), symbols(4), seed=1)
    targets = {horizon: scores for horizon in HORIZONS}
    verdict = component.label(scores, targets, node_id="node")
    assert isinstance(verdict, LabelPermuteVerdict)
    assert verdict.tripwire == LABEL_PERMUTE_NAME


def test_the_two_probes_have_independent_defaults() -> None:
    # Neither probe's default may be a function of the other's: a pairing
    # shared with the first probe would be the same draw under two names, and
    # a level imported from the first would silently tighten the second when
    # anyone tightened the first.
    from tripwires import DEFAULT_SHUFFLE_SEED

    assert DEFAULT_LABEL_SEED != DEFAULT_SHUFFLE_SEED
    assert DEFAULT_LABEL_LEVEL == DEFAULT_SHUFFLE_LEVEL  # pinned equal *by
    # value*, deliberately, and asserted separately per module so the two can
    # diverge without one following the other.
