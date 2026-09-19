"""The signal entrypoint — feature 11 of app_spec.xml.

"System declares the signal entrypoint taking a :class:`~contract.MarketWindow`
plus an integer seed, which returns a Polars series indexed by symbol."

This suite pins the declaration from both halves:

* **the signature** — the entrypoint is a single named function with two
  parameters, the window then the seed, and the seed is *required* (a defaulted
  seed would let a signal sample randomness without naming its source, which
  defeats the determinism contract).  :func:`validate_signal_signature` is the
  positive check that agent-emitted source exposes it, so the suite drives it
  with real source strings — the shape the agent actually emits — and asserts
  the problem list is empty for a conforming signal and names the right defect
  for each malformed one.
* **the return shape** — "a Polars series indexed by symbol" is positional, not
  a labelled axis (Polars has no string index: no ``.index`` attribute, no
  ``index=`` kwarg, ``series["A"]`` raises).  So the *i*-th value is the score
  for the *i*-th symbol of the window's universe.  :func:`validate_signal_return`
  checks that a return is a ``polars.Series``, of floating dtype, of the right
  length, with every value finite — and the suite proves each independent check
  fires, plus that a conforming return is accepted.

Two design choices the suite refuses to let slip by untested:

* the validators **return problem lists, they do not raise** — a non-conforming
  return is a value the caller turns into whatever the run records, so the
  suite asserts the *list* shape and that an empty list means "conforms";
* the validators are **pure over (source, universe)** and never run the signal
  or reach the wall clock — the suite checks determinism by calling twice and
  getting identical results.

Feature 12 (which depends on this one) is the consumer that maps a
``wrong_length``/``absent_symbol`` problem onto a ``contract_violation``
outcome; this suite deliberately stops at "name the failure", so the two
features are pinned independently.
"""

from __future__ import annotations

import polars as pl
import pytest

from contract import (
    SIGNAL_ENTRYPOINT,
    SIGNAL_SEED_ARG,
    SIGNAL_SIGNATURE,
    SignalReturnProblem,
    SignalSignature,
    describe_signal_signature,
    validate_signal_return,
    validate_signal_signature,
)

UNIVERSE = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


# --------------------------------------------------------------------------
# The declared signature
# --------------------------------------------------------------------------


def test_signature_is_a_named_tuple_of_entrypoint_and_args():
    assert isinstance(SIGNAL_SIGNATURE, SignalSignature)
    assert SIGNAL_SIGNATURE.entrypoint == "signal"
    assert SIGNAL_SIGNATURE.window_arg == "ctx"
    assert SIGNAL_SIGNATURE.seed_arg == "seed"


def test_signature_constants_are_consistent():
    assert SIGNAL_ENTRYPOINT == "signal"
    assert SIGNAL_SEED_ARG == "seed"
    assert describe_signal_signature() == SIGNAL_SIGNATURE


def test_describe_returns_the_declared_signature():
    # describe_signal_signature is the callable surface a caller imports; it
    # returns the declared signature.  SignalSignature is an immutable
    # NamedTuple, so whether it hands back the shared constant or an equal
    # copy, a caller cannot mutate it — the identity is not part of the
    # contract, the value is.
    assert isinstance(describe_signal_signature(), SignalSignature)
    assert describe_signal_signature() == SIGNAL_SIGNATURE


# --------------------------------------------------------------------------
# validate_signal_signature — the source half
# --------------------------------------------------------------------------

GOOD_SIGNAL = """
def signal(ctx, seed):
    return ctx
"""

GOOD_SIGNAL_NAMED = """
def signal(ctx, seed):
    return pl.Series([0.0, 1.0, 2.0])
"""

GOOD_SIGNAL_WITH_OPTIONAL_EXTRA = """
def signal(ctx, seed, *, scale=1.0):
    return ctx
"""


def test_conforming_source_has_no_problems():
    assert validate_signal_signature(GOOD_SIGNAL) == []


def test_conforming_source_with_named_args_has_no_problems():
    assert validate_signal_signature(GOOD_SIGNAL_NAMED) == []


def test_optional_keyword_only_extra_is_accepted():
    # The sandbox calls signal(window, seed) positionally; an optional extra
    # does not break that call, so it conforms.
    assert validate_signal_signature(GOOD_SIGNAL_WITH_OPTIONAL_EXTRA) == []


def test_missing_entrypoint_is_reported():
    problems = validate_signal_signature("def not_signal(ctx, seed):\n    return ctx\n")
    assert len(problems) == 1
    assert "no 'signal' entrypoint" in problems[0]


def test_entrypoint_not_callable_is_reported():
    problems = validate_signal_signature("signal = 42\n")
    assert len(problems) == 1
    assert "not callable" in problems[0]


def test_wrong_window_arg_name_is_reported():
    problems = validate_signal_signature("def signal(window, seed):\n    return window\n")
    assert len(problems) == 1
    assert "ctx" in problems[0]


def test_missing_seed_is_reported():
    problems = validate_signal_signature("def signal(ctx):\n    return ctx\n")
    assert len(problems) == 1
    assert "seed" in problems[0]


def test_wrong_seed_arg_name_is_reported():
    problems = validate_signal_signature("def signal(ctx, random_state):\n    return ctx\n")
    assert len(problems) == 1
    assert "seed" in problems[0]


