"""The member's seat in the ``app`` package namespace.

``src/app/modules/bootstrap/`` is where the app package reaches this
member, and the contract is deliberately thin: the seat answers exactly
one question — *what is the composed bootstrap world?* — and nothing else.
These tests hold it to that, from the side the member owns.

**Why ``None`` is not an error.**  A module that cannot reach its
component (the member was not scanned, the workspace is empty) returns
``None`` rather than failing import, mirroring the factory's own
"degrade, don't break" stance.  The distinction the member's seat
docstring draws, and the one these tests pin, is that an absent
*component* is a statement about composition, while an empty bootstrap
*pool* is a statement about what has been authored (feature 188's count,
feature 186's independent tally).  §10.6's *"Report the two pools
separately"* is the rule that keeps them apart, and collapsing the two
would make a deployment problem look like a coverage result.

**Why the seat must not re-export the world's API.**  A caller holding
the world reaches ``world.label(node_id)`` for feature 181's ground-truth
score, ``world.legal_moves(node_id)`` for §10.6.1's ``question.legal_
actions``, ``world.canonical_node()`` for ``legal_roots``, and
``world.setting(node_id)`` for a ``CellMeta``'s coordinates.  A second
spelling of any of those in the seat would be a second thing to keep in
sync — and would defeat the reason the seat exists, which is that the
later features of this category (184's identical policy interface, 189's
ground-truth calibration, 190-191's ported-world adapter) can ask for the
world *without importing the member*.  The ``__all__`` assertion in this
file is what keeps the seat from accreting one.

**Why the seat imports the member lazily.**  The app package must not
depend on any workspace member at import time — that is what keeps a
missing or broken member from taking the application down — so the world
type appears only under ``TYPE_CHECKING``.  The consequence for this
suite is that the seat's return value must be checked by *behaviour*
rather than by ``isinstance``, which is the same discipline
``test_component.py`` states for the loader's synthetic-name copies.
"""

from __future__ import annotations

import bootstrap as member
import pytest

from app.module_loader import Application, Registration, create_app
from app.modules import bootstrap as seat

#: The seat's whole public surface.  Asserted as an exact set rather than
#: as a membership check, because the failure this guards against is the
#: seat *growing* a re-export, and a membership check cannot see that.
EXPECTED_EXPORTS = {"COMPONENT_NAME", "hyperparameter_world_component"}


def test_the_module_names_line_up() -> None:
    # The seat's constant, the member's constant and the spec's plugin name
    # (``plugin="bootstrap"``) are one string.  Three spellings of one name
    # is exactly the kind of drift a test is cheaper than.
    assert seat.COMPONENT_NAME == member.COMPONENT_NAME == "bootstrap"


def test_the_seat_exposes_nothing_but_the_composition_accessor() -> None:
    # See the module docstring: the seat's job is to answer one question,
    # and every extra name is a second thing to keep in sync with the
    # member — as well as a way for a later feature to accidentally depend
    # on the seat for a world API it should reach through the world.
    assert set(seat.__all__) == EXPECTED_EXPORTS
    for name in EXPECTED_EXPORTS:
        assert hasattr(seat, name), name
    # And the world's own API is *not* among the exports — the specific
    # names a well-meaning re-export would add first.
    for leaked in ("HyperparameterWorld", "HyperparameterSetting", "HyperparameterAxis"):
        assert leaked not in seat.__all__


def test_the_seat_returns_the_composed_world() -> None:
    # The composition-level contract, checked by behaviour across the
    # loader's synthetic-name copy.
    world = seat.hyperparameter_world_component()
    assert world is not None
    assert type(world).__name__ == "HyperparameterWorld"
    assert world.world_id == member.HYPERPARAMETER_WORLD_ID
    node_id = world.canonical_node()
    assert world.label(node_id).r2_holdout == member.hyperparameter_world().label(
        node_id
    ).r2_holdout


def test_the_seat_reads_the_application_it_is_handed() -> None:
    # A caller that already holds an application must get *that*
    # application's component, not a freshly composed one — otherwise two
    # callers holding different applications could be handed the same
    # world, and a test that composed deliberately would be measuring
    # something else entirely.
    app = create_app()
    assert seat.hyperparameter_world_component(app) is app.get("bootstrap")


def test_an_absent_component_reads_as_none_rather_than_raising() -> None:
    # ``Application`` is a plain dataclass, so the absent case is
    # constructible without depending on a scan having failed.  Returning
    # ``None`` is the documented behaviour, and the reason the seat is safe
    # to import in a workspace that does not carry this member.
    assert seat.hyperparameter_world_component(Application()) is None


def test_an_empty_workspace_still_composes_only_the_absent_world(tmp_path) -> None:
    # The same fact through the real factory rather than a hand-made
    # ``Application``: a composition whose scan contributes nothing still
    # builds, and the seat still answers ``None`` rather than raising.  A
    # seat that raised here would take down the import of every module
    # that reached it.
    #
    # Both halves of "contributed nothing" are needed, and getting this
    # wrong once is why the test is written out at length.  The *root*
    # must be a directory with no package subdirectories (passing ``"."``
    # scans the repository and finds every member), **and** the registry
    # must be fresh — the loader's default registry is module-level and
    # persists across calls, so a second ``create_app()`` would inherit
    # everything the first one's scan registered and the composition would
    # look populated no matter what was scanned.
    empty = create_app(tmp_path, registry=Registration())
    assert empty.components == {}
    assert seat.hyperparameter_world_component(empty) is None


def test_the_seat_composes_nothing_of_its_own() -> None:
    # Reading the component must not *create* one.  A seat that built a
    # world behind the caller's back would report a bootstrap pool of one
    # in a deployment that carries none — the §10.6 pool-separation rule
    # violated from the composition side, where it is hardest to see.
    empty = Application()
    assert seat.hyperparameter_world_component(empty) is None
    assert empty.components == {}  # and it did not add one on the way out


def test_the_seat_reads_the_documented_component_key() -> None:
    # The key is the member's registration name, so a rename on one side
    # fails here rather than as a mysteriously absent world at runtime.
    app = create_app()
    assert seat.COMPONENT_NAME in app
    assert seat.hyperparameter_world_component(app) is app.get(seat.COMPONENT_NAME)


def test_the_seat_needs_no_arguments() -> None:
    # The no-argument call is the one the app package's other callers use
    # (they hold no application), so it must compose on its own — and it
    # must be safe to call repeatedly, since it is a read rather than a
    # construction.
    first = seat.hyperparameter_world_component()
    second = seat.hyperparameter_world_component()
    assert first is not None and second is not None
    assert type(first).__name__ == type(second).__name__


@pytest.mark.parametrize("absent", ["", "not-a-component", "bootstrap-hpo"])
def test_a_misspelled_component_key_is_absent_not_a_near_match(absent: str) -> None:
    # The component key is exact.  A near-miss must read as absent rather
    # than fuzzy-match onto the world — and ``bootstrap-hpo`` is the
    # specific plausible miss: it is the *world id*'s prefix, so someone
    # reading the pool's reports rather than the code would reach for it.
    # The member registers under ``bootstrap`` and the seat says so.
    app = create_app()
    assert app.get(absent) is None
    assert seat.hyperparameter_world_component(app) is not None  # the real key works
