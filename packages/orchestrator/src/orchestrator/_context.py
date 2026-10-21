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
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from cost_model import (
    MAKER,
    TAKER,
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
    "BOOK_KEY",
    "BOOK_WEIGHTINGS",
    "BWRAP_RUNTIME",
    "DEFAULT_BETA_BENCHMARK",
    "DEFAULT_BETA_WINDOW_DAYS",
    "DEFAULT_BOOK_WEIGHTING",
    "DEFAULT_EVALUATION_MODE",
    "DEFAULT_EVALUATION_WORKERS",
    "DEFAULT_EXECUTION",
    "DEFAULT_INSTRUMENT",
    "DEFAULT_MAX_HISTORY_DAYS",
    "DEFAULT_METRICS_HORIZON",
    "DEFAULT_VOL_WINDOW_DAYS",
    "EVALUATION_CONFIG_CODE",
    "EVALUATION_CONFIG_ENV",
    "EVALUATION_MODES",
    "EVALUATION_MODE_KEY",
    "EVALUATION_WORKERS_KEY",
    "EXECUTIONS",
    "EXECUTION_KEY",
    "FUNDING_STREAM",
    "FUTBARS_STREAM",
    "GVISOR_RUNTIME",
    "GVISOR_RUNTIME_ROOT_KEY",
    "GVISOR_STATE_ROOT_KEY",
    "INSTRUMENTS",
    "INSTRUMENT_KEY",
    "INVERSE_VOL_WEIGHTING",
    "ISOLATION_REQUIRED",
    "LAKE_ROOTS_KEY",
    "MAX_EVALUATION_WORKERS",
    "MAX_HISTORY_DAYS_KEY",
    "METRICS_HORIZONS",
    "METRICS_HORIZON_CONFIGURED",
    "METRICS_HORIZON_KEY",
    "METRICS_HORIZON_SHORTEST",
    "MIN_EVALUATION_WORKERS",
    "MIN_VOL_WINDOW_DAYS",
    "OOS_DATES_KEY",
    "PERP_INSTRUMENT",
    "REQUIRED_KEYS",
    "SANDBOX_RUNTIMES",
    "SHORT_TAIL_WEIGHTING",
    "SPOT_INSTRUMENT",
    "TAIL_DECILE_WEIGHTING",
    "TEST_STUB_SANDBOX_ENV",
    "Z_WEIGHTING",
    "BookConfig",
    "EvaluationConfigError",
    "EvaluationContext",
    "compute_betas",
    "compute_vols",
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

#: The USD-M futures daily-kline stream — additions_spec_research_book_v2.xml,
#: the perp instrument feature: with ``instrument: "perp"``,
#: :func:`load_evaluation_context` serves :attr:`EvaluationContext.closes`
#: from this stream's ``fut_close`` instead of :data:`BARS_STREAM`'s
#: ``close``, keyed by the same spot symbol the partitions already carry
#: (:mod:`nullius_ingest.derivs_backfill` writes every row under the spot
#: symbol, never the UM one).  The same local spelling
#: :mod:`orchestrator._evaluate`'s own ``FUTBARS_STREAM`` carries, for the
#: reason that module's docstring already states: this is the one module on
#: this side that reads the stream by name.
FUTBARS_STREAM: Final[str] = "futbars"

#: The funding-settlement stream the perp instrument's carry is summed
#: from — ``funding_rate_sum``, one row per symbol per ingest day.
FUNDING_STREAM: Final[str] = "funding"

#: The optional key choosing which book this evaluation prices —
#: additions_spec_research_book_v2.xml, the perp instrument feature: a
#: context evaluates signals as a book of USD-M perpetuals when the document
#: names ``"perp"``; absent (or ``"spot"``) is today's unchanged behaviour.
INSTRUMENT_KEY: Final[str] = "instrument"

#: :data:`INSTRUMENT_KEY`'s two values — closed, the same stance
#: :data:`SANDBOX_RUNTIMES` and :data:`EVALUATION_MODES` already take: a
#: third spelling is refused by name rather than guessed.
SPOT_INSTRUMENT: Final[str] = "spot"
PERP_INSTRUMENT: Final[str] = "perp"
INSTRUMENTS: Final[tuple[str, str]] = (SPOT_INSTRUMENT, PERP_INSTRUMENT)

#: :data:`INSTRUMENT_KEY`'s default when the document omits it — today's
#: book, unchanged.
DEFAULT_INSTRUMENT: Final[str] = SPOT_INSTRUMENT

#: The venue-name suffix a perp book's cost model must carry.  A "perp"
#: instrument prices funding carry and futures fees, and a schedule whose
#: venue does not end this way (the shipped ``binance_spot`` default, say)
#: is pricing a different market's fees against this book — refused at
#: load, naming both the instrument and the venue, rather than silently
#: netting a spot fee schedule against a perpetual's returns.
_USDM_VENUE_SUFFIX: Final[str] = "_usdm"

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

#: The optional key choosing the side a node's turnover is priced as —
#: today's default is a crossing order, priced at the venue's taker fee; a
#: signal that trades passively instead rests a quote, pays the maker fee,
#: and bears the queue-position penalty a resting order pays for the
#: adverse selection of its own fill (cost_model feature 64). Optional, the
#: same stance :data:`EVALUATION_MODE_KEY` and :data:`INSTRUMENT_KEY` take
#: toward their own two-member sets: a document that omits it gets
#: :data:`DEFAULT_EXECUTION` rather than a refusal, since "today's taker
#: behaviour" is what every evaluation config written before this key
#: existed already means.
EXECUTION_KEY: Final[str] = "execution"

#: :data:`EXECUTION_KEY`'s two values — :data:`cost_model.TAKER` and
#: :data:`cost_model.MAKER`, the same two spellings
#: :class:`cost_model.FeeSchedule` itself prices a fill under, so an
#: execution mode is never a third vocabulary the fee schedule does not
#: already speak.  Closed, like :data:`EVALUATION_MODES` and
#: :data:`INSTRUMENTS`: a third spelling is refused by name rather than
#: guessed.
EXECUTIONS: Final[tuple[str, str]] = (TAKER, MAKER)

#: :data:`EXECUTION_KEY`'s default when the document omits it — today's
#: taker behaviour, unchanged, the same stance :data:`DEFAULT_INSTRUMENT`
#: and :data:`DEFAULT_EVALUATION_MODE` take toward their own optional keys.
DEFAULT_EXECUTION: Final[str] = TAKER

#: The optional key choosing which horizon the node metrics themselves are
#: measured at — bug_spec_metrics_horizon.xml bug 2.  Both evaluation chains
#: align and gate all of :data:`evaluator.HORIZONS`, so the panel a
#: ``compute_node_metrics`` call reduces over carries every horizon the
#: oracle answered, and before this key the metrics silently took the
#: shortest covered one — always 1 — whatever ``horizon`` the campaign was
#: configured and selected under.  Optional, the same stance
#: :data:`EXECUTION_KEY` takes toward its own two-member set: a document
#: that omits it gets :data:`DEFAULT_METRICS_HORIZON` rather than a
#: refusal, since "the shortest covered horizon" is what every evaluation
#: config written before this key existed already measured.
METRICS_HORIZON_KEY: Final[str] = "metrics_horizon"

#: :data:`METRICS_HORIZON_KEY`'s two values.  ``"shortest"`` keeps
#: :func:`evaluator.compute_node_metrics`'s own shortest-covered policy —
#: every number this system has ever stored was measured that way, and a
#: default that moved them would rewrite the meaning of rows this fix is
#: forbidden to touch.  ``"configured"`` asks for the campaign's own
#: :attr:`EvaluationContext.horizon`, through the derived
#: :attr:`EvaluationContext.metrics_horizon_value` the evaluation chains
#: hand to every metrics call.
METRICS_HORIZON_SHORTEST: Final[str] = "shortest"
METRICS_HORIZON_CONFIGURED: Final[str] = "configured"
METRICS_HORIZONS: Final[tuple[str, str]] = (
    METRICS_HORIZON_SHORTEST,
    METRICS_HORIZON_CONFIGURED,
)

#: :data:`METRICS_HORIZON_KEY`'s default when the document omits it — the
#: shortest covered horizon, today's behaviour unchanged, the same stance
#: :data:`DEFAULT_EXECUTION` and :data:`DEFAULT_BOOK_WEIGHTING` take toward
#: their own optional keys.
DEFAULT_METRICS_HORIZON: Final[str] = METRICS_HORIZON_SHORTEST

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

#: The optional key naming the research book construction —
#: additions_spec_research_book_v2.xml feature 2.  Absent means
#: :data:`BookConfig`'s own defaults (``beta_neutral=False``), the same
#: unchanged-behaviour stance :data:`MAX_HISTORY_DAYS_KEY` takes toward its
#: own optional knob.  Present, its value is a JSON object validated by
#: :func:`_book_config`: a closed vocabulary of its own
#: (``beta_neutral``, ``beta_window_days``, ``beta_benchmark``,
#: ``weighting``, ``vol_window_days``), so a typo'd inner key is refused
#: rather than silently ignored.
BOOK_KEY: Final[str] = "book"

#: :data:`BOOK_KEY`'s five inner keys.
_BOOK_BETA_NEUTRAL_KEY: Final[str] = "beta_neutral"
_BOOK_BETA_WINDOW_DAYS_KEY: Final[str] = "beta_window_days"
_BOOK_BETA_BENCHMARK_KEY: Final[str] = "beta_benchmark"
_BOOK_WEIGHTING_KEY: Final[str] = "weighting"
_BOOK_VOL_WINDOW_DAYS_KEY: Final[str] = "vol_window_days"

#: ``beta_window_days``' default — the trailing daily returns a point-in-time
#: beta is regressed over, when the document omits the key.
DEFAULT_BETA_WINDOW_DAYS: Final[int] = 60

#: ``beta_benchmark``'s default — the symbol :func:`compute_betas` regresses
#: every other symbol's returns on, when the document omits the key.
DEFAULT_BETA_BENCHMARK: Final[str] = "BTCUSDT"

#: The four weightings :data:`BOOK_KEY`'s ``weighting`` inner key accepts —
#: closed, the same stance :data:`INSTRUMENTS` takes toward its own
#: two-member set: ``"z"`` is today's score-proportional book, unchanged;
#: ``"inverse_vol"`` divides each score by its own symbol's point-in-time
#: realised volatility before the book is normalized (see
#: :func:`compute_vols`); ``"tail_decile"`` ignores the score's magnitude
#: entirely and goes long the top decile of the day's ranking, short the
#: bottom decile, equal-weight within each leg, for a ranking whose return
#: gradient lives in its tails rather than across the whole cross-section;
#: ``"short_tail"`` (additions_spec_short_tail_book.xml) shorts the bottom
#: decile of the day's ranking equal-weight and holds every other scored name
#: long equal-weight, dollar-neutral at gross 1 — the construction the
#: committed preregistration results ask for, where the return gradient lives
#: in the bottom decile of scores alone (the top decile never the best
#: bucket, deciles 2 through 10 flat), so the long leg is the market-like
#: complement of the short rather than a second bet on a decile that carries
#: no gradient.
#: A fifth spelling is refused by name rather than guessed, because a
#: weighting is the whole book's construction — running one a document
#: never named is measuring a different portfolio than the one the campaign
#: configured.
Z_WEIGHTING: Final[str] = "z"
INVERSE_VOL_WEIGHTING: Final[str] = "inverse_vol"
TAIL_DECILE_WEIGHTING: Final[str] = "tail_decile"
SHORT_TAIL_WEIGHTING: Final[str] = "short_tail"
BOOK_WEIGHTINGS: Final[tuple[str, ...]] = (
    Z_WEIGHTING,
    INVERSE_VOL_WEIGHTING,
    TAIL_DECILE_WEIGHTING,
    SHORT_TAIL_WEIGHTING,
)

#: ``weighting``'s default when the document omits it — today's book,
#: unchanged, the same stance :data:`DEFAULT_INSTRUMENT` takes toward its own
#: optional key.
DEFAULT_BOOK_WEIGHTING: Final[str] = Z_WEIGHTING

#: ``vol_window_days``' default — the trailing daily returns a point-in-time
#: volatility is measured over, when the document omits the key.  The same
#: 60 :data:`DEFAULT_BETA_WINDOW_DAYS` carries, for the same reason: a
#: season of daily returns is what either estimate is asking the window for.
DEFAULT_VOL_WINDOW_DAYS: Final[int] = 60

#: ``vol_window_days``' floor.  A volatility measured over fewer than twenty
#: returns is noise dressed as a scale — it weights the book on the strength
#: of a fortnight — so a shorter window is refused rather than honoured,
#: unlike ``beta_window_days``' own positive-any bound: a beta is a
#: *relative* figure the rescale only uses to balance legs, while a vol is
#: an *absolute* scale the weights divide by, and a bad one bends every
#: weight in the book.
MIN_VOL_WINDOW_DAYS: Final[int] = 20

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
class BookConfig:
    """The research book's construction — :data:`BOOK_KEY`'s parsed value.

    ``beta_neutral=False`` (with the other fields at their own defaults) is
    what every context carries when the document omits :data:`BOOK_KEY`
    entirely — today's plain dollar-neutral book, unchanged.  With
    ``beta_neutral=True``, :func:`orchestrator._evaluate.evaluate_node` and
    :func:`~orchestrator._evaluate.evaluate_on_dates` ask
    :func:`compute_betas` for this evaluation's point-in-time betas and hand
    them to :func:`evaluator.compute_node_metrics`, which rescales each
    date's book so its long and short legs carry equal benchmark beta.  With
    ``weighting="inverse_vol"``, the same two chains ask :func:`compute_vols`
    for this evaluation's point-in-time volatilities and hand those to the
    same call, which divides each score by its own symbol's vol before the
    book is normalized — one key in the evaluation config switches the whole
    engine to volatility-scaled books, and no other change is needed.  With
    ``weighting="tail_decile"`` the chains pass that string through instead
    and compute no side panel at all: the book is a function of each date's
    scores alone — long the top decile of the ranking, short the bottom,
    equal-weight within each leg — for a ranking whose return gradient lives
    in its tails rather than across the whole cross-section.  With
    ``weighting="short_tail"`` (additions_spec_short_tail_book.xml) the chains
    pass that string through the same way and compute no side panel either:
    each date's book is short the bottom decile of that date's scores
    equal-weight and long every other scored name equal-weight, dollar-neutral
    at gross 1 — the construction the committed preregistration results ask
    for, where the gradient lives in the bottom decile alone (the top decile
    never the best bucket, deciles 2 through 10 flat), so the long leg is the
    market-like complement of the short rather than a second bet on a decile
    that carries no gradient.  Each of the
    four weightings composes independently with ``beta_neutral``, which
    rescales the legs the weighting chose.
    """

    #: Whether the book is rescaled to be benchmark-beta-neutral.
    beta_neutral: bool = False
    #: How many trailing daily returns a point-in-time beta is regressed
    #: over — :data:`DEFAULT_BETA_WINDOW_DAYS` when the document omits it.
    beta_window_days: int = DEFAULT_BETA_WINDOW_DAYS
    #: The symbol every beta is regressed against —
    #: :data:`DEFAULT_BETA_BENCHMARK` when the document omits it.
    beta_benchmark: str = DEFAULT_BETA_BENCHMARK
    #: Which weighting each date's book is built under —
    #: :data:`Z_WEIGHTING` (score-proportional, today's book),
    #: :data:`INVERSE_VOL_WEIGHTING` (each score divided by its own symbol's
    #: point-in-time realised volatility before normalization),
    #: :data:`TAIL_DECILE_WEIGHTING` (long the top decile of the day's
    #: ranking, short the bottom decile, equal-weight within each leg, the
    #: score's magnitude unused), or :data:`SHORT_TAIL_WEIGHTING` (short the
    #: bottom decile of the day's ranking equal-weight, long every other
    #: scored name equal-weight — the long leg the complement of the short).
    #: :data:`DEFAULT_BOOK_WEIGHTING` when the
    #: document omits it.
    weighting: str = DEFAULT_BOOK_WEIGHTING
    #: How many trailing daily returns a point-in-time volatility is measured
    #: over — :data:`DEFAULT_VOL_WINDOW_DAYS` when the document omits it,
    #: never below :data:`MIN_VOL_WINDOW_DAYS`.
    vol_window_days: int = DEFAULT_VOL_WINDOW_DAYS


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
    #: floats, read and memoized one symbol at a time on first use
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
    #: The research book's construction, read from the optional
    #: :data:`BOOK_KEY` (:class:`BookConfig`'s own defaults when absent).
    #: :func:`orchestrator._evaluate.evaluate_node` and
    #: :func:`~orchestrator._evaluate.evaluate_on_dates` are the readers.
    book: BookConfig = field(default_factory=BookConfig)
    #: Which book this evaluation prices — :data:`SPOT_INSTRUMENT` (the
    #: default) or :data:`PERP_INSTRUMENT` — read from the optional
    #: :data:`INSTRUMENT_KEY`.  With ``"perp"``, :attr:`closes` is served
    #: from :data:`FUTBARS_STREAM`'s ``fut_close`` rather than
    #: :data:`BARS_STREAM`'s ``close``, so every forward return, alignment,
    #: beta and close-out figure that reads :attr:`closes` follows — the
    #: bars closes are not read for returns at all.  ``"spot"`` reproduces
    #: every figure exactly as this module measured them before the
    #: instrument existed.
    instrument: str = DEFAULT_INSTRUMENT
    #: The funding-settlement carry :func:`orchestrator._evaluate._cost_schedule_from_context`
    #: sums over a horizon's holding days — ``{symbol: {ingest day:
    #: funding_rate_sum}}``, the same lazy, memoized shape :attr:`closes`
    #: takes, read from :data:`FUNDING_STREAM`.  ``None`` for
    #: :data:`SPOT_INSTRUMENT`, which charges no funding at all; always a
    #: (possibly empty) mapping for :data:`PERP_INSTRUMENT`, so a snapshot
    #: with no sealed funding rows charges a carry of zero rather than
    #: refusing — a missing row is absence, not an error, the same stance
    #: every other optional derivative stream in this package takes.
    funding: Mapping[str, Mapping[dt.date, float]] | None = None
    #: Which side this evaluation's turnover is priced as —
    #: :data:`cost_model.TAKER` (the default) or :data:`cost_model.MAKER` —
    #: read from the optional :data:`EXECUTION_KEY`.  With the default,
    #: :func:`orchestrator._evaluate._turnover_fee_from_context` and
    #: :func:`~orchestrator._evaluate._cost_schedule_from_context` quote
    #: exactly :attr:`cost_schedule`'s taker rate, unchanged from before this
    #: key existed.  With ``"maker"``, both seams quote the maker rate plus
    #: :attr:`cost_schedule`'s own
    #: :attr:`~cost_model.FeeSchedule.passive_penalty_fraction`, so a signal
    #: priced as passively filled is charged the fee it would actually pay
    #: resting — its adverse-selection cost stated beside the fee, never
    #: zero because the maker rate happens to be low.  A ``"maker"``
    #: configuration whose cost model resolves no passive penalty is refused
    #: at load (see :func:`load_evaluation_context`), so a context that
    #: exists with ``execution == MAKER`` always carries a schedule whose
    #: :attr:`~cost_model.FeeSchedule.passive_penalty_fraction` is not
    #: ``None``.
    execution: str = DEFAULT_EXECUTION
    #: The mode choosing which horizon the node metrics are measured at —
    #: :data:`METRICS_HORIZON_SHORTEST` (the default) or
    #: :data:`METRICS_HORIZON_CONFIGURED` — read from the optional
    #: :data:`METRICS_HORIZON_KEY`.  With the default,
    #: :func:`evaluator.compute_node_metrics` keeps its own
    #: shortest-covered policy and every number is exactly what it was
    #: before this key existed.  With ``"configured"``, the derived
    #: :attr:`metrics_horizon_value` names :attr:`horizon`, so the
    #: evaluation chains measure — and an out-of-sample read re-measures,
    #: through ``dataclasses.replace(context, horizon=…)`` — at the horizon
    #: the campaign was configured under.
    metrics_horizon: str = DEFAULT_METRICS_HORIZON

    @property
    def metrics_horizon_value(self) -> int | None:
        """The horizon the metrics are measured at, or ``None`` for "shortest".

        ``None`` under :data:`METRICS_HORIZON_SHORTEST` — the caller hands
        ``compute_node_metrics`` no horizon and its own shortest-covered
        policy applies — and :attr:`horizon` under
        :data:`METRICS_HORIZON_CONFIGURED`.  A property, not a field, on
        purpose: it is *derived* from :attr:`horizon`, so
        ``dataclasses.replace(context, horizon=h)`` — the seam
        :func:`orchestrator._financial_eval._oos_ir` and
        :func:`orchestrator.portfolio_oos._score_pick_oos` re-horizon a
        context through — re-resolves it to ``h`` under ``"configured"``,
        which is what makes that re-horizoning reach the metrics rather
        than only a cache key.
        """
        if self.metrics_horizon == METRICS_HORIZON_CONFIGURED:
            return self.horizon
        return None


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
    book = _book_config(document, named)
    instrument = _instrument(document, named)
    execution = _execution(document, named)
    metrics_horizon = _metrics_horizon(document, named)
    test_stub_sandbox = source.get(TEST_STUB_SANDBOX_ENV) or None
    database_url = _database_url(source)

    mount = _mounted_snapshot(values, named)
    symbols = _bars_symbols(mount, named)
    manifest = _read_manifest(mount, named)
    _refuse_duplicate_bars(manifest, named)
    snapshot_hash = manifest.snapshot_hash
    if instrument == PERP_INSTRUMENT:
        perp_symbols = _futbars_symbols(mount, named)
        _refuse_duplicate_futbars(manifest, named)
        closes = _LazyCloses(
            mount,
            snapshot_hash,
            perp_symbols,
            stream=FUTBARS_STREAM,
            day_column="date",
            close_column="fut_close",
        )
        funding = _LazyFunding(mount, snapshot_hash, mount.partitions(FUNDING_STREAM))
    else:
        closes = _LazyCloses(mount, snapshot_hash, symbols)
        funding = None
    cost_model, cost_schedule, cost_model_hash = _cost_inputs(
        source, database_url
    )
    if instrument == PERP_INSTRUMENT and not cost_model.venue.endswith(
        _USDM_VENUE_SUFFIX
    ):
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: {INSTRUMENT_KEY} is {PERP_INSTRUMENT!r}, "
            "which prices USD-M perpetual funding and fees, but the cost "
            f"model's venue is {cost_model.venue!r}, which does not end in "
            f"{_USDM_VENUE_SUFFIX!r}; point NULLIUS_COST_MODEL_PATH at a "
            "USD-M schedule (cost_model/binance_usdm.yaml) before "
            f"configuring a {PERP_INSTRUMENT!r} book, or set {INSTRUMENT_KEY} "
            f"to {SPOT_INSTRUMENT!r}"
        )
    if execution == MAKER and cost_schedule.passive_penalty_fraction is None:
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: {EXECUTION_KEY} is {MAKER!r}, but "
            f"the cost model document {cost_model.source!r} names no "
            "fill_model.passive queue-position penalty; a maker execution "
            "prices a signal at the fee it would pay executed passively, "
            "with its adverse-selection cost stated rather than ignored, "
            "and a document with no passive fill model cannot state it — "
            "add fill_model.passive.queue_position_penalty_bps to the "
            f"document, or set {EXECUTION_KEY} to {TAKER!r}"
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
        book=book,
        instrument=instrument,
        funding=funding,
        execution=execution,
        metrics_horizon=metrics_horizon,
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
            BOOK_KEY,
            INSTRUMENT_KEY,
            EXECUTION_KEY,
            METRICS_HORIZON_KEY,
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
                f"{EVALUATION_WORKERS_KEY!r}, {EVALUATION_MODE_KEY!r}, "
                f"{OOS_DATES_KEY!r}, {BOOK_KEY!r}, {INSTRUMENT_KEY!r}, "
                f"{EXECUTION_KEY!r} and {METRICS_HORIZON_KEY!r}); "
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


