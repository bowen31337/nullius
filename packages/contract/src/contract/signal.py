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

import ast
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

#: The filename agent-emitted source is read under — parsed by
#: :func:`validate_signal_signature`, compiled by
#: :func:`_require_signal_module` on the sandbox's load path.  Spelled
#: identically in the evaluator sandbox's embedded child runner and in the
#: signal agent's diagnosis law: a defect located in a proposal must name a
#: place in the source every other reader of that source can find, so the
#: anchor is one string held by spelling (the members sit on opposite sides
#: of the Z0 boundary and must not import each other for a literal), pinned
#: by tests on both sides rather than shared by import.
_SIGNAL_SOURCE_FILENAME = "<signal-source>"


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

    **This is the sandbox's own child load path, and nothing else's.**  It
    compiles the source and executes it into a fresh module namespace —
    which is what *running* untrusted code means, and precisely why no
    host-side caller may reach it: :func:`validate_signal_signature` reads
    the syntax tree and never executes a byte of what it is judging, so the
    module-level statements of an agent's answer cannot reach the
    orchestrator's environment, network or filesystem through adoption.  A
    private module name (rather than ``exec`` into the caller's namespace)
    keeps the node's globals off whoever loads it, exactly as they must not
    leak into the sandbox host.

    Raises the compilation error verbatim, so a syntax error in the agent's
    source surfaces as the Python error it is, with its line number, rather
    than being wrapped into something a caller has to unwrap.
    """
    import importlib
    import types

    try:
        compiled = compile(code, _SIGNAL_SOURCE_FILENAME, "exec")
    except SyntaxError as exc:  # pragma: no cover - surfaced verbatim
        raise

    module = types.ModuleType("_nullius_signal_source")
    exec(compiled, module.__dict__)  # noqa: S102 - the sandbox child's own load
    # path, executing untrusted source in a throwaway namespace under the
    # sandbox's resource and import limits; no host-side caller reaches this
    # (validate_signal_signature parses instead of executing).
    return module


def _binds_name(target: ast.expr, name: str) -> bool:
    """Whether ``target`` is an assignment target that binds ``name``.

    Walks the tuple/list/starred shapes a statement can bind through, so
    ``signal, aux = ...`` counts as a binding of ``signal`` exactly as it
    would at execution time.
    """
    if isinstance(target, ast.Name):
        return target.id == name
    if isinstance(target, (ast.Tuple, ast.List)):
        return any(_binds_name(element, name) for element in target.elts)
    if isinstance(target, ast.Starred):
        return _binds_name(target.value, name)
    return False


def _statement_binds_name(stmt: ast.stmt, name: str) -> bool:
    """Whether a module-level ``stmt`` binds ``name``.

    This is the static stand-in for "the module namespace holds this name
    once the source has run", and it deliberately covers only the statements
    that *define* a name at module level: ``def`` and ``class`` bodies,
    assignments (plain, annotated-with-a-value, augmented) and imports.  A
    def nested inside an ``if``/``try``/loop is not a *module-level* def —
    whether it runs is a runtime fact, and the only way to find out would be
    to execute the source, which is the one thing this validator must not
    do — and a name bound only by flow control (``for signal in ...``,
    ``with ... as signal``) is not an entrypoint definition.  Both fall
    through to the no-entrypoint refusal: the static answer fails closed.

    ``async def`` is pointedly absent from the list.  The entrypoint is the
    *synchronous* function the sandbox invokes as ``signal(window, seed)``;
    an ``async def`` of the same name would hand the sandbox a coroutine
    instead of a series, so it is not the def the contract names and does
    not bind the entrypoint here.
    """
    if isinstance(stmt, (ast.FunctionDef, ast.ClassDef)):
        return stmt.name == name
    if isinstance(stmt, ast.Assign):
        return any(_binds_name(target, name) for target in stmt.targets)
    if isinstance(stmt, ast.AnnAssign):
        # An annotation alone (``signal: int``) binds nothing at execution
        # time; only the valued form does.
        return stmt.value is not None and _binds_name(stmt.target, name)
    if isinstance(stmt, ast.AugAssign):
        return _binds_name(stmt.target, name)
    if isinstance(stmt, ast.Import):
        return any(
            alias.asname == name
            or (
                alias.asname is None
                and alias.name == name
                and "." not in alias.name
            )
            for alias in stmt.names
        )
    if isinstance(stmt, ast.ImportFrom):
        return any(
            alias.asname == name or (alias.asname is None and alias.name == name)
            for alias in stmt.names
        )
    return False


def _entrypoint_node(
    binding: ast.stmt | None, name: str
) -> ast.FunctionDef | ast.Lambda | None:
    """The function node a module-level binding of ``name`` defines.

    A ``def`` is the entrypoint every downstream consumer invokes; a lambda
    bound by assignment is the same callable by another spelling, so it is
    read the same way.  Any other binding — ``signal = 42``, a class, an
    import — yields ``None``: the tree can say the name is *defined*, but
    which value an assignment lands in is a runtime fact, and the one
    runtime this validator never observes is the source's own.
    """
    if isinstance(binding, ast.FunctionDef):
        return binding
    if (
        isinstance(binding, ast.Assign)
        and isinstance(binding.value, ast.Lambda)
        and any(_binds_name(target, name) for target in binding.targets)
    ):
        return binding.value
    if (
        isinstance(binding, ast.AnnAssign)
        and isinstance(binding.value, ast.Lambda)
        and _binds_name(binding.target, name)
    ):
        return binding.value
    return None


def validate_signal_signature(code: str) -> list[str]:
    """Check that agent-emitted ``code`` declares a conforming entrypoint.

    Feature 205's half of the contract: the agent emits source, and the system
    must be able to tell whether that source exposes the entrypoint with the
    declared shape.  This is the positive check — *does the source define a
    module-level function named :data:`SIGNAL_ENTRYPOINT` whose parameters
    are the window then the seed?* — and it returns a list of human-readable
    problems, empty when the source conforms.  It does not raise on a
    non-conforming source: a problem list is the shape a caller turns into
    whatever response the authoring loop records (a retry, a rejected
    proposal), and raising here would steal that decision from the caller.

    **The check is a read of the syntax tree, and nothing more — and this is
    load-bearing.**  The source is agent-authored and therefore untrusted
    (architecture §5.2: "LLM-authored code is untrusted code"), and this
    validator runs host-side, in the orchestrator's process, with its
    environment, its network and its filesystem.  The one thing it must
    never do is run what it is reading.  So :func:`ast.parse` builds the
    tree — a parse, not an execution; a syntax error is reported as the
    error it is, under the ``<signal-source>`` filename every other reader
    of a proposal uses — and every check below is a walk over module-level
    nodes: no statement runs, no import loads, no decorator is called, no
    annotation evaluates, and a hostile module level (a file write, an
    environment read, an infinite loop) costs the orchestrator nothing.
    Running untrusted signal code is the sandbox's job, under its limits;
    the validator that gates *adoption* sits outside that boundary and
    treats the source as hostile, because it is.

    What it verifies is exactly the entrypoint contract:

    * a module-level ``def`` named :data:`SIGNAL_ENTRYPOINT` binds the
      entrypoint name — the *last* such binding wins, the same rule the
      sandbox's own module namespace follows.  ``async def`` does not
      qualify: the sandbox calls ``signal(window, seed)`` and needs a
      series back, not a coroutine;
    * its first parameter accepts the window (named ``ctx``);
    * its second parameter is the seed (named :data:`SIGNAL_SEED_ARG`);
    * the seed is required, so a signal cannot silently sample randomness
      with a default and defeat the determinism contract.

    A binding of the entrypoint name that is not a function definition —
    ``signal = 42`` is the plain case — is refused as not callable, the
    same sentence the executed check used.

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
        tree = ast.parse(code, filename=_SIGNAL_SOURCE_FILENAME)
    except SyntaxError as exc:
        return [f"signal source does not compile: {exc}"]

    # The last module-level binding of the entrypoint name wins — the rule
    # the sandbox's own exec applies to the module namespace it builds, read
    # off the tree instead of off a run.
    binding: ast.stmt | None = None
    for stmt in tree.body:
        if _statement_binds_name(stmt, sig.entrypoint):
            binding = stmt

    entry = _entrypoint_node(binding, sig.entrypoint) if binding is not None else None

    if binding is None:
        return [
            f"source defines no {sig.entrypoint!r} entrypoint: the sandbox "
            f"executes a node by calling {sig.entrypoint!r}(window, seed), so "
            f"the emitted function must be named {sig.entrypoint!r}"
        ]
    if entry is None:
        return [f"{sig.entrypoint!r} is defined but is not callable"]

    arguments = entry.args
    # inspect's "positional" (POSITIONAL_ONLY then POSITIONAL_OR_KEYWORD) is
    # posonlyargs then args, in declaration order — the two readings of the
    # same parameter list.
    positional = [*arguments.posonlyargs, *arguments.args]
    n_positional = len(positional)
    # ast.arguments.defaults lines up with the *tail* of the positional list,
    # which is exactly where inspect reports the defaulted parameters.
    n_defaults = len(arguments.defaults)

    def _is_defaulted(index: int) -> bool:
        return index >= n_positional - n_defaults

    if n_positional < 1 or positional[0].arg != sig.window_arg:
        problems.append(
            f"{sig.entrypoint!r} must take the MarketWindow first, as a "
            f"parameter named {sig.window_arg!r}"
        )

    if n_positional < 2:
        problems.append(
            f"{sig.entrypoint!r} must take an integer seed as its second "
            f"argument, named {sig.seed_arg!r}"
        )
    else:
        seed_arg = positional[1]
        if seed_arg.arg != sig.seed_arg:
            problems.append(
                f"the seed argument must be named {sig.seed_arg!r}, got "
                f"{seed_arg.arg!r}"
            )
        elif _is_defaulted(1):
            problems.append(
                f"the {sig.seed_arg!r} argument must be required, not defaulted: "
                "a defaulted seed lets a signal sample randomness without "
                "naming its source, which defeats the determinism contract"
            )

    # A third *required* parameter would break the sandbox's positional call.
    # Optional extras are accepted — a signal may add keyword-only knobs — so
    # only a second required positional after the seed is a problem.
    if any(not _is_defaulted(index) for index in range(2, n_positional)):
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
