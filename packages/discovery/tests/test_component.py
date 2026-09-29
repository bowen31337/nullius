"""The composition seam: feature 232's store as the loader composes it.

Feature 232's store is reached through the factory's scan, which composes it
under the member's registered name; a caller asks the composed application
``create_app().get("discovery")`` for it.  This file holds that wiring, the way
``packages/bootstrap/tests/test_pool_component.py`` holds its own.

**The loader's properties shape the composition half exactly.**  ``create_app``
imports each member under a synthetic module name (``_nullius_scanned_<name>``),
so the composed store's classes are *structurally* identical to a direct
import's but not the same objects: this suite pins class name, module suffix and
behaviour rather than ``isinstance``.  And the loader re-executes a package's
``__init__`` on every composition but not an already-cached submodule, so a
``@register`` in a submodule fires on the first ``create_app()`` of a process
and silently drops out of every later one — which is why the builder lives in
``__init__.py``, and why the second- and third-composition tests below exist at
all.

**The builder's own property: it degrades, and it writes nothing.**  The
discovery member has no world to compute and nothing to do at composition time;
what it has is a *deployment* — a database the campaign table lives in — and an
absent one composes ``None`` rather than raising, because a builder that raised
would take composition down for every unrelated feature in the workspace.
Where the world seats' composition is safe because it *computes* nothing, this
one must also be safe because it *writes* nothing: the test below holds the
database file absent after the composition and after reading the component, and
present only after a campaign is actually created — the composition seam being
where a store that helped itself to a database would be hardest to see.

**The composed ``None`` is about the deployment.**  ``Application()`` — no scan
at all — is the state where nothing was registered; a scanned application with
no ``DATABASE_URL`` is the state where the component was registered and
resolved no store.  A caller that must make feature 232's record has to refuse
to proceed on either, but the two are different facts and the tests keep them
apart by constructing each deliberately.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import discovery as member
import pytest

from app.module_loader import Application, Registration, create_app, scan_components


def _assert_is_the_campaign_store(component: object) -> None:
    """The composed component is the store, pinned across the loader's copies.

    Name, module suffix, then behaviour — the ladder the bootstrap member's
    component suites climb, because the loader's synthetic-name copies make
    ``isinstance`` unusable and behaviour is what matters anyway: the composed
    store carries the deployment's URL and answers the store's own questions.
    """
    assert type(component).__name__ == "CampaignRecords"
    assert type(component).__module__.endswith("discovery.campaign")
    for question in ("create", "get", "resolve"):
        assert callable(getattr(component, question)), question
    for fact in ("database_url", "path"):
        assert getattr(component, fact) is not None, fact


# -- The registration -------------------------------------------------------------


def test_the_member_registers_under_its_own_name() -> None:
    # One component, unprefixed — the ``ledger`` / ``artifacts`` / ``canary``
    # precedent for a member's first and only contribution.  The member and
    # the spec's plugin vocabulary both spell the one name.
    assert member.COMPONENT_NAME == "discovery"


def test_the_scanned_application_carries_the_store(monkeypatch, tmp_path: Path) -> None:
    # The factory scans the members, this package's ``@register`` fires, and
    # the composed application carries the store for the deployment the process
    # is running in — here, the database the test names.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'composed.db'}")
    app = create_app()
    assert member.COMPONENT_NAME in app
    assert member.COMPONENT_NAME in app.order
    _assert_is_the_campaign_store(app.get(member.COMPONENT_NAME))


def test_the_component_survives_a_second_composition(monkeypatch, tmp_path: Path) -> None:
    # The submodule-registration hazard, and the reason the builder lives in
    # ``__init__.py``: the loader caches imported submodules, so a ``@register``
    # in one fires on the first composition of a process and quietly drops out
    # of every later one.  Asserts on the second and third applications
    # specifically — a test that only looked at the first would pass wherever
    # the builder lived and would have caught nothing.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'composed.db'}")
    for app in (create_app(), create_app(), create_app()):
        _assert_is_the_campaign_store(app.get(member.COMPONENT_NAME))
        assert member.COMPONENT_NAME in app.order


def test_the_builder_degrades_to_none_without_a_database(monkeypatch) -> None:
    # An absent ``DATABASE_URL`` composes no store — a discoverable deployment
    # state, not an exception.  The *refusal* belongs to the caller that must
    # create a campaign and finds no store, not to the factory.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert create_app().get(member.COMPONENT_NAME) is None


def test_an_empty_database_url_counts_as_unset(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "   ")
    assert create_app().get(member.COMPONENT_NAME) is None


def test_the_builder_never_raises_and_takes_no_arguments() -> None:
    # The registration protocol passes nothing, and the factory builds every
    # component on every composition — this builder honours both, and resolves
    # the environment itself.
    assert list(inspect.signature(member.build_campaign_records).parameters) == []
    assert member.build_campaign_records() is None or isinstance(
        member.build_campaign_records(), member.CampaignRecords
    )


def test_a_url_the_builder_cannot_speak_is_not_raised_at_composition(monkeypatch) -> None:
    # Construction performs no I/O: the URL is translated (and a URL this
    # member cannot speak is refused by name) the first time an operation needs
    # the path.  So a misconfigured deployment composes a store that refuses
    # when it is used, rather than taking composition down for everyone.
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/nullius")
    app = create_app()
    store = app.get(member.COMPONENT_NAME)
    assert store is not None  # composed, not raised
    # The error *name* rather than the class: the composed store's classes are
    # the loader's synthetic-name copies, structurally identical to a direct
    # import's but not the same objects, so ``pytest.raises(<canonical>)``
    # cannot match them — the wrinkle ``tests/nulloracle/conftest.py``
    # documents, met the same way.
    with pytest.raises(Exception) as raised:
        store.create(member.TYPE_R_CAMPAIGN_TYPE, 12)
    assert type(raised.value).__name__ == "CampaignPlanningError"


def test_scanning_registers_the_component_exactly_once() -> None:
    # A duplicate registration of one name is silently overridden by whichever
    # import landed later, so it would be invisible at runtime and would make
    # the composed store depend on scan order.  Counted against a fresh
    # registry, so the assertion is about this member's contribution.
    registry = Registration()
    scan_components(registry=registry)
    named = [
        component
        for component in registry.components()
        if component.name == member.COMPONENT_NAME
    ]
    assert len(named) == 1
    # And "discovery" is this member's only registered name: an unprefixed
    # first component has no prefix family to count, so the check is that no
    # second name starts with it either.
    assert [
        component.name
        for component in registry.components()
        if component.name.startswith("discovery")
    ] == ["discovery"]


def test_the_name_sorts_between_the_neighbours_the_composed_order_holds(
    monkeypatch, tmp_path: Path
) -> None:
    # ``Application.order`` is name-sorted, and the nulloracle member's eleven
    # seats carry adjacency assertions about their own neighbourhoods.  An
    # unprefixed ``discovery`` lands between ``cost-model`` and
    # ``dispersion-metrics`` — both of them the first component of another
    # member, so nothing that reads a prefix family is disturbed — and this is
    # pinned against the *composed* order rather than against a guess at it,
    # so a later prefix decision has to be made deliberately instead of
    # sliding in between two names nobody checked.
    #
    # Deliberately *ordering* rather than exact adjacency: another member may
    # legitimately register a component in this window, and a test that
    # insisted on the two neighbours by name would fail for a sibling's
    # correct change.  What matters is that this name sorts clear of both
    # prefix families it could disturb — it must precede every
    # ``dispersion-*``/``feature-*`` seat that reads a database and follow the
    # ``cost-model`` seat — and that it carries no prefix at all.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'order.db'}")
    order = create_app().order
    assert order.index("cost-model") < order.index(member.COMPONENT_NAME)
    assert order.index(member.COMPONENT_NAME) < order.index("dispersion-metrics")
    assert not member.COMPONENT_NAME.startswith(
        ("nulloracle", "bootstrap", "sandbox", "tripwires")
    )


# -- On demand --------------------------------------------------------------------


def test_composing_writes_nothing_and_creating_is_on_demand(
    monkeypatch, tmp_path: Path, migrate_at
) -> None:
    # Feature 232's ordering held at the composition seam: an application
    # composed *for* a database-deployed process writes nothing into it, and
    # the row appears only when the planning call is made.  A composition that
    # helped itself to the database would create campaigns an operator never
    # planned.
    database = tmp_path / "on-demand.db"
    # The migration runs first, so the *only* thing that can write a campaign
    # row below is the store: the file's existence is the schema's doing, and
    # the count is the store's.
    migrate_at(f"sqlite:///{database}", "0111_campaign_table")
    before = _bytes_of(database)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database}")
    app = create_app()
    assert _bytes_of(database) == before  # composing wrote nothing
    store = app.get(member.COMPONENT_NAME)
    assert store is not None
    assert _bytes_of(database) == before  # asking for the component neither
    with _row_count(database) as count:
        assert count() == 0
        store.create(member.TYPE_R_CAMPAIGN_TYPE, 12)
        assert count() == 1  # the demand is what wrote


# -- The composed application -----------------------------------------------------


def test_the_composed_application_answers_the_store(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'seated.db'}")
    store = create_app().get(member.COMPONENT_NAME)
    assert store is not None
    assert type(store).__name__ == "CampaignRecords"
    assert store.database_url == f"sqlite:///{tmp_path / 'seated.db'}"


def test_a_deployment_without_a_database_composes_none(monkeypatch) -> None:
    # The composed ``None`` means the component ran and resolved no store —
    # a statement about the deployment.  A caller that must create a campaign
    # has to read it as a refusal to proceed, not as an empty store: an empty
    # store answers "never planned" about every id, while this says there is
    # nowhere a campaign could have been planned.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = create_app()
    assert member.COMPONENT_NAME in app  # registered
    assert app.get(member.COMPONENT_NAME) is None  # and resolved nothing


def test_an_absent_component_reads_as_none_rather_than_raising() -> None:
    # ``Application`` is a plain dataclass, so the absent case is constructible
    # without depending on a scan having failed — and the application answers
    # ``None`` rather than raising.
    assert Application().get(member.COMPONENT_NAME) is None


def test_an_empty_workspace_still_answers_only_the_absent_store(tmp_path) -> None:
    # The same fact through the real factory: a composition whose scan
    # contributes nothing still builds, and it still answers ``None``.
    # Both halves of "contributed nothing" are needed — an empty root *and* a
    # fresh registry (the default registry is module-level and persists across
    # calls, so a second ``create_app`` would inherit the first one's scan).
    empty = create_app(tmp_path, registry=Registration())
    assert empty.components == {}
    assert empty.get(member.COMPONENT_NAME) is None


@pytest.mark.parametrize("absent", ["", "Discovery", "discovery-store", "campaign"])
def test_a_misspelled_component_key_is_absent_not_a_near_match(
    monkeypatch, tmp_path: Path, absent: str
) -> None:
    # The component key is exact.  The plausible misses are the capitalised and
    # hyphenated readings of the name, which someone reaching for the store
    # from a report rather than the code would try — and none may fuzzy-match.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'keys.db'}")
    app = create_app()
    assert app.get(absent) is None
    assert member.COMPONENT_NAME in app
    assert app.get(member.COMPONENT_NAME) is not None


# -- helpers ----------------------------------------------------------------------


def _bytes_of(path: Path) -> bytes:
    """The database file's bytes — the instrument for "nothing was written".

    A count of the campaign rows would miss every other write a composition
    could make; comparing the file is the honest way to assert *nothing at
    all* happened, and it is read rather than modified so the comparison
    cannot itself perturb the store under test.
    """
    return path.read_bytes() if path.exists() else b""


class _row_count:
    """A ``COUNT(*)`` over the campaign table that can be asked repeatedly.

    Context-managed so the connection closes with the block, and re-queried
    rather than cached — the assertion being made is about *when* the row
    appears, so a cached count would be exactly the wrong instrument.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._connection = None

    def __enter__(self):
        import sqlite3
        from contextlib import closing

        self._closing = closing(sqlite3.connect(self._path))
        self._connection = self._closing.__enter__()
        return self._count

    def __exit__(self, *exc):
        return self._closing.__exit__(*exc)

    def _count(self) -> int:
        cursor = self._connection.execute("SELECT COUNT(*) FROM campaign")
        try:
            return int(cursor.fetchone()[0])
        finally:
            cursor.close()
