"""The policy-runtime error vocabulary — one base class, split by contract.

The base class for every failure of the policy-runtime path, and the eight
subclasses that path raises.  One base class so a caller — the replay engine,
the dreaming loop, an operator script, a later feature in this category — can
catch every failure of the read-side question path with a single ``except``,
the discipline :mod:`bootstrap.errors` and :mod:`artifacts._errors` state for
their own trees.  The subclasses split by *which contract* was violated, not by
which line of code failed.

Two of them — :class:`PolicyTreeError` and its child :class:`PolicyAddressError`
— are the tree's: a node that is empty or misspelled, a depth that is not an
integer, a payload that is not canonical JSON, a dangling parent reference, or a
node id that names a cell no tree can reach.  The third —
:class:`PolicyAdmissionRefusal` (features 230 and 231) — is the admission
gate's: a policy's authored source that carries an absolute score constant, a
hardcoded node id, a terminating path that never reaches ``commit()``, or a
learned component (a model-framework import, a checkpoint load, an inference
call, deferred by docs §11.2 until the M1 triage decides it).  It is kept
apart from the tree's two because the tree itself was well-formed and the ask
reached the lattice — it is the *source* that broke the contract, not a node the
question fronted — but a :class:`PolicyRuntimeError` all the same, so the one
base class still catches it.

The fourth — :class:`BetaFixedError` (feature 226) — is the *episode scalar's*:
a value that is not a finite real number at the one moment beta is read, or a
reassignment of a beta already read.  It is kept apart from the admission
gate's because the contract is a different one in a different place: the gate
judges a policy's authored *source* before an episode begins, while this one
guards a value *during* an episode — and a caller that catches a policy refusal
and retries the authoring agent is not the caller that should catch a moved
scalar.  A :class:`PolicyRuntimeError` all the same, so the one base class
still catches every failure of the read-side path.

The fifth — :class:`FamilyThresholdError` (feature 228) — is the *family
conditioning's*: a policy-authored conditional over the schedule that names a
threshold key outside the one mapping, carries a magnitude that is not one, or
is keyed on a theme that cannot be keyed.  It is kept apart from
:class:`BetaFixedError` because the scalar was read honestly and the schedule
was well-formed — it is the conditioning authored *over* them that broke the
routing law, and the repair is a resubmitted conditional, not a different
episode.  A :class:`PolicyRuntimeError` all the same, so the one base class
catches it too.

The sixth and seventh — :class:`PolicyFilesystemError` and
:class:`PolicyImportError` (feature 225) — are the *runtime guard's*: the two
halves of §10.2's closing sentence, *"The policy runtime additionally blocks:
``question.best_so_far``, ``question.budget_spent``, filesystem access, and any
import outside an allowlist."*  They are one feature's two refusals and they
are kept apart from *each other* because they are repaired differently — a
policy that opened a file has reached past every prefix it was shown, while one
that imported a module outside the ceiling reached for a capability the ceiling
never admitted — and they are kept apart from :class:`PolicyAdmissionRefusal`
because they are raised at a different *moment*.  That refusal judges a
policy's authored **source** statically, before an episode begins; this pair
refuses the policy's **execution** while it runs.  The gap is the reason the
feature exists: a source can pass every static check in features 230 and 231
and still reach for a file — a path spelled at runtime, a module named through
a computed name — which is exactly what feature 225's runtime enforcement
catches and no static screen can.  Both are :class:`PolicyRuntimeError`, so a
caller catching the read-side path's one base class catches a guarded policy's
refusal too.

The eighth — :class:`PolicyAnswerSurfaceError` (feature 224) — is the *answer
surface's*: an attribute of an episode's answer surface that is one of the two
docs §10.2 names as forbidden (``best_so_far``, ``budget_spent``), or that is
not a legal-action query at all.  It is the one refusal in this module that is
**also** an :class:`AttributeError`, and the doubling is the feature rather
than an accident of the hierarchy: docs §10.2's third escape hatch is that a
policy *"cannot reach them by introspection, attribute walking…"*, and the
attribute protocol's own error is what ``getattr``, ``hasattr`` and a
``dir()``-driven walk all terminate in.  A caller reaches this refusal by the
ordinary act of reading an attribute, so it has to be catchable the way an
attribute read is caught — while remaining a :class:`PolicyRuntimeError`, so
the one base class still catches it and a caller who never heard of the
attribute protocol is not left holding an unnamed failure.  It is kept apart
from the runtime guard's pair (feature 225) because the surface it defends is
a different one: 225 refuses what a running policy *does to its environment*
(a file, an import), while this refuses what the policy is *handed* — the
answers an episode may give — and the two are repaired in different places, by
different owners.

These live in their own module rather than in the package ``__init__`` for two
reasons.  One, it is the house shape — every sibling member (``sandbox``,
``signal_agent``, ``discovery``) keeps its errors in an ``errors`` module, and
a member that reaches another member's error type does so through a stable,
import-cheap path.  Two, the planning law (:mod:`.planning`) subclasses
:class:`PolicyRuntimeError` at class-definition time, so it needs the base
class at import, not lazily — and importing it from ``__init__`` would be a
circular import, since ``__init__`` imports the planning law.  A dedicated
``errors`` module, importing nothing from the package, breaks that cycle: the
package imports the errors, the errors import nothing back.
"""

