"""Bit-identity across two runs of one seeded signal — feature 145.

These tests pin :mod:`canary._reproducibility` — the byte comparison
feature 145's sentence is, and the refusals that keep it an *assertion*
rather than a summary. The properties under test are the ones the
module docstring argues:

* the verdict is over bytes, not floats — ``0.0`` against ``-0.0`` is a
  divergence, and a payload of NaNs compares equal to itself;
* the comparison *returns* a result (the feature's own clause) and the
  raising spelling is a wrapper over the same comparison, not a second
  assertion;
* a divergence is reported actionably — digests, lengths, the offset of
  the first differing byte and the count — because §15's recovery is
  "halt dreaming; bisect the image diff";
* a run that cannot execute, and a run that returns something other
  than bytes, are refused as the caller's error rather than reported as
  non-determinism.

The signals below are real callables, not mocks: the point of the
feature is that two calls of one callable with one seed agree, so the
deterministic cases use a genuinely seeded ``random.Random`` and a
genuinely re-computed panel, and the divergent cases use one whose
output depends on something other than its seed.
"""

from __future__ import annotations

import dataclasses
import hashlib
import random

import pytest
from canary import (
    HASH_SEED_ENV,
    PINNED,
    PINNED_SEED,
    BitReproducibility,
    ByteComparison,
    CanaryError,
    CanaryImageError,
    CanaryOrderError,
    CanaryReproducibilityError,
    CanaryService,
    assert_bit_identical,
    compare_bytes,
    compare_runs,
    require_identical,
    require_stable_environment,
)
from conftest import (  # type: ignore[import-not-found] - suite-local fixture module
    PINNED_EVALUATOR_DIGEST,
)


#: Two runs of one seeded signal, as a signal that actually is one: a
#: ``random.Random`` built from the seed, a panel of floats computed from
#: it, and the panel serialized in a fixed spelling. Re-running it with
#: the same seed must reproduce the bytes exactly, which is the property
#: feature 11's "the seed is the only argument that carries randomness"
#: buys — and re-running it with a *different* seed must not, which is
#: what makes the passing cases below non-vacuous.
def _seeded_signal(seed: int) -> bytes:
    rng = random.Random(seed)
    panel = [round(rng.gauss(0.0, 1.0), 12) for _ in range(64)]
    return ("\n".join(repr(value) for value in panel)).encode("utf-8")


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# -- The feature's verb: two runs of one seeded signal ----------------------


def test_two_runs_of_one_seeded_signal_are_bit_identical() -> None:
    # The feature's sentence itself, and the verdict is the byte-level
    # result it promises.
    comparison = compare_runs(_seeded_signal, 1234)
    assert isinstance(comparison, ByteComparison)
    assert comparison.identical is True
    assert comparison.ok is True
    assert comparison.seed == 1234
    assert comparison.field == "output"
    assert comparison.left_digest == comparison.right_digest
    assert comparison.left_digest == _digest(_seeded_signal(1234))
    assert comparison.first_difference is None
    assert comparison.differing_bytes == 0


def test_the_passing_case_is_not_vacuous() -> None:
    # A different seed produces different bytes, so "identical" above is
    # a statement about the seed rather than about signals that ignore
    # their input.
    assert _seeded_signal(1234) != _seeded_signal(1235)


def test_the_same_seed_is_handed_to_both_runs() -> None:
    # The one argument the check controls: the signal is asked for the
    # same seed twice, so any difference between the runs came from the
    # signal and not from the harness re-seeding it.
    seeds: list[int] = []

    def recording(seed: int) -> bytes:
        seeds.append(seed)
        return b"constant"

    compare_runs(recording, 7)
    assert seeds == [7, 7]


