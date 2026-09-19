"""Feature 76 — the null gate, the only place the oracle supplies a target.

app_spec.xml feature 76: *"System rejects a target substitution anywhere
outside the null_gate step, which is the only place the oracle supplies a
target series."* docs/nullius-tech-architecture.md §6.1 names the step —
``5. null_gate ── ask null oracle for the target series ── §7`` — and adds
*"Step 5 is the only place the null substitution happens."*

This suite tests the gate's two signs separately — the ask and the
rejection — because the feature sentence is two claims: the oracle is
asked (exactly once per covered horizon, through an injected seam), and a
target series that did not come out of that ask is refused wherever it
turns up. The tests assert:

* **the ask** — the gate asks once per *covered* horizon (an empty horizon
  has nothing to ask), the request carries §7.2's own terms (the node
  identity the caller supplied, the horizon, the cross-section, the span),
  and the bundle that comes back carries one series per horizon plus the
  budget directive, opaquely;
* **the branch is indistinguishable, by design** — an oracle answering
  with the aligned values passes, and so does one answering with permuted
  values on the same support: the gate never compares values, because a
  gate that did would be the client-side null detector principle P2
  forbids. The substitution *inside* the gate is the method; the tests
  prove the gate does not accidentally detect it;
* **the ask's refusals** — an answer that is not a response, an answer
  beyond or short of the aligned support, a symbol nobody scored or a
  scored symbol gone missing, directives that disagree across horizons,
  and a malformed ask (identity, depth, oracle, nothing to ask);
* **the rejection** — :func:`check_targets_gated` certifies the gate's own
  answer and refuses a bundle from another sealed world, another grid, or
  with support the alignment does not back — the substitutions that
  arrived by a door other than the gate — while certifying a value-shuffled
  bundle on the exact aligned support, because the check certifies the
  channel, not the branch;
* **the records** — the §7.2 request and response field contracts, the
  bundle's coherence, the verdict's summary, hashability, and read-only
  capture.

The alignment is built by the real step-4 path (:func:`align_targets` over
a hand-built execution), and the oracle is a stub — the seam is injected,
so these tests ask and answer without a socket, a sidecar, or a key.
"""

from __future__ import annotations

import datetime as dt
import math
from types import MappingProxyType

import pytest

from evaluator import (
    AlignedTargets,
    EvaluatorGateError,
    GateCheck,
    GatedTargets,
    HORIZONS,
    NULL_GATE_STEP,
    OracleRequest,
    OracleResponse,
    RawScoreVector,
    SignalExecution,
    TargetSeries,
    align_targets,
    check_targets_gated,
    gate_targets,
)

_START = dt.date(2026, 9, 1)


def _days(count: int, start: dt.date = _START) -> tuple[dt.date, ...]:
    """``count`` consecutive calendar dates — a synthetic bar grid."""
    return tuple(start + dt.timedelta(days=i) for i in range(count))


def _execution(
    dates,
    universe: tuple[str, ...] = ("AAA", "BBB"),
    *,
    snapshot_name: str = "snap_abc123",
) -> SignalExecution:
    """A hand-built execution — feature 73's output — for step 4 to align."""
    vectors = {
        day: RawScoreVector(
            rebalance_date=day,
            decision_time=dt.datetime.combine(
                day, dt.time(tzinfo=dt.timezone.utc)
            ),
            universe=universe,
            seed=7,
            contract_version="0.1.0",
            problems=[],
        )
        for day in dates
    }
    return SignalExecution(
        snapshot_name=snapshot_name,
        code_hash="ab" * 32,
        seed=7,
        vectors=vectors,
    )


def _closes(
    by_symbol: dict[str, list[float]], days: tuple[dt.date, ...]
) -> dict[str, dict[dt.date, float]]:
    """A fetched closes mapping — one close per symbol per grid day."""
    return {symbol: dict(zip(days, prices)) for symbol, prices in by_symbol.items()}


# The main scenario, in test_align.py's shape: a 12-bar grid, three
# rebalance dates at its head, BBB flat at 50 — and AAA compounding a
# *distinct* rate each bar (1% then half a point more per bar), so the
# forward-return rows differ across rebalance dates.  The distinction is
# load-bearing for this suite: a value-shuffled answer can only be told
# apart from the aligned one where the aligned values differ by date, and
# the permuted-branch tests below turn on exactly that.  Horizons 1, 2 and
# 5 cover all three rebalance dates, horizon 10 covers the first two,
# horizon 20 covers none — the empty-but-carried case the gate must ask
# nothing for.
_GRID = _days(12)
_REBALANCE = _GRID[:3]
_DAILY = [1.0 + 0.01 + 0.005 * i for i in range(11)]
_COMPOUND = [100.0]
for _rate in _DAILY:
    _COMPOUND.append(_COMPOUND[-1] * _rate)
