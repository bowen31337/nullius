"""The context — the evaluation inputs a live run loads, in one object.

additions_spec_live_evaluation.xml, "Orchestrator Member", feature 5:
*System creates the live evaluation inputs with
orchestrator._context.load_evaluation_context(env=None).  It answers an
EvaluationContext, or None when NULLIUS_EVALUATION_CONFIG is unset.*  The
spec's addition summary names the hole precisely — *"Nothing loads the
evaluation inputs from configuration"* — and the hole was real: every
piece existed (the sealed snapshot and its mount, the shared cost model,
the evaluator's identity, the epoch, the store), but the only thing that
assembled them was ``tests/e2e/test_momentum_signal_positive_ic.py``, a
test.  A live run had to hand-build the same nine facts at every call
site, and each hand-built copy was a place the provenance triple could
drift — one spelling of ``snapshot_hash`` computed over a different mount
than the one the evaluation read, and every score after it comparing
incomparables.  This module is the one loader: it answers the inputs
``_run_pipeline`` assembles (the snapshot handle, the closes, the cost
model, the fee schedule), stamped with the identity those very bytes
resolve to.

**One file for what a run is, the environment for what a deployment is.**
The JSON file ``NULLIUS_EVALUATION_CONFIG`` names holds exactly the seven
keys of :data:`REQUIRED_KEYS` — ``snapshot_mount``, ``evaluation_dates``,
``horizon``, ``seed``, ``epoch_id``, ``artifact_dir`` and
``sandbox_runtime`` — the facts that make one campaign's evaluation
*different* from another's.  Everything a deployment *is* stays in the
variables the members already read: ``DATABASE_URL``,
``NULLIUS_COST_MODEL_PATH``, ``NULLIUS_EVALUATOR_CONFIG`` (with the
image the evaluator's own identity resolves over,
``NULLIUS_EVALUATOR_IMAGE``), and the null sidecar's own variables,
which this module never touches — the sidecar and its key are the
nulloracle member's to resolve (§7.1), and a loader that reached for
them would be the orchestrator reading a credential the spec's standing
constraint forbids it to know exists.  That split is what the feature's
last sentence states — *"The file never holds a credential"* — and this
module holds it structurally: the key vocabulary is closed
(:data:`REQUIRED_KEYS` plus :data:`ACKNOWLEDGE_UNISOLATED_KEY`), and a
document carrying any other key is refused rather than read past, so a
credential cannot ride into a live run under a name the loader silently
ignored.  An operator who points the file at a sidecar key reference
gets a refusal naming the offending key, not a run.

**The sandbox gate is checked at load, before anything is touched.**
``sandbox_runtime`` is ``"gvisor"`` or ``"unisolated"`` — there is no
default, and a missing key is refused like any other.  ``"gvisor"`` is
accepted only when the ``runsc`` binary is on the ``PATH`` the same
environment names, looked up through :func:`shutil.which` on every load
(the nulloracle member's own ``sops`` lookup idiom — never cached, so a
deployment that installs the runtime need not restart to start
working); without it the load raises :class:`EvaluationConfigError`
naming ``isolation_required``, the one refusal in this module whose name
is not a key — it is the spec's own word for what is missing, and an
operator grepping a log for it finds feature 157's law and this gate
with one token.  ``"unisolated"`` is accepted only when the document
also holds ``acknowledge_unisolated: true`` *and* the ``bwrap`` binary is
on that same ``PATH``: the acknowledgement is the operator saying *in
the artifact that outlives the process* that model code will run on the
host, which is why a missing or false value is refused rather than
warned — a WARNING can scroll past; a refused configuraration stops the
run before the first ``import`` (the spec's constraint: *"Model-written
code never executes before the import screen"* — the gate is upstream
of that screen, and stays closed until the runtime is real or the risk
is owned).  The ``bwrap`` requirement is
``bug_spec_unisolated_os_boundary.xml`` (SEC-1): the Python import guard
:mod:`orchestrator._sandbox_child` installs is defense-in-depth, not a
security boundary — allowlisted modules re-export disallowed ones as
plain attributes (``dataclasses.sys`` is the real :mod:`sys`), so the
acknowledgement alone no longer suffices.  Isolation for ``"unisolated"``
comes from :class:`~orchestrator._hardened_sandbox.HardenedSubprocessSandbox`
running the child inside ``bwrap``, the same way isolation for
``"gvisor"`` comes from ``runsc``; neither runtime has a bare-subprocess
fallback, and a missing ``bwrap`` is refused under the same
``isolation_required`` name a missing ``runsc`` already carries.  Both spellings are compared
casefolded — ``gVisor`` and ``Runsc`` are one deployment written by two
people, and a law about capitalization would be a law about typography
(``sandbox._is_gvisor`` makes the same call) — and the context carries
the canonical lowercase, so a consumer compares against one spelling.

**The inputs are exactly ``_run_pipeline``'s, and nothing else.**  The
e2e journey's ``_run_pipeline(resolution, closes, config, schedule,
materialize)`` consumes four values a live run must supply (the fifth,
``materialize``, is the lake reader feature 7 injects over the same
mount): the snapshot handle, the closes, the cost model and the fee
schedule.  This loader answers those four and the identity they resolve
to, reading each through the member that owns it:

* the **snapshot** is :meth:`snapshot.SnapshotMount.for_directory` over
  ``snapshot_mount`` — the seam for a caller that holds a path rather
  than a name — so the read-only modes are re-asserted and every later
  read goes through the mount's own refusals;
* the **closes** are a lazy view over the mounted ``bars`` partitions
  (one close per symbol per bar date, the venue's string spelling
  parsed to the finite positive float step 4 validates) — the roster of
  symbols and dates is a directory listing, paid for here, but a given
  symbol's day is read and memoized (keyed by snapshot, symbol and day)
  only the first time something actually indexes it, so every
  evaluation of one context still aligns its targets over the same
  sealed bytes without every partition being opened whether or not a
  node's evaluation ever touches it;
* the **cost model and fee schedule** come from the cost-model member's
  own service over ``NULLIUS_COST_MODEL_PATH`` (the shipped §6.2
  document when unset), one parse for the pair, the hash and the rates
  (feature 60's single-parse seam), the schedule resolved through the
  process's one claimed fee implementation (feature 69) — never a second
  fee arithmetic;
* the **evaluator identity** is :meth:`evaluator.EvaluatorService.identity`
  over the environment's pinned image and configuration — the member's
  own formula, so the ``evaluator_hash`` a live run stamps is the hash
  the evaluator member would compute, not a re-implementation;
* the **snapshot hash** is read from the ``MANIFEST.json`` inside the
  mounted directory — the full 64 hex the directory name only
  abbreviates, so a context names the exact sealed content.

Loading reads; it persists nothing.  The identity is computed
(:meth:`~evaluator.EvaluatorService.identity`), not recorded; the cost
model is loaded (:attr:`~cost_model.service.CostModelService.config`),
not landed.  Rows are feature 7's to write through ``persist_node``,
which is where the evaluator's own stores apply their laws — a loader
that opened a database connection would make an unrunnable
configuration indistinguishable from an unreachable one.

**``None`` is a legitimate answer.**  An unset (or blank)
``NULLIUS_EVALUATION_CONFIG`` means the deployment runs no live
evaluation, and :func:`load_evaluation_context` answers ``None`` so the
composed component (feature 8) can answer ``None`` in turn — the same
stance the evaluator's own service takes toward an unpinned image, for
the same reason: composition must not fail on a member's missing
configuration, and "not configured" is a state, not an error.  Every
*configured but broken* shape, by contrast, is an error, and exactly one:
:class:`EvaluationConfigError`, opening with the greppable code word
:data:`EVALUATION_CONFIG_CODE` and naming the key or variable at fault —
a missing file, a missing key, a malformed value, a missing
``DATABASE_URL``, an unmountable snapshot, an unparseable cost model, an
unpinned image.  Refusals that originate in Z0 members surface through
their own errors first and are translated here (chained, cause intact),
because at this seam the caller asked a configuration question and
deserves a configuration answer that still names whose law refused.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import re
import shutil
import threading
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from cost_model import (
    CostModelConfig,
    CostModelError,
    CostModelService,
    FeeSchedule,
)
from evaluator import (
    DEFAULT_CONFIG,
    EvaluatorConfigError,
    EvaluatorImageError,
    EvaluatorService,
    SandboxResult,
)
from snapshot import (
    MANIFEST_NAME,
    SnapshotError,
    SnapshotManifest,
    SnapshotMount,
)

from ._gvisor import GVisorSandbox
from ._hardened_sandbox import HardenedSubprocessSandbox

__all__ = [
    "ACKNOWLEDGE_UNISOLATED_KEY",
    "BARS_STREAM",
    "BWRAP_RUNTIME",
    "DEFAULT_EVALUATION_MODE",
    "DEFAULT_EVALUATION_WORKERS",
    "DEFAULT_MAX_HISTORY_DAYS",
    "EVALUATION_CONFIG_CODE",
    "EVALUATION_CONFIG_ENV",
    "EVALUATION_MODES",
    "EVALUATION_MODE_KEY",
    "EVALUATION_WORKERS_KEY",
    "GVISOR_RUNTIME",
    "GVISOR_RUNTIME_ROOT_KEY",
    "GVISOR_STATE_ROOT_KEY",
    "ISOLATION_REQUIRED",
    "LAKE_ROOTS_KEY",
    "MAX_EVALUATION_WORKERS",
    "MAX_HISTORY_DAYS_KEY",
    "MIN_EVALUATION_WORKERS",
    "OOS_DATES_KEY",
    "REQUIRED_KEYS",
    "SANDBOX_RUNTIMES",
    "TEST_STUB_SANDBOX_ENV",
    "EvaluationConfigError",
    "EvaluationContext",
    "load_evaluation_context",
    "signal_sandbox",
]

#: The environment variable naming the JSON file that configures a live
#: evaluation.  Unset (or blank) is the *unconfigured* state and answers
#: ``None``; set is a commitment this module holds to the letter.
EVALUATION_CONFIG_ENV: Final[str] = "NULLIUS_EVALUATION_CONFIG"

#: The greppable code word every :class:`EvaluationConfigError` opens
#: with — the spec's own parenthetical, spelled once so the refusal
#: vocabulary of this module is one token an operator can grep a log for.
EVALUATION_CONFIG_CODE: Final[str] = "evaluation_config"

#: The seven keys the configuration file holds, in the spec sentence's
#: own order.  Closed on purpose: the file never holds a credential, and
#: a vocabulary a loader reads past is one a credential can ride in
#: under — an unknown key is refused (see :func:`_refuse_unknown_keys`).
REQUIRED_KEYS: Final[tuple[str, ...]] = (
    "snapshot_mount",
    "evaluation_dates",
    "horizon",
    "seed",
    "epoch_id",
    "artifact_dir",
    "sandbox_runtime",
)

#: The one conditional key: ``true`` is required exactly when
#: ``sandbox_runtime`` is ``"unisolated"`` — the operator's in-artifact
#: acknowledgement that model code will run on the host.
ACKNOWLEDGE_UNISOLATED_KEY: Final[str] = "acknowledge_unisolated"

#: The two runtimes ``sandbox_runtime`` accepts.  A gVisor *executor* is
#: a later spec; what this member holds is the gate, not the runner.
SANDBOX_RUNTIMES: Final[tuple[str, str]] = ("gvisor", "unisolated")

#: The three keys a ``"gvisor"`` runtime also needs, read straight off the
#: document rather than through :data:`REQUIRED_KEYS`: they are conditional
#: on the runtime, the same shape :data:`ACKNOWLEDGE_UNISOLATED_KEY` takes
#: for ``"unisolated"`` — present and refused by name when absent only once
#: the gate has already accepted ``"gvisor"``.
GVISOR_RUNTIME_ROOT_KEY: Final[str] = "gvisor_runtime_root"
GVISOR_STATE_ROOT_KEY: Final[str] = "gvisor_state_root"
LAKE_ROOTS_KEY: Final[str] = "lake_roots"

#: The OCI runtime gVisor ships — the binary ``"gvisor"`` demands on
#: ``PATH``.  The same spelling as the sandbox member's own
#: ``GVISOR_RUNTIME`` constant, local to this module because the member
#: is not this one's dependency; the binary's name is not a fact two
#: spellings of it could drift on.
GVISOR_RUNTIME: Final[str] = "runsc"

#: The binary ``"unisolated"`` is gated on — ``bug_spec_unisolated_os_boundary.xml``
#: (SEC-1): the bare-subprocess path this runtime used to mean had only a
#: bypassable Python import guard between agent code and the host, so
#: ``"unisolated"`` now demands bwrap on the same terms ``"gvisor"`` demands
#: ``runsc`` — there is no bare-subprocess fallback.  The same spelling as
#: :data:`orchestrator._hardened_sandbox.BWRAP_BINARY`, local to this module
#: for the reason :data:`GVISOR_RUNTIME` already states for its own binary.
BWRAP_RUNTIME: Final[str] = "bwrap"

#: The name a missing ``runsc`` refusal carries — the spec's own word
#: for what is missing, the one refusal in this module that names a
#: condition rather than a key.
ISOLATION_REQUIRED: Final[str] = "isolation_required"

#: The stream the closes are read from — §4.2's daily candle stream, the
#: same stream the evaluator's roster resolution reads (its own
#: ``ROSTER_STREAM``), spelled here because the snapshot layout names it
#: and this module walks it directly.
BARS_STREAM: Final[str] = "bars"

#: The optional key bounding how many trailing days of sealed bars one
#: rebalance date's window carries, per symbol.  bug_spec_evaluation_throughput.xml:
#: without a bound, a 2026 date on a 2019-on archive materializes its
#: *entire* history (about 150k rows) into the sandbox, because nothing
#: limited the depth. Optional, unlike :data:`REQUIRED_KEYS` — a document
#: that omits it gets :data:`DEFAULT_MAX_HISTORY_DAYS` rather than a
#: refusal, since "cap a window's depth" is a performance knob a
#: deployment may never need to touch, not a fact every run must state.
MAX_HISTORY_DAYS_KEY: Final[str] = "max_history_days"

#: The trailing-day depth :func:`orchestrator._evaluate._materialize_from_context`
#: bounds a window to when the document carries no :data:`MAX_HISTORY_DAYS_KEY`.
DEFAULT_MAX_HISTORY_DAYS: Final[int] = 400

#: The optional key bounding how many evaluations — a root, or a round's
#: child — ``orchestrator._campaign`` runs at once, each in its own
#: sandbox.  bug_spec_evaluation_throughput.xml, bug 2: a campaign used to
#: evaluate every node one at a time regardless of the host's core count,
#: because nothing bounded (or raised) the concurrency at all.  Optional,
#: the same stance :data:`MAX_HISTORY_DAYS_KEY` already takes for its own
#: performance knob: a document that omits it gets
#: :data:`DEFAULT_EVALUATION_WORKERS` rather than a refusal, since "how many
#: sandboxes run at once" is a throughput knob a deployment may never need
#: to touch.
EVALUATION_WORKERS_KEY: Final[str] = "evaluation_workers"

#: :data:`EVALUATION_WORKERS_KEY`'s default when the document omits it.
DEFAULT_EVALUATION_WORKERS: Final[int] = 4

#: :data:`EVALUATION_WORKERS_KEY`'s inclusive bounds.  Below
#: :data:`MIN_EVALUATION_WORKERS` is not a thread count; above
#: :data:`MAX_EVALUATION_WORKERS` is a concurrency this configuration
#: document is not trusted to set for a host whose core count it was never
#: told — the ceiling is a deliberate cap on gVisor containers started at
#: once, not a number a deployment is expected to reach for every host.
MIN_EVALUATION_WORKERS: Final[int] = 1
MAX_EVALUATION_WORKERS: Final[int] = 16

#: The optional key choosing which evaluator ``build_live_evaluator``
#: answers: ``"process"`` (the default) dispatches every node to a worker
#: process in :class:`orchestrator._process_pool.ProcessEvaluator`'s pool,
#: so a campaign's evaluation work spends as many cores as
#: :data:`EVALUATION_WORKERS_KEY` names instead of one GIL; ``"thread"``
#: keeps today's in-process :class:`~orchestrator.LiveEvaluator`, every
#: evaluation run on the parent's own interpreter.
#: bug_spec_evaluation_throughput.xml bug 2 already bounded a thread
#: pool's slot count, but every slot still ran its window materialization,
#: its metrics and its tripwire probes on that one interpreter's GIL — a
#: pool of threads helps a sandboxed subprocess's own wall-clock wait, but
#: not the CPU-bound Python either side of it. Optional, the same stance
#: :data:`MAX_HISTORY_DAYS_KEY` and :data:`EVALUATION_WORKERS_KEY` already
#: take for their own knobs: a document that omits it gets
#: :data:`DEFAULT_EVALUATION_MODE` rather than a refusal.
EVALUATION_MODE_KEY: Final[str] = "evaluation_mode"

#: The two modes :data:`EVALUATION_MODE_KEY` accepts — closed, like
#: :data:`SANDBOX_RUNTIMES`: a third spelling is refused by name rather
#: than silently read as one of the two.
EVALUATION_MODES: Final[tuple[str, str]] = ("process", "thread")

#: :data:`EVALUATION_MODE_KEY`'s default when the document omits it — the
#: spec's own words, ``evaluation_mode: "process" (the default)``.
DEFAULT_EVALUATION_MODE: Final[str] = "process"

#: The optional key naming the out-of-sample evaluation grid —
#: additions_spec_m2_baseline_financial_worlds.xml feature 1.  Absent means
#: no OOS window: :func:`orchestrator._evaluate.evaluate_on_dates` has no
#: grid to run, and a caller reports OOS as unavailable rather than
#: inventing one.  Present, it is validated like :data:`REQUIRED_KEYS`'s own
#: ``evaluation_dates`` (the extended ISO spelling, round-tripped) plus two
#: rules the in-sample grid does not need (see :func:`_oos_dates`): sorted
#: and de-duplicated, and every date strictly after the in-sample window's
#: own embargo, so an OOS forward return can never reach back into a bar the
#: in-sample window's forward returns already covered.
OOS_DATES_KEY: Final[str] = "oos_dates"

#: Test-only environment variable naming a stub signal executor as
#: ``"<path-to-.py-file>:<zero-arg-factory-name>"`` — read directly off
#: the environment (never the JSON document's closed vocabulary, so it
#: can never ride in as a deployment's own configured key) and consulted
#: by :func:`signal_sandbox` before its two real branches. A worker
#: process :class:`~orchestrator._process_pool.ProcessEvaluator` spawns
#: under the ``spawn`` context is a fresh interpreter a parent's
#: monkeypatch cannot reach — this is the one seam a test can use instead,
#: threaded through :func:`load_evaluation_context`'s own explicit ``env``
#: so the worker's :class:`EvaluationContext` carries it identically to
#: the parent's.  Loaded by file path
#: (:func:`importlib.util.spec_from_file_location`, the same by-path
#: loading this workspace's own test suites already use for a migration
#: module) rather than by dotted import, so the stub resolves regardless
#: of the worker's own ``sys.path``.
TEST_STUB_SANDBOX_ENV: Final[str] = "NULLIUS_TEST_STUB_SANDBOX"


class EvaluationConfigError(Exception):
    """The live evaluation's configuration cannot be loaded.

    Raised by :func:`load_evaluation_context` for every configured-but-
    broken shape: a file that cannot be read or is not a JSON object, a
    key outside :data:`REQUIRED_KEYS` (and
    :data:`ACKNOWLEDGE_UNISOLATED_KEY`), a missing key — there is no
    default for any of them — a malformed value, a ``sandbox_runtime``
    that is neither runtime, an ``"unisolated"`` without its
    acknowledgement, a ``"gvisor"`` with no ``runsc`` on ``PATH``
    (naming :data:`ISOLATION_REQUIRED`), and the environment's own gaps
    (``DATABASE_URL`` unset, an unpinned or misconfigured evaluator
    image), the Z0 members' refusals translated in with their causes
    chained.  Every message opens with :data:`EVALUATION_CONFIG_CODE`
    and names the key or variable at fault, so an operator's next action
    is the message's last noun.
    """


@dataclass(frozen=True)
class EvaluationContext:
    """The inputs one live evaluation runs on, loaded and immutable.

    Built only by :func:`load_evaluation_context`, which validates every
    field before constructing the record — so a context that exists is a
    context whose parts agree: the hashes name the very snapshot, cost
    model and evaluator the handles point at, the closes were read
    through the mount the hash covers, and the sandbox gate answered.
    Frozen because the whole point of loading provenance in one object
    is that it cannot be edited between the load and the charge: a
    context mutated mid-campaign would stamp scores with an identity
    their own inputs no longer support.

    The fields are ``_run_pipeline``'s own inputs (``snapshot`` for the
    resolution, ``closes``, ``cost_model``, ``cost_schedule``) plus the
    identity triple those bytes resolve to, the charge's epoch, the
    store and artifact addresses, and the run parameters the chain
    consumes (``seed``, ``horizon``, ``evaluation_dates``) — and
    ``sandbox_runtime``, which feature 7 reads to decide whether each
    evaluation warns that it runs unisolated.
    """

    #: The sealed snapshot, mounted read-only — the handle
    #: :func:`evaluator.resolve_window` slices and feature 7's
    #: materializer reads through.  A :class:`snapshot.SnapshotMount`.
    snapshot: SnapshotMount
    #: ``{symbol: {bar date: close}}`` — step 4's ``closes`` argument, a
    #: lazy view over the mounted ``bars`` partitions as finite positive
    #: floats, read and memoized one symbol-day at a time on first use
    #: (see :class:`_LazyCloses`), so one context's evaluations all align
    #: over the same sealed bytes without paying for a partition no
    #: evaluation ever asks for.
    closes: Mapping[str, Mapping[dt.date, float]]
    #: The loaded cost model — feature 59's resolved
    #: :class:`cost_model.CostModelConfig`, the value step 7's
    #: ``cost_model`` argument stamps its post-cost series with.
    cost_model: CostModelConfig
    #: The venue's resolved :class:`cost_model.FeeSchedule` — feature
    #: 61's schedule, resolved through the process's one claimed fee
    #: implementation, never a second fee arithmetic.
    cost_schedule: FeeSchedule
    #: §14.1's first provenance axis — the evaluator member's own hash
    #: over the pinned image digest and the resolved configuration.
    evaluator_hash: str
    #: §14.1's second axis — the full 64-hex ``snapshot_hash`` the
    #: mounted directory's ``MANIFEST.json`` carries.
    snapshot_hash: str
    #: §14.1's third axis — the hash folded from the very cost-model
    #: parse :attr:`cost_model` was resolved from (feature 60).
    cost_model_hash: str
    #: The sequestered epoch every charge of this campaign is booked
    #: against (feature 88) — a non-blank string, opaque to this member.
    epoch_id: str
    #: The relational store's address — the workspace-wide
    #: ``DATABASE_URL`` spelling, never a credential from the file.
    database_url: str
    #: Where this campaign's evaluation artifacts land — the
    #: ``artifact_dir`` key's own value, as a path.
    artifact_dir: Path
    #: The signal's only source of randomness — step 2's ``seed``.
    seed: int
    #: The forward-return horizon the evaluation measures, in bars.
    horizon: int
    #: The rebalance grid — step 2's ``rebalance_dates``, as parsed
    #: calendar dates in the document's own order.
    evaluation_dates: tuple[dt.date, ...]
    #: The canonical runtime the gate accepted: ``"gvisor"`` (with
    #: ``runsc`` verified on ``PATH``) or ``"unisolated"`` (with the
    #: document's acknowledgement).
    sandbox_runtime: str
    #: The read-only gVisor runtime root :func:`signal_sandbox` builds a
    #: :class:`~orchestrator._gvisor.GVisorSandbox` over — required (and
    #: refused by name when missing) only when ``sandbox_runtime`` is
    #: ``"gvisor"``; ``None`` for ``"unisolated"``, where no executor reads it.
    gvisor_runtime_root: Path | None = None
    #: Where that executor keeps ``runsc``'s per-container state — the same
    #: conditional shape as ``gvisor_runtime_root``.
    gvisor_state_root: Path | None = None
    #: The data lake roots a gVisor bundle must never mount under (feature
    #: 4's own refusal) — a possibly-empty tuple, required only when
    #: ``sandbox_runtime`` is ``"gvisor"``; empty for ``"unisolated"``.
    lake_roots: tuple[Path, ...] = ()
    #: How many trailing days of sealed bars each rebalance date's window
    #: carries, per symbol — read from the optional
    #: :data:`MAX_HISTORY_DAYS_KEY` (:data:`DEFAULT_MAX_HISTORY_DAYS` when
    #: absent). :func:`orchestrator._evaluate._materialize_from_context` is
    #: the one reader: a partition dated at or before
    #: ``decision_date - max_history_days`` is never read for that date, so
    #: a late date on a long-lived snapshot pays for this many trailing
    #: days, not the snapshot's entire history.
    max_history_days: int = DEFAULT_MAX_HISTORY_DAYS
    #: How many evaluations — a root, or a round's child — run concurrently,
    #: each in its own sandbox.  Read from the optional
    #: :data:`EVALUATION_WORKERS_KEY` (:data:`DEFAULT_EVALUATION_WORKERS`
    #: when absent), bounded to :data:`MIN_EVALUATION_WORKERS`..
    #: :data:`MAX_EVALUATION_WORKERS`.  ``orchestrator._campaign`` is the one
    #: reader: it bounds its root-evaluation and round-dispatch thread pools
    #: to this many slots, never more.
    evaluation_workers: int = DEFAULT_EVALUATION_WORKERS
    #: Which evaluator ``build_live_evaluator`` answers for this process —
    #: ``"process"`` (the default) or ``"thread"``.  Read from the
    #: optional :data:`EVALUATION_MODE_KEY` (:data:`DEFAULT_EVALUATION_MODE`
    #: when absent).
    evaluation_mode: str = DEFAULT_EVALUATION_MODE
    #: :data:`TEST_STUB_SANDBOX_ENV`'s value, or ``None`` — read once at
    #: load time from the same environment every other variable in this
    #: module reads from, never the JSON document.  :func:`signal_sandbox`'s
    #: one hook for a process-pool test that cannot monkeypatch across a
    #: spawned worker's own process boundary.
    test_stub_sandbox: str | None = None
    #: The out-of-sample grid, read from the optional :data:`OOS_DATES_KEY`
    #: — an empty tuple when the document omits it, which means *no OOS
    #: window* rather than an invented one.
    #: :func:`orchestrator._evaluate.evaluate_on_dates` is the one reader.
    oos_dates: tuple[dt.date, ...] = ()


def load_evaluation_context(
    env: Mapping[str, str] | None = None,
) -> EvaluationContext | None:
    """Load the live evaluation inputs, or answer ``None`` when unconfigured.

    Reads ``NULLIUS_EVALUATION_CONFIG`` from ``env`` (the process
    environment when it is given none) and loads the JSON file it names;
    an unset or blank variable is the unconfigured state and answers
    ``None`` — composition's state, not an error.  Everything else the
    environment contributes is read through the same mapping, so a test
    or an operator handing an explicit ``env`` gets one environment for
    every input, not a half-redirected seam that passes alone and fails
    in a suite.

    The load is ordered so the safety gate precedes every side effect:
    the document is read and its keys checked (presence, shape, closed
    vocabulary) before the sandbox gate runs, and the gate — ``runsc``
    on the same environment's ``PATH``, or the ``unisolated``
    acknowledgement — before the mount re-asserts its read-only modes,
    the fee implementation is claimed, or a single bar is read.  A
    configuration that would run model code unisolated and unacknowledged
    refuses before touching the filesystem it was about to read.

    Answers the :class:`EvaluationContext` — ``_run_pipeline``'s inputs
    and the identity they resolve to.  Raises
    :class:`EvaluationConfigError` (naming the key or variable at fault)
    for every configured-but-broken shape; nothing is persisted, so a
    refused load leaves no trace in any store.
    """
    source = os.environ if env is None else env
    named = source.get(EVALUATION_CONFIG_ENV)
    if named is None or not named.strip():
        return None

    document = _read_document(Path(named), named)
    _refuse_unknown_keys(document, named)
    values = {key: _required(document, key, named) for key in REQUIRED_KEYS}
    runtime = _sandbox_runtime(values, document, named, source)
    gvisor_runtime_root, gvisor_state_root, lake_roots = _gvisor_inputs(
        document, named, runtime
    )
    dates = _evaluation_dates(values, named)
    horizon = _horizon(values, named)
    seed = _seed(values, named)
    epoch_id = _epoch_id(values, named)
    artifact_dir = _artifact_dir(values, named)
    max_history_days = _max_history_days(document, named)
    evaluation_workers = _evaluation_workers(document, named)
    evaluation_mode = _evaluation_mode(document, named)
    oos_dates = _oos_dates(document, named, dates, horizon)
    test_stub_sandbox = source.get(TEST_STUB_SANDBOX_ENV) or None
    database_url = _database_url(source)

    mount = _mounted_snapshot(values, named)
    symbols = _bars_symbols(mount, named)
    manifest = _read_manifest(mount, named)
    _refuse_duplicate_bars(manifest, named)
    snapshot_hash = manifest.snapshot_hash
    closes = _LazyCloses(mount, snapshot_hash, symbols)
    cost_model, cost_schedule, cost_model_hash = _cost_inputs(
        source, database_url
    )
    evaluator_hash = _evaluator_hash(source)

    return EvaluationContext(
        snapshot=mount,
        closes=closes,
        cost_model=cost_model,
        cost_schedule=cost_schedule,
        evaluator_hash=evaluator_hash,
        snapshot_hash=snapshot_hash,
        cost_model_hash=cost_model_hash,
        epoch_id=epoch_id,
        database_url=database_url,
        artifact_dir=artifact_dir,
        seed=seed,
        horizon=horizon,
        evaluation_dates=dates,
        sandbox_runtime=runtime,
        gvisor_runtime_root=gvisor_runtime_root,
        gvisor_state_root=gvisor_state_root,
        lake_roots=lake_roots,
        max_history_days=max_history_days,
        evaluation_workers=evaluation_workers,
        evaluation_mode=evaluation_mode,
        test_stub_sandbox=test_stub_sandbox,
        oos_dates=oos_dates,
    )


# -- The document --------------------------------------------------------------


def _read_document(path: Path, named: str) -> Mapping[str, Any]:
    """Read and parse the configured file, refusing what cannot be read.

    The two failures a file can offer — unreadable bytes, and bytes that
    are not a JSON object — are both refused here rather than left to
    surface as an ``OSError`` or a ``TypeError`` mid-load, so the first
    thing an operator learns about a broken configuration is a
    configuration error naming the variable that pointed at it.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: {EVALUATION_CONFIG_ENV} names the "
            f"file {named!r}, which cannot be read: {exc}; the evaluation "
            "configuration is where a live run starts, so a file that "
            "cannot be read is a run that cannot start — point the "
            "variable at the campaign's configuration document"
        ) from exc
    try:
        document = json.loads(text)
    except ValueError as exc:
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: {EVALUATION_CONFIG_ENV} names the "
            f"file {named!r}, which is not valid JSON: {exc}; a partially "
            "parsed configuration is refused rather than read past, "
            "because a run configured by half a document is one whose "
            "file and whose evaluation disagree"
        ) from exc
    if not isinstance(document, dict):
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: {EVALUATION_CONFIG_ENV} names the "
            f"file {named!r}, which holds {type(document).__name__} and "
            "not a JSON object; the evaluation configuration is seven "
            f"keys ({', '.join(REQUIRED_KEYS)}), and only an object can "
            "carry them"
        )
    return document