def test_a_deterministic_signal_over_a_real_panel_agrees() -> None:
    # A slightly more signal-shaped case: a z-scored panel computed in a
    # fixed reduction order (an explicit sort before the sum, §12's
    # "stable iteration order") is bit-identical across two runs, which
    # is the shape a real node's output takes.
    def panel(seed: int) -> bytes:
        rng = random.Random(seed)
        raw = {f"SYM{index:03d}": rng.gauss(0.0, 1.0) for index in range(128)}
        ordered = sorted(raw.items())
        values = [value for _, value in ordered]
        mean = sum(values) / len(values)
        spread = (sum((value - mean) ** 2 for value in values) / len(values)) ** 0.5
        return repr(
            [(symbol, (value - mean) / spread) for symbol, value in ordered]
        ).encode("utf-8")

    assert compare_runs(panel, 42).identical


def test_assert_bit_identical_returns_the_verdict() -> None:
    # The raising spelling and the returning spelling chain the same
    # value: a caller can assert and still hold the digest for its
    # record, rather than running the comparison twice.
    comparison = assert_bit_identical(_seeded_signal, 1234)
    assert comparison.identical
    assert comparison == compare_runs(_seeded_signal, 1234)


def test_a_divergent_signal_is_refused_by_the_assertion() -> None:
    # A signal whose output depends on something other than its seed —
    # here a counter, standing in for any unseeded source of randomness,
    # clock read or mutated global. This is the failure §12 says never
    # announces itself, arriving through the surface a nightly runner
    # holds.
    counter = {"n": 0}

    def divergent(seed: int) -> bytes:
        counter["n"] += 1
        return f"run {counter['n']}".encode()

    with pytest.raises(CanaryReproducibilityError) as raised:
        assert_bit_identical(divergent, 5)
    assert "not bit-identical" in str(raised.value)
    assert "seed 5" in str(raised.value)


def test_the_divergence_is_returned_rather_than_raised_by_compare_runs() -> None:
    # "which returns a byte-level comparison result" — the comparison is
    # a value, so a caller filing one line per field gets a verdict for
    # every field instead of an exception on the first.
    counter = {"n": 0}

    def divergent(seed: int) -> bytes:
        counter["n"] += 1
        return f"run {counter['n']}".encode()

    comparison = compare_runs(divergent, 5)
    assert comparison.identical is False
    assert comparison.ok is False
    assert comparison.left_digest != comparison.right_digest


def test_a_signal_that_cannot_run_propagates_its_own_error() -> None:
    # A run that could not execute has said nothing about determinism;
    # reporting it as a divergence would blame the machine for the
    # signal's bug.
    def broken(seed: int) -> bytes:
        raise ZeroDivisionError("the signal is wrong, not the canary")

    with pytest.raises(ZeroDivisionError):
        compare_runs(broken, 1)


# -- The comparison is over bytes, not over numbers -------------------------


def test_signed_zero_is_a_divergence() -> None:
    # The positive zero and the negative zero are the same number and
    # different bytes. A tolerance-based check (``isclose``) would call
    # these equal; "bit-identical" is the word the feature uses, and it
    # does not.
    comparison = compare_bytes(b"\x00\x00\x00\x00", b"\x80\x00\x00\x00")
    assert comparison.identical is False
    assert comparison.first_difference == 0
    assert comparison.differing_bytes == 1


def test_a_single_low_bit_is_a_divergence() -> None:
    # The smallest divergence a reassociated float reduction produces:
    # one byte, one bit, in an otherwise identical panel.
    left = b"score panel, 128 symbols" + b"\x3f\x80\x00\x00"
    right = b"score panel, 128 symbols" + b"\x3f\x80\x00\x01"
    comparison = compare_bytes(left, right)
    assert comparison.identical is False
    assert comparison.first_difference == len(b"score panel, 128 symbols") + 3
    assert comparison.differing_bytes == 1


def test_a_panel_of_nans_compares_equal_to_itself() -> None:
    # NaN does not equal itself, so a float-wise comparison of two
    # identical NaN-bearing panels reports a divergence that is not
    # there. Bytes have no such opinion.
    nan_panel = b"\x7f\xc0\x00\x00" * 32
    assert compare_bytes(nan_panel, nan_panel).identical is True
    # And the assertion agrees with the comparison here — the two
    # spellings cannot disagree about the same bytes.
    assert assert_bit_identical(lambda seed: nan_panel, 0).identical


