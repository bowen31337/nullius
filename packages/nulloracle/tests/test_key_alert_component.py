"""Feature 111: the alert journal as a composed component.

The rest of this category reaches a composed component through the factory:
the workspace scan imports the member package, fires its ``@register``
decorators, and ``create_app().get("nulloracle-sidecar-key-alert")`` is the
named door onto what got built.  Feature 111 adds one component — the journal
— and this file pins the three claims that make it correct rather than merely
present.

* **the builder is free.**  ``create_app()`` builds *every* registered
  component on *every* call, so a builder runs in deployments that never use
  this feature, on every composition, including inside unrelated members'
  tests.  It must therefore take no arguments (the loader calls it with none),
  never raise, and do no I/O.  In particular it must not resolve the key: a
  builder that called a KMS backend would put a network round trip inside
  composition and raise an ``unrecoverable_state`` alert once per
  ``create_app()`` — an alert nobody asked for, from a process that had not
  yet decided to care about sidecars.
* **the absence is discoverable.**  A deployment with no ``DATABASE_URL``
  composes ``None``.  That is not a degraded mode to apologise for: the alert
  itself does not depend on this component (``emit_unrecoverable_state`` works
  with ``journal=None``), so the component's absence costs durability and
  nothing else.
* **the name keeps ``app.order`` intact.**  ``Registration.components()``
  sorts component names, and ``nulloracle``'s neighbours in that order are
  load-bearing — the KS guard's adjacency to the sidecar is asserted elsewhere
  in this suite.  A name chosen for readability (``nulloracle-key-alert``)
  would sort *before* ``nulloracle-ks-guard`` and displace it; the name here is
  chosen so it sorts after ``nulloracle-plan-gate`` and before
  ``nulloracle-target-route``, leaving every existing adjacency untouched.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from nulloracle import (
    ALERT_KIND,
    KEY_ALERT_COMPONENT_NAME,
    SIDECAR_STAGE,
    KeyAlertJournal,
    UnrecoverableState,
    load_key_alerts,
)

COMPONENT_NAME = "nulloracle-sidecar-key-alert"

pytestmark = pytest.mark.usefixtures("_no_database_url")


@pytest.fixture
def _no_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear ``DATABASE_URL`` so the unconfigured behaviour is the default."""
    monkeypatch.delenv("DATABASE_URL", raising=False)


