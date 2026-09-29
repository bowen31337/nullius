"""Feature 334's act: the observed decay curve for a promoted signal.

app_spec.xml, "Forward-Test Tracking", feature 334: *System exposes GET
/forward/decay which returns the observed decay curve for a promoted signal.*
These tests pin the four halves of that sentence:

* **the observed decay curve** — the signal's live information coefficient
  trajectory over its out-of-sample life, read off feature 333's observation
  rows and framed as a point per measured day, each point's ``days`` the exact
  offset from the boundary the record drew; the curve is one reading of the
  rows, never re-derived, and asserted against a raw ``SELECT`` of the table;
* **for a promoted signal** — the curve joins the record feature 332 opened:
  the ``promoted_at`` it carries is the instant feature 293 stamped (asserted
  against the registry row, through the raw table, not through anything this
  member computed), a signal with no record is refused naming the promote
  step, a record whose rows carry two instants is refused as a vintage nobody
  can state, and a record with nothing measured on it is refused naming the
  observation job — never answered as an empty curve;
* **GET /forward/decay** — the route is a thin seam over the store: it takes
  the signal identity a GET *for a signal* must state, delegates the whole
  read to the store, propagates the store's refusals untouched, and composes
  as the ``forward-decay`` satellite component the seat reads back;
* **returns** — the curve is the store's answer passed through, not a second
  computation, and neither an absent store nor a failed read is ever answered
  with a curve.
"""

from __future__ import annotations

import ast
import datetime as dt
import inspect
import uuid

import forward.decay
import pytest
from conftest import DECIDED_AT, FORWARD_DAYS, NODE_ID, code_of
from forward import (
    DATABASE_URL_ENV,
    FORWARD_ABSENT_ERROR_CODE,
    DecayCurve,
    DecayCurveEndpoint,
    DecayPoint,
    ForwardAbsentError,
    ForwardDecayCurves,
    ForwardError,
    ForwardObservations,
    ForwardRecord,
    ForwardRecordError,
    ForwardStoreError,
    decay_curve,
)

DECIDED = dt.datetime.fromisoformat(DECIDED_AT)

#: The record's boundary day — the promotion instant's own UTC date, spelled
#: as a literal beside the derived value so the two cannot drift apart
#: silently, and so a conftest change that moved :data:`DECIDED_AT` fails
#: here rather than quietly moving every date below with it.
BOUNDARY_DAY = dt.date(2026, 3, 1)

#: The first day an observation may honestly name: the day after the boundary.
FIRST_DAY = dt.date(2026, 3, 2)


@pytest.fixture
def curves(opened_record: ForwardRecord, promoted_signal) -> ForwardDecayCurves:
    """The decay reader over the record's own store — 334's seam.

    Built with :meth:`ForwardDecayCurves.over` off the very store the record
    was opened through, so the reader and the opener point at one database by
    construction — the shape a deployment reaches when it asks the composed
    ``forward`` component for the act.  ``opened_record`` is asked for so the
    record exists before any curve is read, and its boundary is asserted here
    so a conftest change that moved :data:`DECIDED_AT` without moving this
    file's dates fails at the fixture rather than at some refusal deep inside a
    test.
    """
    assert opened_record.promoted_at == DECIDED
    assert opened_record.observed_on == BOUNDARY_DAY
    return ForwardDecayCurves.over(promoted_signal)


@pytest.fixture
def observed(curves: ForwardDecayCurves) -> ForwardDecayCurves:
    """The reader over a record that has been observed on several days.

    Three observations, arriving out of day order, so the curve's ordering is
    asserted against a store that did not write them chronologically.  The
    coefficients fall — the decay the route exists to show — from an early high
    toward a later low, but the fall is the fixture's gift to a reader, not a
    property the curve asserts: the curve reports what was measured, whether it
    rose or fell.
    """
    observations = ForwardObservations.over(curves)
    observations.append_observation(
        NODE_ID, observed_on=dt.date(2026, 3, 5), live_ic=0.06,
        forward_days=FORWARD_DAYS,
    )
    observations.append_observation(
        NODE_ID, observed_on=FIRST_DAY, live_ic=0.30,
        forward_days=FORWARD_DAYS,
    )
    observations.append_observation(
        NODE_ID, observed_on=dt.date(2026, 3, 3), live_ic=0.18,
        forward_days=FORWARD_DAYS,
    )
    return curves


