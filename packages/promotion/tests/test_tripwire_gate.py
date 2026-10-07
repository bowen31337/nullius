"""bug_spec_tripwire_false_positives.xml, bug 2: promotion consults the tripwires.

The bug's own reproduction: write a ``tripwire_verdict`` row with
``rejected = 1`` for a node, pre-register it, then call
``promotion.record_decision`` for it — before this fix, the decision landed
anyway.  This suite pins the gate (:func:`promotion.rejects_tripwire_flagged`)
on its own, and pins :mod:`promotion.decision`'s wiring of it: a flagged or
unprobed node is refused before the write, an operator's
``acknowledge_tripwires`` reason bypasses the refusal and is persisted, and a
refusal leaves the pre-registration's row open.

``tripwire_verdict`` is the orchestrator's own table
(:data:`orchestrator._evaluate.TRIPWIRE_VERDICT_TABLE`); this suite creates it
by hand, restating its shape, rather than importing the orchestrator member —
the same restraint :mod:`promotion.tripwire_gate` itself observes, and the
reason this file needs no ``orchestrator`` on ``PYTHONPATH`` to run alone.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
import uuid
from pathlib import Path

import promotion as member
import pytest
from conftest import DEFAULT_CRITERIA_DOCUMENT, EPOCH_ID, NODE_ID
from promotion import (
    MIN_ACKNOWLEDGEMENT_LENGTH,
    PROMOTION_TRIPWIRE_OVERRIDE_TABLE,
    TRIPWIRE_FLAGGED_ERROR_CODE,
    TRIPWIRE_UNMEASURED_ERROR_CODE,
    TRIPWIRE_VERDICT_TABLE,
    PreRegisterEndpoint,
    PreRegistrationRequest,
    PromotionDecisions,
    TripwireFlaggedError,
    record_decision,
    rejects_tripwire_flagged,
)

#: The shape :func:`orchestrator._evaluate._persist_tripwire_verdicts` writes,
#: restated here by hand rather than imported — see the module docstring.
_CREATE_TRIPWIRE_VERDICT_SQL = f"""
CREATE TABLE IF NOT EXISTS {TRIPWIRE_VERDICT_TABLE} (
    node_id TEXT NOT NULL,
    probe TEXT NOT NULL,
    rejected INTEGER NOT NULL,
    figure REAL,
    measured INTEGER NOT NULL,
    recorded_at TEXT NOT NULL,
    PRIMARY KEY (node_id, probe)
)
"""

REGISTERED_AT = dt.datetime(2026, 3, 1, tzinfo=dt.UTC)
DECIDED_AT = dt.datetime(2026, 3, 2, tzinfo=dt.UTC)

#: A reason long enough to pass :data:`MIN_ACKNOWLEDGEMENT_LENGTH`.
GOOD_REASON = "reviewed by the signal desk, promoting despite the flag"


def _write_verdicts(database_url: str, node: str, rows: list[tuple]) -> None:
    """Write ``tripwire_verdict`` rows for ``node`` — one tuple per probe:
    ``(probe, rejected, figure, measured)``.
    """
    path = Path(database_url.removeprefix("sqlite:///"))
    connection = sqlite3.connect(path)
    try:
        with connection:
            connection.execute(_CREATE_TRIPWIRE_VERDICT_SQL)
            connection.executemany(
                "INSERT INTO tripwire_verdict "
                "(node_id, probe, rejected, figure, measured, recorded_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (node, probe, rejected, figure, measured, "2026-01-01T00:00:00")
                    for probe, rejected, figure, measured in rows
                ],
            )
    finally:
        connection.close()


def _request(**overrides) -> PreRegistrationRequest:
    fields = {
        "node_id": NODE_ID,
        "epoch_id": EPOCH_ID,
        "criteria": dict(DEFAULT_CRITERIA_DOCUMENT),
    }
    fields.update(overrides)
    return PreRegistrationRequest(**fields)


@pytest.fixture
def registered(seeded_database) -> PromotionDecisions:
    """A decision store over a database where :data:`NODE_ID` is pre-registered.

    The same shape :mod:`test_promotion_decision`'s own fixture takes: a
    registration through feature 291's endpoint, at a clock this suite names,
    so the gate and the decision share one row to act on.
    """
    PreRegisterEndpoint(seeded_database).post(
        _request(), clock=lambda: REGISTERED_AT
    )
    return PromotionDecisions(seeded_database.database_url)


@pytest.fixture
def raw_registry_row(database_url: str):
    """Read ``promotion_registry``'s ``decided_at`` for :data:`NODE_ID` raw."""

    def _decided_at() -> str | None:
        connection = sqlite3.connect(Path(database_url.removeprefix("sqlite:///")))
        try:
            cursor = connection.execute(
                "SELECT decided_at FROM promotion_registry WHERE node_id = ?",
                (NODE_ID,),
            )
            try:
                row = cursor.fetchone()
            finally:
                cursor.close()
        finally:
            connection.close()
        return None if row is None else row[0]

    return _decided_at