def _refuse_unknown_keys(document: Mapping[str, Any], named: str) -> None:
    """Refuse a key the configuration does not define.

    The vocabulary is closed because the file must never hold a
    credential: a loader that read past an unknown key would accept a
    sidecar key reference, an API token or a database password riding
    under a name it silently ignored, and "never" would be a comment
    rather than a property.  Every key the loader does not define is
    refused by name — the seven of :data:`REQUIRED_KEYS`, the one
    conditional :data:`ACKNOWLEDGE_UNISOLATED_KEY`, and nothing else.
    """
    allowed = frozenset(
        REQUIRED_KEYS
        + (
            ACKNOWLEDGE_UNISOLATED_KEY,
            GVISOR_RUNTIME_ROOT_KEY,
            GVISOR_STATE_ROOT_KEY,
            LAKE_ROOTS_KEY,
            MAX_HISTORY_DAYS_KEY,
            EVALUATION_WORKERS_KEY,
            EVALUATION_MODE_KEY,
            OOS_DATES_KEY,
        )
    )
    for key in document:
        if key not in allowed:
            raise EvaluationConfigError(
                f"{EVALUATION_CONFIG_CODE}: {key!r} is not a key of the "
                f"evaluation configuration at {named!r} (the keys are "
                f"{', '.join(REQUIRED_KEYS)}, plus "
                f"{ACKNOWLEDGE_UNISOLATED_KEY!r} when the runtime is "
                f"unisolated, {GVISOR_RUNTIME_ROOT_KEY!r}, "
                f"{GVISOR_STATE_ROOT_KEY!r} and {LAKE_ROOTS_KEY!r} when it "
                f"is gvisor, and the always-optional {MAX_HISTORY_DAYS_KEY!r}, "
                f"{EVALUATION_WORKERS_KEY!r}, {EVALUATION_MODE_KEY!r} and "
                f"{OOS_DATES_KEY!r}); "
                "the file never holds a credential — every "
                "key is one the loader defines, and an unknown key is "
                "refused rather than read past. Credentials live where "
                "the members already read them: the sidecar key in "
                "NULL_SIDECAR_KEY_REF (the nulloracle member's, never "
                "this one's), the store in DATABASE_URL"
            )


