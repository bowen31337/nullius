"""A stable iteration order — feature 138.

These tests pin :mod:`canary._ordering` — the classifier that reads a
declared hash seed, the sweep that refuses an environment which would not
make a hash-ordered walk reproducible, the canonical-order assertion every
reduction is checked against, and the verdict that records which of the
two *clean* readings a deployment gave. The properties under test are the
ones the module docstring argues:

* both halves of §12's row are enforced — the seed and the sort — because
  the feature's own sentence joins them with ``and``;
* the seed is *read*, never set: this module cannot change the running
  interpreter's flag, and says so rather than pretending otherwise;
* the classifier is never more permissive than the interpreter it vouches
  for — a value the interpreter would refuse to start under is a refusal
  here, not a pass — and the one value that pins is a valid non-negative
  integer that is exactly zero, in the spellings ``strtol`` accepts;
* unset is not unpinned: a deployment that declared nothing is *recorded*,
  and only a declaration that is present and not the pin is refused;
* the assertion judges a sequence and never repairs it.

The seed values below are the real ones, not mocks, and the two spellings
that matter most are the two a deployment actually reaches for:
``PYTHONHASHSEED=0`` (the row's remedy) and ``PYTHONHASHSEED=1`` (the
deployment asserting the opposite, which is the failure this feature
exists to make loud). The subprocess test at the end is the one that
measures the claim rather than restating it: it runs the same
set-iterating reduction under both spellings, in fresh interpreters, and
shows the classifier's verdict predicting what the interpreter actually
does.
"""

from __future__ import annotations

import dataclasses
import subprocess
import sys

import pytest
from canary import (
    HASH_SEED_ENV,
    MAX_SEED,
    PINNED,
    PINNED_SEED,
    RANDOM_SPELLING,
    UNPINNED,
    UNSET,
    CanaryError,
    CanaryImageError,
    CanaryOrderError,
    CanaryReproducibilityError,
    CanaryService,
    StableOrder,
    apply_reduction_order,
    assert_stable_iteration_order,
    classify_hash_seed,
    hash_seed_active,
    is_stable_iteration_order,
    pinned_environment,
    require_stable_environment,
    stable_reduction_order,
    tree_walk_order,
)

# -- The classifier: a declared seed to pinned, unpinned or unset ------------


@pytest.mark.parametrize(
    "value",
    ["0", "00", "000", "+0", "-0", " 0", "\t0", "+00"],
)
def test_a_zero_declaration_in_every_strtol_spelling_is_the_pin(value: str) -> None:
    # The interpreter reads this variable with ``strtol`` semantics, so
    # leading whitespace and a sign are part of the *same* declaration:
    # ``+0`` and ``"\t0"`` pin the seed just as ``0`` does. The classifier
    # has to accept every one of them, or it would refuse a deployment
    # the interpreter is perfectly happy with — which is a false positive,
    # and just as corrosive as a false negative here.
    assert classify_hash_seed(value) == PINNED


@pytest.mark.parametrize("value", ["1", "42", "1234567890", " 7"])
def test_a_non_zero_declaration_is_unpinned(value: str) -> None:
    # The failure the feature exists to catch: a deployment that *did*
    # declare a seed and declared one that leaves hash randomization on.
    assert classify_hash_seed(value) == UNPINNED


@pytest.mark.parametrize("value", [None, ""])
def test_an_absent_declaration_is_unset(value: object) -> None:
    # The empty string is read as UNSET rather than PINNED deliberately: the
    # interpreter takes the zero default for it, so a trailing
    # ``PYTHONHASHSEED=`` in an env file pins the seed *by accident*.
    # Recording that as the row's remedy would be claiming credit for a
    # guarantee the deployment never asked for. Note the case is *exactly* the
    # empty string — whitespace-only values are refused, see
    # ``test_a_whitespace_only_declaration_is_refused``.
    assert classify_hash_seed(value) == UNSET


@pytest.mark.parametrize(
    "value",
    ["abc", "Random", "RANDOM", " random", "random ", "0x0", "0 ", "0\n", "00 ", "1_0"],
)
def test_a_declaration_the_interpreter_would_reject_is_refused(value: str) -> None:
    # The conservative direction, and the one that matters most: the
    # interpreter refuses to *start* under a value it cannot parse, so
    # such a declaration names an eval worker that would not boot — and a
    # night that never ran is not a night the canary passed. Accepting it
    # would make this sweep more permissive than the runtime it vouches
    # for, which is the one thing it must never be. Note the near-misses
    # of the "random" spelling: the interpreter compares the whole value,
    # so "Random" and " random" are rejections while "random" is not.
    with pytest.raises(CanaryOrderError, match="neither"):
        classify_hash_seed(value)


def test_the_explicit_random_spelling_is_unpinned_not_unparseable() -> None:
    # "random" is the interpreter's other accepted spelling — "choose a seed
    # at startup" — so it is a *declaration*, and a refusal to parse it would
    # misdescribe a worker that boots fine. What it is not is the pin: it is
    # the deployment asking for randomization in as many words, which is
    # exactly what §12's row forbids.
    assert classify_hash_seed(RANDOM_SPELLING) == UNPINNED
    with pytest.raises(CanaryOrderError, match="not the pin"):
        require_stable_environment({HASH_SEED_ENV: RANDOM_SPELLING})


