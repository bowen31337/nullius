"""The member's seat inside the ``app`` package namespace.

``src/app/modules/universe/__init__.py`` is where the composed universe
component is reachable from the ``app`` package without the app package
importing the member at module scope. The universe suite owns this file (it
is inside the feature's declared footprint, alongside the seat itself), so
the seat is tested here rather than in a repository-level suite — the
repository-level ``tests/`` conftest does not reach package-local tests,
and the member's own conftest already reproduces the database isolation
this needs.

The point of the seat is that composition stays the factory's job: this
module asks the factory for the component, and answers ``None`` — not an
exception — when there is none. That degradation is pinned below, since a
module that failed import because a member was absent would take the app
package down with it.

The feature-44 path is pinned here too, one level up: the survivorship
audit report is *emitted by the composed system*, so the end-to-end reads
it through the seat — composed application, universe service, report lines
with the window bounds and the delisted-symbol count — rather than through
a directly imported service. That is the whole reason the seat exists.

The feature-45 path is pinned the same way: the survivorship gate rides
the composed service's own persist path, so the end-to-end composes the
application and is *refused* by it when the build's window is known to
contain a delisting yet would count ``delisted=0`` — and accepted once the
delisted name's history lands. The rejection crosses the scan seam, so it
is asserted as a ``ValueError`` carrying the gate's message, not as the
directly imported exception class (the loader imports scanned packages
under their own mangled names; the scanned copy's exception is a sibling
of the imported one, exactly as its service class is).
"""

from __future__ import annotations

import datetime as dt

import pytest

from app.module_loader import Application

from universe import DailyBar, PriceBar, UniverseConfig

APRIL_1 = dt.date(2026, 4, 1)


def _two_symbol_april() -> list[DailyBar]:
    # April's trailing window is March 2–31; BBB (100) outranks AAA (50) there,
    # so top_n=1 admits BBB.
    march_2 = dt.date(2026, 3, 2)
    return [
        DailyBar("BBBUSDT", march_2 + dt.timedelta(days=offset), 100.0)
        for offset in range(30)
    ] + [
        DailyBar("AAAUSDT", march_2 + dt.timedelta(days=offset), 50.0)
        for offset in range(30)
    ]


def _two_symbol_may() -> list[DailyBar]:
    # May's trailing window is April 1–30; AAA (100) now outranks BBB (50), so
    # BBB's membership interval closes on May 1 — the delisting.
    return [
        DailyBar("AAAUSDT", APRIL_1 + dt.timedelta(days=offset), 100.0)
        for offset in range(30)
    ] + [
        DailyBar("BBBUSDT", APRIL_1 + dt.timedelta(days=offset), 50.0)
        for offset in range(30)
    ]


def test_the_seat_exposes_the_composed_universe_service(test_database_url: str) -> None:
    from app.modules.universe import COMPONENT_NAME, universe_component

    assert COMPONENT_NAME == "universe"
    service = universe_component()
    # The loader imports scanned packages under its own mangled module name,
    # so the composed service is the scanned copy's class — assert on the
    # observable contract, not on cross-copy isinstance.
    assert type(service).__qualname__ == "UniverseService"
    # Field-by-field, like the composition tests: the scanned copy's
    # UniverseConfig is a sibling class, so dataclass == cannot cross the
    # scan seam — the values are the assertion, not the identity.
    assert service.config.top_n == 100
    assert service.config.window_days == 30
    assert service.config.min_observations == 1
    assert service.config.min_dollar_volume == 0.0
    assert service.database_url == test_database_url


def test_the_seat_reads_from_an_application_it_is_handed() -> None:
    from app.modules.universe import COMPONENT_NAME, universe_component

    application = Application(
        components={COMPONENT_NAME: "sentinel"}, order=(COMPONENT_NAME,)
    )
    assert universe_component(application) == "sentinel"


def test_an_absent_component_is_none_rather_than_an_error() -> None:
    from app.modules.universe import universe_component

    empty = Application(components={}, order=())
    assert universe_component(empty) is None


def test_the_seat_emits_the_survivorship_report(test_database_url: str) -> None:
    # The feature-44 flow through the app namespace: compose the application,
    # ask the seat for the universe service, and read the audit the system
    # emits — one line per window, bounds and delisted count on every line.
    from app.modules.universe import universe_component

    service = universe_component()
    # top_n=1 per build (passed explicitly — the composed service carries the
    # spec defaults, and mutating a composed component is not ours to do):
    # BBB wins April, loses May, and its interval closes — the delisting.
    top_one = UniverseConfig(top_n=1)
    service.persist(service.build(_two_symbol_april(), "2026-04", config=top_one))
    service.persist(service.build(_two_symbol_may(), "2026-05", config=top_one))
    # BBB's retained April closes put the delisted name inside May's window.
    service.ingest_prices(
        [PriceBar("BBBUSDT", APRIL_1 + dt.timedelta(days=offset), 20.0) for offset in range(30)]
    )

    (april, may) = service.render_survivorship_report()
    # April's window (March 2–31) predates every retained bar: no delisted
    # name can be present, so the clean period reports zero.
    assert april == "2026-04 [2026-03-02, 2026-03-31] delisted=0"
    # May's window covers BBB's retained closes after the universe dropped
    # it: the period known to contain a delisting reports it, by name.
    assert may == "2026-05 [2026-04-01, 2026-04-30] delisted=1: BBBUSDT"


def test_the_seat_rejects_a_build_on_pruned_history(test_database_url: str) -> None:
    # The feature-45 flow through the app namespace: the composed service's
    # own persist path refuses a build whose window is known to contain a
    # delisting but would count delisted=0 — the survivor's April closes
    # are in the history and the delisted name's are not — and nothing
    # lands until the missing history does.
    from app.modules.universe import universe_component

    service = universe_component()
    top_one = UniverseConfig(top_n=1)
    service.persist(service.build(_two_symbol_april(), "2026-04", config=top_one))
    service.ingest_prices(
        [PriceBar("AAAUSDT", APRIL_1 + dt.timedelta(days=offset), 10.0) for offset in range(30)]
    )

    with pytest.raises(ValueError, match="universe build rejected.*BBBUSDT"):
        service.persist(service.build(_two_symbol_may(), "2026-05", config=top_one))
    assert service.load("2026-05") is None

    # The delisted name's history lands, and the same build is accepted —
    # the report now counts the name the gate defended.
    service.ingest_prices(
        [PriceBar("BBBUSDT", APRIL_1 + dt.timedelta(days=offset), 20.0) for offset in range(30)]
    )
    service.persist(service.build(_two_symbol_may(), "2026-05", config=top_one))
    (_april, may) = service.render_survivorship_report()
    assert may == "2026-05 [2026-04-01, 2026-04-30] delisted=1: BBBUSDT"
