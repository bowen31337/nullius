"""Features 246 and 247 — the replay path's dependency wall: never the evaluator.

app_spec.xml, "Replay Engine", feature 246 (``plugin="replay"``,
``depends_on=245``): *System rejects every replay-path call reaching the
evaluator, granting the replay engine read access to the artifact store
alone.*  Feature 247 (``depends_on=246``, ``covers="cq-9"``) states the same
wall one dependency wider and gives it the code word the refusal opens with:
*System rejects any replay-path call reaching the evaluator or the sandbox,
which returns a ``forbidden_dependency`` error message.*

docs/nullius-tech-architecture.md §1 line 32 is the sentence both features are
made of, and the reason the wall is a wall rather than a preference:

    The replay engine has read access to the artifact store and zero access to
    the evaluator or sandbox. This is what makes dreaming free. If replay can
    trigger evaluation, the cost model of the entire system collapses.

**The two features are one wall, stated twice in one direction.**  246 names
the evaluator and the *grant* that comes with refusing it — read access to the
artifact store, and that alone.  247 names the evaluator *or the sandbox* and
names the code the refusal returns.  247 declares ``depends_on=246`` and is
246's sentence with a second dependency and a mandated word, so this module
carries **one** refusal with one code (:data:`FORBIDDEN_DEPENDENCY_CODE`,
``forbidden_dependency``, 247's own word, which 246's sentence leaves this
member to choose) and one forbidden set (:data:`FORBIDDEN_DEPENDENCIES`),
spelled once so the two sentences cannot drift into two sets that disagree
about the sandbox — which is exactly the state 247 exists to close.  A second
error class for 246's half was considered and refused: the two sentences share
one repair, so two classes would put two names on one repair and let a caller
catching the evaluator half silently miss the sandbox half, the failure
``replay.errors`` argues against for every pair of its siblings.

**The refusal is of the call, not of the thing reached.**  The features' word
is *call* — *"rejects every replay-path call reaching the evaluator"* — the
same word feature 146 (*"rejects a model inference **call** made from the
replay path"*, :mod:`canary._inference`) reads.  §11.2 defers learned
components but does not prohibit them from the system: the evaluation path is
exactly where a learned output is *"computed once at evaluation time and
persisted"*, so an evaluator reached from the evaluation path is the contract
working, not breaking.  Nothing here inspects a store, names an evaluator
service class or refuses a database — the seam is the call and the one fact
the refusal needs is *which forbidden dependency the call was reaching for*.
That is why :func:`reach` refuses a target that cannot be called: the feature
rejects the call, and the situation the wall was built for is a driver that
reached for the evaluator, whatever the thing it reached for turns out to be.

**The mark is the replay path's dynamic extent, and it is the one feature 146
already planted.**  "Reaching for the evaluator from the replay path" is a
fact about where a call sits at runtime, and the replay is a separate
deployment (§13) whose code is not this member's to gate line by line.  So the
path is *marked*: :data:`~canary.replaying` — feature 146's
:class:`~contextvars.ContextVar`, entered by feature 142's
:func:`~canary.replay_pair` around every nightly replay — is the mark, and
:func:`is_replaying` reads it here through the same duck-typed
``importlib``-at-call-time seam :func:`replay.resolve_tree` reaches the
policy-runtime seat through.  It is deliberately **not** re-implemented: a
second :class:`~contextvars.ContextVar` in this member would be a second
provenance for one fact, and a replay guarded by one marker would be
unguarded by the other — the daily failure mode of two spellings of one law.
The canary member is not a dependency of this one (a member never imports
another member, and this member's ``pyproject.toml`` declares the workspace
root and nothing else), so the mark is reached the way every cross-member
fact in this pool is reached: lazily, at the call site, duck-typed for the
one attribute it needs (:func:`_replay_path_mark`).  A deployment where the
canary member was not scanned has no replay path marked at all, and this wall
answers *not marked* rather than inventing a mark it cannot share — the same
"an absent component is a discoverable state, not an exception" stance the
member's seat and builders take.

**The refusal fires before the call is made — the evaluator never runs.**  The
ordering is feature 146's, and feature 245's and 251's before it, and it is
the whole feature rather than a defensive flourish: *"If replay can trigger
evaluation, the cost model of the entire system collapses"* (§1) — an
evaluation triggered inside a replay has already spent the container, the
trial-ledger debit and the wall clock, and the score the replay then produced
carries a value no frozen pair contributed.  A refusal that called first and
raised afterwards would have spent the thing it was refusing to spend, so
:func:`reach` refuses **before the target is called and before any argument is
looked at**.  The wall never calls the target, and a test pins that by handing
it a target that records every call.

**Off the replay path the seam delegates, and that is what makes it a seam.**
A refusal that only refused would guard nothing, because no caller would route
through it.  :func:`reach` is the one spelling of "reach the evaluator (or the
sandbox)" that carries §1's law with it: a caller on the evaluation path gets
the target's own result back, the arguments and keyword arguments passed
through untouched, because the evaluation path is where an evaluator is
*meant* to run — §6's twelve-step pipeline, §5.2's sandbox, feature 240's
persisted attempt.  The delegation is deliberately *thin* — no caching, no
counting, no retries, no validation of the target — because anything more
would make the replay path's wall own evaluation rather than refuse it, the
same line :mod:`canary._inference` draws on its side.

**What the wall grants is the artifact store, and it grants it by not naming
it.**  §1's sentence has a positive half — *"read access to the artifact
store"* — and the mechanism that grants it is the forbidden set's being a
*prohibition*, not a closed allowlist: :func:`replay_path_forbids` answers
``True`` for the two names §1 forbids and ``False`` for everything else, so a
replay reading the artifact store (feature 251's resident read, feature 239's
node rows) is a call no wall here intercepts.  A closed allowlist of one name would
have had to name every member, table and seat the replay path legitimately
touches, and each missing name would have been a false refusal on a path §1
*requires* to be cheap — while the two names §1 actually forbids are known
exactly.  So the set is the prohibition (§12's determinism contract stated as
a set of two), and a caller that wants the positive half reads
:func:`replay_path_forbids` for the name it is about to reach for.

**What this module deliberately does not do.**  It does not check imports or
source text — features 139's allowlist (:mod:`canary._allowlist`) and 230/231's
admission gate screen *code*, before it runs, and a second static screen here
would be a second provenance for a law that already has one.  It does not
record, count or report the refusals it makes — the refusal is the feature and
it is raised where the caller is; a nightly report that wants the count catches
:class:`~replay.ForbiddenDependencyError` around each replay, which is the same
``except`` a dreaming loop already writes.  It does not touch the evaluator, the
sandbox, the artifact store or any database itself: it holds no store, reads no
environment, consults no clock, and composes nothing.

Stdlib only — ``typing`` and the error class it raises — so importing this
member on every factory scan (and on the replay path §1 keeps free of moving
parts) costs composition nothing.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any, Final

from .errors import ForbiddenDependencyError

__all__ = [
    "EVALUATOR_DEPENDENCY",
    "FORBIDDEN_DEPENDENCIES",
    "FORBIDDEN_DEPENDENCY_CODE",
    "MESSAGE_PHRASES",
    "SANDBOX_DEPENDENCY",
    "ReplayPathDependencies",
    "dependency_feature",
    "is_replaying",
    "reach",
    "refused_dependency",
    "replay_path_forbids",
    "validate_dependency_name",
]

#: The code every refusal of this wall opens with — feature 247's own word,
#: *"which returns a ``forbidden_dependency`` error message"*, and therefore
#: the greppable token an operator reads out of the line in the
#: ``illegal_theme`` (212) / ``void_campaign`` (243) / ``pool_too_thin`` (275)
#: tradition this workspace keeps.  Feature 246's sentence names no code of its
#: own (the spec gives it no ``… error message`` phrase), so this is the
#: spelling both halves of the wall use: one code, so the two sentences cannot
#: drift into two words for one refusal.
FORBIDDEN_DEPENDENCY_CODE: Final[str] = "forbidden_dependency"

#: The name of the frozen evaluator, as this wall spells it.  §1's *"the
#: evaluator"* — §6's evaluator service, the container whose image feature 70
#: pins and whose scores carry an ``evaluator_hash``.  A name rather than a
#: class, because the wall refuses a *reach* and never inspects what arrived:
#: the seam is passed this spelling, and 246's whole feature is that no replay
#: path call may name it.
EVALUATOR_DEPENDENCY: Final[str] = "evaluator"

#: The name of the signal sandbox, as this wall spells it.  §5.2's sandbox —
#: the box feature 157's isolation laws describe, where a candidate signal is
#: *executed* for evaluation.  The second half of the name 247 adds to 246's.
SANDBOX_DEPENDENCY: Final[str] = "sandbox"

#: §1's prohibition, as a set of two — *"zero access to the evaluator or
#: sandbox"*.  A prohibition rather than an allowlist, deliberately: §1's same
#: sentence *grants* the replay engine read access to the artifact store, and
#: the way that grant is honored here is by not naming the artifact store at
#: all, so a replay's read of a stored artifact is a call no wall intercepts.
#: A closed allowlist would have had to enumerate every member, store and seat
#: the replay path legitimately touches, and every name it missed would have
#: been a false refusal on a path §1 requires to be cheap.
FORBIDDEN_DEPENDENCIES: Final[frozenset[str]] = frozenset(
    {EVALUATOR_DEPENDENCY, SANDBOX_DEPENDENCY}
)

#: How each forbidden dependency is *named in the refusal's message*, as the
#: spec's own sentences name them — *"the evaluator"* (246, 247) and *"the
#: sandbox"* (247).  Beside the set rather than derived from it, because the
#: name the wall refuses a call by (``"sandbox"``) and the phrase the refusal
#: hands the operator (``"the sandbox"``) are two spellings of one fact and the
#: message must read like the sentence it enforces.
MESSAGE_PHRASES: Final[Mapping[str, str]] = MappingProxyType(
    {
        EVALUATOR_DEPENDENCY: "the evaluator",
        SANDBOX_DEPENDENCY: "the sandbox",
    }
)

#: Which feature's sentence each refusal is enforcing — so a caller paged by
#: this wall can tell *which* half of it fired.  246 is the evaluator half
#: (*"rejects every replay-path call reaching the evaluator"*), and 247 is the
#: half that names the sandbox and the ``forbidden_dependency`` code.
_DEPENDENCY_FEATURES: Final[Mapping[str, int]] = MappingProxyType(
    {
        EVALUATOR_DEPENDENCY: 246,
        SANDBOX_DEPENDENCY: 247,
    }
)

#: The repair each refusal names.  §1 forbids the reach; the way a replay gets
#: the value it wanted is to *read what the evaluation already wrote* — the
#: half of §1's sentence the wall grants — so the repair is different for the
#: two dependencies only because the stored things are named differently: the
#: evaluator's output is a score on a node (feature 240's persisted attempt,
#: feature 255's row) and the sandbox's output is the artifact the signal
#: produced (feature 240's *"full artifact, including failures"*).  Both are
#: *read*, never *recomputed* — which is feature 251's resident read and,
#: before it, docs §11.2's rule that a learned output is *"materialized at
#: evaluation time and read back as stored floats"*, under §10.1's heading for
#: the same fact: transition in replay is *"deterministic: it reveals the child
#: already recorded"*.
_REPAIRS: Final[Mapping[str, str]] = MappingProxyType(
    {
        EVALUATOR_DEPENDENCY: (
            "Read the stored node and its artifact instead: a replay walks "
            "recorded children (feature 245) and reads materialized values, so "
            "a value the evaluator produced is one it already wrote — feature "
            "240 persists every attempt with its full artifact and feature "
            "251's resident read is how a replay takes it back. Evaluate "
            "online, in the discovery loop's worker, and replay the tree that "
            "run wrote"
        ),
        SANDBOX_DEPENDENCY: (
            "Read the artifact the sandboxed run already wrote instead: feature "
            "240 persists every attempt — *including failures* — with its full "
            "artifact, so the signal that was executed in §5.2's box is read "
            "back as stored bytes rather than executed a second time. Run the "
            "signal online, in the sandbox, and replay what it produced"
        ),
    }
)

#: What :func:`reach` reports when it is handed **no target at all** — a bare
#: reach for a forbidden dependency, which is a call to that dependency named
#: and nothing more.  A distinct spelling rather than ``repr(None)``, because
#: the operator must be able to read the difference between *the wall was
#: handed nothing* and *the wall was handed ``None``*, and the two are
#: different facts about the caller's code even though both are refused.
_ABSENT_TARGET: Final[str] = "<no target named — a bare reach>"

#: §1's sentence, quoted with its document and its number — the line every
#: message this module builds carries, because it is the sentence the whole
#: wall is made of and the one an operator greps the log for.  A constant
#: rather than a literal at each raise site: the forbidden branch and the
#: granted branch both quote it, and two spellings of one quotation is two
#: chances for one of them to drift from the document.
_ARCHITECTURE_SENTENCE: Final[str] = (
    "docs/nullius-tech-architecture.md §1: *\"The replay engine has read "
    "access to the artifact store and zero access to the evaluator or "
    "sandbox. This is what makes dreaming free. If replay can trigger "
    "evaluation, the cost model of the entire system collapses.\"*"
)

#: :func:`refused_dependency`'s whole message, built once per name the wall
#: answers for rather than at the raise site — ``(phrase, feature, repair)``
#: for a forbidden name, derived from the three tables above so a name's spec
#: wording, its forbidding feature and its repair are read from one source.
#: The unpacking is the check: a table edited without its siblings fails at
#: import rather than building half a line when a replay reaches for the
#: evaluator at three in the morning.
_REFUSAL_FACTS: Final[Mapping[str, tuple[str, int, str]]] = MappingProxyType(
    {
        name: (MESSAGE_PHRASES[name], _DEPENDENCY_FEATURES[name], _REPAIRS[name])
        for name in FORBIDDEN_DEPENDENCIES
    }
)


def validate_dependency_name(name: Any) -> str:
    """Check that ``name`` is a dependency name, or refuse it.

    The wall's subject is *which* dependency a call was reaching for, so a name
    that is not a non-empty string names no dependency and no refusal built
    from it could say what was refused.  A blank string is refused where a name
    belongs for the reason :func:`replay.transition._edges` refuses a blank
    ``parent_id``: it is neither absent nor a name, so it would read as *some
    dependency* while naming none.

    **Only the shape is checked here, never membership in
    :data:`FORBIDDEN_DEPENDENCIES`.**  An unknown but well-formed name is a
    *legal* answer for this wall — §1 forbids two dependencies and *grants* the
    rest, so a name the wall does not forbid is a name the replay path may
    reach, and :func:`replay_path_forbids` must be able to say ``False`` about
    it.  Refusing an unknown name here would turn §1's grant into a closed
    allowlist of two, and a replay reading the artifact store — the very thing
    §1 grants, feature 251's resident read and feature 239's node rows — would
    be refused by the wall built to protect it.  That is the failure this
    function deliberately does not have.
    """
    if not isinstance(name, str) or not name.strip():
        raise ForbiddenDependencyError(
            f"{FORBIDDEN_DEPENDENCY_CODE}: the replay path's dependency wall is "
            f"asked which dependency a call is reaching for, so it takes a "
            f"dependency name — got {name!r} ({type(name).__name__}), which "
            f"names no dependency, so a refusal here could not say what was "
            f"refused. Pass a dependency name: "
            f"{sorted(FORBIDDEN_DEPENDENCIES)} are the two §1 forbids the "
            f"replay path, and any other name the deployment spells — the "
            f"artifact store included — is one §1 grants it read access to "
            f"(features 246, 247)"
        )
    return name


def replay_path_forbids(name: Any) -> bool:
    """Whether the replay path may reach a dependency with this name.

    §1 read as a predicate: ``True`` for the two dependencies the replay engine
    has *zero access* to — :data:`EVALUATOR_DEPENDENCY` and
    :data:`SANDBOX_DEPENDENCY` — and ``False`` for every other non-empty name,
    which is how §1's grant is honored (*"read access to the artifact store"*):
    the artifact store is not named by this wall at all, so a replay's read of
    a stored artifact is a call nothing here intercepts.

    A *prohibition* rather than a closed allowlist, deliberately — see
    :data:`FORBIDDEN_DEPENDENCIES`.  A name that is not a non-empty string
    names no dependency and is refused by :func:`validate_dependency_name`, so
    this predicate never answers a question about nothing; an unknown but
    well-formed name is answered ``False``, because §1's sentence is a
    prohibition on two dependencies and a grant of everything else.
    """
    return validate_dependency_name(name) in FORBIDDEN_DEPENDENCIES


def dependency_feature(name: Any) -> int:
    """Which feature's sentence forbids this dependency — 246, or 247.

    The evaluator is 246's (*"rejects every replay-path call reaching the
    evaluator"*); the sandbox is 247's (*"reaching the evaluator **or the
    sandbox**"*), and the evaluator is 247's too — which is why the refusal
    quotes 247's sentence when the code it returns is 247's word.  Kept as a
    function rather than a constant so a caller reads the feature off the same
    validated name the refusal does.

    A name this wall does **not** forbid has no feature whose sentence forbids
    it and is refused, naming it: this is the one function here that is only
    meaningful about a forbidden dependency, so a caller asking it about the
    artifact store has asked a question with no answer and is told so rather
    than handed a made-up number.
    """
    dependency = validate_dependency_name(name)
    if dependency not in _DEPENDENCY_FEATURES:
        raise ForbiddenDependencyError(
            f"{FORBIDDEN_DEPENDENCY_CODE}: {dependency!r} is not a dependency "
            f"this wall forbids, so no feature's sentence forbids it: §1 "
            f"forbids the replay path {sorted(FORBIDDEN_DEPENDENCIES)} and "
            f"grants it read access to the artifact store. Ask "
            f"replay_path_forbids() what a name's standing is; this function "
            f"answers which sentence refused a reach, and there is no refusal "
            f"to name here (features 246, 247)"
        )
    return _DEPENDENCY_FEATURES[dependency]


def refused_dependency(name: Any, target: Any = _ABSENT_TARGET) -> ForbiddenDependencyError:
    """The refusal, built but not raised — the wall's whole message, as a value.

    :func:`reach` is one line of ``raise refused_dependency(...)`` around this,
    and the split is what lets a suite assert on the operator-facing message
    without manufacturing a raise — the shape :mod:`replay.duration` takes for
    its own readings, and the reason the message lives in one function rather
    than at the raise site: a second spelling of §1's law is a second law.

    The message opens with :data:`FORBIDDEN_DEPENDENCY_CODE`, names the
    dependency in the spec's own words (:data:`MESSAGE_PHRASES`), quotes §1's
    sentence with its number, names the feature whose sentence is being
    enforced, says that nothing was run, and states the repair — because an
    operator reading it has a replay path that reached for the evaluator and
    needs to know which knob to turn, not merely that something was forbidden.

    **The builder answers for every name it is handed, and it says which
    question it is answering.**  §1's prohibition covers two names and *grants*
    the rest (see :data:`FORBIDDEN_DEPENDENCIES`), so a caller may hand this
    function a name the wall never forbids — an audit walking the dependencies
    a deployment resolves is the obvious one — and there is no refusal to build
    for it.  What there must **not** be is a bare :class:`KeyError` out of a
    phrase table: that reports a fault in the wall's own tables for a name the
    wall simply does not refuse, and it names no dependency at all.  So a name
    this wall does not forbid is refused outright, in the wall's own code and
    vocabulary, naming the name and pointing at
    :func:`replay_path_forbids` — the function that *does* have an answer about
    it.  That is the repair :func:`dependency_feature` states to a caller who
    asks it about a granted name, and repeating it here is the point: this
    function is as meaningful about the artifact store as that one is, which is
    to say not at all, and a caller who asks anyway is told so rather than
    handed a line about a refusal that never happened.
    """
    dependency = validate_dependency_name(name)
    if dependency not in _REFUSAL_FACTS:
        raise ForbiddenDependencyError(
            f"{FORBIDDEN_DEPENDENCY_CODE}: {dependency!r} is not a dependency "
            f"this wall forbids, so there is no refusal to build for it: §1 "
            f"forbids the replay path {sorted(FORBIDDEN_DEPENDENCIES)} and "
            f"grants it read access to the artifact store. Ask "
            f"replay_path_forbids() for a name's standing — this function "
            f"builds the message of a refusal that happened, and none is about "
            f"{dependency!r} (features 246, 247)"
        )
    phrase, feature, repair = _REFUSAL_FACTS[dependency]
    return ForbiddenDependencyError(
        f"{FORBIDDEN_DEPENDENCY_CODE}: the replay path reached {phrase} "
        f"({_target_name(target)}) — app_spec.xml feature {feature} "
        f"refuses every replay-path call reaching {phrase}, because the "
        f"replay engine has read access to the artifact store alone. "
        f"{_ARCHITECTURE_SENTENCE} The call was refused before it was "
        f"made: {phrase} ran nothing and nothing was spent. {repair}"
    )


def reach(name: Any, target: Any = _ABSENT_TARGET, /, *args: Any, **kwargs: Any) -> Any:
    """Reach a dependency through §1's seam — refused when the replay path is marked.

    The replay path's spelling of *reach the evaluator* (or the sandbox, or
    anything else this deployment resolves), and the one place both are
    refused:

    * **inside feature 146's replay path** (:func:`is_replaying`, the mark
      feature 142's nightly replay enters) a reach for a dependency
      :func:`replay_path_forbids` answers ``True`` about — the evaluator, the
      sandbox — is refused with :class:`~replay.ForbiddenDependencyError`
      **before the target is called and before any argument is looked at**:
      the ordering §1 requires, since an evaluation triggered inside a replay
      would have collapsed the cost model before the raise;
    * **in every other case** the target is called with the arguments and
      keyword arguments exactly as handed in and its result returned exactly
      as it came back — the evaluation path's ordinary business (§6's
      pipeline, §5.2's sandbox), and the reason a caller routes through this
      seam rather than around it: the call carries §1's law with it.  That
      includes **a granted dependency on the replay path itself** — §1 forbids
      two names and *grants* the rest, so a replay reaching for the artifact
      store (feature 251's resident read, feature 239's node rows) is delegated
      here, because the wall is the prohibition and not a closed allowlist.
      A seam that refused every name while the mark was set would refuse the
      very read §1's sentence grants, and would make the wall the reason
      dreaming was *not* free.

    The target is positional-only so a caller's own ``args`` cannot collide
    with the seam's own spelling, and it is meaningless — and *allowed to be* —
    beyond being called or refused: a non-callable off the replay path fails
    with the call's own :class:`TypeError`, and on the replay path the refusal
    fires first, because the feature rejects the *call*, whatever the thing
    reached for turns out to be.

    The ``target`` default is the honest spelling of a bare reach: a caller
    looping over dependencies to check them names the dependency and no target,
    and the message says so (:data:`_ABSENT_TARGET`) rather than reporting
    ``None``, which would be indistinguishable from a target that *is* ``None``.

    The wall's own argument, by contrast, **is** checked in either state: a
    name that is not a non-empty string names no dependency, so a refusal built
    from it could not say what was refused — and a wall asked about nothing has
    no answer to give, on the replay path or off it.  An unknown but
    well-formed name is *not* that: §1 forbids two dependencies and grants the
    rest, so it is delegated like any other granted dependency.

    Raises :class:`~replay.ForbiddenDependencyError` — one class for both
    sentences of the wall, because the two have one repair (see the module
    docstring) — for a forbidden reach on the replay path, and for a name that
    is not a dependency name at all in either state.
    """
    dependency = validate_dependency_name(name)
    if replay_path_forbids(dependency) and is_replaying():
        raise refused_dependency(dependency, target)
    return target(*args, **kwargs)


def is_replaying() -> bool:
    """Whether this dynamic extent is the replay path — feature 146's mark.

    Reads :func:`canary.is_replaying` through the app-namespace seam rather
    than restating it (see the module docstring): one fact, one
    :class:`~contextvars.ContextVar`, so a replay guarded by this wall and a
    replay guarded by feature 146's inference refusal are the *same* extent —
    the property that makes the wall cover every replay a deployment runs,
    including the nightly canary's, without this member knowing who entered it.

    A deployment that did not scan the canary member has no mark at all, and
    this answers ``False`` — the honest reading of *nothing here says this
    extent is a replay* — rather than inventing a mark no other guard shares.
    """
    mark = _replay_path_mark()
    return bool(mark()) if mark is not None else False


def _replay_path_mark() -> Callable[[], Any] | None:
    """The canary member's replay-path predicate, or ``None`` if it is absent.

    ``importlib`` at call time, not an import statement, for the two reasons
    :func:`replay.resolve_tree` states for the same seam: a member never
    imports another member (so this member's ``pyproject.toml`` keeps its
    one-dependency shape), and the member loader imports a member under a
    synthetic name — so the *callable* is what is wanted, never a class or a
    module identity, and it is read off the module the loader registered.

    Returned rather than called so :func:`is_replaying` owns the single
    ``None``-vs-callable branch; ``None`` for an unscanned canary member and
    for a canary member that carries no such predicate, which are the same
    fact for this wall: there is no mark to read.
    """
    import importlib

    try:
        canary = importlib.import_module("canary")
    except Exception:  # noqa: BLE001 - a member that is not scanned, or cannot
        # be imported, is the same absence for this wall: no mark.  Caught
        # broadly because the import may fail for reasons this module cannot
        # enumerate (a synthetic module name, a partially scanned workspace),
        # and none of them is a reason a replay's read should fail.
        return None
    mark = getattr(canary, "is_replaying", None)
    return mark if callable(mark) else None


def _target_name(target: Any) -> str:
    """The target's own name — what the refusal calls it.

    A function or class names itself; an instance names its type; a bare reach
    names the absence.  One spelling, stated once, so the refusal points at the
    call site the operator must move rather than at an opaque ``repr`` the
    operator cannot grep for — deliberately the same reading
    :func:`canary._inference._model_name` gives the same question, and
    deliberately *without* a ``repr`` of the target: a repr may raise, may be
    enormous, and may print a store's connection string into a log.
    """
    if target is _ABSENT_TARGET:
        return _ABSENT_TARGET
    name = getattr(target, "__name__", None)
    if isinstance(name, str) and name.strip():
        return f"{name!r}"
    return f"a {type(target).__name__} instance"


class ReplayPathDependencies:
    """§1's wall as a value — the two refusals, named, on the composed facade.

    A stateless facade over :func:`reach`, so a caller holding the composed
    replay component can refuse a forbidden reach without importing this
    member's submodules by name — the role :class:`canary.ModelInference`
    plays for feature 146's inference refusal on the same kind of seam.  The
    class carries no state: ``__slots__`` is empty and it defines no
    ``__init__``, which is the honest shape for a wall that is a fact about
    where a call sits (§1, §12) rather than a thing a deployment configures.
    There is no allowlist, no registry and no toggle here — a wall that could
    be switched off would not be §1's *"zero access"* — so two callers can
    never observe each other through this value and there is nothing a
    deployment could misset.

    The delegation is deliberately *thin* — each method is one call to the
    function that owns the behaviour — because a second implementation of the
    refusal is exactly what this member's one-provenance rule forbids.  What
    this class adds is discoverability (the composed facade carries it as
    ``engine.dependencies``) and one duck-checkable seam for the app seat and
    the features that follow, not enforcement logic.
    """

    __slots__ = ()

    def evaluator(self, target: Any = _ABSENT_TARGET, /, *args: Any, **kwargs: Any) -> Any:
        """Reach the evaluator — feature 246's half of the wall.

        §1's first forbidden dependency: refused
        (:class:`~replay.ForbiddenDependencyError`) when this extent is the
        replay path, delegated untouched otherwise.  The named spelling of
        :func:`reach` for the dependency 246's sentence is about, so a driver
        reaching for the evaluator writes the refusal's name at the call site.
        """
        return reach(EVALUATOR_DEPENDENCY, target, *args, **kwargs)

    def sandbox(self, target: Any = _ABSENT_TARGET, /, *args: Any, **kwargs: Any) -> Any:
        """Reach the sandbox — feature 247's half of the wall.

        §1's second forbidden dependency, and the one 247 adds to 246's
        sentence: §5.2's box executes a candidate signal for evaluation, so a
        replay reaching into it would be recomputing rather than reading —
        the same collapse §1 states for the evaluator, one dependency over.
        """
        return reach(SANDBOX_DEPENDENCY, target, *args, **kwargs)

    def reach(self, name: Any, target: Any = _ABSENT_TARGET, /, *args: Any, **kwargs: Any) -> Any:
        """Reach a dependency by name — the wall's one seam, composed.

        The composed spelling of :func:`reach`, for a caller that holds a
        dependency's name in a variable (a deployment's own resolution table)
        rather than a method name.  Same refusal, same delegation, same
        ordering: the refusal fires before the target is called.
        """
        return reach(name, target, *args, **kwargs)

    def refuses(self, name: Any) -> bool:
        """Whether the replay path may reach this dependency — §1's grant.

        The composed spelling of :func:`replay_path_forbids`: ``True`` for the
        evaluator and the sandbox, ``False`` for every other name — the
        artifact store included, which is §1's grant and the reason a replay is
        cheap.  A caller asks this instead of reaching and catching, which is
        the same reading :func:`canary.is_replaying` gives its own predicate.
        """
        return replay_path_forbids(name)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return "ReplayPathDependencies()"