@pytest.mark.parametrize("value", ["-1", "-7", "-0001", "-01"])
def test_a_negative_declaration_is_refused(value: str) -> None:
    # The interpreter rejects a negative seed outright (``must be an
    # integer in range [0; 4294967295]``), so the classifier does too —
    # with its own reason, because "below zero" and "not a number" are
    # different mistakes an operator would fix differently.
    with pytest.raises(CanaryOrderError, match="outside the range"):
        classify_hash_seed(value)


@pytest.mark.parametrize("value", ["4294967296", "9999999999", "8589934592"])
def test_an_out_of_range_declaration_is_refused(value: str) -> None:
    # The bound is not decoration: 4294967296 is an ordinary thing for an
    # operator to write and the interpreter rejects it outright. A
    # classifier that only checked "digits" would call it unpinned and
    # quietly describe a worker that never started as one that ran with
    # randomization on — a wrong answer wearing the shape of a right one.
    with pytest.raises(CanaryOrderError, match="outside the range"):
        classify_hash_seed(value)


def test_the_upper_bound_itself_is_accepted() -> None:
    # The range is inclusive of both ends, so the classifier must accept the
    # maximum the interpreter does — off-by-one in either direction is a
    # disagreement with the runtime.
    assert classify_hash_seed(str(MAX_SEED)) == UNPINNED


@pytest.mark.parametrize("value", ["   ", "\t", "\n", " \t "])
def test_a_whitespace_only_declaration_is_refused(value: str) -> None:
    # The subtle one, and the reason this test exists: ``""`` is *accepted*
    # by the interpreter (it takes the zero default) while ``"   "`` is
    # *rejected*, so a classifier that treated "blank" as one case would
    # either refuse a value that boots or — far worse — report the passing
    # case for a worker that would not boot. That is the vacuous green the
    # nightly canary must never allow, so the empty case is pinned to
    # exactly the empty string.
    with pytest.raises(CanaryOrderError, match="neither"):
        classify_hash_seed(value)


def test_a_non_string_declaration_is_refused() -> None:
    # The variable is a string a deployment wrote; an int handed to the
    # classifier is a broken declaration rather than a seed. The
    # distinction matters because ``0`` the int and ``"0"`` the string
    # are the same value to a reader and only one of them is what the
    # interpreter reads.
    with pytest.raises(CanaryOrderError, match="must be a string"):
        classify_hash_seed(0)  # type: ignore[arg-type]


def test_the_negative_zero_spelling_is_not_a_negative_declaration() -> None:
    # ``-0`` is zero, and the interpreter starts happily under it. A
    # classifier that pattern-matched on the sign rather than parsing the
    # integer would refuse a deployment that is correctly pinned — the
    # false positive the parametrized pin cases above also guard.
    assert classify_hash_seed("-0") == PINNED


# -- The runtime flag: what the interpreter decided, beside the declaration --


def test_the_runtime_flag_is_read_from_the_interpreter() -> None:
    # Feature 138 reads the *declaration* and the *fact* separately, and
    # this is the fact: ``sys.flags.hash_randomization``, which is False
    # exactly when this interpreter was started with PYTHONHASHSEED=0 and
    # without -R. The module cannot change it — the decision was made
    # before any application code ran — so it reports it.
    assert hash_seed_active() is bool(sys.flags.hash_randomization)


# -- The sweep: an unpinned environment is refused, an absent one is not -----


def test_an_empty_environment_is_recorded_rather_than_refused() -> None:
    # Unset is not unpinned. The row is a statement about what an eval
    # worker is *built* to run as — the container feature 135 pins, whose
    # environment the sandbox writes the seed into — so a deployment that
    # declares nothing has configured nothing.
    verdict = require_stable_environment({})
    assert isinstance(verdict, StableOrder)
    assert verdict.seed == UNSET
    assert verdict.declared is False
    assert verdict.pinned is False


def test_the_pinned_environment_is_recorded_as_the_pin() -> None:
    # §12's remedy, reached: the verdict says so, and says so in a
    # different word from the unset case, because "we pinned it" and "we
    # never pinned it and the container stood in" are different facts
    # about a night that produced the same bytes.
    verdict = require_stable_environment({HASH_SEED_ENV: PINNED_SEED})
    assert verdict.seed == PINNED
    assert verdict.pinned is True
    assert verdict.declared is True


def test_the_verdict_records_the_runtime_flag_beside_the_declaration() -> None:
    # The two readings can disagree in exactly one direction — a
    # deployment that pinned the seed in the environment of a process
    # nevertheless started with -R — and a report showing only the
    # declaration would be showing the claim rather than the fact.
    verdict = require_stable_environment({HASH_SEED_ENV: PINNED_SEED})
    assert verdict.randomization_active is hash_seed_active()
    assert verdict.variable == HASH_SEED_ENV


@pytest.mark.parametrize("value", ["1", "42", "7", "\t13"])
def test_an_explicitly_unpinned_environment_is_refused(value: str) -> None:
    # The refusal, and the whole point of the *environment* half: a
    # deployment that declares a non-zero seed is asserting the opposite
    # of the contract, and every child process it starts inherits the
    # assertion. This is exactly the deployment whose iteration order
    # varies from night to night.
    with pytest.raises(CanaryOrderError, match="not the pin"):
        require_stable_environment({HASH_SEED_ENV: value})


