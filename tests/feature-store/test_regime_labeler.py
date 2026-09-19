"""Feature 58's computation contract: market-regime labels from a rolling fit.

app_spec.xml feature 58: *System labels market regimes using a rolling-window
fit only, which rejects any labeler configured to fit over full history.*
These tests pin the pure computation — the feature matrix, the trailing-window
k-means, the per-date labels — independent of how the labels are persisted.

The invariants the feature's anti-leakage guarantee rests on:

* the label on a date is produced by a model fit on that date's *trailing*
  window of feature vectors — data dated ``<= t`` only, never the series as a
  whole;
* a labeler offers no full-history mode: a ``window`` that is not a finite
  positive integer is refused at construction, and a ``window`` at least as
  long as the usable series is refused at fit time — both raising
  ``FullHistoryFitError``;
* the labels are bit-reproducible: the same panel yields the same labels in
  either order of computation, so a replay re-labels identically;
* the features are the market's multi-horizon realized volatility plus its
  rolling vol-of-vol (feature 55's quantities), so the regimes named are the
  regimes those magnitudes and instabilities describe.
"""

import datetime as dt
import math

import pytest

from feature_store.bars import DailyBar
from feature_store.regime import PricePanel
from feature_store.regime_labeler import (
    DEFAULT_WINDOW,
    KMEANS_SEED,
    FullHistoryFitError,
    RegimeLabeler,
    RegimeLabels,
    regime_feature_matrix,
)

DAYS = [dt.date(2026, 1, 1) + dt.timedelta(days=offset) for offset in range(260)]


def price_panel(
    series: dict[str, list[float]],
    *,
    symbols: "list[str] | None" = None,
    dates: "list[dt.date] | None" = None,
) -> PricePanel:
    """A panel from per-symbol price *levels* over ``DAYS`` (or the overrides).

    ``dates`` defaults to the length of the first series, so a series of ``n``
    levels populates ``n`` axis dates and the panel carries no trailing gap of
    missing prices.
    """
    if dates is None:
        first_len = next(iter(series.values())).__len__()
        dates = DAYS[:first_len]
    symbols = symbols if symbols is not None else list(series)
    bars = [
        DailyBar(symbol, date, levels[i])
        for symbol, levels in series.items()
        for i, date in enumerate(dates)
        if i < len(levels)
    ]
    return PricePanel.from_bars(bars, symbols=symbols, dates=dates)


def levels_from_returns(initial: float, step_returns: list[float]) -> list[float]:
    """Price levels from a list of log returns, one price per arrival."""
    levels = [initial]
    for step in step_returns:
        levels.append(levels[-1] * math.exp(step))
    return levels


def regime_path(count: int, *, vol: float = 0.03, drift: float = 0.0) -> list[float]:
    """A pseudo-random return path, deterministic in the caller's seed."""
    import random

    rng = random.Random(20260417)
    return [rng.gauss(drift, vol) for _ in range(count)]


def multi_regime_series(
    *, calm: int, turbulent: int, crash: int, seed: int = 1
) -> list[float]:
    """A return path with three visually distinct stretches.

    A calm low-vol stretch, a turbulent high-vol stretch and a crash (strong
    negative drift with high vol), concatenated so the market passes through
    three regimes the labeler should, at least partly, separate.
    """
    import random

    rng = random.Random(seed)
    calm_path = [rng.gauss(0.0, 0.005) for _ in range(calm)]
    turb_path = [rng.gauss(0.0, 0.04) for _ in range(turbulent)]
    crash_path = [rng.gauss(-0.02, 0.05) for _ in range(crash)]
    return calm_path + turb_path + crash_path


# ---------------------------------------------------------------------------
# The regime feature matrix
# ---------------------------------------------------------------------------


def test_feature_matrix_is_aligned_to_the_return_axis() -> None:
    # ``n`` price levels are ``n - 1`` period returns, so the feature matrix
    # has ``n - 1`` rows, each with one column per feature (four by default:
    # three horizons plus the vol-of-vol).
    series = {
        symbol: levels_from_returns(100.0, regime_path(120))
        for symbol in ("AAAUSDT", "BBBUSDT", "CCCUSDT")
    }
    panel = price_panel(series)
    dates, rows = regime_feature_matrix(panel)
    assert len(dates) == 120
    assert len(rows) == 120
    assert all(len(row) == 4 for row in rows)
    # The return-axis date for period ``i`` is the panel's date ``i + 1``.
    assert dates[0] == panel.dates[1]


