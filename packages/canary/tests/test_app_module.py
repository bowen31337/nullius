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
