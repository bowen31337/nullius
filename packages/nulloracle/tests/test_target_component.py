"""Feature 112's seat inside the ``app`` package namespace.

``src/app/modules/nulloracle/target.py`` is where the composed POST
/target route is reachable from the ``app`` package without the app
package importing the member at module scope.  The member's suite owns
this file (it lives at ``src/app/modules/nulloracle/``, which the task's
file claim covers), so the seat is tested here rather than in a
repository-level suite — the same arrangement the resolution's, the
verdict's and the flip depth's seats state.

The point of the seat is that composition stays the factory's job: this
module asks the factory for the component, and answers ``None`` — not an
exception — when there is none.  That degradation is pinned below, since a
module that failed import because a member was absent would take the app
package down with it.  The seat is also deliberately accessors only: a
caller who has the endpoint reaches ``post`` on it, and a second spelling
here would be a second thing to keep in sync.

The composed half is pinned too: with a sidecar location and key named,
the factory's scan imports the member, its ``@register`` fires, and the
composed application carries a route over that same sidecar — the
arrangement §6.1's null_gate step asks through.  And the component name's
place in the name-sorted ``app.order`` is asserted, because feature 123's
guard is required to compose immediately after the sidecar and a
mis-sorted tenth name would silently break that adjacency.
"""

from __future__ import annotations

import pytest
from nulloracle import TARGET_COMPONENT_NAME, NullAssignment

from app.module_loader import Application