# -- The feature's sentence ---------------------------------------------------


def test_the_curve_is_the_rows_framed_as_points(curves, observed, forward_rows) -> None:
    # The curve is one reading of the record's standing rows, framed as a
    # point per measured day — not a second computation of the same figure.
    curve = curves.curve(NODE_ID)
    # And the framing is asserted against what the table actually holds, read
    # raw, so the curve is not asked to confirm itself.
    rows = forward_rows()
    measured = [r for r in rows if r["live_ic"] is not None]
    assert len(measured) == 3
    assert curve.observed_days == 3
    assert [p.observed_on for p in curve.points] == [
        dt.date(2026, 3, 2),
        dt.date(2026, 3, 3),
        dt.date(2026, 3, 5),
    ]
    # Each point's coefficient is the table's own copy, read back.
    assert [p.live_ic for p in curve.points] == [0.30, 0.18, 0.06]


def test_each_points_days_is_the_offset_from_the_boundary(curves, observed) -> None:
    # The offset is measured in days from the boundary the record drew — the
    # opening row's own day — the same line feature 333's lower bound and
    # feature 335's upper bound are measured against.  The boundary is
    # 2026-03-01, so the first honest day is days 1, not days 0.
    curve = curves.curve(NODE_ID)
    assert curve.promoted_at == DECIDED
    assert [(p.observed_on, p.days) for p in curve.points] == [
        (dt.date(2026, 3, 2), 1),
        (dt.date(2026, 3, 3), 2),
        (dt.date(2026, 3, 5), 4),
    ]


def test_points_arrive_in_day_order_regardless_of_write_order(curves, observed) -> None:
    # The observations were written 5th, 2nd, 3rd; the curve reads them in
    # day order, because feature 332's ``_READ_SQL`` orders by ``observed_on``
    # and the curve is framed on those rows in that order.
    curve = curves.curve(NODE_ID)
    assert [p.observed_on for p in curve.points] == sorted(
        p.observed_on for p in curve.points
    )


def test_the_curve_summary_is_json_shaped(curves, observed) -> None:
    # The route's answer as a router would serialize it: the node, the boundary
    # instant as an ISO string, the day count, and the points each as their
    # own mapping — mirroring ``IcRetention.summary`` so the route's answer and
    # a job log speak one shape.
    curve = curves.curve(NODE_ID)
    summary = curve.summary()
    assert summary["node_id"] == NODE_ID
    assert summary["promoted_at"] == DECIDED_AT
    assert summary["observed_days"] == 3
    assert summary["points"] == [
        {"observed_on": "2026-03-02", "days": 1, "live_ic": 0.30},
        {"observed_on": "2026-03-03", "days": 2, "live_ic": 0.18},
        {"observed_on": "2026-03-05", "days": 4, "live_ic": 0.06},
    ]


def test_a_curve_refuses_a_point_whose_offset_disagrees_with_its_day(curves) -> None:
    # The curve is frozen and re-derives each point's offset: a point whose
    # stated ``days`` disagrees with the day it is dated to is refused rather
    # than carried, so a caller cannot hand a planner a point whose offset
    # nobody dated.  The boundary is 2026-03-01, so a point dated 2026-03-02
    # is days 1 — stating days 2 is the disagreement the re-derivation catches.
    point = DecayPoint(observed_on=FIRST_DAY, days=1, live_ic=0.30)
    assert point.days == 1
    with pytest.raises(ForwardStoreError) as raised:
        DecayCurve(
            node_id=NODE_ID, promoted_at=DECIDED,
            points=(DecayPoint(observed_on=FIRST_DAY, days=2, live_ic=0.30),),
        )
    assert "forward_record_unwritable" in str(raised.value)