# -- The gate, on its own ------------------------------------------------------------


def test_a_flagged_node_is_refused_naming_the_probes(database_url: str) -> None:
    node = str(uuid.uuid4())
    _write_verdicts(
        database_url,
        node,
        [
            ("time_shuffle", 1, 3.68, 1),
            ("label_permute", 0, 0.5, 1),
        ],
    )
    with pytest.raises(TripwireFlaggedError) as raised:
        rejects_tripwire_flagged(node, database_url=database_url)
    message = str(raised.value)
    assert message.startswith(TRIPWIRE_FLAGGED_ERROR_CODE)
    assert "time_shuffle" in message
    assert "3.68" in message
    # The clean probe is not named as a rejection.
    assert "label_permute=0.5" not in message


def test_a_clean_node_passes(database_url: str) -> None:
    node = str(uuid.uuid4())
    _write_verdicts(
        database_url,
        node,
        [
            ("time_shuffle", 0, 1.2, 1),
            ("label_permute", 0, 0.4, 1),
            ("lookback_jitter", 0, None, 0),
        ],
    )
    assert rejects_tripwire_flagged(node, database_url=database_url) is None


def test_an_unprobed_node_is_refused_as_unmeasured(database_url: str) -> None:
    # The table exists (another node's rows are in it) but this node holds
    # none at all.
    other = str(uuid.uuid4())
    _write_verdicts(database_url, other, [("time_shuffle", 0, 1.0, 1)])
    node = str(uuid.uuid4())
    with pytest.raises(TripwireFlaggedError) as raised:
        rejects_tripwire_flagged(node, database_url=database_url)
    message = str(raised.value)
    assert message.startswith(TRIPWIRE_UNMEASURED_ERROR_CODE)
    assert node in message


def test_all_unmeasured_is_refused(database_url: str) -> None:
    node = str(uuid.uuid4())
    _write_verdicts(
        database_url,
        node,
        [
            ("time_shuffle", 0, None, 0),
            ("label_permute", 0, None, 0),
        ],
    )
    with pytest.raises(TripwireFlaggedError) as raised:
        rejects_tripwire_flagged(node, database_url=database_url)
    assert str(raised.value).startswith(TRIPWIRE_UNMEASURED_ERROR_CODE)


def test_a_measured_rejection_is_not_defeated_by_an_unmeasured_sibling(
    database_url: str,
) -> None:
    # A probe recorded measured=0 is never a rejection, even sitting beside
    # one that is — the mix must still flag on the measured probe.
    node = str(uuid.uuid4())
    _write_verdicts(
        database_url,
        node,
        [
            ("time_shuffle", 1, 4.0, 1),
            ("seed", 0, None, 0),
        ],
    )
    with pytest.raises(TripwireFlaggedError) as raised:
        rejects_tripwire_flagged(node, database_url=database_url)
    assert str(raised.value).startswith(TRIPWIRE_FLAGGED_ERROR_CODE)


def test_a_deployment_with_no_tripwire_verdict_table_is_not_refused(
    database_url: str,
) -> None:
    # No evaluation ever ran step 10's sweep against this database — the
    # table itself does not exist — and the gate treats that as not
    # applicable rather than as an unprobed node (see the module docstring).
    assert rejects_tripwire_flagged(str(uuid.uuid4()), database_url=database_url) is None


def test_a_rejected_row_measured_zero_is_not_a_rejection(database_url: str) -> None:
    # A hand-written or stale row can carry rejected=1 beside measured=0;
    # the bug's own wording is explicit that an unmeasured probe is never a
    # rejection, whatever its own rejected column says.
    node = str(uuid.uuid4())
    _write_verdicts(database_url, node, [("time_shuffle", 1, 3.9, 0)])
    with pytest.raises(TripwireFlaggedError) as raised:
        rejects_tripwire_flagged(node, database_url=database_url)
    # Refused as unmeasured (no measured probe at all), not as flagged.
    assert str(raised.value).startswith(TRIPWIRE_UNMEASURED_ERROR_CODE)


