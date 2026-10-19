"""Maker execution's fee axis — the passive queue-position penalty, carried.

additions_spec: *System lets the evaluation config choose execution "taker"
(today's default) or "maker", where maker charges the venue's maker fee plus
the cost model's passive queue-position penalty on every unit traded, so that
a signal is priced at the fee it would pay when executed passively, with its
adverse-selection cost stated rather than ignored.*

This member's half of that sentence is :attr:`~cost_model.fees.FeeSchedule.passive_penalty_fraction`:
the document's own ``fill_model.passive.queue_position_penalty_bps``
(feature 64's own field), resolved onto the schedule beside the taker and
maker rates so a caller pricing a maker fill reads both numbers off one
value, with no second parse and no second arithmetic.

One test per claim:

* :data:`cost_model.MAKER` already exists (feature 61), and
  :meth:`~cost_model.fees.FeeSchedule.fee_fraction` already answers it —
  pinned here so a caller priced at the maker rate is priced at exactly the
  document's ``maker_bps``.
* the shipped USD-M document (``binance_usdm.yaml``) resolves a taker
  fraction, a maker fraction and a passive penalty fraction that are each
  the document's own bps over ten thousand.
* a document with no passive fill model at all resolves a ``None`` penalty
  rather than a refusal — absence is a fact about the venue, not a defect —
  while still resolving its own maker fraction correctly.
* a *malformed* (but present) penalty rate is refused, the same rule the
  taker and maker rates already hold to.
* the hash is unaffected: :func:`~cost_model.CostModelService.cost_model_hash`
  still hashes the document, not the resolved schedule, so adding a field to
  :class:`~cost_model.fees.FeeSchedule` changes nothing it is keyed on.

No test opens a network connection or writes outside a pytest temporary
directory, and none shares mutable state, so the suite is safe under
pytest-xdist.
"""

from __future__ import annotations

import math
from pathlib import Path

import cost_model
import pytest
from cost_model import (
    MAKER,
    TAKER,
    CostModelConfigError,
    CostModelService,
    FeeSchedule,
    cost_model_digest,
)

USDM_PATH = Path(cost_model.__file__).with_name("binance_usdm.yaml")

#: binance_usdm.yaml's own rates (packages/cost-model/src/cost_model/binance_usdm.yaml):
#: taker 5 bps, maker 2 bps, passive queue-position penalty 1.5 bps.
USDM_TAKER_FRACTION = 0.0005
USDM_MAKER_FRACTION = 0.0002
USDM_PASSIVE_PENALTY_FRACTION = 0.00015

#: A "spot" document in the §6.2 shape, with its own distinct maker rate and
#: no ``fill_model`` section at all — a venue whose schedule prices both fee
#: sides but carries no passive fill model, the state
#: :attr:`~cost_model.fees.FeeSchedule.passive_penalty_fraction` answers
#: ``None`` for rather than refuses.
SPOT_TAKER_BPS = 10.0
SPOT_MAKER_BPS = 7.5
SPOT_DOCUMENT = {
    "cost_model": {
        "version": "2026.09.9",
        "venue": "testnet_spot_no_passive",
        "fees": {
            "taker_bps": SPOT_TAKER_BPS,
            "maker_bps": SPOT_MAKER_BPS,
        },
    }
}


def _service(path: Path, tmp_path: Path) -> CostModelService:
    return CostModelService(
        config_path=str(path), database_url=f"sqlite:///{tmp_path / 'cost.db'}"
    )


# -- MAKER already exists, and fee_fraction(MAKER) matches maker_bps -----------


def test_maker_exists_beside_taker() -> None:
    assert MAKER == "maker"
    assert TAKER == "taker"


def test_fee_fraction_maker_matches_maker_bps() -> None:
    schedule = FeeSchedule(venue="v", taker_bps=12.0, maker_bps=3.25)
    assert schedule.fee_fraction(MAKER) == pytest.approx(3.25 / 10_000.0)


# -- binance_usdm.yaml: taker 0.0005, maker 0.0002, passive penalty 0.00015 ----


def test_usdm_document_yields_its_taker_maker_and_passive_penalty(
    tmp_path: Path,
) -> None:
    schedule = _service(USDM_PATH, tmp_path).fees()
    assert schedule.fee_fraction(TAKER) == pytest.approx(USDM_TAKER_FRACTION)
    assert schedule.fee_fraction(MAKER) == pytest.approx(USDM_MAKER_FRACTION)
    assert schedule.passive_penalty_fraction == pytest.approx(
        USDM_PASSIVE_PENALTY_FRACTION
    )


def test_usdm_fee_fraction_maker_matches_its_own_maker_bps(tmp_path: Path) -> None:
    schedule = _service(USDM_PATH, tmp_path).fees()
    assert schedule.fee_fraction(MAKER) == pytest.approx(schedule.maker_bps / 10_000.0)


