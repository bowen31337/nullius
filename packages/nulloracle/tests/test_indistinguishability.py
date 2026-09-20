"""Feature 114: identical shape, identical timing — branches no caller can tell apart.

app_spec.xml, "Null Oracle & Planted Nulls", feature 114: *System returns
responses whose shape and timing are identical for null and real nodes, so a
caller cannot distinguish the two branches.*  docs/nullius-tech-architecture.md
§7.2 states the promise the feature completes — *"The caller cannot
distinguish the two branches from the response"* — and this suite reads
"the response" the way an adversary does: as everything the caller can
observe about the call, not only the bytes that come back.  A response has a
value, a shape, a call sequence and a duration, and the bit leaks through
whichever of the four varies.

Features 112 and 113 kept the promise over the first two: one record, one
shape, no field that names the branch, the one crossing bit carried as §8's
opaque directive (``test_target.py`` and ``test_target_payload.py`` hold
those halves).  Feature 114 owns the last two, and both reduce to one
discipline on the route: **both branches' series are computed and checked
before the bit selects which to serve** — the permutation is run, and its
support validated, on a real node exactly as on a null one, and the bit's
only office is to pick between two values that already exist.  A route that
permuted only when the bit said so would do strictly more work for a null
node — panel-sized work, spent on one branch alone — and the asymmetry is
readable two ways: by a deployment whose seams notice which of them fired
(the call sequence), and by any caller holding a stopwatch (the duration).

Three sections pin the three observables:

* **the same work** — the permute seam is called once, with the entry's own
  stored parameters, on *both* branches; every collaborator the route
  touches fires in the same order the same number of times whichever branch
  serves; and the permuted series' validation refuses both branches alike,
  where the pre-114 route checked it only where the branch needed it — the
  one ordering this feature exists to forbid, because an exception raised on
  the null branch alone is the bit, caught instead of timed;
* **one shape** — every projection of an answer that is not a value (the
  type, the status, the field names, the payload's grid of dates and symbol
  names) is the same projection for both branches, and erasing the values
  from the two answers erases the difference: the directive remains the one
  sanctioned crossing, §8's requirement and not a leak this feature may
  close;
* **the clock** — measured, not asserted: two nodes, one route, interleaved
  requests, best-of-N compared within a bound the calibrated pre-114 route
  exceeds (it measured ~1.08x on this panel — the permutation spent on the
  null branch alone — where the parity route measures 1.00x, the same
  operations on the same data).
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import time
import uuid
from typing import Any

import pytest
from nulloracle import (
    OK,
    NullAssignment,
    NullSidecar,
    TargetEndpoint,
    TargetPayloadError,
    TargetRequest,
    TargetResponse,
    block_indices,
)

# -- The world under test --------------------------------------------------------


#: The real forward returns pipeline step 4 aligned: a panel, two symbols on
#: five dates, in the shape every sibling suite uses so the assertions below
#: are about *which branch* and never about the fixture.
DAYS = tuple(dt.date(2026, 1, 5) + dt.timedelta(days=i) for i in range(5))

SERIES: dict[dt.date, dict[str, float]] = {
    day: {"BTCUSDT": 0.01 * (index + 1), "ETHUSDT": -0.02 * (index + 1)}
    for index, day in enumerate(DAYS)
}


def _request(node_id: str, **overrides: Any) -> TargetRequest:
    """§7.2's ask for one node, with any term overridden."""
    terms: dict[str, Any] = {
        "node_id": node_id,
        "campaign_id": str(uuid.uuid4()),
        "depth": 2,
        "horizon": 5,
        "symbols": ["ETHUSDT", "BTCUSDT"],
        "date_range": (dt.date(2026, 1, 1), dt.date(2026, 2, 20)),
    }
    terms.update(overrides)
    return TargetRequest(**terms)


def _targets(request: Any) -> dict:
    """The real series — pipeline step 4's supply, as a stand-in."""
    return {day: dict(row) for day, row in SERIES.items()}


def _permute(series: Any, *, seed: Any, block_days: Any) -> dict:
    """Feature 115's mechanism at the panel's grain — days are the blocks.

    The same stand-in the sibling suites use, so the parity assertions below
    are about the *route's* behaviour and not about one suite's mechanism.
    """
    days = list(series)
    rows = [series[day] for day in days]
    order = block_indices(range(len(days)), seed=seed, block_days=block_days)
    return {
        days[position]: dict(rows[order[position]])
        for position in range(len(days))
    }


