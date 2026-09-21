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

Feature 204's three classes, and why they join this taxonomy rather than one
--------------------------------------------------------------------------------

app_spec.xml feature 204 — *"System persists ``agent_ckpt_hash`` for
self-hosted weights plus ``agent_sampling`` recording temperature, top_p,
thinking and seed"* — is the other half of the same record: feature 203 pins
*which model*, feature 204 pins *which weights* and *which dice*, and all three
columns belong to one row of one migration (``0115_agent_model_trio``, feature
100) written through one store.  So the failures of feature 204's half are
failures of *pinning a node's authoring record*, which is exactly what
:class:`ModelPinError` already names — and they join this taxonomy under the
same base rather than minting a second one.

The alternative was tempting and is wrong.  A second base would give a caller
who wants *"did this node's authoring record get pinned?"* two ``except``
clauses to write and one more way to write only one of them; a caller who
catches :class:`ModelPinError` and would have caught a malformed sampling
record would silently stop catching it.  And a single class would be worse
still: *"the sampling record is not four settings"*, *"the checkpoint hash is
not a hash"* and *"the row already records different weights"* are three
different answers to three different questions, and folding them into one
would leave an operator to work out which they met from the message.

They are separate subclasses of :class:`ModelPinError` on the same grounds the
four above are: each answers a question a caller can act on — *is this value
well-formed?*, *does this row already say otherwise?* — and each is refused at
a seam that knows which it is.  Neither shares an ancestor with
:class:`providers.ProviderError`, for the reason the module docstring gives: a
sampling record that is not four settings is not a model call that failed.

Stdlib-only, like the rest of this tree.
"""

from __future__ import annotations

__all__ = [
    "AgentSamplingMalformedError",
    "CkptHashConflictError",
    "CkptHashMalformedError",
    "ModelPinConflictError",
    "ModelPinError",
    "NodeNotRecordedError",
    "NodeProvenanceError",
    "PinColumnError",
    "RollingAliasError",
    "SamplingConflictError",
]


class ModelPinError(Exception):
    """Base of the authoring-record taxonomy — a node's authoring record could not be pinned.

    One base class so a caller can catch every failure of the pinning sentence
    with a single ``except``, the way :class:`providers.ProviderError` gives
    the *call* seam one handle.  The two bases are deliberately unrelated; see
    the module docstring.  The subclasses split by which question the refusal
    is answering — *is this value a triple?*, *is this sampling record four
    settings?*, *is this checkpoint hash a hash?*, *does this node already
    record a different one?*, *is there a node at all?*, *does the column
    exist?* — never by which line of code failed.

    The first three are feature 203's and the next three feature 204's, and the
    split is by *column* rather than by feature: the trio ``0115`` adds is one
    authoring record (which model, which weights, which dice) written through
    one store, and a caller asking whether it could be pinned is asking one
    question about one row.  A second base for the other two columns would make
    that question two ``except`` clauses and one more way to write only one of
    them.
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
    """The tree store has no authoring-record column to write.

    The one failure whose repair is an operation rather than a value.  The
    columns, the trio they sit in and the ``NOT NULL`` some of them carry
    belong to the core migration ``0115_agent_model_trio`` (feature 100); a
    database this process is pointed at that has not reached that revision has
    no column for a pin to live in, and no amount of correct pinning can
    supply one.  The refusal names the revision for that reason.

    All three of ``0115``'s columns are one gap.  ``agent_model_id`` is
    feature 203's, ``agent_ckpt_hash`` and ``agent_sampling`` are feature
    204's, and a database that has reached ``0115`` has all three — so a
    store that needed the second or third and found it missing is looking at a
    tree that has not reached this revision, which is the same report.  The
    refusal names *which* column it was after, because that is what tells an
    operator whether they met a deployment that is behind or a schema that was
    edited.

    Also raised when the ``node`` table itself is absent, since a column
    cannot exist on a table that does not: the two are one deployment gap seen
    at two depths, and the repair is the same migration chain.
    """


class NodeProvenanceError(ModelPinError):
    """The node's row records no authoring model, so its weights cannot be pinned.

    The row half of feature 338's merge refusal — *"when a node record carries
    no ``agent_model_id`` value"* — reached from the write side.  ``0115``
    declares ``agent_model_id TEXT NOT NULL`` with no default and calls that
    refusal correct, because *"a node with no model string is a node the
    stratification cannot place"*.  Feature 203 then names the one state the
    constraint could not cover: a populated table whose column was added
    without it, where *"the repair is a backfill, not a spell"*.

    So this is the state a backfill exists for, met by a caller who is supplying
    the *other* two columns: the row has an ``agent_sampling`` and an
    ``agent_ckpt_hash`` slot waiting and no author, and writing the weights
    first would produce a row that says which dice were thrown and which weights
    served, without saying which model was asked.  That row is a node the
    stratification cannot place **and** a node that looks placeable, because
    two of the three provenance columns are filled — which is worse than the
    bare NULL ``0115`` refuses, since nothing about the row announces what is
    missing.

    Distinct from :class:`NodeNotRecordedError`: *"there is no node here"* and
    *"there is a node here and it records no author"* are different problems
    with different repairs — the first wants a node written, the second wants
    feature 203's backfill run, and the caller that conflates them will go and
    look for a row that is already there.
    """