_MAIN_EXECUTION = _execution(_REBALANCE)
_MAIN_CLOSES = _closes({"AAA": _COMPOUND, "BBB": [50.0] * 12}, _GRID)
_MAIN = align_targets(_MAIN_EXECUTION, _MAIN_CLOSES)

#: The horizons the main scenario's oracle will be asked — and not asked.
_ASKED = (1, 2, 5, 10)


def _identity() -> dict[str, object]:
    """The node identity the gate is asked under — one spelling of it."""
    return {"node_id": "node_1", "campaign_id": "camp_1", "depth": 2}


def _oracle(
    alignment: AlignedTargets,
    *,
    charges_budget: bool = False,
    directive_by_horizon: dict[int, bool] | None = None,
    rewrite=None,
):
    """A stub oracle whose real branch is the identity.

    Answers each request with the alignment's own values for that horizon
    — the §7.2 real branch — optionally ``rewrite``-en (the permuted
    branch, in which values move and the support does not), and with the
    directive the test configures (one bit, constant or per horizon).
    Records every request it was asked, so a test can assert on the ask
    itself.  An oracle that answers ISO-spelled keys is built with
    ``rewrite`` spelling them; see the wire-spelling test.
    """
    calls: list[OracleRequest] = []

    def ask(request: OracleRequest) -> OracleResponse:
        calls.append(request)
        aligned = alignment.targets(request.horizon)
        values = {day: dict(aligned.at(day)) for day in aligned.dates()}
        if rewrite is not None:
            values = rewrite(request.horizon, values)
        directive = (
            charges_budget
            if directive_by_horizon is None
            else directive_by_horizon[request.horizon]
        )
        return OracleResponse(
            target_series=values, charges_budget=directive
        )

    return ask, calls


def _hand_bundle(
    alignment: AlignedTargets,
    *,
    series_mutate=None,
    snapshot_name: str | None = None,
    rebalance_dates: tuple[dt.date, ...] | None = None,
    charges_budget: bool = False,
) -> GatedTargets:
    """A bundle built by hand — what did not come through the gate looks like.

    Built over the alignment's own support (optionally per-horizon
    ``series_mutate``-d), so its shape is coherent and any refusal it
    earns is a refusal of its *supply*, not of its fields.
    """
    series: dict[int, TargetSeries] = {}
    for horizon in HORIZONS:
        aligned = alignment.targets(horizon)
        values = {day: dict(aligned.at(day)) for day in aligned.dates()}
        if series_mutate is not None:
            values = series_mutate(horizon, values)
        series[horizon] = TargetSeries(
            horizon=horizon,
            snapshot_name=aligned.snapshot_name,
            values=values,
        )
    return GatedTargets(
        snapshot_name=snapshot_name or alignment.snapshot_name,
        rebalance_dates=rebalance_dates or alignment.rebalance_dates,
        series=series,
        charges_budget=charges_budget,
    )


# -- the ask --------------------------------------------------------------------


def test_the_gate_asks_once_per_covered_horizon() -> None:
    # The gate is the only ask in the package, and it asks once per horizon
    # the alignment covers — 1, 2, 5 and 10 here. Horizon 20 has nothing
    # aligned over a 12-bar grid, so there is nothing to ask, and asking a
    # service for an empty range would be noise dressed as protocol.
    oracle, calls = _oracle(_MAIN)
    gated = gate_targets(_MAIN, oracle, **_identity())
    assert isinstance(gated, GatedTargets)
    assert tuple(call.horizon for call in calls) == _ASKED


