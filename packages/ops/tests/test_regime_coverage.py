"""Feature 343's route: GET /metrics/regime-coverage, the replay pool's
stored world counts per stratum.

app_spec.xml, "Observability & Dashboards", feature 343 — *System exposes
GET /metrics/regime-coverage which returns stored world counts per
stratum* — with the domain's API summary spelling it *"Return stored
world counts per regime stratum"*.  prd §C7 is the doctrine behind it
(*"Maintain an explicit ledger: ``{high-vol trend: 2, low-vol chop: 14,
crash: 0, …}``"*), and the ledger itself is the regime member's: feature
283 writes it, feature 284 reads it whole.

This suite pins the *route's* law — the seam, not the ledger:

* the route is exactly ``/metrics/regime-coverage``, carried on the
  endpoint as well as spelled as a module constant, so the spec's row and
  the component cannot drift;
* ``get()`` takes no arguments and answers the whole distribution — never
  one stratum's row, and never a filtered read, because the sentence asks
  for counts *per stratum*;
* the counts are feature 284's own
  (:attr:`regime.CoverageLedger.counts`), read through the regime
  member's store rather than re-spelled here — pinned by pointing the
  endpoint at a *real* ``regime.RegimeCoverage`` over a real SQLite file
  and asserting the answer agrees with what the regime member's own read
  says, in both directions;
* a stratum named and holding no worlds is a row (``crash: 0`` — the
  state feature 286 warns on) while a stratum nobody named is absent, and
  the route collapses neither into the other: no zero is filled in for an
  absent name, and no zeroed row is dropped;
* an empty ledger is answered as an empty distribution, which is *not* a
  refusal and *not* the unconfigured-store state;
* no ``DATABASE_URL`` composes no route at all — the two absences held
  apart;
* the response validates what it holds (a name that states nothing, a
  count that is not a genuine non-negative integer with ``bool`` refused
  first, a stratum named twice, an entry that is not a pair), and is
  frozen;
* a read that fails is translated into this member's vocabulary, chained,
  and never answered around with a distribution nobody counted; and
* building performs no I/O of any kind, and this module reaches no
  sibling member at module scope or build time — the one cross-member
  read is the deferred, declared ``regime`` door.

The fixtures mirror ``test_fdr_route.py``: a real SQLite file under
``tmp_path`` with ``DATABASE_URL`` pointed at it, so the route is
exercised end to end through the regime member's own store rather than
through a hand-rolled double that could agree with a misreading here.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import sqlite3
from pathlib import Path

import pytest
import regime
from ops import (
    OPS_REGIME_COVERAGE_COMPONENT_NAME,
    REGIME_COVERAGE_ROUTE,
    RegimeCoverageEndpoint,
    RegimeCoverageMetricError,
    RegimeCoverageResponse,
    require_regime,
)

#: A world count that is a *measurement*, not an absence — the value §C7's
#: own ledger holds for low-vol chop.
CHOP_WORLDS = 14


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    """A real SQLite file under the test's temporary directory."""
    return tmp_path / "regime-coverage.db"


@pytest.fixture
def store_url(store_path: Path) -> str:
    """A ``sqlite:///`` URL naming the test-only database."""
    return f"sqlite:///{store_path}"


@pytest.fixture
def store(store_url: str) -> regime.RegimeCoverage:
    """The *regime member's own* store, bound to the test-only database.

    Deliberately the member's real store rather than a double: this
    route's whole law is that it answers feature 284's read through
    feature 283's writer, and a hand-rolled carrier would agree with the
    route's misreading rather than disagree with it.
    """
    return regime.RegimeCoverage(store_url)


@pytest.fixture
def endpoint(store: regime.RegimeCoverage) -> RegimeCoverageEndpoint:
    """The route over the regime member's store."""
    return RegimeCoverageEndpoint(store)