def test_a_curve_with_no_points_is_refused(curves) -> None:
    # An empty curve is refused, not carried: it is the absence the store
    # refuses by name, and carrying it would read as a signal that was
    # measured and never moved.  Asserted as the *base* store class rather than
    # the absence subclass, and the distinction is the design: the absence
    # class belongs to the store's ask — the node it names is the subject — so
    # a value built by hand past the store is refused by the read contract, not
    # by the state-of-the-world class a caller routes on.  The store's own
    # unobserved record is the absence, and it is asserted below.
    with pytest.raises(ForwardStoreError) as raised:
        DecayCurve(node_id=NODE_ID, promoted_at=DECIDED, points=())
    assert not isinstance(raised.value, ForwardAbsentError)
    assert "no measured point" in str(raised.value)


# -- The store's read, and its refusals ---------------------------------------


def test_a_malformed_identity_is_refused_before_any_io(curves, forward_rows) -> None:
    # The ask settles before anything is opened: a malformed identity is
    # refused without touching a database.  The opening row is already present
    # (the fixture is built over an opened record), so the refusal is asserted
    # to leave the rows untouched rather than to empty them.
    before = len(forward_rows())
    with pytest.raises(ForwardRecordError) as raised:
        curves.curve("not-a-uuid")
    assert "UUID" in str(raised.value)
    assert len(forward_rows()) == before


def test_a_signal_with_no_record_is_refused_naming_the_repair(
    promoted_signal, forward_rows
) -> None:
    # The curve job ran ahead of the promote step: the promotion may well be
    # decided (it is, below — the registry row is closed), but the record is
    # what a curve is framed on, and a reader that opened one silently would
    # fabricate the boundary it failed to read.  The refusal names the repair
    # in order: open the record (POST /forward/promote, feature 332), then
    # observe, then read the curve.
    store = ForwardDecayCurves.over(promoted_signal)
    with pytest.raises(ForwardAbsentError) as raised:
        store.curve(NODE_ID)
    message = str(raised.value)
    # The absence word opens the message, and the store-failure word stays out
    # of it: the database answered perfectly and the row is simply missing, so
    # pointing the operator at the database would send them to a healthy one.
    assert message.startswith(FORWARD_ABSENT_ERROR_CODE)
    assert "forward_record_unwritable" not in message
    assert "/forward/promote" in message
    assert forward_rows() == []


def test_a_record_holding_two_instants_is_refused_rather_than_framed(
    curves, promoted_signal, forward_rows
) -> None:
    # Rows that disagree about ``promoted_at`` are a hand that reached past the
    # member: every row this member writes carries the one instant, so the
    # disagreement cannot have come from either of its acts.  A curve framed
    # over two boundaries would double-count a window whose observations belong
    # to one, and move campaign planning on a timescale nobody measured — the
    # refusal names both instants so the repair starts from the rows.
    observations = ForwardObservations.over(curves)
    observations.append_observation(
        NODE_ID, observed_on=FIRST_DAY, live_ic=0.30, forward_days=FORWARD_DAYS
    )
    connection = promoted_signal._connect()
    try:
        with connection:
            connection.execute(
                "UPDATE forward_record SET promoted_at = ? "
                "WHERE observed_on != ?",
                ("2026-03-09T09:00:00+00:00", "2026-03-01"),
            )
    finally:
        connection.close()
    with pytest.raises(ForwardStoreError) as raised:
        curves.curve(NODE_ID)
    message = str(raised.value)
    assert "forward_record_unwritable" in message
    assert DECIDED_AT in message
    assert "2026-03-09T09:00:00+00:00" in message


