"""The signal entrypoint — the shape an LLM-authored signal must have.

Feature 11 of app_spec.xml: "System declares the signal entrypoint taking a
:class:`~contract.window.MarketWindow` plus an integer seed, which returns a
Polars series indexed by symbol".  This module is that declaration, made
concrete and checkable.

The signature the system runs is fixed (docs/nullius-tech-architecture.md
§5.1)::

    def signal(ctx: MarketWindow, seed: int) -> pl.Series:
        ...

Three words in the feature carry the design, and each has a consequence this
module enforces or records:

*signal entrypoint*
    A node is a single function with a single, well-known name.  The sandbox
    (architecture §5.2) executes it by name — ``entrypoint="signal"`` — so the
    name is part of the contract, not a convention a signal may choose.  It is
    pinned here as :data:`SIGNAL_ENTRYPOINT` so the sandbox, the agent and the
    validator all read it from one place rather than each spelling it.

*taking a MarketWindow plus an integer seed*
    The window is the only argument that carries data, and the seed is the
    only argument that carries randomness.  That pair is the entire surface a
    signal may reach for: no clock, no filesystem, no network, no global
    state — the purity the evaluator relies on to replay a node to a
    bit-identical score (architecture §5.1, the determinism contract).  The
    seed is *required*, not defaulted: a signal that sampled randomness with a
    default seed would look identical at the call site to one that did not,
    and determinism would be a hope rather than a signature.  Requiring it
    forces every signal to name its source of randomness explicitly.

*returns a Polars series indexed by symbol*
    This is the half that needs stating, because Polars does not have a
    string index.  A :class:`polars.Series` is a positional vector: it has no
    ``index`` attribute, no ``index=`` constructor keyword, and ``series["A"]``
    raises.  So "indexed by symbol" cannot mean a labelled axis the way it
    would in pandas — it means the *i*-th value is the score for the *i*-th
    symbol of ``ctx.universe``.  The window carries the labels; the series
    carries the values; the pairing is positional and the order is the
    window's own stable ordering (feature 13's sorted universe, feature 46's
    stable ordering).  :func:`validate_signal_return` is what makes that
    pairing checkable: it walks the returned values against the universe the
    window reports, which is exactly the check feature 12 performs.

The validator is a *positive* declaration of conformance, deliberately not a
rejection path.  Feature 11 says the system *declares* the entrypoint and its
return shape; feature 12 (which depends on this one) says the system
*rejects* a return whose index names a symbol absent from the universe and
*emits a contract_violation outcome*.  Those are downstream, evaluator-side
consequences, so this module names the failure but does not raise it — it
returns a structured :class:`SignalReturnProblem` the caller is free to turn
into whatever outcome the run records.  Splitting "what is a conforming
return" (here) from "what happens to a non-conforming one" (feature 12) keeps
this module import-safe and side-effect free, and keeps the two features from
editing each other.

**The layering note, and it is load-bearing.**  This module imports
``polars`` lazily, on the same seam :func:`contract._arrow.require_arrow`
opens for pyarrow.  The ``contract`` package is imported by the application
factory's workspace scan, so anything it imports at module scope is imported
during composition; a hard ``import polars`` here would make polars a
precondition for *composing the application*, which is a far larger blast
radius than feature 11 needs — the entrypoint name, the signature and the
validator's *shape* are all expressible without a single float.  Deferring
the import keeps the member import-safe in exactly the environments the
workspace contract promises one will be (factory scan, test sandbox,
deterministic replay path) while the validator, which genuinely inspects a
Polars series, names the missing dependency the moment it is reached without
it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, NamedTuple

if TYPE_CHECKING:  # pragma: no cover - typing only; polars is deferred to runtime
    import polars as pl

__all__ = [
    "SIGNAL_ENTRYPOINT",
    "SIGNAL_SEED_ARG",
    "SignalReturnProblem",
    "SignalSignature",
    "describe_signal_signature",
    "validate_signal_return",
]

#: The function name the sandbox executes a node's code under.  Part of the
#: contract, not a convention: architecture §5.2 runs ``entrypoint="signal"``
#: against ``node.code``, so the agent must emit a function with exactly this
#: name and the sandbox must look for exactly this name.  Declared once so the
#: agent, the sandbox and :func:`validate_signal_signature` cannot drift apart
#: over a spelling.
SIGNAL_ENTRYPOINT = "signal"

#: The name of the integer seed argument.  The seed is the only argument that
#: carries randomness into an otherwise pure function, so its position and
#: name are fixed: a signal that reads it as anything else is not the entry
#: point the sandbox invokes.  Kept beside :data:`SIGNAL_ENTRYPOINT` so the
#: two halves of the signature — the name and its second parameter — share
#: one source of truth.
SIGNAL_SEED_ARG = "seed"


class SignalSignature(NamedTuple):
    """The declared shape of a signal entrypoint.

    A value object, not a live callable: it is what a node's source is checked
    against, and what the sandbox's entrypoint lookup is pinned to.  The three
    fields are the whole contract — the name the sandbox executes, the window
    parameter name, and the seed parameter name — and nothing else, because a
    signal's conformance is fully described by "does it expose this function
    with these two arguments".
    """

    entrypoint: str
    window_arg: str
    seed_arg: str


#: The one signature the system accepts.  The window argument is named
#: ``ctx`` to match the documentation every signal is written against
#: (architecture §5.1, the PRD's ``def signal(ctx: MarketWindow)``), and the
#: seed argument after :data:`SIGNAL_SEED_ARG`.  A single shared instance,
#: because the signature is a constant of the contract, not something a caller
#: constructs.
SIGNAL_SIGNATURE = SignalSignature(
    entrypoint=SIGNAL_ENTRYPOINT,
    window_arg="ctx",
    seed_arg=SIGNAL_SEED_ARG,
)


def describe_signal_signature() -> SignalSignature:
    """Return the signal entrypoint's declared signature.

    Exposed as a function rather than exporting :data:`SIGNAL_SIGNATURE`
    directly so the contract's advertised surface stays a set of callables —
    the same shape every other "what does the system declare" accessor takes —
    and so a caller asking "what must my signal look like" gets one answer
    from one place, rather than reading a module global it could not have
    known to import.
    """
    return SIGNAL_SIGNATURE


def _require_signal_module(code: str) -> Any:
    """Import the agent-emitted source under a private module name.

    The sandbox executes a node's code the same way — by compiling the source
    and reading the entrypoint out of the resulting namespace — so this is the
    host-side mirror of the sandbox's own load path, not a second, divergent
    one.  A private module name (rather than ``exec`` into the caller's
    namespace) keeps the node's globals off the host: a signal's module-level
    statements must not leak into whoever is validating it, exactly as they
    must not leak into the sandbox host.

    Raises the compilation error verbatim, so a syntax error in the agent's
    source surfaces as the Python error it is, with its line number, rather
    than being wrapped into something a caller has to unwrap.
    """
    import importlib
    import types

    try:
        compiled = compile(code, "<signal-source>", "exec")
    except SyntaxError as exc:  # pragma: no cover - surfaced verbatim
        raise

    module = types.ModuleType("_nullius_signal_source")
    exec(compiled, module.__dict__)  # noqa: S102 - this is the sandbox's own load path,
    # mirrored host-side on untrusted source; the sandbox applies the same
    # compile+exec under its resource and import limits.
    return module


def validate_signal_signature(code: str) -> list[str]:
    """Check that agent-emitted ``code`` declares a conforming entrypoint.

    Feature 205's half of the contract: the agent emits source, and the system
    must be able to tell whether that source exposes the entrypoint with the
    declared shape.  This is the positive check — *does the source define a
    callable named :data:`SIGNAL_ENTRYPOINT` whose parameters are the window
    then the seed?* — and it returns a list of human-readable problems, empty
    when the source conforms.  It does not raise on a non-conforming source:
    a problem list is the shape a caller turns into whatever response the
    authoring loop records (a retry, a rejected proposal), and raising here
    would steal that decision from the caller.

    The check is deliberately structural and light: it compiles the source
    (so a syntax error is reported as the error it is) and inspects the
    resulting function's parameters.  It does not *run* the function — running
    untrusted signal code is the sandbox's job, under its limits, and a
    signature validator that executed the source would both widen the trust
    boundary and need polars, numpy and a window it cannot have.  What it
    verifies is exactly the entrypoint contract:

    * a callable named :data:`SIGNAL_ENTRYPOINT` exists in the source;
    * its first parameter accepts the window (named ``ctx``);
    * its second parameter is the seed (named :data:`SIGNAL_SEED_ARG`);
    * the seed is required, so a signal cannot silently sample randomness with
      a default and defeat the determinism contract.

    A signal may take more than two parameters only if the extras are
    optional — a keyword-only default, say — because the sandbox invokes it
    positionally as ``signal(window, seed)`` and a third required parameter
    would make that call fail.  This accepts that: it rejects only a *second
    required* parameter after the seed, which is the case that breaks the
    invocation.
    """
    sig = describe_signal_signature()
    problems: list[str] = []

    try:
        import inspect
    except ImportError:  # pragma: no cover - inspect is stdlib
        return ["cannot validate signal signature: inspect is unavailable"]

    try:
        module = _require_signal_module(code)
    except SyntaxError as exc:
        return [f"signal source does not compile: {exc}"]

    fn = getattr(module, sig.entrypoint, None)
    if fn is None:
        return [
            f"source defines no {sig.entrypoint!r} entrypoint: the sandbox "
            f"executes a node by calling {sig.entrypoint!r}(window, seed), so "
            f"the emitted function must be named {sig.entrypoint!r}"
        ]
    if not callable(fn):
        return [f"{sig.entrypoint!r} is defined but is not callable"]

    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError) as exc:
        # A builtin, C function or otherwise uninspectable object: the sandbox
        # could not call it as signal(window, seed) with a known shape either.
        return [f"{sig.entrypoint!r} is not a Python function: {exc}"]

    positional = [
        p
        for p in params.values()
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
    ]

    if len(positional) < 1 or positional[0].name != sig.window_arg:
        problems.append(
            f"{sig.entrypoint!r} must take the MarketWindow first, as a "
            f"parameter named {sig.window_arg!r}"
        )

    if len(positional) < 2:
        problems.append(
            f"{sig.entrypoint!r} must take an integer seed as its second "
            f"argument, named {sig.seed_arg!r}"
        )
    else:
        seed_param = positional[1]
        if seed_param.name != sig.seed_arg:
            problems.append(
                f"the seed argument must be named {sig.seed_arg!r}, got "
                f"{seed_param.name!r}"
            )
        elif seed_param.default is not inspect.Parameter.empty:
            problems.append(
                f"the {sig.seed_arg!r} argument must be required, not defaulted: "
                "a defaulted seed lets a signal sample randomness without "
                "naming its source, which defeats the determinism contract"
            )

    # A third *required* parameter would break the sandbox's positional call.
    # Optional extras are accepted — a signal may add keyword-only knobs — so
    # only a second required positional after the seed is a problem.
    extra_required = [
        p
        for p in positional[2:]
        if p.default is inspect.Parameter.empty
    ]
    if extra_required:
        problems.append(
            f"{sig.entrypoint!r} takes more required arguments than the "
            "entrypoint allows: the sandbox invokes signal(window, seed), so "
            "any parameter after the seed must be optional"
        )

    return problems


@dataclass(frozen=True)
class SignalReturnProblem:
    """One reason a signal's return value fails to conform.

    The structured half of :func:`validate_signal_return`.  A non-conforming
    return is not an exception here — it is a value the caller turns into
    whatever the run records.  Feature 12 (which depends on feature 11) is the
    consumer that maps a problem like ``absent_symbol`` onto a
    ``contract_violation`` outcome; this module names the failure but does not
    decide its consequence, which is exactly the split that keeps the two
    features from editing each other.

    Attributes
    ----------
    kind:
        A stable, machine-readable category — ``absent_symbol``,
        ``wrong_length``, ``not_a_series`` and so on — so a caller can branch
        on the *shape* of the failure without parsing :attr:`message`.
    message:
        A human-readable statement of what was wrong, suitable for a run
        record or an agent retry.
    symbol:
        The offending symbol, for ``absent_symbol`` (and similar) problems;
        ``None`` for a problem that is not about any one symbol.
    """

    kind: str
    message: str
    symbol: str | None = None


def validate_signal_return(
    result: Any,
    universe: "tuple[str, ...]",
) -> list[SignalReturnProblem]:
    """Check that a signal's return value conforms to the declared shape.

    The positive declaration of feature 11's return half: a conforming return
    is a :class:`polars.Series` of finite floats whose length matches the
    window's universe and whose *i*-th value is the score for the *i*-th
    symbol (the window carries the labels; the series carries the values, in
    the window's stable order — see the module docstring for why "indexed by
    symbol" is positional, not a labelled axis).  This returns a list of
    :class:`SignalReturnProblem`, empty when the return conforms.

    It does not raise on a bad return, and it does not emit an outcome: those
    are feature 12's decisions.  It only answers the one question feature 11
    puts in scope — *is this a well-formed signal vector?* — so the validator
    stays a pure function over (value, universe) that the evaluator can run
    before it decides what a violation costs.

    The checks, in the order a caller would want to read them, each an
    independent failure rather than a cascade that stops at the first:

    * **it is a Polars Series** — the entrypoint returns ``pl.Series`` by
      contract; a list, a numpy array or a pandas Series is a different
      contract and is refused by name.
    * **the dtype is floating point** — scores are ranked and z-scored
      downstream, so the values must be floats; an integer or string series is
      a type error a caller could not rank without guessing.
    * **the length matches the universe** — one score per tradable symbol.  A
      series longer or shorter than the universe is misaligned before any
      per-symbol check could mean anything, so it is reported as a single
      ``wrong_length`` problem rather than one problem per index.
    * **every value is a finite float** — NaN, infinity and null are not
      scores; they would poison the cross-sectional reduction downstream
      (feature 46's stable ordering sums the values, and a NaN anywhere
      swallows the rest).  A non-finite value is reported per offending
      position so the agent learns which score was bad.

    A return for an *empty* universe is conforming only when it is itself an
    empty float series: there are no symbols to score, so a series with any
    value would be a score for a symbol that does not exist, and the length
    check catches it.
    """
    problems: list[SignalReturnProblem] = []

    try:
        import polars as pl
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency is declared
        raise ModuleNotFoundError(
            "validate_signal_return requires polars, which the nullius-contract "
            "member declares for the signal return type; run `uv sync` "
            "(or `pip install polars`) in the workspace root"
        ) from exc

    if not isinstance(result, pl.Series):
        return [
            SignalReturnProblem(
                kind="not_a_series",
                message=(
                    f"signal return must be a polars.Series, got "
                    f"{type(result).__name__}; the entrypoint returns "
                    "pl.Series indexed positionally by ctx.universe"
                ),
            )
        ]

    series: pl.Series = result

    is_float = series.dtype.is_float()
    if not is_float:
        # A non-float dtype cannot be ranked or z-scored.  Integer scores are
        # a common "I returned counts" mistake, so the message names the
        # coercion a caller would otherwise reach for — and refuses to do it
        # silently.  It is also the end of the road for the value checks: a
        # string series cast to Float64 *raises* rather than yielding
        # non-finite flags, so finiteness is only inspected for a float dtype.
        problems.append(
            SignalReturnProblem(
                kind="non_float_dtype",
                message=(
                    f"signal scores must be floating point, got dtype "
                    f"{series.dtype}; cast to Float64 before returning — the "
                    "evaluator ranks and z-scores, so an integer or string "
                    "vector is not a score"
                ),
            )
        )

    n = len(series)
    n_universe = len(universe)
    if n != n_universe:
        problems.append(
            SignalReturnProblem(
                kind="wrong_length",
                message=(
                    f"signal returned {n} score(s) for a universe of "
                    f"{n_universe} symbol(s); the i-th value is the score for "
                    "the i-th symbol of ctx.universe, so the lengths must "
                    "match exactly"
                ),
            )
        )
        # A length mismatch means the values cannot be aligned to symbols at
        # all, so per-value checks below would report positions that do not
        # correspond to the window's symbols.  Stop here: the length problem
        # is the one to act on.
        return problems

    if is_float:
        finite = series.is_finite()
        for index, ok in enumerate(finite.to_list()):
            if not ok:
                problems.append(
                    SignalReturnProblem(
                        kind="non_finite_value",
                        message=(
                            f"signal score at position {index} (symbol "
                            f"{universe[index]!r}) is not a finite float (NaN "
                            "or ±inf); scores must be finite so the "
                            "cross-sectional reduction downstream is not poisoned"
                        ),
                        symbol=universe[index],
                    )
                )

    return problems