def test_different_lengths_are_reported_as_such() -> None:
    # A length that moved is not a rounding difference: the run
    # produced a different result set.
    comparison = compare_bytes(b"abc", b"abcd")
    assert comparison.identical is False
    assert comparison.left_length == 3
    assert comparison.right_length == 4
    # The missing byte is the first difference — the place it would
    # have been — and it counts as one differing position.
    assert comparison.first_difference == 3
    assert comparison.differing_bytes == 1


def test_a_prefix_diverges_at_the_point_it_stops_being_one() -> None:
    comparison = compare_bytes(b"abcd", b"abce")
    assert comparison.first_difference == 3
    assert comparison.differing_bytes == 1


def test_differing_lengths_with_a_differing_interior_are_both_counted() -> None:
    # The offset is where the runs first disagree; the count is how much
    # of the rest disagrees, including the positions only one run has.
    comparison = compare_bytes(b"aXc", b"aYcde")
    assert comparison.first_difference == 1
    assert comparison.differing_bytes == 3  # X≠Y, plus the two missing bytes


def test_the_longer_run_on_the_left_is_counted_the_same_way() -> None:
    # The mirror of the case above. The "past the shorter run" offset is
    # the *shorter* length on either side (``min``, not the left one), so
    # a run that produced too much reports the same way as one that
    # produced too little — asymmetry here would make the verdict depend
    # on which of the two calls the caller happened to name "run 1".
    comparison = compare_bytes(b"aYcde", b"aXc")
    assert comparison.identical is False
    assert comparison.left_length == 5
    assert comparison.right_length == 3
    assert comparison.first_difference == 1
    assert comparison.differing_bytes == 3


def test_a_divergence_at_the_far_end_of_a_real_sized_panel_is_located() -> None:
    # A score panel is not four bytes, and the scan is an all-Python pass
    # that runs only after the verdict is already "no". This pins that it
    # reaches the far end: the last byte of a 200 KB payload is reported
    # at its own offset rather than truncated or silently missed.
    big = b"\x00" * 200_000
    comparison = compare_bytes(big, big[:-1] + b"\x01")
    assert comparison.identical is False
    assert comparison.first_difference == 199_999
    assert comparison.differing_bytes == 1
    assert comparison.left_length == comparison.right_length == 200_000


def test_an_early_divergence_does_not_report_the_matching_tail() -> None:
    # The count is of positions that *differ*, not of bytes scanned: a
    # single flipped bit near the front of an otherwise identical panel
    # is one differing position, which is what tells an operator this is a
    # reassociated reduction rather than a different computation.
    panel = b"\xab" * 4_096
    comparison = compare_bytes(panel, b"\xab\xac" + panel[2:])
    assert comparison.first_difference == 1
    assert comparison.differing_bytes == 1


def test_an_empty_run_compares_equal_to_an_empty_run() -> None:
    # A signal that produced nothing twice has produced the same thing
    # twice; the emptiness is not the comparison's business.
    assert compare_bytes(b"", b"").identical is True


def test_an_empty_run_against_a_non_empty_one_diverges() -> None:
    comparison = compare_bytes(b"", b"a")
    assert comparison.identical is False
    assert comparison.first_difference == 0
    assert comparison.differing_bytes == 1


def test_the_verdict_carries_what_a_bisect_needs() -> None:
    # §15's recovery from this failure is "halt dreaming; bisect the
    # image diff", and bisecting starts from the offset. Everything the
    # message names is a field, so a caller can act on the record
    # without parsing the sentence.
    comparison = compare_bytes(b"aaaa", b"aaba", field="score_panel", seed=99)
    assert comparison.field == "score_panel"
    assert comparison.seed == 99
    assert comparison.first_difference == 2
    assert comparison.differing_bytes == 1
    message = comparison.message
    assert "score_panel" in message
    assert "seed 99" in message
    assert str(comparison.first_difference) in message
    assert comparison.left_digest in message
    assert comparison.right_digest in message


