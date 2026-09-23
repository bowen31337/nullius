"""The two seams: composition via the loader, and the app seat.

Feature 283's store is reached two ways — the factory's scan composes it
under the member's registered name, and :mod:`app.modules.regime` answers
*what is the composed coverage ledger?* for a caller that holds the app
namespace — and this file holds both halves of that wiring, the way
``packages/discovery/tests/test_component.py`` holds its own.

**The loader's properties shape the composition half exactly.**
``create_app`` imports each member under a synthetic module name
(``_nullius_scanned_<name>``), so the composed store's classes are
*structurally* identical to a direct import's but not the same objects:
this suite pins class name, module suffix and behaviour rather than
``isinstance``.  And the loader re-executes a package's ``__init__`` on
every composition but not an already-cached submodule, so a
``@register`` in a submodule fires on the first ``create_app()`` of a
process and silently drops out of every later one — which is why the
builder lives in ``__init__.py``, and why the second- and
third-composition tests below exist at all.

**The builder's own property: it degrades, and it writes nothing.**  The
regime member counts nothing of its own (the labeler is feature 290's
and the backfill 287's); what it has is a *deployment* — a database the
ledger lives in — and an absent one composes ``None`` rather than
raising, because a builder that raised would take composition down for
every unrelated feature in the workspace.  The composition seam is also
where a store that helped itself to a database would be hardest to see,
so the on-demand test holds the database file absent after composition
and after reading the component, and present only after a count is
actually persisted.

**The seat's ``None`` is about the deployment.**  ``Application()`` — no
scan at all — is the state where nothing was registered; a scanned
application with no ``DATABASE_URL`` is the state where the component
was registered and resolved no store.  A caller that must persist a
count has to refuse to proceed on either, but the two are different
facts and the tests keep them apart by constructing each deliberately.

**One naming note the discovery suite's once-only test cannot restate
here.**  The feature-store member legitimately registers
``regime-labeler`` and ``regime-metrics`` — the hyphenated spellings of
*its* regime components — so "every name starting with ``regime``"
belongs to three features across two members, and counting the prefix
would be counting someone else's registrations.  The boundary between
the members is the hyphen itself: this member's one name carries none,
the once-only assertion counts the exact name, and the member's own
exported surface is checked for its single builder instead.
"""

from __future__ import annotations

import inspect
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
import regime as member

from app.module_loader import Application, Registration, create_app, scan_components
from app.modules import regime as seat
from app.modules.regime import COMPONENT_NAME as SEAT_COMPONENT_NAME
from app.modules.regime import regime_coverage_component

#: The seat's whole public surface, asserted as an exact set for the same
#: reason the other seats' are: the failure this guards against is the seat
#: *growing* a re-export, and a membership check cannot see that.
EXPECTED_EXPORTS = {"COMPONENT_NAME", "regime_coverage_component"}

#: The names a well-meaning re-export would add first — the record, the
#: store, the module-level persist and the three strata are the member's
#: public vocabulary, and the seat's job is to answer one question about
#: composition.
NOT_THE_SEATS_BUSINESS = (
    "CoverageCount",
    "RegimeCoverage",
    "persist_coverage",
    "DEFAULT_STRATA",
    "CoverageError",
)


def _assert_is_the_coverage_store(component: object) -> None:
    """The composed component is the store, pinned across the loader's copies.

    Name, module suffix, then behaviour — the ladder the discovery
    member's component suites climb, because the loader's synthetic-name
    copies make ``isinstance`` unusable and behaviour is what matters
    anyway: the composed store carries the deployment's URL and answers
    the store's own questions.
    """
    assert type(component).__name__ == "RegimeCoverage"
    assert type(component).__module__.endswith("regime.coverage")
    for question in ("record", "name_stratum", "get", "resolve"):
        assert callable(getattr(component, question)), question
    for fact in ("database_url", "path"):
        assert getattr(component, fact) is not None, fact


# -- The registration -------------------------------------------------------------


def test_the_member_registers_under_its_own_name() -> None:
    # One component, unprefixed — the ``ledger`` / ``artifacts`` /
    # ``canary`` / ``discovery`` precedent for a member's first and only
    # contribution.  The member, the seat and the spec's plugin
    # vocabulary all spell the one name.
    assert member.COMPONENT_NAME == SEAT_COMPONENT_NAME == "regime"


def test_the_member_exports_exactly_one_builder() -> None:
    # This member's once-only property, stated on the member's own
    # surface: the ``build_*`` names it exports are its registered
    # contributions, and there is one.  (The registry itself cannot be
    # scoped by member — see the module docstring's naming note — so the
    # prefix-family count the discovery suite uses is replaced by this
    # and the exact-name count below.)
    assert [name for name in dir(member) if name.startswith("build_")] == [
        "build_regime_coverage"
    ]


