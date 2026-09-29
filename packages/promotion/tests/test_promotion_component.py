"""The composition seam: the member's registry as the loader composes it.

Feature 291's registry is reached through the factory's scan, which composes
it under the member's registered name, and ``create_app().get("promotion")``
answers *what is the composed pre-registration registry?* — this file holds
that wiring, the way ``packages/regime/tests/test_component.py`` holds its
own.

**The loader's properties shape the composition half exactly.**
``create_app`` imports each member under a synthetic module name
(``_nullius_scanned_<name>``), so the composed store's classes are
*structurally* identical to a direct import's but not the same objects: this
suite pins class name, module suffix and behaviour rather than ``isinstance``.
And the loader re-executes a package's ``__init__`` on every composition but
not an already-cached submodule, so a ``@register`` in a submodule fires on
the first ``create_app()`` of a process and silently drops out of every later
one — which is why the builder lives in ``__init__.py``, and why the second-
and third-composition tests below exist at all.

**The builder's own property: it degrades, and it writes nothing.**  The
promotion member judges nothing of its own — the deciding evaluation is
another feature's, and so is the mismatch verdict (292) and the decision
(293); what it has is a *deployment*, a database the registry lives in, and
an absent one composes ``None`` rather than raising, because a builder that
raised would take composition down for every unrelated feature in the
workspace.  The composition seam is also where a store that helped itself to
a database would be hardest to see, so the on-demand test holds the database
file absent after composition and after reading the component, and present
only after a registration is actually written.  That test is sharper here than
for a store that only writes one table: this store *creates three*, so a
composition that touched the database would leave a visibly larger footprint
than the one row it was asked for.

**A composed ``None`` is about the deployment.**  ``Application()`` — no scan
at all — is the state where nothing was registered; a scanned application with
no ``DATABASE_URL`` is the state where the component was registered and
resolved no store.  A caller that must pre-register criteria has to refuse to
proceed on either, but the two are different facts and the tests keep them
apart by constructing each deliberately.
"""

from __future__ import annotations

import inspect
import sqlite3
from contextlib import closing
from pathlib import Path

import promotion as member
import pytest
from conftest import DEFAULT_CRITERIA_DOCUMENT, EPOCH_ID, NODE_ID

from app.module_loader import Application, Registration, create_app, scan_components


def _assert_is_the_registry(component: object) -> None:
    """The composed component is the store, pinned across the loader's copies.

    Name, module suffix, then behaviour — the ladder the discovery and regime
    members' component suites climb, because the loader's synthetic-name
    copies make ``isinstance`` unusable and behaviour is what matters anyway:
    the composed store carries the deployment's URL and answers the store's
    own questions.
    """
    assert type(component).__name__ == "PreRegistrations"
    assert type(component).__module__.endswith("promotion.pre_register")
    for question in ("pre_register", "resolve"):
        assert callable(getattr(component, question)), question
    for fact in ("database_url", "path"):
        assert getattr(component, fact) is not None, fact


# -- The registration -------------------------------------------------------------


def test_the_member_registers_under_its_own_name() -> None:
    # One component, unprefixed — the ``ledger`` / ``artifacts`` / ``canary``
    # / ``discovery`` / ``regime`` precedent for a member's first and only
    # contribution.  The member and the spec's plugin vocabulary both spell
    # the one name.
    assert member.COMPONENT_NAME == "promotion"


def test_the_member_exports_exactly_one_builder() -> None:
    # This member's once-only property, stated on the member's own surface:
    # the ``build_*`` names it exports are its registered contributions, and
    # there is one.  The endpoint is deliberately *not* registered — it holds
    # no state of its own, so composing it would put two entries in
    # ``app.order`` pointing at one database — and this assertion is where
    # that decision would be noticed if it were reversed.
    assert [name for name in dir(member) if name.startswith("build_")] == [
        "build_promotion_registry"
    ]


def test_the_scanned_application_carries_the_registry(monkeypatch, tmp_path: Path) -> None:
    # The factory scans the members, this package's ``@register`` fires, and
    # the composed application carries the registry for the deployment the
    # process is running in — here, the database the test names.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'composed.db'}")
    app = create_app()
    assert member.COMPONENT_NAME in app
    assert member.COMPONENT_NAME in app.order
    _assert_is_the_registry(app.get(member.COMPONENT_NAME))