# -- The verdict record ------------------------------------------------------


def test_a_passing_verdict_messages_the_shared_digest_and_length() -> None:
    comparison = compare_bytes(b"panels", b"panels")
    assert "bit-identical" in comparison.message
    assert comparison.left_digest in comparison.message
    assert "6 byte(s)" in comparison.message


def test_the_verdict_is_frozen_and_hashable() -> None:
    comparison = compare_bytes(b"a", b"b")
    with pytest.raises(dataclasses.FrozenInstanceError):
        comparison.identical = True  # type: ignore[misc]
    # Hashable: a verdict can be filed in a set or used as a key without
    # the caller rebuilding it.
    assert comparison in {comparison}


def test_a_verdict_whose_digests_disagree_cannot_claim_identity() -> None:
    # The one shape that would make the record lie to the operator
    # reading it: two different digests under a passing verdict. §12's
    # whole point is that non-determinism does not announce itself, so a
    # self-contradicting verdict is refused rather than filed.
    with pytest.raises(CanaryReproducibilityError, match="digests differ"):
        ByteComparison(
            field="output",
            identical=True,
            left_digest="a" * 64,
            right_digest="b" * 64,
            left_length=1,
            right_length=1,
            first_difference=None,
            differing_bytes=0,
        )


def test_a_verdict_whose_digests_agree_cannot_claim_divergence() -> None:
    with pytest.raises(CanaryReproducibilityError, match="hash equally"):
        ByteComparison(
            field="output",
            identical=False,
            left_digest="a" * 64,
            right_digest="a" * 64,
            left_length=1,
            right_length=1,
            first_difference=0,
            differing_bytes=1,
        )


def test_a_divergence_must_name_where_it_starts_and_how_much_differs() -> None:
    with pytest.raises(CanaryReproducibilityError, match="must name where"):
        ByteComparison(
            field="output",
            identical=False,
            left_digest="a" * 64,
            right_digest="b" * 64,
            left_length=1,
            right_length=1,
            first_difference=None,
            differing_bytes=0,
        )


@pytest.mark.parametrize(
    "digest",
    ["a" * 63, "a" * 65, "SHA256:" + "a" * 64, "A" * 64, "z" * 64],
    ids=["short", "long", "prefixed", "uppercase", "non-hex"],
)
def test_a_digest_that_names_no_run_is_refused(digest: str) -> None:
    # Bare lowercase hex, matching the workspace's other content hashes
    # (snapshot's ``sha256_file``); the ``sha256:``-prefixed spelling
    # belongs to an image *reference* and is refused here so a report
    # cannot show a run digest where an image digest belongs.
    with pytest.raises(CanaryReproducibilityError, match="lowercase hex"):
        ByteComparison(
            field="output",
            identical=True,
            left_digest=digest,
            right_digest=digest,
            left_length=1,
            right_length=1,
            first_difference=None,
            differing_bytes=0,
        )


def test_a_negative_length_is_refused() -> None:
    with pytest.raises(CanaryReproducibilityError, match="non-negative"):
        ByteComparison(
            field="output",
            identical=True,
            left_digest="a" * 64,
            right_digest="a" * 64,
            left_length=-1,
            right_length=1,
            first_difference=None,
            differing_bytes=0,
        )


@pytest.mark.parametrize("field", ["", "   "], ids=["empty", "blank"])
def test_a_verdict_that_cannot_name_what_it_compared_is_refused(field: str) -> None:
    with pytest.raises(CanaryReproducibilityError, match="non-empty string"):
        compare_bytes(b"a", b"a", field=field)


# -- The strict spelling -----------------------------------------------------


def test_require_identical_returns_the_verdict_it_asserted() -> None:
    comparison = compare_bytes(b"same", b"same")
    assert require_identical(comparison) is comparison