def test_the_scanned_application_carries_the_store(monkeypatch, tmp_path: Path) -> None:
    # The factory scans the members, this package's ``@register`` fires,
    # and the composed application carries the ledger for the deployment
    # the process is running in — here, the database the test names.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'composed.db'}")
    app = create_app()
    assert member.COMPONENT_NAME in app
    assert member.COMPONENT_NAME in app.order
    _assert_is_the_coverage_store(app.get(member.COMPONENT_NAME))


def test_the_component_survives_a_second_composition(monkeypatch, tmp_path: Path) -> None:
    # The submodule-registration hazard, and the reason the builder lives
    # in ``__init__.py``: the loader caches imported submodules, so a
    # ``@register`` in one fires on the first composition of a process
    # and quietly drops out of every later one.  Asserts on the second
    # and third applications specifically — a test that only looked at
    # the first would pass wherever the builder lived and would have
    # caught nothing.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'composed.db'}")
    for app in (create_app(), create_app(), create_app()):
        _assert_is_the_coverage_store(app.get(member.COMPONENT_NAME))
        assert member.COMPONENT_NAME in app.order


def test_the_builder_degrades_to_none_without_a_database(monkeypatch) -> None:
    # An absent ``DATABASE_URL`` composes no ledger — a discoverable
    # deployment state, not an exception.  The *refusal* belongs to the
    # caller that must persist a count and finds no store, not to the
    # factory.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert create_app().get(member.COMPONENT_NAME) is None


def test_an_empty_database_url_counts_as_unset(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "   ")
    assert create_app().get(member.COMPONENT_NAME) is None


def test_the_builder_never_raises_and_takes_no_arguments(
    monkeypatch, tmp_path: Path
) -> None:
    # The registration protocol passes nothing, and the factory builds
    # every component on every composition — this builder honours both,
    # and resolves the environment itself.
    assert list(inspect.signature(member.build_regime_coverage).parameters) == []
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert member.build_regime_coverage() is None
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'built.db'}")
    assert isinstance(member.build_regime_coverage(), member.RegimeCoverage)


def test_a_url_the_builder_cannot_speak_is_not_raised_at_composition(monkeypatch) -> None:
    # Construction performs no I/O: the URL is translated (and a URL this
    # member cannot speak is refused by name) the first time an operation
    # needs the path.  So a misconfigured deployment composes a store
    # that refuses when it is used, rather than taking composition down
    # for everyone.
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/nullius")
    app = create_app()
    store = app.get(member.COMPONENT_NAME)
    assert store is not None  # composed, not raised
    # The error *name* rather than the class: the composed store's
    # classes are the loader's synthetic-name copies, structurally
    # identical to a direct import's but not the same objects, so
    # ``pytest.raises(<canonical>)`` cannot match them — the wrinkle the
    # discovery member's component suite documents, met the same way.
    with pytest.raises(Exception) as raised:
        store.record("crash", 1)
    assert type(raised.value).__name__ == "CoverageError"


def test_scanning_registers_the_component_exactly_once() -> None:
    # A duplicate registration of one name is silently overridden by
    # whichever import landed later, so it would be invisible at runtime
    # and would make the composed store depend on scan order.  Counted
    # against a fresh registry, so the assertion is about this name's
    # contribution.  Deliberately *exact-name*: the feature-store member
    # legitimately owns the hyphenated ``regime-labeler`` and
    # ``regime-metrics``, so the prefix family is two members' and only
    # this member's exact name is its to answer for.
    registry = Registration()
    scan_components(registry=registry)
    named = [
        component
        for component in registry.components()
        if component.name == member.COMPONENT_NAME
    ]
    assert len(named) == 1


def test_the_name_sorts_between_the_neighbours_the_composed_order_holds(
    monkeypatch, tmp_path: Path
) -> None:
    # ``Application.order`` is name-sorted, and other members' seats
    # carry adjacency assertions about their own neighbourhoods.  An
    # unprefixed ``regime`` lands after ``providers`` and before the
    # feature-store member's ``regime-labeler`` — the hyphenated names
    # that made the exact-name count above necessary — and this is
    # pinned against the *composed* order rather than against a guess at
    # it, so a later naming decision has to be made deliberately instead
    # of sliding in between two names nobody checked.
    #
    # Deliberately *ordering* rather than exact adjacency: another member
    # may legitimately register a component in this window, and a test
    # that insisted on the two neighbours by name would fail for a
    # sibling's correct change.  What matters is that this name sorts
    # clear of the hyphenated family it could be confused with — it must
    # precede every ``regime-*`` seat — and that it carries no prefix at
    # all.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'order.db'}")
    order = create_app().order
    assert order.index("providers") < order.index(member.COMPONENT_NAME)
    assert order.index(member.COMPONENT_NAME) < order.index("regime-labeler")
    assert not member.COMPONENT_NAME.startswith(
        ("nulloracle", "bootstrap", "sandbox", "tripwires", "regime-")
    )