def _persist(store: regime.RegimeCoverage, stratum: str, world_count: int) -> None:
    """One stratum's count, written through feature 283's own verb."""
    store.record(stratum, world_count)


# -- The route's name ----------------------------------------------------------


def test_the_route_is_the_one_the_spec_writes() -> None:
    # The spec's API summary row for the Observability domain, spelled
    # once: "GET /metrics/regime-coverage — Return stored world counts per
    # regime stratum".  Pinned as a literal so a rename cannot quietly
    # pass by agreeing with itself.
    assert REGIME_COVERAGE_ROUTE == "/metrics/regime-coverage"
    assert RegimeCoverageEndpoint.route == REGIME_COVERAGE_ROUTE


def test_the_component_name_is_the_member_prefixed_one() -> None:
    # The component name is the route's, member-first and route-second —
    # feature 341's `ops-fdr-deploy` beside it — so a composed
    # application's `order` sorts the category's two read-only routes as
    # peers rather than across two prefix families.
    assert OPS_REGIME_COVERAGE_COMPONENT_NAME == "ops-regime-coverage"


# -- The route's answer --------------------------------------------------------


def test_the_route_answers_stored_world_counts_per_stratum(
    endpoint: RegimeCoverageEndpoint, store: regime.RegimeCoverage
) -> None:
    # The feature sentence, at its seam: the pool's distribution, one
    # entry per named stratum.
    _persist(store, "high-volatility trend", 2)
    _persist(store, "low-volatility chop", CHOP_WORLDS)
    response = endpoint.get()
    assert isinstance(response, RegimeCoverageResponse)
    assert response.counts == {
        "high-volatility trend": 2,
        "low-volatility chop": CHOP_WORLDS,
    }


def test_the_answer_is_feature_284s_own_read(
    endpoint: RegimeCoverageEndpoint, store: regime.RegimeCoverage
) -> None:
    # The counts are the regime member's, not this module's re-derivation:
    # the route's answer and the member's own whole-ledger read agree in
    # both directions, over the same rows.  A second spelling here would
    # be a second place the pool's shape could drift from the ledger the
    # promotion gate blocks on.
    _persist(store, "crash", 0)
    _persist(store, "low-volatility chop", 3)
    ledger = store.ledger()
    assert endpoint.get().counts == ledger.counts


def test_the_route_reads_the_table_every_time(
    endpoint: RegimeCoverageEndpoint, store: regime.RegimeCoverage
) -> None:
    # No memo of a previous answer: the census writes counts from another
    # process, so a cached distribution would make the operator's view of
    # the pool a fact about when the surface started rather than about
    # what the pool holds.
    _persist(store, "crash", 1)
    assert endpoint.get().counts == {"crash": 1}
    _persist(store, "crash", 9)
    assert endpoint.get().counts == {"crash": 9}


def test_the_route_answers_the_whole_distribution_not_one_stratum(
    endpoint: RegimeCoverageEndpoint, store: regime.RegimeCoverage
) -> None:
    # The sentence asks for counts *per stratum*: a filtered read (one
    # name) is feature 283's own `get()`, and a route that answered one
    # row would report nothing about a deployment whose labeler carves
    # more strata than DEFAULT_STRATA names.
    _persist(store, "a fourth stratum the vocabulary never named", 4)
    _persist(store, "crash", 0)
    assert set(endpoint.get().counts) == {
        "a fourth stratum the vocabulary never named",
        "crash",
    }


def test_get_takes_no_arguments() -> None:
    # A GET over the ledger has no body and no stratum to filter by.
    signature = inspect.signature(RegimeCoverageEndpoint.get)
    assert list(signature.parameters) == ["self"]


