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

import sys

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
# validate_signal_signature — the tree, never the running module
# --------------------------------------------------------------------------
#
# bug_spec_signature_host_exec: the validator used to obtain the entrypoint by
# *executing* the source in the calling process, so every module-level
# statement of a model's answer ran with the orchestrator's environment,
# network and filesystem — before any sandbox, import screen or resource
# limit.  The tests in this section hold the fixed shape: the source is
# *parsed* (ast.parse) and the syntax tree inspected, and no part of it — not
# an import, not a call, not a loop, not a decorator, not an annotation — is
# ever executed, imported or evaluated host-side.


def test_module_level_side_effect_is_never_run(tmp_path):
    # The spec's own proof shape: a source whose module level writes a
    # sentinel file, and the file never appears.  The write sits inside a
    # module-level loop and a call, so the one sentinel proves all three
    # statement kinds stay unrun.  A conforming shape plus a hostile module
    # level must validate cleanly *without* the write happening — the write
    # is exactly what running the orchestrator's credentials and filesystem
    # out of the validator would look like.
    sentinel = tmp_path / "sentinel.txt"
    source = (
        "from pathlib import Path\n"
        "for attempt in range(3):\n"
        f"    Path({str(sentinel)!r}).write_text(f'side effect {{attempt}}')\n"
        "\n"
        "def signal(ctx, seed):\n"
        "    return ctx\n"
    )
    assert validate_signal_signature(source) == []
    assert not sentinel.exists()


def test_module_level_import_is_never_executed():
    # The import screen belongs to the sandbox, not to the validator: a
    # module-level ``import`` must not even load a module into this process.
    # ``colorsys`` is a stdlib leaf nothing here depends on, popped first so
    # the assertion is about this call alone.
    sys.modules.pop("colorsys", None)
    source = "import colorsys\n\ndef signal(ctx, seed):\n    return ctx\n"
    assert validate_signal_signature(source) == []
    assert "colorsys" not in sys.modules


def test_host_environment_is_never_read_during_validation(tmp_path, monkeypatch):
    # The credential-reach half of the bug: module-level code reading
    # ``os.environ`` must not run, so no NULLIUS_*_API_KEY can leave the
    # process through validation.  A marker variable — a value no real
    # credential ever holds — stands in for one; no network and no real
    # credential is touched anywhere in this suite.
    monkeypatch.setenv("NULLIUS_VALIDATOR_MARKER", "host-only-marker")
    leak = tmp_path / "leak.txt"
    source = (
        "import os\n"
        "from pathlib import Path\n"
        f"Path({str(leak)!r}).write_text("
        "os.environ.get('NULLIUS_VALIDATOR_MARKER', ''))\n"
        "\n"
        "def signal(ctx, seed):\n"
        "    return ctx\n"
    )
    assert validate_signal_signature(source) == []
    assert not leak.exists()


def test_raising_module_level_statement_does_not_crash_the_validator():
    # The exec path let a module-level raise escape the validator and take
    # the caller with it — the same class as the infinite loop that hangs
    # the orchestrator.  Reading the tree cannot raise the source's errors.
    source = "1 / 0\n\ndef signal(ctx, seed):\n    return ctx\n"
    assert validate_signal_signature(source) == []


def test_decorator_and_annotation_are_never_evaluated():
    # A decorator call and an annotation are expressions in the tree, not
    # code the validator owes an evaluation.  An unresolvable name in either
    # position must not escape the call: the exec path raised NameError out
    # of the validator for the decorator.
    source = (
        "@unknown_decorator\n"
        "def signal(ctx, seed) -> pl.Series:\n"
        "    return ctx\n"
    )
    assert validate_signal_signature(source) == []


def test_return_annotation_is_accepted_as_today():
    # The annotation half of the ABI is untouched: a present return
    # annotation is accepted exactly as before, whatever it names.
    source = (
        "import polars as pl\n"
        "\n"
        "def signal(ctx, seed) -> pl.Series:\n"
        "    return pl.Series([0.5, -0.5, 0.0])\n"
    )
    assert validate_signal_signature(source) == []


