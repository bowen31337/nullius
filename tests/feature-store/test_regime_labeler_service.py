"""Feature 58 end to end: label a universe's market history, persist the regimes.

app_spec.xml feature 58: *System labels market regimes using a rolling-window
fit only, which rejects any labeler configured to fit over full history.*
This suite drives the whole feature through the service seam — panel from bars
+ membership, labels from panel, record from labels — and through the
application factory, so feature 58 is verified as a composed component, not
just as a set of modules.

The membership is the universe's symbols: feature 58 never ranks liquidity
(feature 40 does), it is *given* the cross-section and labels the market that
forms it.  The clause this suite guards most closely is the *rolling-window
fit*: the service refuses a full-history fit at its own seam, and the stored
record carries the version stamp that makes the definition checkable.
"""

import datetime as dt
import math
import random

import pytest

from feature_store.bars import DailyBar
from feature_store.regime_labeler import FullHistoryFitError
from feature_store.regime_labeler_persistence import (
    FEATURE_NAME_LABELS,
    FEATURE_VERSION,
    RegimeLabelerFeatureStore,
)
from feature_store.regime_labeler_service import (
    RegimeLabelerService,
    build_regime_labeler_service,
)
from feature_store.store import FeatureStore

from app.module_loader import create_app, scan_components

SNAPSHOT = "b" * 64


def market_levels(
    count: int, *, calm: int, turbulent: int, crash: int, seed: int = 7
) -> list[float]:
    """Price levels for one symbol, passing calm -> turbulent -> crash.

    The three stretches give the market a visible regime progression the
    labeler should, at least partly, resolve into distinct strata.
    """
    rng = random.Random(seed)
    calm_path = [rng.gauss(0.0, 0.005) for _ in range(calm)]
    turb_path = [rng.gauss(0.0, 0.04) for _ in range(turbulent)]
    crash_path = [rng.gauss(-0.02, 0.05) for _ in range(crash)]
    returns = calm_path + turb_path + crash_path
    while len(returns) < count:
        returns.append(rng.gauss(0.0, 0.02))
    returns = returns[:count]
    levels = [100.0]
    for step in returns:
        levels.append(levels[-1] * math.exp(step))
    return levels


def price_bars(
    series: dict[str, list[float]], first: dt.date = dt.date(2026, 1, 1)
) -> list[DailyBar]:
    count = len(next(iter(series.values())))
    dates = [first + dt.timedelta(days=offset) for offset in range(count)]
    return [
        DailyBar(symbol, dates[i], values[i])
        for symbol, values in series.items()
        for i in range(len(values))
    ]


def axis(count: int, first: dt.date = dt.date(2026, 1, 1)) -> list[dt.date]:
    return [first + dt.timedelta(days=offset) for offset in range(count)]


def universe() -> dict[str, list[float]]:
    return {
        "AAAUSDT": market_levels(220, calm=80, turbulent=70, crash=70, seed=1),
        "BBBUSDT": market_levels(220, calm=80, turbulent=70, crash=70, seed=2),
        "CCCUSDT": market_levels(220, calm=80, turbulent=70, crash=70, seed=3),
        "DDDUSDT": market_levels(220, calm=80, turbulent=70, crash=70, seed=4),
    }


# ---------------------------------------------------------------------------
# Computation through the service
# ---------------------------------------------------------------------------


def test_compute_labels_the_market_history() -> None:
    # The service labels each date with a regime stratum, fit on that date's
    # trailing window.
    service = RegimeLabelerService()
    series = universe()
    labels = service.compute(
        price_bars(series), symbols=list(series), dates=axis(220)
    )
    assigned = [label for label in labels.labels if label is not None]
    assert assigned  # the market was labelled
    assert all(0 <= label < 3 for label in assigned)
    assert labels.k == 3
    assert labels.window == 63


def test_compute_uses_the_membership_as_given() -> None:
    # The service never invents or trims membership; the panel is built over
    # exactly the symbols passed.
    service = RegimeLabelerService()
    series = {
        "AAAUSDT": market_levels(220, calm=80, turbulent=70, crash=70, seed=1),
        "BBBUSDT": market_levels(220, calm=80, turbulent=70, crash=70, seed=2),
    }
    labels = service.compute(
        price_bars(series), symbols=list(series), dates=axis(220)
    )
    assert len(labels.dates) == 219  # one per period return


# ---------------------------------------------------------------------------
# Persistence through the service
# ---------------------------------------------------------------------------


def test_persist_stores_a_version_stamped_market_wide_record() -> None:
    # The service writes the labels under the market-wide daily key at the
    # current version, and they read back.
    service = RegimeLabelerService(store=FeatureStore())
    series = universe()
    labels = service.persist(
        SNAPSHOT,
        price_bars(series),
        symbols=list(series),
        dates=axis(220),
        top_n=len(series),
    )
    restored = service.load(SNAPSHOT)
    assert restored is not None
    assert restored.labels == labels.labels

    store = FeatureStore()
    wrapper = RegimeLabelerFeatureStore(store)
    key = wrapper.labels_key(SNAPSHOT)
    assert key.feature_name == FEATURE_NAME_LABELS
    assert key.feature_version == FEATURE_VERSION
    assert key.symbol == "__market__"
    assert str(key.frequency) == "1d"


def test_persist_refuses_a_full_history_fit() -> None:
    # The service's own seam refuses a window that spans the whole series — the
    # rolling-window fit only, which feature 58 demands.
    service = RegimeLabelerService(window=400)
    series = universe()
    with pytest.raises(FullHistoryFitError):
        service.persist(
            SNAPSHOT,
            price_bars(series),
            symbols=list(series),
            dates=axis(220),
            top_n=len(series),
        )


def test_persist_refuses_an_unbounded_window() -> None:
    # A ``None`` window is the spelling of a full-history fit; refused.
    with pytest.raises(FullHistoryFitError):
        RegimeLabelerService(window=None)  # type: ignore[arg-type]


def test_load_of_unpersisted_snapshot_returns_none() -> None:
    service = RegimeLabelerService()
    assert service.load(SNAPSHOT) is None


# ---------------------------------------------------------------------------
# The composed component
# ---------------------------------------------------------------------------


def test_workspace_scan_discovers_the_regime_labeler_component() -> None:
    names = [component.name for component in scan_components()]
    assert "regime-labeler" in names


def test_create_app_composes_a_regime_labeler_service() -> None:
    app = create_app()
    service = app.get("regime-labeler")
    assert service is not None
    assert type(service).__name__ == "RegimeLabelerService"
    assert type(service).__module__.endswith("regime_labeler_service")


def test_composed_service_labels_and_persists() -> None:
    # Integration: the composed instance actually labels a market and stores
    # the labels under the market-wide daily key.
    app = create_app()
    service = app.get("regime-labeler")
    series = universe()
    labels = service.persist(
        SNAPSHOT,
        price_bars(series),
        symbols=list(series),
        dates=axis(220),
        top_n=len(series),
    )
    assert labels.n_labeled > 0
    restored = service.load(SNAPSHOT)
    assert restored is not None
    assert restored.labels == labels.labels


def test_builder_is_registered() -> None:
    # The zero-argument builder is what the factory composes — the version-1
    # default: three regimes, a 63-vector trailing window.
    service = build_regime_labeler_service()
    assert isinstance(service, RegimeLabelerService)
    assert service._labeler.window == 63
    assert service._labeler.k == 3