def test_the_request_carries_the_seventy_two_terms() -> None:
    # §7.2's request is {node_id, campaign_id, depth, horizon, symbols[],
    # date_range}. The identity terms are the caller's, echoed unchanged;
    # the data terms are the alignment's own — the cross-section that
    # horizon's dates score, and the span of those dates, so the answer is
    # asked for exactly the support it must live on.
    oracle, calls = _oracle(_MAIN)
    gate_targets(_MAIN, oracle, **_identity())
    first, last = calls[0], calls[-1]
    assert (first.node_id, first.campaign_id, first.depth) == (
        "node_1",
        "camp_1",
        2,
    )
    assert first.horizon == 1
    assert first.symbols == ("AAA", "BBB")
    assert first.date_range == (_REBALANCE[0], _REBALANCE[2])
    # Horizon 10 covers only the first two rebalance dates — the span the
    # gate asks on is that horizon's own, not the whole grid's.
    assert last.horizon == 10
    assert last.date_range == (_REBALANCE[0], _REBALANCE[1])


def test_the_bundle_carries_one_series_per_horizon() -> None:
    # Feature 75's shape promise, kept by the answer: five TargetSeries,
    # one per horizon, including the empty horizon 20 — a consumer
    # iterating the five horizons of a decay profile must find five on the
    # gated side too. The bundle stamps the alignment's own provenance and
    # grid, because one gate reads one sealed world over one scored grid.
    oracle, _ = _oracle(_MAIN)
    gated = gate_targets(_MAIN, oracle, **_identity())
    assert gated.snapshot_name == "snap_abc123"
    assert gated.rebalance_dates == _REBALANCE
    assert gated.horizons == HORIZONS
    assert gated.targets(20).dates() == ()
    for horizon in _ASKED:
        assert gated.targets(horizon).snapshot_name == "snap_abc123"
        assert gated.targets(horizon).horizon == horizon


def test_the_real_branch_is_the_aligned_series() -> None:
    # The identity oracle answers with the alignment's own values — §7.2's
    # real branch — so the gated bundle carries the aligned targets
    # exactly: same dates, same symbols, same values, per horizon.
    oracle, _ = _oracle(_MAIN)
    gated = gate_targets(_MAIN, oracle, **_identity())
    for horizon in _ASKED:
        supplied, aligned = gated.targets(horizon), _MAIN.targets(horizon)
        assert supplied.dates() == aligned.dates()
        for day in aligned.dates():
            assert supplied.at(day) == aligned.at(day)


def test_a_permuted_branch_passes_through_untouched() -> None:
    # The gate holds both the aligned series and the oracle's answer, and
    # the one thing it must never do is compare them: a value mismatch is
    # the null branch, and detecting it client-side would be the P2 leak
    # that silently voids every calibration number. So a permuted answer —
    # rows moved across dates, the support untouched, which is the shape
    # of §7.2's block permutation — passes without complaint, and the
    # bundle carries the oracle's values, not the aligned ones.
    def _permute(horizon: int, values: dict[dt.date, dict[str, float]]):
        days = sorted(values)
        return {day: values[mirror] for day, mirror in zip(days, reversed(days))}

    oracle, _ = _oracle(_MAIN, rewrite=_permute)
    gated = gate_targets(_MAIN, oracle, **_identity())
    first_day = _MAIN.targets(1).dates()[0]
    last_day = _MAIN.targets(1).dates()[-1]
    assert gated.targets(1).at(first_day) == _MAIN.targets(1).at(last_day)
    assert gated.targets(1).at(first_day) != _MAIN.targets(1).at(first_day)


def test_the_directive_crosses_opaquely() -> None:
    # charges_budget is the one bit §7.2 lets cross the barrier, and it
    # crosses as a directive, never a label: the bundle carries it through
    # exactly as every answer spelled it, and the gate adds nothing —
    # interpreting it is feature 84's job, not step 5's.
    for directive in (False, True):
        oracle, _ = _oracle(_MAIN, charges_budget=directive)
        gated = gate_targets(_MAIN, oracle, **_identity())
        assert gated.charges_budget is directive


def test_the_wire_spelling_of_an_answer_is_normalized() -> None:
    # §7.2 is a service boundary and ISO strings are the wire spelling of
    # a date; an answer keyed by them is the same answer, normalized to
    # calendar dates on capture — one canonical spelling inside the gate,
    # the courtesy _window._as_utc extends the decision time.
    def _iso(horizon: int, values: dict[dt.date, dict[str, float]]):
        return {
            day.isoformat(): row for day, row in values.items()
        }

    oracle, _ = _oracle(_MAIN, rewrite=_iso)
    gated = gate_targets(_MAIN, oracle, **_identity())
    assert gated.targets(1).dates() == _MAIN.targets(1).dates()


# -- the ask's refusals ---------------------------------------------------------


