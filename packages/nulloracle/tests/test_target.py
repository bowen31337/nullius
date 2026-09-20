"""Feature 112: POST /target — the ask, and the answer's status line.

app_spec.xml, "Null Oracle & Planted Nulls", feature 112: *System exposes
POST /target accepting node_id, campaign_id, depth, horizon, symbols and a
date range, which returns 200 for a known node.*  docs/nullius-tech-
architecture.md §7.2 spells the interface this suite pins::

    POST /target
      request:  { node_id, campaign_id, depth, horizon, symbols[], date_range }
      response: { target_series, charges_budget }   # is_null NEVER appears

This suite owns feature 112's two halves — the ask and the answer's
*status* — and deliberately not the payload, which is feature 113's and is
pinned in ``test_target_payload.py``:

* **the ask** — :class:`nulloracle.target.TargetRequest`, §7.2's six terms
  as one frozen value: canonicalised (UUID identities, one sorted spelling
  of the cross-section, calendar dates), and refused by name term by term,
  before the sidecar is ever opened;
* **the answer's status** — :class:`nulloracle.target.TargetEndpoint` over
  §7.1's sidecar: ``200`` for a node the sidecar holds, ``404`` for one it
  does not, and — the distinction the whole taxonomy rests on — a missing
  or unopenable sidecar is neither, because "unknown node" is a fact about
  the world and "broken deployment" is not.

Two properties get their own sections because they are the ones a
plausible-looking implementation gets wrong:

* **a real node is as known as a null one** — feature 118's selection
  seals both, and a route whose 200 varied by ``is_null`` would be
  feature 114's indistinguishability promise broken on the day the route
  was born;
* **nothing on the answer names the branch** — the response carries a
  status and a payload and never the bit, because §7.2's comment line
  (``# is_null NEVER appears``) is a property of the whole response.

Where feature 113 landed, this suite's endpoint tests supply the series
seam the payload needs — through :func:`_endpoint`, which every test here
constructs its route with, so the *status* assertions stay assertions about
the status rather than about the supply.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import uuid
from types import MappingProxyType
from typing import Any

import pytest
from nulloracle import (
    HORIZONS,
    NOT_FOUND,
    OK,
    TARGET_ROUTE,
    NullAssignment,
    NullSidecar,
    SidecarDecryptionError,
    SidecarStoreError,
    TargetEndpoint,
    TargetRequest,
    TargetResponse,
    TargetRouteError,
    block_indices,
)

# -- Helpers ---------------------------------------------------------------------


#: The series feature 113's tests serve, and the only one this file needs: the
#: subjects below are the request, the status and the branch's *shape*, none of
#: which depend on what the labels are worth.  Two symbols on two dates, so a
#: payload is a panel and not a point.
SERIES: MappingProxyType | dict = {
    dt.date(2026, 1, 5): {"BTCUSDT": 0.01, "ETHUSDT": -0.02},
    dt.date(2026, 1, 6): {"BTCUSDT": 0.03, "ETHUSDT": 0.04},
}


def _targets(request: Any) -> dict:
    """A ``targets`` seam answering the request's own cross-section.

    Feature 112's tests construct endpoints to ask about *statuses*, and a
    route that cannot serve a payload cannot answer 200 at all — so every
    endpoint here is built through :func:`_endpoint`, which supplies the real
    series and feature 115's permutation.  The stub answers for the symbols
    the request named, at the two dates of :data:`SERIES`, so the payload is
    never the reason a status assertion fails.
    """
    return {day: dict(row) for day, row in SERIES.items()}


def _permute(series: Any, *, seed: Any, block_days: Any) -> dict:
    """Feature 115's mechanism at the panel's grain — days are the blocks.

    The same reconciliation the composed route's own closure makes: a
    ``forward_returns`` series' blocks become runs of consecutive *dates*,
    each date's whole cross-section travelling with it.  The dates are the
    axis and stay put; the rows move across them, because a mapping holds no
    order and a gather that kept each row under its own date would rebuild
    the identical series.
    """
    days = list(series)
    rows = [series[day] for day in days]
    order = block_indices(range(len(days)), seed=seed, block_days=block_days)
    return {
        days[position]: dict(rows[order[position]])
        for position in range(len(days))
    }


def _endpoint(sidecar: NullSidecar, **overrides: Any) -> TargetEndpoint:
    """The endpoint under test, with the seams feature 113 needs supplied.

    Feature 112's suite answers *did the route know this node*, and that
    question is only reachable through a route that can build an answer:
    feature 113 requires a series and, on the permuted branch, a mechanism.
    Both are supplied here once so the tests below override exactly the seam
    each one is about.
    """
    seams: dict[str, Any] = {"targets": _targets, "permute": _permute}
    seams.update(overrides)
    return TargetEndpoint(sidecar, **seams)


def _request(node_id: Any, **overrides: Any) -> TargetRequest:
    """§7.2's request for one node, with any term overridden.

    The defaults are one well-formed ask — a campaign, a mid-tree depth,
    the middle horizon, a two-symbol cross-section, a January span — so a
    test overrides exactly the term it is pinning and the reader sees
    which one.
    """
    terms: dict[str, Any] = {
        "node_id": node_id,
        "campaign_id": str(uuid.uuid4()),
        "depth": 2,
        "horizon": 5,
        "symbols": ["BTCUSDT", "ETHUSDT"],
        "date_range": (dt.date(2026, 1, 5), dt.date(2026, 2, 20)),
    }
    terms.update(overrides)
    return TargetRequest(**terms)


class _Ask:
    """A duck-typed ask — anything carrying the node the route reads.

    The composed endpoint and a directly-imported request are the same
    source under two module names, so ``post`` reads its request
    duck-typed; this stand-in pins that a caller who never built a
    :class:`TargetRequest` still gets a named refusal for a malformed
    identity rather than an ``AttributeError``.
    """

    def __init__(self, node_id: Any) -> None:
        self.node_id = node_id


# -- The route, spelled once -------------------------------------------------------


class TestTheRouteIsSpelledOnce:
    def test_the_route_is_the_specs_path(self) -> None:
        # The API summary's row — ``POST /target — Return a target series
        # plus an opaque budget directive`` — pinned as one spelling.
        assert TARGET_ROUTE == "/target"
        assert TargetEndpoint.route == TARGET_ROUTE

    def test_the_horizons_are_the_five_the_spec_aligns(self) -> None:
        # Feature 74's closed set, restated server-side: the route answers
        # per horizon, and a horizon nothing measures is a question no
        # evaluation asks.
        assert HORIZONS == (1, 2, 5, 10, 20)


# -- The ask -----------------------------------------------------------------------


class TestTheAskCanonicalisesItsTerms:
    def test_two_spellings_of_one_ask_are_one_request(self) -> None:
        # The request is a value two callers must be able to compare: the
        # identities however the caller came by them, the cross-section in
        # whatever order it was enumerated, the dates as dates or as their
        # ISO wire spelling.
        identity = uuid.uuid4()
        campaign = uuid.uuid4()
        first = _request(
            str(identity),
            campaign_id=str(campaign),
            symbols=["ETHUSDT", "BTCUSDT", "ETHUSDT"],
            date_range=("2026-01-05", "2026-02-20"),
        )
        second = _request(
            str(identity).upper(),
            campaign_id=campaign,
            symbols=("BTCUSDT", "ETHUSDT"),
            date_range=(dt.date(2026, 1, 5), dt.date(2026, 2, 20)),
        )
        assert first == second
        assert hash(first) == hash(second)
        assert first.node_id == str(identity)
        assert first.symbols == ("BTCUSDT", "ETHUSDT")
        assert first.date_range == (dt.date(2026, 1, 5), dt.date(2026, 2, 20))

    def test_a_request_is_frozen(self) -> None:
        request = _request(str(uuid.uuid4()))
        with pytest.raises(dataclasses.FrozenInstanceError):
            request.depth = 3  # type: ignore[misc]


class TestTheAskRefusesMalformedTerms:
    @pytest.mark.parametrize("identity", ["", "not-a-uuid", 123, None])
    def test_an_identity_that_is_not_a_uuid_is_refused(
        self, identity: Any
    ) -> None:
        with pytest.raises(TargetRouteError, match="node_id"):
            _request(identity)
        with pytest.raises(TargetRouteError, match="campaign_id"):
            _request(str(uuid.uuid4()), campaign_id=identity)

    @pytest.mark.parametrize("depth", [-1, "3", 1.5, True, None])
    def test_a_depth_that_is_not_a_count_is_refused(self, depth: Any) -> None:
        with pytest.raises(TargetRouteError, match="depth"):
            _request(str(uuid.uuid4()), depth=depth)

    @pytest.mark.parametrize("horizon", [0, 3, 21, True, "1", None])
    def test_a_horizon_outside_the_five_is_refused(
        self, horizon: Any
    ) -> None:
        with pytest.raises(TargetRouteError, match="horizon"):
            _request(str(uuid.uuid4()), horizon=horizon)

    @pytest.mark.parametrize("horizon", HORIZONS)
    def test_every_horizon_the_spec_aligns_is_accepted(
        self, horizon: int
    ) -> None:
        assert _request(str(uuid.uuid4()), horizon=horizon).horizon == horizon

    @pytest.mark.parametrize(
        "symbols", [(), "BTCUSDT", ["", "ETHUSDT"], ["BTCUSDT", 7], None]
    )
    def test_a_cross_section_that_is_not_a_list_of_names_is_refused(
        self, symbols: Any
    ) -> None:
        with pytest.raises(TargetRouteError, match="symbols"):
            _request(str(uuid.uuid4()), symbols=symbols)

    def test_a_bare_string_is_refused_rather_than_iterated(self) -> None:
        # ``"BTCUSDT"`` is a sequence of seven characters and a
        # cross-section of zero tickers; the refusal names the type.
        with pytest.raises(TargetRouteError, match="symbols"):
            _request(str(uuid.uuid4()), symbols="BTCUSDT")

    def test_a_datetime_is_refused_as_a_range_endpoint(self) -> None:
        with pytest.raises(TargetRouteError, match="date_range"):
            _request(
                str(uuid.uuid4()),
                date_range=(
                    dt.datetime(2026, 1, 5, 9, 30, tzinfo=dt.UTC),
                    dt.date(2026, 2, 20),
                ),
            )

    def test_a_reversed_range_is_refused(self) -> None:
        with pytest.raises(TargetRouteError, match="first-to-last"):
            _request(
                str(uuid.uuid4()),
                date_range=(dt.date(2026, 2, 20), dt.date(2026, 1, 5)),
            )

    @pytest.mark.parametrize("date_range", [(), ("2026-01-05",), None, "2026-01-05"])
    def test_a_range_that_is_not_a_pair_is_refused(
        self, date_range: Any
    ) -> None:
        with pytest.raises(TargetRouteError, match="date_range"):
            _request(str(uuid.uuid4()), date_range=date_range)

    def test_a_non_iso_string_is_refused_as_a_date(self) -> None:
        with pytest.raises(TargetRouteError, match="ISO date"):
            _request(
                str(uuid.uuid4()),
                date_range=("January 5th", "2026-02-20"),
            )


# -- The answer's status line ------------------------------------------------------


class TestTheResponseHoldsItsOwnContract:
    def test_a_known_node_answers_200_and_is_known(self) -> None:
        node = str(uuid.uuid4())
        response = TargetResponse(
            status=OK,
            node_id=node,
            target_series=SERIES,
            charges_budget=True,
        )
        assert response.status == 200
        assert response.known is True
        assert response.detail is None

    def test_an_unknown_node_answers_404_and_is_not_known(self) -> None:
        node = str(uuid.uuid4())
        response = TargetResponse(
            status=NOT_FOUND, node_id=node, detail="no such node"
        )
        assert response.status == 404
        assert response.known is False

    def test_a_status_outside_the_two_is_refused(self) -> None:
        node = str(uuid.uuid4())
        for status in (500, "200", 200.0, True, None):
            with pytest.raises(TargetRouteError, match="status"):
                TargetResponse(status=status, node_id=node)

    def test_a_malformed_node_on_a_response_is_refused(self) -> None:
        with pytest.raises(TargetRouteError, match="node_id"):
            TargetResponse(status=OK, node_id="not-a-uuid")

    def test_an_ok_answer_carries_no_detail(self) -> None:
        # An answer that explained itself would be an answer that varies
        # by node — the exact variation feature 114 forbids.
        with pytest.raises(TargetRouteError, match="detail"):
            TargetResponse(
                status=OK, node_id=str(uuid.uuid4()), detail="known"
            )


class TestTheEndpointAnswersForTheSidecarItHolds:
    def test_a_known_node_answers_200(self, test_sidecar: NullSidecar, node_id: str) -> None:
        # The feature's own clause, pinned whole: a node the sidecar holds
        # an entry for gets the 200.
        test_sidecar.write(
            [NullAssignment(node_id=node_id, is_null=True, perm_seed=11)]
        )
        response = _endpoint(test_sidecar).post(_request(node_id))
        assert response.status == 200
        assert response.known is True
        assert response.node_id == node_id

    def test_a_real_node_is_as_known_as_a_null_one(
        self, test_sidecar: NullSidecar, node_ids
    ) -> None:
        # Feature 118's selection seals null roots and real roots alike,
        # and the 200 must not vary by the bit the entry carries: the two
        # answers below differ only in whose they are.
        null_node, real_node = node_ids(2)
        test_sidecar.write(
            [
                NullAssignment(node_id=null_node, is_null=True, perm_seed=3),
                NullAssignment(node_id=real_node, is_null=False, perm_seed=0),
            ]
        )
        endpoint = _endpoint(test_sidecar)
        null_answer = endpoint.post(_request(null_node))
        real_answer = endpoint.post(_request(real_node))
        assert null_answer.status == real_answer.status == 200
        assert null_answer.known is real_answer.known is True

    def test_nothing_on_the_answer_names_the_branch(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # §7.2's comment line — ``# is_null NEVER appears`` — is a property
        # of the whole response, so it holds on the day the route is born,
        # before feature 113 adds the payload.
        test_sidecar.write(
            [NullAssignment(node_id=node_id, is_null=True, perm_seed=11)]
        )
        response = _endpoint(test_sidecar).post(_request(node_id))
        for public in (response, type(response)):
            assert not hasattr(public, "is_null")
        assert "is_null" not in repr(response)

    def test_an_unknown_node_answers_404(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # A written sidecar that holds other nodes: the ask names a node
        # no sidecar holds, and that is an answer, not an error.
        other = str(uuid.uuid4())
        test_sidecar.write(
            [NullAssignment(node_id=other, is_null=True, perm_seed=1)]
        )
        response = TargetEndpoint(test_sidecar).post(_request(node_id))
        assert response.status == 404
        assert response.known is False
        assert node_id in (response.detail or "")

    def test_a_missing_sidecar_is_not_an_unknown_node(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # A configured sidecar that was never written is a deployment
        # failure, and reading it as a 404 would say "no such node" about
        # a world the route never saw.
        with pytest.raises(SidecarStoreError):
            TargetEndpoint(test_sidecar).post(_request(node_id))

    def test_an_unopenable_sidecar_is_not_an_unknown_node(
        self,
        test_sidecar: NullSidecar,
        sidecar_path,
        other_key,
        node_id: str,
    ) -> None:
        test_sidecar.write(
            [NullAssignment(node_id=node_id, is_null=True, perm_seed=11)]
        )
        wrong_key_endpoint = TargetEndpoint(
            NullSidecar(sidecar_path, other_key)
        )
        with pytest.raises(SidecarDecryptionError):
            wrong_key_endpoint.post(_request(node_id))

    def test_the_endpoint_duck_checks_its_sidecar(self) -> None:
        with pytest.raises(TypeError, match="assignment"):
            TargetEndpoint(object())  # type: ignore[arg-type]

    def test_a_post_revalidates_the_identity_it_reads(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # Duck-typed on purpose (the composed endpoint and a direct import
        # are two module names for one source), so the identity the route
        # reads is validated by value — a malformed one refused by name.
        test_sidecar.write(
            [NullAssignment(node_id=node_id, is_null=False, perm_seed=0)]
        )
        endpoint = _endpoint(test_sidecar)
        with pytest.raises(TargetRouteError, match="node_id"):
            endpoint.post(_Ask("not-a-uuid"))  # type: ignore[arg-type]
        assert endpoint.post(_Ask(node_id)).status == 200  # type: ignore[arg-type]


class TestTheEndpointComposesFromTheEnvironment:
    def test_an_unconfigured_deployment_composes_no_endpoint(self) -> None:
        # The autouse fixtures clear every variable this member reads, so
        # the default state of a test is the state of a deployment before
        # anyone configured it — which composes nothing, quietly.
        assert TargetEndpoint.from_env() is None

    def test_a_configured_deployment_composes_the_endpoint(
        self, sidecar_path, key_ref: str, node_id: str
    ) -> None:
        endpoint = TargetEndpoint.from_env(
            targets=_targets, permute=_permute
        )
        assert endpoint is not None
        assert endpoint.sidecar.path == sidecar_path

        # And the composed endpoint answers from the same file: written
        # through the resolved sidecar, asked through the route.
        endpoint.sidecar.write(
            [NullAssignment(node_id=node_id, is_null=True, perm_seed=11)]
        )
        assert endpoint.post(_request(node_id)).status == 200
        assert endpoint.post(_request(str(uuid.uuid4()))).status == 404