def _required(document: Mapping[str, Any], key: str, named: str) -> Any:
    """One key's value, refused when absent — there is no default.

    The spec's own rule: *"There is no default: a missing key is
    refused."*  A defaulted key would be worse than a crash — a missing
    ``sandbox_runtime`` silently read as ``"gvisor"`` would assert an
    isolation nobody configured, and a missing ``epoch_id`` would book
    charges against an epoch invented at read time.
    """
    if key not in document:
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: {key!r} is missing from the "
            f"evaluation configuration at {named!r}; there is no default "
            "— the seven keys are the run, and one that is absent is a "
            "run that has not been configured, not one to be guessed"
        )
    return document[key]


# -- The scalar keys -----------------------------------------------------------


def _evaluation_dates(values: Mapping[str, Any], named: str) -> tuple[dt.date, ...]:
    """The rebalance grid, as parsed calendar dates.

    The extended ISO spelling ``YYYY-MM-DD`` only, checked by
    round-trip: ``date.fromisoformat`` also accepts the basic
    ``20261005`` spelling, and a grid whose dates parse but whose
    spellings vary is a document two tools read two ways.  The document's
    order is kept — it is the grid's order — and an empty grid is
    refused: an evaluation with no dates evaluates nothing, which is a
    configuration mistake and not a quiet no-op.
    """
    raw = values["evaluation_dates"]
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: evaluation_dates must be a list "
            f"of ISO dates, got {type(raw).__name__}; the grid is the "
            "rebalance dates step 2 scores one vector per — a single "
            "date or a string of dates is not a grid"
        )
    if not raw:
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: evaluation_dates is empty; a "
            f"campaign that evaluates no dates is a configuration "
            "mistake, not a quiet no-op — name the rebalance grid"
        )
    dates: list[dt.date] = []
    for spelling in raw:
        if not isinstance(spelling, str):
            raise EvaluationConfigError(
                f"{EVALUATION_CONFIG_CODE}: evaluation_dates must hold "
                f"ISO date strings, got {spelling!r} "
                f"({type(spelling).__name__})"
            )
        try:
            day = dt.date.fromisoformat(spelling.strip())
        except ValueError as exc:
            raise EvaluationConfigError(
                f"{EVALUATION_CONFIG_CODE}: evaluation_dates holds "
                f"{spelling!r}, which is not an ISO date (expected "
                "YYYY-MM-DD)"
            ) from exc
        if day.isoformat() != spelling.strip():
            raise EvaluationConfigError(
                f"{EVALUATION_CONFIG_CODE}: evaluation_dates holds "
                f"{spelling!r}, which is not the extended ISO spelling "
                f"YYYY-MM-DD ({day.isoformat()} is the same day written "
                "another way); a document two tools read two ways is a "
                "grid two evaluations could disagree about"
            )
        dates.append(day)
    return tuple(dates)