def test_the_component_survives_a_second_composition(monkeypatch, tmp_path: Path) -> None:
    # The submodule-registration hazard, and the reason the builder lives in
    # ``__init__.py``: the loader caches imported submodules, so a ``@register``
    # in one fires on the first composition of a process and quietly drops out
    # of every later one.  Asserts on the second and third applications
    # specifically — a test that only looked at the first would pass wherever
    # the builder lived and would have caught nothing.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'composed.db'}")
    for app in (create_app(), create_app(), create_app()):
        _assert_is_the_registry(app.get(member.COMPONENT_NAME))
        assert member.COMPONENT_NAME in app.order


def test_no_other_component_in_the_workspace_shares_the_name() -> None:
    # A duplicate registration of one name is silently overridden by whichever
    # import landed later, so it would be invisible at runtime and would make
    # the composed store depend on scan order.  Counted against a fresh
    # registry, so the assertion is about this name's contribution — and
    # *exact-name* rather than by prefix, because this member's unprefixed key
    # is the whole of its identity: unlike ``regime``, no hyphenated family
    # could accidentally share it, which is exactly why the count can be exact.
    registry = Registration()
    scan_components(registry=registry)
    named = [
        component
        for component in registry.components()
        if component.name == member.COMPONENT_NAME
    ]
    assert len(named) == 1


def test_the_builder_degrades_to_none_without_a_database(monkeypatch) -> None:
    # An absent ``DATABASE_URL`` composes no registry — a discoverable
    # deployment state, not an exception.  The *refusal* belongs to the caller
    # that must pre-register criteria and finds no store, not to the factory.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert create_app().get(member.COMPONENT_NAME) is None


def test_an_empty_database_url_counts_as_unset(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "   ")
    assert create_app().get(member.COMPONENT_NAME) is None


def test_the_builder_never_raises_and_takes_no_arguments(
    monkeypatch, tmp_path: Path
) -> None:
    # The registration protocol passes nothing, and the factory builds every
    # component on every composition — this builder honours both, and resolves
    # the environment itself.
    assert list(inspect.signature(member.build_promotion_registry).parameters) == []
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert member.build_promotion_registry() is None
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'built.db'}")
    assert isinstance(member.build_promotion_registry(), member.PreRegistrations)


def test_a_url_the_builder_cannot_speak_is_not_raised_at_composition(monkeypatch) -> None:
    # Construction performs no I/O: the URL is translated (and a URL this
    # member cannot speak is refused by name) the first time an operation
    # needs the path.  So a misconfigured deployment composes a store that
    # refuses when it is used, rather than taking composition down for
    # everyone.
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/nullius")
    app = create_app()
    store = app.get(member.COMPONENT_NAME)
    assert store is not None  # composed, not raised
    # The error *name* rather than the class: the composed store's classes are
    # the loader's synthetic-name copies, structurally identical to a direct
    # import's but not the same objects, so ``pytest.raises(<canonical>)``
    # cannot match them — the wrinkle the other members' component suites
    # document, met the same way.
    with pytest.raises(Exception) as raised:
        store.pre_register(
            NODE_ID, EPOCH_ID, dict(DEFAULT_CRITERIA_DOCUMENT)
        )
    assert type(raised.value).__name__ == "PromotionStoreError"


def test_the_name_sorts_between_the_neighbours_the_composed_order_holds(
    monkeypatch, tmp_path: Path
) -> None:
    # ``Application.order`` is name-sorted, and other members' suites carry
    # adjacency assertions about their own neighbourhoods.  This is pinned
    # against the *composed* order rather than against a guess at it, so a
    # later naming decision has to be made deliberately instead of sliding in
    # between two names nobody checked.
    #
    # Deliberately *ordering* rather than exact adjacency: another member may
    # legitimately register a component in this window — ``providers`` already
    # follows ``policy-runtime`` with this name between them — and a test that
    # insisted on the two neighbours being adjacent would fail for a sibling's
    # correct change.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'order.db'}")
    order = create_app().order
    assert order.index("policy-runtime") < order.index(member.COMPONENT_NAME)
    assert order.index(member.COMPONENT_NAME) < order.index("providers")
    assert not member.COMPONENT_NAME.startswith(
        ("nulloracle", "bootstrap", "sandbox", "tripwires", "regime-", "ledger-")
    )