def test_an_alignment_that_is_not_one_is_refused() -> None:
    # The gate gates step 4's own result — the terms the oracle is asked
    # on — and a mapping that is not one, however target-shaped, has no
    # support to ask on.
    oracle, _ = _oracle(_MAIN)
    with pytest.raises(EvaluatorGateError, match="AlignedTargets"):
        gate_targets({"snapshot_name": "snap_abc123"}, oracle, **_identity())  # type: ignore[arg-type]


def test_a_non_callable_oracle_is_refused() -> None:
    # The oracle is §7.2's seam, injected — never reached for — and a
    # service URL or response payload left in its place is not a callable
    # seam the gate can ask through.
    with pytest.raises(EvaluatorGateError, match="injected"):
        gate_targets(_MAIN, "https://z0/null/target", **_identity())  # type: ignore[arg-type]


def test_the_node_identity_is_validated() -> None:
    # The request's identity terms find the node in the sidecar's schema
    # and resolve a Type-D flip; an identity that is not a name or a depth
    # that is not a count would make the answer unattributable, so each is
    # refused by name — a bool included, because ``True`` is a depth of
    # one to nobody.
    oracle, _ = _oracle(_MAIN)
    for bad in ({"node_id": "", "campaign_id": "c", "depth": 1},
                {"node_id": "n", "campaign_id": "  ", "depth": 1},
                {"node_id": "n", "campaign_id": "c", "depth": True},
                {"node_id": "n", "campaign_id": "c", "depth": -1},
                {"node_id": "n", "campaign_id": "c", "depth": 1.0}):
        with pytest.raises(EvaluatorGateError):
            gate_targets(_MAIN, oracle, **bad)  # type: ignore[arg-type]


def test_an_alignment_with_nothing_to_ask_is_refused() -> None:
    # An alignment with no computable target at any horizon leaves the
    # gate nothing to ask — the §7.2 exchange never happens, so there is
    # no evaluation to gate and no directive to carry.
    empty = AlignedTargets(
        snapshot_name="snap_abc123",
        rebalance_dates=(),
        series=MappingProxyType(
            {
                horizon: TargetSeries(
                    horizon=horizon,
                    snapshot_name="snap_abc123",
                    values=MappingProxyType({}),
                )
                for horizon in HORIZONS
            }
        ),
    )
    oracle, calls = _oracle(empty)
    with pytest.raises(EvaluatorGateError, match="nothing to ask"):
        gate_targets(empty, oracle, **_identity())
    assert calls == []


def test_an_answer_that_is_not_a_response_is_refused() -> None:
    # The seam's payload is validated at the record; anything else — the
    # raw JSON a client returned, a bare mapping — is not an answer, and
    # the gate says so by name rather than probing at its keys.
    def _raw(request: OracleRequest):
        return {"target_series": {}, "charges_budget": False}

    with pytest.raises(EvaluatorGateError, match="OracleResponse"):
        gate_targets(_MAIN, _raw, **_identity())


def test_an_answer_beyond_the_support_is_refused() -> None:
    # §7.2's branches preserve the aligned support exactly, so an answer
    # covering a date the alignment does not is not an answer either
    # branch could have produced — it arrived by another path, and a label
    # on a bar nobody scored is a label for nobody.
    def _extra(horizon: int, values: dict[dt.date, dict[str, float]]):
        values = dict(values)
        values[_GRID[5]] = {"AAA": 0.01, "BBB": 0.0}
        return values

    oracle, _ = _oracle(_MAIN, rewrite=_extra)
    with pytest.raises(EvaluatorGateError, match="no scored grid names"):
        gate_targets(_MAIN, oracle, **_identity())


def test_an_answer_missing_a_date_is_refused() -> None:
    # The mirror refusal: a shrunk answer would shrink what every
    # downstream metric measures — the dressed-up emptiness feature 75's
    # coverage refusal exists to reject, arriving one horizon later.
    def _short(horizon: int, values: dict[dt.date, dict[str, float]]):
        return {day: row for day, row in values.items() if day != _REBALANCE[2]}

    oracle, _ = _oracle(_MAIN, rewrite=_short)
    with pytest.raises(EvaluatorGateError, match="the alignment covers"):
        gate_targets(_MAIN, oracle, **_identity())