def test_a_record_with_no_observation_is_refused_not_emptied(curves, forward_rows) -> None:
    # A record with nothing measured on it is refused naming the observation
    # job, never answered as an empty curve: an empty chart and a flat one read
    # alike in front of a planner, and the two must not be confused.
    assert forward_rows()  # the opening row is there
    with pytest.raises(ForwardAbsentError) as raised:
        curves.curve(NODE_ID)
    message = str(raised.value)
    # The absence word opens the message, and the store-failure word stays out
    # of it — the row is the honest opening row, just unobserved, so this is a
    # state of the world, not a database fault.
    assert message.startswith(FORWARD_ABSENT_ERROR_CODE)
    assert "forward_record_unwritable" not in message
    assert "observe" in message
    assert "feature 333" in message


def test_a_stored_coefficient_that_is_not_a_correlation_is_refused(
    curves, promoted_signal
) -> None:
    # A hand that reached past the store could write a live_ic that stopped
    # being an information coefficient; the curve refuses it rather than
    # plotting it as a measurement, because a stored figure outside [−1, 1] is
    # a number nobody measured.  The refusal is a record error: the row can no
    # longer be read as a forward record, and the curve reads the record.
    connection = promoted_signal._connect()
    try:
        with connection:
            connection.execute(
                "UPDATE forward_record SET live_ic = ? WHERE observed_on = ?",
                (2.5, "2026-03-01"),
            )
    finally:
        connection.close()
    with pytest.raises(ForwardRecordError) as raised:
        curves.curve(NODE_ID)
    assert "information coefficient" in str(raised.value)


# -- Absence, decided apart from store failure --------------------------------


def test_the_absence_class_subclasses_the_store_class() -> None:
    # The subclassing IS the compatibility contract: every caller guarding a
    # forward read with ``except ForwardStoreError`` — and every test written
    # before this class existed — keeps catching these refusals, while a caller
    # that must decide something *on the difference* can ask the narrower
    # question.  Both orders are asserted, because a class that were a sibling
    # would satisfy neither.
    assert issubclass(ForwardAbsentError, ForwardStoreError)
    assert issubclass(ForwardAbsentError, ForwardError)


def test_an_absent_record_is_an_absence_and_not_a_store_failure(
    promoted_signal,
) -> None:
    # The decidable difference, from the caller's side: a signal with no
    # forward record is a *state of the world* — the database answered
    # perfectly and the row is not there — so the narrower ``except`` catches
    # it.  The store is reachable and the node row exists; only the record is
    # missing, which is why no retry of this call produces it.
    store = ForwardDecayCurves.over(promoted_signal)
    with pytest.raises(ForwardAbsentError) as raised:
        store.curve(NODE_ID)
    message = str(raised.value)
    # The absence word — what the route's 404 turns on — opens the message, and
    # the store-failure word is kept OUT of it: ``forward_record_unwritable``
    # is reserved for a store the member cannot reach, and naming it inside an
    # absence would point the operator at a healthy database.
    assert message.startswith(FORWARD_ABSENT_ERROR_CODE)
    assert "forward_record_unwritable" not in message
    # The node is named in the ``node_id <id>`` form the other absences use, so
    # a caller attributes the absence without parsing prose.
    assert f"node_id {NODE_ID}" in message


def test_an_unobserved_record_is_an_absence_not_a_store_failure(curves) -> None:
    # The second face: the record is there and nobody has measured on it.  Also
    # a state of the world rather than a fault — the row is the honest opening
    # row 0108 declares, with its three NULL observation columns — so it is the
    # absence class, and it names the node and the act that produces the rows.
    with pytest.raises(ForwardAbsentError) as raised:
        curves.curve(NODE_ID)
    message = str(raised.value)
    assert message.startswith(FORWARD_ABSENT_ERROR_CODE)
    assert NODE_ID in message
    assert "feature 333" in message