def test_feature_matrix_early_rows_are_uncomputable() -> None:
    # The vol-of-vol needs a full base window *and* a full vol window on top,
    # so the first several rows carry a nan column and are not usable.
    series = {"AAAUSDT": levels_from_returns(100.0, regime_path(120))}
    panel = price_panel(series)
    _, rows = regime_feature_matrix(panel)
    usable = [i for i, row in enumerate(rows) if all(math.isfinite(v) for v in row)]
    assert usable  # some rows become usable once the windows fill
    assert usable[0] > 0  # but not the very first one


def _matrices_equal(first: list[list[float]], second: list[list[float]]) -> bool:
    """Element-wise equality treating ``nan`` as equal to ``nan``.

    The matrix carries ``nan`` where a window is not yet full, and ``nan != nan``
    would make a plain list comparison report two identical matrices as
    different — so the comparison must treat a matching pair of nans as equal.
    """
    if len(first) != len(second):
        return False
    for left, right in zip(first, second):
        for a, b in zip(left, right):
            if math.isnan(a) and math.isnan(b):
                continue
            if a != b:
                return False
    return True


def test_feature_matrix_is_reproducible() -> None:
    # The same panel yields the same matrix, so the labels built on it are
    # reproducible across a replay.
    series = {
        symbol: levels_from_returns(100.0, regime_path(250))
        for symbol in ("AAAUSDT", "BBBUSDT")
    }
    panel = price_panel(series)
    _, first = regime_feature_matrix(panel)
    _, second = regime_feature_matrix(panel)
    assert _matrices_equal(first, second)


# ---------------------------------------------------------------------------
# Construction guard: no full-history mode
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_window", [None, 0, -1, -10])
def test_construction_rejects_non_positive_window(bad_window: object) -> None:
    # A non-positive window has no trailing span to fit on; it is the spelling
    # of an unbounded, hence full-history, fit, so it is refused outright.
    with pytest.raises(FullHistoryFitError):
        RegimeLabeler(k=3, window=bad_window)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad_window", [1.5, 2.0, "63"])
def test_construction_rejects_non_integer_window(bad_window: object) -> None:
    # A non-integer window is not a finite span; refused as a type error.
    with pytest.raises(TypeError):
        RegimeLabeler(k=3, window=bad_window)  # type: ignore[arg-type]


def test_construction_rejects_single_regime() -> None:
    # One regime is not a labelling — every date would carry the same stratum.
    with pytest.raises(ValueError):
        RegimeLabeler(k=1, window=63)


def test_construction_accepts_a_finite_window() -> None:
    labeler = RegimeLabeler(k=3, window=63)
    assert labeler.k == 3
    assert labeler.window == 63


# ---------------------------------------------------------------------------
# Fit guard: window must not span the whole series
# ---------------------------------------------------------------------------


def test_fit_time_rejects_window_spanning_the_series() -> None:
    # A window equal to the number of usable vectors makes the single fit span
    # all the available history — the full-history fit the feature forbids.
    rows = [[float(i), float(i) * 2] for i in range(50)]
    with pytest.raises(FullHistoryFitError):
        RegimeLabeler(k=3, window=50).label_features(rows)


def test_fit_time_rejects_window_longer_than_the_series() -> None:
    rows = [[float(i), float(i) * 2] for i in range(50)]
    with pytest.raises(FullHistoryFitError):
        RegimeLabeler(k=3, window=80).label_features(rows)


def test_fit_time_accepts_a_trailing_window_shorter_than_the_series() -> None:
    rows = [[float(i), float(i) * 2] for i in range(50)]
    labels = RegimeLabeler(k=3, window=20).label_features(rows)
    # The first ``window - 1`` positions have no full window yet, so they are
    # unlabeled; the rest carry a cluster index.
    assert labels[:19] == (None,) * 19
    assert all(label is not None for label in labels[19:])
    assert all(0 <= label < 3 for label in labels[19:])


def test_empty_series_labels_to_nothing() -> None:
    assert RegimeLabeler(k=3, window=20).label_features([]) == tuple()