def test_async_entrypoint_is_refused():
    # The entrypoint is the *synchronous* def the sandbox invokes as
    # signal(window, seed); an ``async def`` would hand the sandbox a
    # coroutine instead of a series.  The scan looks for a module-level def,
    # so an async def leaves the source without the entrypoint the contract
    # names — the existing refusal sentence, vocabulary unchanged.
    problems = validate_signal_signature(
        "async def signal(ctx, seed):\n    return ctx\n"
    )
    assert len(problems) == 1
    assert "no 'signal' entrypoint" in problems[0]


def test_def_inside_a_module_level_if_is_not_the_entrypoint():
    # A def under an ``if`` is not a module-level def: whether it runs is a
    # runtime fact the tree cannot promise, and finding out would mean
    # executing the source — the very thing this validator must not do.  The
    # exec path defined it by running the branch; the tree-reading path
    # refuses instead of finding out.
    problems = validate_signal_signature(
        "if True:\n    def signal(ctx, seed):\n        return ctx\n"
    )
    assert len(problems) == 1
    assert "no 'signal' entrypoint" in problems[0]


def test_star_and_kwargs_extras_still_conform():
    # Parity with the inspect-based check the exec path used: ``*args`` and
    # ``**kwargs`` extras after the declared pair do not break the sandbox's
    # positional signal(window, seed) call, so they stay accepted.  (The
    # declared pair itself must be the two named parameters —
    # ``def signal(*args, seed)`` is refused by the window/seed checks
    # above.)
    star_args = "def signal(ctx, seed, *args):\n    return ctx\n"
    star_kwargs = "def signal(ctx, seed, **kwargs):\n    return ctx\n"
    assert validate_signal_signature(star_args) == []
    assert validate_signal_signature(star_kwargs) == []


def test_lambda_entrypoint_still_conforms():
    # A module-level lambda binding the entrypoint name with the declared
    # parameters is as conforming as the def: the sandbox looks the name up
    # and calls it, and could not tell the difference.
    assert validate_signal_signature("signal = lambda ctx, seed: ctx\n") == []


def test_last_binding_of_the_entrypoint_name_wins():
    # The module namespace the sandbox builds keeps the last binding the
    # source executes, so ``def signal`` twice means the second one; the
    # tree-reading path applies the same rule to the module body.
    good_then_conforming = (
        "def signal(ctx):\n    return ctx\n"
        "def signal(ctx, seed):\n    return ctx\n"
    )
    assert validate_signal_signature(good_then_conforming) == []

    conformed_then_broken = (
        "def signal(ctx, seed):\n    return ctx\n"
        "def signal(ctx):\n    return ctx\n"
    )
    problems = validate_signal_signature(conformed_then_broken)
    assert len(problems) == 1
    assert "must take an integer seed" in problems[0]


def test_import_binding_the_entrypoint_name_is_refused():
    # ``import os as signal`` binds the entrypoint name to a module: the
    # name is defined, and it is not the callable entrypoint.  A binding
    # that is not a def (or a lambda) is the existing not-callable refusal.
    problems = validate_signal_signature("import os as signal\n")
    assert len(problems) == 1
    assert "not callable" in problems[0]


def test_the_sandbox_load_path_helper_remains_available():
    # ``_require_signal_module`` is the sandbox's own child load path — the
    # one place agent source is *meant* to be materialised — and it stays
    # available for exactly that.  Pinned here so the fix cannot quietly
    # remove the door the sandbox opens; no host-side caller reaches it
    # anymore (validate_signal_signature reads the tree instead).
    from contract.signal import _require_signal_module

    module = _require_signal_module("def signal(ctx, seed):\n    return ctx\n")
    assert callable(module.signal)


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