# -- On demand --------------------------------------------------------------------


def test_composing_writes_nothing_and_registering_is_on_demand(
    monkeypatch, tmp_path: Path
) -> None:
    # A pre-registration is a fact about a hypothesis, written when a caller
    # asks for its criteria to be fixed: an application composed *for* a
    # database-holding process writes nothing into it, and the file does not
    # even exist until the first registration brings the three tables.  A
    # composition that helped itself to the database would be recording
    # criteria nobody registered — and, because this store creates ``node``
    # and ``epoch_ledger`` too, it would also be fabricating two parent tables
    # on behalf of features whose writers are elsewhere.
    database = tmp_path / "on-demand.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database}")
    app = create_app()
    assert not database.exists()  # composing wrote nothing
    store = app.get(member.COMPONENT_NAME)
    assert store is not None
    assert not database.exists()  # asking for the component neither
    store._connect().close()
    assert database.exists()  # the demand is what created, and it is the store's
    with closing(sqlite3.connect(database)) as connection:
        tables = {
            name
            for (name,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert {"node", "epoch_ledger", "promotion_registry"} <= tables


def test_composing_records_no_pre_registration(monkeypatch, tmp_path: Path) -> None:
    # The sharper half of the same fact, in the table's own terms: composing
    # must not leave a *row*.  A composition that pre-registered something
    # would be fixing criteria for a hypothesis nobody named.
    database = tmp_path / "no-rows.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database}")
    create_app()
    assert not database.exists()
    with closing(sqlite3.connect(database)) if database.exists() else closing(
        sqlite3.connect(":memory:")
    ) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name = 'promotion_registry'"
            ).fetchone()[0]
            == 0
        )


# -- Reading the composition -----------------------------------------------------


def test_the_composed_application_returns_the_store(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'composed.db'}")
    store = create_app().get("promotion")
    assert store is not None
    assert type(store).__name__ == "PreRegistrations"
    assert store.database_url == f"sqlite:///{tmp_path / 'composed.db'}"


def test_a_deployment_without_a_database_composes_none(monkeypatch) -> None:
    # A composed ``None`` means the component ran and resolved no store — a
    # statement about the deployment.  A caller that must pre-register has to
    # read it as a refusal to proceed, not as an empty registry: an empty
    # registry answers *this node holds no pre-registration* about every
    # identity, while this says there is nowhere a hash could have been
    # recorded.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = create_app()
    assert member.COMPONENT_NAME in app  # registered
    assert app.get(member.COMPONENT_NAME) is None  # and resolved nothing


def test_an_absent_component_reads_as_none_rather_than_raising() -> None:
    # ``Application`` is a plain dataclass, so the absent case is constructible
    # without depending on a scan having failed — and the application answers
    # ``None`` rather than raising.
    assert Application().get(member.COMPONENT_NAME) is None


def test_reading_an_absent_component_composes_nothing() -> None:
    # Reading the component must not *create* one: a read that built a store
    # behind the caller's back would report a registry where the deployment
    # holds none — and would have opened a database the process never asked
    # for.
    empty = Application()
    assert empty.get(member.COMPONENT_NAME) is None
    assert empty.components == {}


def test_an_empty_workspace_composes_only_the_absent_store(tmp_path) -> None:
    # The same fact through the real factory: a composition whose scan
    # contributes nothing still builds, and the application still answers
    # ``None``.  Both halves of "contributed nothing" are needed — an empty
    # root *and* a fresh registry (the default registry is module-level and
    # persists across calls, so a second ``create_app`` would inherit the
    # first one's scan).
    empty = create_app(tmp_path, registry=Registration())
    assert empty.components == {}
    assert empty.get(member.COMPONENT_NAME) is None


@pytest.mark.parametrize(
    "absent",
    ["", "Promotion", "promotion-registry", "pre-register", "promotion_pre_register"],
)
def test_a_misspelled_component_key_is_absent_not_a_near_match(
    monkeypatch, tmp_path: Path, absent: str
) -> None:
    # The component key is exact.  The plausible misses are the capitalised
    # reading, the table's own name and the two spellings of the route — and
    # none may fuzzy-match, least of all into another member's hyphenated
    # names.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'keys.db'}")
    app = create_app()
    assert app.get(absent) is None
    assert member.COMPONENT_NAME in app
    assert app.get(member.COMPONENT_NAME) is not None