def test_the_answer_exposes_the_section_c7_mapping(
    endpoint: RegimeCoverageEndpoint, store: regime.RegimeCoverage
) -> None:
    # prd §C7's own spelling — `{high-vol trend: 2, low-vol chop: 14,
    # crash: 0, …}` — which is the shape the spec's API summary writes the
    # route in and the shape feature 284's `counts` docstring names this
    # feature as the reason for.
    _persist(store, "high-volatility trend", 2)
    _persist(store, "low-volatility chop", CHOP_WORLDS)
    _persist(store, "crash", 0)
    assert endpoint.get().counts == {
        "high-volatility trend": 2,
        "low-volatility chop": CHOP_WORLDS,
        "crash": 0,
    }


# -- Named-empty versus never-named --------------------------------------------


def test_a_stratum_named_and_holding_none_is_a_row(
    endpoint: RegimeCoverageEndpoint, store: regime.RegimeCoverage
) -> None:
    # §C7's `crash: 0` — a stratum the census counted and found empty, the
    # state feature 286's empty_stratum warning fires on.  It is a
    # *measurement*, and the route serves it rather than dropping it.
    _persist(store, "crash", 0)
    response = endpoint.get()
    assert response.counts == {"crash": 0}
    assert "crash" in response.counts


def test_a_stratum_nobody_named_is_absent(
    endpoint: RegimeCoverageEndpoint, store: regime.RegimeCoverage
) -> None:
    # The other half of feature 0107's detail 1: a stratum the ledger holds
    # no row for is *never named*, and the route reports it as an absence
    # rather than stamping a zero on it — a zero would be a coverage
    # nobody counted, in the one direction §C7's ledger exists to make
    # impossible.  One named-empty row beside one absent name, so the two
    # states are visible in a single answer.
    _persist(store, "crash", 0)
    counts = endpoint.get().counts
    assert counts == {"crash": 0}
    for absent in ("high-volatility trend", "low-volatility chop"):
        assert absent not in counts


def test_the_route_fills_in_no_stratum(
    endpoint: RegimeCoverageEndpoint, store: regime.RegimeCoverage
) -> None:
    # DEFAULT_STRATA names three strata and the ledger holds none of them:
    # a route that answered the vocabulary rather than the pool would
    # report three zeroes here.  It reports nothing, because nothing is
    # what the pool names.
    _persist(store, "an unnamed fourth", 1)
    assert endpoint.get().counts == {"an unnamed fourth": 1}
    assert set(endpoint.get().counts).isdisjoint(regime.DEFAULT_STRATA)


def test_an_empty_ledger_is_an_honest_absence(
    endpoint: RegimeCoverageEndpoint,
) -> None:
    # A configured database where no census has run yet: the response
    # holds no rows and is falsy.  A discoverable state answered as an
    # absence, never a refusal — the stance feature 284's own read takes.
    response = endpoint.get()
    assert response.counts == {}
    assert not response
    assert len(response) == 0


def test_the_empty_answer_is_not_a_zeroed_vocabulary(
    endpoint: RegimeCoverageEndpoint,
) -> None:
    # The distinction that matters most on this route: *the pool names
    # nothing* is not *every stratum holds zero worlds*.  The latter is a
    # non-empty mapping whose every value is 0 — those rows exist and are
    # findings — and it is truthy here, because the rows are real.
    empty = endpoint.get()
    assert empty.counts == {}
    for name in regime.DEFAULT_STRATA:
        assert name not in empty.counts


def test_a_zero_only_ledger_is_truthy(
    endpoint: RegimeCoverageEndpoint, store: regime.RegimeCoverage
) -> None:
    _persist(store, "crash", 0)
    _persist(store, "low-volatility chop", 0)
    response = endpoint.get()
    assert response.counts == {"crash": 0, "low-volatility chop": 0}
    assert response
    assert len(response) == 2


# -- Order and content ---------------------------------------------------------