def _oos_dates(
    document: Mapping[str, Any],
    named: str,
    evaluation_dates: tuple[dt.date, ...],
    horizon: int,
) -> tuple[dt.date, ...]:
    """The optional out-of-sample grid — ``()`` when :data:`OOS_DATES_KEY` is absent.

    additions_spec_m2_baseline_financial_worlds.xml feature 1.  Present, a
    date is validated the way :func:`_evaluation_dates` validates one (the
    extended ISO spelling ``YYYY-MM-DD``, checked by round-trip), plus two
    rules the in-sample grid does not need: the dates must arrive sorted and
    de-duplicated (unlike ``evaluation_dates``, which keeps the document's
    own order, the OOS grid has no other order to keep, so a document that
    wrote it any other way made a mistake worth refusing rather than
    silently re-sorting), and every date must land strictly after the
    in-sample window's own embargo.

    The embargo boundary is ``max(evaluation_dates) + horizon + embargo``,
    counted in calendar days of the bars (this snapshot's bars are daily, so
    a bar and a calendar day are the same step): the in-sample window's last
    rebalance date's own forward return reaches ``horizon`` bars past it,
    and the evaluator's own cross-validation embargo
    (:data:`evaluator.DEFAULT_CONFIG`'s ``embargo_periods``) is the same
    margin this workspace already keeps between a split boundary and the
    training bars that follow it — restated here as calendar days rather
    than grid periods, for the same reason: a bar within it of the in-sample
    window is scored from features or labels that reach back across the
    boundary. An OOS date inside that margin would compute a forward return
    that overlaps bars the in-sample evaluation already used, which is
    exactly the leak an out-of-sample score exists to rule out.

    Refused with :class:`EvaluationConfigError` for every shape
    :func:`_evaluation_dates` already refuses (not a list, an empty list, a
    non-string entry, an unparsable or non-canonical spelling), for a grid
    that is not sorted and de-duplicated, and for a date that does not clear
    the embargo boundary.
    """
    if OOS_DATES_KEY not in document:
        return ()
    raw = document[OOS_DATES_KEY]
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: {OOS_DATES_KEY} must be a list of "
            f"ISO dates, got {type(raw).__name__}; absent means no OOS "
            "window, and a single date or a string of dates is not a grid"
        )
    if not raw:
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: {OOS_DATES_KEY} is empty; an absent "
            f"key is how a configuration states no OOS window — name the "
            f"grid or drop {OOS_DATES_KEY!r} entirely"
        )
    dates: list[dt.date] = []
    for spelling in raw:
        if not isinstance(spelling, str):
            raise EvaluationConfigError(
                f"{EVALUATION_CONFIG_CODE}: {OOS_DATES_KEY} must hold ISO "
                f"date strings, got {spelling!r} ({type(spelling).__name__})"
            )
        try:
            day = dt.date.fromisoformat(spelling.strip())
        except ValueError as exc:
            raise EvaluationConfigError(
                f"{EVALUATION_CONFIG_CODE}: {OOS_DATES_KEY} holds "
                f"{spelling!r}, which is not an ISO date (expected "
                "YYYY-MM-DD)"
            ) from exc
        if day.isoformat() != spelling.strip():
            raise EvaluationConfigError(
                f"{EVALUATION_CONFIG_CODE}: {OOS_DATES_KEY} holds "
                f"{spelling!r}, which is not the extended ISO spelling "
                f"YYYY-MM-DD ({day.isoformat()} is the same day written "
                "another way)"
            )
        dates.append(day)
    if dates != sorted(set(dates)):
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: {OOS_DATES_KEY} must be sorted and "
            "de-duplicated, got "
            f"{[day.isoformat() for day in dates]!r}"
        )

    embargo_days = DEFAULT_CONFIG["embargo_periods"]
    earliest_allowed = max(evaluation_dates) + dt.timedelta(
        days=horizon + embargo_days
    )
    for day in dates:
        if day <= earliest_allowed:
            raise EvaluationConfigError(
                f"{EVALUATION_CONFIG_CODE}: {OOS_DATES_KEY} holds "
                f"{day.isoformat()}, which is not strictly after "
                f"{earliest_allowed.isoformat()} "
                f"(max(evaluation_dates) {max(evaluation_dates).isoformat()} "
                f"+ horizon {horizon} + embargo {embargo_days} calendar "
                "days of the bars); an earlier OOS date would compute a "
                "forward return that overlaps the in-sample window"
            )
    return tuple(dates)