def test_a_symbol_nobody_scored_is_refused() -> None:
    # The oracle answers for the cross-section it was asked for, no wider:
    # a CCC target on a scored date is a label for a symbol nobody scored,
    # and carrying it would let a substituted series widen the measured
    # cross-section behind the metrics' back.
    def _wider(horizon: int, values: dict[dt.date, dict[str, float]]):
        return {
            day: {**row, "CCC": 0.0} for day, row in values.items()
        }

    oracle, _ = _oracle(_MAIN, rewrite=_wider)
    with pytest.raises(EvaluatorGateError, match="whom nobody scored"):
        gate_targets(_MAIN, oracle, **_identity())


def test_a_scored_symbol_gone_missing_is_refused() -> None:
    # And no narrower: dropping BBB from the answers would silently
    # halve the cross-section every downstream metric measures.
    def _narrower(horizon: int, values: dict[dt.date, dict[str, float]]):
        return {
            day: {symbol: value for symbol, value in row.items() if symbol != "BBB"}
            for day, row in values.items()
        }

    oracle, _ = _oracle(_MAIN, rewrite=_narrower)
    with pytest.raises(EvaluatorGateError, match="missing BBB"):
        gate_targets(_MAIN, oracle, **_identity())


def test_disagreeing_directives_are_refused() -> None:
    # One evaluation asks one debit question, and §7.2's directive is the
    # one bit that crosses the barrier; an oracle answering it differently
    # per horizon is speaking for two evaluations, and neither answer can
    # be trusted to be the evaluation's.
    oracle, _ = _oracle(_MAIN, directive_by_horizon={1: True, 2: False, 5: True, 10: True})
    with pytest.raises(EvaluatorGateError, match="disagreed"):
        gate_targets(_MAIN, oracle, **_identity())


# -- the rejection — substitutions outside the gate ------------------------------


def test_the_check_certifies_the_gates_own_answer() -> None:
    # The consumer's half of the feature: a bundle the gate minted is
    # certified against the very alignment it was gated over, and the
    # verdict summarizes the binding — the provenance, the grid, the
    # per-horizon coverage (the alignment's own, horizon 10's two dates
    # and horizon 20's none included), and the directive.
    oracle, _ = _oracle(_MAIN, charges_budget=True)
    gated = gate_targets(_MAIN, oracle, **_identity())
    check = check_targets_gated(gated, _MAIN)
    assert check.snapshot_name == "snap_abc123"
    assert check.rebalance_dates == _REBALANCE
    assert check.charges_budget is True
    assert check.coverage[1] == _REBALANCE
    assert check.coverage[10] == _REBALANCE[:2]
    assert check.coverage[20] == ()


def test_a_bundle_from_another_sealed_world_is_refused() -> None:
    # A bundle is bound to the sealed world it gated: one alignment reads
    # one snapshot, so an answer gated over snap_abc123 cannot be the
    # gate's answer over snap_other — a replayed answer is a substitution
    # outside the null_gate step, refused however well-formed it is.
    other = align_targets(
        _execution(_REBALANCE, snapshot_name="snap_other"), _MAIN_CLOSES
    )
    oracle, _ = _oracle(_MAIN)
    gated = gate_targets(_MAIN, oracle, **_identity())
    with pytest.raises(EvaluatorGateError, match="snap_other"):
        check_targets_gated(gated, other)


def test_a_bundle_over_another_grid_is_refused() -> None:
    # Same sealed world, different scored grid: the gate answers on the
    # grid it was asked on, so a bundle carrying three rebalance dates
    # cannot be the gate's answer over an evaluation that scored two —
    # whatever evaluation produced it, it was not this one.
    shorter = align_targets(
        _execution(_REBALANCE[:2]), _MAIN_CLOSES
    )
    oracle, _ = _oracle(_MAIN)
    gated = gate_targets(_MAIN, oracle, **_identity())
    with pytest.raises(EvaluatorGateError, match="another grid"):
        check_targets_gated(gated, shorter)


def test_a_hand_built_bundle_beyond_the_support_is_refused() -> None:
    # The feature's own refusal, exercised: a bundle whose horizon-1
    # series covers a date the alignment does not cannot have come through
    # the gate — the gate refuses that answer at the ask — so finding one
    # downstream proves it was substituted in after the fact.
    def _extra(horizon: int, values: dict[dt.date, dict[str, float]]):
        if horizon != 1:
            return values
        values = dict(values)
        values[_GRID[5]] = {"AAA": 0.01, "BBB": 0.0}
        return values

    bundle = _hand_bundle(_MAIN, series_mutate=_extra)
    with pytest.raises(EvaluatorGateError, match="substitution"):
        check_targets_gated(bundle, _MAIN)