def test_defaulted_seed_is_reported():
    # A defaulted seed is the determinism hole: a signal can sample randomness
    # with the default and look identical at the call site to a seeded one.
    problems = validate_signal_signature("def signal(ctx, seed=0):\n    return ctx\n")
    assert len(problems) == 1
    assert "required" in problems[0]


def test_extra_required_argument_is_reported():
    problems = validate_signal_signature(
        "def signal(ctx, seed, lookback):\n    return ctx\n"
    )
    assert len(problems) == 1
    assert "more required arguments" in problems[0]


def test_syntax_error_is_reported_verbatim_shape():
    problems = validate_signal_signature("def signal(ctx, seed\n    return")
    assert len(problems) == 1
    assert "does not compile" in problems[0]


def test_validate_signature_does_not_execute_the_source():
    # The validator inspects, it does not run — running untrusted signal code
    # is the sandbox's job.  Prove it by making the body raise on execution;
    # a conforming *shape* with a body that would blow up must still pass.
    boom = "def signal(ctx, seed):\n    raise RuntimeError('executed!')\n"
    assert validate_signal_signature(boom) == []


def test_validate_signature_is_deterministic():
    # Pure over the source: two calls give identical results, so a replay
    # reaches the same verdict.
    assert validate_signal_signature(GOOD_SIGNAL) == validate_signal_signature(GOOD_SIGNAL)


# --------------------------------------------------------------------------
# validate_signal_return — the value half
# --------------------------------------------------------------------------


def test_conforming_return_has_no_problems():
    series = pl.Series("score", [0.1, -0.2, 0.5])
    assert validate_signal_return(series, UNIVERSE) == []


def test_empty_universe_with_empty_series_conforms():
    assert validate_signal_return(pl.Series("s", [], dtype=pl.Float64), ()) == []


def test_non_series_return_is_rejected_by_name():
    for bad in ([0.1, 0.2, 0.3], "not a series", {"a": 1}, None):
        problems = validate_signal_return(bad, UNIVERSE)
        assert len(problems) == 1
        assert problems[0].kind == "not_a_series"
        assert "polars.Series" in problems[0].message


def test_integer_dtype_is_rejected():
    problems = validate_signal_return(pl.Series([1, 2, 3]), UNIVERSE)
    assert len(problems) == 1
    assert problems[0].kind == "non_float_dtype"
    assert "Float64" in problems[0].message


def test_string_dtype_is_rejected():
    problems = validate_signal_return(pl.Series(["a", "b", "c"]), UNIVERSE)
    assert len(problems) == 1
    assert problems[0].kind == "non_float_dtype"


def test_wrong_length_is_reported():
    problems = validate_signal_return(pl.Series([1.0, 2.0]), UNIVERSE)
    assert len(problems) == 1
    assert problems[0].kind == "wrong_length"
    assert "3" in problems[0].message
    assert "2" in problems[0].message


def test_empty_series_against_nonempty_universe_is_wrong_length():
    problems = validate_signal_return(pl.Series("s", [], dtype=pl.Float64), UNIVERSE)
    assert len(problems) == 1
    assert problems[0].kind == "wrong_length"


def test_non_finite_values_are_reported_per_position():
    series = pl.Series([1.0, float("nan"), float("inf"), None])
    problems = validate_signal_return(series, ("A", "B", "C", "D"))
    kinds = [p.kind for p in problems]
    assert kinds == ["non_finite_value", "non_finite_value", "non_finite_value"]
    # Each names the offending symbol via the positional pairing.
    assert problems[0].symbol == "B"
    assert problems[1].symbol == "C"
    assert problems[2].symbol == "D"


def test_length_check_wins_over_finiteness_check():
    # A length mismatch means positions cannot be aligned to symbols, so the
    # validator reports only the length problem — not a finiteness problem for
    # a value that cannot be mapped to a symbol.
    series = pl.Series([float("nan")])
    problems = validate_signal_return(series, ())
    assert [p.kind for p in problems] == ["wrong_length"]


def test_wrong_length_short_circuits_per_value_checks():
    # A length mismatch means positions cannot be aligned to symbols, so the
    # validator reports only the length problem, not a problem per value.
    series = pl.Series([1.0, float("nan")])
    problems = validate_signal_return(series, ("A", "B", "C"))
    assert [p.kind for p in problems] == ["wrong_length"]


def test_return_problem_is_a_frozen_dataclass():
    problem = SignalReturnProblem(kind="not_a_series", message="nope")
    assert problem.symbol is None
    with pytest.raises(Exception):  # frozen: cannot be mutated after construction
        problem.kind = "other"  # type: ignore[misc]


def test_return_problem_carries_symbol_for_absent_symbol_kind():
    problem = SignalReturnProblem(kind="absent_symbol", message="x", symbol="DOGEUSDT")
    assert problem.symbol == "DOGEUSDT"


def test_validate_return_is_deterministic():
    series = pl.Series([1.0, 2.0, 3.0])
    assert validate_signal_return(series, UNIVERSE) == validate_signal_return(series, UNIVERSE)


# --------------------------------------------------------------------------
# The two halves compose: a full conforming signal round-trips through both
# --------------------------------------------------------------------------


def test_a_real_signal_passes_both_validators():
    code = """
import polars as pl

def signal(ctx, seed):
    return pl.Series([0.5, -0.5, 0.0])
"""
    assert validate_signal_signature(code) == []

    namespace: dict = {}
    exec(compile(code, "<t>", "exec"), namespace)
    result = namespace["signal"](None, 0)
    assert validate_signal_return(result, UNIVERSE) == []