def _book_config(document: Mapping[str, Any], named: str) -> BookConfig:
    """:data:`BOOK_KEY`'s parsed value — :class:`BookConfig`'s own defaults
    when the document omits it, so an absent block leaves
    ``book.beta_neutral`` false and every figure unchanged.

    Present, the value must be a JSON object holding only
    ``beta_neutral`` (required — there is no default for the field that
    decides whether the book is rescaled at all), ``beta_window_days``
    (a positive integer, :data:`DEFAULT_BETA_WINDOW_DAYS` when absent),
    ``beta_benchmark`` (a non-blank string, :data:`DEFAULT_BETA_BENCHMARK`
    when absent), ``weighting`` (one of :data:`BOOK_WEIGHTINGS`,
    :data:`DEFAULT_BOOK_WEIGHTING` when absent — a key of its own rather
    than folded into ``beta_neutral``, because the two constructions are
    independent: a book can be inverse-vol weighted and not beta-neutral,
    or both, or neither) and ``vol_window_days`` (an integer of at least
    :data:`MIN_VOL_WINDOW_DAYS`, :data:`DEFAULT_VOL_WINDOW_DAYS` when
    absent); any other inner key is refused by name, the same closed
    vocabulary discipline :func:`_refuse_unknown_keys` holds for the
    outer document.
    """
    if BOOK_KEY not in document:
        return BookConfig()
    raw = document[BOOK_KEY]
    if not isinstance(raw, Mapping):
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: {BOOK_KEY!r} must be a JSON "
            f"object, got {type(raw).__name__}"
        )
    allowed = frozenset(
        (
            _BOOK_BETA_NEUTRAL_KEY,
            _BOOK_BETA_WINDOW_DAYS_KEY,
            _BOOK_BETA_BENCHMARK_KEY,
            _BOOK_WEIGHTING_KEY,
            _BOOK_VOL_WINDOW_DAYS_KEY,
        )
    )
    for key in raw:
        if key not in allowed:
            raise EvaluationConfigError(
                f"{EVALUATION_CONFIG_CODE}: {key!r} is not a key of "
                f"{BOOK_KEY!r} (the keys are {', '.join(sorted(allowed))}); "
                f"an unknown key inside {BOOK_KEY!r} is refused rather "
                "than read past"
            )
    if _BOOK_BETA_NEUTRAL_KEY not in raw:
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: {_BOOK_BETA_NEUTRAL_KEY!r} is "
            f"missing from {BOOK_KEY!r} at {named!r}; there is no default "
            "— a book block without it does not say whether the book is "
            "rescaled"
        )
    beta_neutral = raw[_BOOK_BETA_NEUTRAL_KEY]
    if not isinstance(beta_neutral, bool):
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: {BOOK_KEY}.{_BOOK_BETA_NEUTRAL_KEY} "
            f"must be a boolean, got {beta_neutral!r} "
            f"({type(beta_neutral).__name__})"
        )
    window_raw = raw.get(_BOOK_BETA_WINDOW_DAYS_KEY, DEFAULT_BETA_WINDOW_DAYS)
    if (
        isinstance(window_raw, bool)
        or not isinstance(window_raw, int)
        or window_raw < 1
    ):
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: {BOOK_KEY}.{_BOOK_BETA_WINDOW_DAYS_KEY} "
            f"must be a positive integer (a count of daily returns), got "
            f"{window_raw!r} ({type(window_raw).__name__})"
        )
    benchmark_raw = raw.get(_BOOK_BETA_BENCHMARK_KEY, DEFAULT_BETA_BENCHMARK)
    if not isinstance(benchmark_raw, str) or not benchmark_raw.strip():
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: {BOOK_KEY}.{_BOOK_BETA_BENCHMARK_KEY} "
            f"must be a non-blank symbol string, got {benchmark_raw!r} "
            f"({type(benchmark_raw).__name__})"
        )
    weighting_raw = raw.get(_BOOK_WEIGHTING_KEY, DEFAULT_BOOK_WEIGHTING)
    if not isinstance(weighting_raw, str) or weighting_raw not in BOOK_WEIGHTINGS:
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: {BOOK_KEY}.{_BOOK_WEIGHTING_KEY} must "
            f"be one of {', '.join(repr(name) for name in BOOK_WEIGHTINGS)}, "
            f"got {weighting_raw!r}; the weighting is the whole book's "
            "construction — 'z' weights each name by its own score, "
            f"'{INVERSE_VOL_WEIGHTING}' divides each score by its own "
            "symbol's realised volatility first, "
            f"'{TAIL_DECILE_WEIGHTING}' goes long each date's top score "
            "decile and short its bottom decile at equal weight within each "
            f"leg, and '{SHORT_TAIL_WEIGHTING}' shorts each date's bottom "
            "score decile at equal weight and holds every other scored name "
            "long at equal weight — and a value outside that closed set is "
            "refused rather than guessed, because running a weighting the "
            "document never named would measure a portfolio the campaign "
            "did not configure"
        )
    vol_window_raw = raw.get(
        _BOOK_VOL_WINDOW_DAYS_KEY, DEFAULT_VOL_WINDOW_DAYS
    )
    if (
        isinstance(vol_window_raw, bool)
        or not isinstance(vol_window_raw, int)
        or vol_window_raw < MIN_VOL_WINDOW_DAYS
    ):
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: "
            f"{BOOK_KEY}.{_BOOK_VOL_WINDOW_DAYS_KEY} must be an integer of "
            f"at least {MIN_VOL_WINDOW_DAYS} (a count of daily returns), "
            f"got {vol_window_raw!r} ({type(vol_window_raw).__name__}); a "
            "volatility over a shorter window is noise the whole book's "
            "weights would be divided by"
        )
    return BookConfig(
        beta_neutral=beta_neutral,
        beta_window_days=window_raw,
        beta_benchmark=benchmark_raw,
        weighting=weighting_raw,
        vol_window_days=vol_window_raw,
    )


