"""Single-threaded numerics — the two caps, and the worker they guard.

app_spec.xml feature 137 (this category's, in "Determinism Guarantees &
Nightly Canary"): *"System rejects an evaluation worker started without
OMP_NUM_THREADS and MKL_NUM_THREADS set to 1, because threaded reductions
are non-deterministic in float."*  It is §12's third table row —
"Single-threaded numerics | ``OMP_NUM_THREADS=1``, ``MKL_NUM_THREADS=1``
in every eval worker" — and the prerequisites state the same requirement
from the deployment's side: *"eval workers pin single-threaded BLAS,
``PYTHONHASHSEED=0`` and digest-pinned images."*  Those three clauses are
three features: the image is feature 135, the seed is feature 138, and
this module is the clause nothing in this workspace asserted yet.  It is
the third assertion the category layers onto one frozen container, and it
follows the shape the others established: a pure parser over strings a
deployment already wrote, stdlib-only and import-cheap, so importing this
member on every factory scan (and on the replay path §1 keeps away from
anything that could perturb it) still costs composition nothing.

**Why a thread count is a determinism knob at all.**  A floating-point sum
is not associative: ``(a + b) + c`` and ``a + (b + c)`` are different
numbers whenever an intermediate rounds, which for a long accumulation of
mixed-magnitude values is most of the time.  A threaded reduction
partitions the members, sums each partition in a private register, and
reduces the partials — so the answer depends on how many partitions the
library chose, and the loss of significance depends on which members landed
together.  The classic demonstration is a small value added to a large one
and then subtracted away — ``(1e16 + 1.0) - 1e16`` versus
``(1e16 - 1e16) + 1.0``, which are ``0.0`` and ``1.0`` — and the loss grows
with the number of regroupings.  A library's *default* count is drawn from
the machine, one worker per core, so the same bytes summed on a 16-core
host and a 4-core host are two different totals, and the nightly canary
compares against one recorded constant.  That is exactly the failure §12
files as invisible: nothing errors, no alert fires, and the drift is
largest where the reduction is longest, which is where the interesting
trees are.  The row's remedy is to take the choice away from the machine,
and this module is the assertion that the deployment did.

**Both caps, one feature, and neither subsumes the other.**  The feature's
own sentence joins the two variables with *and*, and the join is
load-bearing rather than a stylistic list: ``OMP_NUM_THREADS`` governs
OpenMP-parallel kernels (the MKL and OpenBLAS reductions a manylinux
numerics wheel reaches), while ``MKL_NUM_THREADS`` governs Intel MKL's own
threading layer *independently of OpenMP* and takes precedence there.  The
two layers spell different variables, a deployment that set one has said
nothing about the other, and nothing in this workspace imports both to
check — so the sweep is over a fixed table of two variables
(:data:`THREAD_ENV_CAPS`, each read from the name §5.2 writes into the
sandbox and the architecture's table spells) and reads each one.  Spelling
the table out rather than inferring the variables from a library is the
same decision :data:`~canary.IMAGE_ENV_VARS` and
:data:`~canary.DEVICE_ENV_VARS` make: a thread knob that is not read here
is a reduction the sweep would silently leave threaded, and a
silently-threaded reduction is precisely the one that moves the score.

**The verdict is a reading, so the refusal is not a second opinion.**  The
caps are *environment variables*, and by the time any module of this
package is imported they are a fact about a process that already started —
which is why this module, like :mod:`canary._ordering`, **reads** them
rather than setting them: a library that wrote ``os.environ["OMP_NUM_THREADS"]``
would be changing a variable the numerics may already have read in this
process and will definitely not re-read in the next, while looking like it
had fixed the problem in both.  What a deployment can do is declare them,
and what a canary can do is refuse a worker whose declaration is missing, or
present and not the pin.  So the sweep answers the feature's question — *was
this worker started under both caps?* — and the sentence it renders is about
the *launch*.

**The remedy is the pin, so this sweep has a producing half.**  The caps are
read by the numerics at their own import, so nothing can repair a process
that has already started; what a launcher *can* do is hand a child an
environment carrying the pin, and that is what
:func:`thread_capped_environment` returns — a fresh mapping, never a
mutation of the ambient shell, built so there is exactly one spelling of
the pin in the system, the same stance :func:`~canary.pinned_environment`
takes for the hash seed.  §5.2's sandbox (:mod:`evaluator._sandbox`) writes
the same two variables into every signal's environment; the two are
independent spellings of one row, and this module — unlike the sandbox —
imports no numerics at all.

**``1`` is the only pin, and the sweep says so exactly.**  A cap is pinned
when the value is a valid integer that is exactly one, read with the integer
grammar the runtime applies: a ``strtol``-shaped run of digits, which under
``int()`` means any script's decimal digits (``"1"``, ``"01"``, ``"+1"``,
``"\\t1"`` and a fullwidth ``"１"`` are all the pin).  ``0`` is a perfectly
reasonable *other* choice — it asks the library for its conservative
behaviour — but it is not the pin: §12's row names one value, and a
deployment that wrote another has moved the promise into its own hands,
which is the honest reading rather than a convenient one.  ``2`` and ``4``
are the failure the feature exists to catch: reproducible *at that count*
across runs on one host, and therefore quiet, while a change of hardware, a
rebuilt wheel or a library that reads "as many as asked for, but no more
than the machine has" differently moves every reduction at once.

**Three classifications, and the third is the feature.**  Unlike the device
sweep — where an unset variable is the *passing* case, because the contract
is "no GPU" and a deployment reaches the CPU by declaring nothing — an
absent cap is a refusal here, and the asymmetry is a difference in what is
being read.  ``NULLIUS_EVAL_DEVICE`` is a declaration about the
*deployment*, made by the operator this member's caller reads it from;
``OMP_NUM_THREADS`` is a declaration about the *worker*, written by a
launcher and read by a third-party library this member cannot see.  Nothing
in the environment states that a reduction is single-threaded; what states
it is the variable, present and pinned, at the moment the library imports.
So:

* :data:`ABSENT` — the variable is not in the worker's environment at all:
  nothing was declared, so there is no evidence the reduction is
  single-threaded, and passing it would be the vacuous green §12's
  prerequisites exist to prevent.  A **refusal**, naming the omission;
* :data:`CAPPED` — present and the pin: the worker was started under
  the row, and the verdict records it;
* :data:`UNCAPPED` — present and not the pin: another integer, a blank, a
  value no library reads as a count.  A **refusal** naming the value.

The three are named ``CAPPED``/``UNCAPPED`` rather than reusing
:data:`~canary.PINNED`/:data:`~canary.UNPINNED` — which the seed sweep
spells the same three-way shape with — because the two share a package root
and the distinction they record is not the same one: a seed is
:pinned:/:unpinned: when the *interpreter* honours it or does not, while a
cap is :capped:/:uncapped: when a *library* will read a pool of one or
something else.  One vocabulary for two rows would invite a caller to catch
one sweep's classification and test it against the other's.

Unset and blank are therefore pulled apart rather than folded together, and
the pair is worth the paragraph because a coarser sweep would treat them as
one case.  An unset variable is the absence above; a variable set to the
**empty string** is a *present* declaration naming no count, and it is the
more dangerous of the two: a library reading it applies its own default of
one worker per core, so ``OMP_NUM_THREADS=`` in a Compose file is a threaded
worker wearing the shape of a configured one.  Both are refusals, with
different messages, because an operator repairs them differently — add the
variable, or fix the value.

**The syntax is wider than the seed's, deliberately.**  The classifier here
accepts ``strtol``'s whitespace and sign forms and any script's decimal
digits, and it says so rather than leaving the divergence from
:func:`~canary.classify_hash_seed` to be discovered.  ``PYTHONHASHSEED`` has
a grammar that lives entirely in the interpreter, so the seed sweep can be
measured against the runtime to the character; the caps have no single
owner — each library parses them its own way — so the widest reading a
plausible library could share is the one taken.  Being permissive about
*syntax* can only classify a declaration, never accept a threaded one
(every spelling of one is still one), while being strict would refuse a
worker that is genuinely single-threaded, which is the false positive the
other direction of this category's rule forbids.

**A declaration a library will not read as a number is refused, not
guessed at.**  ``OMP_NUM_THREADS=auto`` and ``MKL_NUM_THREADS=many`` are
things a deployment might write after reading a library's documentation,
and every one of them is a refusal here rather than an :data:`ABSENT` or a
pass: this module will not decide on a library's behalf which non-numeric
tokens that library honours, because a sweep that guessed wrong would
certify a threaded worker on the strength of its own guess.  The refusal
names the value as written, which is the half the operator can act on.

**What the sweep cannot see, and the one thing it measures instead.**  A
variable in the environment is a *claim*; the pool a library sized is the
fact, and a pinned variable that seats nothing is a claim nothing honoured
— the case this feature's own sentence does not reach and the one that
makes it uncomfortable in practice.  It is not hypothetical: with both of
§12's caps set to one, this workspace's Polars still reports a sixteen-thread
pool (``POLARS_MAX_THREADS``, unset, defaults to one per core, and the OMP
caps bind the BLAS kernels rather than the frame engine), so *"two runs of
one seeded signal over the same bytes can diverge in float"* is live on a
worker that satisfies §12's row to the letter.  So the sweep has an
**opt-in** measured reading: :func:`interpreter_thread_pool` reports the
pool a numerics library already loaded in this process resolved, and when a
caller supplies it the sweep refuses a claim that seats nothing rather than
recording a green it cannot support.  It stays opt-in for the reason the
whole category gives: this member is imported on every factory scan, and a
canary that imported the numerics to audit their threading would be the
audit becoming a participant — so the reading is taken by a caller who has
the library loaded anyway (the nightly runner, §5.2's sandbox host), and the
composed service's ``service.threads`` is the declaration sweep, which is
what the feature's sentence asks for.

**The refusal is collective and complete.**  Exactly as the pin, device and
order sweeps name every offender in one error,
:func:`reject_threaded_workers` collects and raises one
:class:`~canary.CanaryThreadError` naming every variable that is not pinned
— and, when a measured reading is supplied, the pool it found — because a
sweep that stopped at the first would be re-run to learn the rest, and the
operator of a nightly assertion reads the whole deployment's numerics state
in one message.  Per-variable failures are reported in sorted variable
order so the message is stable across runs.

**The verdict is a value; the refusal is the feature.**  On a
single-threaded worker
:func:`reject_threaded_workers_from_env` returns a :class:`ThreadCaps`
recording which variables were declared and at what value, which of them
was capped at one, and whether the pool was *measured* or assumed
— so a nightly report can show what it checked and that it was clean rather
than merely that it did not raise, the same audit
:class:`~canary.DevicePaths` and :class:`~canary.StableOrder` are.  The
verdict carries the measurement because that is the fact distinguishing two
nights that produced the same bytes for different reasons.

**The span, and what it does not promise.**  "A worker started without
these variables" is a statement about a process, but the interpreter running
the canary is not the interpreter that evaluated, and a library imported
once has fixed its pool for the life of the process.  What this module can
bound is an *extent*: :func:`single_threaded` sweeps on entry, yields the
verdict, and on a clean exit refuses a pool that has **widened** since —
a ``set_num_threads(16)`` inside the span, or a second numeric library
loaded whose default outranks the caps — which is a break of the row inside
the extent, caught at the boundary that can name it rather than at the next
night's ``1e-12`` comparison.  The check is monotone (only a wider pool is
refused; narrowing cannot reintroduce the divergence and refusing it would
make the span unusable on a path that legitimately tightens its own
threads) and bounded (it cannot see a pool resolved before the span was
entered — which is why the measured refusal above exists at all, and why
§5.2's sandbox, not this module, is what actually *starts* a signal
single-threaded).

**A trap variable is removed rather than overridden.**  A worker in this
system spawns children, and an inherited cap is the one knob that travels
wrongly: the common remedy (export the two caps to one, then launch) leaves
a wider ``POLARS_MAX_THREADS`` behind, and a child reading it outranks the
pin that was written for it.  So :func:`inherited_threaded_variables` names
every variable in an environment that would make a *child* threaded —
§12's two caps plus the one floor this module knows by name, present and
not the pin — and :func:`child_thread_environment` removes those names
before writing the pin.  The floor is *carried* rather than overridden in
:func:`thread_capped_environment` too: adjudicating a third library's knobs
is how an audit becomes a guess, so the producing half preserves a floor the
deployment declared (and the sweep refuses a wider one) rather than quietly
rewriting it.

**The layering note.**  Stdlib only — ``os``, ``re``, ``sys``,
a dataclass, a loop and a context manager — with no polars,
no pyarrow, no lake, no environment-at-import and no numerics of its own, for
the reason the whole category states: this package is imported on every
factory scan (and on the replay path §1 keeps free of moving parts), and the
thread refusal must not be the member that made that path expensive — nor
may it import the numerics whose threading it is auditing, which would make
the audit a participant.  Reading the cap variables out of the process is a
lookup at call time, not an import-time side effect, and it is the *caller's*
decision whether to hand the function an environment explicitly — the
composed service does, through the same mapping seam every other sweep in
this member resolves through.  Where the sweep does need a library it does
not import, it finds it the way a caller would have: by looking for one
already loaded (:func:`interpreter_thread_pool`), so the numerics of the
world are read off the process rather than imported into it.  It is carried
by :class:`~canary.CanaryService` at ``service.threads``, beside the pin
sweep at ``service.containers`` and the device sweep at ``service.devices``
— the same seam, the same laziness (resolved on first use, so composition
never fails on a deployment's numerics configuration), so a caller holding
the composed canary reaches the refusal without importing this member's
submodules by name.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Optional

from ._errors import CanaryThreadError

__all__ = [
    "ABSENT",
    "CAPPED",
    "CHILD_CAP_VARIABLES",
    "POOL_ACCESSOR",
    "POOL_VARIABLE",
    "SINGLE_THREADED",
    "THREAD_ENV_CAPS",
    "UNCAPPED",
    "ThreadCaps",
    "child_thread_environment",
    "classify_thread_cap",
    "inherited_threaded_variables",
    "interpreter_thread_pool",
    "reject_threaded_workers",
    "reject_threaded_workers_from_env",
    "single_threaded",
    "thread_capped_environment",
]

#: §12's "Single-threaded numerics" row as the table the sweep reads:
#: variable → the library layer that reads it.  Both are named, because the
#: feature's own sentence joins them with *and* and because neither layer is
#: bound by the other's variable — ``OMP_NUM_THREADS`` governs the
#: OpenMP-parallel kernels, ``MKL_NUM_THREADS`` governs MKL's own threading
#: independently of OpenMP and outranks it there.  Spelled as a mapping of
#: variable to layer rather than as a set of names for the reason
#: :data:`~canary.IMAGE_ENV_VARS` is: a refusal has to say *which* library
#: was left threaded, and the layer is the word an operator can act on.
THREAD_ENV_CAPS: Mapping[str, str] = {
    "OMP_NUM_THREADS": "the OpenMP-parallel BLAS kernels",
    "MKL_NUM_THREADS": "the Intel MKL threading layer",
}

#: The value §12 pins both caps to: one thread, so a reduction has a single,
#: reproducible order.  A constant, not a knob — the row names one value, and
#: ``0`` (let the library choose its conservative default) and ``2`` (a fixed
#: but wider pool) are both *choices*, admitted by the libraries and refused
#: here because neither is the pin.
SINGLE_THREADED = "1"

#: The variable beyond §12's two that this module knows by name: a
#: library-level pool floor which, unset, is one worker per core, and which
#: outranks the OMP caps inside the library that reads it.  Known by name
#: rather than left alone because it is the knob a deployment's *ambient*
#: shell tends to carry and every child tends to inherit (see
#: :func:`inherited_threaded_variables`), and because a sweep that vetted
#: only §12's two variables would certify a worker this one is about to make
#: threaded.  It is *carried* rather than interpreted: the sweep never
#: decides what value this floor should hold, it only refuses to let a wider
#: declaration the row does not name travel with a worker — adjudicating a
#: third library's knobs is how an audit becomes a guess.
POOL_VARIABLE = "POLARS_MAX_THREADS"

#: The accessor the pool reading looks for on a loaded numerics module: the
#: conventional spelling of "the pool this library sized for reductions".
#: A name rather than a library list, so the reading costs no import and a
#: library that spells it differently is recorded as unmeasured rather than
#: guessed at.
POOL_ACCESSOR = "thread_pool_size"

#: The cap variables a worker can declare *and* the one floor this module
#: knows by name, in one tuple: the names an environment can carry that
#: decide a reduction's thread count.  A child launched from a worker
#: inherits whatever is left in the worker's environment, which is why the
#: child-side question (:func:`inherited_threaded_variables`) is asked over
#: the whole tuple and not over §12's two alone.
CHILD_CAP_VARIABLES: tuple[str, ...] = (*sorted(THREAD_ENV_CAPS), POOL_VARIABLE)

#: The variable is not in the worker's environment at all: nothing was
#: declared and nothing was capped.  A refusal, unlike the device
#: sweep's unset variable, because this declaration is read by a library
#: rather than by this member's caller — see the module docstring.
ABSENT = "absent"
#: The variable is present and is the pin: the worker was started under
#: §12's row.  The one classification a clean verdict records.
CAPPED = "capped"
#: The variable is present and is *not* the pin — another integer, a blank,
#: or a value no library would read as a thread count.  A refusal naming the
#: value as written.
UNCAPPED = "uncapped"

#: ``strtol``'s shape with Python's integer grammar behind it: leading
#: ``strtol`` whitespace, an optional sign, then a non-empty run of decimal
#: digits — which under ``re``'s Unicode default is *any* script's decimal
#: digits, matching the integers :func:`int` parses.  Anchored with
#: ``\A``/``\Z`` so a trailing newline or space is part of the value rather
#: than silently trimmed: a library comparing the whole string sees it, and a
#: sweep that accepted it would be more permissive than the readers it
#: vouches for.  See the module docstring for why this is deliberately wider
#: in syntax than :data:`canary._ordering._SEED_RE`.
_CAP_RE = re.compile(r"\A[ \t\v\f\r]*[+-]?\d+\Z")


def classify_thread_cap(value: object) -> str:
    """The classification of a declared thread cap — the one place it is read.

    :data:`CAPPED` when the value names a pool of exactly one;
    :data:`UNCAPPED` when it names anything else a deployment could have
    written — a wider count, a blank, a token no library reads as a number,
    a non-string — and :data:`ABSENT` when the variable is not declared at
    all (``None``).

    The value must be an integer that :func:`int` parses — the ``strtol``
    shape in :data:`_CAP_RE`, which admits surrounding ``strtol`` whitespace,
    a sign, and any script's decimal digits — and it must equal one.  An
    ``int`` handed over directly (a caller sweeping an explicit declaration
    rather than an environment) is classified as the same value, so the two
    spellings cannot disagree about a declaration.  ``bool`` is excluded even
    though Python makes it an ``int``: no library reads ``True`` as a count,
    and the environment never carries it.

    Deliberately *not* strict the way :func:`~canary.classify_hash_seed` is:
    ``PYTHONHASHSEED``'s grammar lives in the interpreter and can be measured
    against it to the character, while the caps have no single owner and each
    library parses them its own way.  So this classifier has no
    "the runtime would not start under it" case, and every unplaceable value
    is :data:`UNCAPPED` rather than a third kind of refusal — a
    classification it could not justify would be one more thing to keep in
    sync (see the module docstring).

    Unset and blank are pulled apart explicitly, which is the distinction a
    caller is most likely to want and least likely to get from a boolean:
    ``None`` is :data:`ABSENT` (no declaration was made), while ``""`` and
    ``"   "`` are :data:`UNCAPPED` (a declaration *was* made and names no
    count, so the library reading it applies its own default of one worker
    per core).  Collapsing the pair would misdescribe a worker, and
    misdescribing a worker is the failure this category exists to prevent.
    """
    if value is None:
        return ABSENT
    if isinstance(value, bool):
        return UNCAPPED
    if isinstance(value, int):
        return CAPPED if value == 1 else UNCAPPED
    if not isinstance(value, str):
        return UNCAPPED
    if not _CAP_RE.match(value):
        return UNCAPPED
    return CAPPED if int(value) == 1 else UNCAPPED


def _describes_a_count(value: object) -> bool:
    """Whether a declared value names a *number* at all, pinned or not.

    Used only to word the refusal: ``"4"`` is a deployment that chose a wider
    pool and ``"auto"`` is one whose variable no parser will resolve, and an
    operator repairs those differently.  Kept beside the classifier because
    the *verdict* has no third state for it — see :func:`classify_thread_cap`
    on why unplaceable values are :data:`UNCAPPED` rather than their own
    classification.
    """
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, str) and bool(_CAP_RE.match(value))


def _is_blank(value: object) -> bool:
    """Whether a declared value was written and names nothing.

    ``""`` and ``"   "`` — present in the environment, so the variable looks
    configured, and empty to every reader.  The distinction from an absent
    variable is the one :func:`classify_thread_cap` exists to keep, and this
    is where the refusal for it is worded.
    """
    return isinstance(value, str) and not value.strip()


def interpreter_thread_pool(
    *,
    modules: Optional[Sequence[object]] = None,
) -> Optional[int]:
    """The thread pool a numerics library in this process resolved, if any.

    The witness that a declared cap was *honoured*, which no parser can be: a
    variable in the environment is a claim some library may or may not have
    read, and the pool it sized is the fact.  Reads the first module that
    exposes :data:`POOL_ACCESSOR` — a callable reporting the pool it will sum
    reductions with — and returns its answer as an ``int``; ``None`` when no
    module reports one.

    The modules walked are ``sys.modules`` by default — *already loaded*
    modules, so the reading costs no import and cannot make this package
    depend on the numerics whose threading it audits.  That is the whole
    design: a process that has loaded a numerics library gets a real
    measurement, and a process that has not gets ``None``, which is the
    honest answer rather than a zero or a one.  A caller that wants to ask
    about a specific library passes it in (``modules=[polars]``), which is
    how a nightly runner wires the reading in without this member importing
    anything.

    ``None`` is *unmeasured* and never *clean*: the sweep records it as
    :attr:`ThreadCaps.measured` false, which is the same stance the image
    sweep takes on a container it was asked nothing about.  A library that
    cannot answer — an accessor that raises, one that returns something
    :func:`int` will not take, one that reports a count that is not a pool of
    threads at all — is unmeasured too, for the same reason a refusal to guess
    runs through the whole module.  A count of zero or less is the last of
    those rather than a pool: it is a library saying it has no thread pool,
    which is not the same claim as "one thread", and the sweep must not read
    it as a measurement of anything.
    """
    candidates: Sequence[object] = (
        tuple(sys.modules.values()) if modules is None else tuple(modules)
    )
    for module in candidates:
        if module is None:
            continue
        accessor = getattr(module, POOL_ACCESSOR, None)
        if accessor is None or not callable(accessor):
            continue
        try:
            pool = int(accessor())
        except Exception:  # noqa: BLE001 - a library that cannot answer is unmeasured
            return None
        return pool if pool > 0 else None
    return None


@dataclass(frozen=True)
class ThreadCaps:
    """The worker's thread caps, swept and found single-threaded — the verdict.

    Feature 137's passing case, as a value: which cap variables the worker
    was started with and at what value, which of them was capped at a pool of
    one, and whether that pool was *measured* or assumed.  Frozen and
    ordered, so a nightly report can file one record per deployment and
    compare it across nights.

    A :class:`ThreadCaps` only ever exists when the sweep raised nothing, so
    every declaration it carries is the pin and every capping is a real
    one — the same all-or-nothing property :class:`~canary.DevicePaths`
    has, for the same reason: a record that could say "single-threaded" while
    carrying a threaded value is an audit nobody can act on.

    :attr:`measured` is the field worth understanding, because it is the only
    place this package records *how strong* the clean reading was.  A worker
    whose declarations were swept and whose pool was read from a loaded
    numerics library reports ``measured=True`` and a pool of one: the claim
    was checked against the fact.  A worker swept in a process that has no
    numerics loaded reports ``measured=False`` and the assumed pool of one:
    the declaration is clean and nothing contradicted it, and the nightly
    report that files this record can say which of the two nights it was.
    Only a pool wider than one is ever refused, so both readings are green —
    and they are different greens, which is the distinction this category
    keeps everywhere it records a verdict.
    """

    #: Every cap variable this worker declared, as ``(variable, value)``
    #: sorted by variable.  Only variables actually present in the swept
    #: environment: an absent or unpinned one is a refusal and never reaches
    #: a built value.
    declared: tuple[tuple[str, str], ...]
    #: The declared variables whose value caps the pool at one, in sorted
    #: order.  Always exactly :attr:`declared`'s names, since an uncapped
    #: declaration is refused before this value is built.
    capped: tuple[str, ...]
    #: The pool the sweep settled on: always ``1``, because a wider pool is
    #: the refusal this feature's verb exists for.  Recorded so a report
    #: carries the number it certified rather than only the word.
    pool_size: int
    #: Whether :attr:`pool_size` was read from a loaded numerics library
    #: rather than assumed from the declarations.
    measured: bool

    def __post_init__(self) -> None:
        # A clean verdict is a statement about a sweep that ran, so every
        # field is validated before the value exists. The alternative is a
        # record that could say "single-threaded" while carrying a declaration
        # the sweep refuses — precisely the shape of an audit nobody can act
        # on.
        declared = tuple(self.declared)
        for variable, value in declared:
            if variable not in THREAD_ENV_CAPS and variable != POOL_VARIABLE:
                raise CanaryThreadError(
                    f"a thread-caps verdict records {variable!r} as a declared "
                    "cap: the sweep reads the two variables architecture §12 "
                    f"names ({', '.join(sorted(THREAD_ENV_CAPS))}) plus the one "
                    f"pool floor it knows by name ({POOL_VARIABLE}), and a "
                    "verdict about any other variable would vouch for a knob "
                    "nothing here reads"
                )
            if classify_thread_cap(value) != CAPPED:
                raise CanaryThreadError(
                    f"a thread-caps verdict records {variable}={value!r}, which "
                    "is not the pin: a ThreadCaps is the clean verdict, built "
                    "only after every declaration that leaves a reduction "
                    f"threaded is refused, so a value it carries is "
                    f"{SINGLE_THREADED!r} — and a record that carried anything "
                    "else would say 'single-threaded' while naming a threaded "
                    "worker"
                )
        if tuple(sorted(declared, key=lambda entry: entry[0])) != declared:
            raise CanaryThreadError(
                "a thread-caps verdict records its declarations out of sorted "
                "variable order: a report compares two nights' records field by "
                "field, and a record whose order depends on the sweep that "
                "built it cannot be compared with itself"
            )
        names = tuple(variable for variable, _ in declared)
        if tuple(sorted(self.capped)) != names:
            raise CanaryThreadError(
                f"a thread-caps verdict names {self.capped!r} as the capped "
                f"variables of the declarations it records ({names!r}): every "
                "declaration a clean sweep admits caps the pool at one — one "
                "that did not is a refusal and never reaches a built value — so "
                "the two fields name exactly one set"
            )
        if not isinstance(self.pool_size, int) or isinstance(self.pool_size, bool):
            raise CanaryThreadError(
                f"a thread-caps verdict records a pool size of "
                f"{self.pool_size!r}, which is not an integer: the pool is a "
                "count of threads a library resolved, and a value that is not "
                "one cannot be the count"
            )
        if self.pool_size != 1:
            raise CanaryThreadError(
                f"a thread-caps verdict records a pool of {self.pool_size} "
                "threads: a ThreadCaps is the clean verdict, and a pool wider "
                "than one is the threaded worker this feature exists to refuse "
                "— a record that carried it would say 'single-threaded' while "
                "naming the failure"
            )
        if not isinstance(self.measured, bool):
            raise CanaryThreadError(
                "a thread-caps verdict records whether the pool was measured as "
                f"{self.measured!r}, which is not a bool: the reading is either "
                "a library's report or an assumption, and a value that is "
                "neither cannot be the distinction"
            )

    @property
    def variables(self) -> tuple[str, ...]:
        """The declared cap variables, in sorted order."""
        return tuple(variable for variable, _ in self.declared)

    def value(self, variable: str) -> Optional[str]:
        """The value ``variable`` was declared at, or ``None`` when absent."""
        for name, value in self.declared:
            if name == variable:
                return value
        return None

    @property
    def complete(self) -> bool:
        """Whether every variable §12's row names was declared by this worker.

        The first question a nightly report asks, as a property rather than
        an inference from :attr:`declared`: the sweep refuses an *absent*
        cap, so a built verdict always names both — this is the assertion of
        that fact, for a caller that does not want to hold the table and
        check for itself.
        """
        return all(variable in self.variables for variable in THREAD_ENV_CAPS)

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"ThreadCaps(declared={len(self.declared)}, "
            f"pool_size={self.pool_size}, measured={self.measured})"
        )


def _environment(env: Optional[Mapping[str, str]]) -> Mapping[str, str]:
    """The environment mapping a sweep reads the caps from.

    The caller's mapping when one is given — the same seam every other sweep
    in this member resolves through, so a test or an operator can hand the
    refusal an environment without touching the process — and the process
    environment otherwise.  Read at call time, never at import: importing
    this module must not consult the process's environment, for the reason
    every module in this package states.
    """
    return os.environ if env is None else env


def _entries(declarations: Mapping[str, object]) -> dict[str, object]:
    """Every cap-shaped declaration, with the absent ones filled in.

    ``declarations`` is what a caller or an environment holds; the result
    carries a key for every name in :data:`CHILD_CAP_VARIABLES`, with
    ``None`` where nothing was declared — so the sweep's subject is the
    *table* and a caller cannot narrow it by handing over a thin mapping.
    A name outside the table raises here, naming it: a declaration about a
    knob nothing in this module reads would otherwise be silently ignored,
    which is the failure mode the whole table exists to prevent.
    """
    unknown = sorted(name for name in declarations if name not in CHILD_CAP_VARIABLES)
    if unknown:
        raise CanaryThreadError(
            "a thread-caps declaration names "
            + ", ".join(repr(name) for name in unknown)
            + ": the sweep reads exactly "
            + ", ".join(repr(name) for name in CHILD_CAP_VARIABLES)
            + " (architecture §12's two caps and the one pool floor this module "
            "knows by name), and a declaration about any other variable would "
            "vouch for a knob nothing here reads"
        )
    return {
        name: declarations.get(name) for name in CHILD_CAP_VARIABLES
    }


def _refusal(variable: str, raw: object) -> str:
    """The refusal for one cap variable that is not the pin.

    Four cases, each worded for the repair it needs: absent (the worker was
    started without it), blank (present and naming nothing, so the library
    applies its own default), a numeric count that is not one, and a value no
    parser resolves to a count.  The layer — which library reads this
    variable — is named in every one, because an operator fixing a worker
    needs to know *which* reduction was left threaded.
    """
    layer = THREAD_ENV_CAPS[variable]
    if raw is None:
        return (
            f"{variable} is not set: this worker was started without the cap "
            f"that governs {layer}, so every reduction it makes is summed in "
            "as many partitions as the library's default picks — one worker "
            "per core — and floating-point addition is not associative, so the "
            "same bytes produce a different last bit on a different machine "
            "(architecture §12, 'Single-threaded numerics'). Set "
            f"{variable}={SINGLE_THREADED} in this worker's environment"
        )
    if _is_blank(raw):
        return (
            f"{variable}={raw!r} names no thread count: the variable is "
            "present, so it looks configured, and the library reading it "
            "applies its own default of one worker per core — a threaded "
            f"worker wearing the shape of a pinned one. Set "
            f"{variable}={SINGLE_THREADED}"
        )
    if _describes_a_count(raw):
        return (
            f"{variable}={raw!r} is not the pin: a thread count other than one "
            "leaves the reduction partitioned, so its sum depends on how the "
            "members were grouped rather than on the members — reproducible at "
            "this count on this host, and therefore quiet until the wheel, the "
            "library or the machine changes and every reduction moves "
            "together. §12's row names one value: set "
            f"{variable}={SINGLE_THREADED}"
        )
    return (
        f"{variable}={raw!r} is not a thread count at all: this worker "
        f"declared the cap that governs {layer} and no parser resolves what it "
        "declared to a number, so the reduction is summed at whatever the "
        "library defaults to — one worker per core — while the environment "
        "says the cap was set. Set "
        f"{variable}={SINGLE_THREADED}"
    )


def _pool_refusal(pool_size: int, declared: Sequence[tuple[str, str]]) -> str:
    """The refusal for a measured pool wider than one — the honest reading.

    The case §12's row does not reach on its own: the library that sized the
    pool resolves it without consulting the two variables, so the declaration
    is satisfied and the reduction is still partitioned — and the repair is to
    pin the floor that library reads (:data:`POOL_VARIABLE`).

    One shape, not two, and that is a fact about the sweep rather than a
    simplification: this is reached only when every cap classification passed,
    so ``declared`` always carries both of §12's variables.  A worker with
    nothing declared is refused by :func:`_refusal` long before the pool is
    consulted, which is right — *"started without"* is the feature's own verb
    and a sweep that reported the pool instead would be answering a question
    the worker's declaration already settled.

    Split out of :func:`_sweep` so the sweep reads as a sequence of
    classifications with one refusal shape each, rather than as a paragraph
    of string concatenation deciding what to say.
    """
    pinned = ", ".join(f"{name}={value}" for name, value in declared)
    return (
        f"the numerics loaded in this process report a thread pool of "
        f"{pool_size} for their reductions, so this worker is threaded "
        f"whatever its declarations say: {pinned} are declared, but the "
        "library that sized this pool resolves it without consulting the "
        "OMP caps — a worker can satisfy architecture §12's row to the "
        f"letter and still sum in {pool_size} partitions. Pin the floor "
        f"that library reads ({POOL_VARIABLE}) in this worker's "
        "environment"
    )


def _sweep(
    entries: Mapping[str, object],
    *,
    pool_size: Optional[int],
) -> ThreadCaps:
    """Classify every cap, refuse completely, record the reading.

    The one place the feature's *and* is enforced mechanically: both cap
    variables are classified, the known pool floor is classified with them,
    no failure is dropped, and the refusal raised carries all of them in
    sorted variable order.  ``entries`` is ``variable → value or None`` for
    every name in :data:`CHILD_CAP_VARIABLES`; the caller fills the absent
    ones in (:func:`_entries`) so the table is the subject rather than
    whatever mapping happened to arrive.

    ``pool_size`` is a measured pool (:func:`interpreter_thread_pool`) or
    ``None`` for an unmeasured one, and it is a parameter rather than a
    lookup so the sweep is a pure function of its inputs and the suite can
    exercise every branch without a numerics dependency.  A measured pool
    wider than one is refused — *before* the verdict is built, so the
    refusal names which declarations were and were not there to bound it —
    because a sweep that certified a worker whose numerics are visibly
    threaded would be the vacuous green this category exists to prevent.
    """
    failures: list[str] = []
    declared: list[tuple[str, str]] = []
    for variable in CHILD_CAP_VARIABLES:
        raw = entries.get(variable)
        kind = classify_thread_cap(raw)
        if kind == CAPPED:
            declared.append((variable, str(raw)))
            continue
        if variable == POOL_VARIABLE:
            # The library-level floor: not §12's row, so an absent one is not
            # a refusal (nothing here can say what a deployment's own library
            # should default to) — but a *declared* value that is not the pin
            # is, because it is the one knob that outranks the caps inside the
            # library that reads it, and a worker certified by this sweep
            # would be threaded while both of §12's variables were pinned.
            if raw is None:
                continue
            failures.append(
                f"{variable}={raw!r} is declared and is not the pin: this is "
                "the library-level pool floor, which the library that reads it "
                "resolves without consulting "
                f"{', '.join(sorted(THREAD_ENV_CAPS))}, so a worker with both "
                "caps pinned and a floor like this is threaded anyway — and "
                "inherited by every child that worker launches. Remove the "
                f"declaration, or set {variable}={SINGLE_THREADED}"
            )
            continue
        failures.append(_refusal(variable, raw))
    if failures:
        raise CanaryThreadError(
            "an evaluation worker was started without single-threaded "
            f"numerics — {len(failures)} declarations refused:\n  "
            + "\n  ".join(failures)
        )
    if pool_size is not None and pool_size > 1:
        raise CanaryThreadError(_pool_refusal(pool_size, declared))
    return ThreadCaps(
        declared=tuple(declared),
        capped=tuple(variable for variable, _ in declared),
        pool_size=1,
        measured=pool_size is not None,
    )


def reject_threaded_workers(
    declarations: Mapping[str, str],
    *,
    pool_size: Optional[int] = None,
) -> ThreadCaps:
    """Refuse a worker whose declared caps leave a reduction threaded.

    The explicit-declaration spelling, for a test or a caller that holds the
    cap values directly rather than through an environment: every variable in
    :data:`CHILD_CAP_VARIABLES` is classified, every failure is collected, and
    one :class:`~canary.CanaryThreadError` names them all (see the module
    docstring for why the refusal is complete rather than first-wins).  A
    variable the mapping does not carry is read as :data:`ABSENT` — the
    refusal that gives this feature its verb — so a caller cannot narrow the
    sweep by handing it a thin mapping, and a name outside the table is
    refused rather than ignored.

    ``pool_size`` is the measured-pool seam, passed through to the sweep.  It
    defaults to an unmeasured reading, so the explicit spelling is a pure
    function of a declaration and needs no numerics in the process;
    :func:`reject_threaded_workers_from_env` is the environment spelling.
    """
    if not isinstance(declarations, Mapping):
        raise CanaryThreadError(
            "a thread-caps declaration must be a mapping of variable to value, "
            f"got {type(declarations).__name__}; the sweep reads one "
            "declaration per variable, not a sequence of maybe-related strings"
        )
    for name in declarations:
        if not isinstance(name, str) or not name.strip():
            raise CanaryThreadError(
                "a thread-caps declaration's variable must be a non-empty "
                f"string, got {name!r}; the variable is the word the refusal "
                "names, so a variable that cannot be named cannot be swept"
            )
    return _sweep(_entries(declarations), pool_size=pool_size)


def reject_threaded_workers_from_env(
    env: Optional[Mapping[str, str]] = None,
    *,
    pool_size: Optional[int] = None,
) -> ThreadCaps:
    """Refuse a worker started without single-threaded numerics — feature 137.

    The feature's own sentence, read off the environment this worker was
    started under: each variable in :data:`THREAD_ENV_CAPS` is classified,
    and one that is absent, blank, or present at anything but the pin is
    refused — naming the variable, the layer it governs and the value as
    written.  A declared pool floor that is not the pin is refused with them,
    because it outranks the caps inside the library that reads it.

    ``env`` is the same mapping seam the pin, device and order sweeps resolve
    through, so a test or an operator can hand the refusal an environment
    without touching the process; the process environment is read when it is
    ``None``.

    ``pool_size`` is the measured-pool seam, and it is deliberately *not*
    filled in here: measuring means loading the numerics to ask them, which
    this package may not do on the factory scan path (see the module
    docstring).  A caller that holds a numerics module — the nightly runner,
    §5.2's sandbox host — passes
    ``pool_size=interpreter_thread_pool()``, and the sweep then refuses a
    pinned worker whose pool is visibly wider than the declaration claims,
    which is the case §12's row does not reach on its own.
    """
    source = _environment(env)
    return _sweep(
        _entries({name: source[name] for name in CHILD_CAP_VARIABLES if name in source}),
        pool_size=pool_size,
    )


def thread_capped_environment(
    env: Optional[Mapping[str, str]] = None,
) -> dict[str, str]:
    """The environment to *start* a worker under — both caps at the pin.

    Feature 137's remedy, as a value.  The caps are read by the numerics at
    their own import, so nothing can repair a process that has already
    started; what a launcher *can* do is hand a child an environment that
    carries the pin, and this is that environment, built once so there is
    exactly one spelling of the pin in the system — the same stance
    :func:`~canary.pinned_environment` takes for the hash seed.

    Takes the base environment to copy — the process environment by default —
    and returns a **new** mapping with both caps written in, never mutating
    the base: two callers building from one environment must not fight over
    it, and a function that wrote to ``os.environ`` would be changing the
    ambient shell as a side effect of building a value.  Where a declaration
    is already present the pin **wins**, because the whole point of the row is
    that the value is ``1`` and a launcher that preserved an inherited
    ``OMP_NUM_THREADS=16`` while claiming to pin the worker would be the very
    failure this feature exists to catch, one layer down.

    The one variable carried forward rather than overridden is the
    library-level pool floor this module knows by name, and it is carried
    **only where the base already declared it**: a floor is a deployment's own
    choice about its own library — unlike §12's two caps, which the row fixes
    — so this function neither invents one nor removes one, it refuses to be
    the layer that drops a declaration the deployment made.  A deployment
    whose floor is wider than the pin is refused by the sweep, not silently
    repaired here, because that is a declaration about the deployment and the
    caller is the one who can decide what to do with it;
    :func:`child_thread_environment` is the spelling for a *child*, where
    removing it is the right answer.
    """
    capped = dict(_environment(env))
    for variable in THREAD_ENV_CAPS:
        capped[variable] = SINGLE_THREADED
    return capped


def inherited_threaded_variables(
    env: Optional[Mapping[str, str]] = None,
) -> tuple[str, ...]:
    """The cap names in ``env`` that would make a *child* threaded.

    Every name in :data:`CHILD_CAP_VARIABLES` present in ``env`` whose value
    is not the pin, in sorted order — the trap a launched child inherits.
    Derived from the same table the sweep reads, so the producing and reading
    halves cannot disagree about what a cap is.

    This is the half a launcher needs and a sweep cannot supply, and it is
    spelled as *names to remove* rather than *values to use* on purpose: the
    common remedy (export the two caps to one, then launch) leaves the
    library-level floor untouched, and a child that reads it outranks the pin
    its parent wrote for it.  So a caller about to start a child asks this
    question and clears the names it returns from the child's environment —
    which is exactly what :func:`child_thread_environment` does.  An
    environment that declared no such value returns the empty tuple, which is
    the honest answer and emphatically not "clean": the child is bounded by
    the caps the caller is about to write, and the sweep is what decides
    whether there was a declaration behind them.
    """
    source = _environment(env)
    return tuple(
        sorted(
            name
            for name in CHILD_CAP_VARIABLES
            if name in source and classify_thread_cap(source[name]) != CAPPED
        )
    )


def child_thread_environment(
    env: Optional[Mapping[str, str]] = None,
) -> dict[str, str]:
    """The environment to launch a *child* under — traps removed, pin written.

    :func:`thread_capped_environment` writes the pin; a child launched from an
    environment that also carries a wider floor would inherit the floor and
    outrank the pin inside the library that reads it.  So this removes every
    name :func:`inherited_threaded_variables` reports and then writes both
    caps at the pin — by delegating to the producing half rather than
    repeating it, so there is one spelling of the pin and the two cannot
    drift.

    A convenience over composing the two, kept because composing them by hand
    at every launch site is how one site ends up writing the caps and
    forgetting the removal.  What it does *not* do is start anything or touch
    the current process: like every producing function here, it hands the
    environment back.
    """
    source = _environment(env)
    trapped = frozenset(inherited_threaded_variables(source))
    pruned = {name: value for name, value in source.items() if name not in trapped}
    return thread_capped_environment(pruned)


@contextmanager
def single_threaded(
    *,
    env: Optional[Mapping[str, str]] = None,
    pool_size: Optional[int] = None,
    modules: Optional[Sequence[object]] = None,
) -> Iterator[ThreadCaps]:
    """The span a worker justified as single-threaded — swept, then rechecked.

    Feature 137 as the thing a caller can hold: the environment is swept on
    entry (the same refusal :func:`reject_threaded_workers_from_env` raises,
    through the same sweep), the verdict is yielded, and on a clean exit the
    pool is read again and a **widening** is refused.  The exit check is what
    makes this a span rather than a reading: a ``set_num_threads(16)`` after
    the sweep, or a second numeric library loaded whose default outranks the
    caps for solving the reduction, is a break of the row *inside* the extent
    and is caught at the boundary that can name it rather than at the next
    night's ``1e-12`` comparison.

    The check is deliberately **monotone and bounded**, and both halves of
    that are decisions.  Monotone: only a pool *wider* than the one measured
    on entry is refused, never a narrower one, because narrowing cannot
    reintroduce the divergence and refusing it would make the span unusable
    on a path that legitimately tightens its own threads.  Bounded: it cannot
    see a pool resolved before the span was entered, which is why the
    measured-pool refusal exists at all — the entry sweep is the one that
    checks the declaration against the pool that is actually there, this exit
    check catches drift during the extent, and neither is a guarantee about a
    process this module did not start.  §5.2's sandbox is that guarantee, and
    the module docstring says so.

    ``pool_size`` short-circuits the entry measurement with one the caller
    already holds; ``modules`` selects which loaded modules the measurement
    walks (:func:`interpreter_thread_pool`).  A process with no numerics
    loaded measures ``None`` — the span then checks nothing and records an
    unmeasured verdict, which is the honest reading rather than a green one.

    If the body raises, that failure propagates unchanged and the exit check
    is skipped: the run's own error is the informative one, and replacing it
    with a secondary complaint about threads would hide why the run failed.
    """
    entry = pool_size if pool_size is not None else interpreter_thread_pool(modules=modules)
    verdict = reject_threaded_workers_from_env(env, pool_size=entry)
    # Everything below the yield *is* the clean-exit half, and it needs no
    # ``except`` to be one: a context manager's generator has the body's
    # exception thrown into it at the yield point, so a failing body leaves the
    # frame here and the exit check never runs — the run's own error
    # propagates unchanged, which is what it should do, and a thread complaint
    # raised in its place would hide why the run failed.
    yield verdict
    after = interpreter_thread_pool(modules=modules)
    if after is not None and after > verdict.pool_size:
        raise CanaryThreadError(
            f"the thread pool of this process widened from "
            f"{verdict.pool_size} to {after} inside a span justified as "
            "single-threaded: the reduction that runs after this point is "
            "summed in partitions the sweep never vouched for, so the "
            "extent's verdict no longer describes the worker it was made "
            "about. A threaded reduction is not reproducible — dropping the "
            "offending step, or moving it outside the span, is the repair; "
            "widening the pool and keeping the verdict would move the "
            "promise into the library's hands, which is what architecture "
            "§12's 'Single-threaded numerics' row forbids"
        )
    if after is not None and not verdict.measured:
        # The exit reading is the first evidence this span got; record it
        # rather than leaving the verdict claiming a reading it did not
        # have, so a report can tell a checked night from an assumed one.
        verdict = ThreadCaps(
            declared=verdict.declared,
            capped=verdict.capped,
            pool_size=verdict.pool_size,
            measured=True,
        )