# -- A document with no passive fill model: its own maker, a None penalty -----


def test_a_document_with_no_fill_model_resolves_its_own_maker_and_a_none_penalty(
    tmp_path: Path,
) -> None:
    path = tmp_path / "spot_no_passive.yaml"
    _write_yaml(path, SPOT_DOCUMENT)
    schedule = _service(path, tmp_path).fees()
    assert schedule.fee_fraction(MAKER) == pytest.approx(SPOT_MAKER_BPS / 10_000.0)
    assert schedule.passive_penalty_fraction is None


def test_a_document_with_fill_model_but_no_passive_half_resolves_none(
    tmp_path: Path,
) -> None:
    document = _with_fees_block(
        {"cost_model": {"fill_model": {"aggressive": {"walk_book": True}}}}
    )
    path = tmp_path / "no_passive_half.yaml"
    _write_yaml(path, document)
    schedule = _service(path, tmp_path).fees()
    assert schedule.passive_penalty_fraction is None


def test_a_passive_half_with_no_penalty_key_resolves_none(tmp_path: Path) -> None:
    document = _with_fees_block(
        {
            "cost_model": {
                "fill_model": {
                    "passive": {"require_trade_through": True},
                    "aggressive": {"walk_book": True},
                }
            }
        }
    )
    path = tmp_path / "no_penalty_key.yaml"
    _write_yaml(path, document)
    schedule = _service(path, tmp_path).fees()
    assert schedule.passive_penalty_fraction is None


# -- A malformed (but present) penalty rate is refused, like the fee rates ----


def test_a_negative_passive_penalty_is_refused(tmp_path: Path) -> None:
    document = _with_fees_block(
        {
            "cost_model": {
                "fill_model": {
                    "passive": {"queue_position_penalty_bps": -1.0},
                }
            }
        }
    )
    path = tmp_path / "negative_penalty.yaml"
    _write_yaml(path, document)
    with pytest.raises(CostModelConfigError):
        _service(path, tmp_path).fees()


def test_a_non_finite_passive_penalty_is_refused(tmp_path: Path) -> None:
    document = _with_fees_block(
        {
            "cost_model": {
                "fill_model": {
                    "passive": {"queue_position_penalty_bps": math.nan},
                }
            }
        }
    )
    path = tmp_path / "nan_penalty.yaml"
    _write_yaml(path, document)
    with pytest.raises(CostModelConfigError):
        _service(path, tmp_path).fees()


def test_a_zero_passive_penalty_is_legal(tmp_path: Path) -> None:
    document = _with_fees_block(
        {
            "cost_model": {
                "fill_model": {
                    "passive": {"queue_position_penalty_bps": 0.0},
                }
            }
        }
    )
    path = tmp_path / "zero_penalty.yaml"
    _write_yaml(path, document)
    schedule = _service(path, tmp_path).fees()
    assert schedule.passive_penalty_fraction == 0.0


# -- The direct FeeSchedule constructor validates the same rule ---------------


def test_feeschedule_accepts_none_passive_penalty() -> None:
    schedule = FeeSchedule(venue="v", taker_bps=1.0, maker_bps=1.0)
    assert schedule.passive_penalty_fraction is None


def test_feeschedule_accepts_a_configured_passive_penalty() -> None:
    schedule = FeeSchedule(
        venue="v", taker_bps=1.0, maker_bps=1.0, passive_penalty_fraction=0.00015
    )
    assert schedule.passive_penalty_fraction == pytest.approx(0.00015)


def test_feeschedule_refuses_a_negative_passive_penalty() -> None:
    with pytest.raises(CostModelConfigError):
        FeeSchedule(
            venue="v", taker_bps=1.0, maker_bps=1.0, passive_penalty_fraction=-0.001
        )


# -- cost_model_hash is unaffected: it hashes the document, not the schedule --


def test_cost_model_hash_is_unaffected_by_the_resolved_schedule(
    tmp_path: Path,
) -> None:
    service = _service(USDM_PATH, tmp_path)
    document = service.document
    assert service.cost_model_hash() == cost_model_digest(document)


# -- Helpers --------------------------------------------------------------------


def _with_fees_block(document: dict) -> dict:
    """Layer ``fees`` (and a venue/version) onto a partial ``cost_model`` document."""
    block = document["cost_model"]
    block.setdefault("version", "2026.09.9")
    block.setdefault("venue", "testnet_spot_passive_variants")
    block["fees"] = {"taker_bps": SPOT_TAKER_BPS, "maker_bps": SPOT_MAKER_BPS}
    return document


def _write_yaml(path: Path, document: dict) -> None:
    import yaml

    path.write_text(yaml.safe_dump(document), encoding="utf-8")
