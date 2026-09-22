"""The policy-runtime error vocabulary — one base class, split by contract.

The base class for every failure of the policy-runtime path, and the four
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