# ---------------------------------------------------------------------------
# Labelling a panel
# ---------------------------------------------------------------------------


def test_panel_labels_are_aligned_and_bounded() -> None:
    series = {
        symbol: levels_from_returns(100.0, regime_path(200))
        for symbol in ("AAAUSDT", "BBBUSDT", "CCCUSDT", "DDDUSDT")
    }
    panel = price_panel(series)
    labels = RegimeLabeler(k=3, window=63).label_panel(panel)
    assert isinstance(labels, RegimeLabels)
    assert len(labels.labels) == len(labels.dates)
    # Every assigned label is a valid cluster index.
    assigned = [label for label in labels.labels if label is not None]
    assert assigned  # some dates were labelled
    assert all(0 <= label < 3 for label in assigned)
    assert labels.k == 3
    assert labels.window == 63
    assert labels.n_labeled == len(assigned)


def test_panel_labels_separate_the_three_regimes() -> None:
    # A market that moves calm -> turbulent -> crash should, across the
    # stretches, visit more than one regime cluster: a labeler that assigned a
    # single stratum to everything would be failing to label at all.
    returns = multi_regime_series(calm=80, turbulent=80, crash=80)
    panel = price_panel({"AAAUSDT": levels_from_returns(100.0, returns)})
    labels = RegimeLabeler(k=3, window=40).label_panel(panel)
    assigned = [label for label in labels.labels if label is not None]
    assert len(set(assigned)) >= 2


def test_panel_labels_are_reproducible() -> None:
    # The same panel yields the same labels, bit for bit — the replay contract.
    series = {
        symbol: levels_from_returns(100.0, regime_path(200))
        for symbol in ("AAAUSDT", "BBBUSDT")
    }
    panel = price_panel(series)
    first = RegimeLabeler(k=3, window=63).label_panel(panel)
    second = RegimeLabeler(k=3, window=63).label_panel(panel)
    assert first.labels == second.labels
    assert first.dates == second.dates


def test_seed_is_a_fixed_constant() -> None:
    # The initialization seed is a constant, not the module RNG, so the labels
    # never depend on anything else that happened to call ``random`` first.
    assert isinstance(KMEANS_SEED, int)
    assert KMEANS_SEED >= 0


# ---------------------------------------------------------------------------
# The causal fit: the label at ``t`` never sees data after ``t``
# ---------------------------------------------------------------------------


def test_label_at_t_is_invariant_to_appended_future() -> None:
    # The core anti-leakage property: relabelling the same history with extra
    # future appended must not change any label *within* the original history,
    # because each label's fit window ends at its own date.  A full-history fit
    # would move the early labels when the tail changed.
    #
    # The trick is to extend the *same* return path, not a different one: the
    # shared history's returns — and therefore its feature matrix — are then
    # byte-identical, so any label difference would have to come from the fit
    # span reaching past ``t``.  It must not.
    returns = multi_regime_series(calm=90, turbulent=90, crash=90)
    import random

    rng = random.Random(999)
    returns.extend(rng.gauss(0.0, 0.01) for _ in range(120))  # a calm future
    levels = levels_from_returns(100.0, returns)

    short_panel = price_panel({"AAAUSDT": levels[:150]})
    short_labels = RegimeLabeler(k=3, window=40).label_panel(short_panel)

    long_panel = price_panel({"AAAUSDT": levels})
    long_labels = RegimeLabeler(k=3, window=40).label_panel(long_panel)

    # The labels over the shared dates are identical whether or not the future
    # was known.
    shared = min(len(short_labels.labels), len(long_labels.labels))
    assert short_labels.labels[:shared] == long_labels.labels[:shared]


def test_k_means_uses_a_seedable_deterministic_init() -> None:
    # Two labelers with the same seed produce identical labels; the seeding is
    # what makes the labelling reproducible rather than RNG-order-dependent.
    series = {
        symbol: levels_from_returns(100.0, regime_path(150))
        for symbol in ("AAAUSDT", "BBBUSDT", "CCCUSDT")
    }
    panel = price_panel(series)
    a = RegimeLabeler(k=3, window=40).label_panel(panel)
    b = RegimeLabeler(k=3, window=40).label_panel(panel)
    assert a.labels == b.labels