def _instrument(document: Mapping[str, Any], named: str) -> str:
    """Which book this evaluation prices — :data:`DEFAULT_INSTRUMENT` when
    :data:`INSTRUMENT_KEY` is absent.

    additions_spec_research_book_v2.xml, the perp instrument feature: *"the
    evaluation config gains an optional key, instrument, with values 'spot'
    (the default, unchanged behaviour) or 'perp'. Any other value is
    refused."*  A present value outside :data:`INSTRUMENTS` is refused by
    name, the same closed-vocabulary stance :func:`_sandbox_runtime` and
    :func:`_evaluation_mode` already take toward their own two-member sets.
    """
    if INSTRUMENT_KEY not in document:
        return DEFAULT_INSTRUMENT
    raw = document[INSTRUMENT_KEY]
    if not isinstance(raw, str) or raw not in INSTRUMENTS:
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: {INSTRUMENT_KEY} must be one of "
            f"{', '.join(repr(name) for name in INSTRUMENTS)}, got {raw!r}; "
            "this evaluation prices either the spot default or a USD-M "
            "perpetual book, and a third spelling is refused rather than "
            "guessed"
        )
    return raw


def _execution(document: Mapping[str, Any], named: str) -> str:
    """Which side this evaluation's turnover is priced as — :data:`DEFAULT_EXECUTION`
    when :data:`EXECUTION_KEY` is absent.

    *"the evaluation config gains an optional top-level key, execution,
    with values 'taker' (default when absent) or 'maker'."*  A present
    value outside :data:`EXECUTIONS` is refused by name, the same
    closed-vocabulary stance :func:`_instrument` and :func:`_evaluation_mode`
    already take toward their own two-member sets.  A ``"maker"`` value
    whose cost model resolves no passive fill model is refused later, once
    the cost model has loaded (see :func:`load_evaluation_context`), naming
    the document rather than this key — the key itself is well-formed.
    """
    if EXECUTION_KEY not in document:
        return DEFAULT_EXECUTION
    raw = document[EXECUTION_KEY]
    if not isinstance(raw, str) or raw not in EXECUTIONS:
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: {EXECUTION_KEY} must be one of "
            f"{', '.join(repr(name) for name in EXECUTIONS)}, got {raw!r}; "
            "this chooses the side a node's turnover is priced as — a "
            "crossing order at the venue's taker fee, or a resting order "
            "at the maker fee plus its queue-position penalty — and a "
            "third spelling is refused rather than guessed"
        )
    return raw