# -- On demand --------------------------------------------------------------------


def test_composing_writes_nothing_and_persisting_is_on_demand(
    monkeypatch, tmp_path: Path
) -> None:
    # The ledger's rows are facts about the pool, written when the census
    # or the backfill counts it: an application composed *for* a
    # database-holding process writes nothing into it, and the file does
    # not even exist until the first persist brings the table.  A
    # composition that helped itself to the database would be writing
    # coverage nobody measured.
    database = tmp_path / "on-demand.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database}")
    app = create_app()
    assert not database.exists()  # composing wrote nothing
    store = app.get(member.COMPONENT_NAME)
    assert store is not None
    assert not database.exists()  # asking for the component neither
    store.record("crash", 1)
    assert database.exists()  # the demand is what wrote
    with closing(sqlite3.connect(database)) as connection:
        count = connection.execute("SELECT COUNT(*) FROM regime_coverage").fetchone()
    assert count[0] == 1


# -- The seat ---------------------------------------------------------------------


def test_the_seat_exposes_nothing_but_the_composition_accessor() -> None:
    assert set(seat.__all__) == EXPECTED_EXPORTS
    for name in EXPECTED_EXPORTS:
        assert hasattr(seat, name), name
    for leaked in NOT_THE_SEATS_BUSINESS:
        assert leaked not in seat.__all__, leaked


def test_the_seat_returns_the_composed_store(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'seated.db'}")
    store = regime_coverage_component()
    assert store is not None
    assert type(store).__name__ == "RegimeCoverage"
    assert store.database_url == f"sqlite:///{tmp_path / 'seated.db'}"


def test_the_seat_reads_the_application_it_is_handed(monkeypatch, tmp_path: Path) -> None:
    # A caller that already holds an application gets *that*
    # application's ledger — the seat must not compose its own behind the
    # caller's back.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'handed.db'}")
    app = create_app()
    assert regime_coverage_component(app) is app.get(member.COMPONENT_NAME)


def test_a_deployment_without_a_database_seats_none(monkeypatch) -> None:
    # The seat's ``None`` means the component ran and resolved no store —
    # a statement about the deployment.  A caller that must persist a
    # count has to read it as a refusal to proceed, not as an empty
    # ledger: an empty ledger answers *this stratum holds zero worlds*
    # about every name, while this says there is nowhere a count could
    # have been persisted.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = create_app()
    assert member.COMPONENT_NAME in app  # registered
    assert regime_coverage_component(app) is None  # and resolved nothing


def test_an_absent_component_reads_as_none_rather_than_raising() -> None:
    # ``Application`` is a plain dataclass, so the absent case is
    # constructible without depending on a scan having failed — and the
    # seat answers ``None`` rather than raising, which is what makes it
    # safe to import in a workspace that does not carry this member.
    assert regime_coverage_component(Application()) is None


def test_the_seat_composes_nothing_of_its_own() -> None:
    # Reading the component must not *create* one: a seat that built a
    # store behind the caller's back would report a ledger where the
    # deployment holds none — and would have opened a database the
    # process never asked for.
    empty = Application()
    assert regime_coverage_component(empty) is None
    assert empty.components == {}


def test_an_empty_workspace_still_seats_only_the_absent_store(tmp_path) -> None:
    # The same fact through the real factory: a composition whose scan
    # contributes nothing still builds, and the seat still answers
    # ``None``.  Both halves of "contributed nothing" are needed — an
    # empty root *and* a fresh registry (the default registry is
    # module-level and persists across calls, so a second ``create_app``
    # would inherit the first one's scan).
    empty = create_app(tmp_path, registry=Registration())
    assert empty.components == {}
    assert regime_coverage_component(empty) is None


@pytest.mark.parametrize("absent", ["", "Regime", "regime-coverage", "regime-store", "coverage"])
def test_a_misspelled_component_key_is_absent_not_a_near_match(
    monkeypatch, tmp_path: Path, absent: str
) -> None:
    # The component key is exact.  The plausible misses are the
    # capitalised reading, the table's own name, and the hyphenated
    # spellings someone reaching for the store from a report rather than
    # the code would try — and none may fuzzy-match, least of all into
    # the feature-store member's hyphenated regime components.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'keys.db'}")
    app = create_app()
    assert app.get(absent) is None
    assert SEAT_COMPONENT_NAME in app
    assert regime_coverage_component(app) is not None
