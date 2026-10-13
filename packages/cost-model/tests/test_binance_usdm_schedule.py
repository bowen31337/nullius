"""The shipped USD-M perpetual fee schedule loads and prices perp fees.

additions_spec_research_book_v2.xml: a perp research book points
NULLIUS_COST_MODEL_PATH at binance_usdm.yaml. It must load through the same
service as the spot default, quote a 5 bps taker fee, and hash differently,
so that no score can confuse the two schedules.
"""

from __future__ import annotations

from pathlib import Path

import cost_model
from cost_model import TAKER, CostModelService

USDM = Path(cost_model.__file__).with_name("binance_usdm.yaml")


def _service(path: Path | None, tmp_path: Path) -> CostModelService:
    return CostModelService(
        config_path=str(path) if path else None,
        database_url=f"sqlite:///{tmp_path / 'cost.db'}",
    )


def test_the_usdm_schedule_loads_with_its_venue_and_version(tmp_path: Path) -> None:
    config = _service(USDM, tmp_path).config
    assert config.venue == "binance_usdm"
    assert config.version == "2026.10.1"


def test_the_taker_fee_is_five_bps(tmp_path: Path) -> None:
    assert _service(USDM, tmp_path).fees().fee_fraction(TAKER) == 0.0005


def test_the_usdm_hash_differs_from_the_spot_default(tmp_path: Path) -> None:
    assert (
        _service(USDM, tmp_path).cost_model_hash()
        != _service(None, tmp_path).cost_model_hash()
    )