# -- The wiring into record_decision --------------------------------------------------


def test_record_decision_refuses_a_flagged_node_and_writes_no_decision_row(
    registered, raw_registry_row
) -> None:
    _write_verdicts(
        registered.database_url, NODE_ID, [("time_shuffle", 1, 3.68, 1)]
    )
    with pytest.raises(TripwireFlaggedError) as raised:
        registered.record_decision(NODE_ID, clock=lambda: DECIDED_AT)
    assert str(raised.value).startswith(TRIPWIRE_FLAGGED_ERROR_CODE)
    assert raw_registry_row() is None


def test_record_decision_refuses_an_unprobed_node(registered) -> None:
    # The table exists (another node's row) but NODE_ID holds none at all.
    _write_verdicts(
        registered.database_url, str(uuid.uuid4()), [("time_shuffle", 0, 1.0, 1)]
    )
    with pytest.raises(TripwireFlaggedError) as raised:
        registered.record_decision(NODE_ID, clock=lambda: DECIDED_AT)
    assert str(raised.value).startswith(TRIPWIRE_UNMEASURED_ERROR_CODE)


def test_record_decision_proceeds_for_a_clean_node(
    registered, raw_registry_row
) -> None:
    _write_verdicts(
        registered.database_url, NODE_ID, [("time_shuffle", 0, 1.0, 1)]
    )
    record, created = registered.record_decision(NODE_ID, clock=lambda: DECIDED_AT)
    assert created is True
    assert record.decided_at == DECIDED_AT
    assert raw_registry_row() == DECIDED_AT.isoformat()


def test_the_override_records_the_reason_and_the_probes_and_passes(
    registered, raw_registry_row
) -> None:
    _write_verdicts(
        registered.database_url, NODE_ID, [("time_shuffle", 1, 3.68, 1)]
    )
    record, created = registered.record_decision(
        NODE_ID, clock=lambda: DECIDED_AT, acknowledge_tripwires=GOOD_REASON
    )
    assert created is True
    assert raw_registry_row() == DECIDED_AT.isoformat()

    connection = sqlite3.connect(
        Path(registered.database_url.removeprefix("sqlite:///"))
    )
    try:
        cursor = connection.execute(
            f"SELECT reason, probes FROM {PROMOTION_TRIPWIRE_OVERRIDE_TABLE} "
            "WHERE node_id = ?",
            (NODE_ID,),
        )
        row = cursor.fetchone()
    finally:
        connection.close()
    assert row is not None
    assert row[0] == GOOD_REASON
    assert row[1] == "time_shuffle"
    assert record.decided_at == DECIDED_AT


def test_a_short_reason_is_refused_and_writes_nothing(
    registered, raw_registry_row
) -> None:
    _write_verdicts(
        registered.database_url, NODE_ID, [("time_shuffle", 1, 3.68, 1)]
    )
    assert len("too short") < MIN_ACKNOWLEDGEMENT_LENGTH
    with pytest.raises(TripwireFlaggedError):
        registered.record_decision(
            NODE_ID, clock=lambda: DECIDED_AT, acknowledge_tripwires="too short"
        )
    assert raw_registry_row() is None
    connection = sqlite3.connect(
        Path(registered.database_url.removeprefix("sqlite:///"))
    )
    try:
        cursor = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND "
            "name = ?",
            (PROMOTION_TRIPWIRE_OVERRIDE_TABLE,),
        )
        table_exists = cursor.fetchone() is not None
        if table_exists:
            cursor = connection.execute(
                f"SELECT 1 FROM {PROMOTION_TRIPWIRE_OVERRIDE_TABLE} "
                "WHERE node_id = ?",
                (NODE_ID,),
            )
            assert cursor.fetchone() is None
    finally:
        connection.close()


def test_the_override_bypasses_an_unmeasured_refusal_too(
    registered, raw_registry_row
) -> None:
    # The override is general: it also lets a node nobody probed through,
    # since an operator may have a legitimate reason this node was never
    # swept (e.g. it predates step 10's rollout).
    _record, created = registered.record_decision(
        NODE_ID, clock=lambda: DECIDED_AT, acknowledge_tripwires=GOOD_REASON
    )
    assert created is True
    assert raw_registry_row() == DECIDED_AT.isoformat()


def test_the_vocabulary_is_reachable_from_the_members_surface() -> None:
    assert member.rejects_tripwire_flagged is rejects_tripwire_flagged
    assert member.record_decision is record_decision
    assert member.TripwireFlaggedError is TripwireFlaggedError