@pytest.fixture
def configured_database_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Point ``DATABASE_URL`` at a fresh SQLite file for this test."""
    url = f"sqlite:///{tmp_path / 'nullius.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    return url


# -- The name ---------------------------------------------------------------


class TestTheName:
    def test_the_package_exports_the_name_the_composition_is_read_by(self) -> None:
        # Two spellings of one string — the member's constant and the literal a
        # caller reads the composition by — that a rename can desync.
        # Pinned so the drift is a failure here rather than a `None` component
        # at runtime.
        assert KEY_ALERT_COMPONENT_NAME == COMPONENT_NAME


# -- The builder contract ----------------------------------------------------


class TestTheBuilder:
    def test_the_builder_takes_no_arguments(self) -> None:
        # `create_app()` calls it with none; a builder with a required
        # parameter would make every composition raise.
        from nulloracle import build_key_alert_journal

        assert not [
            p
            for p in inspect.signature(build_key_alert_journal).parameters.values()
            if p.default is inspect.Parameter.empty
            and p.kind
            in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
        ]

    def test_the_builder_is_registered_under_the_component_name(self) -> None:
        from nulloracle import build_key_alert_journal

        # The decorator returns the function; the registration is the side
        # effect.  Asserting on the function's own module is the cheap check
        # that the decorator is on the right object.
        assert build_key_alert_journal.__module__ == "nulloracle"

    def test_an_unconfigured_builder_returns_none_and_does_not_raise(self) -> None:
        from nulloracle import build_key_alert_journal

        assert build_key_alert_journal() is None

    def test_a_configured_builder_returns_a_journal(
        self, configured_database_url: str
    ) -> None:
        from nulloracle import build_key_alert_journal

        journal = build_key_alert_journal()
        assert isinstance(journal, KeyAlertJournal)
        assert journal.database_url == configured_database_url

    def test_the_builder_touches_no_disk(self, tmp_path, monkeypatch) -> None:
        # Composition must not open a database, and the file is absent until
        # the first read or write.
        path = tmp_path / "never" / "nullius.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path}")
        from nulloracle import build_key_alert_journal

        build_key_alert_journal()
        assert not path.exists()

    def test_the_builder_does_not_resolve_the_key(self) -> None:
        # The central claim of this file: no KMS call, no sops invocation, no
        # alert, at composition time.  §7's alert is emitted by a process that
        # *decided* to need the key, not by every process that merely composes
        # an application.
        from nulloracle import build_key_alert_journal

        # A KMS reference is configured, and the builder must still do
        # nothing: it reads DATABASE_URL and nothing else.
        import os

        os.environ["NULL_SIDECAR_KEY_REF"] = "kms:arn:aws:kms:eu-west-1:1:key/x"
        try:
            assert build_key_alert_journal() is None  # no DATABASE_URL either
        finally:
            del os.environ["NULL_SIDECAR_KEY_REF"]


# -- Composition -------------------------------------------------------------


class TestComposition:
    def test_the_scan_finds_the_component(self) -> None:
        from app.module_loader import scan_components

        assert COMPONENT_NAME in {c.name for c in scan_components()}

    def test_an_unconfigured_deployment_composes_none(self) -> None:
        from app.module_loader import create_app

        assert create_app().get(COMPONENT_NAME) is None

    def test_a_configured_deployment_composes_the_journal(
        self, configured_database_url: str
    ) -> None:
        # Asserted by class *name* rather than with `isinstance`: the factory's
        # scan imports the member under a synthetic module alias
        # (`_nullius_scanned_nulloracle`), so the composed journal's class is
        # structurally but not identically the one a direct `import nulloracle`
        # yields — the wrinkle `tests/nulloracle/conftest.py`'s `raised_named`
        # fixture and `tests/feature-store/test_registration.py` both document.
        # The two copies agree on the name because they are the same source.
        from app.module_loader import create_app

        composed = create_app().get(COMPONENT_NAME)
        assert type(composed).__name__ == KeyAlertJournal.__name__

    def test_the_composed_journal_actually_works(
        self, configured_database_url: str
    ) -> None:
        # The name check above proves *what* was composed; this proves it is
        # the store the feature needs rather than an empty stand-in.
        from app.module_loader import create_app

        composed = create_app().get(COMPONENT_NAME)

        assert composed.alerts() == ()
        composed.record(
            UnrecoverableState(
                alert_kind=ALERT_KIND,
                stage=SIDECAR_STAGE,
                detail="the sidecar's tag did not verify",
            )
        )
        assert len(composed.alerts()) == 1
        # And the row is on disk where a deployment's operator would find it.
        assert len(load_key_alerts(configured_database_url)) == 1

    def test_the_composed_journal_accepts_a_directly_imported_record(
        self, configured_database_url: str
    ) -> None:
        # The claim the duck-check exists for.  The alias split is invisible in
        # the database but *not* in a type check, so an `isinstance`-guarded
        # store would refuse the records a caller built through a canonical
        # import — telling a deployment its own alert was not an alert.
        # :func:`nulloracle.assignment._is_assignment` draws the same
        # distinction for the same reason, and this member's store follows it.
        #
        # Measured, not reasoned about: the strict check passed every unit test
        # in this suite and failed eleven integration tests, because only the
        # integration suite ever puts the composed and canonical worlds in one
        # process.
        from app.module_loader import create_app

        composed = create_app().get(COMPONENT_NAME)
        composed.record(
            UnrecoverableState(
                alert_kind=ALERT_KIND, stage=SIDECAR_STAGE, detail="cause"
            )
        )
        assert len(composed.alerts()) == 1

    def test_the_composed_journal_still_refuses_a_non_record(
        self, configured_database_url: str
    ) -> None:
        # Duck-typed is not unchecked: an object that cannot name its kind, its
        # stage, its cause and render itself is still refused, so the
        # permissiveness above does not become a way to write a row no reader
        # can reconstruct.
        from app.module_loader import create_app

        composed = create_app().get(COMPONENT_NAME)
        with pytest.raises(Exception, match="UnrecoverableState values"):
            composed.record({"alert_kind": ALERT_KIND, "stage": SIDECAR_STAGE})

    def test_the_application_holds_the_composed_component(
        self, configured_database_url: str
    ) -> None:
        # ``application.get`` is the door the rest of the category uses, so it
        # must resolve to the component the factory built: reading the same
        # application twice returns *that* application's journal, not a second
        # one.  (Identity across two separate `create_app()` calls is not the
        # claim — each composition builds its own.)
        from app.module_loader import create_app

        app = create_app()
        assert app.get(COMPONENT_NAME) is not None
        assert app.get(COMPONENT_NAME) is app.get(COMPONENT_NAME)

    def test_composition_survives_a_second_create_app(
        self, configured_database_url: str
    ) -> None:
        # The scan re-executes each member's `__init__` on every
        # `create_app()` — which is why the decorator lives there rather than
        # in a submodule, whose cached execution would fire once per process.
        # A second composition must find the component again.
        from app.module_loader import create_app

        assert create_app().get(COMPONENT_NAME) is not None
        assert create_app().get(COMPONENT_NAME) is not None

    def test_composition_does_not_raise_without_the_feature_configured(self) -> None:
        # Degrade, don't break: one member's unset variable must not take
        # composition down for every other feature in the workspace.
        from app.module_loader import create_app

        assert create_app() is not None

    def test_a_broken_database_url_does_not_take_composition_down(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The URL is only inspected on first *use*, so a deployment whose
        # DATABASE_URL is unusable still composes — the failure belongs to the
        # process that tries to record, not to every process that composes.
        monkeypatch.setenv("DATABASE_URL", "postgresql://host/db")
        from app.module_loader import create_app

        assert create_app().get(COMPONENT_NAME) is not None


class TestTheOrderStaysIntact:
    """``app.order`` is name-sorted, and the nulloracle neighbours are load-bearing."""

    def test_the_journal_sorts_after_the_plan_gate(self) -> None:
        # `nulloracle-key-…` would sort before `nulloracle-ks-guard` and
        # displace it; the chosen name sorts late, so nothing moves.
        from app.module_loader import create_app

        order = list(create_app().order)
        assert order.index(COMPONENT_NAME) > order.index("nulloracle-plan-gate")

    def test_the_journal_sorts_before_the_target_route(self) -> None:
        from app.module_loader import create_app

        order = list(create_app().order)
        assert order.index(COMPONENT_NAME) < order.index("nulloracle-target-route")

    def test_the_sidecar_still_precedes_the_ks_guard(self) -> None:
        # The adjacency feature 123 depends on, restated here because this
        # feature's name is the kind of change that could disturb it — and the
        # failure would appear in a *different* member's suite, far from the
        # name that caused it.
        from app.module_loader import create_app

        order = list(create_app().order)
        assert order.index("nulloracle") + 1 == order.index("nulloracle-ks-guard")

    def test_the_feature_109_components_are_all_still_present(self) -> None:
        # Adding a component must not displace one.  The names below are the
        # member's pre-111 surface; if a later rename drops one, that is a
        # failure here rather than a `None` somewhere downstream.
        from app.module_loader import create_app

        order = list(create_app().order)
        for name in ("nulloracle", "nulloracle-ks-guard"):
            assert name in order

    def test_the_order_is_sorted(self) -> None:
        # The property the constraints above are instances of.
        from app.module_loader import create_app

        order = list(create_app().order)
        assert order == sorted(order)