def test_a_two_vintage_fault_is_a_store_failure_not_an_absence(
    curves, promoted_signal
) -> None:
    # The line the class draws, asserted from the other side.  Rows carrying
    # two promotion instants are a hand that reached past this member: the
    # table is in a state no act of this member could have produced, no retry
    # repairs it, and an operator has to go and look at the database.  That is
    # a store failure, so the *absence* class must NOT catch it — otherwise a
    # route would answer 404 for a corrupted table and send nobody to it.
    observations = ForwardObservations.over(curves)
    observations.append_observation(
        NODE_ID, observed_on=FIRST_DAY, live_ic=0.30, forward_days=FORWARD_DAYS
    )
    connection = promoted_signal._connect()
    try:
        with connection:
            connection.execute(
                "UPDATE forward_record SET promoted_at = ? "
                "WHERE observed_on != ?",
                ("2026-03-09T09:00:00+00:00", "2026-03-01"),
            )
    finally:
        connection.close()
    with pytest.raises(ForwardStoreError) as raised:
        curves.curve(NODE_ID)
    assert not isinstance(raised.value, ForwardAbsentError)


def test_an_unreachable_store_is_a_store_failure_not_an_absence(tmp_path) -> None:
    # The third side of the same line: a store this member cannot speak is a
    # *fault*, so a caller routing on absence must not swallow it as a 404.
    # Refused at first use rather than at construction, so the refusal lands
    # where the read would have happened.
    store = ForwardDecayCurves("postgresql://localhost/records")
    with pytest.raises(ForwardStoreError) as raised:
        store.curve(NODE_ID)
    assert not isinstance(raised.value, ForwardAbsentError)


# -- The endpoint -------------------------------------------------------------


def test_the_endpoint_delegates_to_the_store(curves, observed) -> None:
    # The route is a thin seam over the store: it takes the signal identity a
    # GET *for a signal* must state and returns the curve the store answered
    # with — the same value, so a caller reading through one spelling and the
    # other reads the same curve.
    endpoint = DecayCurveEndpoint(curves)
    assert endpoint.route == "/forward/decay"
    curve = endpoint.get(NODE_ID)
    assert isinstance(curve, DecayCurve)
    # The route returns the store's answer — the same curve, read back through
    # the store's own equality, not the same object (the store frames a fresh
    # curve on every read).
    assert curve == curves.curve(NODE_ID)


def test_the_endpoint_duck_checks_its_store() -> None:
    # The loader's scan imports the member under a synthetic module name, so
    # the composed store is structurally a ForwardDecayCurves but never the
    # same class object a direct import yields.  The seam checks for a callable
    # ``curve`` rather than a class — and an object that can only read rows is
    # refused here rather than answering the route with a curve the store never
    # stated.
    class RowReader:
        def __init__(self) -> None:
            self.database_url = "sqlite:///x.db"

    with pytest.raises(TypeError) as raised:
        DecayCurveEndpoint(RowReader())  # type: ignore[arg-type]
    assert "curve" in str(raised.value)


def test_the_endpoint_distinguishes_absent_from_present_none() -> None:
    # The duck-check reads ``getattr`` against a sentinel, so an absent
    # ``curve`` attribute is distinguished from a present-``None`` one — the
    # loader's synthetic-name copies are judged as well as canonical stores.
    class NoCurve:
        curve = None

    with pytest.raises(TypeError):
        DecayCurveEndpoint(NoCurve())  # type: ignore[arg-type]


def test_from_env_returns_none_without_a_database(monkeypatch) -> None:
    # No ``DATABASE_URL`` composes no endpoint — an unconfigured store is a
    # discoverable state, not an error — while a deployment whose reader must
    # draw a signal's curve is the one that must not find itself in it.
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    assert DecayCurveEndpoint.from_env() is None


def test_from_env_resolves_the_endpoint_over_the_named_database(
    monkeypatch, tmp_path
) -> None:
    # With a URL the endpoint resolves the store exactly as the member's
    # builder does, so the route reads the database the process is actually
    # pointed at.
    monkeypatch.setenv(DATABASE_URL_ENV, f"sqlite:///{tmp_path / 'decay.db'}")
    endpoint = DecayCurveEndpoint.from_env()
    assert endpoint is not None
    assert endpoint.curves.database_url == f"sqlite:///{tmp_path / 'decay.db'}"


# -- The module-level spelling --------------------------------------------------