def _metrics_horizon(document: Mapping[str, Any], named: str) -> str:
    """Which horizon the node metrics are measured at —
    :data:`DEFAULT_METRICS_HORIZON` when :data:`METRICS_HORIZON_KEY` is
    absent.

    bug_spec_metrics_horizon.xml bug 2's own rule: the key is optional with
    a closed two-member vocabulary, and a present value outside
    :data:`METRICS_HORIZONS` is refused by name — the same stance
    :func:`_execution`, :func:`_instrument` and the ``"book"`` document's
    own ``weighting`` parser take toward their sets.  A refused spelling
    names the mode, never a horizon: the horizon itself is
    :data:`REQUIRED_KEYS`'s own ``horizon`` key, unchanged.
    """
    if METRICS_HORIZON_KEY not in document:
        return DEFAULT_METRICS_HORIZON
    raw = document[METRICS_HORIZON_KEY]
    if not isinstance(raw, str) or raw not in METRICS_HORIZONS:
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: {METRICS_HORIZON_KEY} must be one "
            f"of {', '.join(repr(name) for name in METRICS_HORIZONS)}, got "
            f"{raw!r}; this chooses which horizon the node metrics are "
            "measured at — the shortest one the priced panel covers, or "
            "the horizon this document's own 'horizon' key configures — "
            "and a third spelling is refused rather than guessed"
        )
    return raw


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


def _futbars_symbols(mount: SnapshotMount, named: str) -> tuple[str, ...]:
    """The symbols the snapshot carries USD-M futures bars for — the
    perp instrument's own roster, the same directory-listing shape
    :func:`_bars_symbols` already takes for the spot default.  Refused when
    the stream is empty: a "perp" instrument with no sealed futbars has no
    perp closes to align targets over at all.
    """
    symbols = mount.partitions(FUTBARS_STREAM)
    if not symbols:
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: snapshot_mount names a snapshot "
            f"carrying no {FUTBARS_STREAM!r} partitions, so there are no "
            f"perp closes to align targets over — {INSTRUMENT_KEY} is "
            f"{PERP_INSTRUMENT!r}, which measures returns off "
            f"{FUTBARS_STREAM!r}'s own ``fut_close`` (never the sealed "
            "bars), and a snapshot without them cannot serve one"
        )
    return symbols


#: One partition's relative path, as the manifest's own ``files`` keys
#: spell it (``"bars/symbol=SYM00/date=2026-09-01/part-0.parquet"``) —
#: group 1 is the symbol, group 2 the ``date=`` directory's own string.
#: Parametrized by stream so the free, manifest-only duplicate check holds
#: for :data:`FUTBARS_STREAM` on exactly the terms it already holds for
#: :data:`BARS_STREAM`.
def _partition_pattern(stream: str) -> re.Pattern[str]:
    return re.compile(rf"^{re.escape(stream)}/symbol=([^/]+)/date=([^/]+)/[^/]+$")


_BARS_PARTITION_RE = _partition_pattern(BARS_STREAM)
_FUTBARS_PARTITION_RE = _partition_pattern(FUTBARS_STREAM)


