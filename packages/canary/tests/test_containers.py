"""The sweep: every evaluation container, pinned at once.

These tests pin :mod:`canary._containers` — the set assertion feature
135's word *every* lives in. The properties under test are the three
the module docstring argues: the refusal is collective and complete
(every offender named in one error), the sweep never passes vacuously
(an empty declaration is refused, and so is an environment that names
no reference), and the declared set is one table the environment
resolution reads exactly.
"""

from __future__ import annotations

import pytest

from canary import (
    EVALUATOR_ROLE,
    IMAGE_ENV_VARS,
    PinnedContainers,
    PinnedImage,
    pin_containers,
    pinned_containers_from_env,
)
from conftest import (  # type: ignore[import-not-found] - suite-local fixture module
    PINNED_EVALUATOR_DIGEST,
    PINNED_EVALUATOR_IMAGE,
    PINNED_RUNNER_IMAGE,
)


# -- The positive sweep ------------------------------------------------------


def test_every_container_in_a_declaration_is_pinned() -> None:
    containers = pin_containers(
        {
            "evaluator": PINNED_EVALUATOR_IMAGE,
            "runner": PINNED_RUNNER_IMAGE,
        }
    )
    assert isinstance(containers, PinnedContainers)
    assert containers.roles == ("evaluator", "runner")
    assert containers.digests == {
        "evaluator": PINNED_EVALUATOR_DIGEST,
        "runner": "sha256:" + "ef" * 32,
    }


def test_the_references_survive_as_written() -> None:
    declaration = {
        "evaluator": PINNED_EVALUATOR_IMAGE,
        "runner": PINNED_RUNNER_IMAGE,
    }
    assert pin_containers(declaration).references == declaration


def test_pins_iterate_in_role_order_and_answer_lookup() -> None:
    containers = pin_containers(
        {"runner": PINNED_RUNNER_IMAGE, "evaluator": PINNED_EVALUATOR_IMAGE}
    )
    assert [pin.role for pin in containers] == ["evaluator", "runner"]
    assert containers["runner"].digest == "sha256:" + "ef" * 32
    assert "evaluator" in containers
    assert "worker" not in containers
    assert len(containers) == 2
    with pytest.raises(KeyError):
        containers["worker"]


def test_a_set_can_be_assembled_from_parsed_pins() -> None:
    # The value constructor validates what the sweep validates — never
    # empty, no duplicated roles — so a hand-assembled set cannot be
    # less of an assertion than a swept one.
    evaluator = PinnedImage(
        role="evaluator",
        digest=PINNED_EVALUATOR_DIGEST,
        reference=PINNED_EVALUATOR_IMAGE,
    )
    runner = PinnedImage(
        role="runner", digest="sha256:" + "ef" * 32, reference=PINNED_RUNNER_IMAGE
    )
    containers = PinnedContainers((runner, evaluator))
    assert containers.roles == ("evaluator", "runner")


def test_a_set_of_non_pins_is_rejected() -> None:
    with pytest.raises(Exception, match="must be a PinnedImage"):
        PinnedContainers(("evaluator",))  # type: ignore[arg-type]


def test_a_duplicated_role_is_rejected() -> None:
    first = PinnedImage(
        role="evaluator",
        digest=PINNED_EVALUATOR_DIGEST,
        reference=PINNED_EVALUATOR_IMAGE,
    )
    second = PinnedImage(
        role="evaluator",
        digest="sha256:" + "ef" * 32,
        reference=PINNED_EVALUATOR_IMAGE,
    )
    with pytest.raises(Exception, match="declared twice"):
        PinnedContainers((first, second))


def test_an_empty_pin_set_is_rejected() -> None:
    with pytest.raises(Exception, match="pins nothing"):
        PinnedContainers(())


# -- The collective refusal ---------------------------------------------------


def test_a_tag_only_entry_is_refused_and_names_the_role() -> None:
    with pytest.raises(Exception, match="not pinned by digest") as raised:
        pin_containers(
            {
                "evaluator": PINNED_EVALUATOR_IMAGE,
                "runner": "ghcr.io/nullius/runner:latest",
            }
        )
    message = str(raised.value)
    assert "the runner container" in message
    assert "ghcr.io/nullius/runner:latest" in message
    assert "not digest-pinned" in message


def test_the_refusal_names_the_environment_variable_behind_the_role() -> None:
    # The evaluator's variable is the one entry IMAGE_ENV_VARS declares
    # today; its refusal names it so an operator knows where to fix.
    with pytest.raises(Exception, match="NULLIUS_EVALUATOR_IMAGE"):
        pin_containers({"evaluator": "ghcr.io/nullius/evaluator:latest"})


