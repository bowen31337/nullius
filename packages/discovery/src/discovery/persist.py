"""Every attempt into the tree, with its artifact — feature 240.

app_spec.xml, "Discovery Orchestrator & Campaigns", feature 240: *System
persists every attempt into the node table together with its full
artifact, including failures.*  docs/alpha-engine-prd.md §5 states the
same sentence as loop 1's last bullet — *"Every attempt is logged to the
tree with its full artifact"* — and docs/nullius-tech-architecture.md
§6.1 puts it at the end of the pipeline it belongs to: step 12,
``persist  artifact → ART, scalars → TREE``, which ``0117``'s docstring
compresses into the column it is about, *"a node with no artifact URI is
a node whose numbers cannot be re-derived"*.

**Where this module sits, and what the three before it handed it.**  The
category's loop is a chain and this is its last link: feature 232 plans
the campaign (the row every node hangs off), feature 238 dispatches the
selected batch across ``W`` slots and answers each attempt the moment its
slot finishes, feature 239 expands one selected node into exactly one
:class:`~discovery.expansion.RefinedSignal`, and feature 244 re-runs the
attempts §14's reclamation took away.  Every one of those modules names
this one as its consumer in as many words — 238's *"feature 240
persists* every *attempt 'including failures'"*, 239's *":meth:`RefinedSignal.row`
is the hand-off … ``artifact_uri`` is feature 240's write"*, 244's *"the
record feature 240 persists is attempt by attempt"* — and what they hand
over is deliberately incomplete: 239's ``row()`` carries the five
structural columns plus ``code_hash`` and ``stated_mechanism`` and stops,
because the provenance, authoring-model and metrics triples are *"the
evaluator's and the attempt's, not the signal's"*.  This module is where
those meet the tree.

**"Every attempt" is the feature's subject, and the whole design of the
call hangs on taking it literally.**  The system's discipline, stated in
four modules of this member, is *a failed run is a value*: 238 captures
a worker's exception on :attr:`~discovery.workers.WorkerResult.error`
rather than letting it kill the batch, 244 turns an interruption into a
:class:`~discovery.errors.WorkerInterrupted` marker, and §6.1 step 11
debits a node *because a failed evaluation still consumed a hypothesis*.
The consequence for this module is the one clause the feature's sentence
turns on: ``ok`` is **not** a precondition of being logged.  A
:class:`Attempt` whose ``fail_class`` is ``timeout``, ``error`` or
``tripwire_fail`` is written by exactly the same call, into exactly the
same table, with exactly the same artifact directory as one that
succeeded — and a log that recorded only successes would be a tree whose
missing rows mean nothing, because *absent* is already how the tree says
"this node was never expanded".  Keeping the two apart is the difference
between a campaign you can audit and one you cannot.

**What "including failures" cannot mean, and why the honest reading is
narrower than the words.**  ``0117`` declares ``code_hash CHAR(64) NOT
NULL`` and explains the constraint in its own docstring in terms of this
very feature: *"every node is its code: a node with no code hash is not
a node at all but an empty attempt"*.  So an attempt that failed
*before* a signal existed — the agent never answered, the expansion
refused because the tree did not hold the selected row — has no ``node``
row to be logged into, and no amount of wanting the sentence to say
otherwise will put one there: the column the migration declares refuses
it, and a fabricated ``code_hash`` would be worse than the omission,
because it would be a *fabricated identity* — the failure direction
``0117`` exists to make impossible, *"a node wearing identity that
belongs to a different one"*.  What is true is that such an attempt
*has* a node identity — :func:`attempt_node_id` derives it from the
parent, the identity law feature 239 pinned and feature 244 relies on —
and that this module names the refusal rather than dropping the attempt
silently.  Every attempt that carries a construction is persisted, failed
or not; an attempt that carries none is refused **by name, naming the
node**, so the campaign loop hears about it as a fact about one attempt
rather than as a hole in the tree.

**One node row per attempt, and a retry refreshes rather than
duplicates.**  §9.1's table is keyed ``id UUID PRIMARY KEY``, and the
identity §14's idempotence is built on is *derived*:
:func:`~discovery.expansion.refined_node_id` is a ``uuid5`` over the
parent, so a job re-run after a reclamation lands on the node its first
run named — which is exactly why *"ledger debits are idempotent by
``node_id``"* holds.  This module inherits that law rather than restating
it: an :class:`Attempt` is built from a :class:`~discovery.expansion.RefinedSignal`
and validated so that ``node_id`` *is* the derivation of ``parent_id``,
so two attempts of one job cannot be two rows.  A re-record is
therefore a **refresh** — the row is updated in place and the directory
is re-published wholesale — and :attr:`AttemptRecord.appended` answers
which of the two happened, the same signal
:meth:`evaluator.TreeNodeWriter.write_node` answers across its own seam.
What survives a retry is the *history*: :attr:`Attempt.attempts` and
:attr:`Attempt.interruptions` carry 244's ``interruptions + (result,)``
into the attempt's trace, so the artifact of a retried node records that
it took four runs, not one.  The row and the directory describe the
standing attempt; the trace describes what it cost.  That split is what
lets §9.1's key and §14's idempotence both be true at once.

**The artifact half, and which of §9.2's seven files are the
orchestrator's.**  §9.2 lists seven names, and they have two owners.
The measured five — ``signal_returns.parquet``, ``ic_series.parquet``,
``turnover_series.parquet``, ``decay_profile.json``,
``regime_attribution.json`` — are rendered from records the *evaluator*
measured (features 170-173, orchestrated by feature 85's step 12), and
this member has never seen those records.  The other two are feature
173's pair and they are the orchestrator's: ``code.py`` is the adopted
source text and ``exec_trace.json`` is the record of *the attempt* — the
run's own fingerprint, which is the one thing this module knows and the
evaluator does not.

:func:`AttemptLog.record` stages that pair and **publishes the node's
whole directory**, which is what ``commit`` means: the staged set
becomes the directory, replacing any prior version wholesale.  That
wholesale replacement is the property that makes one call the attempt's
complete artifact, and it is also the one way this feature could destroy
work it did not do — a retry of an *evaluated* node would publish a
complete artifact for the standing attempt and delete step 12's five
numbers in the process.  So the measured files are carried across that
replacement: the caller may stage them (the documented path), and any
that are neither staged nor supplied are **recovered from the published
directory as opaque bytes** before the commit.  Nothing here reads,
renders, encodes or re-derives a measured file: the Parquet boundary is
the artifacts member's, and a module of the orchestrator that grew a
``polars`` import would be paying composition cost for a number it never
measured.

**The directory store arrives as a seam, not as an import.**  The
workspace contract is that no member imports another, so the artifact
half is written through an injected :class:`ArtifactDirectory` — a
Protocol exposing four required methods
(:meth:`~ArtifactDirectory.node_directory`,
:meth:`~ArtifactDirectory.write`, :meth:`~ArtifactDirectory.commit`,
:meth:`~ArtifactDirectory.discard`) and two optional ones
(:meth:`~ArtifactDirectory.files`, :meth:`~ArtifactDirectory.read`,
which only the carry-forward described above uses), which
:class:`artifacts.ArtifactStore` satisfies **structurally, by name,
with no adapter**.  That is the same injection feature 85 makes for its
:class:`~evaluator.ArtifactWriter` and feature 239 makes for its agent,
and here it buys one further thing: the tree row's ``artifact_uri`` is
computed from the *same* ``node_directory`` the bytes were written
through, so the address the row carries and the directory the attempt
published are one path resolved once — the two halves cannot disagree
about where the node lives, which is the failure the ``NOT NULL`` on
that column exists to catch.

**The row is assembled from the table's own columns.**  The ``node``
table reaches a database through an assembled migration chain
(``0118`` creates it; ``0113``-``0117`` add indexes and columns), and
this module writes against whichever chain the deployment ran.  So the
INSERT names the **intersection** of the columns an attempt knows with
the columns the table actually has, read once per call from
``PRAGMA table_info``.  Two consequences, and both are deliberate.
``created_at`` is not written even where a table carries it: ``0118``'s
docstring states that the spec's ``TIMESTAMPTZ NOT NULL`` is absent from
the tree's DDL because *"feature 97's description names five columns and
``created_at`` is not among"* them, and a writer that supplied it would
be legislating a column three migrations short of it.  And the seven
metrics are not written either: they are step 12's, feature 85 assembles
them across its own seam, and an orchestrator that wrote them would be
overwriting measured numbers with its own silence.

**One column this feature adds, because it is the one nobody else
declares.**  §9.1 lists ``fail_class TEXT`` on ``node`` and *no
migration creates it* — ``0118``'s docstring argues the absence of its
neighbour ``created_at`` on precisely the ground that *"the honest form
is a feature that names it, not a sixth column"*.  Feature 240 names
it: the column is where the *"including failures"* clause is recorded,
and without it every failed attempt would be a row indistinguishable
from one that answered.  So :meth:`AttemptLog._connect` probes for it
and issues the ``ALTER TABLE ... ADD COLUMN`` when the tree lacks it —
the shipped convention for a store that owns a node column
(:mod:`nulloracle.plan` for feature 119's ``flip_depth``,
:mod:`tripwires.layout` for ``poisoned_at``) — nullable, because the
statement must be legal on a tree already holding roots.  Everything
else is left exactly as the chain left it.

**How each of the four words gets into the column, since one route is
not obvious.**  ``ok`` is the attempt that answered.  ``error`` is any
raised exception — *including* a raised :class:`TimeoutError`, because
§5.2's timeout is a control the sandbox reports as a *value* after
hard-killing the child, never as an exception, so one arriving raised is
a host-side fault wearing a familiar name (the rule
:func:`evaluator.failure_outcome` already states, pinned against it in
``packages/discovery/tests/test_cross_member.py``).  ``timeout`` and
``tripwire_fail`` therefore both reach the column by being **stated** —
by the caller holding the sandbox's recorded class or §C6's verdict —
which is why :func:`classify_failure` accepts a §9.1 word as well as an
exception, and why :meth:`Attempt.from_signal` takes ``fail_class``
beside ``error`` rather than deriving one from the other.

**Refusals, and they all fire before the first byte.**  This module's own
:class:`~discovery.errors.AttemptLogError` for everything about the
*attempt* — a ``fail_class`` outside §9.1's four, an attempt whose
identity is not its parent's derivation, a ``code_hash`` that is not
``sha256(code)``, an ``attempt`` ordinal above its own ``attempts``, a
provenance triple that is not a hash or an authoring record that is not
one, an error recorded on a successful attempt or a failure recorded
without one.  And for the two facts about the *deployment*: a database
holding no ``node`` table (named, the way feature 239 names it, rather
than surfacing SQLite's ``no such table``), and a tree that does not
hold the attempt's ``parent_id``.  Every one lands before a row is
written and before a byte is staged, so a refused attempt leaves the
database and the directory exactly as they were.

**No component, and the reason is feature 239's with a second face.**
:class:`AttemptLog` closes over state a deployment holds — a database URL
and an artifact directory — and it still composes nothing.  The first
face is 239's: the artifact directory is a *sibling member's* component,
and a builder takes no arguments, so a registered log would have to
invent one — which would be the tree store and the artifact store
disagreeing about where a node lives.  The second face is this feature's
own and it is the sharper one: a component is built on **every**
``create_app()``, and a log that resolved its tree at build time would
have to answer *which campaign's attempts does this writer hold?* —
a question with no answer, because the log holds every campaign's, and
a builder that picked one would be a store that silently wrote a
campaign's nodes into another's directory.  The member's registered
surface stays feature 232's single store, and the campaign loop reaches
this verb the only way the spec allows: by constructing it with the
tree it writes into and the store it publishes through.

**Stdlib only, and import-cheap.**  ``hashlib``, ``json``, ``os``,
``sqlite3`` and ``urllib.parse``, over this member's own values; no
third-party import at module scope, so the factory's scan — which
imports this package to fire its ``@register`` — pays nothing for the
log, and a composed application that never records an attempt never
opens a database or a directory.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote, unquote, urlparse

from .errors import AttemptLogError
from .expansion import RefinedSignal, refined_node_id

__all__ = [
    "ARTIFACT_URI_COLUMN",
    "ATTEMPT_DATABASE_URL_ENV",
    "FAIL_CLASSES",
    "FAIL_CLASS_COLUMN",
    "MEASURED_FILENAMES",
    "SOURCE_FILENAME",
    "TRACE_FILENAME",
    "ArtifactDirectory",
    "Attempt",
    "AttemptLog",
    "AttemptProvenance",
    "AttemptRecord",
    "attempt_node_id",
    "classify_failure",
    "record_attempts",
]

#: §9.1's failure vocabulary, verbatim — ``ok | timeout | error |
#: tripwire_fail`` — and the whole of what the ``fail_class`` column may
#: hold.  Restated from the architecture doc's own annotation rather than
#: imported, for the reason every restatement in this workspace exists:
#: the ledger member spells the same four for its ``outcome`` column
#: (§8's trial vocabulary), and a system that wrote ``failed`` in one
#: place and ``error`` in the other would have two names for one fact and
#: no way to count either.  ``packages/discovery/tests/test_cross_member.py``
#: pins the two spellings against each other.
#:
#: ``ok`` is a member of the set and not the absence of one: §9.1's
#: comment lists it first, and an attempt that answered is a *recorded
#: outcome*, not a row that happens to carry no failure.
FAIL_CLASSES: tuple[str, ...] = ("ok", "timeout", "error", "tripwire_fail")

#: The ``node`` column §9.1's vocabulary lands in.
FAIL_CLASS_COLUMN = "fail_class"

#: The ``node`` column holding the node's one artifact address — the
#: string :meth:`AttemptLog.record` derives from the directory it
#: published through, and the column feature 239's ``RefinedSignal.row``
#: deliberately omits because the write is this feature's.
ARTIFACT_URI_COLUMN = "artifact_uri"

#: §9.2's name for the executed signal source — the exact module text the
#: sandbox ran.  Restated from :data:`artifacts.SOURCE_FILENAME`, which is
#: the same string for the same layout.
SOURCE_FILENAME = "code.py"

#: §9.2's name for the execution trace — the attempt's own fingerprint.
#: Restated from :data:`artifacts.TRACE_FILENAME`.
TRACE_FILENAME = "exec_trace.json"

#: §9.2's five **measured** names — the files step 12 renders from
#: records this member never sees.  Restated as data because feature 240
#: is the call that publishes the node's *whole* directory, which means it
#: is the call that must not drop them: a ``commit`` replaces the
#: directory wholesale, so a refresh following a published evaluation
#: would silently delete every number the evaluation produced.  Nothing
#: here reads, renders or re-derives one of these — they travel as opaque
#: bytes between the two halves of the pipeline's step 12, which is the
#: only way an orchestrator can carry a Parquet file it cannot decode.
MEASURED_FILENAMES: tuple[str, ...] = (
    "signal_returns.parquet",
    "ic_series.parquet",
    "turnover_series.parquet",
    "decay_profile.json",
    "regime_attribution.json",
)

#: The environment variable naming the relational store — the one
#: spelling every store in this workspace uses, restated here so this
#: module states its own contract rather than importing a sibling's.
ATTEMPT_DATABASE_URL_ENV = "DATABASE_URL"

#: The read-only probe that answers *does this database hold a tree at
#: all?* — the ``sqlite_master`` idiom feature 232's ordering law and
#: feature 239's workspace read both use, restated rather than imported
#: because a private constant of a sibling module is not a promise.
_NODE_TABLE_EXISTS_SQL = (
    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?"
)

#: The read that answers *which columns does this tree actually have?*
#: — a ``PRAGMA`` over the live table, run once per write.  This is what
#: makes the INSERT a projection of the deployment's chain rather than of
#: this file's guess at it: ``0118`` creates five columns, ``0113``-
#: ``0117`` add indexes and ten more, and a writer that named all fifteen
#: unconditionally would be an ``OperationalError`` on every database the
#: column migrations have not reached.  The providers member's node
#: writer states the same rule for the same reason (a database where
#: ``0115`` has not run *"would be an ``OperationalError`` about this
#: fixture rather than about the store under test"*).
_TABLE_COLUMNS_SQL = "PRAGMA table_info(node)"

#: The one read that proves an attempt hangs off a real node.  §9.1
#: spells ``parent_id UUID REFERENCES node(id)`` and :meth:`AttemptLog._connect`
#: turns the foreign key on, so this probe is the *diagnosis* and the
#: constraint is the *enforcement* — the same pair the expansion's
#: workspace read makes, and the reason both exist is that SQLite's own
#: ``FOREIGN KEY constraint failed`` names no node.
_PARENT_EXISTS_SQL = "SELECT 1 FROM node WHERE id = ?"

#: The ``node``-table columns an attempt can fill, as data rather than as
#: a statement — so *"what does this feature write?"* is answerable by a
#: reader and a test without parsing SQL, the shape ``0113``'s
#: :data:`INDEX_COLUMNS` uses for its own list.  Nothing here is a metric
#: (those are step 12's, feature 85's) and ``created_at`` is absent on
#: purpose (see the module docstring).
_ATTEMPT_COLUMNS: tuple[str, ...] = (
    "id",
    "parent_id",
    "campaign_id",
    "theme_root",
    "depth",
    "code_hash",
    "stated_mechanism",
    ARTIFACT_URI_COLUMN,
    "evaluator_hash",
    "snapshot_hash",
    "cost_model_hash",
    "agent_model_id",
    "agent_ckpt_hash",
    "agent_sampling",
    FAIL_CLASS_COLUMN,
)

#: The columns that identify the row rather than describe it — the ones a
#: refresh must not rewrite.  They are already validated to equal the
#: stored row's (the identity is derived, so a second attempt of one job
#: cannot name a different parent), and leaving them out of the UPDATE is
#: what makes "a retry refreshes the standing attempt" literally true
#: rather than a promise about values that happen to match.
_IDENTITY_COLUMNS: tuple[str, ...] = ("id", "parent_id", "campaign_id", "theme_root", "depth")

_HEX_DIGITS = frozenset("0123456789abcdef")


# -- The vocabulary ----------------------------------------------------------------


def classify_failure(failure: Any) -> str:
    """Classify one attempt's failure as §9.1's ``fail_class`` — or ``ok``.

    The module's own copy of the classification the ledger member makes
    for its ``outcome`` column, because the two must agree and neither may
    import the other.  Three shapes are accepted, for the same reason
    :func:`evaluator.failure_outcome` accepts three: the value a caller
    holds depends on which layer observed the failure.

    1. **``None``** — the attempt answered.  ``ok``.
    2. **A §9.1 word.**  A caller that already knows the outcome — a
       tripwire verdict, §6.1's step 11, a driver that read the sandbox's
       own ``fail_class`` — states it, and a word outside
       :data:`FAIL_CLASSES` is refused rather than passed through: a
       document's vocabulary that drifted from the column's is a
       ``fail_class`` no reader could count.
    3. **An exception.**  Every one of them is ``error`` — *including*
       :class:`TimeoutError`.

    **Why a raised ``TimeoutError`` is ``error`` and not ``timeout``.**
    This is the one place where the obvious reading is wrong, and the
    sibling that already ruled on it is
    :func:`evaluator.failure_outcome`: *"Every raised failure is an
    ``'error'`` — the timeout distinction is the sandbox's recorded hard
    kill, and the sandbox never raises."*  §5.2's timeout is a **control**,
    not an accident: :meth:`evaluator._sandbox.SignalSandbox.run` hard-kills
    the child and returns its class as a *value* — *"a failed run is a
    value the pipeline records"* — so ``timeout`` reaches this function
    through shape 2, stated by the caller that watched the kill, and never
    through this shape.  Feature 163's own docstring draws the same line
    from the other side: a ``TimeoutError`` arriving *raised* "has a
    host-side failure, not this law's subject".

    So a raised ``TimeoutError`` is a host-side fault wearing a familiar
    name, and classifying it as ``timeout`` would do two wrong things at
    once: it would record a host fault as §5.2's budget being enforced
    (inverting the blame), and it would make one exception name mean two
    different outcomes in two members that share one vocabulary.  The
    timeout *class* is not lost by this — the caller that holds the kill
    states it and gets it verbatim — and the entry that a genuine kill
    produces is still ``timeout`` in both the row and the trace.

    Everything else — an ``oom``, a ``crash``, a ``violation``, a payload
    refusal, an agent's own exception, and
    :class:`~discovery.errors.WorkerInterrupted` — is ``error`` too.

    **Why an interruption is ``error`` and not a word of its own.**  §14's
    reclamation is a scheduled event rather than a fault, and it is
    tempting to give it a fifth word.  It gets none, because
    :data:`FAIL_CLASSES` is §9.1's closed set and a member that widened
    it would be legislating a vocabulary the schema, the ledger and every
    reader of a campaign's failure histogram share.  What distinguishes a
    reclaim is not the *word* but the **marker** — feature 244's
    :class:`~discovery.errors.WorkerInterrupted` — and where it is
    recorded is the attempt's trace, which carries ``error_class``
    verbatim beside the class.  So the column answers *how did this
    attempt end?* (``error``) and the trace answers *to what?*
    (``WorkerInterrupted``), and neither answer is guessed at.

    A value that is none of the three is refused — a caller that passed,
    say, a ``SandboxResult`` object would otherwise get ``ok`` for a run
    that failed, which is the one wrong answer with no symptom.
    """
    if failure is None:
        return "ok"
    if isinstance(failure, str):
        text = failure.strip()
        if text in FAIL_CLASSES:
            return text
        raise AttemptLogError(
            f"{failure!r} is not a failure class §9.1 records "
            f"({', '.join(repr(word) for word in FAIL_CLASSES)}); the "
            "vocabulary is the architecture doc's own annotation on the "
            f"{FAIL_CLASS_COLUMN} column, shared with the trial ledger's "
            "``outcome``, and a drifted word would be a failure no reader "
            "of this campaign could count (feature 240)"
        )
    # No ``TimeoutError`` branch, and its absence is the decision rather
    # than an oversight — see the docstring: the sandbox records its kills
    # as values and never raises, so a *raised* timeout is a host fault and
    # the class belongs to the caller that watched the kill, not here.
    # ``test_cross_member.py`` pins this against ``failure_outcome``.
    if isinstance(failure, BaseException):
        return "error"
    raise AttemptLogError(
        f"classify_failure classifies an exception, a §9.1 failure class "
        f"or None — got {type(failure).__name__} {failure!r}. An "
        "unrecognised value must not be read as ``ok``: a run that failed "
        "and was recorded as having answered is the one wrong answer with "
        "no symptom (feature 240)"
    )


def attempt_node_id(parent_id: Any) -> str:
    """The node id an attempt on ``parent_id`` will land on — derived.

    :func:`discovery.expansion.refined_node_id` under this module's own
    name, and it is a *re-export in the honest sense* rather than a second
    derivation: the identity law is feature 239's and there is exactly one
    implementation of it in this member.  What this spelling buys is the
    caller that wants the *address* without holding a signal — a campaign
    loop about to log an attempt it is still assembling, a test asserting
    that a failure and its retry name one node.

    Exported because the derivation is the fact §14's idempotence rests
    on — *"ledger debits are idempotent by ``node_id``"* — and a caller
    that wants to state that property must be able to name the id without
    reaching into a private helper.
    """
    return refined_node_id(parent_id)


# -- The deployment's record of the world the attempt ran in -----------------------


def _validated_hash(value: Any, field_name: str, node: str | None) -> str:
    """Return ``value`` as §9.1's 64-hex-character digest, or refuse it.

    ``CHAR(64)`` is the spec's own type on all three provenance columns
    and on ``code_hash``, and every writer in this workspace fills it with
    ``hashlib.sha256(...).hexdigest()``.  Case is *folded* rather than
    refused — ``"AB…"`` and ``"ab…"`` are one digest written two ways, and
    two spellings of one hash is exactly the drift a provenance column
    exists to prevent.  Everything else is refused by name: a truncated
    hash, a ``sha256:``-prefixed image reference (the shape §12's
    digest-pinned container vocabulary deals in, and the one the ledger's
    own validator refuses for the same reason — *a term that names
    nothing is not made acceptable by arriving from somewhere else*), a
    non-hex token, a non-string.
    """
    where = f" for node {node!r}" if node is not None else ""
    if not isinstance(value, str):
        raise AttemptLogError(
            f"a node's {field_name} must be a string — §9.1 types it "
            f"CHAR(64) — got {type(value).__name__} {value!r}{where}; the "
            "provenance triple pins everything except the thing that "
            "wrote the code, and a value that is not a digest pins "
            "nothing (feature 240)"
        )
    text = value.strip().casefold()
    if len(text) != 64 or any(char not in _HEX_DIGITS for char in text):
        raise AttemptLogError(
            f"a node's {field_name} must be 64 hexadecimal characters — "
            f"got {value!r} (length {len(text)}){where}; §9.1 types the "
            "column CHAR(64) and the system computes it as "
            "sha256(...).hexdigest(), so a truncated hash or a "
            "``sha256:``-prefixed image reference names something no "
            "other writer's value could ever equal — and a provenance "
            "nothing can be compared against is a score with no "
            "provenance (feature 240)"
        )
    return text


def _validated_text(value: Any, field_name: str, node: str | None) -> str:
    """Return ``value`` as non-empty text, or refuse it by name."""
    where = f" for node {node!r}" if node is not None else ""
    if not isinstance(value, str) or not value.strip():
        raise AttemptLogError(
            f"a node's {field_name} must be non-empty text — got "
            f"{type(value).__name__} {value!r}{where}; §9.1 types the "
            "column NOT NULL, so an attempt that cannot state this fact "
            "is an attempt the tree cannot hold (feature 240)"
        )
    return value.strip()


def _validated_sampling(value: Any, node: str | None) -> str:
    """Return ``agent_sampling`` as the canonical JSON text the column holds.

    §9.1 types the column ``JSONB NOT NULL`` and describes it as
    ``{temperature, top_p, thinking, seed}`` — the dice one attempt was
    authored under.  This module stores it as **canonical JSON text**:
    a mapping is rendered with ``sort_keys=True`` and the compact
    separators (the spelling every canonical-JSON writer in this
    workspace uses, so two equal samplings stage equal bytes and a
    comparison is over content rather than key order), and text is
    accepted only if it parses to an object.  Text that is not a JSON
    object is refused rather than stored: the column's whole purpose is
    that a later reader — feature 100's *"so a pool can be stratified by
    authoring model"* — can parse it back, and a string that only looks
    like JSON is a sampling nothing can read.  Non-finite floats are
    refused with it (``allow_nan=False``): ``nan`` is not JSON, and
    a sampling a parser must round-trip cannot carry it.
    """
    where = f" for node {node!r}" if node is not None else ""
    if isinstance(value, str):
        try:
            body: Any = json.loads(value)
        except json.JSONDecodeError as exc:
            raise AttemptLogError(
                f"a node's agent_sampling must be the JSON object §9.1 "
                f"types the column for — got text that does not parse: "
                f"{exc}{where}; the sampling records the dice the attempt "
                "was authored under, and text no reader can parse is a "
                "record of nothing (feature 240)"
            ) from exc
    else:
        # Mappings, lists, scalars and everything else fall through to the
        # object check below rather than being refused here, so the one
        # message a caller sees is the one about the *shape the column
        # holds* — a list is refused as "not a JSON object", which is a
        # more useful sentence than "not a mapping", because a caller who
        # passed a list was thinking of the four dice and not of JSON.
        body = value
    if not isinstance(body, dict):
        raise AttemptLogError(
            f"a node's agent_sampling must be a JSON object — got "
            f"{type(body).__name__} {body!r}{where}; §9.1 types the "
            "column NOT NULL and describes it as "
            "{temperature, top_p, thinking, seed}, so a scalar or a list "
            "is not an authoring record any later reader could resolve "
            "(feature 240)"
        )
    try:
        return json.dumps(
            body, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    except (TypeError, ValueError) as exc:
        raise AttemptLogError(
            f"a node's agent_sampling must be renderable as JSON — "
            f"{exc}{where}; the column is what a later stratification "
            "reads back, and a value no JSON renderer may emit is not a "
            "fact about the attempt that can be stored beside it "
            "(feature 240)"
        ) from exc


@dataclass(frozen=True)
class AttemptProvenance:
    """The deployment's record of the world one attempt ran in.

    The six ``node`` columns this feature writes that the *orchestrator*
    cannot measure, and the reason they arrive as an argument rather than
    being derived here.  §9.1's provenance triple pins everything about a
    score except the thing that wrote the code — ``evaluator_hash`` is
    the digest-pinned container (§12: *"Docker, digest-pinned, because
    ``evaluator_hash`` requires digests not tags"*), ``snapshot_hash``
    the sealed lake the attempt read, ``cost_model_hash`` the fee schedule
    that priced it — and the authoring trio records *who wrote the code
    and under what dice* (§14.1's model, the checkpoint when the weights
    are self-hosted, and §9.1's ``agent_sampling`` object).  None of the
    six is a fact about the work this module does: they are facts about
    the **deployment** the work ran in, which means the caller that ran
    the attempt is the only one that holds them, and a module that
    defaulted any of them would be fabricating provenance — the failure
    direction ``0117`` names when it refuses a fabricated ``DEFAULT`` for
    its own ``NOT NULL`` pair: *"a node wearing identity that belongs to a
    different one"*.

    Frozen and validated in :meth:`__post_init__`, the discipline
    :class:`~discovery.campaign.CampaignRecord` and
    :class:`~discovery.expansion.RefinedSignal` both state; the
    validation runs there rather than at the store because
    ``dataclasses.replace`` and unpickling both rebuild instances past a
    factory's nose, and a provenance value that exists is one the
    feature's sentence could have produced.

    ``agent_ckpt_hash`` is the one nullable member, and its ``None`` is a
    positive fact rather than a missing one: ``0115`` makes it the
    trios' single nullable column, and §9.1's annotation on it —
    ``non-null for self-hosted weights`` — is what the null records.  A
    hosted API is a deployment whose weights live somewhere this system
    never hashed.
    """

    #: The digest-pinned evaluator container that produced the attempt.
    evaluator_hash: str
    #: The sealed snapshot the attempt was measured in.
    snapshot_hash: str
    #: The fee schedule that priced the attempt.
    cost_model_hash: str
    #: The authoring model, as §14.1 spells it — ``provider/model/version``.
    agent_model_id: str
    #: The dice the attempt was authored under, as a mapping or its JSON text.
    agent_sampling: Any = field(default_factory=lambda: {"seed": 0})
    #: The weights digest — ``None`` for a hosted API, per §9.1's annotation.
    agent_ckpt_hash: str | None = None

    def __post_init__(self) -> None:
        # ``object.__setattr__`` because the dataclass is frozen: the
        # canonicalization below is normalization, not mutation of the
        # caller's values, and it is the only write this object takes.
        object.__setattr__(
            self,
            "evaluator_hash",
            _validated_hash(self.evaluator_hash, "evaluator_hash", None),
        )
        object.__setattr__(
            self,
            "snapshot_hash",
            _validated_hash(self.snapshot_hash, "snapshot_hash", None),
        )
        object.__setattr__(
            self,
            "cost_model_hash",
            _validated_hash(self.cost_model_hash, "cost_model_hash", None),
        )
        object.__setattr__(
            self,
            "agent_model_id",
            _validated_text(self.agent_model_id, "agent_model_id", None),
        )
        object.__setattr__(
            self, "agent_sampling", _validated_sampling(self.agent_sampling, None)
        )
        if self.agent_ckpt_hash is not None:
            object.__setattr__(
                self,
                "agent_ckpt_hash",
                _validated_hash(self.agent_ckpt_hash, "agent_ckpt_hash", None),
            )


# -- The attempt -------------------------------------------------------------------


@dataclass(frozen=True)
class Attempt:
    """One attempt, as the tree and the artifact store will hold it.

    The atom this module persists: the signal half feature 239 handed
    over — the derived identity, the parentage, the adopted source and its
    hash, the agent's rationale — the provenance half the deployment's
    caller supplied, the failure half §6.1's step 11 recorded, and the
    history feature 244's retry accumulated.

    **Frozen and validated in :meth:`__post_init__`, and the validation
    pins the identity law inside the value** — the discipline
    :class:`~discovery.retry.RetriedResult` states for its own law and
    :class:`~discovery.expansion.RefinedSignal` repeats.  ``node_id``
    must be :func:`attempt_node_id` of ``parent_id``; ``depth`` must be
    at least one (a refined attempt is never a root — the tree's roots
    are planted with a fresh theme, feature 241); ``code_hash`` must be
    ``sha256(code)``; ``fail_class`` must be one of §9.1's four.  A value
    that fails any of these is not an attempt this system made, and
    neither ``dataclasses.replace`` nor unpickling can build one past the
    check.  The law being *inside the value* is what makes the two
    refusals this feature exists to prevent unreachable rather than
    merely unlikely: two attempts of one job cannot become two rows
    (§14's idempotence), and a node cannot wear a code hash belonging to
    source it did not run (§9.1's identity).

    **The failure half is either fully present or fully absent.**  An
    attempt whose ``fail_class`` is ``ok`` carries no ``error_class`` and
    no ``error_message``; one that failed carries at least the class, so
    the trace can answer *to what?* and not merely *that*.  A failure
    recorded with no evidence of what failed would be a hole in the
    record exactly where the feature's *"including failures"* clause
    points, and a success carrying an error would be two contradictory
    answers to one question.  Both are refused.

    **``attempts`` and ``attempt`` are feature 244's ledger, carried into
    the trace.**  ``attempts`` is the job's total run count — 244's
    ``len(interruptions) + 1`` — and ``attempt`` is which of them this
    record stands for, always the last.  They are validated together
    (``attempt <= attempts``, both genuine positive integers, ``bool``
    refused) because they are two halves of one fact, and a value that
    claimed a first attempt out of four would describe a history the
    interruptions beside it contradict.
    """

    #: The parent whose workspace was resumed — the ``v`` of ``CONTINUE(v)``.
    parent_id: str
    #: The campaign the attempt belongs to, inherited from the parent.
    campaign_id: str
    #: The theme the parent's root was planted in, inherited unchanged.
    theme_root: str
    #: The attempt's depth: the parent's, plus one.  At least one.
    depth: int
    #: The adopted source text — the exact module §5.2's sandbox executes.
    code: str
    #: ``sha256(code)`` — §9.1's ``code_hash CHAR(64)``.
    code_hash: str
    #: The agent's stated economic rationale, or ``None`` when it stated
    #: none.  ``0117``'s honest NULL: dedup and human review only, never
    #: scored.
    stated_mechanism: str | None
    #: The deployment's record of the world the attempt ran in.
    provenance: AttemptProvenance
    #: §9.1's ``fail_class`` — one of :data:`FAIL_CLASSES`.
    fail_class: str = "ok"
    #: The exception class an attempt failed to, as text, or ``None``.
    error_class: str | None = None
    #: The exception's own account of what happened, or ``None``.
    error_message: str | None = None
    #: Which run of the job this record stands for — 244's ordinal.
    attempt: int = 1
    #: How many runs the job has had in total — 244's
    #: ``len(interruptions) + 1``.
    attempts: int = 1
    #: Every earlier run that was reclaimed, oldest first, as
    #: ``{"slot", "error_class", "error_message"}`` mappings — 244's
    #: ``interruptions``, carried into the trace.
    interruptions: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        # ``object.__setattr__`` because the dataclass is frozen.
        parent = _canonical_node_id(self.parent_id)
        object.__setattr__(self, "parent_id", parent)
        object.__setattr__(
            self,
            "campaign_id",
            _canonical_node_id(self.campaign_id, field_name="campaign_id"),
        )
        node = attempt_node_id(parent)
        object.__setattr__(
            self, "theme_root", _validated_text(self.theme_root, "theme_root", node)
        )
        if isinstance(self.depth, bool) or not isinstance(self.depth, int):
            raise AttemptLogError(
                f"attempt {node} carries depth {self.depth!r} "
                f"({type(self.depth).__name__}); a depth is the position "
                "the attempt occupies one below the parent it resumes, "
                "and a row placed at a non-count depth is a node the tree "
                "cannot walk (feature 240)"
            )
        if self.depth < 1:
            raise AttemptLogError(
                f"attempt {node} carries depth {self.depth!r}; a refined "
                "attempt is never a root — the tree's roots are planted "
                "with a fresh research theme (feature 241) and only their "
                "refinements are CONTINUE(v) — so a logged attempt at "
                "depth 0 would be a root nobody assigned a theme to "
                "(feature 240)"
            )
        if not isinstance(self.code, str) or not self.code.strip():
            raise AttemptLogError(
                f"attempt {node} carries no source ({self.code!r}, "
                f"{type(self.code).__name__}); §9.1 declares ``code_hash "
                "CHAR(64) NOT NULL`` because every node *is* its code, and "
                "an attempt with no source is an empty attempt the tree "
                "cannot hold — 0117's own words: 'a node with no code "
                "hash is not a node at all' (feature 240)"
            )
        expected = hashlib.sha256(self.code.encode("utf-8")).hexdigest()
        if self.code_hash != expected:
            raise AttemptLogError(
                f"attempt {node} carries code_hash {self.code_hash!r} "
                f"over code whose sha256 is {expected!r}; §9.1 persists "
                "the hash beside the node and the artifact directory "
                "holds the text, so a pair that disagrees identifies "
                "source no run could reproduce — and the node would wear "
                "an identity belonging to a different one (feature 240)"
            )
        if self.stated_mechanism is not None and (
            not isinstance(self.stated_mechanism, str)
            or not self.stated_mechanism.strip()
        ):
            raise AttemptLogError(
                f"attempt {node} carries stated_mechanism "
                f"{self.stated_mechanism!r} "
                f"({type(self.stated_mechanism).__name__}); the field is "
                "the agent's own rationale for dedup and human review, so "
                "the honest absent value is None and a blank or non-text "
                "one states nothing while claiming to (feature 240)"
            )
        if not isinstance(self.provenance, AttemptProvenance):
            raise AttemptLogError(
                f"attempt {node} carries provenance "
                f"{self.provenance!r} ({type(self.provenance).__name__}); "
                "the provenance, authoring-model and cost-model triples "
                "are the deployment's record of the world the attempt ran "
                "in, and a row written without them would be a node whose "
                "numbers cannot be attributed to anything (feature 240)"
            )
        if not isinstance(self.fail_class, str) or self.fail_class not in FAIL_CLASSES:
            raise AttemptLogError(
                f"attempt {node} carries fail_class {self.fail_class!r}; "
                "§9.1's column holds "
                f"{', '.join(repr(word) for word in FAIL_CLASSES)} and "
                "nothing else, and a drifted word would be a failure no "
                "reader of this campaign could count (feature 240)"
            )
        failed = self.fail_class != "ok"
        if failed and not (
            isinstance(self.error_class, str) and self.error_class.strip()
        ):
            raise AttemptLogError(
                f"attempt {node} records fail_class {self.fail_class!r} "
                "and no error_class; the feature's sentence persists "
                "failures, and a failure logged with no evidence of what "
                "failed is a hole in exactly the record 'including "
                "failures' points at — name the exception type, or the "
                "class that stands for it (feature 240)"
            )
        if not failed and (self.error_class is not None or self.error_message is not None):
            raise AttemptLogError(
                f"attempt {node} records fail_class 'ok' beside "
                f"error_class {self.error_class!r}; an attempt that "
                "answered carries no failure, and a row that states both "
                "is two contradictory answers to one question (feature 240)"
            )
        if self.error_class is not None and not isinstance(self.error_class, str):
            raise AttemptLogError(
                f"attempt {node} carries error_class {self.error_class!r} "
                f"({type(self.error_class).__name__}); the trace records "
                "the exception's type by name so a failure histogram can "
                "be counted from the artifact (feature 240)"
            )
        for value, name in ((self.attempt, "attempt"), (self.attempts, "attempts")):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise AttemptLogError(
                    f"attempt {node} carries {name}={value!r} "
                    f"({type(value).__name__}); feature 244's ordinal is a "
                    "genuine positive integer — every run of a job is the "
                    "first, the second or later — and ``bool`` is refused "
                    "because it is not a count (feature 240)"
                )
        if self.attempt > self.attempts:
            raise AttemptLogError(
                f"attempt {node} is run {self.attempt} of "
                f"{self.attempts}; a job's runs are numbered up to its "
                "total, and a record claiming to be the fourth run of "
                "three describes a history the interruptions beside it "
                "contradict (feature 244's ``len(interruptions) + 1``, "
                "persisted by feature 240)"
            )
        if self.attempts != len(self.interruptions) + 1:
            raise AttemptLogError(
                f"attempt {node} is the {self.attempt}th run of "
                f"{self.attempts} and carries {len(self.interruptions)} "
                "interruptions; feature 244 states the relation exactly — "
                "``attempts`` is ``len(interruptions) + 1``, because every "
                "reclaimed run was followed by another — and a record that "
                "breaks it is a cost history nothing can reconcile "
                "(feature 240)"
            )
        object.__setattr__(self, "interruptions", tuple(self.interruptions))

    # -- The derived identity -------------------------------------------------

    @property
    def node_id(self) -> str:
        """The attempt's node id — derived from the parent, never minted.

        Computed rather than stored, so the identity law cannot be
        violated by a field: :meth:`__post_init__` has already refused any
        ``parent_id`` whose derivation is not what the caller meant, and
        there is no second value here to fall out of step with it.  This
        is the id §14's *"ledger debits are idempotent by ``node_id``"*
        keys on and the id the row's primary key holds.
        """
        return attempt_node_id(self.parent_id)

    @property
    def ok(self) -> bool:
        """True when the attempt answered rather than failed.

        The split that is *not* a precondition of being logged: an attempt
        with ``ok`` false is written by the same call into the same table
        with the same artifact directory, and this property exists for the
        consumer that wants to count rather than to filter.
        """
        return self.fail_class == "ok"

    # -- The two halves as the store wants them --------------------------------

    @classmethod
    def from_signal(
        cls,
        signal: RefinedSignal,
        provenance: AttemptProvenance,
        *,
        fail_class: Any = "ok",
        error: BaseException | None = None,
        attempt: int = 1,
        interruptions: Iterable[Mapping[str, Any]] = (),
    ) -> Attempt:
        """Build an attempt from feature 239's hand-off, and what became of it.

        The one shape a campaign loop actually has in hand: the
        :class:`~discovery.expansion.RefinedSignal` the worker of record
        answered, plus — when the attempt failed — the exception §6.1's
        step 11 charged it for.  The five derived facts come off the
        signal (:meth:`~discovery.expansion.RefinedSignal.row`'s seven
        columns minus the one this feature writes), so nothing here
        re-derives an identity the expansion already pinned.

        ``fail_class`` defaults to ``"ok"`` and ``error`` to ``None``,
        which is the attempt that answered.  For an attempt that failed,
        **the class and the evidence travel together**, because
        :class:`Attempt` refuses one without the other: *"a failure logged
        with no evidence of what failed is a hole in exactly the record
        'including failures' points at"*.  So there are two shapes, not
        three:

        * A caller holding the exception passes ``error`` and lets
          :func:`classify_failure` name the class — the ``error`` route.
        * A caller that knows the class from a value — §5.2's
          :class:`~sandbox.timeout.TimeoutKill`, a §C6 tripwire verdict,
          §9.1's *tripwire_fail* — **still passes evidence**: ``error``
          holding whatever the value carried (§6.1's ``detail``, the
          tripwire's own exception), or a directly constructed
          :class:`Attempt` naming ``error_class``/``error_message`` as
          text.  This is the stated route, and it is the one a real
          timeout takes — the sandbox hard-kills and returns its class as
          a value, so there is no exception to hand over and the caller
          supplies the value's own detail instead.

        Passing **both** is therefore the ordinary case rather than the
        exception to it: a caller that knows the class and holds the
        evidence gets the class it stated and the evidence it holds,
        which is precisely the pair §6.1's step 11 and this feature's
        trace need between them.  Note what is *not* available: stating a
        class with nothing beside it, which the constructor refuses rather
        than recording a failure no reader can attribute.
        """
        interruptions = tuple(interruptions)
        if error is not None and fail_class == "ok":
            fail_class = classify_failure(error)
        return cls(
            parent_id=signal.parent_id,
            campaign_id=signal.campaign_id,
            theme_root=signal.theme_root,
            depth=signal.depth,
            code=signal.code,
            code_hash=signal.code_hash,
            stated_mechanism=signal.stated_mechanism,
            provenance=provenance,
            fail_class=fail_class,
            error_class=None if error is None else type(error).__name__,
            error_message=None if error is None else str(error),
            attempt=attempt,
            attempts=len(interruptions) + 1,
            interruptions=interruptions,
        )

    def row(self, artifact_uri: str) -> dict[str, Any]:
        """The attempt as the ``node`` row it lands in — a fresh dict.

        The columns this feature writes, with the artifact address passed
        in rather than computed here, because the address is the *store's*
        — :meth:`AttemptLog.record` derives it from the very directory it
        published the bytes through, so the row and the directory are one
        path resolved once.  A ``row()`` that computed its own address
        from a root this value does not hold would be the second spelling
        of one location, and the one thing ``artifact_uri TEXT NOT NULL``
        cannot tolerate is two answers.

        The seven metrics and ``created_at`` are absent by design — see
        the module docstring: the first are step 12's measured numbers,
        and the second is not a column ``0118`` declares.
        """
        address = _validated_text(artifact_uri, ARTIFACT_URI_COLUMN, self.node_id)
        return {
            "id": self.node_id,
            "parent_id": self.parent_id,
            "campaign_id": self.campaign_id,
            "theme_root": self.theme_root,
            "depth": self.depth,
            "code_hash": self.code_hash,
            "stated_mechanism": self.stated_mechanism,
            ARTIFACT_URI_COLUMN: address,
            "evaluator_hash": self.provenance.evaluator_hash,
            "snapshot_hash": self.provenance.snapshot_hash,
            "cost_model_hash": self.provenance.cost_model_hash,
            "agent_model_id": self.provenance.agent_model_id,
            "agent_ckpt_hash": self.provenance.agent_ckpt_hash,
            "agent_sampling": self.provenance.agent_sampling,
            FAIL_CLASS_COLUMN: self.fail_class,
        }

    def trace(self) -> dict[str, Any]:
        """The attempt as §9.2's ``exec_trace.json`` — the run's fingerprint.

        The one file in the node's directory that records the *attempt*
        rather than its numbers, and the half of feature 173's pair this
        feature owns.  Where the evaluator's step 12 renders a trace from
        what it measured, this one renders it from what the orchestrator
        knows — and the orchestrator knows two things the evaluator does
        not: **how the attempt ended** (``fail_class``, and the exception
        class and message beside it when it failed) and **what it cost**
        (feature 244's ``attempt``/``attempts`` and the reclaimed runs
        before it).  A node that failed four times before standing still
        answers *four* from this file and *one* from the table, and both
        are true: the table holds one node, the artifact holds its history.

        ``node_id`` and ``campaign_id`` are spelled exactly as the
        directory's own two keys, because the artifacts member's write
        path refuses a trace filed under a node it does not fingerprint —
        a check this module passes by construction rather than by
        coincidence, since both values come off the same
        :class:`~discovery.expansion.RefinedSignal` the address does.

        Everything here is a JSON scalar, list or object, so the renderer
        cannot meet an unserializable value: the fields are already
        validated text, counts and ``None``.
        """
        body: dict[str, Any] = {
            "node_id": self.node_id,
            "parent_id": self.parent_id,
            "campaign_id": self.campaign_id,
            "theme_root": self.theme_root,
            "depth": self.depth,
            "code_hash": self.code_hash,
            "stated_mechanism": self.stated_mechanism,
            FAIL_CLASS_COLUMN: self.fail_class,
            "attempt": self.attempt,
            "attempts": self.attempts,
            "interruptions": [
                {
                    "slot": interrupted.get("slot"),
                    "error_class": interrupted.get("error_class"),
                    "error_message": interrupted.get("error_message"),
                }
                for interrupted in self.interruptions
            ],
            "evaluator_hash": self.provenance.evaluator_hash,
            "snapshot_hash": self.provenance.snapshot_hash,
            "cost_model_hash": self.provenance.cost_model_hash,
            "agent_model_id": self.provenance.agent_model_id,
            "agent_ckpt_hash": self.provenance.agent_ckpt_hash,
            "agent_sampling": json.loads(self.provenance.agent_sampling),
        }
        if self.error_class is not None:
            body["error_class"] = self.error_class
        if self.error_message is not None:
            body["error_message"] = self.error_message
        return body

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"{type(self).__name__}(node_id={self.node_id!r}, "
            f"fail_class={self.fail_class!r}, attempt={self.attempt!r} "
            f"of {self.attempts!r})"
        )


def _canonical_node_id(value: Any, *, field_name: str = "parent_id") -> str:
    """Canonicalize one node id, refusing what is not one.

    The same canonicalization the campaign store and the expansion both
    apply to the tree's key — a :class:`uuid.UUID`, or text
    :class:`uuid.UUID` parses, is canonicalized to its lowercase hyphenated
    form so two spellings of one id are one value — restated here for the
    fourth time in this member rather than imported, because each of the
    three writers names its own refusal for its own act and a caller's
    ``except AttemptLogError`` must not be defeated by a refusal another
    module's class raised.
    """
    if isinstance(value, uuid.UUID):
        return str(value)
    if not isinstance(value, str):
        raise AttemptLogError(
            f"a node id must be a string or a UUID — got "
            f"{type(value).__name__} {value!r} for {field_name}; the tree "
            "keys every row by the id ``0118`` declares as its primary key "
            "(feature 240)"
        )
    try:
        return str(uuid.UUID(value.strip()))
    except (ValueError, AttributeError, TypeError) as exc:
        raise AttemptLogError(
            f"{value!r} is not a node id ({field_name}): {exc}; the tree's "
            "key is a UUID, and an attempt filed under a value the table "
            "cannot hold is an attempt nothing could ever read back "
            "(feature 240)"
        ) from exc


# -- The artifact seam -------------------------------------------------------------


class ArtifactDirectory(Protocol):
    """The artifact store's seam — how an attempt's bytes reach §9.2.

    Injected, not imported: the workspace contract keeps this member from
    reaching the artifacts member, so the directory arrives as an object
    exposing the four methods :class:`artifacts.ArtifactStore` already
    speaks — satisfied *structurally, by name, with no adapter*, the same
    way feature 85's :class:`~evaluator.ArtifactWriter` and feature 239's
    agent are injected.  The four are spelled with the store's own
    signatures on purpose: an adapter layer would be a second place the
    layout could drift, and the layout is a contract.

    .. py:method:: node_directory(campaign_id, node_id) -> Path

        Persist and return the node's one directory —
        ``<root>/<campaign_id>/<node_id>``.  This module calls it *once*
        per recorded attempt and uses the answer for both halves: the
        bytes are staged under it and the row's ``artifact_uri`` is
        rendered from it, so the address in the table and the directory
        on disk cannot be two paths.

    .. py:method:: write(campaign_id, node_id, filename, data) -> Path

        Stage one file.  Staged bytes are invisible to every read until
        the commit, which is what makes a failed attempt publish nothing.

    .. py:method:: commit(campaign_id, node_id) -> Path

        Publish the node's whole staged set as its directory, replacing
        any prior version wholesale.  **This is the commit point of one
        attempt's artifact**, and it publishes whatever the caller staged
        for the node alongside this module's pair — which is why the
        measured files feature 85 renders are staged *before* the attempt
        is recorded.

    .. py:method:: files(campaign_id, node_id) -> Sequence[str]

        **Optional.**  The *published* directory's filenames, sorted.
        Read-only and total: it answers "what is there?" without raising,
        which is why the carry-forward asks it instead of probing with
        ``read`` — see :meth:`AttemptLog._restage_published` for why an
        exception-driven probe across a member seam is the wrong shape.

    .. py:method:: read(campaign_id, node_id, filename) -> bytes

        **Optional.**  The bytes of one *published* file.  Feature 240
        calls it only for names :meth:`files` listed, to carry step 12's
        measured five across a whole-directory commit that would
        otherwise drop them.  A store exposing neither is not refused:
        the caller that wants them preserved stages them itself, which is
        the documented path and needs no recovery — a degraded *artifact*
        must never become a failed *write*, since the row, the source and
        the trace are the feature's sentence.

    .. py:method:: discard(campaign_id, node_id) -> None

        Roll the staged set back.  Called when the row write refuses, so a
        refused attempt leaves neither half behind.
    """

    def node_directory(self, campaign_id: str, node_id: str) -> Path:
        """Persist and return the node's one directory."""
        ...

    def write(
        self,
        campaign_id: str,
        node_id: str,
        filename: str,
        data: bytes | bytearray | memoryview | str,
    ) -> Path:
        """Stage one file of the node's artifact."""
        ...

    def commit(self, campaign_id: str, node_id: str) -> Path:
        """Publish the node's staged set as its directory."""
        ...

    def discard(self, campaign_id: str, node_id: str) -> None:
        """Roll the node's staged set back."""
        ...

    def files(self, campaign_id: str, node_id: str) -> Sequence[str]:
        """The published directory's filenames, sorted."""
        ...

    def read(self, campaign_id: str, node_id: str, filename: str) -> bytes:
        """The bytes of one published file of the node's artifact."""
        ...


# -- The write ---------------------------------------------------------------------


@dataclass(frozen=True)
class AttemptRecord:
    """What recording one attempt left behind — the write's answer.

    The node's identity, the class the attempt ended in, the address the
    row now carries, the files the published directory holds, and the one
    idempotency signal: :attr:`appended` is ``True`` when *this* call
    inserted the row and ``False`` when it refreshed one a prior attempt
    of the same job wrote.  The same shape and the same reason as feature
    85's ``tree_appended`` — a retry must be distinguishable from a first
    write, because §14's idempotence is a fact about the *ledger* and this
    is the tree's side of it.

    :attr:`artifact_files` is what a reader would find in the directory
    *now* — read back after the commit rather than remembered from the
    staging — so a caller that staged the measured files before recording
    sees them in the answer, and a caller that staged nothing but this
    module's pair sees exactly the two.
    """

    #: The node this attempt landed on — the parent's derivation.
    node_id: str
    #: The campaign the node belongs to.
    campaign_id: str
    #: §9.1's ``fail_class`` for this attempt.
    fail_class: str
    #: The address the row's ``artifact_uri`` column now carries.
    artifact_uri: str
    #: The files the node's published directory holds, sorted.
    artifact_files: tuple[str, ...]
    #: Whether *this* call inserted the row (``False`` on a refresh).
    appended: bool


class AttemptLog:
    """The tree writer and the artifact publisher, for one deployment.

    Constructed with the database URL the tree lives in and the artifact
    directory the bytes go to; called once per attempt.  The two
    collaborators are held rather than resolved per call because they are
    facts about the *deployment* — which database, which store — exactly
    as :class:`~discovery.expansion.NodeExpansion` holds its URL and its
    agent, and for the same reason: a log that resolved its tree from the
    ambient environment on every attempt would be a write whose target
    changed under the campaign loop.

    Construction performs no I/O.  The tree's path is translated on first
    use (so a URL this member cannot speak is refused by name the first
    time an attempt needs it, never at composition time) and the artifact
    directory is the injected object, untouched until a byte is staged —
    the composition-time contract every store in this workspace keeps.
    """

    def __init__(self, database_url: str, directory: ArtifactDirectory) -> None:
        """Wire the log: the tree it writes into, the store it publishes through.

        Both are validated here, before any call, because both are facts
        about the *log* rather than about any one attempt: a URL that is
        not a non-empty string names no tree, and a directory that does
        not speak the four-method seam would fail identically on every
        attempt — the wrong place for a campaign to discover a wiring
        fault, exactly as a non-callable agent is for the expansion.
        """
        if not isinstance(database_url, str) or not database_url.strip():
            raise AttemptLogError(
                f"the attempt log needs a database URL naming the tree it "
                f"writes into, got {database_url!r}; every attempt lands in "
                "the ``node`` table a deployment migrated, and a log with "
                "no tree names no table its rows could reach (feature 240)"
            )
        for method in ("node_directory", "write", "commit", "discard"):
            if not callable(getattr(directory, method, None)):
                raise AttemptLogError(
                    f"the artifact directory must expose {method} — the "
                    f"ArtifactDirectory seam an ArtifactStore already "
                    f"satisfies — got {directory!r} "
                    f"({type(directory).__name__}), which does not; the "
                    "attempt's source and trace reach §9.2 through this "
                    "one seam, and a store that cannot be written through "
                    "is a log that would record rows whose artifacts do "
                    "not exist (feature 240)"
                )
        self._database_url = database_url.strip()
        self._directory = directory
        # Resolved on first use rather than at construction: building the
        # log is composition-time work and must not touch the disk.
        self._path: Path | None = None

    @property
    def database_url(self) -> str:
        """The database URL this log writes to."""
        return self._database_url

    @property
    def directory(self) -> ArtifactDirectory:
        """The artifact directory this log publishes through."""
        return self._directory

    @property
    def path(self) -> Path:
        """The SQLite file behind the tree, resolved on first use."""
        if self._path is None:
            self._path = _sqlite_path(self._database_url)
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """Open the tree's database — read-write, and the author of one column.

        **The ``node`` table is not created here.**  It is feature 97's
        (``0118``) and the ten columns beside its five are features
        98-101's, so a log that created the table would be inventing a
        tree the migrations own — the inverse of the ``CREATE TABLE IF
        NOT EXISTS`` every *reader* in this workspace runs, and the same
        stance :class:`discovery.campaign.CampaignRecords` takes toward
        the ``campaign`` table.  An absent table is :meth:`record`'s own
        named refusal.

        **``fail_class`` is added here, and it is the one exception
        because it is the one column that is this feature's own.**
        §9.1 declares it on ``node`` and *no migration declares it at
        all* — ``0118``'s docstring says so from the other side, arguing
        that ``created_at``'s absence is honest because *"the honest form
        is a feature that names it, not a sixth column"*.  Feature 240
        names it: the column is what *"including failures"* is recorded
        in, and without it every failed attempt would be a row that says
        ``ok``.  The probe-then-``ALTER`` is the shipped convention for
        exactly this situation — :mod:`nulloracle.plan` does it for
        feature 119's ``flip_depth``, :mod:`tripwires.layout` and
        :mod:`tripwires.node_metric` for ``poisoned_at`` and
        ``perturb_stability`` — and it is idempotent in both directions:
        a deployment whose chain later gains the column, and one whose
        migration already ran, both find it present and neither is
        altered.  Nullable, so the statement is legal on a populated
        table (the reason ``0117``'s ``NOT NULL`` pair needed the empty
        table; ``ADD COLUMN`` has no ``IF NOT EXISTS``, which is why the
        probe is the guard).

        Nothing else is added.  The seven metrics are step 12's and
        ``created_at`` is a column three features short of here, so this
        method widens the tree by exactly the column this feature's
        sentence requires and no more.

        ``PRAGMA foreign_keys = ON`` is not decoration: ``0118`` declares
        ``parent_id UUID REFERENCES node(id)``, and the constraint is what
        makes *"an attempt hangs off a node the tree holds"* enforced by
        the database rather than trusted from the caller.  The probe
        :meth:`record` runs beside it is the diagnosis, because SQLite's
        own ``FOREIGN KEY constraint failed`` names no node.
        """
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys = ON")
        _ensure_fail_class_column(connection)
        return connection

    # -- Feature 240: the record --------------------------------------------

    def record(self, attempt: Any) -> AttemptRecord:
        """Persist one attempt — its ``node`` row and its artifact directory.

        Feature 240's sentence as one call, and the steps in the order
        they must happen:

        1. **Validate the attempt.**  A value that is not an
           :class:`Attempt` is refused by name.  (Everything about a
           well-formed attempt was already checked inside the value, which
           is where :class:`Attempt` puts the identity law; this step is
           the seam's own refusal, for the caller that handed over
           something else entirely.)
        2. **Resolve the node's one directory**, through the injected
           store.  The answer is used for both halves below, so the
           address the row carries and the directory the bytes land in are
           one path — see :meth:`Attempt.row`.
        3. **Refuse a tree without the deployment's schema.**  The ``node``
           table is probed read-only and its absence is named, rather than
           surfacing SQLite's ``no such table``; the attempt's
           ``parent_id`` is probed too, so a child of a node nobody
           planted is refused naming the node instead of failing as a
           foreign-key violation.  Both land before any byte is staged.
        4. **Write the row**, inserted or refreshed, inside one
           transaction, and take its answer's ``appended``.  This lands
           *before* any byte is staged, and the order is load-bearing:
           step 3's refusals must reach the caller before this module has
           touched the caller's staged measured five, so a refused attempt
           cannot destroy the caller's work on its way out (the sibling
           test ``test_a_row_write_refusal_leaves_the_callers_staged_set_alone``
           is that fact, read off the seam).
        5. **Stage the orchestrator's pair** — ``code.py`` and
           ``exec_trace.json`` — through the same directory.
        6. **Carry forward any published measured file** — §9.2's other
           five, restaged as opaque bytes from the directory this attempt
           is about to replace.  See :meth:`_restage_published`: without
           this a retry would publish a complete artifact for the standing
           attempt and delete the evaluation's numbers doing it.
        7. **Commit the directory**, publishing the whole staged set: this
           module's pair, the caller's measured five as they were staged
           or as they were published, and nothing invented.  This is the
           attempt's commit point.
        8. **Read the published directory back** so
           :attr:`AttemptRecord.artifact_files` reports what a reader
           would actually find rather than what this call remembers
           staging.

        **What a failure leaves behind depends on where it lands, and the
        two cases are different facts.**  A failure at step 3 stages no
        byte and writes no row: the tree refused the attempt, so the call
        leaves the campaign and the caller's staged set exactly as it
        found them.  A failure at step 5 or later is the **half state**,
        and it is worth stating precisely rather than denying: the row is
        already committed, so it *stays* committed, and what rolls back is
        the staged pair, discarded through the seam's own ``discard`` —
        and only the pair *this* call staged, since a discard on a failure
        that happened before the first ``write`` would throw away files
        the caller staged for the node before recording, which are none of
        this call's business to destroy.  The attempt is therefore
        recorded as a row whose ``artifact_uri`` names a directory that
        was not published: exactly the state ``0117``'s ``NOT NULL``
        column exists to make visible rather than silent.

        That state is recoverable rather than corrupt, and the recovery is
        the identity law.  Re-issuing the attempt derives the same node,
        so the retry refreshes that row and publishes the directory it
        names — §14's idempotence, the same property :meth:`record_all`
        states for a whole batch, holding here for the single attempt that
        failed.  The opposite order — directory first, row second — would
        trade this for the strictly worse state, an artifact directory no
        row addresses, which nothing in the system would ever collect.

        Refuses, in order: an ask that is not an :class:`Attempt`
        (:class:`~discovery.errors.AttemptLogError`); a database holding no
        ``node`` table (the same class, naming ``0118``); a tree that does
        not hold the attempt's parent (the same class, naming the parent);
        a ``NOT NULL`` column the table declares that neither the attempt
        nor a ``DEFAULT`` fills (the same class, naming the column); and a
        directory seam that fails (the seam's own exception, propagating
        unwrapped — this module refuses only what it can reason about,
        and a store's own refusal already names its own fact).
        """
        if not isinstance(attempt, Attempt):
            raise AttemptLogError(
                f"record persists one attempt — got {attempt!r} "
                f"({type(attempt).__name__}); the feature's sentence is "
                "about a node row and its artifact, and a value that is "
                "not an attempt has neither (feature 240)"
            )
        node = attempt.node_id
        campaign = attempt.campaign_id

        directory = self._directory.node_directory(campaign, node)
        row = attempt.row(_artifact_uri(directory))

        with closing(self._connect()) as connection, connection:
            shape = _table_shape(connection, node)
            _require_parent(connection, attempt)
            appended = _write_row(connection, row, shape, node)

        staged = False
        try:
            # The orchestrator's pair first: these are the two §9.2 files
            # this feature owns, and they are staged before anything is
            # recovered so a failure below cannot leave a directory whose
            # bytes came from the *previous* attempt.
            self._directory.write(campaign, node, SOURCE_FILENAME, attempt.code)
            # ``allow_nan=False`` is this renderer's own choice, not the
            # seam's: a trace is read back by a later process, ``NaN`` is
            # not JSON, and an attempt's own fields are text, counts and
            # ``None``, so nothing here can meet it legitimately.  One
            # ``try`` so every failure of the pair rolls back through one
            # ``except`` — including a ``BaseException``, which is what
            # feature 238 captures per job and feature 244 marks as an
            # interruption: a reclaim mid-write must not leave a staged
            # set behind for the next attempt of the same job to publish
            # as though this one had finished.
            trace = json.dumps(
                attempt.trace(),
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            self._directory.write(campaign, node, TRACE_FILENAME, trace)
            staged = True
            # A refresh re-publishes the node's *whole* directory, which
            # is what makes the address on the row and the files on disk
            # describe the same attempt — but the measured five are
            # step 12's and this call cannot mint them.  Recovering them
            # from the published directory first is what keeps a retry
            # from deleting an evaluation's numbers; see
            # :meth:`_restage_published`.
            self._restage_published(campaign, node)
            self._directory.commit(campaign, node)
        except BaseException:
            # The pair rolls back like any staged file — but only if *this*
            # call staged it.  A discard on a failure that happened before
            # the first ``write`` would throw away files the caller staged
            # for the node before recording, which are none of this
            # call's business to destroy.
            if staged:
                self._directory.discard(campaign, node)
            raise
        return AttemptRecord(
            node_id=node,
            campaign_id=campaign,
            fail_class=attempt.fail_class,
            artifact_uri=row[ARTIFACT_URI_COLUMN],
            artifact_files=tuple(
                sorted(entry.name for entry in directory.iterdir())
            ),
            appended=appended,
        )

    def record_all(self, attempts: Any) -> tuple[AttemptRecord, ...]:
        """Persist a batch of attempts, in the order given.

        A plain loop rather than a generator, and the distinction is the
        feature's own: the pool's *"as each worker completes"* is feature
        238's streaming law and it is satisfied one layer up — a caller
        records each :class:`Attempt` the moment the result it came from
        arrives, by calling :meth:`record` once.  This verb is for the
        caller that already holds the batch (a retry's
        ``interruptions + (result,)``, a replay of a manifest), and it
        deliberately does **not** swallow failures: an attempt the tree
        refuses stops the call with the refusal, because a batch whose
        first failure was skipped silently would leave later attempts
        recorded as though the tree were complete.

        ``attempts`` must be an iterable of :class:`Attempt` — a bare
        ``str`` or ``bytes`` is refused as an ask spelled without its
        brackets, the same refusal feature 238's dispatch makes for a
        batch, because iterating one would silently turn it into a batch
        of characters.  An empty iterable records nothing and answers an
        empty tuple: nothing to persist is not this verb's judgement to
        overturn.

        **A refusal leaves the batch half-written, and that is stated
        rather than denied.**  Each attempt is committed by its own call
        — one transaction, one published directory — so the attempts
        before the refusal are *persisted attempts*, not a partial
        transaction, and the tuple never returns, which is why the
        refusal reports only the node it stopped on.  The distinction
        that matters is that this is idempotent rather than destructive:
        every attempt that landed did so whole, and re-issuing the batch
        once the offending one is fixed refreshes those rows and
        re-publishes those directories through each node's derived
        identity, so the second run of the campaign loop finishes a log
        the first run started.  Making it atomic instead would mean one
        transaction spanning every artifact publish, and a directory
        committed beside a transaction that later rolls back is exactly
        the ``artifact_uri`` naming nothing that §9.1's ``NOT NULL``
        column exists to prevent.
        """
        if isinstance(attempts, (str, bytes, bytearray)) or not isinstance(
            attempts, Iterable
        ):
            raise AttemptLogError(
                f"record_all persists a batch of attempts — got "
                f"{type(attempts).__name__} {attempts!r}; a batch is an "
                "iterable of Attempt values, and a single ask spelled "
                "without its brackets would be iterated into a batch of "
                "characters by a loop that trusted it (feature 240, the "
                "refusal feature 238's dispatch makes for its own jobs)"
            )
        return tuple(self.record(attempt) for attempt in attempts)

    def _restage_published(self, campaign: str, node: str) -> None:
        """Carry an already-published measured file into this attempt's commit.

        The one thing a whole-directory commit makes dangerous.  §9.2
        lists **seven** files and this feature owns two of them; the other
        five are step 12's, rendered by features 170-173 from records this
        member has never seen.  A ``commit`` publishes the node's staged
        set *as* the directory, replacing the prior version wholesale —
        which is exactly the property that makes a retry re-publish one
        attempt's complete artifact, and exactly what would silently
        delete an evaluation's numbers the second time a job is recorded
        (feature 244's retry, or a §14 reclamation's re-run).

        So before the commit, every §9.2 name this call does not itself
        stage is checked against the *published* directory and, where
        found, staged again as opaque bytes.  Nothing here decodes,
        validates or re-renders one: a Parquet file is the artifacts
        member's business, and an orchestrator that grew a ``polars``
        import to carry it would be paying composition cost for a number
        it cannot read.  The bytes travel unchanged between the two halves
        of one pipeline step, which is the only honest way for this module
        to be party to a measured artifact at all.

        **A store that does not expose ``read`` is not refused.**  The
        seam's other four methods are required and this one is optional
        (see :class:`ArtifactDirectory`), because the fallback is a
        degraded *artifact*, not a failed write: the row, the source and
        the trace are feature 240's sentence, and refusing to record an
        attempt because a store could not hand back a Parquet file would
        trade a complete record for a partial one.  The caller that wants
        the measured five preserved stages them itself, which is the
        documented path and the one that requires no recovery at all.

        **What is published is asked, not discovered by failing.**  The
        store is asked which names its directory holds (the seam's
        optional ``files``) and only those are read.  The obvious
        alternative — call ``read`` and treat the exception as "absent" —
        is the trap this module is written to avoid: a sibling's
        absence is signalled with *its own* error class
        (:class:`artifacts._errors.ArtifactNotFoundError`), which this
        member may not import and therefore cannot name in an ``except``,
        so the probe would have to catch bare ``Exception`` and would
        swallow a genuine store fault as though the file were simply not
        there.  A query has no such ambiguity — it answers a question
        rather than raising one — and a store that does not expose
        ``files`` is in the same position as one that does not expose
        ``read``: the caller stages the measured five itself, which is
        the documented path.

        A ``read`` that fails *after* the name was listed is a real
        inconsistency in the store, and it is deliberately not fatal to
        the record: this method's whole contract is that a degraded
        *artifact* never becomes a failed *write*, because the row, the
        source and the trace are the feature's sentence.  The exception
        vocabulary across a member seam is not enumerable, so the guard
        is deliberately broad (see :func:`_published_bytes`) rather than
        pretending otherwise.
        """
        files = getattr(self._directory, "files", None)
        read = getattr(self._directory, "read", None)
        if not callable(files) or not callable(read):
            return
        try:
            published = set(files(campaign, node))
        except Exception:  # noqa: BLE001 - see the docstring: unenumerable
            return
        for name in MEASURED_FILENAMES:
            if name not in published:
                continue
            body = _published_bytes(read, campaign, node, name)
            if body is None:
                continue
            self._directory.write(campaign, node, name, body)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"{type(self).__name__}(database_url={self._database_url!r}, "
            f"directory={self._directory!r})"
        )


# -- The row, as SQL ---------------------------------------------------------------


def _ensure_fail_class_column(connection: sqlite3.Connection) -> None:
    """Add §9.1's ``fail_class`` to ``node`` if the tree does not have it.

    The one column this feature owns, and the one place in this member
    that issues DDL.  §9.1 declares the column and no migration creates
    it; the shipped convention for a store that owns a node column is the
    probe below plus ``ALTER TABLE`` — :mod:`nulloracle.plan` does it for
    feature 119's ``flip_depth``, :mod:`tripwires.layout` and
    :mod:`tripwires.node_metric` for ``poisoned_at`` and
    ``perturb_stability`` — and the probe is what makes it idempotent,
    because SQLite's ``ADD COLUMN`` carries no ``IF NOT EXISTS``.

    **A database with no ``node`` table is left alone.**  ``PRAGMA
    table_info`` answers with no rows for a missing table, so the loop
    below issues nothing and the absent table stays absent — it is
    :meth:`AttemptLog.record`'s refusal to name, with the migration that
    owns it, and a log that created the table from a ``PRAGMA`` would be
    inventing a tree three features wide out of one column's worth of
    knowledge.

    **Nullable, deliberately.**  ``ALTER TABLE ... ADD COLUMN ... NOT
    NULL`` without a ``DEFAULT`` succeeds only on an empty table — the
    constraint ``0117``'s docstring documents from its own side — and a
    tree this store reaches may already hold the campaign's roots.  ``is
    null`` is therefore meaningful and is the honest reading: a node the
    orchestrator did not write an attempt for has no failure class,
    which is a different fact from having answered.
    """
    try:
        rows = connection.execute(_TABLE_COLUMNS_SQL).fetchall()
    except sqlite3.Error:  # pragma: no cover - sqlite_master probe is safe
        return
    if not rows:
        return
    if any(str(row[1]) == FAIL_CLASS_COLUMN for row in rows):
        return
    with connection:
        connection.execute(
            f"ALTER TABLE node ADD COLUMN {FAIL_CLASS_COLUMN} TEXT"
        )


def _table_shape(
    connection: sqlite3.Connection, node: str
) -> dict[str, tuple[bool, bool]]:
    """The tree's ``node`` columns: ``name -> (not_null, has_default)``.

    Read from the live table rather than assumed from the migration tree,
    because the tree reaches a database through an *assembled* chain and
    this module writes against whichever one the deployment ran.  A
    missing table is refused **here**, naming ``0118``, rather than left
    for the INSERT to discover: SQLite's ``no such table: node`` names the
    table but not the feature that owns it, and the orchestrator's own
    refusal can say both.

    Two facts per column, and the second is not decoration.  ``0118``
    declares ``id UUID NOT NULL PRIMARY KEY DEFAULT <sqlite v4 expr>``,
    so a column list that asked "is every ``NOT NULL`` column filled by
    the attempt?" would report ``id`` as missing on a table where the
    database supplies it — a refusal for a row that writes perfectly well.
    The ``dflt_value`` pragma column is therefore read beside the
    ``notnull`` one (it is ``None`` when the column has no default, and a
    *text* default such as ``'{}'`` or ``'ok'`` when it has one, which is
    why the check is ``is not None`` rather than a truth test).
    """
    try:
        rows = connection.execute(_TABLE_COLUMNS_SQL).fetchall()
    except sqlite3.Error as exc:
        raise AttemptLogError(
            f"this database holds no node table ({exc}): the tree is "
            "created by migrations/versions/0118_node_table.py (feature "
            "97) and every attempt lands in it, so a database the "
            "migration has not reached has no table these rows could be "
            "written into (feature 240)"
        ) from exc
    if not rows:
        raise AttemptLogError(
            "this database holds no node table: the tree is created by "
            "migrations/versions/0118_node_table.py (feature 97), and an "
            "attempt logged against a database without it would be a row "
            "nothing could ever read back (feature 240)"
        )
    return {
        str(row[1]): (bool(row[3]), row[4] is not None) for row in rows
    }


def _require_parent(connection: sqlite3.Connection, attempt: Attempt) -> None:
    """Refuse an attempt whose parent the tree does not hold.

    ``0118`` declares ``parent_id UUID REFERENCES node(id)`` and
    :meth:`AttemptLog._connect` turns the constraint on, so this probe is
    the *diagnosis* rather than the enforcement — the write below would
    fail either way, and it would fail with SQLite's ``FOREIGN KEY
    constraint failed``, which names no node.  The expansion resumes a
    workspace the tree holds, so in a correct run this probe never fires;
    it exists because a caller can construct an :class:`Attempt` from a
    value it assembled rather than one the worker of record answered, and
    the failure that would otherwise reach an operator would be a
    constraint name and an integer, not a node.
    """
    if connection.execute(_PARENT_EXISTS_SQL, (attempt.parent_id,)).fetchone() is None:
        raise AttemptLogError(
            f"node {attempt.parent_id!r} is not in the tree, so attempt "
            f"{attempt.node_id} has no parent to hang from: every node is "
            "a child of another node (or a root) by way of the "
            "self-referencing ``parent_id``, and the selection that "
            "produced this attempt expanded nodes the tree holds "
            "(feature 240, the parent-side twin of feature 239's "
            "'node is not in the tree' refusal)"
        )


def _write_row(
    connection: sqlite3.Connection,
    row: dict[str, Any],
    shape: dict[str, tuple[bool, bool]],
    node: str,
) -> bool:
    """Write one attempt's ``node`` row; answer whether it was appended.

    The INSERT names the **intersection** of the columns the attempt
    carries with the columns the table has, which is what lets one writer
    serve a chain that stops at ``0118`` and a chain that runs through
    ``0117`` — and it is the same restraint the providers member's node
    writer states from the other side.  Two facts make the projection
    safe rather than merely convenient:

    * every ``NOT NULL`` column the table declares is either one an
      attempt always fills — ``0118``'s four (its ``id`` is defaulted),
      ``0115``'s two, ``0116``'s three, ``0117``'s ``code_hash`` and
      ``artifact_uri`` — or one the database supplies a ``DEFAULT`` for;
      ``agent_ckpt_hash`` is the one ``NOT NULL``-free member of those
      trios and ``stated_mechanism`` the one of the identity triple, and
      both are nullable precisely because their absence is a fact;
    * a column an attempt carries that the table does *not* have — a
      ``fail_class`` on a database whose tree has not reached it — is
      simply absent from the statement, which is how this writer serves a
      deployment whose chain is short without this module deciding that
      the column does not matter.

    A ``NOT NULL`` column the table has, that the attempt does **not**
    carry and that carries **no default** is refused by name, before the
    INSERT is built.  No shipped migration declares one, so this is a
    guard against a *future* column — and it is worth having, because
    SQLite would report that case as a constraint violation naming a
    column, which is not a sentence any operator should have to translate
    back into a feature.  The default exemption is what keeps ``id`` on
    the exempt side: ``0118`` gives it the v4 expression, so the database
    mints it whenever the caller's id is not in the column list, and
    refusing it here would be refusing ``0118``'s own DDL.

    The write is an ``UPDATE`` when the row exists and an ``INSERT`` when
    it does not, both inside the caller's single transaction: this is the
    refresh-not-duplicate law §14's idempotence rests on, and probing then
    writing is how the two are told apart honestly.  ``INSERT OR REPLACE``
    is deliberately *not* used: it deletes and re-inserts, which on a
    self-referencing table either cascades into children this feature
    never meant to touch or fails outright, and it would report no
    ``appended`` at all.  The ``UPDATE`` leaves the identity columns alone
    — they are already provably equal, the id being the parent's
    derivation — so a refresh rewrites the attempt's descriptions and
    nothing that identifies it.
    """
    missing = [
        name
        for name, (not_null, has_default) in shape.items()
        if not_null and not has_default and name not in row
    ]
    if missing:
        raise AttemptLogError(
            f"the tree's node table declares "
            f"{', '.join(repr(name) for name in missing)} NOT NULL and an "
            f"attempt carries no value for {'it' if len(missing) == 1 else 'them'}: "
            f"node {node} is an attempt whose row the column list cannot "
            "hold, and a fabricated default here would be identity "
            "belonging to a different node — the direction 0117 refuses a "
            "default for (feature 240)"
        )
    names = [name for name in _ATTEMPT_COLUMNS if name in shape]
    if not names:
        raise AttemptLogError(
            f"the tree's node table shares no column with an attempt "
            f"(it holds {', '.join(sorted(shape))}): node {node} cannot "
            "be written into a table this writer does not recognise, and "
            "guessing at the mapping would be this module legislating a "
            "schema three features short of it (feature 240)"
        )
    stored = connection.execute(
        "SELECT 1 FROM node WHERE id = ?", (row["id"],)
    ).fetchone()
    if stored is None:
        connection.execute(
            f"INSERT INTO node ({', '.join(names)}) "
            f"VALUES ({', '.join('?' for _ in names)})",
            [row[name] for name in names],
        )
        return True
    updated = [name for name in names if name not in _IDENTITY_COLUMNS]
    connection.execute(
        f"UPDATE node SET {', '.join(f'{name} = ?' for name in updated)} "
        "WHERE id = ?",
        [row[name] for name in updated] + [row["id"]],
    )
    return False


# -- Plumbing ----------------------------------------------------------------------


def _artifact_uri(directory: Path) -> str:
    """The §9.1 address of one node's artifact directory — pure.

    A ``file:`` URI of the directory, percent-encoded so any key the
    layout accepts round-trips.  Restated from
    :func:`artifacts.artifact_uri` rather than imported, because no member
    imports another — and the restatement is safe in a way a formula
    would not be, because both spellings are *one line over the same
    path*: the artifacts member resolves ``<root>/<campaign_id>/<node_id>``
    and this module is handed that very directory by the seam, so the two
    cannot disagree about the location.  ``packages/discovery/tests/
    test_cross_member.py`` pins the two spellings against each other, the
    remedy this workspace applies to every restatement.

    Percent-encoding rather than raw text: a URI is not a path, and one
    carrying a space or a ``#`` would parse back as a different address
    than the one it names.
    """
    return "file://" + quote(str(directory))


def _published_bytes(
    read: Callable[[str, str, str], bytes],
    campaign_id: str,
    node_id: str,
    filename: str,
) -> bytes | None:
    """One published file's bytes, or ``None`` when the store could not give them.

    The one broad guard in this module, and the reason it is broad rather
    than :class:`OSError`-shaped is worth stating where the guard lives
    rather than only where it is called.

    A sibling's absence is signalled with *its own* error class —
    :class:`artifacts._errors.ArtifactNotFoundError` — and this member
    may not import another member, so the class cannot be named in an
    ``except``.  The alternative spellings are both worse: a bare
    ``except Exception`` that let the caller distinguish nothing (this
    function's shape fixes that by returning rather than raising), or a
    narrow tuple that would let a genuine store fault escape and turn a
    degraded *artifact* into a failed *write* — which is precisely the
    trade this module refuses to make, since the row, the source and the
    trace are feature 240's sentence and a Parquet file is not.

    ``None`` is the absence signal on the *return* side, so the caller
    needs no ``except`` at all and the two questions a store can answer
    badly — "no such file" and "the store itself broke" — collapse to the
    one response that is correct for both: this attempt does not carry
    that measurement, and the row says so by not listing it.
    """
    try:
        body = read(campaign_id, node_id, filename)
    except Exception:  # noqa: BLE001 - a sibling's vocabulary is not importable
        return None
    if body is None:
        return None
    return body


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into the filesystem path it names.

    The same convention every store in this workspace restates —
    :func:`discovery.campaign._sqlite_path`'s translation with this
    module's own refusal vocabulary, because a caller's ``except
    AttemptLogError`` must not be defeated by a planning refusal raised
    from the log's path.  A non-SQLite scheme and a pathless URL are
    refused by name; an in-memory database is refused because a node row
    must outlive the campaign that wrote it, and the replay engine casts
    the artifact store it points at against rows another process wrote.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise AttemptLogError(
            f"unsupported {ATTEMPT_DATABASE_URL_ENV} scheme "
            f"{parsed.scheme!r}: the attempt log writes the tree the "
            "sqlite deployment holds (the spec's single-machine "
            f"allowance); point {ATTEMPT_DATABASE_URL_ENV} at the sqlite "
            "database the node table already lives in (feature 240)"
        )
    if parsed.netloc not in ("", "localhost"):
        raise AttemptLogError(
            f"sqlite {ATTEMPT_DATABASE_URL_ENV} must not carry a host, got "
            f"{parsed.netloc!r} (feature 240)"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path or path == ":memory:":
        raise AttemptLogError(
            f"sqlite {ATTEMPT_DATABASE_URL_ENV} carries no database path: "
            "an in-memory tree would die with the connection that opened "
            "it, and a node row must outlive the attempt that wrote it — "
            "the replay engine, the pool's census and the tripwire stores "
            "all reach this row from another process (feature 240)"
        )
    return Path(path)


# -- The module-level spelling -----------------------------------------------------


def record_attempts(
    attempts: Any,
    *,
    directory: Any,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[AttemptRecord, ...]:
    """Persist a batch of attempts — the module-level spelling.

    Feature 240's sentence as one call, for the caller that wants the act
    without holding a log: the attempts, the artifact directory they
    publish through, and (optionally) the tree.  The store is resolved
    from ``database_url``, else from ``DATABASE_URL``; a deployment that
    names neither is refused *by name* rather than silently doing
    nothing, because a log that quietly skipped its write would leave the
    tree missing exactly the attempts the campaign spent hypotheses on —
    the act the feature's sentence refuses.

    ``directory`` is required and has no default, because it is the
    sibling member's component and this module may not import it: the
    caller that holds the deployment's artifact store passes it, and the
    refusal for a missing one is
    :meth:`AttemptLog.__init__`'s, which names the four methods the seam
    speaks.  A default here would have to be a directory this module
    invented, and an attempt published to a store nobody named is an
    artifact the replay engine cannot find.

    A :class:`~discovery.errors.AttemptLogError` from the log propagates
    unwrapped: the refusal already names the node and the fact, and
    re-wrapping it here would put a second message in front of the one an
    operator needs.
    """
    source = os.environ if env is None else env
    url = (
        database_url
        if database_url is not None
        else source.get(ATTEMPT_DATABASE_URL_ENV, "").strip()
    )
    if not url:
        raise AttemptLogError(
            "record_attempts persists every attempt of a campaign and "
            f"nothing names a tree: {ATTEMPT_DATABASE_URL_ENV} is unset "
            "(and no database_url was supplied), so the rows could not be "
            "written. Feature 240's sentence is that every attempt — "
            "failures included — reaches the tree with its artifact, and "
            "a log that skipped its write would leave the campaign's "
            "spend unaccounted for (feature 240)"
        )
    return AttemptLog(url, directory).record_all(attempts)