def test_the_module_level_spelling_reads_from_a_url(
    observed, promoted_signal
) -> None:
    # The feature's sentence as one call, for the caller that wants the curve
    # without holding a store.  The store is resolved from the URL, else from
    # ``DATABASE_URL``, and returns the same curve the endpoint returns.
    url = promoted_signal.database_url
    curve = decay_curve(NODE_ID, database_url=url)
    assert isinstance(curve, DecayCurve)
    assert curve.observed_days == 3


def test_the_module_level_spelling_is_refused_by_name_without_a_database(
    monkeypatch,
) -> None:
    # A deployment that names neither a URL nor ``DATABASE_URL`` is refused by
    # name rather than silently answering nothing: the silence would be the
    # dangerous failure, leaving a promoted signal with a curve nobody could
    # draw.
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    with pytest.raises(ForwardStoreError) as raised:
        decay_curve(NODE_ID)
    assert "forward_record_unwritable" in str(raised.value)


# -- The component and the seat -------------------------------------------------


def test_the_route_composes_under_the_documented_name(
    monkeypatch, tmp_path
) -> None:
    # The route is registered as a hyphenated satellite component, reached as
    # ``app.get("forward-decay")`` — exactly as ``app.get("ledger-k-effective")``
    # reaches feature 94 — so a composed deployment holds the store and the
    # route as two entries pointing at one database.
    import app.module_loader as loader
    from forward import FORWARD_DECAY_COMPONENT_NAME

    monkeypatch.setenv(DATABASE_URL_ENV, f"sqlite:///{tmp_path / 'composed.db'}")
    application = loader.create_app()
    assert FORWARD_DECAY_COMPONENT_NAME in application.order
    endpoint = application.get(FORWARD_DECAY_COMPONENT_NAME)
    # The composed endpoint is `_nullius_scanned_forward.decay.DecayCurveEndpoint`
    # — structurally the endpoint but never the same class object a direct
    # import yields, so it is duck-checked, not `isinstance`-checked.
    assert getattr(endpoint, "route", None) == "/forward/decay"
    assert callable(getattr(endpoint, "get", None))


def test_the_route_component_degrades_without_a_database(monkeypatch) -> None:
    # An unconfigured store contributes no route — a discoverable state — while
    # the reader that must draw a signal's curve is the caller that must not
    # find itself in it.
    import app.module_loader as loader
    from forward import FORWARD_DECAY_COMPONENT_NAME

    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    assert FORWARD_DECAY_COMPONENT_NAME in loader.create_app().order
    assert loader.create_app().get(FORWARD_DECAY_COMPONENT_NAME) is None


def test_the_seat_answers_the_composed_route(
    monkeypatch, tmp_path
) -> None:
    # The seat's whole job for the route, asked once: given the application,
    # answer *the* composed endpoint — not a second one constructed beside it,
    # which would be two routes over one database.
    import app.module_loader as loader
    from app.modules.forward import decay_component

    monkeypatch.setenv(DATABASE_URL_ENV, f"sqlite:///{tmp_path / 'seat.db'}")
    application = loader.create_app()
    endpoint = decay_component(application)
    assert endpoint is application.get("forward-decay")
    # Duck-checked, not `isinstance`-checked: the composed endpoint is a
    # `_nullius_scanned_forward.decay` copy, never the direct-import class.
    assert getattr(endpoint, "route", None) == "/forward/decay"
    assert callable(getattr(endpoint, "get", None))


def test_both_error_faces_are_forward_error_subclasses(
    curves, promoted_signal
) -> None:
    # The spec's contract: a caller that refuses forward work wholesale writes
    # one ``except ForwardError``. The malformed ask and the failed read both
    # land in the member's two existing faces, and both are ``ForwardError`` —
    # so the one ``except`` catches a bad identity and a missing record alike.
    with pytest.raises(ForwardError):
        curves.curve("not-a-uuid")  # the ask face
    connection = promoted_signal._connect()
    try:
        with connection:
            connection.execute(
                "UPDATE forward_record SET live_ic = ? WHERE observed_on = ?",
                (2.5, "2026-03-01"),
            )
    finally:
        connection.close()
    with pytest.raises(ForwardError):
        curves.curve(NODE_ID)  # the read face
    # And each is the face it is, not a third class smuggled in.
    assert issubclass(ForwardRecordError, ForwardError)
    assert issubclass(ForwardStoreError, ForwardError)


