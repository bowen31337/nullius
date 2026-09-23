"""The member's seat in the ``app`` package namespace.

``src/app/modules/scoring/`` is where the app package reaches this
member, and the contract is deliberately thin: the seat answers exactly
one question — *what is the composed per-world objective?* — and nothing
else.  These tests hold it to that, from the side the member owns.

**Why ``None`` is not an error.**  A module that cannot reach its
component (the member was not scanned, the workspace is empty) returns
``None`` rather than failing import, mirroring the factory's own
"degrade, don't break" stance.  The distinction the seat's docstring
draws, and the one these tests pin, is sharper here than for the
store-bound members: this member's builder cannot fail and reads no
environment, so a ``None`` from this seat can only mean the *member
itself* was absent from the scan — a statement about composition, never
about the deployment.  Collapsing that with a store's "nothing named a
database" would send an operator hunting for a configuration variable
that does not exist.

**Why the seat must not re-export the member's surface.**  A caller
holding the objective calls it; a sibling feature of this category that
needs the value types (``WorldScore``, the error vocabulary) reaches the
member's own namespace, the way the policy-runtime member's free seams
are reached from theirs.  A second spelling of any of those in the seat
would be a second thing to keep in sync — and would defeat the reason
the seat exists, which is that the members that need the objective (the
replay engine's scoring step among them) reach it through the app package
without importing the member.  The ``__all__`` assertion in this file is
what keeps the seat from accreting one.
"""

from __future__ import annotations

import datetime as dt

import scoring as member

from app.module_loader import Application, create_app
from app.modules import scoring as seat

#: The seat's whole public surface.  Asserted as an exact set rather than
#: as a membership check, because the failure this guards against is the
#: seat *growing* a re-export, and a membership check cannot see that.
EXPECTED_EXPORTS = {"COMPONENT_NAME", "world_objective_component"}

#: A hand-computed panel (mean 1.5 over population std 0.5, ratio 3.0) —
#: the seat's question is composition, and one panel carries every
#: behaviour check through it.
_PANEL = {dt.date(2026, 1, 5): 1.0, dt.date(2026, 1, 6): 2.0}


def _fields(score: object) -> tuple[object, ...]:
    """A world score's fields, read duck-typed across the loader's copies."""
    return (score.world_id, score.node_id, score.ir_oos, score.score, score.epoch_id)  # type: ignore[attr-defined]


def test_the_module_names_line_up() -> None:
    # The seat's constant, the member's constant and the spec's plugin name
    # (``plugin="scoring"``) are one string.  Three spellings of one name
    # is exactly the kind of drift a test is cheaper than.
    assert seat.COMPONENT_NAME == member.COMPONENT_NAME == "scoring"


def test_the_seat_exposes_nothing_but_the_composition_accessor() -> None:
    # See the module docstring: the seat's job is to answer one question,
    # and every extra name is a second thing to keep in sync with the
    # member — as well as a way for a later feature to accidentally depend
    # on the seat for a value type it should reach through the member.
    assert set(seat.__all__) == EXPECTED_EXPORTS
    for name in EXPECTED_EXPORTS:
        assert hasattr(seat, name), name
    # And the member's own API is *not* among the exports — the specific
    # names a well-meaning re-export would add first.
    for leaked in (
        "WorldScore",
        "world_objective",
        "WorldObjectiveError",
        "ScoringError",
    ):
        assert leaked not in seat.__all__


def test_the_seat_returns_the_composed_objective() -> None:
    # The composition-level contract, checked by behaviour across the
    # loader's synthetic-name copy: the seat hands back a callable that
    # answers exactly what the member's own objective answers.
    objective = seat.world_objective_component()
    assert objective is not None
    assert callable(objective)
    answered = objective("financial-campaign-01", "node-a", _PANEL)
    direct = member.world_objective("financial-campaign-01", "node-a", _PANEL)
    assert _fields(answered) == _fields(direct)


def test_the_seat_reads_the_application_it_is_handed() -> None:
    # A caller that already holds an application must get *that*
    # application's component, not a freshly composed one — otherwise two
    # holders of one application could disagree about the objective.
    app = create_app()
    from_seat = seat.world_objective_component(app)
    from_app = app.get(seat.COMPONENT_NAME)
    assert from_seat is from_app


def test_the_seat_answers_none_when_the_component_is_absent() -> None:
    # An application composed without this member — here, one built
    # directly over an unrelated component — answers None, not an
    # exception: the "degrade, don't break" stance every seat takes.  And
    # because this member's builder cannot fail and reads no environment,
    # that None is a statement about composition alone; a caller that
    # finds it must refuse to score rather than hunt for a configuration
    # variable, since none exists to find.
    without = Application(components={"unrelated": object()}, order=("unrelated",))
    assert "scoring" not in without
    assert seat.world_objective_component(without) is None


def test_a_hand_computed_objective_crosses_the_seat() -> None:
    # One end-to-end pass through the seat on the law's own example: the
    # composed objective answers the hand-computed ratio (1.5/0.5 = 3.0),
    # with the score starting from the leading term.
    objective = seat.world_objective_component()
    if objective is None:  # pragma: no cover - the member is in this workspace
        raise AssertionError("the scoring member was not scanned into its own suite")
    score = objective("financial-campaign-01", "node-a", _PANEL)
    assert score.ir_oos == 3.0  # type: ignore[attr-defined]
    assert score.score == score.ir_oos  # type: ignore[attr-defined]
