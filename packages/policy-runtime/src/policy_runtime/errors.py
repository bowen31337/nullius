"""The policy-runtime error vocabulary — one base class, split by contract.

The base class for every failure of the policy-runtime path, and the two
subclasses the read-side question path raises.  One base class so a caller —
the replay engine, the dreaming loop, an operator script, a later feature in
this category — can catch every failure of the read-side question path with a
single ``except``, the discipline :mod:`bootstrap.errors` and
:mod:`artifacts._errors` state for their own trees.  The subclasses split by
*which contract* was violated, not by which line of code failed.

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
