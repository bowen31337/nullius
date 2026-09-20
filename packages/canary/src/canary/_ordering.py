"""A stable iteration order — the hash seed, and the sort before the reduction.

app_spec.xml feature 138 (this category's, in "Determinism Guarantees &
Nightly Canary"): *"System sets PYTHONHASHSEED to 0 and applies explicit
sorts before every reduction, which returns a stable iteration order."*  It
is §12's row — "Stable iteration order | ``PYTHONHASHSEED=0``; explicit
sorts before every reduction" — and the prerequisites state the same
sentence from the deployment's side: *"eval workers pin single-threaded
BLAS, PYTHONHASHSEED=0 and digest-pinned images."*  This module is that row
made into something a run can *fail*.

**Both halves of the row, because either alone is not the row.**  The
feature's sentence has two clauses joined by *and*: set the seed, *and*
sort before every reduction.  They are not two features and they are not
alternatives — they are two mechanisms defending one guarantee, and each
covers a case the other does not.  A pinned seed makes ``set`` and ``dict``
iteration over strings reproducible *within one interpreter version*, so a
reduction that walks a container without sorting is reproducible as long as
nothing added to that container in a different order or ran on a different
build.  An explicit sort makes a reduction reproducible *regardless of the
seed*, but only where it is applied — the string hash is what reaches a
``set``, a ``dict`` key order, ``frozenset`` rendering, and every ``groupby``
and ``unique`` that keys off a hash, and a caller who sorted at one boundary
has said nothing about the next one.  §12's row says both, so this module
refuses when either is missing: an unpinned environment is refused by name
before a reduction runs, and a sequence handed to
:func:`canary.assert_stable_iteration_order` is refused unless it is in the
canonical order a sort produces.  Feature 46's
:func:`~universe.canonical_symbol_order` is the sort half applied where the
universe is resolved; this module is the assertion that the *environment*
the reduction runs in was pinned too, which is the half nothing in the
workspace otherwise checks.

**The seed's contract is narrower than it looks, and the parser says so.**
``PYTHONHASHSEED`` is read by the interpreter before any application code
runs — which is why this module *reads* it rather than setting it: by the
time a module of this package is imported, the seed for this interpreter is
already fixed, and a library that wrote ``os.environ["PYTHONHASHSEED"]``
would be changing a variable that no longer affects the running process
while looking like it had fixed the problem.  What a deployment can do is
declare it, and what a canary can do is refuse a declaration the interpreter
would not honour.  The seed is pinned when its value is a valid
non-negative integer that is exactly zero: the interpreter parses the value
with ``strtol`` semantics, and its rule is *zero means off, anything else
means on* — so ``"0"``, ``"00"``, ``"+0"``, ``"-0"`` and ``"\t0"`` are all
the pin, while ``"1"``, ``"+1"`` and the literal ``"random"`` are not.  The
grammar is exactly the interpreter's own and is worth spelling out, because
it is narrower than "any string": a value must be the literal ``"random"``
(case-sensitive, no surrounding whitespace) or a ``strtol`` integer in
``[0, 4294967295]``.  Everything outside it — ``"abc"``, ``"0x0"``,
``"0junk"``, ``"0 "``, a negative integer, ``4294967296`` — is a value the
interpreter *refuses to start under* (``invalid PYTHONHASHSEED``) and is
therefore refused here too, rather than assumed harmless: it names a
deployment whose eval workers would not boot, and a night that never ran is
not a night the canary passed.  The classifier is deliberately *not*
conservative about whitespace and signs the interpreter rejects — it accepts
``strtol``'s leading whitespace and sign forms, and refuses a trailing one —
so it matches the runtime rather than approximating it, and the suite's
differential test checks the whole grammar against real interpreters rather
than trusting this paragraph.

**Unset is not unpinned, and the difference is recorded.**  §12's row is a
statement about a *deployment*: an eval worker pins the seed.  A deployment
that declares nothing has configured nothing, and this module reads that the
way the device sweep reads an unset device variable — as the passing case,
classified and recorded rather than refused — because the determinism
contract is about what a path is built to run as, and the build that runs an
eval worker is the container feature 135 pins and ``_sandbox`` writes the
seed into.  What the module refuses is a deployment that *did* declare a
seed and declared one that does not pin: an explicit ``PYTHONHASHSEED=1``
reaches every child process, and it is the deployment that has taken the
guarantee into its own hands at a value §12 does not admit.

The distinction is subtler than "varying bytes", and stating it exactly is
worth the paragraph, because the obvious argument for the refusal is the
wrong one.  A *fixed* non-zero seed is reproducible across runs *at that
value* — the same set of symbols iterates in the same order tonight and
tomorrow — so it is not that a non-zero seed makes a reduction
non-reproducible now.  What it does is move the guarantee somewhere §12 does
not accept: the order derives from a value this deployment chose rather than
from the zero the contract names, so it holds only for as long as nothing
changes that value — and the things that change it are exactly the things a
nightly canary exists to survive (a base image rebuilt with a different
default, a supervisor exporting its own seed into its workers, a process
started ``-R``, which re-enables randomization whatever the variable says).
The row names one value, so this sweep admits one value; a deployment that
picks another has made its reductions stable against a different and
unbecoming promise, and the refusal is what makes that choice loud while it
is still cheap.  The feature's own remedy is the row itself — pin the seed,
sort before the reduction — and the seed half accepts exactly the zero.

So :func:`classify_hash_seed`
returns :data:`PINNED`, :data:`UNPINNED` or :data:`UNSET`, and only
:data:`UNPINNED` is a refusal — a value *present and not zero*, which is a
deployment asserting the opposite of the contract.  Collapsing the three
into a boolean would lose the distinction the nightly report is for: "we
pinned it", "we never pinned it and rely on the container" and "we pinned it
to something that is not a pin" are three different nights.

**The sort half both applies the sort and refuses a sequence without one.**
This module does not forbid sets, and it does not scan searched code for
them: a set is a perfectly good intermediate, and §12's row does not ask for
the absence of hash-ordered containers — it asks that the reduction not
depend on one.  So the sort half comes in the two halves the feature's verb
implies.  :func:`apply_reduction_order` *applies* the explicit sort — any
iterable in, the members ascending by code point out, with the sort
dominating whatever iteration preceded it — which is the row's second clause
and the reason a caller routing through it is reproducible whatever the seed
is.  :func:`assert_stable_iteration_order` *checks* one, refusing a sequence
that is not strictly increasing by code point, so a boundary that produced
its own order can prove it kept to the contract.  Strictly, not merely
non-decreasing, because a repeated member is not an order a sort produces
and misaligns every ``zip`` downstream exactly as an unsorted one does — the
argument feature 46 states for its own predicate, and this module produces
and checks the same order so a sequence satisfying one satisfies the other.
:func:`stable_reduction_order` is the feature's own sentence end to end:
sweep the environment, apply the sort, and *return* the stable order with the
verdict beside it.  The assertion still never repairs — it judges what it was
handed and raises rather than quietly sorting, because a checker that fixed
its input would hide the defect it exists to catch — while the producing path
is a separate, explicitly named function a caller chooses to route through.

**The refusal is collective and complete.**  Exactly as the pin and device
sweeps name every offender in one error, :func:`require_stable_environment`
names every reason it cannot vouch for the environment in a single
:class:`~canary.CanaryOrderError` — the seed's value, whether it was set or
blank, and what the pin requires — because a sweep that stopped at the first
would be re-run to learn the rest.  And the pair is swept *together*: a
nightly canary's honest question is not "is the seed pinned?" or "was the
sequence sorted?" but "is this reduction's order stable?", which is one
question with two parts, so :func:`stable_reduction_order` takes the
environment and the sequence and answers it once, refusing if either half
failed.

**The verdict is a value; the refusal is the feature.**  On a healthy
deployment :func:`require_stable_environment` returns a
:class:`StableOrder` recording the seed's classification — pinned or unset —
so a nightly report can show *what it checked and that it was clean* rather
than merely that it did not raise, the same audit the device sweep's
:class:`~canary.DevicePaths` is.  §12's whole point is that
non-determinism does not announce itself, so the fact that the seed *was*
pinned on a given night is worth carrying; it is exactly the fact that
distinguishes two nights that produced the same bytes for different reasons.

**Setting the seed is a thing this module hands out, never a thing it does
to the process.**  The row's first clause is a verb a *launcher* performs, and
:func:`pinned_environment` is that verb: it builds the environment to start a
child under, with the pin written in and an inherited declaration overridden.
What it deliberately does **not** do is write ``os.environ`` or re-exec
anything.  It cannot usefully change the current interpreter — the seed was
fixed before this module was imported — and a function that mutated the
ambient shell while appearing to answer a question would be a side effect
nobody asked for.  So the seed travels *forward* into processes the caller
launches, which is where it can still take effect, and the value is returned
rather than applied so there is exactly one spelling of the pin in the
system.  The sandbox (:mod:`evaluator._sandbox`) writes the same pin into the
environment every signal runs under; the two are independent spellings of one
row, which is why this module's writes are offered to a launcher rather than
imposed on a process.  Nor does anything here resolve: the seed is a
declaration a deployment already made or did not make, and the reduction
order is a property of a sequence the caller already holds, so there is no
store, no clock and no registry between the question and the answer.

**The layering note.**  Stdlib only — ``re``, a dataclass and a loop, with
no polars, no pyarrow, no lake, no environment-at-import and no numerics —
for the reason the whole category states: this package is imported on every
factory scan (and on the replay path §1 keeps away from anything that could
perturb it), and the order assertion must not be the member that made that
path expensive.  Reading :data:`HASH_SEED_ENV` out of the process is a one
dictionary lookup at call time, not an import-time side effect, and it is
the *caller's* decision whether to hand the function an environment
explicitly — the composed service does, through the same mapping seam every
other sweep in this member resolves through.  The observed interpreter flag
is still available to a caller who wants it: :func:`hash_seed_active`
reports whether this *running* interpreter has hash randomization on, which
is the runtime truth beside the declaration's, and the one reading a test
can assert against a real subprocess (see the suite).
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Optional

from ._errors import CanaryOrderError

__all__ = [
    "HASH_SEED_ENV",
    "MAX_SEED",
    "PINNED",
    "PINNED_SEED",
    "RANDOM_SPELLING",
    "UNPINNED",
    "UNSET",
    "StableOrder",
    "apply_reduction_order",
    "assert_stable_iteration_order",
    "classify_hash_seed",
    "hash_seed_active",
    "is_stable_iteration_order",
    "pinned_environment",
    "require_stable_environment",
    "stable_reduction_order",
]

#: The variable §12's row names.  Kept as a constant and spelled once, so the
#: sweep, the service and the tests cannot disagree about which variable the
#: contract is read from — and so a deployment's declaration and this module's
#: reading of it are visibly the same knob.  The evaluator's sandbox spells the
#: same variable as :data:`evaluator.ENV_HASHSEED`; the two are the same
#: spelling of "the hash seed" arriving from two members' vocabularies, and
#: neither imports the other's.
HASH_SEED_ENV = "PYTHONHASHSEED"

#: The value §12 pins the seed to — the only value that turns hash
#: randomization off.  A constant, not a knob: the row says ``0``, the
#: interpreter says zero means off, and there is no second value that means
#: the same thing.
PINNED_SEED = "0"

#: The other spelling the interpreter admits besides an integer: the literal
#: ``random``, which asks it to choose a seed at startup.  Case-sensitive and
#: whitespace-exact — ``"Random"``, ``" random"`` and ``"random "`` are all
#: rejected — because the interpreter compares the whole value.  A deployment
#: may legitimately *choose* it, which is why it is classified rather than
#: treated as an unparseable value; what it is not is the pin.
RANDOM_SPELLING = "random"

#: The seed is declared and it is the pin — §12's row, satisfied.
PINNED = "pinned"
#: The seed is declared and it is *not* the pin: a deployment asserting the
#: opposite of the contract, and the only classification that is a refusal.
#: Covers both a non-zero integer and the explicit :data:`RANDOM_SPELLING`.
UNPINNED = "unpinned"
#: No seed is declared in this environment.  A deployment that configured
#: nothing — the passing case, recorded rather than refused, for the reason
#: the module docstring gives.
UNSET = "unset"

#: The largest integer the interpreter accepts — ``2**32 - 1``, i.e. the width
#: of the seed it derives the hash secret from.  One above it is rejected at
#: startup (``must be "random" or an integer in range [0; 4294967295]``), so
#: the bound is part of the *declaration's* validity and the classifier
#: applies it rather than accepting a value the runtime would refuse.  Read
#: off the interpreter's own message and pinned here so a version that moves
#: the bound is a test failure rather than a silently loosened sweep.
MAX_SEED = 2**32 - 1

#: ``strtol``'s integer syntax, which is how the interpreter reads the
#: variable before any application code runs: optional leading whitespace, an
#: optional sign, then decimal digits.  Anchored with ``\A``/``\Z`` rather than
#: ``^``/``$`` — ``$`` also matches just before a trailing newline, so a
#: ``PYTHONHASHSEED="0\n"`` would have been read as the zero its first byte
#: suggests.  It is not zero to the interpreter: the whole value must parse, so
#: a trailing newline names a worker that would not boot, and a sweep that
#: accepted it would be more permissive than the runtime it vouches for — the
#: one thing this classifier must never be.  Same reasoning for ``"0 "``,
#: ``"0x0"`` and ``"0junk"``: it is the *whole* value or a refusal.
_SEED_RE = re.compile(r"\A[ \t\v\f\r]*[+-]?\d+\Z")


def classify_hash_seed(value: object) -> str:
    """The classification of a declared hash seed — the one place it is read.

    :data:`PINNED` when the value is a valid non-negative integer that is
    exactly zero; :data:`UNPINNED` when the value is either a valid integer
    that is not zero *or* the interpreter's explicit :data:`RANDOM_SPELLING` —
    both leave hash randomization on, so both are the deployment asserting the
    opposite of §12's row; and :data:`UNSET` when there is no declaration at
    all — ``None``, or the empty string *exactly*.

    A value the interpreter would *refuse to start under* is refused here with
    :class:`~canary.CanaryOrderError` rather than classified, and the accepted
    grammar is the interpreter's own, not a guess: a value must be the empty
    string, exactly :data:`RANDOM_SPELLING` (case-sensitive, no surrounding
    whitespace), or a ``strtol`` integer in ``[0, 4294967295]``.  Anything
    else — an unparseable string, a negative integer, an integer past
    :data:`MAX_SEED`, a near-miss spelling like ``"Random"``, a
    whitespace-only value like ``"   "`` (which the interpreter rejects even
    though ``""`` is accepted), a non-string — names an eval worker that would
    not boot, and a night that never ran is not a night the canary passed.
    Accepting one would be the single thing this sweep must never do: be more
    permissive than the runtime it is vouching for.

    The bound is not decoration.  ``PYTHONHASHSEED=4294967296`` is a perfectly
    ordinary thing for an operator to write and the interpreter rejects it
    outright, so a classifier that only checked "digits" would call it
    unpinned and quietly mis-describe a worker that never started.  This rule
    was read off the interpreter's own message (``must be "random" or an
    integer in range [0; 4294967295]``) and is checked against real
    interpreters by the suite's differential test, which is what keeps the
    grammar honest if a future version moves the bound.

    Stated once so the refusal path and the recording path cannot disagree
    about what a value classifies as: :func:`require_stable_environment`
    refuses on exactly :data:`UNPINNED` and the unplaceable values, and
    :class:`StableOrder` records exactly the two classifications a clean
    sweep can produce.
    """
    if value is None:
        return UNSET
    if not isinstance(value, str):
        raise CanaryOrderError(
            f"a {HASH_SEED_ENV} declaration must be a string, got "
            f"{type(value).__name__} ({value!r}); the interpreter reads this "
            "variable as the literal 'random' or a decimal integer, so a "
            "declaration that is not a string is a declaration no eval worker "
            "could start under"
        )
    if value == "":
        # The empty string, and *only* the empty string: an env file with a
        # trailing ``PYTHONHASHSEED=``, or an unset variable exported as
        # nothing.  The interpreter takes the zero default for it — blank is
        # not "random" and does not parse as an integer, so hash randomization
        # is off *by accident*.  Classified as UNSET rather than PINNED anyway,
        # because the deployment declared nothing: it is a deployment that
        # configured nothing, not one that pinned something, and recording it
        # as a pin would be claiming credit for a guarantee nobody asked for.
        #
        # That this case is *exactly* the empty string is not a detail —
        # ``"   "`` and ``"\t"`` are **rejected** by the interpreter while
        # ``""`` is accepted, so a whitespace-only declaration falls through to
        # the refusal below rather than being folded in here.  Treating it as
        # "blank, so unset" would report the passing case for a worker that
        # would not boot: the vacuous green the nightly canary must never
        # allow.
        return UNSET
    if value == RANDOM_SPELLING:
        # The interpreter's other accepted spelling: "choose a seed at
        # startup".  A legitimate choice, and emphatically not the pin — it is
        # the deployment asking for randomization in as many words.
        return UNPINNED
    if not _SEED_RE.match(value):
        raise CanaryOrderError(
            f"{HASH_SEED_ENV} is declared as {value!r}, which is neither "
            f"{RANDOM_SPELLING!r} nor a decimal integer: the interpreter "
            "accepts only those two spellings and refuses to start under "
            "anything else, so this declaration names an eval worker that "
            "would not boot — and a night that never ran is not a night the "
            f"canary passed. Set {HASH_SEED_ENV}={PINNED_SEED} (architecture "
            "§12), or leave it unset and let the container pin it"
        )
    number = int(value)
    if number < 0 or number > MAX_SEED:
        raise CanaryOrderError(
            f"{HASH_SEED_ENV} is declared as {value!r}, an integer outside the "
            f"range [0; {MAX_SEED}] the interpreter accepts: it refuses to "
            "start under a value below zero or past that bound, so this "
            "declaration names an eval worker that would not boot. Set "
            f"{HASH_SEED_ENV}={PINNED_SEED} (architecture §12), or leave it "
            "unset and let the container pin it"
        )
    return PINNED if number == 0 else UNPINNED


def hash_seed_active() -> bool:
    """Whether this *running* interpreter has hash randomization on.

    ``sys.flags.hash_randomization`` — ``False`` exactly when the interpreter
    was started with ``PYTHONHASHSEED=0`` and without ``-R``, and ``True``
    otherwise (under an unpinned seed, under any non-zero seed, and under the
    ``-R`` that re-enables randomization whatever the environment says).  The
    runtime reading, beside :func:`classify_hash_seed`'s declaration reading:
    the classification is what a deployment *said*, this is what the process
    that is doing the reducing *is*.

    The distinction is load-bearing and is why both exist.  The row is a
    deployment-side pin — an eval worker is *started* with the seed — so
    refusing an unpinned environment is the feature.  But a module of this
    package is imported long after that decision was made, so this function
    cannot *change* the answer for the current process; it can only report it,
    and reporting it is what lets a nightly runner record "the seed was live
    tonight" rather than assert a claim it has no way to honour.  A library
    that tried to fix the flag here would be editing a decision the
    interpreter already made.
    """
    return bool(sys.flags.hash_randomization)


def is_stable_iteration_order(values: Iterable[object]) -> bool:
    """Whether ``values`` is already in the canonical reduction order.

    True exactly when the sequence is composed of valid strings and strictly
    increasing by code point — sorted *and* free of duplicates, the two ways a
    sequence can fail to be a usable reduction order.  The empty sequence is
    stable, vacuously and honestly: nothing is in no particular order, and a
    reduction over no members has no order to get wrong.

    Total over the *members*, exactly as feature 46's predicate is: it never
    raises on what it iterates — a member that is not a non-blank string
    simply makes the sequence not a reduction order at all, which is ``False``
    here and a loud refusal in :func:`assert_stable_iteration_order`.  A value
    that is not iterable raises Python's own ``TypeError``, which is the
    honest answer: there is no sequence there to have an order.

    Code-point order, stated here rather than delegated, for the reason
    :func:`assert_stable_iteration_order` states: this order has to be the one
    feature 46's :func:`~universe.canonical_symbol_order` produces, and a
    predicate that asked a different library whether a sequence was sorted
    would be a second answer to the same question.
    """
    previous: Optional[str] = None
    for value in values:
        if not isinstance(value, str) or not value.strip():
            return False
        if previous is not None and value <= previous:
            return False
        previous = value
    return True


def assert_stable_iteration_order(
    values: Sequence[str],
    *,
    origin: str = "reduction",
) -> tuple[str, ...]:
    """Return ``values`` as a tuple when they are in the canonical order.

    Feature 138's *explicit sorts* half, as an assertion: the sequence a
    reduction is about to consume — the symbol names a cross-sectional mean
    sums over, a partition's keys, a column of labels — is checked before the
    reduction runs, so an ordering no sort produced fails loudly here rather
    than silently in the last bits of every float computed over it.  The
    complaint §12 files about this failure is that it does not announce
    itself; the whole point of asserting at the boundary is to make it
    announce itself at a line the operator can read.

    ``origin`` names where the sequence came from, so the refusal reads
    "``<origin>`` is not in the stable iteration order" and an operator learns
    *which boundary* leaked the unstable order rather than merely that one
    did.  Matching feature 46's :func:`~universe.assert_stable_symbol_order`,
    which performs the same judgement one member over.

    The order is ascending by code point — Python's plain ``str`` comparison,
    deliberately not a locale- or case-folded collation, because those vary by
    environment and this order may not.  Strictly increasing, so a duplicate
    is refused as well as an inversion: a member appearing twice is not an
    order any sort produces and misaligns every ``zip`` downstream exactly as
    an unsorted sequence does.

    Returns the values materialized as a tuple, unchanged: this function
    judges the order, it never repairs it.  Sorting here — quietly fixing what
    it was handed — would hide precisely the defect it exists to catch, the
    way a swallowed exception hides the bug that raised it; the fix is always
    upstream, at the boundary that produced the sequence, which is also the
    boundary whose *sort* the row asks for.
    """
    if not isinstance(origin, str) or not origin.strip():
        raise ValueError(
            "origin must be a non-empty, non-blank string naming where the "
            f"sequence came from, got {origin!r}"
        )
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise CanaryOrderError(
            f"a stable iteration order is a sequence of symbols, got "
            f"{type(values).__name__}; a reduction consumes an ordered "
            "sequence, and a value that is not one cannot be in any order — "
            "least of all a reproducible one"
        )
    materialized = tuple(values)
    for index, value in enumerate(materialized):
        if not isinstance(value, str) or not value.strip():
            raise CanaryOrderError(
                f"{origin} returned {value!r} at position {index}, which is not "
                "a non-blank string: a reduction over a member nobody could "
                "vouch for is not a reduction any run can reproduce, whatever "
                "order it is in"
            )
    for index in range(1, len(materialized)):
        previous, current = materialized[index - 1], materialized[index]
        if current == previous:
            raise CanaryOrderError(
                f"{origin} repeats {previous!r} at positions {index - 1} and "
                f"{index}: a symbol is in a reduction once or not at all, and "
                "a repeated member misaligns every zip against it"
            )
        if current < previous:
            raise CanaryOrderError(
                f"{origin} is not in the stable iteration order: {current!r} "
                f"follows {previous!r} at positions {index - 1} and {index}; a "
                "reduction over an unsorted sequence is not bit-reproducible, "
                "because floating-point addition is not associative and the "
                "order the members arrive in decides the last bits.  Apply "
                "§12's remedy at the boundary that produced this sequence — "
                "sort it before the reduction — then assert again"
            )
    return materialized


@dataclass(frozen=True)
class StableOrder:
    """A reduction's order, swept and found stable — the clean verdict.

    Feature 138's passing case, as a value: the environment that was checked
    and the classification it was found to be.  Frozen and ordered, so a
    nightly report can file one record per deployment and compare it across
    nights — and, because :data:`PINNED` and :data:`UNSET` are different
    records, the report can say which of the two clean readings it got, which
    is §12's whole point: "the seed was pinned tonight" and "the container's
    seed stood in for a declaration tonight" are different facts about a night
    that produced the same bytes, and only one of them is the row's remedy.

    A :class:`StableOrder` only ever exists when the sweep raised nothing, so
    every value it carries is a *vouched-for* environment: nothing here can
    describe an unplaceable declaration, because an unplaceable declaration is
    a refusal and never reaches a built value.  That is the same
    all-or-nothing property :class:`~canary.DevicePaths` has, and for the same
    reason: an audit record that could say "stable" while carrying a value
    that would make a reduction unstable is an audit nobody can act on.
    """

    #: The environment variable the seed was read from —
    #: :data:`HASH_SEED_ENV`, carried so a report names the knob it checked
    #: rather than assuming the reader knows.
    variable: str
    #: The classification: :data:`PINNED` or :data:`UNSET`.  Never
    #: :data:`UNPINNED`, because an unpinned declaration is a refusal.
    seed: str
    #: Whether the *running* interpreter actually has hash randomization on,
    #: read from :func:`hash_seed_active`.  Recorded beside the declaration's
    #: classification because the two can disagree in exactly one direction —
    #: a deployment that pinned the seed in the environment of a process that
    #: was nevertheless started with ``-R`` — and a report that showed only
    #: the declaration would be showing the claim rather than the fact.
    randomization_active: bool

    def __post_init__(self) -> None:
        # A clean verdict is a statement about a sweep that ran, so every
        # field is validated before the value exists.  The alternative is a
        # record that could say "stable" while carrying UNPINNED — the one
        # classification the sweep refuses — which is precisely the shape of
        # an audit nobody can act on.
        if self.variable != HASH_SEED_ENV:
            raise CanaryOrderError(
                f"a stable-order verdict names the variable {self.variable!r}: "
                f"the seed's contract is read from {HASH_SEED_ENV} (architecture "
                "§12), and a verdict about any other variable would vouch for a "
                "knob nothing reads"
            )
        if self.seed not in (PINNED, UNSET):
            raise CanaryOrderError(
                f"a stable-order verdict records the seed as {self.seed!r}: a "
                "StableOrder is the clean verdict, built only after every "
                f"unpinned declaration is refused, so its seed is {PINNED} or "
                f"{UNSET} — and a record carrying {UNPINNED} would say 'stable' "
                "while naming the one declaration the row forbids"
            )
        if not isinstance(self.randomization_active, bool):
            raise CanaryOrderError(
                "a stable-order verdict records whether hash randomization is "
                f"active as {self.randomization_active!r}, which is not a "
                "bool: the runtime reading is a fact about the interpreter "
                "(sys.flags.hash_randomization), and a value that is not the "
                "flag cannot be the fact"
            )

    @property
    def pinned(self) -> bool:
        """Whether the deployment declared the pin (rather than nothing)."""
        return self.seed == PINNED

    @property
    def declared(self) -> bool:
        """Whether the deployment declared a seed at all."""
        return self.seed != UNSET

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"StableOrder({self.variable}={self.seed}, "
            f"randomization_active={self.randomization_active})"
        )


def apply_reduction_order(values: Iterable[str]) -> tuple[str, ...]:
    """Feature 138's *applies explicit sorts* — the order a reduction consumes.

    The producing half of §12's row, and the counterpart to
    :func:`assert_stable_iteration_order`'s checking half.  The row asks two
    things of every reduction — that the environment be pinned *and* that the
    sequence be sorted before the sum — and a module that only asserted the
    second would leave every caller to write its own ``sorted(...)``, which is
    how one boundary ends up sorting by a different key than its neighbour and
    the reduction's order quietly stops being the tree's identity.  So this is
    the one spelling of *the sort*: it takes any iterable — a set, a
    generator, whatever a query or an upstream step produced — and returns the
    members ascending by code point.

    Three properties make it the right shape for the job, and each is a
    decision rather than an implementation detail:

    **The sort dominates whatever iterated before it.**  ``values`` may be a
    ``set`` whose iteration order the hash seed decides, and the result is the
    same tuple under every seed — because the ``sorted()`` is the last thing
    that happens to the sequence.  That is precisely why an explicit sort is
    the row's *second* clause rather than an alternative to the first: a
    caller that sorts here gets a reproducible order without depending on the
    seed at all, and the seed pin is what protects the reductions that were
    not routed through this function.

    **Distinct members, and a repetition is refused rather than collapsed.**
    A duplicate is not an order any sort produces, and the tempting repair —
    ``sorted(set(values))`` — is the one this function must not make.
    Collapsing a repeat *changes the reduction*: a member carrying a weight
    contributes once per occurrence, so a ``node_id`` listed twice is a
    different total than the same id listed once, and a reduction whose sum
    silently moves is exactly the failure §12 is written about.  The
    repetition means the *query* that produced it is wrong, and the caller
    is the only one who can say which occurrence was intended.  So this
    refuses, matching :func:`assert_stable_iteration_order` — the two agree
    in both directions, since a producer that collapsed what its own checker
    refuses would be manufacturing a sequence the checker never saw.

    **Judged input, never repaired output.**  Members are validated exactly as
    the assertion validates them — a non-string or blank member is refused —
    so the producing path cannot manufacture a sequence its own checker would
    reject.  Note what is *not* here: this function does not consult the
    environment and does not refuse an unpinned seed.  A sorted sequence is
    reproducible whatever the seed is; the seed's own clause is
    :func:`require_stable_environment`'s, and folding it in here would make a
    pure function of a sequence depend on the process it ran in.

    Returns a tuple, not a list: the order is a value a caller can hand
    downstream, compare, or hash, and a mutable list would let a later step
    reorder what this one pinned.
    """
    materialized = tuple(values)
    for index, value in enumerate(materialized):
        if not isinstance(value, str) or not value.strip():
            raise CanaryOrderError(
                f"a reduction order is built from non-blank strings, got "
                f"{value!r} at position {index}: a reduction over a member "
                "nobody could vouch for is not a reduction any run can "
                "reproduce, whatever order it is sorted into"
            )
    ordered = tuple(sorted(materialized))
    for index in range(1, len(ordered)):
        if ordered[index] == ordered[index - 1]:
            raise CanaryOrderError(
                f"a reduction order is built from distinct members, got "
                f"{ordered[index]!r} more than once: a member is in a "
                "reduction once or not at all, and silently dropping the "
                "repeat would change the sum — a weighted contribution "
                "counted twice is a different number, and a reduction whose "
                "total moved without saying so is the failure §12 is written "
                "about.  Pass a set of members, or fix the query that "
                "produced the repetition"
            )
    return ordered


def pinned_environment(
    env: Optional[Mapping[str, str]] = None,
) -> dict[str, str]:
    """Feature 138's *sets PYTHONHASHSEED to 0* — the environment to launch under.

    The producing half of the row's *first* clause.  ``PYTHONHASHSEED`` is read
    by the interpreter before any application code runs, so this module can
    never change the seed of the process it is imported into — but the
    processes a deployment *launches* (an eval worker, a sandboxed signal, a
    test's fresh interpreter) are launched with an environment the launcher
    chooses, and this is that environment, built once.

    Takes the base environment to copy — the process environment by default —
    and returns a **new** mapping with the pin written in, never mutating the
    base: two callers building from one environment must not fight over it,
    and a function that wrote to ``os.environ`` would be changing the ambient
    shell as a side effect of asking a question.  That is also why the result
    is returned rather than applied, and why the base is copied rather than
    edited in place.

    Where a *declaration* is already present, the pin **wins** — the whole
    point of the row is that the value is ``0``, and a launcher that preserved
    an inherited ``PYTHONHASHSEED=1`` while claiming to pin the seed would be
    the very failure this feature exists to catch, one layer down.  The
    returned mapping is the one thing to hand to ``subprocess.run(env=...)``,
    so the pin has exactly one spelling in the system rather than one per
    launch site.

    Deliberately still *not* an assertion: an unpinned base is not refused
    here, it is *repaired*, because that is what launching a child under the
    contract means — this is the remedy §12 names.  A caller that wants to
    know whether the deployment's own declaration was pinned asks
    :func:`require_stable_environment`, and the two are used together: refuse
    the deployment, then launch its children under this.
    """
    source = _environment(env)
    pinned = dict(source)
    pinned[HASH_SEED_ENV] = PINNED_SEED
    return pinned


def _environment(env: Optional[Mapping[str, str]]) -> Mapping[str, str]:
    """The environment mapping a sweep reads the seed from.

    The caller's mapping when one is given — the same seam every other sweep
    in this member resolves through, so a test or an operator can hand the
    refusal an environment without touching the process — and the process
    environment otherwise.  Read at call time, never at import: importing this
    member must not have the side effect of consulting the process's
    environment, for the reason every module in this package states.
    """
    return os.environ if env is None else env


def require_stable_environment(
    env: Optional[Mapping[str, str]] = None,
) -> StableOrder:
    """Refuse an environment that would not make a reduction's order stable.

    Feature 138's *``PYTHONHASHSEED=0``* half, asserted against a
    declaration: :data:`HASH_SEED_ENV` is read out of ``env`` (or the process
    environment when ``env`` is ``None``), classified by
    :func:`classify_hash_seed`, and the sweep refuses a declaration that is
    present and not the pin — one that names a value the interpreter would
    parse but that does not turn hash randomization off, which is a deployment
    asserting the opposite of §12's row.  A declaration the interpreter could
    not even start under is refused too, by the classifier, with its own
    reason.

    On a clean environment it returns a :class:`StableOrder` — the variable,
    the classification (:data:`PINNED` or :data:`UNSET`) and whether the
    running interpreter actually has randomization on, recorded so a nightly
    report can show *what it checked and that it was clean* rather than merely
    that it did not raise.

    A **blank** declaration is read as :data:`UNSET`, not as a pin: an empty
    value does not parse as an integer, so the interpreter's ``strtol`` reads
    it as zero and hash randomization is off by accident.  Classifying it as
    :data:`UNSET` rather than :data:`PINNED` is deliberate — the deployment
    declared nothing, and recording a trailing ``PYTHONHASHSEED=`` in an env
    file as the row's remedy would be claiming credit for a guarantee nobody
    asked for.

    Unset is not a refusal.  The row is a statement about what an eval worker
    is *built* to run as — the container feature 135 pins, into whose
    environment :mod:`evaluator._sandbox` writes the pin — so a deployment
    that declares nothing has configured nothing, and is read the way the
    device sweep reads an unset device variable.  The two are recorded
    separately, because a nightly report that could not tell them apart could
    not tell a night the deployment pinned from a night the container stood
    in for it.
    """
    source = _environment(env)
    value = source.get(HASH_SEED_ENV)
    # The classifier is the whole of the reading: it refuses an unplaceable
    # value with its own reason and returns one of the three classifications
    # otherwise.  A refusal propagates; nothing is caught here, because the
    # refusal *is* the feature and an operator needs the classifier's reason
    # rather than a second, poorer one this function would have to invent.
    seed = classify_hash_seed(value)
    if seed == UNPINNED:
        raise CanaryOrderError(
            f"{HASH_SEED_ENV} is declared as {value!r} in this environment, "
            "which is not the pin: a non-zero seed leaves hash randomization "
            "*on*, so every set, dict and frozenset of strings a reduction "
            "walks iterates in an order the seed derives — an order §12 does "
            "not admit as stable, because it is pinned to a value this "
            "deployment chose rather than to the zero the determinism contract "
            "names.  (It is reproducible across runs *at this one value*, which "
            "is exactly why the failure is quiet: the night the value changes, "
            "or the process that inherits a different one, is the night every "
            "reduction over a hash-ordered container moves together.)  The "
            "failure architecture §12 files under 'Stable iteration order | "
            f"PYTHONHASHSEED=0; explicit sorts before every reduction'. Set "
            f"{HASH_SEED_ENV}={PINNED_SEED}, or leave it unset and let the "
            "pinned container (feature 135) supply it"
        )
    return StableOrder(
        variable=HASH_SEED_ENV,
        seed=seed,
        randomization_active=hash_seed_active(),
    )


def stable_reduction_order(
    values: Iterable[str],
    env: Optional[Mapping[str, str]] = None,
    *,
    origin: str = "reduction",
) -> tuple[tuple[str, ...], StableOrder]:
    """Feature 138's whole sentence — *returns a stable iteration order*.

    Both halves of §12's row, applied and returned together: the reduction is
    handed a sequence, and it comes back in the stable order, with the
    environment verdict that says which clean reading the deployment gave.
    This is the function the feature's own verb describes — it does not merely
    *check* an order, it *returns* one, so a caller can hand its result
    straight to the reduction it was about to make.

    The order of operations is deliberate.  :func:`require_stable_environment`
    sweeps the environment first and raises if the seed would leave a
    hash-ordered walk unpinnable; only then does
    :func:`apply_reduction_order` sort.  Either refusal propagates unchanged,
    so a caller learns *which* half of the row failed with the reason the half
    that owns it gives — and the taxonomy's class split is what keeps that
    legible at the ``except``.

    What is applied and what is *not* is the feature's own division, and it is
    worth stating because the function mutates nothing: the sequence is
    **sorted here** — the row's second clause, and the reason this returns an
    order rather than judging one — while the seed is **not** applied, because
    the interpreter fixed it before this module was imported and no function
    can change it now.  A caller that needs the seed on a *child* process gets
    that from :func:`pinned_environment`; a caller that needs to know whether
    the current deployment was pinned reads the second half of the returned
    pair.  Nothing here pretends to have re-seeded the running interpreter.

    The input is any iterable — a ``set`` is the common case and precisely the
    one this exists for — and the result is its members ascending by code
    point.  Both refusals are :func:`apply_reduction_order`'s and are neither
    caught nor repaired here: a member that is not a non-blank string, and a
    member that appears twice.  The second is the one worth naming, because
    collapsing it is the obvious-looking mistake — a repeat is a real
    contribution in a weighted reduction, so dropping it would move the sum
    silently, and the caller is the only one who can say which occurrence was
    meant.

    The argument order puts the sequence first because it is the subject: the
    environment is the condition the reduction runs under, and a caller with
    one sequence to sort and one environment to check it in reads the call as
    what it is.
    """
    verdict = require_stable_environment(env)
    ordered = apply_reduction_order(values)
    return ordered, verdict