def _refuse_duplicate_partition_rows(
    manifest: SnapshotManifest,
    named: str,
    *,
    stream: str,
    pattern: re.Pattern[str],
) -> None:
    """Refuse a symbol-day ``stream``'s own manifest row counts show twice.

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
        match = pattern.match(path)
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
            f"whose {stream} carry {symbol!r} on {day.isoformat()} twice; "
            "one bar, one close — the aligner's grain, and a snapshot "
            "that carries two has a staging defect a silent merge would "
            "hide"
        )


def _refuse_duplicate_bars(manifest: SnapshotManifest, named: str) -> None:
    """Refuse a symbol-day the sealed bars carry twice — see
    :func:`_refuse_duplicate_partition_rows`.
    """
    _refuse_duplicate_partition_rows(
        manifest, named, stream=BARS_STREAM, pattern=_BARS_PARTITION_RE
    )


def _refuse_duplicate_futbars(manifest: SnapshotManifest, named: str) -> None:
    """Refuse a symbol-day the sealed futbars carry twice — the perp
    instrument's own counterpart to :func:`_refuse_duplicate_bars`, over
    :data:`FUTBARS_STREAM` instead of :data:`BARS_STREAM`.
    """
    _refuse_duplicate_partition_rows(
        manifest, named, stream=FUTBARS_STREAM, pattern=_FUTBARS_PARTITION_RE
    )


#: Prices already read, keyed by the exact stream, snapshot, symbol and bar
#: day they belong to — the stream is part of the key because a bars close
#: and a futbars ``fut_close`` for the same symbol-day are different prices
#: and must never share a cache entry.  Module-level and never cleared: a
#: second evaluation over the same snapshot in the same process — even
#: through a freshly loaded context, since feature 8 composes one per
#: ``create_app()`` — finds every close it already paid to read, and reads
#: no partition twice.
_CLOSE_CACHE: dict[tuple[str, str, str, dt.date], float] = {}
#: Serializes cache misses, so concurrent node evaluations never read the same
#: close twice (with 8 workers every node missed at once and the archive's
#: 139k closes were read about 8 times over).
_CLOSE_LOCK = threading.Lock()

#: One symbol's whole ``{day: close}`` map, keyed by the exact stream,
#: snapshot and symbol it was read for — the one-pass counterpart to
#: :data:`_CLOSE_CACHE`.  The lake stores a file per symbol-day, so the
#: per-day :func:`_read_close` path paid one ``mount.select`` and one
#: ``pyarrow.parquet.read_table`` *per day*: 331,369 reads for one
#: snapshot's futures closes.  Reading every partition of a symbol in one
#: call answers the identical mapping for one read per symbol.  Module-level
#: and never cleared, like :data:`_CLOSE_CACHE`: a second evaluation over
#: the same snapshot in the same process — even through a freshly loaded
#: context — finds every close it already paid to read.
_SERIES_CACHE: dict[tuple[str, str, str], dict[dt.date, float]] = {}
_SERIES_LOCK = threading.Lock()

#: ``{(stream, snapshot_hash, symbol): (dates, date set)}`` — each symbol's
#: partition listing, read once per process.  A listing is not free: on the
#: archive snapshot :meth:`SnapshotMount.dates` costs about 77 ms, and
#: :class:`_LazyCloses`/:class:`_LazyFunding` hand out a fresh per-symbol
#: mapping on every index, so the beta window and the funding carry (one
#: lookup per date x symbol x day) re-listed the same directory hundreds of
#: thousands of times — a single archP00 root ran for 15+ minutes on
#: listings alone.  The set makes ``day in closes`` O(1) instead of a scan
#: over a 2000-date tuple.  A sealed snapshot's listing never changes.
_DATES_CACHE: dict[tuple[str, str, str], tuple[tuple[dt.date, ...], frozenset[dt.date]]] = {}
_DATES_LOCK = threading.Lock()


def _listed_dates(
    mount: SnapshotMount, stream: str, snapshot_hash: str, symbol: str
) -> tuple[tuple[dt.date, ...], frozenset[dt.date]]:
    """``symbol``'s partition dates in ``stream``, listed once per process."""
    key = (stream, snapshot_hash, symbol)
    try:
        return _DATES_CACHE[key]
    except KeyError:
        pass
    with _DATES_LOCK:
        cached = _DATES_CACHE.get(key)
        if cached is None:
            dates = tuple(
                dt.date.fromisoformat(iso) for iso in mount.dates(stream, symbol)
            )
            cached = (dates, frozenset(dates))
            _DATES_CACHE[key] = cached
        return cached


class _LazySymbolCloses(Mapping[dt.date, float]):
    """One symbol's closes — read and memoized in one pass per symbol.

    The dates this maps are a directory listing
    (:meth:`SnapshotMount.dates`, about 77 ms on the archive), fetched once
    per process through :func:`_listed_dates`; the *prices* are read only
    when a date is actually looked up, and then all of the symbol's
    partitions at once, through :func:`_read_series` — which is where the
    poisoned-close and duplicate-bar refusals a symbol's own partitions can
    still raise now fire: at first use, not at load.  Reading the whole
    symbol rather than one day at a time is the ``_context`` half of the
    same fix ``_evaluate``'s panel cache makes: the lake stores one Parquet
    file per symbol-day, so a per-day loop paid one ``mount.select`` and one
    ``read_table`` per day — 331,369 reads for one snapshot's futures closes
    alone.  Only the *reading* changed: the ``{day: close}`` mapping answered
    is identical (see :meth:`_series`).

    Parametrized by ``stream``/``day_column``/``close_column`` so the perp
    instrument's ``fut_close`` (read from :data:`FUTBARS_STREAM`'s own
    ``date`` column) takes the identical lazy, point-in-time and
    validation rules the spot default's ``close`` (read from
    :data:`BARS_STREAM`'s ``open_time``) already takes — the defaults
    reproduce the spot behaviour exactly.
    """

    __slots__ = (
        "_close_column",
        "_day_column",
        "_mount",
        "_snapshot_hash",
        "_stream",
        "_symbol",
    )

    def __init__(
        self,
        mount: SnapshotMount,
        snapshot_hash: str,
        symbol: str,
        *,
        stream: str = BARS_STREAM,
        day_column: str = "open_time",
        close_column: str = "close",
    ) -> None:
        self._mount = mount
        self._snapshot_hash = snapshot_hash
        self._symbol = symbol
        self._stream = stream
        self._day_column = day_column
        self._close_column = close_column

    def _listing(self) -> tuple[tuple[dt.date, ...], frozenset[dt.date]]:
        return _listed_dates(
            self._mount, self._stream, self._snapshot_hash, self._symbol
        )

    def _available(self) -> tuple[dt.date, ...]:
        return self._listing()[0]

    def __contains__(self, day: object) -> bool:
        return isinstance(day, dt.date) and day in self._listing()[1]

    def _series(self) -> dict[dt.date, float]:
        """This symbol's whole ``{day: close}`` map, read once per process.

        The one-pass read this class's docstring promises: every one of the
        symbol's partitions read together on first access, rather than one
        ``mount.select`` plus one ``pyarrow.parquet.read_table`` per day.
        The per-day shape answered is identical — the same keys, the same
        parsed floats, the same poisoned-close and duplicate-row refusals —
        it is the *reading* that stops being per-day.

        Memoized in :data:`_SERIES_CACHE` under one entry per
        (stream, snapshot, symbol), so a second context over the same
        snapshot in the same process — every ``create_app()`` — finds the
        whole map already read.

        **Why this reader may keep its one-pass read when the panel cache
        may not.**  Reading a symbol's whole series is only a defect when
        it reads a date the caller is not allowed to see.  Nothing that
        reaches this mapping is point-in-time bounded by a single
        rebalance date: ``align_targets`` needs the *forward* return
        ``close[d+h] / close[d] − 1`` — a bar demonstrably after the
        rebalance date, which is the label, not a leak — and the
        beta/volatility windows step *backward* from ``D`` through
        :func:`_beta_window_dates`, taking only the trailing dates they
        name.  The signal never sees ``closes``; the sandbox is handed the
        materialized feature frames instead, and those are bounded by
        :class:`orchestrator._evaluate._PanelCache`'s forward-growing read.
        So the symbol's own sealed series is exactly what every caller here
        is allowed to see, and reading it in one pass is safe.  A future
        caller that indexed ``closes`` from *inside* a per-date signal
        feature would change that answer, and would have to grow forward
        the way the panel cache does.
        """
        cache_key = (self._stream, self._snapshot_hash, self._symbol)
        with _SERIES_LOCK:
            cached = _SERIES_CACHE.get(cache_key)
            if cached is not None:
                return cached
            series = _read_series(
                self._mount,
                self._symbol,
                self._available(),
                stream=self._stream,
                day_column=self._day_column,
                close_column=self._close_column,
            )
            _SERIES_CACHE[cache_key] = series
            return series

    def __getitem__(self, day: dt.date) -> float:
        if day not in self._listing()[1]:
            raise KeyError(day)
        try:
            return self._series()[day]
        except KeyError:
            raise KeyError(day) from None

    def __iter__(self) -> Iterator[dt.date]:
        return iter(self._available())

    def __len__(self) -> int:
        return len(self._available())