def _horizon(values: Mapping[str, Any], named: str) -> int:
    """The forward-return horizon, a positive integer in bars.

    The horizon vocabulary itself — which horizons the frozen pipeline
    measures — is the evaluator's own (:data:`evaluator.HORIZONS`), and
    this loader does not re-implement it: a horizon the pipeline refuses
    is refused by the pipeline, with its own message.  What loading
    checks is the shape a JSON document can get wrong — a string, a
    float, a boolean — because those never reach the pipeline's refusal
    as anything but a crash.
    """
    raw = values["horizon"]
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: horizon must be a positive "
            f"integer (a count of bars), got {raw!r} "
            f"({type(raw).__name__})"
        )
    return raw


def _seed(values: Mapping[str, Any], named: str) -> int:
    """The signal's seed — an integer, opaque to this module.

    The seed is the one source of randomness a signal gets and the one
    term determinism (§12) turns on, so its type is checked where it is
    loaded rather than where the sandbox first uses it: a JSON ``5.0``
    or ``"5"`` would otherwise surface as a ``TypeError`` inside an
    evaluation, looking like a signal defect instead of a document one.
    """
    raw = values["seed"]
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: seed must be an integer, got "
            f"{raw!r} ({type(raw).__name__}); the seed is the signal's "
            "one source of randomness and the term replay turns on — "
            "an opaque integer, never a float or a string"
        )
    return raw


def _epoch_id(values: Mapping[str, Any], named: str) -> str:
    """The sequestered epoch's identifier, a non-blank string.

    The spec's own named refusal: *"an epoch_id that is not a non-blank
    string raises EvaluationConfigError naming the key"*.  Opaque to
    this member beyond that — which epoch a campaign belongs to is the
    holdout's vocabulary, and a loader that validated it would be a
    second spelling of feature 88's law.
    """
    raw = values["epoch_id"]
    if not isinstance(raw, str) or not raw.strip():
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: epoch_id must be a non-blank "
            f"string, got {raw!r} ({type(raw).__name__}); every charge "
            "of the campaign is booked against the epoch this key "
            "names, and a blank one books against nothing"
        )
    return raw


def _artifact_dir(values: Mapping[str, Any], named: str) -> Path:
    """Where the campaign's artifacts land, as a path.

    Held, not created: creating directories is a write, and a load that
    wrote would leave a trace from a configuration that may still be
    refused one key later.  The writer that needs the directory makes
    it; the context only names it.
    """
    raw = values["artifact_dir"]
    if not isinstance(raw, str) or not raw.strip():
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: artifact_dir must be a non-blank "
            f"path string, got {raw!r} ({type(raw).__name__})"
        )
    return Path(raw)


def _max_history_days(document: Mapping[str, Any], named: str) -> int:
    """The trailing-day depth a window is bounded to — optional, unlike
    :data:`REQUIRED_KEYS`.

    :data:`DEFAULT_MAX_HISTORY_DAYS` when :data:`MAX_HISTORY_DAYS_KEY` is
    absent — the one key this module defaults rather than refuses, because
    bounding a window's depth is a performance knob, not a fact every run
    must state.  A present value is still a positive integer, refused by
    name otherwise (:data:`MAX_HISTORY_DAYS_KEY`): a non-positive cap
    bounds a rebalance date's window to nothing or less, which starves
    every signal rather than merely limiting its lookback.
    """
    if MAX_HISTORY_DAYS_KEY not in document:
        return DEFAULT_MAX_HISTORY_DAYS
    raw = document[MAX_HISTORY_DAYS_KEY]
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: {MAX_HISTORY_DAYS_KEY} must be a "
            f"positive integer (a count of trailing days), got {raw!r} "
            f"({type(raw).__name__}); a non-positive cap bounds a "
            "rebalance date's window to nothing or less, which starves "
            "every signal rather than merely limiting its lookback"
        )
    return raw


def _evaluation_workers(document: Mapping[str, Any], named: str) -> int:
    """How many evaluations run concurrently — optional, unlike
    :data:`REQUIRED_KEYS`.

    :data:`DEFAULT_EVALUATION_WORKERS` when :data:`EVALUATION_WORKERS_KEY`
    is absent.  A present value outside
    :data:`MIN_EVALUATION_WORKERS`..\\ :data:`MAX_EVALUATION_WORKERS` is
    refused by name: this is how many sandboxes ``orchestrator._campaign``
    runs at once, not an exploration width, so a value below one is not a
    thread count and a value above the ceiling is a concurrency this
    document is not trusted to set for a host whose core count it was
    never told.
    """
    if EVALUATION_WORKERS_KEY not in document:
        return DEFAULT_EVALUATION_WORKERS
    raw = document[EVALUATION_WORKERS_KEY]
    if (
        isinstance(raw, bool)
        or not isinstance(raw, int)
        or not (MIN_EVALUATION_WORKERS <= raw <= MAX_EVALUATION_WORKERS)
    ):
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: {EVALUATION_WORKERS_KEY} must be an "
            f"integer from {MIN_EVALUATION_WORKERS} to "
            f"{MAX_EVALUATION_WORKERS}, got {raw!r} ({type(raw).__name__}); "
            "this bounds how many sandboxes a campaign runs at once, not "
            "an exploration width, and a value outside that range is "
            "refused rather than clamped"
        )
    return raw


def _evaluation_mode(document: Mapping[str, Any], named: str) -> str:
    """Which evaluator ``build_live_evaluator`` answers — optional, unlike
    :data:`REQUIRED_KEYS`.

    :data:`DEFAULT_EVALUATION_MODE` when :data:`EVALUATION_MODE_KEY` is
    absent. A present value outside :data:`EVALUATION_MODES` is refused by
    name: the vocabulary is closed, the same stance :func:`_sandbox_runtime`
    holds for its own two-member set, and for the same reason — a third
    spelling would be guessed rather than chosen.
    """
    if EVALUATION_MODE_KEY not in document:
        return DEFAULT_EVALUATION_MODE
    raw = document[EVALUATION_MODE_KEY]
    if not isinstance(raw, str) or raw not in EVALUATION_MODES:
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: {EVALUATION_MODE_KEY} must be one "
            f"of {', '.join(repr(name) for name in EVALUATION_MODES)}, got "
            f"{raw!r}; this chooses which evaluator build_live_evaluator "
            "answers — a value outside that closed set is refused rather "
            "than guessed"
        )
    return raw


# -- The sandbox gate ---------------------------------------------------------


