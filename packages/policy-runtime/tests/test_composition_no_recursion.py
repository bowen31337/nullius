"""Bug fix: create_app() must never recurse through build_campaign_tree.

``build_campaign_tree`` used to resolve its tree by composing the
application again (``create_app().get("artifacts")``), and since the factory
builds every registered component on every ``create_app()`` call, that
nested call rebuilt ``build_campaign_tree`` too — which composed the
application again, and so on until ``RecursionError``, silently swallowed
into ``None``.  Each level also paid for every *other* registered builder,
so a live evaluator configured onto the composition
(``NULLIUS_EVALUATION_CONFIG``) multiplied its own cost once per recursion
level — the 30+ minute smoke-campaign hang and the segfaulting
``create_app()`` probe this bug report is written against.

These tests pin the fix: the builder reaches the artifacts component through
the same registry :func:`app.module_loader.create_app` itself reads from
(:func:`app.module_loader.registered_components`), calling that one
registered builder directly rather than composing the application — so
``create_app`` is never re-entered from inside this builder, and a sibling
builder's cost is never paid twice.  They also pin the lazy carrier the fix
returns for a deployment whose store *does* name a committed campaign: the
per-node payload reads stay deferred to the first time a caller actually
reaches through it, so composing an application with a real campaign still
performs only the cheap presence check during ``create_app()``.

Isolated by construction, so these tests are safe under pytest-xdist: each
test either calls ``build_campaign_tree()`` directly or composes its own
:class:`~app.module_loader.Registration` over an empty temporary directory
(never the real workspace, so a test never contends with another worker's
scan), and monkeypatches the module-level lookups the builder reads from —
the same seam ``packages/replay/tests/test_component.py`` patches
``create_app`` through.  No module-level state survives a test, and no test
depends on another having run first.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from policy_runtime import CAMPAIGN_TREE_COMPONENT, CampaignTree, build_campaign_tree

import app.module_loader as loader


class _StubStore:
    """A minimal duck-typed artifact store: no committed campaign at all."""

    def campaign_ids(self) -> tuple[str, ...]:
        return ()


class _CountingStore:
    """Wraps a real store, counting the calls the lazy read actually makes.

    The spy that proves "resolves on first use": ``campaign_ids`` is the one
    call :func:`policy_runtime._resolve_tree` makes eagerly (the cheap
    presence check this bug's fix performs during composition), while
    ``node_ids``/``read`` are the per-node reads the lazy carrier must defer
    to first use.
    """

    def __init__(self, store: object) -> None:
        self._store = store
        self.campaign_ids_calls = 0
        self.node_ids_calls = 0
        self.read_calls = 0

    def campaign_ids(self) -> tuple[str, ...]:
        self.campaign_ids_calls += 1
        return self._store.campaign_ids()

    def node_ids(self, campaign_id: str) -> tuple[str, ...]:
        self.node_ids_calls += 1
        return self._store.node_ids(campaign_id)

    def files(self, campaign_id: str, node_id: str) -> tuple[str, ...]:
        return self._store.files(campaign_id, node_id)

    def read(self, campaign_id: str, node_id: str, filename: str) -> bytes:
        self.read_calls += 1
        return self._store.read(campaign_id, node_id, filename)


def _patch_registered_components(monkeypatch: pytest.MonkeyPatch, components: list) -> None:
    """Make ``build_campaign_tree`` see exactly ``components`` and nothing else.

    ``_resolve_tree`` imports ``registered_components``/``scan_components``
    from :mod:`app.module_loader` at call time (the same import-inside-the-
    function seam ``replay.resolve_tree`` takes for ``create_app``), so
    patching the loader's attributes substitutes what the builder reads
    without touching the real, process-wide registry.  ``scan_components`` is
    patched to fail the test if it is ever reached: these tests always hand
    the component in up front, so a scan would mean the cheap registry lookup
    did not find it — a regression, not the common path.
    """
    monkeypatch.setattr(loader, "registered_components", lambda *a, **k: list(components))

    def _scan_must_not_be_needed(*args: object, **kwargs: object) -> None:
        raise AssertionError(
            "scan_components() was called even though the registry already "
            "named 'artifacts' -- the cheap lookup should have found it "
            "without a scan"
        )

    monkeypatch.setattr(loader, "scan_components", _scan_must_not_be_needed)


# ---------------------------------------------------------------------------
# No store / no campaign -- the documented absent answer
# ---------------------------------------------------------------------------


def test_no_artifacts_component_gives_the_documented_absent_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The registry names no "artifacts" component at all -- the same fact as
    # a deployment where the artifacts member was never scanned.  The old
    # recursive body reached this exact case through `create_app().get(...)`
    # answering `None`; the registry lookup must answer the same way.
    monkeypatch.setattr(loader, "registered_components", lambda *a, **k: [])
    monkeypatch.setattr(loader, "scan_components", lambda *a, **k: None)

    assert build_campaign_tree() is None


def test_a_store_with_no_committed_campaign_gives_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    component = loader.Component("artifacts", _StubStore)
    _patch_registered_components(monkeypatch, [component])

    assert build_campaign_tree() is None


def test_an_artifacts_builder_that_answers_none_gives_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # "artifacts" is registered but its own builder answers no store (the
    # artifacts member's own degrade-don't-break stance) -- the
    # policy-runtime builder must pass that through rather than crashing on a
    # None store.
    component = loader.Component("artifacts", lambda: None)
    _patch_registered_components(monkeypatch, [component])

    assert build_campaign_tree() is None


# ---------------------------------------------------------------------------
# The lazy carrier -- resolves a tmp artifact store's committed tree, once,
# on first use
# ---------------------------------------------------------------------------


def test_the_lazy_carrier_resolves_a_tmp_stores_tree_on_first_use(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    artifacts = pytest.importorskip("artifacts")

    real_store = artifacts.ArtifactStore(tmp_path)
    real_store.write("c1", "root", "node.json", '{"parent_id": null, "depth": 0}')
    real_store.commit("c1", "root")

    spy = _CountingStore(real_store)
    component = loader.Component("artifacts", lambda: spy)
    _patch_registered_components(monkeypatch, [component])

    result = build_campaign_tree()

    # Construction performed the cheap presence check and nothing else: it
    # found a committed campaign, so this is not the documented absence...
    assert result is not None
    # ...but it is not a resolved CampaignTree either -- reading the node's
    # payload has not happened yet.
    assert not isinstance(result, CampaignTree)
    assert spy.campaign_ids_calls == 1
    assert spy.node_ids_calls == 0
    assert spy.read_calls == 0

    # First use: any attribute a replay or a question would read resolves the
    # tree, exactly once, from the store handed to the carrier.
    nodes = result.nodes
    assert spy.read_calls == 1
    assert [node.node_id for node in nodes] == ["root"]
    assert result.node("root").depth == 0

    # A second access answers from the cached resolution -- no second read.
    _ = result.nodes
    assert spy.read_calls == 1


# ---------------------------------------------------------------------------
# No recursion: create_app() is never re-entered, and a sibling builder's
# cost is never paid twice
# ---------------------------------------------------------------------------


def test_build_campaign_tree_never_calls_create_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[None] = []
    monkeypatch.setattr(loader, "create_app", lambda *a, **k: calls.append(None))
    component = loader.Component("artifacts", _StubStore)
    _patch_registered_components(monkeypatch, [component])

    build_campaign_tree()

    assert calls == []


def test_one_composition_calls_create_app_exactly_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    registry = loader.Registration()
    registry.add(loader.Component("artifacts", _StubStore))
    registry.add(loader.Component(CAMPAIGN_TREE_COMPONENT, build_campaign_tree))

    # The builder loop reads from this isolated registry; patch the
    # module-level lookup too, so build_campaign_tree sees exactly the
    # "artifacts" component this test registered -- never the real
    # workspace's, and never by scanning (the registry already names it).
    monkeypatch.setattr(loader, "registered_components", lambda *a, **k: registry.components())

    real_create_app = loader.create_app
    calls: list[None] = []

    def counting_create_app(*args: object, **kwargs: object) -> object:
        calls.append(None)
        return real_create_app(*args, **kwargs)

    monkeypatch.setattr(loader, "create_app", counting_create_app)

    empty_root = tmp_path / "empty"
    empty_root.mkdir()

    app = loader.create_app(empty_root, registry=registry)

    # Exactly the one call this test made itself -- build_campaign_tree never
    # re-entered create_app from inside the composition it is part of.
    assert len(calls) == 1
    assert app.get(CAMPAIGN_TREE_COMPONENT) is None


def test_composition_completes_with_a_sleeping_stub_evaluator_exactly_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The actual symptom this bug report describes: a slow sibling builder
    # (orchestrator's live evaluator, stood in here by a builder that
    # sleeps) must run exactly once per composition.  The old recursive body
    # paid for it once per recursion level -- hundreds of times before
    # RecursionError finally cut it off -- which is what hung a real
    # campaign for 30+ minutes.
    sleep_seconds = 0.2

    registry = loader.Registration()
    registry.add(loader.Component("artifacts", _StubStore))
    registry.add(loader.Component(CAMPAIGN_TREE_COMPONENT, build_campaign_tree))

    sleep_calls: list[None] = []

    def build_slow_sibling() -> str:
        sleep_calls.append(None)
        time.sleep(sleep_seconds)
        return "evaluated"

    registry.add(loader.Component("zzz-slow-sibling", build_slow_sibling))

    monkeypatch.setattr(loader, "registered_components", lambda *a, **k: registry.components())

    empty_root = tmp_path / "empty"
    empty_root.mkdir()

    started = time.perf_counter()
    app = loader.create_app(empty_root, registry=registry)
    elapsed = time.perf_counter() - started

    # One sleep, not one per recursion level: the old body would have paid
    # for this builder again on every nested create_app() call until
    # RecursionError, so a bare 2x headroom over one sleep is already a
    # wide margin against any reintroduced recursion.
    assert len(sleep_calls) == 1
    assert elapsed < sleep_seconds * 4
    assert app.get("zzz-slow-sibling") == "evaluated"
    assert app.get(CAMPAIGN_TREE_COMPONENT) is None