def test_a_hand_built_bundle_missing_support_is_refused() -> None:
    # A hole in the supply is the same substitution in the other
    # direction: the metrics would measure fewer dates than were scored,
    # and no branch of §7.2's oracle produces that.
    def _short(horizon: int, values: dict[dt.date, dict[str, float]]):
        if horizon != 2:
            return values
        return {day: row for day, row in values.items() if day != _REBALANCE[1]}

    bundle = _hand_bundle(_MAIN, series_mutate=_short)
    with pytest.raises(EvaluatorGateError, match="substitution"):
        check_targets_gated(bundle, _MAIN)


def test_a_substituted_symbol_is_refused() -> None:
    # The support rule is per date *and* per symbol: a bundle answering
    # for CCC on a scored date — or dropping BBB from one — is a
    # substituted cross-section, refused at the check exactly as the same
    # answer would have been refused at the ask.
    def _wider(horizon: int, values: dict[dt.date, dict[str, float]]):
        if horizon != 1:
            return values
        return {day: {**row, "CCC": 0.0} for day, row in values.items()}

    bundle = _hand_bundle(_MAIN, series_mutate=_wider)
    with pytest.raises(EvaluatorGateError, match="substitution"):
        check_targets_gated(bundle, _MAIN)


def test_the_check_never_compares_values() -> None:
    # The companion the refusals need to stay honest: a bundle on the
    # exact aligned support whose *values* were shuffled is
    # indistinguishable from the oracle's own answer — that is §7.2's
    # design, the method's own property — so the check certifies it.  The
    # check certifies the channel, not the branch; anything less would be
    # the client-side null detector P2 forbids.
    def _shuffle(horizon: int, values: dict[dt.date, dict[str, float]]):
        days = sorted(values)
        return {day: values[mirror] for day, mirror in zip(days, reversed(days))}

    bundle = _hand_bundle(_MAIN, series_mutate=_shuffle, charges_budget=True)
    check = check_targets_gated(bundle, _MAIN)
    assert bundle.targets(1).at(_REBALANCE[0]) != _MAIN.targets(1).at(
        _REBALANCE[0]
    )
    assert check.coverage[1] == _MAIN.targets(1).dates()


def test_the_check_refuses_what_is_not_a_bundle() -> None:
    # The check certifies the null gate's own answer; an alignment handed
    # back in its place — the value the caller already holds — is what was
    # gated, not what the gate returned, and the refusal says exactly
    # that rather than probing at shared fields.
    with pytest.raises(EvaluatorGateError, match="what the gate returned"):
        check_targets_gated(_MAIN, _MAIN)
    with pytest.raises(EvaluatorGateError, match="AlignedTargets"):
        check_targets_gated(_MAIN, {"series": {}})  # type: ignore[arg-type]


def test_the_step_is_named_in_the_refusals() -> None:
    # The feature names the one step a substitution is allowed at, and the
    # refusals name it too — one spelling, the §6.1 one, so a reader of a
    # log or a failure can find the door the series did not come through.
    assert NULL_GATE_STEP == "null_gate"
    def _extra(horizon: int, values: dict[dt.date, dict[str, float]]):
        values = dict(values)
        values[_GRID[5]] = {"AAA": 0.01, "BBB": 0.0}
        return values

    oracle, _ = _oracle(_MAIN, rewrite=_extra)
    with pytest.raises(EvaluatorGateError, match="null_gate"):
        gate_targets(_MAIN, oracle, **_identity())


# -- the records ----------------------------------------------------------------