@pytest.fixture(autouse=True)
def _sidecar_environment_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test with the sidecar environment the member conftest clears.

    The member's own autouse fixtures already clear ``NULL_SIDECAR_PATH``,
    ``NULL_SIDECAR_KEY_REF`` and ``NULL_SIDECAR_SERVICE_ACCOUNT``; this
    fixture exists so the *reader* of this file sees that the unconfigured
    tests below start from a deployment that names nothing, without having
    to look two files over.
    """
    for name in (
        "NULL_SIDECAR_PATH",
        "NULL_SIDECAR_KEY_REF",
        "NULL_SIDECAR_SERVICE_ACCOUNT",
    ):
        monkeypatch.delenv(name, raising=False)


class _Ask:
    """A minimal ask for the composed route.

    The composed endpoint was imported by the scan under an alias module,
    so its ``TargetRequest`` is not the class a direct import yields; the
    route reads its request duck-typed (validating the identity by value),
    and this stand-in pins that the composed component answers one.

    It carries the ``symbols`` term too, because feature 113's payload must
    answer the cross-section the ask named: the seat test below drives a
    *real* node through the route, and a real node's series is served
    unchanged — so the ask has to state what it asked for.
    """

    def __init__(self, node_id: str, symbols: tuple[str, ...] = ("BTCUSDT",)) -> None:
        self.node_id = node_id
        self.symbols = symbols


def _targets(request) -> dict:
    """The real-return series the composed route is given, per ask.

    Two bars over the ask's own cross-section, with values that differ between
    them — so a test can tell a permuted series from the real one by reading
    the values rather than by comparing insertion orders, which a mapping does
    not carry.
    """
    import datetime as dt

    symbols = getattr(request, "symbols", ("BTCUSDT",))
    return {
        dt.date(2026, 1, 5): {
            symbol: 0.01 * (index + 1)
            for index, symbol in enumerate(symbols)
        },
        dt.date(2026, 1, 6): {
            symbol: 0.05 * (index + 1)
            for index, symbol in enumerate(symbols)
        },
    }


def test_the_component_name_matches_the_member() -> None:
    # Spelled twice on purpose — once in the member, once in the seat — so
    # the two cannot drift apart silently.
    import nulloracle

    assert (
        TARGET_COMPONENT_NAME
        == nulloracle.TARGET_COMPONENT_NAME
        == "nulloracle-target-route"
    )


def test_the_seat_reads_from_an_application_it_is_handed() -> None:
    from app.modules.nulloracle.target import target_route_component

    application = Application(
        components={TARGET_COMPONENT_NAME: "sentinel"},
        order=(TARGET_COMPONENT_NAME,),
    )
    assert target_route_component(application) == "sentinel"


def test_an_absent_component_is_none_rather_than_an_error() -> None:
    from app.modules.nulloracle.target import target_route_component

    empty = Application(components={}, order=())
    assert target_route_component(empty) is None


def test_an_unconfigured_environment_yields_none_not_an_exception() -> None:
    from app.modules.nulloracle.target import target_route_component

    assert target_route_component() is None


def test_a_configured_environment_composes_the_route(
    sidecar_path, key_ref: str, node_id: str
) -> None:
    # The factory's scan imports the member, the ``@register`` builder
    # fires, and the composed application carries a route over the sidecar
    # the deployment named — no registry, router or factory edit involved.
    from app.modules.nulloracle.target import target_route_component

    component = target_route_component()
    assert type(component).__name__ == "TargetEndpoint"
    assert component.sidecar.path == sidecar_path

    # And the composed route answers over the composed sidecar: the two
    # components resolve from one environment, so they can never point at
    # two worlds.  The node below is *real*, so the route serves the series
    # unchanged and the component's own wired permutation is never reached —
    # which is what a composition with no step-4 supply can still serve.
    from app.module_loader import create_app

    application = create_app()
    sidecar = application.get("nulloracle")
    route = application.get(TARGET_COMPONENT_NAME)
    # The series half of feature 113 is pipeline step 4's supply, and it is
    # not something the member resolves from an environment variable; the
    # composed component therefore carries none, and the test attaches one
    # the way a deployment would — alongside the component the factory built,
    # over the same sidecar.
    #
    # ``route._permute`` is asserted present above and is set on the instance
    # rather than passed here on purpose: a route carrying ``targets`` but no
    # ``permute`` refuses *both* branches (a missing supply that only the null
    # branch tripped over would be a branch oracle), so rebuilding the
    # endpoint without the builder's permutation would test the refusal
    # instead of the answer this test is about.
    route._targets = _targets
    sidecar.write([NullAssignment(node_id=node_id, is_null=False, perm_seed=0)])
    response = route.post(_Ask(node_id))
    assert response.status == 200
    assert response.known is True
    assert response.charges_budget is True
    assert set(next(iter(response.target_series.values()))) == {"BTCUSDT"}


def test_the_composed_routes_own_permutation_moves_rows_across_dates(
    sidecar_path, key_ref: str, node_id: str
) -> None:
    # The seam ``build_target_route`` wires itself — feature 115's mechanism,
    # reconciled with the panel's grain — is the one piece of feature 113 that
    # no other test reaches, because the *builder* composes it and the tests
    # above attach their own seams instead.  It is also the piece with the
    # failure mode this suite exists to catch: a gather that carries each date
    # together with its own row rebuilds the identical mapping, and mapping
    # equality ignores insertion order, so every other assertion here would
    # pass while the null branch served the real series.
    #
    # So this test drives a *null* node through the route the factory built,
    # attaching only the series supply (step 4's, which is not this member's
    # to resolve) and leaving the permutation to the builder.
    # The application is composed here once and handed to the seat, so the
    # route and the sidecar below are read from one composition rather than
    # two — ``target_route_component`` builds its own when given none.
    from app.module_loader import create_app
    from app.modules.nulloracle.target import target_route_component

    application = create_app()
    route = target_route_component(application)
    sidecar = application.get("nulloracle")
    assert route is application.get(TARGET_COMPONENT_NAME)

    # The builder's own wiring, asserted before it is used: the composed route
    # carries a permutation without anyone having supplied one.
    assert route._permute is not None

    # Only the *series* supply is attached — pipeline step 4's, which is not
    # this member's to resolve from an environment variable, and which is what
    # ``build_target_route``'s docstring says the caller supplies on the
    # constructor.  Attaching it here rather than rebuilding the endpoint
    # keeps the builder's permutation in place: a fresh
    # ``type(route)(route.sidecar, targets=...)`` would drop it and the test
    # would be exercising its own seams again.
    route._targets = _targets

    # Two bars, so the fixture's series is small enough to reason about, and a
    # seed whose one-observation blocks genuinely swap them.  Asserted here as
    # a property of the *fixture* rather than of the route: if a future change
    # to feature 115's shuffle made this seed an identity permutation, the
    # test would fail here — naming the fixture — instead of three assertions
    # later, blaming the route.
    from nulloracle import block_indices

    asserted_seed, asserted_block = 1, 1
    order = block_indices(range(2), seed=asserted_seed, block_days=asserted_block)
    assert tuple(order) != (0, 1)

    sidecar.write(
        [
            NullAssignment(
                node_id=node_id,
                is_null=True,
                perm_seed=asserted_seed,
                block_days=asserted_block,
            )
        ]
    )
    response = route.post(_Ask(node_id, symbols=("BTCUSDT", "ETHUSDT")))

    assert response.status == 200
    assert response.charges_budget is False
    served = response.target_series
    real = _targets(_Ask(node_id, symbols=("BTCUSDT", "ETHUSDT")))
    assert served is not None
    # The grid is intact — the same two dates, and no others — and the rows
    # have moved across it, which is the whole of §7.3's displacement.  The
    # multiset of values is preserved (a permutation moves observations, it
    # never invents one) and at least one date now carries the other's row.
    assert set(served) == set(real)
    assert sorted(
        value for row in served.values() for value in row.values()
    ) == sorted(value for row in real.values() for value in row.values())
    assert any(served[day] != real[day] for day in served)
    # Stated the way a reader would check it: the null answer is not the real
    # series.  A closure that gathered each date together with its own row
    # would rebuild ``real`` exactly, and — since mapping equality ignores
    # insertion order — would satisfy every assertion above except this one.
    assert served != real


def test_composing_the_route_creates_no_sidecar_file(
    sidecar_path, key_ref: str
) -> None:
    # The factory builds every registered component on every
    # ``create_app()`` call, so a builder that opened the sidecar would
    # open it for every composition of every application in the process.
    # The endpoint holds its sidecar lazily; asking for the component
    # touches no file.
    from app.modules.nulloracle.target import target_route_component

    component = target_route_component()
    assert component is not None
    assert not sidecar_path.exists()


def test_the_builder_is_registered_beside_the_members_other_components() -> None:
    # The member contributes seven components now — the sidecar, the
    # guard, the verdict, the fraction, the flip depth, the resolution and
    # this route — and the scan discovers them all by name,
    # deterministically, on every scan.
    from app.module_loader import scan_components

    names = [component.name for component in scan_components()]
    assert TARGET_COMPONENT_NAME in names


def test_the_guard_still_composes_immediately_after_the_sidecar(
    sidecar_path, key_ref: str
) -> None:
    # ``app.order`` is name-sorted, and feature 123's guard is required to
    # land immediately after the sidecar.  The route's ``target-`` prefix
    # sorts after every ``ks-*`` and ``null-*`` name, so the tenth
    # component changes nothing about that adjacency — asserted here so a
    # future eleventh name cannot break it silently either.
    from app.module_loader import create_app

    order = create_app().order
    assert order.index("nulloracle") + 1 == order.index("nulloracle-ks-guard")


def test_the_seat_is_a_composition_read_and_not_a_second_api() -> None:
    # The seat is deliberately accessors only: a caller who has the route
    # reaches post on it, and a second spelling here would be a second
    # thing to keep in sync.
    import app.modules.nulloracle.target as seat

    assert set(seat.__all__) == {"COMPONENT_NAME", "target_route_component"}