def _sandbox_runtime(
    values: Mapping[str, Any],
    document: Mapping[str, Any],
    named: str,
    source: Mapping[str, str],
) -> str:
    """Accept the configured runtime — or refuse, before anything is touched.

    ``"gvisor"`` demands the ``runsc`` binary on the ``PATH`` the same
    environment names (the process's when ``env`` was omitted — the
    environment that loads the configuration is the environment that
    would run the code), looked up fresh through :func:`shutil.which`
    and never cached.  ``"unisolated"`` demands the document's explicit
    ``acknowledge_unisolated: true`` *and* the ``bwrap`` binary on that
    same ``PATH`` (``bug_spec_unisolated_os_boundary.xml``, SEC-1): the
    acknowledgement alone no longer suffices, because the runtime it
    acknowledges runs model-written code inside a bwrap sandbox now, not
    a bare subprocess, and there is no bare-subprocess fallback to fall
    back to when bwrap is missing.  Both comparisons casefold, and the
    canonical lowercase spelling is what the context carries.
    """
    raw = values["sandbox_runtime"]
    if not isinstance(raw, str):
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: sandbox_runtime must be one of "
            f"{', '.join(repr(name) for name in SANDBOX_RUNTIMES)}, got "
            f"{raw!r} ({type(raw).__name__})"
        )
    runtime = raw.strip().casefold()
    if runtime not in SANDBOX_RUNTIMES:
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: sandbox_runtime must be one of "
            f"{', '.join(repr(name) for name in SANDBOX_RUNTIMES)}, got "
            f"{raw!r}; there is no default and no third runtime — a "
            "gVisor executor is a later spec, and everything else would "
            "run model-written code on the host while calling it "
            "isolated"
        )
    if runtime == "gvisor":
        search = source.get("PATH", "")
        if shutil.which(GVISOR_RUNTIME, path=search) is None:
            raise EvaluationConfigError(
                f"{EVALUATION_CONFIG_CODE}: {ISOLATION_REQUIRED} — "
                f"sandbox_runtime is 'gvisor', which runs model-written "
                f"code under gVisor, and the {GVISOR_RUNTIME!r} binary "
                "is not on the PATH this environment names; install "
                "gVisor's runsc in the deployment, or — only where the "
                "risk is owned — set sandbox_runtime to 'unisolated' "
                f"with {ACKNOWLEDGE_UNISOLATED_KEY}: true in the "
                "configuration. Live evaluation refuses to start "
                "without one or the other (feature 157: 'LLM-authored "
                "code is untrusted code. Treat it that way.')"
            )
        return runtime
    acknowledged = document.get(ACKNOWLEDGE_UNISOLATED_KEY)
    if acknowledged is not True:
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: {ACKNOWLEDGE_UNISOLATED_KEY!r} "
            f"must be true when sandbox_runtime is 'unisolated', got "
            f"{acknowledged!r}; the acknowledgement is the operator "
            "stating in the artifact that outlives the process that "
            "model-written code will run on the host — a missing or "
            "false one is refused rather than warned, because a warning "
            "scrolls past and an unisolated run does not"
        )
    search = source.get("PATH", "")
    if shutil.which(BWRAP_RUNTIME, path=search) is None:
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: {ISOLATION_REQUIRED} — "
            f"sandbox_runtime is 'unisolated', which still runs "
            f"model-written code inside a bwrap (bubblewrap) sandbox — "
            "the only OS boundary this runtime has "
            "(bug_spec_unisolated_os_boundary.xml: a bare-subprocess "
            "executor trusts a Python import guard that allowlisted "
            "modules re-export around) — and the "
            f"{BWRAP_RUNTIME!r} binary is not on the PATH this "
            "environment names; install bubblewrap in the deployment, "
            "or set sandbox_runtime to 'gvisor' instead. There is no "
            "bare-subprocess fallback."
        )
    return runtime


def _gvisor_inputs(
    document: Mapping[str, Any], named: str, runtime: str
) -> tuple[Path | None, Path | None, tuple[Path, ...]]:
    """``gvisor_runtime_root``, ``gvisor_state_root`` and ``lake_roots`` — or
    ``(None, None, ())`` for ``"unisolated"``, which builds no executor that
    reads them.

    Checked immediately after the gate accepts ``runtime``, before a single
    byte of the snapshot or the cost model is touched — the same "the gate
    precedes every read" ordering :func:`_sandbox_runtime` itself holds, so
    a ``"gvisor"`` configuration missing one of these three still refuses
    before the mount is reached.
    """
    if runtime != "gvisor":
        return None, None, ()
    runtime_root = _gvisor_path(document, named, GVISOR_RUNTIME_ROOT_KEY)
    state_root = _gvisor_path(document, named, GVISOR_STATE_ROOT_KEY)
    lake_roots = _lake_roots(document, named)
    return runtime_root, state_root, lake_roots


def _gvisor_path(document: Mapping[str, Any], named: str, key: str) -> Path:
    """One gVisor-only path key: a non-blank string, refused by name when
    missing or malformed — there is no default once ``"gvisor"`` is chosen.
    """
    if key not in document:
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: {key!r} is missing from the "
            f"evaluation configuration at {named!r}; sandbox_runtime is "
            f"'gvisor', which needs {key!r} to build the executor "
            "(orchestrator._context.signal_sandbox), and there is no default"
        )
    raw = document[key]
    if not isinstance(raw, str) or not raw.strip():
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: {key!r} must be a non-blank path "
            f"string, got {raw!r} ({type(raw).__name__})"
        )
    return Path(raw)


def _lake_roots(document: Mapping[str, Any], named: str) -> tuple[Path, ...]:
    """``lake_roots``: a list of path strings (possibly empty), refused by
    name when missing or malformed.  The gVisor bundle (feature 4) refuses
    any mount under one of these, so a missing list is a missing guarantee
    — not a default an executor could fall back to.
    """
    key = LAKE_ROOTS_KEY
    if key not in document:
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: {key!r} is missing from the "
            f"evaluation configuration at {named!r}; sandbox_runtime is "
            f"'gvisor', which needs {key!r} to build the executor "
            "(orchestrator._context.signal_sandbox), and there is no default"
        )
    raw = document[key]
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: {key!r} must be a list of path "
            f"strings, got {type(raw).__name__}"
        )
    roots: list[Path] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise EvaluationConfigError(
                f"{EVALUATION_CONFIG_CODE}: {key!r} must hold non-blank "
                f"path strings, got {item!r} ({type(item).__name__})"
            )
        roots.append(Path(item))
    return tuple(roots)


# -- The environment ----------------------------------------------------------


def _database_url(source: Mapping[str, str]) -> str:
    """The relational store's address, from the variable members already read.

    Blank counts as unset — the treatment the rest of the workspace
    gives an empty environment variable — and unset is refused here
    rather than deferred to the first store that opens, because the
    context is the one place the address is named: a deployment that
    cannot say where its rows land should learn it at load, not at the
    first charge.
    """
    raw = source.get("DATABASE_URL")
    if raw is None or not raw.strip():
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: DATABASE_URL is not set; the "
            "evaluation context names the store the node rows and the "
            "trial ledger land in, and a live run without one has "
            "nowhere to persist what it evaluates — set it to the "
            "deployment's relational store"
        )
    return raw


def _evaluator_hash(source: Mapping[str, str]) -> str:
    """§14.1's first axis, computed by the evaluator member's own service.

    :meth:`evaluator.EvaluatorService.identity` folds the pinned image
    (``NULLIUS_EVALUATOR_IMAGE``) and the resolved configuration
    (``NULLIUS_EVALUATOR_CONFIG`` over the defaults) — the member's own
    formula, so the hash a live run stamps is the hash the member would
    compute, never a re-implementation beside it.  Computed, not
    recorded: recording is a write, and loading writes nothing.  The
    member's refusals — an unset or tag-only image, an unparseable
    override — already name their variable; they are translated here so
    one seam answers with one error type, the cause chained.
    """
    try:
        return EvaluatorService.from_env(source).identity().evaluator_hash
    except (EvaluatorImageError, EvaluatorConfigError) as exc:
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: the evaluator identity could not "
            f"be resolved from the environment: {exc}"
        ) from exc


# -- The snapshot and its closes ----------------------------------------------


def _mounted_snapshot(
    values: Mapping[str, Any], named: str
) -> SnapshotMount:
    """Mount the configured snapshot directory, read-only.

    ``snapshot_mount`` is a path — the sealed snapshot directory itself
    (``<lake>/snapshots/<sealed_at>_<hash prefix>``), which is what a
    campaign's configuration holds and what
    :meth:`snapshot.SnapshotMount.for_directory` is for: the seam for a
    caller that holds a path rather than a lake and a name.  Mounting
    re-asserts the sealed modes (it can only tighten them) and refuses a
    directory that is not a sealed snapshot; both are the snapshot
    member's own laws, translated into this module's one error with the
    member's message intact.
    """
    raw = values["snapshot_mount"]
    if not isinstance(raw, str) or not raw.strip():
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: snapshot_mount must be a "
            f"non-blank path string naming the sealed snapshot "
            f"directory, got {raw!r} ({type(raw).__name__})"
        )
    try:
        return SnapshotMount.for_directory(raw)
    except (SnapshotError, OSError) as exc:
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: snapshot_mount names {raw!r}, "
            f"which does not mount as a sealed snapshot: {exc}; the "
            "evaluation reads the market only through a mounted "
            "snapshot (§4.2), so the configuration must name the "
            "directory the seal published"
        ) from exc