from __future__ import annotations


class PolicyRuntimeError(Exception):
    """The base class for every failure of the policy-runtime path.

    One base class so a caller — the replay engine, the dreaming loop, an
    operator script, a later feature in this category — can catch every
    failure of the read-side question path with a single ``except``, the
    discipline :mod:`bootstrap.errors` and :mod:`artifacts._errors` state for
    their own trees.  The subclasses split by *which contract* was violated,
    not by which line of code failed.
    """


class PolicyTreeError(PolicyRuntimeError):
    """A campaign tree could not be addressed as the thing the caller named.

    A node id that is empty or misspelled, a depth that is negative or not an
    integer, a payload that is not canonical JSON, a duplicate node id, or a
    parent reference that names a node the tree does not hold.  Raised before
    any observation is computed, so a refused tree answers no node at all —
    the same "name the subject in the refusal" discipline
    :class:`bootstrap.BootstrapWorldError` applies to a world.
    """


class PolicyAdmissionRefusal(PolicyRuntimeError):
    """A policy could not be admitted — a static check found an anti-pattern.

    Raised by :meth:`PolicyAdmissionDecision.require` on the caller's last line
    before it admits a policy — the bridge between the gate's returned verdict
    and the exception a caller wants there, the same role
    :meth:`PlanGridDecision.require` plays for feature 229 and
    :meth:`sandbox.ModuleDecision.require` plays for feature 167. The gate
    itself (:func:`screen_policy`) raises nothing: it returns a
    :class:`PolicyAdmissionDecision`, so a caller auditing a *history* of
    policies can read the verdict without a try/except. Only :meth:`require`
    raises, and it carries the refusal's own sentence, so the admission log and
    the retry prompt say the same thing.

    Kept apart from :class:`PolicyTreeError`/:class:`PolicyAddressError` because
    the tree itself was well-formed and the ask reached the lattice — it is the
    *policy's authored source* that broke the admission contract, not a node the
    question fronted. A subclass of :class:`PolicyRuntimeError` all the same, so
    a caller catching the read-side path's one base class catches an admission
    refusal too — the single-except discipline :mod:`bootstrap.errors` and
    :mod:`artifacts._errors` state.
    """


class PolicyAddressError(PolicyTreeError):
    """A node id named a cell no tree the question fronts can reach.

    Kept apart from :class:`PolicyTreeError` because the tree itself was
    well-formed — the ask reached the lattice — and it is the *node* that is
    outside it.  A policy is shown its legal actions and reveals only cells it
    was shown, so a node id a policy hands to the question is one it was
    shown, and a node outside the lattice names a cell the policy never saw.
    The refusal names the node and the tree, so an operator reading a replay's
    failure can tell *which* node refused and *what tree* it was asked of.
    """


class BetaFixedError(PolicyRuntimeError):
    """An episode's beta scalar could not be read, or was reassigned after it was.

    Feature 226's contract, from both sides.  At initialization: a value that is
    not a finite real number — a ``bool``, text, ``None``, a NaN — is refused
    rather than coerced, because the scalar is one number the whole episode is
    compared under and a mistyped configuration that becomes a silent episode is
    the failure the check exists for.  After initialization: *every* path by
    which a caller could move it — ``beta.value = x``, ``beta._value = x``, a
    shadow attribute, ``del beta.value`` — raises here, because docs §609 fixes
    beta for the episode so every threshold in it (feature 227's schedule)
    derives from one number that does not move, and "carried over from the paper
    unchanged because it is what makes cross-cycle comparison legible".

    Kept apart from :class:`PolicyAdmissionRefusal` because it is a different
    contract in a different place: that refusal judges a policy's authored
    *source* before an episode begins and is repaired by resubmitting, while
    this one guards a value *during* an episode and is not repaired at all — a
    different beta is a different episode, not a reassignment of this one.  The
    precedent is feature 10's :class:`contract.MarketWindow`, which fixes a
    decision time at construction and refuses reassignment in the same shape and
    for the same reason.  A subclass of :class:`PolicyRuntimeError` all the
    same, so a caller catching the read-side path's one base class catches a
    moved scalar too.
    """