class _LazyCloses(Mapping[str, Mapping[dt.date, float]]):
    """Step 4's ``closes`` — one :class:`_LazySymbolCloses` per symbol,
    built from the roster :func:`_bars_symbols` (or, for the perp
    instrument, :func:`_futbars_symbols`) already paid a directory
    listing for at load.  Nothing past that listing is read until a
    caller indexes a specific symbol and date, so a context answers the
    same full mapping :func:`_closes` used to build eagerly, but reads
    only the partitions whoever consumes ``closes`` actually touches.
    """

    __slots__ = (
        "_close_column",
        "_day_column",
        "_mount",
        "_snapshot_hash",
        "_stream",
        "_symbols",
    )

    def __init__(
        self,
        mount: SnapshotMount,
        snapshot_hash: str,
        symbols: tuple[str, ...],
        *,
        stream: str = BARS_STREAM,
        day_column: str = "open_time",
        close_column: str = "close",
    ) -> None:
        self._mount = mount
        self._snapshot_hash = snapshot_hash
        self._symbols = symbols
        self._stream = stream
        self._day_column = day_column
        self._close_column = close_column

    def __contains__(self, symbol: object) -> bool:
        return symbol in self._symbols

    def __getitem__(self, symbol: str) -> Mapping[dt.date, float]:
        if symbol not in self._symbols:
            raise KeyError(symbol)
        return _LazySymbolCloses(
            self._mount,
            self._snapshot_hash,
            symbol,
            stream=self._stream,
            day_column=self._day_column,
            close_column=self._close_column,
        )

    def __iter__(self) -> Iterator[str]:
        return iter(self._symbols)

    def __len__(self) -> int:
        return len(self._symbols)


def _read_close(
    mount: SnapshotMount,
    symbol: str,
    day: dt.date,
    *,
    stream: str = BARS_STREAM,
    day_column: str = "open_time",
    close_column: str = "close",
) -> float:
    """One symbol-day's close, read from its own partition.

    The content half of the original eager read, scoped to the single
    ``(symbol, day)`` a lazy lookup asked for: the venue's string
    spelling of a close is parsed to the finite positive float step 4
    validates (a price that is not a positive finite number poisons every
    forward return measured off it), keyed by the row's own ``day_column``
    date — the candle's day, not the partition's name, so a partition
    holding a row of another day still lands where the bar says it
    belongs.  A second row for this ``(symbol, day)`` is refused rather
    than merged, the same "one bar, one close" law
    :func:`_refuse_duplicate_partition_rows` already checked for free
    across the whole snapshot — held here too, for the partitions that
    check could not see into (an unknown row count).  ``day`` absent from
    this partition's own rows answers :class:`KeyError`, like any other
    missing mapping key.

    ``stream``/``day_column``/``close_column`` default to the spot bars'
    own spelling; the perp instrument calls this with
    :data:`FUTBARS_STREAM`, ``"date"`` and ``"fut_close"`` instead — the
    same function, the same rules, a different column spelling.
    """
    iso = day.isoformat()
    series = _close_series(
        mount.select(stream, symbol, iso),
        mount,
        symbol,
        stream=stream,
        day_column=day_column,
        close_column=close_column,
    )
    if day not in series:
        raise KeyError(day)
    return series[day]


def _read_series(
    mount: SnapshotMount,
    symbol: str,
    days: Sequence[dt.date],
    *,
    stream: str = BARS_STREAM,
    day_column: str = "open_time",
    close_column: str = "close",
) -> dict[dt.date, float]:
    """Every close of one symbol, read in one pass over all its partitions.

    The one-pass counterpart to :func:`_read_close`: ``days`` is the
    symbol's own partition listing (:func:`_listed_dates`), and every one
    of those partitions is read together — one ``mount.select`` per day
    (the directory listing the mount already provides) collected into one
    :func:`_read_part` call, rather than one call per day.  The answered
    mapping is identical to what a loop of :func:`_read_close` calls would
    have built, because both go through :func:`_close_series`: the same
    finite-positive validation, the same "one bar, one close" duplicate
    refusal, the same row's-own-``day_column`` keying.
    """
    parts = [
        part for day in days for part in mount.select(stream, symbol, day.isoformat())
    ]
    return _close_series(
        parts,
        mount,
        symbol,
        stream=stream,
        day_column=day_column,
        close_column=close_column,
    )


def _close_series(
    parts: Sequence[object],
    mount: SnapshotMount,
    symbol: str,
    *,
    stream: str,
    day_column: str,
    close_column: str,
) -> dict[dt.date, float]:
    """Parse ``parts`` into ``{bar day: close}``, with every same refusal.

    The content half shared by :func:`_read_close` and :func:`_read_series`:
    the venue's string spelling of a close is parsed to the finite positive
    float step 4 validates (a price that is not a positive finite number
    poisons every forward return measured off it), keyed by the row's own
    ``day_column`` date — the candle's day, not the partition's name, so a
    partition holding a row of another day still lands where the bar says it
    belongs.  A second row for one ``(symbol, day)`` is refused rather than
    merged, the same "one bar, one close" law
    :func:`_refuse_duplicate_partition_rows` already checked for free across
    the whole snapshot — held here too, for the partitions that check could
    not see into (an unknown row count).
    """
    parts = list(parts)
    series: dict[dt.date, float] = {}
    if not parts:
        return series
    table = _read_part(parts, symbol)
    if day_column not in table.column_names:
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: snapshot_mount names "
            f"a snapshot whose {parts[0]!s} carries no "
            f"{day_column!r} column; a close whose bar day cannot be "
            "read is a close that cannot be keyed"
        )
    if close_column not in table.column_names:
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: snapshot_mount names "
            f"a snapshot whose {parts[0]!s} carries no {close_column!r} "
            "column; the alignment's market grid is the closes of "
            "the scored symbols, and a bar without one is a bar no "
            "target can be measured from"
        )
    for row in table.select([day_column, close_column]).to_pylist():
        moment = row[day_column]
        row_day = moment.date() if isinstance(moment, dt.datetime) else moment
        price = _close_price(row[close_column], symbol, row_day)
        if row_day in series:
            raise EvaluationConfigError(
                f"{EVALUATION_CONFIG_CODE}: snapshot_mount "
                f"names a snapshot whose {stream} carry "
                f"{symbol!r} on {row_day.isoformat()} twice; one "
                "bar, one close — the aligner's grain, and "
                "a snapshot that carries two has a staging "
                "defect a silent merge would hide"
            )
        series[row_day] = price
    return series


# -- The funding carry: a lazy, memoized read beside the closes -----------------


#: Funding values already read, keyed by snapshot, symbol and ingest day —
#: the same memoization shape :data:`_CLOSE_CACHE` takes for closes, so a
#: funding carry summed over several horizons (and several nodes) never
#: re-reads one partition.
_FUNDING_CACHE: dict[tuple[str, str, dt.date], float] = {}
_FUNDING_LOCK = threading.Lock()

#: One symbol's whole ``{ingest day: funding_rate_sum}`` map — the
#: funding twin of :data:`_SERIES_CACHE`, keyed by snapshot and symbol.
_FUNDING_SERIES_CACHE: dict[tuple[str, str], dict[dt.date, float]] = {}


class _LazySymbolFunding(Mapping[dt.date, float]):
    """One symbol's ``funding_rate_sum``, read and memoized one pass per symbol.

    The funding counterpart to :class:`_LazySymbolCloses`: the dates this
    maps are a directory listing (cached per process by
    :func:`_listed_dates`), and the values are read only when
    a date is actually looked up — read then as all of the symbol's
    partitions at once, through :func:`_read_funding_series`, the same
    one-pass read the closes take.  Unlike a close, a funding rate may
    legitimately be negative (a short-pays-long settlement), so the
    validator only demands a finite number — see :func:`_funding_value`.
    """

    __slots__ = ("_mount", "_snapshot_hash", "_symbol")

    def __init__(self, mount: SnapshotMount, snapshot_hash: str, symbol: str) -> None:
        self._mount = mount
        self._snapshot_hash = snapshot_hash
        self._symbol = symbol

    def _listing(self) -> tuple[tuple[dt.date, ...], frozenset[dt.date]]:
        return _listed_dates(
            self._mount, FUNDING_STREAM, self._snapshot_hash, self._symbol
        )

    def _available(self) -> tuple[dt.date, ...]:
        return self._listing()[0]

    def __contains__(self, day: object) -> bool:
        return isinstance(day, dt.date) and day in self._listing()[1]

    def _series(self) -> dict[dt.date, float]:
        """Every ``funding_rate_sum`` of this symbol, read in one pass.

        The funding twin of :class:`_LazySymbolCloses`' own one-pass read:
        all of the symbol's partitions read together on first access
        instead of one ``mount.select`` and one read per day, answering the
        identical ``{ingest day: value}`` mapping under the identical
        refusals (see :func:`_read_funding_series`).  Memoized per
        (snapshot, symbol), so a second funding reader in the same process
        reads nothing again.
        """
        cache_key = (self._snapshot_hash, self._symbol)
        with _FUNDING_LOCK:
            cached = _FUNDING_SERIES_CACHE.get(cache_key)
            if cached is not None:
                return cached
            series = _read_funding_series(
                self._mount, self._symbol, self._available()
            )
            _FUNDING_SERIES_CACHE[cache_key] = series
            return series

    def __getitem__(self, day: dt.date) -> float:
        if day not in self._listing()[1]:
            raise KeyError(day)
        try:
            return self._series()[day]
        except KeyError:
            raise KeyError(day) from None

    def __iter__(self) -> Iterator[dt.date]:
        return iter(self._available())

    def __len__(self) -> int:
        return len(self._available())