def _read_manifest(mount: SnapshotMount, named: str) -> SnapshotManifest:
    """The sealed manifest, read once — a JSON parse, never a bars read.

    The directory name carries only the first six characters of
    ``snapshot_hash``; the score and the charge carry all sixty-four, so
    the manifest the seal published beside the content is where the
    context reads it.  It is also where the duplicate-bar check
    (:func:`_refuse_duplicate_bars`) reads the per-file row counts the
    seal already computed, which is what lets that refusal fire without
    opening a single bars partition.
    """
    try:
        return SnapshotManifest.from_json_bytes(mount.read_text(MANIFEST_NAME))
    except (SnapshotError, OSError) as exc:
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: snapshot_mount names a snapshot "
            f"whose {MANIFEST_NAME} cannot be read through the mount: "
            f"{exc}; the full snapshot_hash a live run stamps is the "
            "one the seal published, and a mount without it names "
            "content nobody sealed"
        ) from exc


def _bars_symbols(mount: SnapshotMount, named: str) -> tuple[str, ...]:
    """The symbols the snapshot carries bars for — a directory listing,
    never a Parquet read (:meth:`SnapshotMount.partitions`).  Refused when
    the stream is empty: there are no closes to align targets over
    without it.
    """
    symbols = mount.partitions(BARS_STREAM)
    if not symbols:
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: snapshot_mount names a snapshot "
            f"carrying no {BARS_STREAM!r} partitions, so there are no "
            "closes to align targets over — the evaluation's labels are "
            "measured off the sealed bars (§4.2), and a snapshot "
            "without them cannot serve one"
        )
    return symbols


#: One bars partition's relative path, as the manifest's own ``files``
#: keys spell it (``"bars/symbol=SYM00/date=2026-09-01/part-0.parquet"``)
#: — group 1 is the symbol, group 2 the ``date=`` directory's own string.
_BARS_PARTITION_RE = re.compile(
    rf"^{re.escape(BARS_STREAM)}/symbol=([^/]+)/date=([^/]+)/[^/]+$"
)


def _refuse_duplicate_bars(manifest: SnapshotManifest, named: str) -> None:
    """Refuse a symbol-day the manifest's own row counts already show twice.

    The manifest records a row count per file at seal time (feature 31,
    read from the Parquet footer when the seal ran) — reading it back
    here costs nothing a JSON parse has not already cost, so "one bar,
    one close" is checked at load, across every partition, without
    opening one.  A file whose row count the manifest could not take
    (``None``) is skipped here; :func:`_read_close` re-applies the same
    check the moment it actually opens that partition, so no duplicate
    escapes for the files this free check could not see into.
    """
    totals: dict[tuple[str, str], int] = {}
    for path, entry in manifest.files.items():
        match = _BARS_PARTITION_RE.match(path)
        if match is None or entry.row_count is None:
            continue
        key = (match.group(1), match.group(2))
        totals[key] = totals.get(key, 0) + entry.row_count
    for (symbol, iso), count in totals.items():
        if count <= 1:
            continue
        try:
            day = dt.date.fromisoformat(iso)
        except ValueError:
            continue
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: snapshot_mount names a snapshot "
            f"whose bars carry {symbol!r} on {day.isoformat()} twice; one "
            "bar, one close — the aligner's grain, and a snapshot that "
            "carries two has a staging defect a silent merge would hide"
        )


#: Prices already read, keyed by the exact snapshot, symbol and bar day
#: they belong to.  Module-level and never cleared: a second evaluation
#: over the same snapshot in the same process — even through a freshly
#: loaded context, since feature 8 composes one per ``create_app()`` —
#: finds every close it already paid to read, and reads no partition
#: twice.
_CLOSE_CACHE: dict[tuple[str, str, dt.date], float] = {}
#: Serializes cache misses, so concurrent node evaluations never read the same
#: close twice (with 8 workers every node missed at once and the archive's
#: 139k closes were read about 8 times over).
_CLOSE_LOCK = threading.Lock()


class _LazySymbolCloses(Mapping[dt.date, float]):
    """One symbol's closes — read and memoized one bar at a time.

    The dates this maps are a directory listing
    (:meth:`SnapshotMount.dates`, free), fetched once and cached on the
    instance; the *prices* are read only when a date is actually looked
    up, through :func:`_read_close` — which is where the poisoned-close
    and duplicate-bar refusals a symbol's own partitions can still raise
    now fire: at first use, not at load.
    """

    __slots__ = ("_dates", "_mount", "_snapshot_hash", "_symbol")

    def __init__(
        self, mount: SnapshotMount, snapshot_hash: str, symbol: str
    ) -> None:
        self._mount = mount
        self._snapshot_hash = snapshot_hash
        self._symbol = symbol
        self._dates: tuple[dt.date, ...] | None = None

    def _available(self) -> tuple[dt.date, ...]:
        if self._dates is None:
            self._dates = tuple(
                dt.date.fromisoformat(iso)
                for iso in self._mount.dates(BARS_STREAM, self._symbol)
            )
        return self._dates

    def __contains__(self, day: object) -> bool:
        return isinstance(day, dt.date) and day in self._available()

    def __getitem__(self, day: dt.date) -> float:
        if day not in self._available():
            raise KeyError(day)
        cache_key = (self._snapshot_hash, self._symbol, day)
        try:
            return _CLOSE_CACHE[cache_key]
        except KeyError:
            pass
        with _CLOSE_LOCK:
            cached = _CLOSE_CACHE.get(cache_key)
            if cached is not None:
                return cached
            price = _read_close(self._mount, self._symbol, day)
            _CLOSE_CACHE[cache_key] = price
            return price

    def __iter__(self) -> Iterator[dt.date]:
        return iter(self._available())

    def __len__(self) -> int:
        return len(self._available())


class _LazyCloses(Mapping[str, Mapping[dt.date, float]]):
    """Step 4's ``closes`` — one :class:`_LazySymbolCloses` per symbol,
    built from the roster :func:`_bars_symbols` already paid a directory
    listing for at load.  Nothing past that listing is read until a
    caller indexes a specific symbol and date, so a context answers the
    same full mapping :func:`_closes` used to build eagerly, but reads
    only the partitions whoever consumes ``closes`` actually touches.
    """

    __slots__ = ("_mount", "_snapshot_hash", "_symbols")

    def __init__(
        self, mount: SnapshotMount, snapshot_hash: str, symbols: tuple[str, ...]
    ) -> None:
        self._mount = mount
        self._snapshot_hash = snapshot_hash
        self._symbols = symbols

    def __contains__(self, symbol: object) -> bool:
        return symbol in self._symbols

    def __getitem__(self, symbol: str) -> Mapping[dt.date, float]:
        if symbol not in self._symbols:
            raise KeyError(symbol)
        return _LazySymbolCloses(self._mount, self._snapshot_hash, symbol)

    def __iter__(self) -> Iterator[str]:
        return iter(self._symbols)

    def __len__(self) -> int:
        return len(self._symbols)


def _read_close(mount: SnapshotMount, symbol: str, day: dt.date) -> float:
    """One symbol-day's close, read from its own partition.

    The content half of the original eager read, scoped to the single
    ``(symbol, day)`` a lazy lookup asked for: the venue's string
    spelling of a close is parsed to the finite positive float step 4
    validates (a price that is not a positive finite number poisons every
    forward return measured off it), keyed by the row's own
    ``open_time`` date — the candle's day, not the partition's name, so
    a partition holding a row of another day still lands where the bar
    says it belongs.  A second row for this ``(symbol, day)`` is refused
    rather than merged, the same "one bar, one close" law
    :func:`_refuse_duplicate_bars` already checked for free across the
    whole snapshot — held here too, for the partitions that check could
    not see into (an unknown row count).  ``day`` absent from this
    partition's own rows answers :class:`KeyError`, like any other
    missing mapping key.
    """
    iso = day.isoformat()
    series: dict[dt.date, float] = {}
    for part in mount.select(BARS_STREAM, symbol, iso):
        table = _read_part(part, symbol)
        if "open_time" not in table.column_names:
            raise EvaluationConfigError(
                f"{EVALUATION_CONFIG_CODE}: snapshot_mount names "
                f"a snapshot whose {part!s} carries no "
                "'open_time' column; bars are candles (the "
                "contract's two required columns name the book "
                "and the candle-open instant), and a close "
                "whose bar day cannot be read is a close that "
                "cannot be keyed"
            )
        if "close" not in table.column_names:
            raise EvaluationConfigError(
                f"{EVALUATION_CONFIG_CODE}: snapshot_mount names "
                f"a snapshot whose {part!s} carries no 'close' "
                "column; the alignment's market grid is the "
                "closes of the scored symbols, and a bar "
                "without one is a bar no target can be "
                "measured from"
            )
        for row in table.select(["open_time", "close"]).to_pylist():
            moment = row["open_time"]
            row_day = (
                moment.date() if isinstance(moment, dt.datetime) else moment
            )
            price = _close_price(row["close"], symbol, row_day)
            if row_day in series:
                raise EvaluationConfigError(
                    f"{EVALUATION_CONFIG_CODE}: snapshot_mount "
                    f"names a snapshot whose bars carry "
                    f"{symbol!r} on {row_day.isoformat()} twice; one "
                    "bar, one close — the aligner's grain, and "
                    "a snapshot that carries two has a staging "
                    "defect a silent merge would hide"
                )
            series[row_day] = price
    if day not in series:
        raise KeyError(day)
    return series[day]