def test_an_unplaceable_seed_is_refused_through_the_sweep_too() -> None:
    # The classifier's refusal propagates unchanged: a caller holding the
    # sweep learns the deployment's worker would not boot, with the
    # classifier's reason rather than a second, poorer one the sweep
    # would have to invent.
    with pytest.raises(CanaryOrderError, match="neither"):
        require_stable_environment({HASH_SEED_ENV: "nonsense"})


def test_the_blank_declaration_is_recorded_as_unset() -> None:
    # The env-file case, through the sweep rather than the classifier:
    # set and blank is a deployment that declared nothing, and the
    # verdict says so rather than claiming the pin.
    verdict = require_stable_environment({HASH_SEED_ENV: ""})
    assert verdict.seed == UNSET


def test_the_environment_mapping_is_the_single_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The sweep reads the mapping it is handed and not the process, so a
    # test or an operator can hand it an environment without touching the
    # shell — the same single-seam property every other sweep in this
    # member has.
    monkeypatch.setenv(HASH_SEED_ENV, "1")
    assert require_stable_environment({}).seed == UNSET
    with pytest.raises(CanaryOrderError, match="not the pin"):
        require_stable_environment({HASH_SEED_ENV: "1"})


def test_the_process_environment_is_read_when_none_is_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(HASH_SEED_ENV, PINNED_SEED)
    assert require_stable_environment().seed == PINNED
    monkeypatch.setenv(HASH_SEED_ENV, "5")
    with pytest.raises(CanaryOrderError, match="not the pin"):
        require_stable_environment()


# -- The verdict record -------------------------------------------------------


def test_the_verdict_is_frozen() -> None:
    verdict = require_stable_environment({})
    with pytest.raises(dataclasses.FrozenInstanceError):
        verdict.seed = PINNED  # type: ignore[misc]


def test_a_verdict_cannot_carry_an_unpinned_seed() -> None:
    # The all-or-nothing property: a StableOrder is the clean verdict,
    # built only after every unpinned declaration is refused, so a record
    # that carried UNPINNED would say "stable" while naming the one
    # declaration the row forbids. Same shape as DevicePaths refusing to
    # carry a GPU.
    with pytest.raises(CanaryOrderError, match="clean verdict"):
        StableOrder(variable=HASH_SEED_ENV, seed=UNPINNED, randomization_active=True)


def test_a_verdict_must_name_the_variable_the_contract_is_read_from() -> None:
    # A verdict about any other variable would vouch for a knob nothing
    # reads.
    with pytest.raises(CanaryOrderError, match="names the variable"):
        StableOrder(variable="NULLIUS_HASH_SEED", seed=PINNED, randomization_active=False)


def test_a_verdict_must_carry_the_flag_as_a_bool() -> None:
    with pytest.raises(CanaryOrderError, match="not a bool"):
        StableOrder(variable=HASH_SEED_ENV, seed=PINNED, randomization_active="no")  # type: ignore[arg-type]


# -- The order predicate and assertion ---------------------------------------


def test_a_sorted_sequence_is_a_stable_order() -> None:
    assert is_stable_iteration_order(("A", "B", "C")) is True
    assert assert_stable_iteration_order(("A", "B", "C")) == ("A", "B", "C")


def test_an_empty_sequence_is_stable_vacuously() -> None:
    # Nothing is in no particular order: a reduction over no members has
    # no order to get wrong.
    assert is_stable_iteration_order(()) is True
    assert assert_stable_iteration_order(()) == ()


def test_an_unsorted_sequence_is_not_a_stable_order() -> None:
    assert is_stable_iteration_order(("B", "A")) is False
    with pytest.raises(CanaryOrderError, match="not in the stable iteration order"):
        assert_stable_iteration_order(("B", "A"))


def test_a_repeated_member_is_not_a_stable_order() -> None:
    # Strictly increasing, not merely non-decreasing: a member appearing
    # twice is not an order any sort produces and misaligns every zip
    # downstream exactly as an unsorted sequence does. The same rule
    # feature 46 states, so a sequence satisfying one satisfies the other.
    assert is_stable_iteration_order(("A", "A")) is False
    with pytest.raises(CanaryOrderError, match="repeats"):
        assert_stable_iteration_order(("A", "A"))


def test_a_blank_member_is_not_a_stable_order() -> None:
    assert is_stable_iteration_order(("A", "")) is False
    assert is_stable_iteration_order(("A", "  ")) is False
    with pytest.raises(CanaryOrderError, match="non-blank string"):
        assert_stable_iteration_order(("A", ""))


def test_a_non_string_member_is_not_a_stable_order() -> None:
    # Total over the members, like feature 46's predicate: the predicate
    # never raises on what it iterates, and the assertion is where the
    # loud refusal lives.
    assert is_stable_iteration_order(("A", 3)) is False
    with pytest.raises(CanaryOrderError, match="non-blank string"):
        assert_stable_iteration_order(("A", 3))  # type: ignore[arg-type]


def test_a_value_that_is_not_a_sequence_is_refused() -> None:
    # A reduction consumes an ordered sequence; a bare string is iterable
    # but is not one (it would be read as a sequence of characters, which
    # is a different question than the one asked).
    with pytest.raises(CanaryOrderError, match="sequence of symbols"):
        assert_stable_iteration_order("ABC")  # type: ignore[arg-type]
    with pytest.raises(CanaryOrderError, match="sequence of symbols"):
        assert_stable_iteration_order({"A", "B"})  # type: ignore[arg-type]