def _written(
    sidecar: NullSidecar,
    node_id: str,
    *,
    is_null: bool,
    perm_seed: int = 7,
    block_days: int = 2,
) -> NullAssignment:
    """Seal one node's entry and hand back what was sealed."""
    entry = NullAssignment(
        node_id=node_id,
        is_null=is_null,
        perm_seed=perm_seed,
        block_days=block_days,
    )
    sidecar.write([entry])
    return entry


class _TracedSidecar:
    """A sidecar that records each read the route spends on it.

    The endpoint duck-checks its sidecar by the ``assignment`` seam, so a
    wrapper over the real one composes exactly as the sealed file does — and
    every lookup the route performs becomes a line in the trace.  A route
    that read the file twice on one branch (a cache warm on the real arm, a
    fresh read on the null one) would show here as a count that varies with
    the bit.
    """

    def __init__(self, sidecar: NullSidecar, events: list[Any]) -> None:
        self._sidecar = sidecar
        self._events = events

    def assignment(self, node_id: Any) -> Any:
        self._events.append("sidecar")
        return self._sidecar.assignment(node_id)


#: Sentinel for "compose no ``past_flip`` seam at all" — distinct from
#: ``None``, which a caller might want to answer for every ask.  A trace taken
#: without the seam is the Type-R regime's trace (the sidecar's own bit
#: deciding); a trace taken with one is the Type-D regime's, and the two must
#: not be conflated by an accident of defaulting.
_NO_FLIP_SEAM = object()


def _traced_endpoint(
    sidecar: NullSidecar,
    events: list[Any],
    *,
    past_flip_answers: Any = _NO_FLIP_SEAM,
) -> TargetEndpoint:
    """An endpoint whose every collaborator records into one event list.

    The events are what the *deployment* observes about a request — which
    seams fired, in what order, with what permutation parameters — and the
    deployment is a caller like any other: a seam that fires on one branch
    and not the other is a distinguishability the agent can hire.  The
    ``permute`` event carries the entry's stored ``(seed, block_days)`` so
    trace equality also pins *with what parameters* the mechanism ran.
    """
    answers = {} if past_flip_answers is _NO_FLIP_SEAM else past_flip_answers

    def targets(request: Any) -> dict:
        events.append("targets")
        return _targets(request)

    def permute(series: Any, *, seed: Any, block_days: Any) -> dict:
        events.append(("permute", seed, block_days))
        return _permute(series, seed=seed, block_days=block_days)

    def past_flip(request: Any) -> Any:
        events.append("past_flip")
        return answers.get(getattr(request, "node_id", None))

    seam: Any = None if past_flip_answers is _NO_FLIP_SEAM else past_flip
    return TargetEndpoint(
        _TracedSidecar(sidecar, events),
        targets=targets,
        permute=permute,
        past_flip=seam,
    )


# -- The same work ---------------------------------------------------------------


