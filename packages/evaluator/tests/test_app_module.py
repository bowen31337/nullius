"""The member's seat inside the ``app`` package namespace.

``src/app/modules/evaluator/__init__.py`` is where the composed evaluator
component is reachable from the ``app`` package without the app package
importing the member at module scope. The evaluator suite owns this file (it
is inside the feature's declared footprint), so the seat is tested here
rather than in a repository-level suite — and the member's own conftest
already reproduces the database isolation this needs.

The point of the seat is that composition stays the factory's job: this
module asks the factory for the component, and answers ``None`` — not an
exception — when there is none. That degradation is pinned below, since a
module that failed import because a member was absent would take the app
package down with it.
"""

from __future__ import annotations

import sys
from pathlib import Path

from app.module_loader import Application

_FACTORY_SRC = Path(__file__).resolve().parents[3] / "src"
if str(_FACTORY_SRC) not in sys.path:
    sys.path.insert(0, str(_FACTORY_SRC))


def test_the_seat_exposes_the_composed_evaluator_service(
    evaluator_env: dict[str, str],
) -> None:
    from app.modules.evaluator import COMPONENT_NAME, evaluator_component

    assert COMPONENT_NAME == "evaluator"
    service = evaluator_component()
    assert type(service).__name__ == "EvaluatorService"


def test_the_seat_reads_from_an_application_it_is_handed() -> None:
    from app.modules.evaluator import COMPONENT_NAME, evaluator_component

    application = Application(
        components={COMPONENT_NAME: "sentinel"}, order=(COMPONENT_NAME,)
    )
    assert evaluator_component(application) == "sentinel"


def test_an_absent_component_is_none_rather_than_an_error() -> None:
    from app.modules.evaluator import evaluator_component

    empty = Application(components={}, order=())
    assert evaluator_component(empty) is None


def test_the_seat_can_record_an_identity(evaluator_env: dict[str, str]) -> None:
    # Feature 70 from the app namespace: composed service, resolved identity,
    # persisted row — the path an assembled system takes.
    from app.modules.evaluator import evaluator_component

    service = evaluator_component()
    identity = service.record()
    assert len(identity.evaluator_hash) == 64
    assert service.recorded().evaluator_hash == identity.evaluator_hash


def test_the_seat_degrades_rather_than_raising_when_the_image_is_unset() -> None:
    # A service with no pinned image is still a composed component — the seat
    # must not turn the member's lazy refusal into an import-time failure.
    #
    # The refusal is pinned by *name* rather than by class, for the reason the
    # snapshot suite's component tests document: the loader imports this
    # member under a synthetic module name (``_nullius_scanned_evaluator``),
    # so the error class the composed component raises is a distinct object
    # from the ``evaluator`` package this suite also imports. ``isinstance``
    # across the two copies cannot hold.
    import pytest

    from app.modules.evaluator import evaluator_component

    service = evaluator_component()
    assert service is not None
    with pytest.raises(Exception, match="NULLIUS_EVALUATOR_IMAGE is not set") as raised:
        service.identity()
    assert type(raised.value).__name__ == "EvaluatorImageError"
