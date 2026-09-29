"""Feature 314: passive by default, aggressive only when the decay
outruns the fill.

app_spec.xml, "Order Routing & Venue Filters", feature 314: *System posts
orders passively by default, which sends an aggressive order only when
signal decay horizon is shorter than expected fill time.*
``docs/nullius-tech-architecture.md`` §13.2 states the same rule as one
line of the execution engine's contract — *"Post-only by default;
aggressive only when the signal's decay horizon is shorter than the
expected fill time."* — and ``docs/alpha-engine-prd.md`` C9 repeats it
with the comparison itself: *"Post-only by default; taker only when
signal decay horizon < expected fill time."*

The tests below are organised around the two halves of that sentence,
because each can be false while the other is true:

* **posts orders passively by default** — an edge that outlives the
  queue posts, an edge exactly as long as the queue posts (the
  comparison is strict), and there is no way to ask for the other
  posture: the verb admits no posture argument, so the default is
  structural rather than a preference a caller could override;
* **sends an aggressive order only when signal decay horizon is
  shorter than expected fill time** — a decay that outruns the fill
  crosses, and *only* that does: not a hint, not a flag, and not a
  stated posture the terms do not compel, which is refused rather than
  recorded.

The suite also pins the shape around the sentence: the two terms are
measured durations rather than bare numbers, the vocabulary is the
system's own (``passive``/``aggressive``) and not the venue's
(``post-only``/``taker``), and the choice is pure — no clock, no I/O,
no store — so two processes derive one posture without speaking.

No test needs a database.  The decision is a pure function of the two
durations it is handed — the suite pins that too, by deleting
``DATABASE_URL`` and resolving postures anyway — so every test here
runs with no store behind it, which is the feature's own shape:
nothing to persist, nothing to compose.
"""

from __future__ import annotations