def test_the_response_honours_its_field_contract() -> None:
    # The response is the wire value, validated at the record: the
    # directive must be the bool the barrier lets cross (an int that
    # happens to be 0 or 1 is not a bit), every target a finite number (a
    # NaN label would reach the metrics dressed as a measurement), and
    # every key a date or an ISO string — a datetime names an instant, and
    # guessing its candle is a guess.
    with pytest.raises(EvaluatorGateError, match="charges_budget must be a bool"):
        OracleResponse(target_series={}, charges_budget=1)  # type: ignore[arg-type]
    with pytest.raises(EvaluatorGateError, match="not finite"):
        OracleResponse(
            target_series={_REBALANCE[0]: {"AAA": math.nan}},
            charges_budget=False,
        )
    with pytest.raises(EvaluatorGateError, match="must be a number"):
        OracleResponse(
            target_series={_REBALANCE[0]: {"AAA": True}},  # type: ignore[dict-item]
            charges_budget=False,
        )
    with pytest.raises(EvaluatorGateError, match="datetime"):
        OracleResponse(
            target_series={
                dt.datetime.combine(_REBALANCE[0], dt.time()): {"AAA": 0.0}  # type: ignore[dict-item]
            },
            charges_budget=False,
        )
    with pytest.raises(EvaluatorGateError, match="ISO date"):
        OracleResponse(target_series={"Sept 1": {"AAA": 0.0}}, charges_budget=False)
    with pytest.raises(EvaluatorGateError, match="twice"):
        OracleResponse(
            target_series={
                _REBALANCE[0]: {"AAA": 0.0},
                _REBALANCE[0].isoformat(): {"AAA": 0.0},
            },
            charges_budget=False,
        )
    with pytest.raises(EvaluatorGateError, match="non-empty strings"):
        OracleResponse(
            target_series={_REBALANCE[0]: {"": 0.0}}, charges_budget=False
        )


def test_the_request_honours_its_field_contract() -> None:
    # The ask is the experiment's own header: closed horizon set, one
    # spelling of the cross-section, a span that runs first-to-last —
    # each refused by name so a malformed ask cannot leave the gate.
    good = {
        "node_id": "n",
        "campaign_id": "c",
        "depth": 0,
        "horizon": 1,
        "symbols": ("AAA", "BBB"),
        "date_range": (_REBALANCE[0], _REBALANCE[2]),
    }
    OracleRequest(**good)
    with pytest.raises(EvaluatorGateError, match="horizons the spec names"):
        OracleRequest(**{**good, "horizon": 3})
    with pytest.raises(EvaluatorGateError, match="cross-section to ask for"):
        OracleRequest(**{**good, "symbols": ()})
    with pytest.raises(EvaluatorGateError, match="sorted and de-duplicated"):
        OracleRequest(**{**good, "symbols": ("BBB", "AAA")})
    with pytest.raises(EvaluatorGateError, match="pair of calendar dates"):
        OracleRequest(**{**good, "date_range": (_REBALANCE[0],)})
    with pytest.raises(EvaluatorGateError, match="first-to-last"):
        OracleRequest(**{**good, "date_range": (_REBALANCE[2], _REBALANCE[0])})
    with pytest.raises(EvaluatorGateError, match="non-empty strings"):
        OracleRequest(**{**good, "symbols": ("AAA", "")})


def test_the_bundle_honours_its_field_contract() -> None:
    # The bundle mirrors the alignment's coherence — the closed horizon
    # set, series filed under their own horizon, one snapshot, a sorted
    # grid — plus the directive's own contract, because this record is
    # the alignment's counterpart downstream.
    series = MappingProxyType(
        {
            horizon: TargetSeries(
                horizon=horizon,
                snapshot_name="snap_abc123",
                values=MappingProxyType(dict(_MAIN.targets(horizon).values)),
            )
            for horizon in HORIZONS
        }
    )
    GatedTargets(
        snapshot_name="snap_abc123",
        rebalance_dates=_REBALANCE,
        series=series,
        charges_budget=False,
    )
    with pytest.raises(EvaluatorGateError, match="one series per horizon"):
        GatedTargets(
            snapshot_name="snap_abc123",
            rebalance_dates=_REBALANCE,
            series=MappingProxyType({h: series[h] for h in HORIZONS[:4]}),
            charges_budget=False,
        )
    with pytest.raises(EvaluatorGateError, match="filed under the wrong horizon"):
        GatedTargets(
            snapshot_name="snap_abc123",
            rebalance_dates=_REBALANCE,
            series=MappingProxyType({**series, 1: series[2]}),
            charges_budget=False,
        )
    with pytest.raises(EvaluatorGateError, match="one gate reads one sealed world"):
        GatedTargets(
            snapshot_name="snap_other",
            rebalance_dates=_REBALANCE,
            series=series,
            charges_budget=False,
        )
    with pytest.raises(EvaluatorGateError, match="sorted and de-duplicated"):
        GatedTargets(
            snapshot_name="snap_abc123",
            rebalance_dates=(_REBALANCE[1], _REBALANCE[0], _REBALANCE[2]),
            series=series,
            charges_budget=False,
        )
    with pytest.raises(EvaluatorGateError, match="charges_budget must be a bool"):
        GatedTargets(
            snapshot_name="snap_abc123",
            rebalance_dates=_REBALANCE,
            series=series,
            charges_budget=0,  # type: ignore[arg-type]
        )