class TestBothBranchesSpendTheSameWork:
    def test_the_permutation_is_computed_for_both_branches(
        self, test_sidecar: NullSidecar, node_ids
    ) -> None:
        # The discipline in one assertion.  The null branch's payload is the
        # real series through the stored permutation, so a route that ran
        # the mechanism only where the branch needed it would spend
        # panel-sized work on the null node alone — and the deployment that
        # supplied the seam could read the bit off whether its callable
        # fired.  Both nodes below are sealed with the same stored
        # parameters and asked the same question, and the mechanism runs
        # once for each, with the entries' own parameters and nothing the
        # route invented.
        null_node, real_node = node_ids(2)
        calls: list[tuple[Any, Any]] = []

        def recording(series: Any, *, seed: Any, block_days: Any) -> dict:
            calls.append((seed, block_days))
            return _permute(series, seed=seed, block_days=block_days)

        test_sidecar.write(
            [
                NullAssignment(
                    node_id=null_node, is_null=True, perm_seed=31, block_days=2
                ),
                NullAssignment(
                    node_id=real_node, is_null=False, perm_seed=31, block_days=2
                ),
            ]
        )
        endpoint = TargetEndpoint(
            test_sidecar, targets=_targets, permute=recording
        )
        endpoint.post(_request(null_node))
        assert calls == [(31, 2)]
        endpoint.post(_request(real_node))
        # The real node pays for a permutation it discards — deliberate,
        # because the alternative is a branch the caller can time.
        assert calls == [(31, 2), (31, 2)]

    def test_the_two_call_sequences_are_one_sequence(
        self, test_sidecar: NullSidecar, node_ids
    ) -> None:
        # The whole observable call sequence, not only the mechanism: the
        # sidecar is read once, the series seam is asked once, the
        # permutation runs once with the stored parameters, in the same
        # order whichever branch serves.  The Type-R world below — no
        # ``past_flip`` seam, the sidecar's own bit deciding — is the
        # regime the sealed file speaks for.
        null_node, real_node = node_ids(2)
        test_sidecar.write(
            [
                NullAssignment(
                    node_id=null_node, is_null=True, perm_seed=5, block_days=2
                ),
                NullAssignment(
                    node_id=real_node, is_null=False, perm_seed=5, block_days=2
                ),
            ]
        )
        events: list[Any] = []
        endpoint = _traced_endpoint(test_sidecar, events)

        events.clear()
        endpoint.post(_request(null_node))
        null_trace = list(events)
        events.clear()
        endpoint.post(_request(real_node))
        real_trace = list(events)

        expected = ["sidecar", "targets", ("permute", 5, 2)]
        assert null_trace == expected
        assert real_trace == expected

    def test_the_type_d_resolution_spends_the_same_work(
        self, test_sidecar: NullSidecar, node_ids
    ) -> None:
        # The same statement through §7.2's other regime: a Type-D
        # campaign's branch is a fact of depths resolved by the ``past_flip``
        # seam, and the entries below are sealed with the *opposite* bits to
        # the ones the seam answers — so the seam is exercised as the thing
        # that decides, and the trace still shows one sequence.  A flip
        # resolution that consulted the store only when it was about to
        # serve a permuted series would fire the seam on the null node
        # alone, and the store is a caller that could count.
        null_node, real_node = node_ids(2)
        test_sidecar.write(
            [
                NullAssignment(
                    node_id=null_node, is_null=False, perm_seed=9, block_days=2
                ),
                NullAssignment(
                    node_id=real_node, is_null=True, perm_seed=9, block_days=2
                ),
            ]
        )
        events: list[Any] = []
        endpoint = _traced_endpoint(
            test_sidecar,
            events,
            past_flip_answers={null_node: True, real_node: False},
        )

        events.clear()
        null_answer = endpoint.post(_request(null_node))
        null_trace = list(events)
        events.clear()
        real_answer = endpoint.post(_request(real_node))
        real_trace = list(events)

        # The seam really decided — the answers sit on the branches the
        # depths chose and not the bits the entries carry, so this test is
        # about the flip's parity and not the sidecar's.
        assert null_answer.charges_budget is False
        assert real_answer.charges_budget is True
        expected = ["sidecar", "past_flip", "targets", ("permute", 9, 2)]
        assert null_trace == expected
        assert real_trace == expected

    @pytest.mark.parametrize("is_null", [True, False])
    def test_a_permutation_that_breaks_the_support_refuses_both_branches(
        self, test_sidecar: NullSidecar, node_id: str, is_null: bool
    ) -> None:
        # The validation half of the same discipline.  The permuted series'
        # date-preservation check is work, and under the pre-114 ordering it
        # ran only where the branch needed it — so a broken mechanism
        # refused the null node and *answered* the real one, and the
        # exception was the bit, caught instead of timed.  Since the
        # permutation is computed and checked whichever branch serves, a
        # mechanism that drops a date refuses both branches alike.
        _written(test_sidecar, node_id, is_null=is_null, perm_seed=3)
        endpoint = TargetEndpoint(
            test_sidecar,
            targets=_targets,
            permute=lambda series, *, seed, block_days: {
                day: dict(row) for day, row in list(series.items())[:-1]
            },
        )
        with pytest.raises(TargetPayloadError, match="day blocks"):
            endpoint.post(_request(node_id))

    def test_the_missing_mechanism_still_refuses_both_branches_alike(
        self, test_sidecar: NullSidecar, node_ids
    ) -> None:
        # The refusal the discipline predicted, restated as the caller's
        # classifier: a route with no ``permute`` answers neither branch,
        # and an answer of "refused for the null node, 200 for the real
        # one" is exactly the reading of the bit this feature forbids.
        # (Feature 113's suite pinned this refusal first; it is repeated
        # here because the *reason* changed — what was once fairness is now
        # one instance of the same-work rule.)
        null_node, real_node = node_ids(2)
        test_sidecar.write(
            [
                NullAssignment(node_id=null_node, is_null=True, perm_seed=4),
                NullAssignment(node_id=real_node, is_null=False, perm_seed=4),
            ]
        )
        endpoint = TargetEndpoint(test_sidecar, targets=_targets, permute=None)
        outcomes = []
        for node in (null_node, real_node):
            try:
                outcomes.append(endpoint.post(_request(node)).status)
            except TargetPayloadError:
                outcomes.append("refused")
        assert outcomes[0] == outcomes[1] != OK


# -- One shape -------------------------------------------------------------------