def test_the_answer_is_sorted_by_stratum(
    endpoint: RegimeCoverageEndpoint, store: regime.RegimeCoverage
) -> None:
    # The read's canonical order, imposed on the response too: the display
    # must not change because two readings reached the same rows in a
    # different order.
    _persist(store, "zulu", 1)
    _persist(store, "alpha", 2)
    _persist(store, "mike", 3)
    response = endpoint.get()
    assert [name for name, _ in response.strata] == ["alpha", "mike", "zulu"]
    assert list(response.counts) == ["alpha", "mike", "zulu"]


def test_the_answer_carries_stratum_and_count_and_nothing_third(
    endpoint: RegimeCoverageEndpoint, store: regime.RegimeCoverage
) -> None:
    # The two facts §C7's ledger holds per stratum.  No sum, no
    # percentage, no verdict: the pool's *size* is not its *distribution*,
    # and the judgements built over this ledger (feature 285's promotion
    # block, feature 289's diversity floor, feature 286's warning) are each
    # their own seam.
    _persist(store, "crash", 2)
    for row in endpoint.get().strata:
        assert len(row) == 2
        name, count = row
        assert isinstance(name, str) and isinstance(count, int)


def test_len_counts_strata_not_worlds(
    endpoint: RegimeCoverageEndpoint, store: regime.RegimeCoverage
) -> None:
    # `len` is the number of *names*, deliberately not a sum of the
    # counts: a ledger naming two strata is two names whether they hold
    # two worlds or two million.
    _persist(store, "crash", 2_000_000)
    _persist(store, "low-volatility chop", 0)
    assert len(endpoint.get()) == 2


def test_the_counts_view_is_a_fresh_mapping_each_call(
    endpoint: RegimeCoverageEndpoint, store: regime.RegimeCoverage
) -> None:
    # A caller cannot mutate this value's answer.
    _persist(store, "crash", 1)
    response = endpoint.get()
    first = response.counts
    first["crash"] = 999
    assert response.counts == {"crash": 1}


# -- The response's own validation ---------------------------------------------


@pytest.mark.parametrize(
    ("strata", "fragment"),
    [
        (("crash",), "is not one"),
        ([("crash", 1, "extra")], "3 values"),
        ([("", 1)], "no nameable one"),
        ([("   ", 1)], "no nameable one"),
        ([(None, 1)], "no nameable one"),
        ([(7, 1)], "no nameable one"),
        ([("crash", "1")], "non-negative integer"),
        ([("crash", 1.0)], "non-negative integer"),
        ([("crash", None)], "non-negative integer"),
        ([("crash", -1)], "at least 0"),
        ([("crash", True)], "non-negative integer"),
        ([("crash", 1), ("crash", 2)], "twice"),
        ("crash", "is not one"),
        (7, "is not one"),
    ],
)
def test_a_distribution_the_response_cannot_hold_is_refused(
    strata: object, fragment: str
) -> None:
    # A frozen value that validated nothing would lend this route's
    # guarantees to a distribution no store answered.  Each half is
    # defended with feature 283's own law: a name is non-empty text (the
    # strip is the near-miss guard against a trailing newline persisting
    # as a second row for one stratum) and a count is a genuine
    # non-negative integer, with bool refused *before* int because True is
    # an int in Python and a flag where a count belongs would silently
    # answer one stored world.
    with pytest.raises(RegimeCoverageMetricError) as caught:
        RegimeCoverageResponse(strata)
    assert fragment in str(caught.value)


def test_a_refused_distribution_names_the_feature_and_the_section() -> None:
    # The refusal's argument, so an operator reading a log line learns
    # which doctrine the number they passed broke.
    with pytest.raises(RegimeCoverageMetricError) as caught:
        RegimeCoverageResponse([("crash", -1)])
    message = str(caught.value)
    assert "feature 343" in message
    assert "§C7" in message
    assert REGIME_COVERAGE_ROUTE in message


def test_the_response_is_frozen() -> None:
    # The response is the route's testimony about the ledger at the moment
    # it was read; nothing on it is a knob to adjust.
    response = RegimeCoverageResponse([("crash", 1)])
    with pytest.raises(dataclasses.FrozenInstanceError):
        response.strata = ()