class FamilyThresholdError(PolicyRuntimeError):
    """A family-conditional threshold could not be routed through the schedule.

    Feature 228's contract, from both ends of it.  On the *authored* end: a
    conditional whose ``theme_root`` cannot be keyed (not a non-empty string),
    whose ``adjustments`` name a threshold key outside the one mapping
    :func:`policy_runtime.schedule` returns (a threshold derived anywhere but
    through that mapping is a second beta — docs §609 — arriving here through a
    family key instead of a second formula), whose adjustments carry a
    magnitude that is not a finite real number, or that adjust nothing at all
    (a conditional that adjusts nothing conditions nothing).  On the *composed*
    end: an evidence count that is negative or not a magnitude (evidence
    accumulates from zero; a NaN weight shrinks no threshold toward anything),
    or two conditionals keyed on one theme (which one wins is not a question
    the schedule answers silently).

    Kept apart from :class:`BetaFixedError` because it is a different law in a
    different place: that one guards the *scalar* an episode was opened on and
    is not repaired at all, while this one guards the *family conditioning* a
    policy authored over that scalar's schedule and is repaired by resubmitting
    the conditional — the split 226/227/228 draw across the beta knob (the
    scalar, the mapping, the family dimension), each refusing its own failure.
    A subclass of :class:`PolicyRuntimeError` all the same, so a caller
    catching the read-side path's one base class catches a refused conditional
    too.
    """


class PolicyFilesystemError(PolicyRuntimeError):
    """A policy reached the filesystem while the guard held its episode.

    Feature 225's first half: docs §10.2 — *"The policy runtime additionally
    blocks: … filesystem access …"* — and the sentence's subject is a policy
    that has already been admitted.  The runtime guard
    (:func:`policy_runtime.guard_policy`) raises this from the interpreter's
    own audit channel, where the filesystem call is visible as the call it is:
    :func:`open`, :func:`os.listdir`, :func:`os.remove`, :func:`shutil.copyfile`
    and their kind, each refused before it can touch a byte, naming the
    operation and its argument.

    It is kept apart from :class:`PolicyRuntimeError`'s other children because
    the *repair* is its own — a policy that reads a file is reaching past the
    prefix it was shown, and the fix is to take the data as an argument rather
    than to reach for it — and apart from :class:`PolicyImportError` because
    the two halves of the sentence are two different reaches: importing ``os``
    is a capability the ceiling never admitted, while opening a path is an
    access the capability would have bought.  One is refused at the import,
    the other at the call, and a caller reading a refusal is told which.
    """


class PolicyImportError(PolicyRuntimeError):
    """A policy imported a module outside the configured allowlist.

    Feature 225's second half: docs §10.2's *"… and any import outside an
    allowlist"*, and §11.1's *"no imports outside the allowlist"* among the
    static checks before any policy is admitted — stated here as the runtime
    enforcement behind those checks.  The ceiling is the same configured
    document feature 167 screens a submitted module against
    (:data:`sandbox.imports.COMMITTED_IMPORTS_ALLOWLIST`); this refusal is
    what happens when a policy reaches an import the *static* screen could not
    see, which is exactly the case a computed module name creates.

    It is kept apart from :class:`PolicyFilesystemError` because the repair is
    its own — a policy that imports ``subprocess`` has reached for a capability
    the ceiling never admitted, and the fix is to stay inside the allowlist,
    not to pass a path differently — and apart from
    :class:`PolicyAdmissionRefusal` because that one refuses a policy's
    authored source before it runs, while this one refuses the running
    episode's own import.  The refusal names the module and the ceiling, so
    the author reads what was refused and against what.
    """


class PolicyAnswerSurfaceError(PolicyRuntimeError, AttributeError):
    """An episode's answer surface was asked for an attribute it does not answer.

    Feature 224's contract: docs/nullius-tech-architecture.md §10.2 — *"The
    policy runtime additionally blocks: ``question.best_so_far``,
    ``question.budget_spent``, filesystem access, and any import outside an
    allowlist."* The first two of those four are this class's, and they are the
    two the *surface* can refuse rather than the two a running policy has to be
    caught doing: an attribute read is a request to an object the runtime
    already controls, so the refusal is available one seam earlier than 225's
    pair, before anything has been reached for at all.

    **It is an :class:`AttributeError` as well as a
    :class:`PolicyRuntimeError`**, and this is the only class in this module
    that is two things.  The feature's own sentence names the mechanism —
    *"rejects an attribute walk that attempts to reach them"* — and §10.2 names
    the same act from the prefix side: a policy *"cannot reach them by
    introspection, attribute walking, or a stray ``__dict__`` access."* An
    attribute walk is spelled ``getattr``, ``hasattr`` or a ``dir()``-driven
    loop, and every one of those terminates on :class:`AttributeError`; a
    refusal that were only a :class:`PolicyRuntimeError` would raise *through*
    a walk that had already decided the name was absent, so ``hasattr`` would
    answer a question about the law rather than about the surface and a
    defensive ``try/except AttributeError`` in the policy would not see it.
    Doubling the base keeps both readings true at once: a policy's own
    attribute-protocol handling catches it exactly as ``hasattr`` would have,
    and a caller that catches the read-side path's one base class catches it
    too — the single-``except`` discipline the rest of this module keeps.

    It is kept apart from the runtime guard's pair because the surface it
    defends is not the same one.  :class:`PolicyFilesystemError` and
    :class:`PolicyImportError` refuse what a *running* policy does to its
    environment; this refuses what the policy is *handed* — the answers an
    episode is willing to give — and the repair belongs to a different owner
    (the runtime's surface, not the sandbox's ceiling).  Every refusal names
    the attribute that was asked for.
    """