def test_the_assertion_judges_and_never_repairs() -> None:
    # The load-bearing stance: repairing here — quietly sorting what it
    # was handed — would hide exactly the defect it exists to catch. The
    # fix is upstream, at the boundary that produced the sequence.
    with pytest.raises(CanaryOrderError):
        assert_stable_iteration_order(("C", "A", "B"))
    # And it returns what it was given, unchanged, when the order is right.
    given = ["A", "B"]
    assert assert_stable_iteration_order(given) == ("A", "B")


def test_the_assertion_names_the_origin_of_the_sequence() -> None:
    # An operator reading the refusal learns *which boundary* leaked the
    # unstable order, not merely that one did.
    with pytest.raises(CanaryOrderError, match="universe resolution"):
        assert_stable_iteration_order(("B", "A"), origin="universe resolution")


def test_a_blank_origin_is_refused() -> None:
    with pytest.raises(ValueError, match="origin must be"):
        assert_stable_iteration_order(("A",), origin="  ")


def test_the_order_is_by_code_point_not_case_folded() -> None:
    # Python's plain ``str`` comparison, deliberately: a locale- or
    # case-folded collation varies by environment and this order may not.
    # "Z" < "a" by code point, so this sequence is in the canonical order
    # even though a case-insensitive reader would call it reversed.
    assert is_stable_iteration_order(("Z", "a")) is True


# -- The producing half: the sort applied, the seed set ----------------------


def test_the_producing_half_sorts_what_it_is_handed() -> None:
    # The row's verb is *applies*, not *checks*: a caller hands this the
    # order it happens to have and gets back the order a reduction may sum
    # in. Float addition is not associative, so the last bits of a sum are
    # decided by the arrival order — which is why the sort has to happen
    # here, at the seam, and not wherever the members were collected.
    assert apply_reduction_order(("C", "A", "B")) == ("A", "B", "C")


def test_the_producing_half_dominates_the_order_the_members_arrived_in() -> None:
    # Same members, different arrival orders, one answer. This is the whole
    # point: an unordered container's iteration order is exactly what a
    # pinned seed makes reproducible-but-not-fixed, so the boundary sorts.
    assert apply_reduction_order(("B", "A", "C")) == apply_reduction_order(
        ("C", "B", "A")
    )


def test_the_producing_half_refuses_a_repeated_member_rather_than_collapsing_it() -> None:
    # The tempting repair is ``sorted(set(values))``, and it is wrong: a
    # member carrying a weight contributes once per occurrence, so collapsing
    # a repeat silently changes the reduction's total. A sum that moves
    # without announcing itself is the failure §12 is written about, so the
    # repetition is refused and the caller — who alone knows which
    # occurrence was meant — fixes the query.
    with pytest.raises(CanaryOrderError, match="distinct members"):
        apply_reduction_order(("A", "B", "A"))


def test_the_producing_half_agrees_with_the_checker_on_a_repetition() -> None:
    # The producer must not manufacture a sequence its own checker refuses.
    # Collapsing would do exactly that: the checker never sees the input, so
    # a dedupe here would hide from the very check the row asks for.
    repeated = ("A", "B", "A")
    with pytest.raises(CanaryOrderError):
        assert_stable_iteration_order(repeated, origin="an ungrouped query")
    with pytest.raises(CanaryOrderError):
        apply_reduction_order(repeated)


def test_the_producing_half_is_stable_for_an_empty_input() -> None:
    assert apply_reduction_order(()) == ()


def test_the_producing_half_returns_a_tuple_not_the_input() -> None:
    # A tuple is what a reduction may be handed on to someone else without
    # the caller's later mutation reaching it.
    given = ["B", "A"]
    produced = apply_reduction_order(given)
    assert produced == ("A", "B")
    given.append("C")
    assert produced == ("A", "B")


def test_the_producing_half_sorts_by_code_point_like_the_checker() -> None:
    # The producing and checking halves must agree on what "sorted" means,
    # or a boundary could satisfy one and fail the other. "Z" < "a".
    produced = apply_reduction_order(("a", "Z"))
    assert produced == ("Z", "a")
    assert is_stable_iteration_order(produced) is True


@pytest.mark.parametrize("value", ["", "   ", "\t", "\n", "  \n "])
def test_the_producing_half_refuses_a_blank_member(value: str) -> None:
    # Sorting a member nobody could vouch for produces a stable *order* of
    # unaccountable things, which is not a reproducible reduction.
    with pytest.raises(CanaryOrderError, match="non-blank strings"):
        apply_reduction_order(("A", value))


@pytest.mark.parametrize("value", [None, 1, b"A", ["A"]])
def test_the_producing_half_refuses_a_non_string_member(value: object) -> None:
    with pytest.raises(CanaryOrderError, match="non-blank strings"):
        apply_reduction_order(("A", value))  # type: ignore[arg-type]


def test_the_producing_half_names_the_position_of_the_member_it_refused() -> None:
    # An operator reading the refusal learns *where* the bad member was,
    # which is what makes the upstream boundary findable.
    with pytest.raises(CanaryOrderError, match="position 1"):
        apply_reduction_order(("A", "", "B"))


def test_the_producing_half_accepts_a_set_which_is_what_it_exists_for() -> None:
    # An unordered container is the case the row is written about: this is
    # an order the caller could not have known, handed back sorted.
    assert apply_reduction_order({"B", "A"}) == ("A", "B")