def test_the_response_accepts_the_section_c7_shape_it_derives() -> None:
    # §C7 writes the ledger as a mapping and `counts` derives exactly that
    # shape, so a hand-built response must not have to convert the spec's
    # own shape into a sequence of pairs to be accepted.  Order is the
    # value's either way — a mapping's entries are not ordered, so the
    # sort-by-stratum is what fixes the display.
    response = RegimeCoverageResponse({"zulu": 1, "alpha": 2, "crash": 0})
    assert response.counts == {"zulu": 1, "alpha": 2, "crash": 0}
    assert [name for name, _ in response.strata] == ["alpha", "crash", "zulu"]


def test_a_mapping_answer_validates_its_counts_like_any_other() -> None:
    # The mapping door is a translation, not a bypass: every entry still
    # goes through the same narrowing, so a mapping cannot smuggle in a
    # count a sequence would have been refused for.
    with pytest.raises(RegimeCoverageMetricError):
        RegimeCoverageResponse({"crash": "1"})
    with pytest.raises(RegimeCoverageMetricError):
        RegimeCoverageResponse({"": 1})


def test_the_response_strips_a_near_miss_name() -> None:
    # Feature 283's writer strips before persisting, so a name arriving
    # here with padding is the same stratum — and holding it unstripped
    # would answer a *second* key for one stratum.
    response = RegimeCoverageResponse([(" crash ", 1)])
    assert response.counts == {"crash": 1}


def test_the_response_refuses_two_names_that_reduce_to_one() -> None:
    with pytest.raises(RegimeCoverageMetricError) as caught:
        RegimeCoverageResponse([("crash", 1), (" crash ", 2)])
    assert "twice" in str(caught.value)


# -- The store seam ------------------------------------------------------------


def test_the_endpoint_refuses_a_carrier_that_cannot_read_the_ledger() -> None:
    # Duck-checked, never isinstance-guarded: a carrier that can only
    # answer one stratum's row cannot report the pool's shape.
    with pytest.raises(TypeError) as caught:
        RegimeCoverageEndpoint(object())
    assert "ledger()" in str(caught.value)
    with pytest.raises(TypeError):
        RegimeCoverageEndpoint({"ledger": None})


def test_a_ledger_whose_mapping_cannot_be_read_is_refused_by_name() -> None:
    # The composed store always answers the mapping, but the endpoint is
    # constructible with any carrier satisfying its duck check — and a
    # value whose content cannot be read is refused by name rather than
    # reaching construction as a puzzling AttributeError from inside this
    # module's own plumbing.
    class NotALedger:
        pass

    class CarriesNotALedger:
        def ledger(self) -> object:
            return NotALedger()

    endpoint = RegimeCoverageEndpoint(CarriesNotALedger())
    with pytest.raises(RegimeCoverageMetricError) as caught:
        endpoint.get()
    assert "does not carry one" in str(caught.value)


def test_a_failing_read_is_translated_not_answered_around() -> None:
    # The member-seam law: the rows are the regime member's, the route is
    # this member's, and a caller that wrote
    # `except RegimeCoverageMetricError` must not be taken down by the
    # regime member's own error class — translated at the seam, chained,
    # and never caught *into* an answer.
    class Refusing:
        def ledger(self) -> object:
            raise regime.CoverageError("the store's own words")

    with pytest.raises(RegimeCoverageMetricError) as caught:
        RegimeCoverageEndpoint(Refusing()).get()
    assert REGIME_COVERAGE_ROUTE in str(caught.value)
    assert isinstance(caught.value.__cause__, regime.CoverageError)
    assert "the store's own words" in str(caught.value.__cause__)