def test_the_bundle_and_response_are_hashable_values() -> None:
    # A bundle is a value: two gates of the same alignment over the same
    # answers are interchangeable as dict keys, and so are two equal
    # responses — filed beside a report or compared across checks without
    # recomputing.
    oracle_a, _ = _oracle(_MAIN)
    oracle_b, _ = _oracle(_MAIN)
    a = gate_targets(_MAIN, oracle_a, **_identity())
    b = gate_targets(_MAIN, oracle_b, **_identity())
    assert a == b
    assert hash(a) == hash(b)
    assert {a, b} == {a}
    first = OracleResponse(
        target_series={_REBALANCE[0]: {"AAA": 0.01}}, charges_budget=False
    )
    second = OracleResponse(
        target_series={_REBALANCE[0].isoformat(): {"AAA": 0.01}},
        charges_budget=False,
    )
    assert first == second
    assert hash(first) == hash(second)


def test_the_verdict_honours_its_field_contract() -> None:
    # The verdict is the certified binding summarized: one coverage entry
    # per horizon the spec names, dates sorted and de-duplicated, the
    # directive a bool — so a hand-built verdict cannot describe a binding
    # the check itself would have refused.
    good = GateCheck(
        snapshot_name="snap_abc123",
        rebalance_dates=_REBALANCE,
        coverage=MappingProxyType({h: _MAIN.targets(h).dates() for h in HORIZONS}),
        charges_budget=False,
    )
    assert good.coverage[20] == ()
    with pytest.raises(EvaluatorGateError, match="per horizon the spec names"):
        GateCheck(
            snapshot_name="snap_abc123",
            rebalance_dates=_REBALANCE,
            coverage=MappingProxyType({1: _REBALANCE}),
            charges_budget=False,
        )
    with pytest.raises(EvaluatorGateError, match="sorted and de-duplicated"):
        GateCheck(
            snapshot_name="snap_abc123",
            rebalance_dates=_REBALANCE,
            coverage=MappingProxyType(
                {h: (_REBALANCE[1], _REBALANCE[0]) for h in HORIZONS}
            ),
            charges_budget=False,
        )
    with pytest.raises(EvaluatorGateError, match="charges_budget must be a bool"):
        GateCheck(
            snapshot_name="snap_abc123",
            rebalance_dates=_REBALANCE,
            coverage=MappingProxyType({h: () for h in HORIZONS}),
            charges_budget="no",  # type: ignore[arg-type]
        )


def test_the_verdict_is_a_hashable_value() -> None:
    # Certifying the same bundle twice yields interchangeable verdicts,
    # and a hand-built one built from the same terms is the same value.
    oracle, _ = _oracle(_MAIN)
    gated = gate_targets(_MAIN, oracle, **_identity())
    a = check_targets_gated(gated, _MAIN)
    b = check_targets_gated(gated, _MAIN)
    assert a == b
    assert hash(a) == hash(b)
    assert {a, b} == {a}


def test_the_records_capture_their_mappings_read_only() -> None:
    # A caller keeping the dict it passed cannot add a target, a date or a
    # horizon to a live record — the bundle, the response and the verdict
    # capture their mappings behind read-only proxies, the same discipline
    # the execution and the alignment hold.
    row = {_REBALANCE[0]: {"AAA": 0.01, "BBB": 0.0}}
    response = OracleResponse(target_series=row, charges_budget=False)
    row[_REBALANCE[1]] = {"AAA": 0.99}
    assert _REBALANCE[1] not in response.target_series
    series = {
        horizon: TargetSeries(
            horizon=horizon,
            snapshot_name="snap_abc123",
            values=values,
        )
        for horizon, values in (
            (1, dict(_MAIN.targets(1).values)),
            (2, MappingProxyType({})),
            (5, MappingProxyType({})),
            (10, MappingProxyType({})),
            (20, MappingProxyType({})),
        )
    }
    bundle = GatedTargets(
        snapshot_name="snap_abc123",
        rebalance_dates=_REBALANCE,
        series=series,
        charges_budget=False,
    )
    series[3] = series[1]  # type: ignore[index]
    assert 3 not in bundle.series