def test_the_pinned_environment_sets_the_seed_to_zero() -> None:
    assert pinned_environment({}) == {HASH_SEED_ENV: PINNED_SEED}
    assert pinned_environment({})[HASH_SEED_ENV] == "0"


def test_the_pinned_environment_overrides_an_inherited_declaration() -> None:
    # A worker launched from a shell that already declares a seed gets the
    # pin, not the shell's value: the contract is the deployment's, and a
    # non-zero declared seed has provenance §12 does not name.
    for inherited in ("3", RANDOM_SPELLING, "4294967295"):
        produced = pinned_environment({"PATH": "/bin", HASH_SEED_ENV: inherited})
        assert produced[HASH_SEED_ENV] == PINNED_SEED
        assert classify_hash_seed(produced[HASH_SEED_ENV]) == PINNED


def test_the_pinned_environment_keeps_the_rest_of_the_environment() -> None:
    # A child process launched with this mapping must still be the child
    # the caller meant: pinning the seed is not licence to drop PATH.
    base = {"PATH": "/bin", "HOME": "/root", "OMP_NUM_THREADS": "1"}
    produced = pinned_environment(base)
    for name, value in base.items():
        assert produced[name] == value
    assert len(produced) == len(base) + 1


def test_the_pinned_environment_never_mutates_what_it_was_given() -> None:
    # The caller's mapping may be ``os.environ`` itself; a producer that
    # wrote through to it would pin the *current* process, which is exactly
    # the thing this module documents it never does — the interpreter has
    # already read the variable by the time any of this runs.
    base = {"PATH": "/bin"}
    pinned_environment(base)
    assert base == {"PATH": "/bin"}


def test_the_pinned_environment_returns_a_fresh_mapping_each_call() -> None:
    first = pinned_environment({})
    second = pinned_environment({})
    assert first == second
    assert first is not second


def test_the_pinned_environment_defaults_to_the_process_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CANARY_ORDER_PROBE", "probe")
    monkeypatch.setenv(HASH_SEED_ENV, "7")
    produced = pinned_environment()
    assert produced["CANARY_ORDER_PROBE"] == "probe"
    assert produced[HASH_SEED_ENV] == PINNED_SEED


def test_the_environment_the_producer_hands_out_is_the_one_the_sweep_accepts() -> None:
    # The two halves of the row meeting: what this module sets is what this
    # module then judges pinned. A producer whose output its own checker
    # refused would be two spellings of the contract.
    produced = pinned_environment({HASH_SEED_ENV: RANDOM_SPELLING})
    verdict = require_stable_environment(produced)
    assert verdict.seed == PINNED
    ordered, _ = stable_reduction_order({"B", "A"}, produced)
    assert ordered == ("A", "B")


# -- Both halves of the row, swept together ----------------------------------


def test_both_halves_pass_together_on_a_pinned_environment() -> None:
    ordered, verdict = stable_reduction_order(("A", "B"), {HASH_SEED_ENV: PINNED_SEED})
    assert ordered == ("A", "B")
    assert verdict.seed == PINNED


def test_the_seed_half_is_checked_even_when_the_sequence_is_ordered() -> None:
    # The feature's ``and``: a perfectly sorted sequence in an unpinned
    # environment is still a reduction whose order can move. Checking
    # either half alone would pass this, which is why the sweep checks
    # both.
    with pytest.raises(CanaryOrderError, match="not the pin"):
        stable_reduction_order(("A", "B"), {HASH_SEED_ENV: "3"})


def test_the_sequence_half_is_applied_even_when_the_seed_is_pinned() -> None:
    # The other direction, and the reason the sort clause is not redundant
    # with the seed clause: a pinned seed makes a *given* container's
    # iteration reproducible, not every sequence ordered. The feature's verb
    # is *returns a stable iteration order*, so this function applies the sort
    # rather than passing an unsorted sequence through — a caller hands it the
    # order it has and gets back the order a reduction may sum in.
    ordered, verdict = stable_reduction_order(
        ("B", "A"), {HASH_SEED_ENV: PINNED_SEED}
    )
    assert ordered == ("A", "B")
    assert verdict.seed == PINNED


def test_the_checking_half_still_refuses_an_unsorted_sequence() -> None:
    # The division the row draws: the *producing* path sorts, the *checking*
    # path refuses. A boundary that produced its own order proves it kept to
    # the contract with assert_stable_iteration_order, which never repairs —
    # a checker that quietly sorted its input would hide exactly the defect it
    # exists to catch.
    with pytest.raises(CanaryOrderError, match="not in the stable iteration order"):
        assert_stable_iteration_order(("B", "A"), origin="a hand-rolled boundary")


# -- The taxonomy -------------------------------------------------------------


def test_the_order_refusal_is_a_canary_error_but_not_an_image_error() -> None:
    # One ``except CanaryError`` still catches every assertion this member
    # makes; the split is what lets a caller tell "the seed is unpinned"
    # apart from "the container moved" — two failures with two repairs.
    assert issubclass(CanaryOrderError, CanaryError)
    assert not issubclass(CanaryOrderError, CanaryImageError)
    assert not issubclass(CanaryOrderError, CanaryReproducibilityError)
    assert not issubclass(CanaryReproducibilityError, CanaryOrderError)


# -- The composed component carries the sweep ---------------------------------