import ast
import inspect
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import router as member
from router.errors import (
    CLIENT_ORDER_ID_CODE,
    CROSS_MARGIN_CODE,
    ORDER_POSTURE_CODE,
    ORDER_SUBMISSION_UNHEALTHY_CODE,
    RATE_LIMITED_CODE,
    RETRY_BACKOFF_CODE,
    SUBMISSION_RESULT_CODE,
    RouterClientOrderIdError,
    RouterCrossMarginError,
    RouterError,
    RouterFilterError,
    RouterOrderPostureError,
    RouterRateLimitError,
    RouterStoreError,
    RouterSubmissionHealthError,
    RouterSubmissionResultError,
)
from router.posture import (
    AGGRESSIVE_ORDER,
    ORDER_POSTURES,
    PASSIVE_ORDER,
    OrderPosture,
    resolve_order_posture,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

#: A signal whose edge outlives the queue it must wait behind, and the
#: queue it is expected to wait behind: the sentence's default case, an
#: order posted on the passive side of the book.
PATIENT_HORIZON = timedelta(minutes=30)
PATIENT_FILL = timedelta(minutes=5)

#: A signal whose edge is gone before the passive fill would arrive: the
#: sentence's one exception, an order that crosses the spread.
IMPATIENT_HORIZON = timedelta(seconds=30)
IMPATIENT_FILL = timedelta(minutes=5)


# =============================================================================
# "posts orders passively by default"
# =============================================================================


class TestTheActAnswersThePosture:
    """The sentence's verb returns the decision, with its terms beside it."""

    def test_an_edge_that_outlives_the_queue_posts(self) -> None:
        posture = resolve_order_posture(
            signal_decay_horizon=PATIENT_HORIZON,
            expected_fill_time=PATIENT_FILL,
        )
        assert isinstance(posture, OrderPosture)
        assert posture.posture == PASSIVE_ORDER
        assert posture.is_aggressive is False

    def test_the_terms_ride_beside_the_verdict(self) -> None:
        # A verdict alone could not say *why* an order crossed; the value
        # carries the edge and the wait it was decided over, the same shape
        # feature 316's identity takes for the same reason.
        posture = resolve_order_posture(
            signal_decay_horizon=IMPATIENT_HORIZON,
            expected_fill_time=IMPATIENT_FILL,
        )
        assert posture.signal_decay_horizon == IMPATIENT_HORIZON
        assert posture.expected_fill_time == IMPATIENT_FILL

    def test_the_decision_is_frozen_and_hashable(self) -> None:
        import dataclasses

        posture = resolve_order_posture(
            signal_decay_horizon=PATIENT_HORIZON, expected_fill_time=PATIENT_FILL
        )
        assert dataclasses.is_dataclass(posture)
        with pytest.raises(dataclasses.FrozenInstanceError):
            posture.posture = AGGRESSIVE_ORDER  # type: ignore[misc]
        # It stands as its own key -- a caller can file decisions by value.
        assert {posture: 1}[posture] == 1

    def test_resolving_is_deterministic(self) -> None:
        first = resolve_order_posture(
            signal_decay_horizon=PATIENT_HORIZON, expected_fill_time=PATIENT_FILL
        )
        second = resolve_order_posture(
            signal_decay_horizon=PATIENT_HORIZON, expected_fill_time=PATIENT_FILL
        )
        assert first == second
        assert hash(first) == hash(second)

    def test_the_exception_has_the_one_predicate(self) -> None:
        # ``is_aggressive`` is the gate's own question -- the sentence's
        # exception.  The default has no predicate of its own: over a closed
        # vocabulary of two, a second spelling would be a second fact to
        # keep in sync, and the token itself is the positive reading.
        assert (
            resolve_order_posture(
                signal_decay_horizon=IMPATIENT_HORIZON,
                expected_fill_time=IMPATIENT_FILL,
            ).is_aggressive
            is True
        )
        assert (
            resolve_order_posture(
                signal_decay_horizon=PATIENT_HORIZON, expected_fill_time=PATIENT_FILL
            ).is_aggressive
            is False
        )
        assert not hasattr(OrderPosture, "is_passive")

    def test_the_verb_and_direct_construction_agree(self) -> None:
        assert resolve_order_posture(
            signal_decay_horizon=PATIENT_HORIZON, expected_fill_time=PATIENT_FILL
        ) == OrderPosture(PATIENT_HORIZON, PATIENT_FILL)


class TestShorterThanIsStrict:
    """C9 spells the comparison ``<``; equality keeps the default."""

    def test_an_edge_exactly_as_long_as_the_wait_posts(self) -> None:
        # At equality every unit of edge is still there when the fill lands,
        # so the sentence's *shorter than* does not fire and the default
        # stands.
        same = timedelta(minutes=5)
        posture = resolve_order_posture(
            signal_decay_horizon=same, expected_fill_time=same
        )
        assert posture.posture == PASSIVE_ORDER
        assert posture.is_aggressive is False

    def test_one_microsecond_shorter_crosses(self) -> None:
        # The boundary is the sentence's and not a float's: timedeltas are
        # exact, so the smallest margin the clock can express already
        # compels the crossing.
        posture = resolve_order_posture(
            signal_decay_horizon=PATIENT_FILL - timedelta(microseconds=1),
            expected_fill_time=PATIENT_FILL,
        )
        assert posture.posture == AGGRESSIVE_ORDER
        assert posture.is_aggressive is True

    def test_one_microsecond_longer_posts(self) -> None:
        posture = resolve_order_posture(
            signal_decay_horizon=PATIENT_FILL + timedelta(microseconds=1),
            expected_fill_time=PATIENT_FILL,
        )
        assert posture.posture == PASSIVE_ORDER

    def test_the_strictness_holds_across_magnitudes(self) -> None:
        # From microseconds to days the rule is the same rule: only the
        # ordering of the two durations decides, never their scale.
        assert (
            resolve_order_posture(
                signal_decay_horizon=timedelta(microseconds=1),
                expected_fill_time=timedelta(days=1),
            ).is_aggressive
            is True
        )
        assert (
            resolve_order_posture(
                signal_decay_horizon=timedelta(days=1),
                expected_fill_time=timedelta(microseconds=1),
            ).is_aggressive
            is False
        )


class TestTheOnlyDoorToAggressiveIsTheComparison:
    """The verb takes no posture argument; ``only when`` is structural."""

    def test_the_verb_admits_no_posture_argument(self) -> None:
        # The signature is exactly the two measured terms.  There is no
        # hint, no flag, no urgency field -- the single door to an
        # aggressive order is the comparison the function makes itself.
        signature = inspect.signature(resolve_order_posture)
        assert set(signature.parameters) == {
            "signal_decay_horizon",
            "expected_fill_time",
        }

    def test_the_terms_are_required_keywords(self) -> None:
        # A default would be this module inventing an edge's length or a
        # queue's wait -- the law feature 316's own ``rebalance_ts`` states
        # for its term one module over.
        signature = inspect.signature(resolve_order_posture)
        for name in ("signal_decay_horizon", "expected_fill_time"):
            parameter = signature.parameters[name]
            assert parameter.kind is inspect.Parameter.KEYWORD_ONLY, name
            assert parameter.default is inspect.Parameter.empty, name
        with pytest.raises(TypeError):
            resolve_order_posture(PATIENT_HORIZON, PATIENT_FILL)  # type: ignore[misc]

    def test_a_caller_cannot_ask_for_aggressive(self) -> None:
        # Terms that compel the default, offered a posture anyway: the ask
        # is not near-miss-answered -- it is not an ask this verb takes.
        with pytest.raises(TypeError):
            resolve_order_posture(
                signal_decay_horizon=PATIENT_HORIZON,
                expected_fill_time=PATIENT_FILL,
                posture=AGGRESSIVE_ORDER,  # type: ignore[misc]
            )

    def test_omitting_the_verdict_derives_it(self) -> None:
        # The value's omitted posture is the sentence's *by default* made a
        # construction fact: the terms decide, both ways, with no verdict
        # stated at all.
        assert OrderPosture(PATIENT_HORIZON, PATIENT_FILL).posture == PASSIVE_ORDER
        assert (
            OrderPosture(IMPATIENT_HORIZON, IMPATIENT_FILL).posture
            == AGGRESSIVE_ORDER
        )


class TestTheVocabularyIsClosed:
    """`passive` and `aggressive` are the two postures; nothing else is one."""

    def test_the_vocabulary_is_exactly_the_two_postures(self) -> None:
        assert ORDER_POSTURES == frozenset({"passive", "aggressive"})
        assert PASSIVE_ORDER in ORDER_POSTURES
        assert AGGRESSIVE_ORDER in ORDER_POSTURES
        assert PASSIVE_ORDER == "passive"
        assert AGGRESSIVE_ORDER == "aggressive"

    @pytest.mark.parametrize(
        "absent",
        [
            # §13.2's and C9's own spellings of the *same* postures, one
            # layer down at the venue's flags: admitting them here would be
            # two vocabularies for one fact.
            "post_only",
            "post-only",
            "postonly",
            "taker",
            "maker",
            # Misspellings a pasted token could carry.
            "Passive",
            "PASSIVE",
            "passive ",
            " passive",
            "passiv",
            "agressivo",
        ],
    )
    def test_a_near_miss_is_not_a_posture(self, absent: str) -> None:
        with pytest.raises(RouterOrderPostureError) as raised:
            OrderPosture(IMPATIENT_HORIZON, IMPATIENT_FILL, posture=absent)
        assert ORDER_POSTURE_CODE in str(raised.value)

    @pytest.mark.parametrize("bad", [None, 314, b"passive", [], {}, 1.0, True])
    def test_a_posture_that_is_not_a_token_is_refused_by_name(
        self, bad: object
    ) -> None:
        # The unhashable cases matter: ``frozenset`` membership raises
        # TypeError on ``[]``, and a caller offering a list to a vocabulary
        # of tokens deserves this member's refusal naming the value.
        with pytest.raises(RouterOrderPostureError) as raised:
            OrderPosture(IMPATIENT_HORIZON, IMPATIENT_FILL, posture=bad)
        assert str(raised.value).startswith(f"{ORDER_POSTURE_CODE}:")


class TestTheTermsAreDurations:
    """The comparison is over lengths of time; nothing else is one."""

    @pytest.mark.parametrize(
        "bad",
        [30, 30.0, "30m", None, True, [30], {"minutes": 30}],
    )
    def test_a_bare_number_states_no_unit_for_the_horizon(
        self, bad: object
    ) -> None:
        # Thirty seconds and thirty minutes compel different postures over
        # the same queue; a number without a unit is refused rather than
        # read in whatever unit this module would have had to pick.
        with pytest.raises(RouterOrderPostureError) as raised:
            resolve_order_posture(
                signal_decay_horizon=bad, expected_fill_time=PATIENT_FILL
            )
        assert str(raised.value).startswith(f"{ORDER_POSTURE_CODE}:")
        assert "signal_decay_horizon" in str(raised.value)

    @pytest.mark.parametrize("bad", [5, 5.0, "5m", None, False, [], 300_000])
    def test_a_bare_number_states_no_unit_for_the_fill_time(
        self, bad: object
    ) -> None:
        with pytest.raises(RouterOrderPostureError) as raised:
            resolve_order_posture(
                signal_decay_horizon=PATIENT_HORIZON, expected_fill_time=bad
            )
        assert str(raised.value).startswith(f"{ORDER_POSTURE_CODE}:")
        assert "expected_fill_time" in str(raised.value)

    def test_a_moment_is_not_a_duration(self) -> None:
        # An instant is not a length of time, whichever term it is offered
        # as: the comparison is between two *spans*, and a timestamp states
        # when, not how long.
        moment = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
        for ask in (
            lambda: resolve_order_posture(
                signal_decay_horizon=moment, expected_fill_time=PATIENT_FILL
            ),
            lambda: resolve_order_posture(
                signal_decay_horizon=PATIENT_HORIZON, expected_fill_time=moment
            ),
        ):
            with pytest.raises(RouterOrderPostureError) as raised:
                ask()
            assert str(raised.value).startswith(f"{ORDER_POSTURE_CODE}:")

    def test_a_negative_horizon_is_refused(self) -> None:
        # No measurement of an edge's survival runs backwards, and a
        # comparison over a negative length would be over nothing.
        with pytest.raises(RouterOrderPostureError) as raised:
            resolve_order_posture(
                signal_decay_horizon=timedelta(seconds=-1),
                expected_fill_time=PATIENT_FILL,
            )
        assert str(raised.value).startswith(f"{ORDER_POSTURE_CODE}:")
        assert "negative" in str(raised.value)

    def test_a_negative_fill_time_is_refused(self) -> None:
        with pytest.raises(RouterOrderPostureError) as raised:
            resolve_order_posture(
                signal_decay_horizon=PATIENT_HORIZON,
                expected_fill_time=timedelta(seconds=-1),
            )
        assert str(raised.value).startswith(f"{ORDER_POSTURE_CODE}:")
        assert "negative" in str(raised.value)

    def test_a_zero_horizon_is_admissible_and_compels_the_crossing(self) -> None:
        # Zero is a measurement, not an absence: an edge already gone is
        # the strongest case the sentence names for crossing, because
        # nothing survives waiting for it.
        posture = resolve_order_posture(
            signal_decay_horizon=timedelta(0), expected_fill_time=PATIENT_FILL
        )
        assert posture.posture == AGGRESSIVE_ORDER
        assert posture.is_aggressive is True

    def test_a_zero_fill_time_is_admissible_and_keeps_the_default(self) -> None:
        # A queue expected to clear the instant the order lands leaves
        # nothing to outrun -- no horizon is shorter than a zero wait -- so
        # the default stands, by the sentence's own arithmetic.
        posture = resolve_order_posture(
            signal_decay_horizon=PATIENT_HORIZON, expected_fill_time=timedelta(0)
        )
        assert posture.posture == PASSIVE_ORDER
        assert (
            resolve_order_posture(
                signal_decay_horizon=timedelta(0), expected_fill_time=timedelta(0)
            ).posture
            == PASSIVE_ORDER
        )


# =============================================================================
# "sends an aggressive order only when signal decay horizon is shorter
#  than expected fill time"
# =============================================================================


class TestAnAggressiveOrderIsSentOnlyWhenCompelled:
    """The exception fires on the comparison, and on nothing else."""

    def test_a_decay_that_outruns_the_fill_crosses(self) -> None:
        posture = resolve_order_posture(
            signal_decay_horizon=IMPATIENT_HORIZON,
            expected_fill_time=IMPATIENT_FILL,
        )
        assert posture.posture == AGGRESSIVE_ORDER
        assert posture.is_aggressive is True

    def test_a_stated_posture_that_agrees_is_kept(self) -> None:
        # Reconstruction from a record states the verdict; when the terms
        # compel it, the value stands.
        assert (
            OrderPosture(
                IMPATIENT_HORIZON, IMPATIENT_FILL, posture=AGGRESSIVE_ORDER
            ).posture
            == AGGRESSIVE_ORDER
        )
        assert (
            OrderPosture(PATIENT_HORIZON, PATIENT_FILL, posture=PASSIVE_ORDER).posture
            == PASSIVE_ORDER
        )

    def test_aggressive_stated_for_patient_terms_is_refused(self) -> None:
        with pytest.raises(RouterOrderPostureError) as raised:
            OrderPosture(PATIENT_HORIZON, PATIENT_FILL, posture=AGGRESSIVE_ORDER)
        assert str(raised.value).startswith(f"{ORDER_POSTURE_CODE}:")

    def test_passive_stated_for_impatient_terms_is_refused(self) -> None:
        with pytest.raises(RouterOrderPostureError):
            OrderPosture(IMPATIENT_HORIZON, IMPATIENT_FILL, posture=PASSIVE_ORDER)

    def test_the_refusal_names_the_terms_and_the_verdict_they_compel(
        self,
    ) -> None:
        # An operator auditing a record that crossed needs the edge, the
        # wait and the posture the terms compelled, in the refusal itself.
        with pytest.raises(RouterOrderPostureError) as raised:
            OrderPosture(PATIENT_HORIZON, PATIENT_FILL, posture=AGGRESSIVE_ORDER)
        message = str(raised.value)
        assert repr(PATIENT_HORIZON) in message
        assert repr(PATIENT_FILL) in message
        assert repr(PASSIVE_ORDER) in message
        assert "(feature 314)" in message

    def test_a_refused_ask_leaves_no_posture_behind(self) -> None:
        # There is nothing to leave behind -- no scope, no table, no
        # registry -- and this pins that the refusal is a raise and not a
        # recorded fallback: the ask either answers or does not exist.
        with pytest.raises(RouterOrderPostureError):
            resolve_order_posture(signal_decay_horizon=30, expected_fill_time=30)
        posture = resolve_order_posture(
            signal_decay_horizon=PATIENT_HORIZON, expected_fill_time=PATIENT_FILL
        )
        assert posture.posture == PASSIVE_ORDER


class TestTheErrorVocabulary:
    """Feature 314's refusal is its own class with its own greppable word."""

    def test_the_code_is_the_one_the_messages_open_with(self) -> None:
        with pytest.raises(RouterOrderPostureError) as raised:
            resolve_order_posture(signal_decay_horizon=30, expected_fill_time=30)
        assert str(raised.value).startswith(f"{ORDER_POSTURE_CODE}:")
        assert ORDER_POSTURE_CODE == "order_posture"

    def test_it_is_not_the_sibling_codes(self) -> None:
        # One grep apart, deliberately: the faults name deployments,
        # orders, budgets and waits, and an operator sent from one to the
        # other would edit the wrong file.
        for sibling in (
            CLIENT_ORDER_ID_CODE,
            CROSS_MARGIN_CODE,
            ORDER_SUBMISSION_UNHEALTHY_CODE,
            RATE_LIMITED_CODE,
            RETRY_BACKOFF_CODE,
            SUBMISSION_RESULT_CODE,
        ):
            assert ORDER_POSTURE_CODE != sibling

    def test_it_is_a_router_error_and_its_own_sibling(self) -> None:
        # Catchable through the member's one base, and *not* an instance of
        # any of the faults it must not be mistaken for: a caller catching
        # the fetch fault, the record fault, the health fault, the
        # identifier fault, the rate-limit tree, the duplicate-submission
        # fault or the margin fault must not have this refusal land in its
        # ``except``.
        with pytest.raises(RouterError) as raised:
            resolve_order_posture(signal_decay_horizon=30, expected_fill_time=30)
        for unrelated in (
            RouterFilterError,
            RouterStoreError,
            RouterSubmissionHealthError,
            RouterClientOrderIdError,
            RouterRateLimitError,
            RouterSubmissionResultError,
            RouterCrossMarginError,
        ):
            assert not issubclass(RouterOrderPostureError, unrelated)
            assert not isinstance(raised.value, unrelated)
            assert not issubclass(unrelated, RouterOrderPostureError)

    def test_it_is_not_the_margin_fault(self) -> None:
        # The split margin's own docstring draws: margin is judged once per
        # deployment, at startup; the posture is judged per order, as it is
        # built.  A caller sent to fix its book configuration because one
        # order crossed would repair the wrong layer.
        assert not issubclass(RouterOrderPostureError, RouterCrossMarginError)
        assert not issubclass(RouterCrossMarginError, RouterOrderPostureError)

    def test_it_is_not_the_identifier_fault(self) -> None:
        # The fine split: both are facts about one order, and feature 316's
        # class refuses a name it cannot hash into a key while this one
        # refuses the durations the crossing choice cannot read.
        assert not issubclass(RouterOrderPostureError, RouterClientOrderIdError)
        assert not issubclass(RouterClientOrderIdError, RouterOrderPostureError)


class TestTheMemberStillRegistersOneComponent:
    """Feature 314 adds a module and a class -- no component, no table."""

    def test_exactly_one_builder(self) -> None:
        assert [name for name in dir(member) if name.startswith("build_")] == [
            "build_router_exchange_info_store"
        ]

    def test_the_member_exports_the_feature_314_names(self) -> None:
        for name in (
            "AGGRESSIVE_ORDER",
            "ORDER_POSTURES",
            "ORDER_POSTURE_CODE",
            "PASSIVE_ORDER",
            "OrderPosture",
            "RouterOrderPostureError",
            "resolve_order_posture",
        ):
            assert name in member.__all__, name
            assert hasattr(member, name), name

    def test_the_member_still_exports_its_other_decisions(self) -> None:
        # Feature 315's gate and feature 316's key are untouched, and this
        # module never re-spells either.
        assert "require_isolated_margin" in member.__all__
        assert "derive_client_order_id" in member.__all__
        assert "client_order_digest" in member.__all__


class TestTheChoiceIsPure:
    """No clock, no I/O, no store -- the same ask answers the same posture."""

    def test_the_decision_reads_no_clock_of_its_own(self) -> None:
        # Pinned statically: a posture that depended on when it was computed
        # would be a second posture for one order between the decision and
        # the send, which is the one property a restarted router cannot
        # afford.
        import router.posture as module

        tree = ast.parse(inspect.getsource(module))
        reads = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"now", "perf_counter", "monotonic"}
        ]
        assert reads == []

    def test_the_module_imports_no_store(self) -> None:
        # Nothing to persist.  ``datetime`` is allowed here where margin's
        # own suite forbids it: that module judges a configuration and
        # needs no time at all, while this one's *terms* are lengths of
        # time and the module needs the type to read them.
        import router.posture as module

        tree = ast.parse(inspect.getsource(module))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        for forbidden in ("sqlite3", "os", "socket", "pathlib", "subprocess", "time"):
            assert forbidden not in imported, forbidden
        assert "datetime" in imported
        assert "dataclasses" in imported

    def test_the_decision_needs_no_database(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The feature's own shape: nothing to persist, nothing to compose.
        # If this ever needs a store, this test fails.
        monkeypatch.delenv("DATABASE_URL", raising=False)
        posture = resolve_order_posture(
            signal_decay_horizon=IMPATIENT_HORIZON, expected_fill_time=IMPATIENT_FILL
        )
        assert posture.is_aggressive is True

    def test_two_asks_of_one_order_agree(self) -> None:
        # What a restarted router re-derives is what the process it replaced
        # derived: the two terms are the whole of the decision.
        first = resolve_order_posture(
            signal_decay_horizon=IMPATIENT_HORIZON, expected_fill_time=IMPATIENT_FILL
        )
        second = OrderPosture(IMPATIENT_HORIZON, IMPATIENT_FILL)
        assert first == second
        assert first.is_aggressive == second.is_aggressive


class TestTheCrossProcessCase:
    """Two routers build one deployment's orders; the posture is the same in both."""

    _SCRIPT = """
import json
from datetime import timedelta

from router.posture import ORDER_POSTURES, resolve_order_posture
from router.errors import RouterOrderPostureError

print(json.dumps(sorted(ORDER_POSTURES)))
print(resolve_order_posture(
    signal_decay_horizon=timedelta(seconds=30),
    expected_fill_time=timedelta(minutes=5),
).posture)
print(resolve_order_posture(
    signal_decay_horizon=timedelta(minutes=30),
    expected_fill_time=timedelta(minutes=5),
).posture)
try:
    resolve_order_posture(signal_decay_horizon=30, expected_fill_time=5)
except RouterOrderPostureError as exc:
    print(str(exc).startswith({code!r}))
"""

    def _run(self, script: str) -> subprocess.CompletedProcess[str]:
        env = {
            **os.environ,
            "PYTHONPATH": os.pathsep.join(
                [
                    str(REPO_ROOT / "src"),
                    str(REPO_ROOT / "packages" / "router" / "src"),
                    os.environ.get("PYTHONPATH", ""),
                ]
            ),
        }
        return subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_another_interpreter_answers_the_same_posture(self) -> None:
        script = self._SCRIPT.format(code=ORDER_POSTURE_CODE)
        finished = self._run(script)
        assert finished.returncode == 0, finished.stderr
        vocabulary, aggressive, passive, refused = finished.stdout.strip().splitlines()
        assert json.loads(vocabulary) == sorted(ORDER_POSTURES)
        assert aggressive == AGGRESSIVE_ORDER
        assert passive == PASSIVE_ORDER
        assert refused == "True"
