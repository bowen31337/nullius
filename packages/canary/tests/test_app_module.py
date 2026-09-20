"""The member's seat inside the ``app`` package namespace.

``src/app/modules/canary/__init__.py`` is where the composed canary
component is reachable from the ``app`` package without the app package
importing the member at module scope. The canary suite owns this file
(it is inside the feature's declared footprint), so the seat is tested
here rather than in a repository-level suite.

The point of the seat is that composition stays the factory's job: this
module asks the factory for the component, and answers ``None`` — not
an exception — when there is none. That degradation is pinned below,
since a module that failed import because a member was absent would
take the app package down with it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.module_loader import Application

_FACTORY_SRC = Path(__file__).resolve().parents[3] / "src"
if str(_FACTORY_SRC) not in sys.path:
    sys.path.insert(0, str(_FACTORY_SRC))


def test_the_seat_exposes_the_composed_canary_service(
    canary_env: dict[str, str],
) -> None:
    from app.modules.canary import COMPONENT_NAME, canary_component

    assert COMPONENT_NAME == "canary"
    service = canary_component()
    assert type(service).__name__ == "CanaryService"


def test_the_seat_reads_from_an_application_it_is_handed() -> None:
    from app.modules.canary import COMPONENT_NAME, canary_component

    application = Application(
        components={COMPONENT_NAME: "sentinel"}, order=(COMPONENT_NAME,)
    )
    assert canary_component(application) == "sentinel"


def test_an_absent_component_is_none_rather_than_an_error() -> None:
    from app.modules.canary import canary_component

    empty = Application(components={}, order=())
    assert canary_component(empty) is None


def test_the_seat_resolves_the_pinned_set(canary_env: dict[str, str]) -> None:
    # Feature 135 from the app namespace: composed service, swept
    # deployment, pinned evaluator — the path an assembled system
    # takes.
    from app.modules.canary import canary_component

    service = canary_component()
    assert service.containers["evaluator"].digest == "sha256:" + "ab" * 32


def test_the_seat_degrades_rather_than_raising_when_the_image_is_unset() -> None:
    # A service with no pinned environment is still a composed
    # component — the seat must not turn the member's lazy refusal into
    # an import-time failure.
    #
    # The refusal is pinned by *name* rather than by class, for the
    # reason the component tests document: the loader imports this
    # member under a synthetic module name (``_nullius_scanned_canary``),
    # so the error class the composed component raises is a distinct
    # object from the ``canary`` package this suite also imports.
    # ``isinstance`` across the two copies cannot hold.
    from app.modules.canary import canary_component

    service = canary_component()
    assert service is not None
    with pytest.raises(Exception, match="NULLIUS_EVALUATOR_IMAGE is not set") as raised:
        _ = service.containers
    assert type(raised.value).__name__ == "CanaryImageError"


def test_the_seat_refuses_a_tag_only_reference(
    canary_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # The feature's own clause, through the seat: a tag-only reference
    # is rejected, naming the role and the variable behind it.
    from app.modules.canary import canary_component

    monkeypatch.setenv("NULLIUS_EVALUATOR_IMAGE", "nullius-evaluator:latest")
    service = canary_component()
    with pytest.raises(Exception, match="not pinned by digest") as raised:
        _ = service.containers
    assert "NULLIUS_EVALUATOR_IMAGE" in str(raised.value)
    assert "the evaluator container" in str(raised.value)


# -- Feature 141: the reference-store seat --------------------------------------


def test_the_reference_store_seat_exposes_its_component_name() -> None:
    # The seat spells its own component name, so the three spellings — the
    # member's, the store's and the seat's — cannot drift apart silently.
    from app.modules.canary.reference_store import COMPONENT_NAME

    assert COMPONENT_NAME == "canary-reference-store"


def test_the_reference_store_seat_reads_from_an_application_it_is_handed() -> None:
    from app.modules.canary.reference_store import reference_store_component

    application = Application(
        components={"canary-reference-store": "sentinel"},
        order=("canary-reference-store",),
    )
    assert reference_store_component(application) == "sentinel"


def test_the_reference_store_seat_degrades_rather_than_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A deployment without a ``DATABASE_URL`` composes no store — degrade,
    # don't break — and the seat answers ``None`` rather than raising, exactly
    # as the pin-sweep seat does for an absent component.
    from app.modules.canary.reference_store import reference_store_component

    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert reference_store_component() is None


def test_the_reference_store_seat_reaches_the_composed_store(
    test_database_url: str,
) -> None:
    # Feature 141's store, through the seat: the composed store the factory
    # built, pointed at the deployment's database — the path a nightly runner
    # takes.
    from app.modules.canary.reference_store import reference_store_component

    store = reference_store_component()
    assert store is not None
    assert store.database_url == test_database_url


# -- Feature 143: the halt-store seat -------------------------------------------


def test_the_halt_store_seat_exposes_its_component_name() -> None:
    # The seat spells its own component name, so the three spellings — the
    # member's (:data:`canary.HALT_STORE_COMPONENT_NAME`), the seat's and the
    # one the factory composes under — cannot drift apart silently.
    from app.modules.canary.halt import COMPONENT_NAME

    assert COMPONENT_NAME == "canary-dream-halt"


def test_the_halt_store_seat_reads_from_an_application_it_is_handed() -> None:
    from app.modules.canary.halt import halt_store_component

    application = Application(
        components={"canary-dream-halt": "sentinel"},
        order=("canary-dream-halt",),
    )
    assert halt_store_component(application) == "sentinel"


def test_the_halt_store_seat_degrades_rather_than_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A deployment without a ``DATABASE_URL`` composes no halt store — degrade,
    # don't break — and the seat answers ``None`` rather than raising, exactly
    # as the reference-store seat does for the same deployment fact.
    from app.modules.canary.halt import halt_store_component

    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert halt_store_component() is None


def test_the_halt_store_seat_reaches_the_composed_store(
    test_database_url: str,
) -> None:
    # Feature 143's store, through the seat: the composed halt store the
    # factory built, pointed at the deployment's database — the store a
    # determinism break is halted to.
    from app.modules.canary.halt import halt_store_component

    store = halt_store_component()
    assert store is not None
    assert store.database_url == test_database_url


def test_the_halt_store_seat_is_a_third_module_beside_the_other_two() -> None:
    # Three components, three seats — and the older two keep exactly the
    # surfaces they promised: a third accessor crowded into either would be a
    # caller-visible change to a feature that already shipped.
    import app.modules.canary as pin_seat
    import app.modules.canary.halt as halt_seat
    import app.modules.canary.reference_store as reference_seat

    assert pin_seat.__all__ == ["COMPONENT_NAME", "canary_component"]
    assert reference_seat.__all__ == [
        "COMPONENT_NAME",
        "reference_store_component",
    ]
    assert halt_seat.__all__ == ["COMPONENT_NAME", "halt_store_component"]
    assert halt_seat.__name__ != reference_seat.__name__


def test_the_void_marker_seat_exposes_its_component_name() -> None:
    # The seat spells its own component name, so the three spellings — the
    # member's (:data:`canary.VOID_MARKER_COMPONENT_NAME`), the seat's and the
    # one the factory composes under — cannot drift apart silently.
    from app.modules.canary.void import COMPONENT_NAME

    assert COMPONENT_NAME == "canary-void-marker"


def test_the_void_marker_seat_reads_from_an_application_it_is_handed() -> None:
    from app.modules.canary.void import void_marker_component

    application = Application(
        components={"canary-void-marker": "sentinel"},
        order=("canary-void-marker",),
    )
    assert void_marker_component(application) == "sentinel"


def test_the_void_marker_seat_degrades_rather_than_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A deployment without a ``DATABASE_URL`` composes no void-marker store —
    # degrade, don't break — and the seat answers ``None`` rather than raising,
    # exactly as the other three seats do for the same deployment fact.
    from app.modules.canary.void import void_marker_component

    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert void_marker_component() is None


def test_the_void_marker_seat_reaches_the_composed_store(
    test_database_url: str,
) -> None:
    # Feature 144's store, through the seat: the composed void-marker store the
    # factory built, pointed at the deployment's database — the store every
    # score produced after a determinism break is marked in.
    from app.modules.canary.void import void_marker_component

    store = void_marker_component()
    assert store is not None
    assert store.database_url == test_database_url


def test_the_void_marker_seat_is_a_fourth_module_beside_the_other_three() -> None:
    # Four components, four seats — and the older three keep exactly the
    # surfaces they promised: a fourth accessor crowded into any of them would
    # be a caller-visible change to a feature that already shipped.
    import app.modules.canary as pin_seat
    import app.modules.canary.halt as halt_seat
    import app.modules.canary.reference_store as reference_seat
    import app.modules.canary.void as void_seat

    assert pin_seat.__all__ == ["COMPONENT_NAME", "canary_component"]
    assert reference_seat.__all__ == [
        "COMPONENT_NAME",
        "reference_store_component",
    ]
    assert halt_seat.__all__ == ["COMPONENT_NAME", "halt_store_component"]
    assert void_seat.__all__ == ["COMPONENT_NAME", "void_marker_component"]
    assert len(
        {
            pin_seat.__name__,
            reference_seat.__name__,
            halt_seat.__name__,
            void_seat.__name__,
        }
    ) == 4