def test_the_composed_service_exposes_the_order_sweep_beside_the_pin_sweep(
    canary_env: dict[str, str],
) -> None:
    # Feature 138 through the composed component: one value carries the
    # category's assertions, so a caller holding the composed canary
    # reaches the order verdict without importing submodules by name.
    service = CanaryService(env=canary_env)
    assert isinstance(service.order, StableOrder)
    assert service.order.seed == UNSET
    # ... and the pin sweep is still its own verb, unchanged.
    assert service.containers["evaluator"].digest == "sha256:" + "ab" * 32


def test_the_order_sweep_is_lazy_like_the_pin_sweep() -> None:
    # The factory builds this component on every create_app(), so the
    # order sweep must not fail composition on a deployment's seed
    # configuration. A bare service constructs, and the refusal lands on
    # first use.
    service = CanaryService()
    assert service._order is None
    assert isinstance(service.order, StableOrder)
    # Resolved once: a deployment that re-read its seed mid-run could
    # observe two different truths about the same night.
    assert service.order is service.order


def test_the_order_sweep_refuses_an_unpinned_seed_on_first_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(HASH_SEED_ENV, "1")
    service = CanaryService()
    with pytest.raises(CanaryOrderError, match="not the pin"):
        _ = service.order


def test_the_order_sweep_does_not_require_a_pinned_deployment() -> None:
    # Deliberately like ``devices`` and unlike ``containers``: a
    # deployment whose images are unset is still perfectly able to learn
    # whether its iteration order is stable. Two failures, two repairs,
    # and a caller must not have to fix one to see the other.
    service = CanaryService(env={})
    assert service.order.seed == UNSET


def test_the_composed_application_carries_the_order_sweep() -> None:
    # Feature 138 through the module loader, like every other assertion in
    # this category: the factory's scan imports this member, the
    # ``@register`` builder fires, and the composed service a caller holds
    # reaches the verdict without importing a submodule by name.
    #
    # Pinned by class *name* and by the property's presence rather than by
    # ``isinstance``, for the reason ``test_component.py`` documents: the
    # loader imports this package under a synthetic module name, so the
    # classes this suite imported canonically are distinct objects from the
    # composed component's. And asserted on the class rather than the
    # instance, because ``order`` is a property — reading it off a composed
    # service built over an unknown environment would run the sweep, and
    # this test is about wiring, not about the ambient shell.
    from app.module_loader import create_app

    component = create_app().get("canary")
    assert type(component).__name__ == "CanaryService"
    assert isinstance(vars(type(component)).get("order"), property)


# -- The replay's reduction is the sort the row asks for ----------------------


def test_the_replay_walk_is_the_sorted_order_the_reduction_uses() -> None:
    # Feature 142's reduction, checked against feature 138's assertion —
    # which is what the two features are *for*: the replay sums over the
    # tree's nodes, and this is the proof that the sum runs in an order a
    # sort produced rather than in whichever order the caller's list
    # happened to be in.
    nodes = [{"node_id": "c"}, {"node_id": "a"}, {"node_id": "b"}]
    assert tree_walk_order(nodes) == ("a", "b", "c")
    assert assert_stable_iteration_order(
        tree_walk_order(nodes), origin="canary replay"
    ) == ("a", "b", "c")


def test_the_replay_walk_matches_the_order_the_score_is_summed_in() -> None:
    # The walk is not a second opinion about the order: it is the order the
    # replay's own reduction walks, and the sum runs in it. Two trees whose
    # nodes carry the *same ids with different weights* replay to two
    # different scores under an unsorted walk and to the same one under a
    # sorted walk — which is why the row exists. The proof here is the
    # weight-carrying one: ``node_id → weight`` is inverted between the two
    # trees, so a sum in id order is identical and a sum in insertion order
    # is not.
    from canary import CanaryTree, CanaryTreeNode, replay_pair

    def tree_for(weights: dict[str, float]) -> CanaryTree:
        return CanaryTree(
            nodes=tuple(
                CanaryTreeNode.freeze(
                    node_id, {"score": 1.0, "weight": weight}, depth=0
                )
                for node_id, weight in weights.items()
            )
        )

    forward = tree_for({"a": 1.0, "b": 2.0})
    reverse = tree_for({"b": 2.0, "a": 1.0})

    # The walk is the same for both, and it is sorted — the shape feature
    # 138 asks a reduction's order to have.
    walk_forward = tree_walk_order(
        [{"node_id": node.node_id} for node in forward.nodes]
    )
    walk_reverse = tree_walk_order(
        [{"node_id": node.node_id} for node in reverse.nodes]
    )
    assert walk_forward == walk_reverse == ("a", "b")
    assert assert_stable_iteration_order(walk_forward, origin="canary replay")

    # ... and the replay reduces over that order, so the two trees score
    # the same. This is the property: with the sort, the score is a
    # function of the tree's *nodes*, not of the order a caller listed
    # them in.
    assert replay_pair(_pair_for(forward)).score == replay_pair(_pair_for(reverse)).score


def _pair_for(tree: object) -> object:
    """A minimal frozen pair around ``tree`` — the replay's argument."""
    from datetime import datetime, timezone

    from canary import CanaryPolicy, CanaryReferencePair

    return CanaryReferencePair(
        policy=CanaryPolicy.freeze(version="1", policy={"kind": "canary"}),
        tree=tree,
        recorded_score=None,
        id=None,
        is_active=True,
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )


# -- The claim, measured: the classifier predicts the interpreter -------------

