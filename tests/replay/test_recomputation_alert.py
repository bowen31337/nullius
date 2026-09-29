"""Feature 253 in the assembled system — the alert over a composed replay path.

app_spec.xml, "Replay Engine", feature 253: *System emits a
``recomputation_suspected`` alert when a replay exceeds 200 milliseconds,
because the cost model has then broken.*  The member's own suite
(``packages/replay/tests/test_alert.py``) pins the law against 252's record and
against duck-typed carriers; what a member's suite structurally cannot pin is
the alert's behaviour **in the deployment**:

* **the composed application is unchanged** — 253 adds no component, so the
  factory still carries exactly the one ``replay`` component it carried before,
  and composing the alert costs composition nothing;
* **the composed replay path is the one the alert is about** — the duration the
  alert judges is measured off the *real* ``measure_replay`` clock around a walk
  of the *real* ``policy_runtime.CampaignTree``, performed by the component
  ``create_app()`` composed, so the number on the record is a deployment's
  number and not a fixture's;
* **the alert reaches an operator from a deployment that has no store** — the
  alert opens nothing: 253 names no table, so it must emit with ``DATABASE_URL``
  pointing at a database it could not possibly open, which is the fact that
  makes it the alert a *bare* deployment still gets;
* **it refuses no replay** — the composed walk that recomputed still returns its
  transition, and the alert is a second thing that happened, not a gate on the
  first: 252's law (*measures and persists; never refuses a slow replay*) holds
  through the composition;
* **253 and 254 agree about the slow tail** — a population that recomputed
  produces exactly one alert, on exactly the replay 254's report builds its tail
  from, and the report still carries that replay afterward; the two are composed
  here in a *test* (the feature-244 precedent), never in the packages, because
  neither member imports the other.

**Nothing here asserts ``isinstance`` across the composition seam.**  The module
loader imports a member under a synthetic name (``_nullius_scanned_<name>``) and
re-executes it, so the class objects the composed application's path produced are
*second* ones with the same names.  The alert itself is reached by import — it is
per-replay state with no component — but the record a deployment
holds may have come from either import path, which is exactly why 253's seam is
duck-typed; the checks below name the behaviour and compare
``type(exc).__name__``, the answer every other suite under ``tests/`` gives for
the same wrinkle.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
import replay

from app.module_loader import Registration, create_app, scan_components

REPO_ROOT = Path(__file__).resolve().parents[2]
REPLAY_SRC = REPO_ROOT / "packages" / "replay" / "src"

POLICY = "policy-v0007"
WORLD = "world-financial-0042"


@pytest.fixture(scope="module")
def app():
    """The composed application, built once — the same fixture the 245 suite uses.

    Module-scoped because composition is a deployment-wide act: the object is
    read-only by convention, so sharing it observes nothing any test here
    mutates, and rebuilding it per test would rebuild every other member's
    component for no assertion's benefit.
    """
    return create_app()


@pytest.fixture
def campaign_tree():
    """The real campaign tree a deployment holds, built by its own member.

    Read through ``CampaignTree.freeze`` — the public constructor feature 217
    ships — never by hand-rolling a node model: feature 253's alert is *about a
    replay*, so the replay it is measured around has to be the one the composed
    component actually walks.
    """
    policy_runtime = pytest.importorskip("policy_runtime")
    return policy_runtime.CampaignTree.freeze(
        {
            "r-mom": (None, 0, {"depth": 0, "r2_insample": None}),
            "m1": ("r-mom", 1, {"parent_id": "r-mom", "depth": 1, "r2_insample": 0.20}),
            "m1x": ("m1", 2, {"parent_id": "m1", "depth": 2, "r2_insample": 0.51}),
            "r-event": (None, 0, {"depth": 0, "r2_insample": None}),
        }
    )


# ---------------------------------------------------------------------------
# Composition is unchanged by this feature
# ---------------------------------------------------------------------------


def test_the_composed_application_still_carries_one_replay_component(app) -> None:
    # Feature 253 adds no component: the one the factory carries is still
    # feature 245's, reached by the plugin name the spec states.  A feature that
    # registered its own component would show up here as a second name — and in
    # every deployment as one more builder the factory runs inside
    # ``create_app()``, for a record and a raise that are per-replay state.
    assert "replay" in app.components
    assert "replay" in app.order


def test_scanning_the_member_still_registers_exactly_one_component() -> None:
    # The same question the 245 suite asks, asked again because 253 is a feature
    # that *could* have answered it differently: a fresh registry, so the answer
    # is this member's contribution rather than accumulated process state.
    components = scan_components(REPLAY_SRC, registry=Registration())
    assert [component.name for component in components] == ["replay"]


def test_the_composed_facade_grew_no_alert_verb(app) -> None:
    # The alert is a free function over a record, not a method on the composed
    # engine — the stance 252's timer and 254's report take — so the facade a
    # deployment holds is the same stateless three-verb object it was.  A verb
    # added here would be deployment state on a component that has none, and the
    # pre-existing resolution cycle would be widened by it.
    component = app.get("replay")
    assert getattr(component, "__slots__", None) == ()
    assert not hasattr(component, "__dict__"), "the facade must hold no instance state"
    for absent in ("emit_recomputation_suspected", "suspected_recomputation"):
        assert not hasattr(component, absent), absent


# ---------------------------------------------------------------------------
# The alert over a replay the composed deployment actually performed
# ---------------------------------------------------------------------------


def test_a_fast_composed_walk_emits_nothing(app, campaign_tree) -> None:
    # The number this feature judges comes off the *real* clock around a walk of
    # the *real* tree, performed by the *composed* component: a replay that reads
    # comes in far under docs §10.4's point, and the emission is silent — the
    # property a dreaming cycle sweeping thousands of these depends on.
    component = app.get("replay")
    with replay.measure_replay(POLICY, WORLD) as timer:
        transition = component.transition(campaign_tree)
    assert transition.transition("r-mom") == "m1"  # the walk really ran
    assert replay.emit_recomputation_suspected(timer.duration) is None


def test_the_slow_composed_walk_emits_the_alert(app, campaign_tree) -> None:
    # The feature's whole sentence, over the deployment: a replay that took past
    # 200 ms — held open here, because a sleeping body is the only way to make a
    # real replay slow on purpose, and 252's timer measures the interval it is
    # given rather than trusting a number — produces the alert, carrying that
    # measured interval and the pair the walk was measured under.
    component = app.get("replay")
    with replay.measure_replay(POLICY, WORLD) as slow:
        time.sleep(0.21)
        transition = component.transition(campaign_tree)
    assert transition.transition("r-mom") == "m1"
    with pytest.raises(replay.ReplayError) as raised:
        replay.emit_recomputation_suspected(slow.duration)
    # By name, not ``isinstance``: the record the composed path produced may be a
    # second class object of the same name (see the module docstring).
    assert type(raised.value).__name__ == "RecomputationSuspectedError"
    alert = raised.value.alert
    assert alert is not None
    assert alert.alert_kind == "recomputation_suspected"
    assert alert.policy_version == POLICY
    assert alert.world_id == WORLD
    assert alert.duration_seconds >= 0.21
    assert alert.threshold_seconds == replay.REPLAY_DURATION_ALERT_THRESHOLD


def test_the_alert_does_not_refuse_the_composed_walk(app, campaign_tree) -> None:
    # 252's law carried through the composition: the slow walk still produced
    # its transition, its record still answers the measurement, and the alert is
    # a *diagnosis of* that replay rather than a gate on it.  A deployment that
    # stopped replaying because a replay was slow would be failing P5's own
    # recommendation — §15's recovery is to revert to stored-float artifacts and
    # re-check the resident read, not to discard the replay.
    component = app.get("replay")
    with replay.measure_replay(POLICY, WORLD) as slow:
        time.sleep(0.21)
        transition = component.transition(campaign_tree)
    with pytest.raises(replay.ReplayError):
        replay.emit_recomputation_suspected(slow.duration)
    assert transition.prefix() == ("r-event", "r-mom")
    assert slow.duration.exceeds_alert_threshold is True
    assert slow.duration.within_target is False


# ---------------------------------------------------------------------------
# The alert opens nothing
# ---------------------------------------------------------------------------


def test_the_alert_reaches_an_operator_from_a_deployment_with_no_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Feature 253 names an *alert*, not a store — the in-repo precedent is
    # snapshot's corruption alert and nulloracle's unrecoverable state, both of
    # which raise a record with no table behind them.  The sharpest statement of
    # that is an environment where the observability store could not be opened
    # at all: the alert must still emit, because the processes that most need to
    # hear about a broken cost model are exactly the ones whose store is
    # unreachable.  A store-touching implementation would raise the database's
    # own refusal here instead of the alert.
    monkeypatch.setenv("DATABASE_URL", "postgresql://nowhere.example/nullius")
    with replay.measure_replay(POLICY, WORLD) as slow:
        time.sleep(0.21)
    with pytest.raises(replay.ReplayError) as raised:
        replay.emit_recomputation_suspected(slow.duration)
    assert type(raised.value).__name__ == "RecomputationSuspectedError"


def test_the_alert_module_touches_no_database_driver() -> None:
    # The same fact structurally, and it is the stronger of the two: this member
    # imports ``sqlite3`` for feature 254's store, and 253's module imports
    # nothing but the stdlib and its own two siblings.  A source read, because
    # "opened nothing" is a fact about the code rather than about one run — and
    # a driver behind an ``import`` inside a branch would not show up as a
    # module-level import either way, which is why the set below is exact: any
    # name at all that is not one of these six is a dependency this alert took
    # on and did not have.
    import ast

    import replay.alert as alert_module

    tree = ast.parse(Path(alert_module.__file__).read_text())
    imported = {
        (node.module or "").split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        # A relative import (``level`` > 0) names a sibling, never a dependency.
        and not node.level
    } | {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert imported <= {"__future__", "datetime", "math", "typing"}, imported
    assert "sqlite3" not in imported


# ---------------------------------------------------------------------------
# 253 and 254 agree about the slow tail
# ---------------------------------------------------------------------------


def test_the_population_254_summarises_is_the_one_253_alerts_over() -> None:
    # Two features about one fact, composed **here** rather than in the packages
    # (the feature-244 precedent: neither member imports the other, so the
    # agreement between them is a deployment's fact and it is pinned where a
    # deployment assembles them).  254 summarises a population and keeps the slow
    # tail as measured — *"the alert on the tail is feature 253's"* — so a
    # population that recomputed must produce exactly one alert, on exactly the
    # replay the report's tail is made of, and the report must still carry that
    # replay afterward: 254 keeps the tail, 253 speaks about it, and neither
    # censors the other.
    records = [
        replay.ReplayDuration(POLICY, WORLD, 0.030),
        replay.ReplayDuration(POLICY, WORLD, 0.045),
        replay.ReplayDuration(POLICY, WORLD, 0.080),
        replay.ReplayDuration(POLICY, WORLD, 0.310),  # the replay that recomputed
    ]
    report = replay.replay_latency(records)

    alerts, silent = [], []
    for record in records:
        (alerts if replay.suspected_recomputation(record) else silent).append(record)

    # One alert, and it is the slow replay's — the three fast ones warrant
    # nothing at all, because a p50 over §10.4's 50 ms *target* is still not a
    # broken cost model, and this feature alerts only on the second number.
    assert [record.duration_seconds for record in alerts] == [0.310]
    assert [record.duration_seconds for record in silent] == [0.030, 0.045, 0.080]

    # The tail the report carries is that same replay.  `p99_seconds` is a
    # *derived* view — the linear method interpolates between the top two
    # samples — so the honest claim is not equality with the sample but that the
    # slow replay is what the tail is made of, and that the report still reaches
    # past the broken-cost-model point on the strength of it.  A 254 that clipped
    # its tail would report a deployment nobody runs, and the alert would have
    # nothing to be about.
    assert report.n == len(records)  # nothing dropped from the population
    assert report.p99_seconds >= replay.REPLAY_DURATION_ALERT_THRESHOLD
    assert report.p99_seconds <= records[-1].duration_seconds  # a tail of it
    assert report.p99_seconds > records[-2].duration_seconds  # and not of the rest
    # p50 over the four, by the same linear method: between 0.045 and 0.080.
    assert report.p50_seconds == pytest.approx(0.0625)


def test_a_dreaming_cycles_sweep_emits_on_the_slow_replays_alone() -> None:
    # The shape a dreaming cycle actually writes: a *measured* population — one
    # real timer reading per replay — summarised by 254 and swept by 253, so
    # neither feature sees a number the other did not.  The emission is the typed
    # raise, so the sweep is a `try`, and exactly one replay out of three emits.
    records = []
    for seconds in (0.0, 0.0, 0.21):
        with replay.measure_replay(POLICY, WORLD) as timer:
            time.sleep(seconds)
        records.append(timer.duration)

    report = replay.replay_latency(records)
    emitted = []
    for record in records:
        try:
            replay.emit_recomputation_suspected(record)
        except replay.ReplayError as alert:
            emitted.append(alert)

    assert len(emitted) == 1, "exactly the replay that recomputed emits"
    assert type(emitted[0]).__name__ == "RecomputationSuspectedError"
    alert = emitted[0].alert
    assert alert is not None
    # The emitted record is the measured one — the same interval 254 summarised,
    # not a re-measurement of it — and the population is intact behind it.
    assert alert.duration_seconds == records[-1].duration_seconds
    assert report.n == 3