def test_a_carrier_bug_is_not_dressed_up_as_a_store_failure() -> None:
    # Only the store's own vocabulary is translated.  A carrier that fails
    # with anything else is a caller bug and propagates raw — translating
    # it would dress a programming error up as a metrics refusal and send
    # an operator hunting a database that is fine.
    class Buggy:
        def ledger(self) -> object:
            raise ValueError("a bug, not a refusal")

    with pytest.raises(ValueError, match="a bug, not a refusal"):
        RegimeCoverageEndpoint(Buggy()).get()


def test_a_corrupt_row_surfaces_as_this_members_vocabulary(
    store_url: str, store_path: Path
) -> None:
    # A row another tool wrote — a count that is not an integer — is
    # refused by the regime member's read (feature 284's own law, which
    # names the stratum it came off), and that refusal reaches this
    # route's caller in this member's vocabulary, chained.  Never answered
    # around: a fallback distribution would report a pool nobody counted.
    store = regime.RegimeCoverage(store_url)
    _persist(store, "crash", 1)
    connection = sqlite3.connect(store_path)
    with connection:
        connection.execute(
            f"UPDATE {regime.COVERAGE_TABLE} SET {regime.WORLD_COUNT_COLUMN} = ? "
            f"WHERE {regime.STRATUM_COLUMN} = ?",
            ("not a count", "crash"),
        )
    connection.close()
    endpoint = RegimeCoverageEndpoint(regime.RegimeCoverage(store_url))
    with pytest.raises(RegimeCoverageMetricError) as caught:
        endpoint.get()
    assert isinstance(caught.value.__cause__, regime.CoverageError)
    assert "crash" in str(caught.value.__cause__)


def test_a_read_against_an_unreachable_database_is_surfaced() -> None:
    # A store the route cannot ask — here a URL whose path is a file
    # rather than a directory — is surfaced in this member's vocabulary
    # rather than answered around with an empty distribution, which would
    # read as *an empty ledger*: the honest-absence answer wearing a state
    # it does not have.  The regime member refuses this URL itself, so the
    # refusal arrives already in the store's vocabulary and is translated.
    endpoint = RegimeCoverageEndpoint(
        regime.RegimeCoverage("postgresql://host/coverage")
    )
    with pytest.raises(RegimeCoverageMetricError) as caught:
        endpoint.get()
    assert isinstance(caught.value.__cause__, regime.CoverageError)


def test_the_store_speaks_the_regime_members_own_type(
    endpoint: RegimeCoverageEndpoint, store: regime.RegimeCoverage
) -> None:
    assert endpoint.store is store


# -- from_env ------------------------------------------------------------------


def test_from_env_answers_none_without_a_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An unconfigured store is a discoverable deployment state, not an
    # error — and deliberately *not* the empty-ledger answer: no route at
    # all says there is nowhere a count could have been persisted, while
    # an empty ledger says the pool names no stratum.  Two different
    # facts, and an operator wants to tell them apart.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert RegimeCoverageEndpoint.from_env() is None