#: A reduction whose float result depends on the *string hash seed* rather
#: than on its argument: it sums over a ``set`` of symbol names, whose
#: iteration order Python varies per interpreter under hash randomization.
#: §12's "Stable iteration order" row, in its most common real form — and
#: the shape of signal the nightly canary is blind to without this feature,
#: because two runs inside one interpreter share one seed and look
#: perfectly deterministic.
_SET_SUM_SOURCE = (
    "import sys\n"
    "symbols = {f'SYM{i}' for i in range(64)}\n"
    "sys.stdout.write(repr(sum(float(len(s)) for s in symbols)) + '|')\n"
    "sys.stdout.write(','.join(symbols))\n"
)


def _subprocess_env(seed: str | None) -> dict[str, str]:
    """An environment for a spawned interpreter, with the seed as declared.

    The interpreter that is spawned here runs a *set-iterating reduction*,
    so its environment has to be a real one: ``sys.executable`` must be
    findable by name (the venv's bin directory on ``PATH``) and the child
    must not inherit this suite's redirected ``PYTHONPATH`` or
    ``UV_CACHE_DIR``, which point at directories the spawned interpreter has
    no business reading. This mirrors the spawning seam feature 145's suite
    uses for the same reason.
    """
    import os

    env = {
        key: value
        for key, value in os.environ.items()
        if key not in ("PYTHONPATH", "UV_CACHE_DIR", "VIRTUAL_ENV")
    }
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env.get("PATH", "")
    if seed is None:
        env.pop(HASH_SEED_ENV, None)
    else:
        env[HASH_SEED_ENV] = seed
    return env


def _run_under(seed: str | None) -> str:
    """Run the set-reducing signal in a fresh interpreter under ``seed``."""
    return subprocess.run(
        [sys.executable, "-c", _SET_SUM_SOURCE],
        capture_output=True,
        check=True,
        env=_subprocess_env(seed),
        text=True,
    ).stdout


def _can_spawn() -> bool:
    try:
        subprocess.run(
            [sys.executable, "-c", "pass"], capture_output=True, timeout=30, check=True
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - sandboxed
        return False
    return True


@pytest.mark.skipif(not _can_spawn(), reason="cannot spawn a subprocess here")
def test_the_pin_the_classifier_accepts_is_the_pin_the_interpreter_honours() -> None:
    # The claim, measured — and the measurement corrects the naive version
    # of it. The classifier says PINNED for "0" and UNPINNED for "1"; asked
    # to actually run a set-iterating reduction in fresh interpreters, the
    # interpreter agrees that the two are different *kinds* of thing, but
    # not in the way the obvious test would assume:
    #
    #   * "0" turns hash randomization *off*, so the set's iteration order
    #     is the same in every interpreter that runs it — one distinct
    #     output from many runs.
    #   * "1" leaves randomization *on*, so the order derives from the seed
    #     — and because the seed is the same fixed value in each run, the
    #     order is *also* the same. This is the subtle half, and it is why
    #     the module docstring argues the refusal on provenance rather than
    #     on varying bytes: a fixed non-zero seed is reproducible at that
    #     value, and the classifier's objection is that the value is not
    #     the one §12 names.
    #
    # What separates them is the *unset* case, where each interpreter picks
    # its own seed and the order varies. That is the state a deployment
    # that declared nothing is in, which is why the sweep records it rather
    # than refusing it — and why the row's remedy is the explicit zero.
    assert classify_hash_seed("0") == PINNED
    assert classify_hash_seed("1") == UNPINNED
    assert classify_hash_seed(None) == UNSET

    pinned = {_run_under("0") for _ in range(8)}
    assert len(pinned) == 1, "PYTHONHASHSEED=0 must pin the set's iteration order"

    # A fixed non-zero seed is reproducible too — at that seed. Reported
    # rather than asserted as a failure, because it is the fact the
    # module's refusal is argued from.
    fixed = {_run_under("1") for _ in range(8)}
    assert len(fixed) == 1, (
        "a fixed non-zero seed derives one order: the classifier refuses it "
        "for its provenance, not for instability at that value"
    )
    assert fixed != pinned, (
        "the pin and a non-zero seed must not happen to agree; if they did, "
        "this test would be measuring nothing"
    )

    # Unpinned: each interpreter picks its own seed, so the order varies.
    unpinned = {_run_under(None) for _ in range(8)}
    assert len(unpinned) > 1, (
        "an unset PYTHONHASHSEED must leave hash randomization on, so a "
        "set's iteration order varies between interpreters"
    )


@pytest.mark.skipif(not _can_spawn(), reason="cannot spawn a subprocess here")
def test_the_environment_the_producer_hands_out_pins_a_real_interpreter() -> None:
    # The row's first clause, measured end to end rather than argued: a
    # child launched with exactly what ``pinned_environment`` returns runs
    # its set-iterating reduction in the same order every time, and reports
    # randomization off. This is the one test where the module's output is
    # the *only* thing standing between a reduction and a varying order —
    # ``_subprocess_env`` is not used, because the mapping under test has to
    # be the mapping the child gets.
    def run_with(env: dict[str, str]) -> str:
        return subprocess.run(
            [sys.executable, "-c", _SET_SUM_SOURCE],
            capture_output=True,
            check=True,
            env=env,
            text=True,
        ).stdout

    base = _subprocess_env(None)
    assert HASH_SEED_ENV not in base
    pinned = pinned_environment(base)

    first = run_with(pinned)
    second = run_with(pinned)
    assert first == second, "the pinned environment did not fix the sum's order"

    # And the same environment with the pin removed does vary: without this
    # the test above would pass for a child whose order happened to be fixed
    # for some other reason.
    unpinned = dict(pinned)
    unpinned.pop(HASH_SEED_ENV)
    assert run_with(unpinned) != run_with(unpinned)

    flag = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; print(int(sys.flags.hash_randomization))",
        ],
        capture_output=True,
        check=True,
        env=pinned,
        text=True,
    ).stdout.strip()
    assert flag == "0"