def test_require_identical_raises_with_the_verdict_message() -> None:
    comparison = compare_bytes(b"left", b"right")
    with pytest.raises(CanaryReproducibilityError) as raised:
        require_identical(comparison)
    assert str(raised.value) == comparison.message


def test_require_identical_refuses_a_value_that_never_compared_anything() -> None:
    # Reporting a broken call site as a divergence would put it in the
    # same class as a broken run, which is the one distinction §15's
    # recovery depends on.
    with pytest.raises(CanaryReproducibilityError, match="has not compared"):
        require_identical(True)  # type: ignore[arg-type]


# -- Refusing what cannot be compared ----------------------------------------


@pytest.mark.parametrize(
    "value",
    ["a string", ["a", "list"], 5, None, memoryview(b"x")],
    ids=["str", "list", "int", "none", "memoryview"],
)
def test_a_run_that_did_not_produce_bytes_is_refused(value: object) -> None:
    # A comparison over bytes is undefined over anything else — not
    # false — so the caller learns where to serialize rather than
    # reading a TypeError raised from inside the scan.
    with pytest.raises(CanaryReproducibilityError, match="not bytes"):
        compare_runs(lambda seed: value, 1)  # type: ignore[arg-type,return-value]


def test_the_non_bytes_refusal_names_the_run_and_the_type() -> None:
    with pytest.raises(CanaryReproducibilityError) as raised:
        compare_bytes(b"ok", "not bytes")  # type: ignore[arg-type]
    message = str(raised.value)
    assert "second run" in message
    assert "str" in message
    assert "Serialize" in message


@pytest.mark.parametrize(
    "value",
    [bytearray(b"ab"), memoryview(b"ab")],
    ids=["bytearray", "memoryview"],
)
def test_a_byte_like_view_is_refused_rather_than_silently_coerced(
    value: object,
) -> None:
    # ``bytearray`` and ``memoryview`` compare equal to ``bytes`` in
    # Python, so a comparison that accepted them would *work* — and would
    # be comparing a mutable buffer whose contents a caller could change
    # between the hash and the scan. The unit of this comparison is stated
    # at the call site by the caller converting once, not inferred here
    # from whatever a run happened to hand back.
    with pytest.raises(CanaryReproducibilityError, match="not bytes"):
        compare_bytes(b"ab", value)  # type: ignore[arg-type]


def test_a_non_callable_signal_is_refused() -> None:
    with pytest.raises(CanaryReproducibilityError, match="must be callable"):
        compare_runs(b"already run", 1)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "seed",
    [None, "1234", 1.5, True],
    ids=["none", "string", "float", "bool"],
)
def test_a_seed_that_is_not_an_integer_is_refused(seed: object) -> None:
    # A seed of True is a broken caller, not a seed of 1 — and the seed
    # is the run's *only* source of randomness (feature 11), so a seed
    # that is not an integer makes the assertion meaningless.
    with pytest.raises(CanaryReproducibilityError, match="must be an integer"):
        compare_runs(_seeded_signal, seed)  # type: ignore[arg-type]


def test_a_negative_seed_is_accepted() -> None:
    # Nothing in the system assigns seeds by index, and Python's own
    # ``random.seed`` takes negative integers.
    assert compare_runs(_seeded_signal, -7).identical


# -- The seam's strength: why the callable is injected ----------------------
#
# The module docstring's load-bearing claim is that the callable seam is
# where the *strength* of the check is chosen, and that a caller wanting the
# second run in a second interpreter expresses that by handing in a spawning
# callable. The two tests below are that claim, measured — because a claim
# about what a check can catch is exactly the kind that is easy to assert and
# wrong. Each is skipped if this interpreter cannot spawn, so the suite stays
# runnable in a sandbox that forbids subprocesses.

#: A signal whose output depends on the *string hash seed* rather than on
#: the argument it is handed: it reduces over a ``set`` of strings, whose
#: iteration order Python varies per interpreter under hash randomization.
#: This is §12's "Stable iteration order | PYTHONHASHSEED=0; explicit sorts
#: before every reduction" row, in its most common real form.
_SET_ORDER_SOURCE = (
    "import sys\n"
    "symbols = {f'SYM{i}' for i in range(20)}\n"
    "sys.stdout.buffer.write(','.join(symbols).encode())\n"
)