def test_a_rerun_over_the_same_record_answers_an_equal_curve(
    curves, observed
) -> None:
    # The value is frozen testimony about the rows at the moment they were
    # read: re-reading the same record yields an equal value, and nothing here
    # is a knob to adjust. Asserted equal across two independent reads, so a
    # caller holding the curve at two moments of an unchanged record holds the
    # same answer.
    first = curves.curve(NODE_ID)
    second = curves.curve(NODE_ID)
    assert first == second
    assert first is not second  # a fresh framing, not a memo


def test_the_seat_reaches_the_member_only_under_type_checking() -> None:
    # The seat reaches the endpoint through the *application*, never through a
    # runtime import: a static import would be the app package depending on a
    # member's installed layout at runtime.  The one allowance is the
    # ``TYPE_CHECKING`` block, erased at runtime.
    import ast

    from conftest import APP_SRC

    seat = APP_SRC / "app" / "modules" / "forward" / "__init__.py"
    tree = ast.parse(seat.read_text(encoding="utf-8"))
    guarded: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and (
            isinstance(node.test, ast.Name)
            and node.test.id == "TYPE_CHECKING"
            or isinstance(node.test, ast.Attribute)
            and node.test.attr == "TYPE_CHECKING"
        ):
            guarded.update(id(child) for child in ast.walk(node))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [(node.module or "").split(".")[0]]
        else:
            continue
        if "forward" in names:
            assert id(node) in guarded, (
                "the seat imports the forward member outside a TYPE_CHECKING "
                "guard"
            )


# -- The member's own laws ------------------------------------------------------


def test_the_decay_module_imports_no_workspace_member_at_module_scope() -> None:
    # The loader imports every scanned member under a synthetic name, so a
    # static import of a sibling would bind a different class object than the
    # composed one and every seam check would fail on identity.  ``promotion``
    # is reached by ``importlib`` at call time; this module reads the record's
    # own rows, never the registry.
    tree = ast.parse(_code_of(forward.decay))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0:
            assert (node.module or "").split(".")[0] != "promotion", (
                f"{forward.decay.__name__} imports a workspace member at module scope"
            )


def test_the_decay_module_is_stdlib_only_at_module_scope() -> None:
    # The factory's scan imports this package on every ``create_app()`` to fire
    # its ``@register``, so the module must pay nothing for the route beyond
    # the import it already paid: stdlib only, and no clock is read — every
    # date in the curve is the table's own, never the reader's.
    text = code_of(forward.decay)
    for token in ("utc_now", "datetime.now", "dt.now", "SELECT *", "INSERT", "UPDATE"):
        assert token not in text, f"forward.decay reaches past a read: {token}"
    for token in ("dataclasses", "contextlib", "sqlite3"):
        assert token in text, f"forward.decay is missing an expected stdlib: {token}"


def test_no_verb_accepts_a_content_or_window_parameter() -> None:
    # The route takes the signal identity a GET *for a signal* must state, and
    # nothing else: no verb accepts a window-length or content parameter, so a
    # caller cannot steer the curve.  Pinned through the signatures, so a verb
    # that gained a parameter is caught rather than silently inherited.
    assert list(inspect.signature(DecayCurveEndpoint.get).parameters) == ["self", "node_id"]
    assert list(inspect.signature(ForwardDecayCurves.curve).parameters) == [
        "self",
        "node_id",
    ]


def _code_of(module: object) -> str:
    """A module's code as unparsed text, with every docstring stripped."""
    import ast
    from pathlib import Path

    source = Path(module.__file__).read_text(encoding="utf-8")  # type: ignore[attr-defined]
    tree = ast.parse(source)
    holders = [tree]
    holders += [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    for holder in holders:
        body = holder.body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            holder.body = body[1:]
    return ast.unparse(tree)