def _shape_of(response: TargetResponse) -> tuple[Any, ...]:
    """Every property of an answer that is not a value.

    The type, the status, the detail, the field names, the slot set, the
    payload's grid — which dates, which symbols on each — and the
    directive's *type*: everything a caller can read that is not a float and
    not the directive's truth.  Two answers of one shape project to one
    tuple, whichever branch produced them.
    """
    series = response.target_series or {}
    return (
        type(response).__name__,
        response.status,
        response.detail,
        tuple(field.name for field in dataclasses.fields(type(response))),
        tuple(getattr(response, "__slots__", ())),
        tuple(sorted(series)),
        tuple(
            (day, tuple(sorted(row))) for day, row in sorted(series.items())
        ),
        type(response.charges_budget).__name__,
    )


def _values_erased(response: TargetResponse) -> tuple[Any, ...]:
    """The answer with every branch-dependent value erased.

    The same projection with the floats and the directive's truth gone: if
    erasing the values erases the difference, then the difference *is* the
    values — and §7.2 lets the values differ (the series is the point of
    the route) while §8 requires the directive to (the budget is a debit).
    """
    series = response.target_series or {}
    return (
        response.status,
        response.detail,
        tuple((day, tuple(sorted(row))) for day, row in sorted(series.items())),
    )


class TestTheAnswersShareOneShape:
    def test_every_projection_a_caller_can_read_is_one_shape(
        self, test_sidecar: NullSidecar, node_ids
    ) -> None:
        # Feature 114's shape half, stated over the caller's whole view: the
        # two answers for two nodes of one world carry the same type, the
        # same status, the same fields, the same payload grid — the same
        # everything a caller could count, name or serialise.  A route whose
        # null answer carried an extra field, a different status vocabulary
        # or a reshaped grid would be a route that varied by branch without
        # saying so.
        null_node, real_node = node_ids(2)
        test_sidecar.write(
            [
                NullAssignment(
                    node_id=null_node, is_null=True, perm_seed=3, block_days=2
                ),
                NullAssignment(
                    node_id=real_node, is_null=False, perm_seed=3, block_days=2
                ),
            ]
        )
        endpoint = TargetEndpoint(
            test_sidecar, targets=_targets, permute=_permute
        )
        null_answer = endpoint.post(_request(null_node))
        real_answer = endpoint.post(_request(real_node))
        # The two answers differ in their values (the null one is the
        # permuted series) so the shape equality below is between two
        # genuinely different payloads, not one payload served twice.
        assert null_answer.target_series != real_answer.target_series
        assert _shape_of(null_answer) == _shape_of(real_answer)

    def test_erasing_the_values_erases_the_difference(
        self, test_sidecar: NullSidecar, node_ids
    ) -> None:
        # The same claim from the other side, and the guard that keeps it
        # honest: the two answers genuinely differ — the null node is served
        # a permutation and the real node the series, the one behavioural
        # difference §7.2 exists to produce — so this test cannot pass on a
        # route that ignored the bit and served one world to both.  Erase
        # the floats and the two answers are equal; the directive remains as
        # the one sanctioned crossing (§8 requires it to be exactly the
        # fact it is, and features 113's and 114's docstrings state why
        # neither may blur it).
        null_node, real_node = node_ids(2)
        # ``perm_seed=3, block_days=2`` on the five-date panel is the pair the
        # sibling suite proved moves the rows, so the guard below is a real
        # guard and not a coin that happened to land identity.  (Spelled
        # explicitly rather than left to the record's default ``block_days``:
        # the default is 20, and a panel shorter than its blocks has one
        # block and nothing to move.)
        test_sidecar.write(
            [
                NullAssignment(
                    node_id=null_node, is_null=True, perm_seed=3, block_days=2
                ),
                NullAssignment(
                    node_id=real_node, is_null=False, perm_seed=3, block_days=2
                ),
            ]
        )
        endpoint = TargetEndpoint(
            test_sidecar, targets=_targets, permute=_permute
        )
        null_answer = endpoint.post(_request(null_node))
        real_answer = endpoint.post(_request(real_node))

        # The branches differ where §7.2 says they must...
        assert null_answer.target_series != real_answer.target_series
        assert null_answer.charges_budget is False
        assert real_answer.charges_budget is True
        # ...and nowhere else: erase the values and the difference is gone.
        assert _values_erased(null_answer) == _values_erased(real_answer)
        assert _shape_of(null_answer) == _shape_of(real_answer)


# -- The clock -------------------------------------------------------------------