def _spawning_signal(*, pin_hash_seed: bool) -> object:
    """A ``SeededSignal`` whose every run is a *fresh interpreter*.

    The analyzing seam the module docstring describes: the caller closes
    over the window, the payload and the serialization, and — here — over
    the process boundary. ``pin_hash_seed`` reproduces §12's remedy so the
    same seam can be shown to go green.
    """
    import os
    import subprocess
    import sys

    def run(seed: int) -> bytes:
        env = dict(os.environ)
        if pin_hash_seed:
            env["PYTHONHASHSEED"] = "0"
        else:
            env.pop("PYTHONHASHSEED", None)
        return subprocess.run(
            [sys.executable, "-c", _SET_ORDER_SOURCE],
            capture_output=True,
            env=env,
            check=True,
        ).stdout

    return run


def _can_spawn() -> bool:
    import subprocess
    import sys

    try:
        subprocess.run(
            [sys.executable, "-c", "pass"], capture_output=True, timeout=30, check=True
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - sandboxed
        return False
    return True


@pytest.mark.skipif(not _can_spawn(), reason="cannot spawn a subprocess here")
def test_an_in_process_pair_cannot_catch_hash_order_non_determinism() -> None:
    # The reason the seam exists is that the *default* reading — two calls
    # in one interpreter — is genuinely weaker: both calls share one hash
    # seed, so a signal whose output depends on set iteration order looks
    # perfectly deterministic. This is what makes the spawning variant
    # below a real strengthening rather than a stylistic preference.
    def in_process(seed: int) -> bytes:
        symbols = {f"SYM{index}" for index in range(20)}
        return ",".join(symbols).encode()

    # Non-vacuous: the set's order is stable within one interpreter...
    assert compare_runs(in_process, 1).identical


@pytest.mark.skipif(not _can_spawn(), reason="cannot spawn a subprocess here")
def test_the_spawning_seam_catches_what_the_in_process_pair_cannot() -> None:
    # The claim, measured: with each run in its own interpreter the hash
    # seed differs between them, the set iterates in a different order, and
    # the byte comparison catches it.
    comparison = compare_runs(_spawning_signal(pin_hash_seed=False), 1)  # type: ignore[arg-type]
    assert comparison.identical is False
    assert comparison.differing_bytes > 0


@pytest.mark.skipif(not _can_spawn(), reason="cannot spawn a subprocess here")
def test_the_spawning_seam_goes_green_under_the_remedy_section_12_names() -> None:
    # §12's row for this failure is "PYTHONHASHSEED=0; explicit sorts before
    # every reduction". Pinning the seed through the same spawning seam
    # makes the check pass — which is what closes the loop: the check
    # detects the failure it is for, and stops detecting it once the
    # documented remedy is applied.
    comparison = compare_runs(_spawning_signal(pin_hash_seed=True), 1)  # type: ignore[arg-type]
    assert comparison.identical is True


# -- The discoverable seam: the composed component carries the check --------


def test_the_facade_delegates_to_the_same_functions() -> None:
    # The facade is *thin*: each method is one call to the function that
    # owns the comparison, so the two paths cannot disagree about what
    # "identical" means. A second implementation of the byte scan is
    # exactly what this package's one-provenance rule forbids.
    reproducibility = BitReproducibility()
    assert reproducibility.assert_identical(_seeded_signal, 3) == assert_bit_identical(
        _seeded_signal, 3
    )
    assert reproducibility.run(_seeded_signal, 3) == compare_runs(_seeded_signal, 3)
    assert reproducibility.bytes(b"a", b"b") == compare_bytes(b"a", b"b")
    # Feature 138's verdict is exposed here too, and it delegates as well:
    # the byte check and the order check must not disagree about what a
    # pin is, so there is one implementation of the sweep between them.
    assert reproducibility.order({}) == require_stable_environment({})


def test_the_facade_delegates_the_order_check_to_the_one_sweep() -> None:
    # The reason feature 138's verdict sits on this facade: a bit-identity
    # check is only as strong as the environment the two runs shared, and
    # a caller whose comparison came back ``identical`` needs to know
    # whether the seed was pinned or whether both runs simply shared an
    # unpinned one. Same function, so the two members cannot disagree.
    reproducibility = BitReproducibility()
    with pytest.raises(CanaryOrderError, match="not the pin"):
        reproducibility.order({HASH_SEED_ENV: "1"})
    assert reproducibility.order({HASH_SEED_ENV: PINNED_SEED}).seed == PINNED


def test_the_facade_refuses_a_divergence_on_the_asserting_method() -> None:
    counter = {"n": 0}

    def divergent(seed: int) -> bytes:
        counter["n"] += 1
        return f"run {counter['n']}".encode()

    reproducibility = BitReproducibility()
    with pytest.raises(CanaryReproducibilityError, match="not bit-identical"):
        reproducibility.assert_identical(divergent, 5)
    # ... and reports it as a value on the returning one. Same signal,
    # two spellings, one comparison.
    assert reproducibility.run(divergent, 5).identical is False


def test_the_facade_compares_payloads_the_caller_already_holds() -> None:
    # The recorded-vs-replayed path: two persisted payloads read back from
    # the artifact store, compared by the same function the fresh-run path
    # funnels through.
    reproducibility = BitReproducibility()
    recorded = b"a materialized score panel"
    comparison = reproducibility.bytes(recorded, recorded, field="score_panel")
    assert comparison.identical is True
    assert comparison.field == "score_panel"


def test_the_facade_carries_no_state() -> None:
    # Stateless by construction — an empty ``__slots__`` and no
    # ``__init__`` — which is the honest shape for a check that is a pure
    # function of its inputs: two callers comparing two candidates can
    # never observe each other, and there is no setting a deployment could
    # get wrong.
    reproducibility = BitReproducibility()
    assert BitReproducibility.__slots__ == ()
    assert not hasattr(reproducibility, "__dict__")
    assert reproducibility.assert_identical(_seeded_signal, 1).identical


def test_the_composed_service_exposes_the_check_beside_the_sweep(
    canary_env: dict[str, str],
) -> None:
    # Feature 145 through the composed component: one value carries the
    # whole category's assertions, so a caller holding the composed canary
    # reaches the check without importing submodules by name.
    service = CanaryService(env=canary_env)
    assert isinstance(service.reproducibility, BitReproducibility)
    assert service.reproducibility.assert_identical(_seeded_signal, 11).identical
    # ... and the pin sweep is still its own verb, unchanged.
    assert service.containers["evaluator"].digest == PINNED_EVALUATOR_DIGEST


def test_the_check_does_not_require_a_pinned_deployment() -> None:
    # Deliberately unlike ``containers``: this check reads no environment,
    # so a deployment whose pins are unset is still perfectly able to
    # learn that its bytes diverged. The two are different failures with
    # different repairs, and a caller must not have to fix one to see the
    # other.
    service = CanaryService(env={})
    assert service.reproducibility.assert_identical(_seeded_signal, 4).identical
    with pytest.raises(CanaryImageError, match="is not set"):
        service.containers  # noqa: B018 - the property raises; that is the point


# -- The taxonomy ------------------------------------------------------------


def test_the_reproducibility_refusal_is_a_canary_error_but_not_an_image_error() -> None:
    # A deployment can be perfectly pinned and still emit different
    # bytes twice, and the two repairs differ (re-pin an image vs
    # bisect a diff), so a caller must be able to tell them apart.
    assert issubclass(CanaryReproducibilityError, CanaryError)
    from canary import CanaryImageError

    assert not issubclass(CanaryReproducibilityError, CanaryImageError)
    assert not issubclass(CanaryImageError, CanaryReproducibilityError)
