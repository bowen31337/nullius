"""The failure modes of pinning a node's authoring model — feature 203.

Feature 203 is *"System persists ``agent_model_id`` per node as a provider,
model and version triple rather than a rolling alias"*, and this module is the
vocabulary of everything that sentence refuses.  It is a **separate base class
from :class:`providers.ProviderError`**, and the separation is the whole reason
this file exists rather than four classes appended to :mod:`providers._errors`.

:mod:`providers._errors` states its own boundary in as many words: the errors
there *"are the failure modes of that seam, and no other: they are raised by
the interface's own guardrails ... never by a provider's transport, a network,
or the model itself"*, and its base exists so a caller catching
:class:`~providers.ProviderError` is catching *"the provider contract was
violated"*.  A node stamped with a rolling alias is not a call that failed and
not a provider that returned the wrong shape; it is a **record** that cannot be
read as an authoring-model pin.  Folding it under ``ProviderError`` would make
every ``except ProviderError`` in the deployment answer two unrelated questions
at once — *did the model call work?* and *is this node's author identifiable?*
— which is the collapse :mod:`providers._errors` refuses for its own four
classes.  So the two taxonomies share no ancestor, and a caller that wants both
writes two ``except`` clauses.

The splits follow the contract's own shape — *what* could not be pinned, never
which line failed:

* :class:`ModelPinError` — the base, one handle for every failure of feature
  203's sentence.  It is also raised *directly* for the two failures no
  subclass describes: the store itself is unusable (a ``DATABASE_URL`` whose
  scheme this member cannot speak, a URL naming no database path), and the
  node id handed in is not a UUID.  That is the move
  :class:`providers.RecordingProvider` makes when it raises
  :class:`~providers.ProviderError` for a non-provider argument — a contract
  violation that is genuinely none of the named cases has no subclass to
  wear, and minting one class per call site is how a taxonomy stops
  describing anything.  The subclasses below each answer a question a caller
  can *act on*; "your URL is not sqlite:///" and "your node id is not a UUID"
  have no such question beyond the message itself.

* :class:`RollingAliasError` — the value is not a triple.  The load-bearing
  one, and the feature's own words: ``'deepseek-flash'`` names a target the
  provider is free to re-point, so a node stamped with it belongs to no model
  stratum.  Raised both on the way in (a caller offering
  ``persist(node, 'deepseek-flash')``) and on the way out (a store already
  holding one), because the alternative on the read side — reporting an alias
  as a pin — is exactly the corruption §14.1's mitigation exists to prevent.

* :class:`ModelPinConflictError` — the node already records a *different*
  triple.  A node's author is history: it is the variable the M3 paired
  comparison stratifies on (PRD §5a, architecture §14.1), so re-stamping a node
  with a second model would silently move every score it carries into another
  stratum.  Refused rather than overwritten, the same stance
  ``discovery.CampaignRecords`` takes for a re-issued plan that disagrees with
  the stored campaign.

* :class:`NodeNotRecordedError` — there is no node row to stamp.  Distinct from
  a conflict for the reason :mod:`providers._errors` keeps
  :class:`~providers.ProviderNotConfiguredError` distinct from
  :class:`~providers.CompletionMalformedError`: "nothing is there" and "what is
  there says otherwise" are different problems, and a caller that cannot tell
  them apart cannot report which one to fix.

* :class:`PinColumnError` — the ``node`` table or its ``agent_model_id`` column
  is absent.  A deployment gap: the tree store this process is pointed at has
  not reached revision ``0115``, so the column the value belongs in does not
  exist.  Named separately because it is the one failure whose repair is
  *run the migration* rather than *fix the value or the caller*.

Stdlib-only, like the rest of this tree.
"""

from __future__ import annotations

__all__ = [
    "ModelPinConflictError",
    "ModelPinError",
    "NodeNotRecordedError",
    "PinColumnError",
    "RollingAliasError",
]


class ModelPinError(Exception):
    """Base of feature 203's taxonomy — a node's authoring model could not be pinned.

    One base class so a caller can catch every failure of the pinning
    sentence with a single ``except``, the way :class:`providers.ProviderError`
    gives the *call* seam one handle.  The two bases are deliberately
    unrelated; see the module docstring.  The subclasses split by which
    question the refusal is answering — *is this value a triple?*, *does this
    node already record a different one?*, *is there a node at all?*, *does
    the column exist?* — never by which line of code failed.
    """


class RollingAliasError(ModelPinError):
    """A model identifier is not a provider/model/version triple.

    Feature 203's own words, and the reason the feature exists: *"rather than a
    rolling alias"*.  A provider alias re-routes silently — architecture §14.1
    records DeepSeek retiring ``deepseek-v4-flash`` on 2026-09-10 while
    continuing to accept the id and serving V4.1-Flash underneath it — so a
    campaign run in August and one in September under the same model string
    were generated by *different models*.  A node stamped with such a string
    sits in no model stratum, and the ablation that stratifies on
    ``agent_model_id`` (PRD §5a) reads a pool that is heterogeneous in an
    uncontrolled variable.

    Raised at construction and at the store seam, in both directions: a caller
    offering an alias is refused before anything is written, and a stored value
    that is not a triple is refused rather than reported as a pin.
    """


class ModelPinConflictError(ModelPinError):
    """The node already records a different authoring model.

    A node's author is a fact about the past, not a mutable field: the value is
    the axis §14.1's mitigation 3 stratifies the M3 paired comparison on, so
    overwriting it would quietly move every score the node carries into another
    stratum while leaving the scores themselves untouched.  The conflict is
    refused, and the refusal names both triples so an operator can see which
    two runs are claiming one node.

    Re-stamping a node with the *same* triple is not a conflict — it is the
    idempotent retry every store in this workspace answers (architecture §14
    demands retry-safe writes of the workers this runs on), and it is answered
    rather than refused.
    """


class NodeNotRecordedError(ModelPinError):
    """There is no ``node`` row for the id a pin was asked about.

    A pin is a column *on a node*, so stamping one without a node would mean
    writing a row this feature does not own — the ``node`` table is feature
    97's DDL and its rows are the discovery tree's.  Refused, and distinct
    from :class:`ModelPinConflictError`: "nothing is there to stamp" and "what
    is there says something else" are different problems with different
    repairs, and a caller that cannot tell them apart cannot report which one
    it met.
    """


class PinColumnError(ModelPinError):
    """The tree store has no ``agent_model_id`` column to write.

    The one failure whose repair is an operation rather than a value.  The
    column, the trio it sits in and the ``NOT NULL`` it carries belong to the
    core migration ``0115_agent_model_trio`` (feature 100); a database this
    process is pointed at that has not reached that revision has no column for
    a pin to live in, and no amount of correct pinning can supply one.  The
    refusal names the revision for that reason.

    Also raised when the ``node`` table itself is absent, since a column
    cannot exist on a table that does not: the two are one deployment gap seen
    at two depths, and the repair is the same migration chain.
    """