class AgentSamplingMalformedError(ModelPinError):
    """A node's ``agent_sampling`` is not the four settings feature 204 records.

    Feature 204's own list — *"recording temperature, top_p, thinking and
    seed"* — is the contract, and it is a *total* record rather than a partial
    one.  ``0115``'s docstring gives the reason the column is ``NOT NULL``:
    *"the sampling parameters are known at authoring time even when they are
    defaults: there is no node whose dice are unknown, only unrecorded ones."*
    A two-key record that a reader accepts as "the sampling" is therefore not
    a smaller answer but a wrong one: it says *these two settings decided this
    output* about a generation four settings decided.

    Raised for a missing key that would have meant something other than its
    default, for a value outside the range its knob exposes, for a
    non-finite or non-numeric number, for a ``bool`` where a number belongs
    (and a number where the flag belongs), and for stored text that is not a
    JSON object.  A missing key whose only possible value is the default *is*
    accepted and filled — see :mod:`providers._sampling` for why that is a
    completion of the caller's meaning rather than a guess at it.

    Distinct from :class:`RollingAliasError` although both refuse a value
    that would land in the same row: the two name different columns and
    different repairs, and an operator told "not a triple" about a sampling
    record would go and look at the wrong field.
    """


class CkptHashMalformedError(ModelPinError):
    """A supplied ``agent_ckpt_hash`` is not a sha256 hex digest.

    ``agent_ckpt_hash`` is ``CHAR(64)`` and §14.1's mitigation 1 is the reason
    it exists: *"Self-host open weights for the campaigns that feed M3.
    MIT-licensed checkpoints with FP8 quants and published vLLM configs make
    ``agent_ckpt_hash`` a real hash, not a promise."*  A value that is not the
    digest of the weights is a promise again, and a *truncated* one is worse
    than an absent one: it would compare unequal to the same checkpoint hashed
    properly and so read as a second, different set of weights.

    Refused with the same shape :func:`artifacts.canonical_code_hash` refuses
    ``code_hash`` with — 64 hex characters, case folded — and, like it, it
    refuses a ``sha256:``-prefixed reference by name: the prefixed spelling is
    the argument an image reference carries its digest in, not the digest
    itself, and a column that held one would hold a value no comparison
    against another node's hash could ever equal.

    Distinct from :class:`CkptHashConflictError`: *"this is not a hash"* and
    *"this row already records different weights"* are different problems with
    different repairs, and both are distinct from :class:`RollingAliasError`
    for the reason :class:`AgentSamplingMalformedError` gives.
    """


class CkptHashConflictError(ModelPinError):
    """The node's row already records different weights.

    Feature 204's half of :class:`ModelPinConflictError`'s rule, and refused on
    the same grounds: a node's weights are history, and ``agent_ckpt_hash`` is
    the column more than one M3 campaign reads as *"these nodes were generated
    by the same weights and may be compared"*.  Overwriting it would move
    every score the node carries into another weight stratum while leaving the
    scores themselves untouched — the same silent reclassification
    ``agent_model_id`` is defended against, arriving through the column the
    triple cannot see.

    **The case that makes it load-bearing is the rollback.**  A node recorded
    as self-hosted, with a checkpoint hash, is a node whose weights can be
    named exactly.  A later call re-stamping it as hosted-API weights — the
    ordinary way a re-run "records" a node it has already recorded, carrying
    no hash because the deployment is no longer self-hosting — would not
    record *less*: it would assert that this node's weights are a provider's
    to change, which is the heterogeneity §14.1's mitigation 3 exists to make
    visible.  Two nodes that were generated by one checkpoint would then read
    as two weights, and the comparison between them would be drawn from a
    pool that is not the pool it claims to be.

    Re-recording the *same* weights is not a conflict: it is the idempotent
    retry every store in this workspace answers, including the hosted-API case
    re-recorded as hosted-API.
    """


class SamplingConflictError(ModelPinError):
    """The node's row already records different sampling settings.

    The third column of the same rule.  A node's sampling is the *dice* that
    produced it, and it is what makes replay a claim rather than a hope —
    ``0115``: *"a replay that re-issues the authoring call without these four
    cannot reproduce the node, and determinism under replay is the property
    §14 demands of every recorded decision."*  Re-stamping a row with
    different settings would leave every stored score reproducible only by the
    settings that are no longer recorded there, which turns the replay
    guarantee into a value that *looks* recorded.

    The one that catches people: ``temperature`` and ``top_p`` are the
    knobs a deployment retunes most often, so a re-run that reuses a node id
    while a config change moved a default lands here.  That is the intended
    refusal — the node's score is a fact about one draw, and the draw that
    produced it is the one the row must keep.

    Distinct from :class:`AgentSamplingMalformedError` for the reason
    :class:`CkptHashConflictError` is distinct from
    :class:`CkptHashMalformedError`: a malformed value can be fixed by
    resending it, and a disagreeing one cannot.
    """