@pytest.mark.parametrize("value", ["", "   ", "\t\n"])
def test_from_env_refuses_a_blank_url(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", value)
    assert RegimeCoverageEndpoint.from_env() is None


def test_from_env_holds_the_url_without_touching_the_disk(
    store_url: str, store_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The URL is a composition fact, resolved eagerly; the *store* is
    # deferred, because a builder runs after the factory's scan has taken
    # the regime member's src/ back off sys.path.  Building creates no
    # database file at all.
    monkeypatch.setenv("DATABASE_URL", store_url)
    endpoint = RegimeCoverageEndpoint.from_env()
    assert endpoint is not None
    assert endpoint.store.database_url == store_url
    assert not store_path.exists()


def test_from_env_reads_a_mapping_it_is_handed(store_url: str) -> None:
    endpoint = RegimeCoverageEndpoint.from_env({"DATABASE_URL": store_url})
    assert endpoint is not None
    assert endpoint.store.database_url == store_url


def test_the_deferred_carrier_reaches_the_regime_members_own_read(
    store_url: str, store_path: Path
) -> None:
    # The endpoint built by from_env answers the same distribution the
    # member's own store does — the deferral moves *when* the store is
    # constructed, never *what* it is.
    endpoint = RegimeCoverageEndpoint.from_env({"DATABASE_URL": store_url})
    assert endpoint is not None
    assert endpoint.get().counts == {}
    store = regime.RegimeCoverage(store_url)
    _persist(store, "crash", 3)
    assert endpoint.get().counts == {"crash": 3}
    assert store_path.exists()


# -- The module's own law ------------------------------------------------------


def test_require_regime_answers_the_member() -> None:
    assert require_regime() is regime


def test_the_module_imports_no_sibling_at_scope() -> None:
    # The member's law is delegation, and the one cross-member read is the
    # deferred, declared regime door.  Read on the code (docstrings
    # stripped), so the prose may name the regime member and the code may
    # not reach it at module scope.
    import ops.regime_coverage as module

    tree = ast.parse(_code_of(module))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module.split(".")[0])
    assert imported <= {
        "__future__",
        "collections",
        "dataclasses",
        "os",
        "regime",
        "typing",
        "errors",
    }, sorted(imported)
    # The one sibling it does reach is the declared, deferred door — and
    # the test below pins that the import lives inside it.  Every other
    # member is absent: this route re-derives no figure of its own.
    for sibling in ("scoring", "promotion", "nulloracle", "ledger", "dreaming"):
        assert sibling not in imported
    # And no clock: the response is a reading, and nothing here stamps an
    # instant of its own.
    names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert "perf_counter" not in names
    assert "now" not in names


def test_the_sibling_import_lives_inside_the_door() -> None:
    # `import regime` appears in exactly one place — inside
    # require_regime, where it is deferred past module scope and past
    # builder time — and the module's other cross-member reach is the
    # regime member's own `RegimeCoverage` through that door.
    import ops.regime_coverage as module

    tree = ast.parse(_code_of(module))
    at_scope = [
        node
        for node in tree.body
        if isinstance(node, ast.Import)
        and any(alias.name == "regime" for alias in node.names)
    ]
    assert at_scope == []
    source = _code_of(module)
    assert source.count("import regime") == 1


def test_the_module_declares_its_dependency_in_the_member_pyproject() -> None:
    # The regime member is a declared workspace dependency of this member,
    # the same way the scoring member is for feature 341's route: the
    # import is deferred, but it is not undeclared.
    member_root = Path(__file__).resolve().parents[1]
    declaration = (member_root / "pyproject.toml").read_text()
    assert "regime" in declaration.split("[project]")[1].split("[build-system]")[0]


def test_require_regime_says_which_wheel_is_missing() -> None:
    # The door's own failure mode: a deployment that genuinely needs the
    # ledger and cannot reach the regime member is told what to run rather
    # than shown a bare ImportError.  Simulated by making the import fail.
    import builtins

    real_import = builtins.__import__

    def refusing(name: str, *args: object, **kwargs: object) -> object:
        if name == "regime":
            raise ModuleNotFoundError("No module named 'regime'")
        return real_import(name, *args, **kwargs)

    builtins.__import__ = refusing
    try:
        with pytest.raises(ModuleNotFoundError) as caught:
            require_regime()
    finally:
        builtins.__import__ = real_import
    assert "uv sync --all-packages" in str(caught.value)
    assert isinstance(caught.value.__cause__, ModuleNotFoundError)


def _code_of(module: object) -> str:
    """The module's source with every docstring stripped.

    The "what the code does, not what the prose says" reading this suite
    shares with the member's other suites: a docstring naming the regime
    member's store is honesty (the figure's owner is stated where it is
    delegated to), while an *import* of it at module scope would be the
    second spelling this route exists to avoid — and only the AST can tell
    the two apart.
    """
    tree = ast.parse(inspect.getsource(module))
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)