@pytest.mark.skipif(not _can_spawn(), reason="cannot spawn a subprocess here")
def test_the_runtime_flag_matches_what_a_fresh_interpreter_reports() -> None:
    # ``hash_seed_active`` reads this interpreter's flag; this checks the
    # flag means what the docstring claims by asking fresh interpreters
    # under each spelling. ``-R`` re-enables randomization whatever the
    # environment says, which is the one direction the declaration and the
    # flag can disagree — and the reason the verdict records both.
    def flag_under(args: list[str], seed: str | None) -> str:
        return subprocess.run(
            [
                sys.executable,
                *args,
                "-c",
                "import sys; print(int(sys.flags.hash_randomization))",
            ],
            capture_output=True,
            check=True,
            env=_subprocess_env(seed),
            text=True,
        ).stdout.strip()

    # ``sys.flags.hash_randomization`` is an int flag, so it prints as 0/1.
    assert flag_under([], "0") == "0"
    assert flag_under([], "1") == "1"
    # ``-R`` re-enables randomization whatever the environment says — the
    # one direction the declaration and the runtime fact disagree, and the
    # reason the verdict carries both.
    assert flag_under(["-R"], "0") == "1"


#: The values the differential test below sweeps. Deliberately built from the
#: edges rather than from examples: the pin's spellings, the explicit random
#: spelling, the near-misses of it, the range's both bounds and one past each,
#: the parsable-but-rejected forms, and the empty-versus-whitespace pair the
#: classifier once got wrong.
_DIFFERENTIAL_CORPUS: tuple[str | None, ...] = (
    None,
    "",
    "   ",
    "\t",
    "0",
    "00",
    "+0",
    "-0",
    " 0",
    "\t0",
    "\r0",
    "1",
    "42",
    "+1",
    " 1",
    "1  ",
    "-1",
    "-01",
    RANDOM_SPELLING,
    "RANDOM",
    "Random",
    " random",
    "random ",
    "abc",
    "0x0",
    "0 ",
    "0\n",
    "0junk",
    "1_0",
    str(MAX_SEED),
    str(MAX_SEED + 1),
    "9999999999",
)


def _interpreter_verdict(value: str | None) -> str:
    """What a fresh interpreter actually does with ``value`` — three outcomes.

    ``"REJECT"`` when it refuses to start (the worker that would not boot),
    ``"OFF"`` when it starts with hash randomization off, ``"ON"`` when it
    starts with randomization on. This is the ground truth the classifier is
    measured against.
    """
    result = subprocess.run(
        [sys.executable, "-c", "import sys; print(int(sys.flags.hash_randomization))"],
        capture_output=True,
        # Deliberately not ``check=True``: a nonzero exit *is* one of the three
        # outcomes being measured — the interpreter refusing to start under the
        # value — so a raise here would abort the sweep at the first value the
        # classifier is supposed to catch.
        check=False,
        env=_subprocess_env(value),
        text=True,
    )
    if result.returncode != 0:
        return "REJECT"
    return "OFF" if result.stdout.strip() == "0" else "ON"


@pytest.mark.skipif(not _can_spawn(), reason="cannot spawn a subprocess here")
def test_the_classifier_agrees_with_real_interpreters_on_every_value() -> None:
    # The test this module most needs, because the classifier is a *claim
    # about the runtime* and every other test above only checks it against
    # itself. The invariant is agreement in both directions: wherever the
    # interpreter refuses to boot the classifier must refuse too (never more
    # permissive), and wherever both accept, the classifier's PINNED verdict
    # must be exactly the interpreter's randomization-off.
    #
    # This is not hypothetical diligence — it is the test that caught three
    # real defects while this feature was being written: an out-of-range
    # integer past 4294967295 accepted as merely "unpinned" when the
    # interpreter rejects it outright, the "random" spelling refused as
    # unparseable when the interpreter accepts it, and a whitespace-only value
    # reported as the passing UNSET case when the interpreter refuses to start
    # under it. Each was a quiet misdescription of a deployment, which is the
    # one failure mode this category exists to prevent.
    disagreements: list[str] = []
    for value in _DIFFERENTIAL_CORPUS:
        try:
            classified = classify_hash_seed(value)
        except CanaryOrderError:
            classified = "REJECT"
        actual = _interpreter_verdict(value)

        if (classified == "REJECT") != (actual == "REJECT"):
            disagreements.append(
                f"{value!r}: classifier says {classified}, interpreter says {actual}"
            )
            continue
        if classified != "REJECT" and (classified == PINNED) != (actual == "OFF"):
            disagreements.append(
                f"{value!r}: classifier says {classified}, interpreter says {actual}"
            )
    assert not disagreements, "classifier disagrees with the interpreter:\n  " + "\n  ".join(
        disagreements
    )