class _LazyFunding(Mapping[str, Mapping[dt.date, float]]):
    """``{symbol: {ingest day: funding_rate_sum}}`` — one
    :class:`_LazySymbolFunding` per symbol in :data:`FUNDING_STREAM`'s
    roster, the same lazy shape :class:`_LazyCloses` already takes.  A
    symbol with no sealed funding row at all (no perpetual, or a snapshot
    that never backfilled the stream) is simply absent — every reader of
    this mapping treats a missing symbol or a missing day as a zero carry,
    never a refusal (see :mod:`orchestrator._evaluate`'s
    ``_cost_schedule_from_context``).
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
        return _LazySymbolFunding(self._mount, self._snapshot_hash, symbol)

    def __iter__(self) -> Iterator[str]:
        return iter(self._symbols)

    def __len__(self) -> int:
        return len(self._symbols)


def _funding_value(raw: Any, symbol: str, day: dt.date) -> float:
    """One ``funding_rate_sum``, as a finite float — any sign.

    Unlike a close (:func:`_close_price`), a funding settlement is
    legitimately negative (shorts pay longs when the rate is negative), so
    this validator demands only that the value is a finite number, parsed
    from the venue's own string spelling the same way a close is.
    """
    if isinstance(raw, bool):
        value: float | None = None
    elif isinstance(raw, str):
        try:
            value = float(raw.strip())
        except ValueError:
            value = None
    elif isinstance(raw, (int, float)):
        value = float(raw)
    else:
        value = None
    if value is None or not math.isfinite(value):
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: snapshot_mount names a snapshot "
            f"whose funding_rate_sum for {symbol!r} on {day.isoformat()} "
            f"is not a finite number, got {raw!r}; the funding carry sums "
            "this value over the horizon's holding days, and a NaN or "
            "±inf would poison every node's charge measured off it"
        )
    return value


def _read_funding_rate_sum(mount: SnapshotMount, symbol: str, day: dt.date) -> float:
    """One symbol-day's ``funding_rate_sum``, read from its own partition.

    The funding counterpart to :func:`_read_close`: keyed by the row's own
    ``date`` column (the ingest day :mod:`nullius_ingest.derivs_backfill`
    already buckets settlements into), with the same "one row, one value"
    duplicate refusal.
    """
    iso = day.isoformat()
    series = _funding_series(
        mount.select(FUNDING_STREAM, symbol, iso), symbol, stream=FUNDING_STREAM
    )
    if day not in series:
        raise KeyError(day)
    return series[day]


def _read_funding_series(
    mount: SnapshotMount, symbol: str, days: Sequence[dt.date]
) -> dict[dt.date, float]:
    """Every ``funding_rate_sum`` of one symbol, read in one pass.

    The one-pass counterpart to :func:`_read_funding_rate_sum`: ``days`` is
    the symbol's own funding partition listing, and every partition is read
    together in one :func:`_read_part` call instead of one per day.  The
    answered mapping is identical, because both go through
    :func:`_funding_series` — the same finite-number validation and the same
    "one settlement window, one value" duplicate refusal.
    """
    parts = [
        part
        for day in days
        for part in mount.select(FUNDING_STREAM, symbol, day.isoformat())
    ]
    return _funding_series(parts, symbol, stream=FUNDING_STREAM)


def _funding_series(
    parts: Sequence[object], symbol: str, *, stream: str
) -> dict[dt.date, float]:
    """Parse ``parts`` into ``{ingest day: funding_rate_sum}``.

    Keyed by the row's own ``date`` column (the ingest day
    :mod:`nullius_ingest.derivs_backfill` already buckets settlements into),
    with the same "one row, one value" duplicate refusal.
    """
    parts = list(parts)
    series: dict[dt.date, float] = {}
    if not parts:
        return series
    table = _read_part(parts, symbol)
    if "date" not in table.column_names:
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: snapshot_mount names a "
            f"snapshot whose {parts[0]!s} carries no 'date' column; a "
            "funding row whose own ingest day cannot be read is a "
            "settlement that cannot be keyed"
        )
    if "funding_rate_sum" not in table.column_names:
        raise EvaluationConfigError(
            f"{EVALUATION_CONFIG_CODE}: snapshot_mount names a "
            f"snapshot whose {parts[0]!s} carries no 'funding_rate_sum' "
            "column; the funding carry sums this value over the "
            "holding window, and a row without one is a row no carry "
            "can be measured from"
        )
    for row in table.select(["date", "funding_rate_sum"]).to_pylist():
        moment = row["date"]
        row_day = moment.date() if isinstance(moment, dt.datetime) else moment
        value = _funding_value(row["funding_rate_sum"], symbol, row_day)
        if row_day in series:
            raise EvaluationConfigError(
                f"{EVALUATION_CONFIG_CODE}: snapshot_mount names a "
                f"snapshot whose {stream} carries {symbol!r} on "
                f"{row_day.isoformat()} twice; one settlement window, "
                "one funding_rate_sum — a snapshot that carries two "
                "has a staging defect a silent merge would hide"
            )
        series[row_day] = value
    return series


def _read_part(part: object, symbol: str) -> Any:
    """Read one Parquet part — or a whole symbol's parts — in a single call.

    ``part`` may be a single read-only path (one day's part) or a sequence
    of paths (every partition of one symbol).  A sequence goes to one
    :func:`pyarrow.parquet.read_table` over the whole list, which is the
    one-pass read the lazy readers take instead of one call per day: the
    lake stores a file per symbol-day, so a per-day loop paid one call per
    (symbol, day) — 331,369 of them for one snapshot's futures closes
    alone.  The answered table is the concatenation of those files' rows,
    in the order the paths were given.

    ``partitioning=None`` is load-bearing: the lake's paths are Hive-shaped
    (``symbol=…/date=…/part-0.parquet``), so pyarrow's dataset inference
    would read the directory names as partition keys — and these files
    already carry their own day/``symbol`` columns, so the inferred
    dictionary-typed partition column collides with the file's own string
    column and the read fails outright.  Disabling inference makes the call
    a plain concatenation of the named files.

    Split out so an unreadable part is one refusal with one shape: the
    configuration named a snapshot whose bytes cannot be read, and the
    operator's remedy is the snapshot, not the loader.  pyarrow's
    malformed-file and unreadable-path failures derive from
    :class:`ValueError` and :class:`OSError` respectively, so those are
    the two shapes translated — anything else is a defect worth seeing
    whole, not a configuration fact.
    """
    import pyarrow.parquet as pq  # lazy: the evaluator's own reader idiom

    if isinstance(part, (str, bytes)) or hasattr(part, "__fspath__"):
        paths = [str(part)]
    else:
        paths = [str(one) for one in part]  # type: ignore[union-attr]
    try:
        return pq.read_table(paths, partitioning=None)
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


# -- The configured book: point-in-time betas and vols, from context.closes -----


def _beta_window_dates(end: dt.date, window_days: int) -> tuple[dt.date, ...]:
    """The ``window_days`` calendar dates ending at and including ``end``.

    Never a date after ``end`` — the point-in-time discipline
    :func:`compute_betas` and :func:`compute_vols` hold throughout: a figure
    for ``end`` is measured only over returns whose own entry and exit dates
    are both at or before it.
    """
    return tuple(
        end - dt.timedelta(days=offset) for offset in range(window_days - 1, -1, -1)
    )


def _close_to_close_returns(
    closes: Mapping[dt.date, float], window: Sequence[dt.date]
) -> dict[dt.date, float]:
    """One symbol's daily close-to-close returns over ``window``.

    A date contributes a return only when both it and the prior calendar
    day are present in ``closes``; a gap (a delisting, a not-yet-listed
    symbol, a missing partition) simply contributes nothing, rather than
    an interpolated or fabricated value.
    """
    returns: dict[dt.date, float] = {}
    for day in window:
        prior = day - dt.timedelta(days=1)
        if day in closes and prior in closes:
            returns[day] = closes[day] / closes[prior] - 1.0
    return returns


def _ols_slope(
    x_returns: Mapping[dt.date, float], y_returns: Mapping[dt.date, float]
) -> float | None:
    """The OLS slope of ``y`` on ``x``, over the dates both carry a return for.

    ``None`` when fewer than two dates pair (a slope needs at least two
    points) or ``x``'s paired returns carry no variance (a flat benchmark
    window divides by zero) — both read as "no beta", never a fabricated
    number.
    """
    paired = [day for day in y_returns if day in x_returns]
    if len(paired) < 2:
        return None
    xs = [x_returns[day] for day in paired]
    ys = [y_returns[day] for day in paired]
    mean_x = math.fsum(xs) / len(xs)
    mean_y = math.fsum(ys) / len(ys)
    covariance = math.fsum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    variance = math.fsum((x - mean_x) ** 2 for x in xs)
    if variance == 0.0:
        return None
    return covariance / variance


#: The fraction of a beta window's returns a symbol must carry to be rated
#: at all — additions_spec_research_book_v2.xml feature 2: "a symbol needs
#: at least 80% of the window's returns, otherwise it has no beta for D."
#: Compared as ``count * _BETA_COVERAGE_DENOMINATOR >=
#: window_days * _BETA_COVERAGE_NUMERATOR`` (4/5), rather than a float
#: ratio, so the threshold is exact for every integer window length.
_BETA_COVERAGE_NUMERATOR: Final[int] = 4
_BETA_COVERAGE_DENOMINATOR: Final[int] = 5


def _betas_for_date(
    context: EvaluationContext, day: dt.date, symbols: Iterable[str]
) -> Mapping[str, float]:
    """``{symbol: beta}`` for ``day``, among ``symbols`` — point-in-time.

    ``{}`` when the configured benchmark carries no entry in
    ``context.closes`` at all (feature 2: "If the benchmark is absent, there
    are no betas for D"), or when it carries no close-to-close return in the
    window.  Otherwise each symbol with at least
    :data:`_BETA_COVERAGE_NUMERATOR`/:data:`_BETA_COVERAGE_DENOMINATOR` of the
    window's returns gets the OLS slope of its own returns on the
    benchmark's (:func:`_ols_slope`); every other symbol — thin coverage, or
    a degenerate (flat-benchmark) regression — is simply absent from the
    answer, never a fabricated value.
    """
    book = context.book
    benchmark = book.beta_benchmark
    if benchmark not in context.closes:
        return {}
    window = _beta_window_dates(day, book.beta_window_days)
    benchmark_returns = _close_to_close_returns(context.closes[benchmark], window)
    if not benchmark_returns:
        return {}
    betas: dict[str, float] = {}
    for symbol in symbols:
        if symbol not in context.closes:
            continue
        symbol_returns = _close_to_close_returns(context.closes[symbol], window)
        if (
            len(symbol_returns) * _BETA_COVERAGE_DENOMINATOR
            < book.beta_window_days * _BETA_COVERAGE_NUMERATOR
        ):
            continue
        beta = _ols_slope(benchmark_returns, symbol_returns)
        if beta is not None:
            betas[symbol] = beta
    return betas


def compute_betas(
    context: EvaluationContext, scores: Mapping[dt.date, Mapping[str, float]]
) -> Mapping[dt.date, Mapping[str, float]]:
    """Point-in-time betas for every date ``scores`` names a symbol for.

    additions_spec_research_book_v2.xml feature 2: for each date ``D`` in
    ``scores``, a symbol's beta is the OLS slope of its own daily
    close-to-close returns on ``context.book.beta_benchmark``'s, over the
    trailing ``context.book.beta_window_days`` daily returns ending at
    ``D`` — read from ``context.closes``, so the instrument in force
    (:data:`SPOT_INSTRUMENT`'s bars close, or :data:`PERP_INSTRUMENT`'s
    ``fut_close``) is what every beta is measured against, and never a row
    after ``D`` (see :func:`_beta_window_dates`).
    A date with no scored symbol (``scores[day]`` empty — a thin or
    no-preference rebalance date) is skipped: there is no book on it for a
    beta to rescale.

    This is a pure read of ``context`` and ``scores``; it does not consult
    ``context.book.beta_neutral`` — :func:`orchestrator._evaluate.evaluate_node`
    and :func:`~orchestrator._evaluate.evaluate_on_dates` are what decide
    whether to call it at all, so a context whose book is not beta-neutral
    never pays for this computation.
    """
    return {
        day: _betas_for_date(context, day, row) for day, row in scores.items() if row
    }


#: The fraction of a vol window's returns a symbol must carry to be measured
#: at all — half the window, compared as ``count * 2 >= vol_window_days``
#: rather than a float ratio so the threshold is exact for odd window
#: lengths.  A symbol under it gets *no* volatility (it is simply absent
#: from that date's row) — one of the two "no vol" outcomes
#: :func:`compute_vols` documents; a measured volatility that is not finite
#: or not strictly positive is the other.
_VOL_COVERAGE_DENOMINATOR: Final[int] = 2


def _population_std(values: Iterable[float]) -> float:
    """The population standard deviation (``ddof=0``) of ``values``.

    The whole window's dispersion, not a sample estimate of a larger one:
    the window *is* the population the vol is asked to describe, and the
    metrics side consumes the scale as-is — nothing downstream re-counts the
    returns or re-scales the answer.
    """
    items = list(values)
    mean = math.fsum(items) / len(items)
    variance = math.fsum((value - mean) ** 2 for value in items) / len(items)
    return math.sqrt(variance)


def _vols_for_date(
    context: EvaluationContext, day: dt.date, symbols: Iterable[str]
) -> Mapping[str, float]:
    """``{symbol: vol}`` for ``day``, among ``symbols`` — point-in-time.

    The same date and symbol handling :func:`_betas_for_date` takes: the
    window is :func:`_beta_window_dates`' own trailing dates ending at
    ``day`` (never a return after it), a symbol ``context.closes`` does not
    carry is skipped, and the returns are :func:`_close_to_close_returns`'s
    own — a date both closes must be present for, gaps contributing nothing.
    A symbol whose volatility cannot be measured is *absent from the answer*
    rather than given a default vol, and there are two such cases — the same
    "no vol" outcome, so a consumer sees one rule rather than two:

    * fewer than half the window's returns exist (the coverage rule above —
      a thin history, or a symbol that only starts trading mid-window); and
    * the window's returns measure a volatility that is not finite or not
      strictly positive.  A complete window of *identical* closes — a
      perpetual delisted in place, its archived ``fut_close`` frozen — gives a
      population standard deviation of exactly ``0.0``, and a volatility of
      zero is not a positive scale: dividing a score by it would drop the name
      or hand it an infinite weight, which is why
      :func:`evaluator.book_weights` refuses one by name.  Emitting it from
      here would make the whole day's book refuse over one untradeable name;
      leaving it out lets :func:`evaluator.compute_node_metrics` drop that
      name from the day's book and renormalise the rest.

    What the omission means to a consumer is stated once, at
    :func:`compute_vols`: this function answers "whose volatility could be
    measured", never "a volatility for every symbol asked about".
    """
    window_days = context.book.vol_window_days
    window = _beta_window_dates(day, window_days)
    vols: dict[str, float] = {}
    for symbol in symbols:
        if symbol not in context.closes:
            continue
        returns = _close_to_close_returns(context.closes[symbol], window)
        if len(returns) * _VOL_COVERAGE_DENOMINATOR < window_days:
            continue
        vol = _population_std(returns.values())
        if not math.isfinite(vol) or vol <= 0.0:
            continue
        vols[symbol] = vol
    return vols


def compute_vols(
    context: EvaluationContext, scores: Mapping[dt.date, Mapping[str, float]]
) -> Mapping[dt.date, Mapping[str, float]]:
    """Point-in-time realised volatilities for every date ``scores`` names a
    symbol for.

    For each date ``D`` in ``scores``, a symbol's volatility is the
    population standard deviation of its own daily close-to-close returns
    over the trailing ``context.book.vol_window_days`` returns ending at
    ``D`` — read from ``context.closes``, so the instrument in force
    (:data:`SPOT_INSTRUMENT`'s bars close, or :data:`PERP_INSTRUMENT`'s
    ``fut_close``) is what every vol is measured against, and never a row
    after ``D`` (see :func:`_beta_window_dates`).  A date with no scored
    symbol is skipped, the same stance :func:`compute_betas` takes: there is
    no book on it for a vol to scale.

    A symbol whose volatility this function cannot measure is **absent from
    that date's row**, and the consumer's rule is one rule with one spelling:

    * fewer than half the window's returns exist — a thin history, or a
      symbol only listed part of the window; and
    * the window's returns measure a volatility that is not finite or not
      strictly positive — a complete window of identical closes, which is
      what a perpetual delisted in place looks like, gives a population
      standard deviation of exactly ``0.0``.

    Both are "no vol", and the row is the answer to "whose volatility could be
    measured", never "a volatility for every symbol asked about".
    :func:`evaluator.compute_node_metrics` drops a name the row does not carry
    from that date's book and renormalises the survivors (recording the count
    in ``NodeMetrics.vol_dropped``), so one frozen perp costs the book one
    name rather than the whole evaluation; :func:`evaluator.book_weights`,
    called directly with a row like this one, still refuses a scored symbol
    the row does not name, because a caller who assembled an incomplete row by
    hand has made an error worth naming.

    Like :func:`compute_betas`, this is a pure read of ``context`` and
    ``scores``; it does not consult ``context.book.weighting`` —
    :func:`orchestrator._evaluate.evaluate_node` and
    :func:`~orchestrator._evaluate.evaluate_on_dates` are what decide
    whether to call it at all, so a context whose book is z-weighted never
    pays for this computation.
    """
    return {
        day: _vols_for_date(context, day, row) for day, row in scores.items() if row
    }


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
