"""The cost model plugin's error taxonomy.

One base class (:class:`CostModelError`) so callers — the evaluator's
``apply_costs`` step, the live execution path that must import the same
library, an operator tool — can catch every failure of this package with a
single ``except``.  The subclasses split by *which contract* was violated,
not by which line of code failed:

* :class:`CostModelConfigError` — the document contract.  The YAML
  configuration §6.2 specifies could not be read as a cost model: a file
  that cannot be opened, bytes that are not YAML, a document that is not a
  mapping (or holds several), a missing ``cost_model`` block, or a block
  whose ``version``/``venue`` is absent, blank, or not even a string.  Each
  is a misconfiguration — a caller bug or a corrupt signed artifact — and
  never a runtime condition to retry.
* :class:`CostModelStoreError` — the persisted-record contract.  Feature 59
  says the resolved version and venue are *persisted*, so a store that was
  configured and then failed to take the row is an error rather than a
  shrug: the alternative is a cost model that silently never lands, which is
  the state the feature exists to rule out.  A store that was never
  configured at all is not this error — see :mod:`cost_model.service` for
  the stance that separates the two.

Every message names the offending value and the contract it broke, because
these are operational signals for a pipeline that loads a Z0 artifact on
schedule (docs/nullius-tech-architecture.md §2, §6.2), not debugging aids.
"""

from __future__ import annotations

__all__ = [
    "CostModelConfigError",
    "CostModelError",
    "CostModelStoreError",
]


class CostModelError(Exception):
    """Base class for every failure of the cost model package."""


class CostModelConfigError(ValueError, CostModelError):
    """The loaded YAML configuration is not a cost model.

    Dual-inherited on purpose: an invalid configuration is a
    :class:`ValueError` the way the universe member's config validation is
    one — a mistake in a value, refused at construction so the failure lands
    on whoever supplied it — and it is also a :class:`CostModelError`, so a
    caller catching this package's single vocabulary catches a bad document
    along with a failed persist.  Both ``except ValueError`` and ``except
    CostModelError`` work, and neither had to be special-cased into the
    other's type.

    Raised for the document's own defects (unreadable file, unparseable
    YAML, not a mapping, missing or unusable ``version``/``venue``) and
    never for a store failure, which is :class:`CostModelStoreError`.
    """


class CostModelStoreError(CostModelError):
    """The resolved cost model could not be persisted.

    Feature 59: *"System persists the resolved cost model version string
    with its venue name after loading the YAML configuration."*  This is the
    failure of the second half of that sentence: the configuration loaded,
    and the row that records it did not land.  It is raised rather than
    swallowed — a cost model that resolved but was never persisted is
    exactly the gap the feature closes, and the process that goes on to
    evaluate against it would be a process whose scores name fee
    assumptions nothing in the store can resolve.

    A store that is merely *absent* (no ``DATABASE_URL``, and no explicit
    URL passed) is not this error: this package treats "no relational store
    configured" as a supported state and refuses the persist with this error
    only at the moment a caller actually asks for one, naming the variable
    that would have named the store.
    """