def test_every_offender_is_named_in_one_refusal() -> None:
    # The feature's word is *every*: a sweep that reported only the
    # first offender would be re-run N times to learn what one run
    # should have said. Two of three containers are unpinned here, in
    # an order chosen so neither is "first" by accident.
    with pytest.raises(Exception, match="not pinned by digest") as raised:
        pin_containers(
            {
                "worker": "ghcr.io/nullius/worker",  # bare name
                "evaluator": PINNED_EVALUATOR_IMAGE,
                "runner": "ghcr.io/nullius/runner:latest",  # tag-only
            }
        )
    message = str(raised.value)
    assert "2 of 3 declared refused" in message
    assert "the runner container" in message
    assert "the worker container" in message
    # The pinned container is not smeared onto the offenders list.
    assert "the evaluator container" not in message


def test_the_refusal_counts_offenders_in_sorted_role_order() -> None:
    with pytest.raises(Exception) as raised:
        pin_containers({"runner": ":latest", "worker": ":latest"})
    first, second = str(raised.value).split("\n  ")[-2:]
    assert "the runner container" in first
    assert "the worker container" in second


def test_a_declaration_that_names_no_containers_is_refused() -> None:
    # A pin sweep over an empty set is green because it checked
    # nothing — vacuous green, the one reading a nightly canary must
    # never allow.
    with pytest.raises(Exception, match="vacuous"):
        pin_containers({})


def test_a_non_mapping_declaration_is_refused() -> None:
    with pytest.raises(Exception, match="must be a mapping"):
        pin_containers(["ghcr.io/nullius/evaluator@sha256:" + "ab" * 32])  # type: ignore[arg-type]


def test_an_unnameable_role_key_is_refused_immediately() -> None:
    # A malformed role is a caller programming error, refused before
    # the sweep collects failures — not folded into a message that
    # would have to name it by a word it does not have.
    with pytest.raises(Exception, match="non-empty string"):
        pin_containers({"": PINNED_EVALUATOR_IMAGE})


def test_a_non_string_reference_is_refused_with_the_value_named() -> None:
    with pytest.raises(Exception, match="non-empty string, got 5"):
        pin_containers({"evaluator": 5})  # type: ignore[dict-item]


# -- The environment resolution ------------------------------------------------


def test_the_environment_resolves_the_declared_containers() -> None:
    containers = pinned_containers_from_env(
        {"NULLIUS_EVALUATOR_IMAGE": PINNED_EVALUATOR_IMAGE}
    )
    assert containers.roles == (EVALUATOR_ROLE,)
    assert containers[EVALUATOR_ROLE].digest == PINNED_EVALUATOR_DIGEST


def test_the_declared_table_names_the_evaluator_variable() -> None:
    # One table, one spelling: the sweep reads NULLIUS_EVALUATOR_IMAGE
    # — the same variable the evaluator service resolves — so a
    # deployment states a pin once and both read it.
    assert IMAGE_ENV_VARS == {"evaluator": "NULLIUS_EVALUATOR_IMAGE"}


def test_an_unset_variable_is_a_refusal_not_a_skip() -> None:
    # An evaluation container nobody named is an evaluation container
    # nobody pinned; a sweep that quietly dropped it would pass while
    # the path it guards ran unpinned.
    with pytest.raises(Exception, match="NULLIUS_EVALUATOR_IMAGE is not set") as raised:
        pinned_containers_from_env({})
    assert "nobody pinned" in str(raised.value)


@pytest.mark.parametrize("value", ["", "   "], ids=["empty", "blank"])
def test_a_blank_variable_is_a_refusal(value: str) -> None:
    with pytest.raises(Exception, match="NULLIUS_EVALUATOR_IMAGE is not set"):
        pinned_containers_from_env({"NULLIUS_EVALUATOR_IMAGE": value})


def test_a_tag_only_environment_is_refused_with_role_and_variable() -> None:
    with pytest.raises(Exception, match="not pinned by digest") as raised:
        pinned_containers_from_env(
            {"NULLIUS_EVALUATOR_IMAGE": "nullius-evaluator:latest"}
        )
    message = str(raised.value)
    assert "NULLIUS_EVALUATOR_IMAGE (the evaluator container)" in message
    assert "nullius-evaluator:latest" in message
    assert "not digest-pinned" in message