#: The timing panel's size: large enough that the permutation is a
#: measurable fraction of a request (on the calibrated host, ~8% of a
#: ~2.8 ms post) and small enough that a whole measurement — warm-up, 60
#: interleaved rounds over both branches — stays well under a second.
TIMING_DAYS = 240
TIMING_SYMBOLS = 40

#: How many interleaved rounds each branch is timed over.  The branches do
#: literally the same operations on the same data, so their best-case costs
#: agree to a fraction of a percent; taking the best of many rounds is the
#: low-noise estimator for the cost of fixed work, since scheduler noise
#: only ever adds time.
TIMING_ROUNDS = 60

#: The bound the two branches' best-case costs may not exceed, as a ratio.
#: Calibrated on this suite's panel: the parity route measures 1.00x (the
#: same operations either way), and the pre-114 route — which permuted only
#: on the null branch — measured 1.08x-1.09x across repeated runs.  A bound
#: of 1.04 sits between the two with headroom on both sides: it would fail
#: the route that spends the permutation on one branch alone, and it holds
#: the route that spends it on both with an order of magnitude to spare.
TIMING_TOLERANCE = 1.04


def _timing_panel() -> dict[dt.date, dict[str, float]]:
    """A panel large enough to time: ``TIMING_DAYS`` bars of a full cross-section.

    The values are a deterministic arithmetic hash — the route never reads
    them (the checks are on names and dates), so any finite values serve,
    and these are reproducible from the constants alone.
    """
    names = [f"S{index:03d}" for index in range(TIMING_SYMBOLS)]
    return {
        dt.date(2025, 1, 1) + dt.timedelta(days=offset): {
            name: ((offset * 31 + position * 17) % 97 - 48) / 1000.0
            for position, name in enumerate(names)
        }
        for offset in range(TIMING_DAYS)
    }


class TestTheClockCannotSeparateTheBranches:
    def test_the_two_branches_take_the_same_time(
        self, test_sidecar: NullSidecar, node_ids
    ) -> None:
        # Feature 114's timing half, measured.  Two nodes of one world —
        # one null, one real, sealed with the same stored parameters — are
        # asked the same question over the same route, the requests
        # interleaved so drift on a loaded host lands on both branches
        # alike, and the best of each branch's rounds is compared within
        # :data:`TIMING_TOLERANCE`.  Under the parity route the two branches
        # execute the same operations in the same order — sidecar read,
        # series seam, permutation, validation, answer — so the clocks agree
        # because the work is the same, not because a pad was tuned to make
        # it look that way; a caller timing the route learns nothing about
        # the bit it could not learn from the response, which is the whole
        # of §7.2's promise.
        null_node, real_node = node_ids(2)
        test_sidecar.write(
            [
                NullAssignment(
                    node_id=null_node,
                    is_null=True,
                    perm_seed=7,
                    block_days=20,
                ),
                NullAssignment(
                    node_id=real_node,
                    is_null=False,
                    perm_seed=7,
                    block_days=20,
                ),
            ]
        )
        panel = _timing_panel()
        names = sorted(next(iter(panel.values())))
        requests = {
            node: TargetRequest(
                node_id=node,
                campaign_id=str(uuid.uuid4()),
                depth=2,
                horizon=5,
                symbols=names,
                date_range=(min(panel), max(panel)),
            )
            for node in (null_node, real_node)
        }
        endpoint = TargetEndpoint(
            test_sidecar,
            targets=lambda request: {
                day: dict(row) for day, row in panel.items()
            },
            permute=_permute,
        )

        # Warm-up: first-touch imports, file cache and allocator state are
        # not the route's work, and letting them land inside the measurement
        # would time the test's own housekeeping.
        for request in requests.values():
            assert endpoint.post(request).status == OK

        times: dict[str, list[float]] = {null_node: [], real_node: []}
        for _ in range(TIMING_ROUNDS):
            for node, request in requests.items():
                start = time.perf_counter()
                endpoint.post(request)
                times[node].append(time.perf_counter() - start)

        null_best = min(times[null_node])
        real_best = min(times[real_node])
        slower = max(null_best, real_best)
        faster = min(null_best, real_best)
        assert slower <= TIMING_TOLERANCE * faster, (
            f"the two branches' best-of-{TIMING_ROUNDS} costs differ by "
            f"{slower / faster:.3f}x on a {TIMING_DAYS}x{TIMING_SYMBOLS} "
            f"panel (null {null_best * 1000:.2f} ms, real "
            f"{real_best * 1000:.2f} ms); a route whose branches differ in "
            "time is a route whose caller can read §7.2's bit off the "
            "clock — the permutation must be spent on both branches, not "
            "only on the one that serves it"
        )