def _read_part(part: object, symbol: str) -> Any:
    """Read one Parquet part through its read-only path.

    Split out so an unreadable part is one refusal with one shape: the
    configuration named a snapshot whose bytes cannot be read, and the
    operator's remedy is the snapshot, not the loader.  pyarrow's
    malformed-file and unreadable-path failures derive from
    :class:`ValueError` and :class:`OSError` respectively, so those are
    the two shapes translated — anything else is a defect worth seeing
    whole, not a configuration fact.
    """
    import pyarrow.parquet as pq  # lazy: the evaluator's own reader idiom

    try:
        return pq.read_table(str(part))
    except (OSError, ValueError) as exc:
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: snapshot_mount names a snapshot "
            f"whose part {part!s} for {symbol!r} cannot be read as "
            f"Parquet: {exc}"
        ) from exc


def _close_price(raw: Any, symbol: str, day: dt.date) -> float:
    """One close, as the finite positive float the alignment validates.

    The venue's own spelling — a string, in the bars this lake seals
    (§4.1 passes it through verbatim) — is parsed here; a numeric
    column is accepted as-is.  Zero, negative and non-finite prices are
    refused at load for the aligner's own stated reason: the forward
    return divides by the entry close, so a price that is not a
    positive finite number poisons every label measured off it, and a
    poison that waits for step 4 looks like an evaluation defect
    instead of a snapshot one.
    """
    if isinstance(raw, bool) or raw is None:
        price: float | None = None
    elif isinstance(raw, str):
        try:
            price = float(raw.strip())
        except ValueError:
            price = None
    elif isinstance(raw, (int, float)):
        price = float(raw)
    else:
        price = None
    if price is None or not math.isfinite(price) or price <= 0.0:
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: snapshot_mount names a snapshot "
            f"whose close for {symbol!r} on {day.isoformat()} is not a "
            f"positive finite price, got {raw!r}; the forward return "
            "divides by the entry close, so a price that is not one "
            "poisons every label measured off it"
        )
    return price


# -- The cost inputs ----------------------------------------------------------


def _cost_inputs(
    source: Mapping[str, str], database_url: str
) -> tuple[CostModelConfig, FeeSchedule, str]:
    """The loaded cost model, its resolved schedule, and its hash.

    One service over ``NULLIUS_COST_MODEL_PATH`` (unset meaning the
    shipped §6.2 document — the cost-model member's own semantics for
    the variable, kept rather than re-decided here), and one parse
    behind all three answers: the pair, the rates and feature 60's hash
    all read from the document the service loaded, so a schedule and
    the hash beside it cannot disagree about which document was read.
    The schedule resolves through the process's one claimed fee
    implementation (feature 69) — this member computes no fee
    arithmetic of its own, and the claim is what keeps it that way.
    """
    raw = source.get("NULLIUS_COST_MODEL_PATH")
    path = raw if raw and raw.strip() else None
    origin = f"from {raw!r}" if path else "from the shipped default document"
    service = CostModelService(config_path=path, database_url=database_url)
    try:
        cost_model = service.config
        cost_schedule = service.fees()
        cost_model_hash = service.cost_model_hash()
    except CostModelError as exc:
        # The variable is named even when it was unset (the shipped
        # document) — the operator's remedy is always the same one knob,
        # and a refusal that named only the path would send them looking
        # for a file the variable never pointed at.
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: the cost model named by "
            f"NULLIUS_COST_MODEL_PATH could not be loaded {origin}: "
            f"{exc}; post-cost returns are netted through the shared "
            "library's own schedule (feature 69), so a document it "
            "refuses is a configuration this loader refuses"
        ) from exc
    return cost_model, cost_schedule, cost_model_hash


# -- The executor ---------------------------------------------------------------


def signal_sandbox(context: EvaluationContext) -> object:
    """Build this evaluation's signal executor from its own context.

    additions_spec_gvisor_executor.xml, "Executor Selection", feature 7:
    *orchestrator._context.signal_sandbox(context) answers a GVisorSandbox
    for sandbox_runtime "gvisor", or a HardenedSubprocessSandbox for
    "unisolated".*  Both are drop-ins for :func:`evaluator.execute_signal`'s
    ``sandbox`` argument, and :func:`orchestrator._evaluate.evaluate_node`
    always passes this function's answer to it — the evaluator's own
    default :class:`~evaluator.SignalSandbox` (a plain, unconfined
    subprocess) is never asked to run agent-authored code.

    ``"gvisor"`` builds a fresh :class:`~orchestrator._gvisor.GVisorSandbox`
    over the context's own ``gvisor_runtime_root``, ``gvisor_state_root``
    and ``lake_roots`` — already loaded and validated once, at
    :func:`load_evaluation_context` time (the missing-key refusal this
    feature names happens there, not here). ``"unisolated"`` builds a fresh
    :class:`~orchestrator._hardened_sandbox.HardenedSubprocessSandbox`,
    taking its defaults.  ``context.sandbox_runtime`` is one of
    :data:`SANDBOX_RUNTIMES` by construction (the gate already checked it),
    so there is no third branch.

    The answer also remembers its own last :class:`~evaluator.SandboxResult`
    on ``last_result`` (see :func:`_track_last_result`): a fresh executor
    per call, built once per evaluated node and reused for every rebalance
    date within it, the same "construct once, run many" shape both
    executors' own docstrings already state.

    **One test-only exception, checked first.**  When
    ``context.test_stub_sandbox`` carries :data:`TEST_STUB_SANDBOX_ENV`'s
    value, this answers that stub instead of either real branch — see
    that constant's own docstring for why a process-pool test needs a
    third seam here that a real deployment's closed ``sandbox_runtime``
    vocabulary never offers.
    """
    if context.test_stub_sandbox:
        return _track_last_result(_load_stub_sandbox(context.test_stub_sandbox))
    if context.sandbox_runtime == "gvisor":
        sandbox_instance: object = GVisorSandbox(
            runsc=GVISOR_RUNTIME,
            runtime_root=context.gvisor_runtime_root,
            state_root=context.gvisor_state_root,
            lake_roots=context.lake_roots,
        )
    else:
        sandbox_instance = HardenedSubprocessSandbox()
    return _track_last_result(sandbox_instance)


#: One loaded module per distinct ``path_text``, kept for the life of this
#: process. :func:`_load_stub_sandbox` runs once per *node* (``evaluate_node``
#: calls :func:`signal_sandbox` fresh every time), and a test file loaded by
#: path carries its own imports — re-executing it from scratch on every node
#: would re-pay that cost every single call rather than once per worker
#: process, the same "construct once, run many" shape every real executor
#: this function stands in for already holds.
_STUB_SANDBOX_MODULES: dict[str, Any] = {}


def _load_stub_sandbox(spelling: str) -> Any:
    """Build the test-only stub sandbox :data:`TEST_STUB_SANDBOX_ENV` names.

    ``spelling`` is ``"<path-to-.py-file>:<zero-arg-factory-name>"``,
    loaded by file path rather than by dotted import (the same by-path
    loading this workspace's own test suites already use for a migration
    module), so a worker process spawned fresh under
    :class:`~orchestrator._process_pool.ProcessEvaluator`'s ``spawn``
    context can build the identical stub regardless of its own
    ``sys.path``.  Calls the named attribute with no arguments — a
    zero-arg factory, the same shape a bare class name already is.  The
    module itself is loaded once per ``path_text`` and cached
    (:data:`_STUB_SANDBOX_MODULES`); only the zero-arg factory call runs
    fresh every time, matching the real executors' own "construct once,
    run many" shape at the instance level while never paying for the
    file's own imports more than once per process.
    """
    import importlib.util

    path_text, _, factory_name = spelling.rpartition(":")
    if not path_text or not factory_name:
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: {TEST_STUB_SANDBOX_ENV} must be "
            f"'<path-to-.py-file>:<factory-name>', got {spelling!r}"
        )
    module = _STUB_SANDBOX_MODULES.get(path_text)
    if module is None:
        spec = importlib.util.spec_from_file_location(
            "_orchestrator_test_stub_sandbox", path_text
        )
        if spec is None or spec.loader is None:
            raise EvaluationConfigError(
                f"{EVALUATION_CONFIG_CODE}: {TEST_STUB_SANDBOX_ENV} names "
                f"{path_text!r}, which cannot be loaded as a Python module"
            )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _STUB_SANDBOX_MODULES[path_text] = module
    factory = getattr(module, factory_name)
    return factory()


def _track_last_result(sandbox_instance: Any) -> Any:
    """Wrap ``sandbox_instance.run`` so it remembers its own last answer.

    :class:`~evaluator.RawScoreVector` drops the executor's ``fail_class``
    and ``detail`` entirely (neither field exists on it) — the only trace
    of *why* a rebalance date's run failed is the
    :class:`~evaluator.SandboxResult` :meth:`run` answered for it, and
    ``execute_signal`` holds that value only as a local variable before
    discarding it. This is the one seam that survives: an instance
    attribute override (never a subclass), so
    ``isinstance(signal_sandbox(context), GVisorSandbox)`` — feature 7's own
    sentence — still holds for the gVisor branch, and the same for
    :class:`~orchestrator._hardened_sandbox.HardenedSubprocessSandbox` on
    the other. :func:`orchestrator._evaluate.evaluate_node` reads
    ``last_result`` off the executor it was handed once
    :class:`~evaluator.RawScoreVector`'s own ``conforming`` says a date
    failed, which is exactly feature 7's "evaluate_node reads them from the
    executor's last result."
    """
    original_run = sandbox_instance.run

    def run(code: str, window: object, *, seed: int) -> SandboxResult:
        result = original_run(code, window, seed=seed)
        sandbox_instance.last_result = result
        return result

    sandbox_instance.last_result = None
    sandbox_instance.run = run
    return sandbox_instance
