"""Executing a signal over a resolved window — pipeline step 2.

app_spec.xml feature 73: *"System executes the signal function inside the
sandbox, which returns a raw score vector per rebalance date."*
docs/nullius-tech-architecture.md §6.1 names the step —
``2. execute_signal (sandbox) → raw score vector per rebalance date`` — and
§5.2 shows the call it makes:

    window = materialize_window(snapshot, t, lookback=L, universe=U)   # HOST side, Z0
    result = sandbox.run(entrypoint="signal", code=node.code,
                         payload=window.to_arrow(), limits=…, seed=node.seed)

Two words in the feature carry the design, and each has a consequence this
module enforces:

*executes the signal function inside the sandbox*
    The signal is LLM-authored, so it runs in the resource-limited child
    process :mod:`evaluator._sandbox` provides — never in the host, never in a
    thread.  The window is materialized, serialized to an Arrow IPC payload
    (feature 14, §5.2's ``payload=window.to_arrow()``), handed to the sandbox
    over the payload channel, and the raw score vector comes back.  The
    sandbox is injectable here (a :data:`SignalSandbox`, or a stub in a test),
    so the orchestration is testable without spawning a process, and a gVisor
    deployment can substitute its own runner underneath.

*per rebalance date*
    The plural is load-bearing.  A signal is scored at every rebalance date in
    the window — the grid §6.1 step 1's resolution names — so the signal runs
    **once per rebalance date**, each execution over a window sliced to that
    date's decision time, and the result is keyed by rebalance date.  A single
    execution would be a different and worse feature: it would score the signal
    at one instant and call it a vector, when the feature is a *map* of dates
    to vectors.

**The materialize seam, and why it is injected.**  §6.1 step 1
(``materialize_window(snapshot, t, lookback=L, universe=U)``) is the sibling
that reads the sealed lake into frames — and it does not live in this module,
because reading the lake is a separate step from executing the signal.  So
:func:`execute_signal` takes a ``materialize`` callable that turns a
``(resolution, decision_time)`` into a :class:`~contract.window.MarketWindow`,
defaulting to a host-side reader that pulls the resolution's *surviving*
partitions into Arrow frames.  The default is deliberately minimal and
testable — it reads only the partitions the resolution already named as
surviving at or before the decision time, so it cannot serve a date past
``t`` — and the production reader (over a real ``SnapshotMount``) is injected
by the feature that owns the lake read.  The seam keeps sandbox execution
independent of lake reading, exactly as the two §6.1 steps are separate.

**What this module does not do, and why the boundary matters.**  It returns
*raw* scores — it does not normalize them (feature 74), align targets (feature
75), apply costs (feature 79), or persist them.  The contract problems a
signal's return triggers (feature 11/12) are attached to each vector but not
acted upon: :func:`contract.signal.validate_signal_return` is a positive
validator, and the *consequence* of a violation — the ``contract_violation``
outcome — is a downstream feature's decision, not this one's.  This module
answers exactly one question the pipeline puts in scope: *what raw score
vector does this signal produce, at each rebalance date?*

**The layering note.**  This module imports ``polars`` only to type the score
vector; it never constructs one on the host for a conforming return (the
sandbox's child does that), so composing the application — which imports this
member on every factory scan, including the replay path §1 forbids from
reaching the evaluator — pays no polars cost for importing it.  ``contract``
is reached lazily, on the same seam the sandbox and the window use, so the
import stays cheap.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Optional

from ._errors import EvaluatorSignalError
from ._sandbox import SandboxResult, SignalSandbox
from ._window import ROSTER_STREAM, WindowResolution

if TYPE_CHECKING:  # pragma: no cover - typing only; polars/contract are runtime deps
    from contract.signal import SignalReturnProblem

    try:
        import polars as pl
    except ImportError:  # pragma: no cover - polars is a declared runtime dep
        pl = None  # type: ignore[assignment]

__all__ = [
    "RawScoreVector",
    "SignalExecution",
    "execute_signal",
    "pit_universe",
]

#: The default decision instant for a rebalance date: midnight UTC on that
#: date.  The window's accessors truncate rows at ``t`` on every call
#: (features 5 and 6), so the exact instant matters only at the day boundary,
#: and midnight UTC is the honest reading of "score as of this date".
_MIDNIGHT_UTC: dt.time = dt.time(0, 0, tzinfo=dt.timezone.utc)


@dataclass(frozen=True)
class RawScoreVector:
    """One rebalance date's raw scores — the date, the universe, the values.

    The atomic result the sandbox produces: a single execution of the signal
    over the window sliced to one decision time.  The score vector is
    *positional* — the *i*-th value is the score for the *i*-th symbol of the
    universe (feature 11: the window carries the labels, the series carries
    the values, in the window's stable order) — so :attr:`universe` travels
    beside :attr:`scores`; a vector without its labels would be a set of
    numbers no one could align to a symbol.

    The contract problems are carried beside the scores but not acted upon:
    this is the raw-score feature, and the consequence of a violation is a
    downstream feature's decision (feature 12).  A conforming vector has an
    empty :attr:`problems` list; a violating one has ``scores=None`` and a
    populated list, so a caller can tell "the signal returned nothing
    conforming" from "the sandbox failed to run".
    """

    #: The rebalance date this vector was scored at — the key it is filed
    #: under in a :class:`SignalExecution`.
    rebalance_date: dt.date
    #: The decision instant the window was sliced at — the date at midnight
    #: UTC, unless the resolution carried a finer instant.
    decision_time: dt.datetime
    #: The symbols tradable as of the decision time — the labels the
    #: positional :attr:`scores` align to.
    universe: tuple[str, ...]
    #: The seed the signal was executed with.
    seed: int
    #: The signal ABI version the execution ran under.
    contract_version: str
    #: The raw score vector, positional against :attr:`universe`, or ``None``
    #: when the signal did not produce a conforming return.
    scores: Optional["pl.Series"] = None
    #: The contract problems the return triggered — empty when conforming.
    problems: "list[SignalReturnProblem]" = field(default_factory=list)

    @property
    def conforming(self) -> bool:
        """True when the signal returned a conforming score vector at this date."""
        return self.scores is not None and not self.problems


@dataclass(frozen=True)
class SignalExecution:
    """The result of executing a signal across every rebalance date.

    The feature's whole sentence, as a value: the snapshot the window came
    from, the signal's code hash and seed (the two identity terms a persisted
    node carries — feature 15), and the map of rebalance date to raw score
    vector.  "A raw score vector per rebalance date" is this map, and it is a
    read-only mapping captured behind a proxy at construction, so a caller
    keeping the dict it passed cannot add a date to a live execution.
    """

    #: The canonical name of the sealed snapshot the window was sliced from —
    #: the provenance a persisted result needs to say *which* sealed world its
    #: scores came from.
    snapshot_name: str
    #: The sha256 of the signal source — the code's identity, persisted
    #: alongside the contract version on the node (§15's ABI term).
    code_hash: str
    #: The seed every execution ran with.
    seed: int
    #: The raw score vectors, keyed by rebalance date — one per date.
    vectors: Mapping[dt.date, RawScoreVector]

    def __post_init__(self) -> None:
        # Captured behind a read-only proxy: the map of dates to vectors is a
        # settled record, and a caller keeping the dict it passed must not be
        # able to add a date to a live execution.
        if not isinstance(self.vectors, Mapping):
            raise EvaluatorSignalError(
                "vectors must be a mapping of rebalance date to score vector, got "
                f"{type(self.vectors).__name__}"
            )
        object.__setattr__(self, "vectors", MappingProxyType(dict(self.vectors)))

    def dates(self) -> tuple[dt.date, ...]:
        """The rebalance dates this execution scored, in ascending order."""
        return tuple(sorted(self.vectors))

    def vector(self, rebalance_date: dt.date) -> Optional[RawScoreVector]:
        """The raw score vector at one rebalance date, or ``None`` if absent.

        Empty for a date the execution did not score — the miss reported as
        nothing, on the same principle as the contract's accessors: an absent
        date cannot leak a nearest date's scores.
        """
        return self.vectors.get(rebalance_date)


def _sha256_hex(code: str) -> str:
    """The sha256 of the signal source, as the node's code identity (§15)."""
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _default_rebalance_dates(resolution: WindowResolution) -> tuple[dt.date, ...]:
    """The rebalance grid a resolution names: its surviving **bars** dates.

    The natural rebalance schedule is the bars partitions the resolution kept
    — the candle dates at or before the decision time, which is where a
    bar-driven signal rebalances.  Resolved from the bars stream only (the
    roster stream — feature 72's :data:`~evaluator.ROSTER_STREAM`), because
    the universe is a bars question and the rebalance grid is the same one:
    a symbol is tradable and the market rebalances on the days the bars are
    there.  Sorted ascending, so the execution's dates are in a stable order
    whatever order the resolution enumerated them in.

    Refused when the resolution carries no surviving bars dates: with no bars
    there is no rebalance grid to score at, and scoring at no date is not the
    feature.  A resolution with bars but no surviving date is the empty-
    universe case feature 72 distinguishes — present but silent — and that
    resolves to *no dates*, which this refuses for the same reason a window
    over data that stops before its decision time is refused: there is nothing
    to score.
    """
    # Gather the bars dates across every symbol the resolution kept for bars,
    # de-duplicated.  ``resolution.slices["bars"]`` is ``{symbol: (ISO dates,)}``
    # — the surviving partitions feature 72 already sliced to at or before t.
    bars = resolution.slices.get("bars", {})
    kept: set[dt.date] = set()
    for isos in bars.values():
        for iso in isos:
            kept.add(dt.date.fromisoformat(iso))
    if not kept:
        raise EvaluatorSignalError(
            f"resolution {resolution.snapshot_name!r} carries no surviving bars "
            "partitions, so there is no rebalance grid to score the signal at — "
            "the rebalance dates are the surviving bars dates (docs §6.1), and a "
            "resolution without bars cannot say when to rebalance"
        )
    return tuple(sorted(kept))


def pit_universe(resolution: WindowResolution, decision_date: dt.date) -> tuple[str, ...]:
    """The point-in-time universe for one rebalance date — feature 72's rule,
    applied per date rather than once at the resolution's own decision time.

    A resolution is sliced to a single instant, but a multi-date execution
    scores every rebalance date in its grid, and a symbol tradable on the
    resolution's own decision date is not necessarily tradable on an earlier
    one (it may not have been listed yet) or, for a date between two others,
    on a later one (it may since have been delisted). Feature 72's admission
    rule is day-granular and stated once in :mod:`evaluator._window`: a
    symbol is tradable on a day exactly when its sealed bars carry a
    partition dated that day. Applying it again here, per date, is what
    ``execute_signal`` needs so that each :class:`RawScoreVector` carries the
    universe that was actually alive on *its* date, not the resolution's.

    Answered entirely from ``resolution.slices[ROSTER_STREAM]`` — the
    surviving bars partitions at or before the resolution's own decision
    date, which is already a superset of what any earlier rebalance date
    needs (every date this is called for is at or before that same decision
    date). No further snapshot read is needed: the resolution named every
    surviving partition once, and this is a pure lookup over that record.

    Sorted, the same stable ordering feature 46 pins for the resolution's
    own ``universe`` — a vector's labels are ordered the same way whichever
    date it was scored at.
    """
    iso = decision_date.isoformat()
    roster = resolution.slices.get(ROSTER_STREAM, {})
    return tuple(sorted(symbol for symbol, days in roster.items() if iso in days))


def _materialize_default(
    resolution: WindowResolution,
    decision_time: dt.datetime,
) -> Any:
    """The default materialize: pull the resolution's surviving partitions into frames.

    The host-side reader that turns a ``(resolution, decision_time)`` into a
    :class:`~contract.window.MarketWindow` for the default path.  It reads
    *only* the partitions the resolution already named as surviving at or
    before the decision time — the ``slices`` feature 72 computed — so it
    cannot serve a partition dated after ``t`` (look-ahead is physically
    absent, not merely unchecked).  It does not reach the lake: the resolution
    is pure data (names, instants, ISO dates), so this reader builds frames
    from what the resolution already carried, and a production reader over a
    real ``SnapshotMount`` is injected where the lake is actually read.

    The frames are empty Arrow tables with the window's column schema left to
    the injected reader in production; here, for the default path, each frame
    is an empty table — the honest result of a resolution that named its
    partitions but carried no bytes — so the sandbox still runs the signal
    over the resolved universe.  This keeps sandbox execution testable without
    a lake, while the production reader (feature 73's sibling) supplies the
    bytes.  One empty table per stream the resolution named — the surface the
    sandbox reconstructs the universe from — so the payload is never empty (an
    unmaterialized window cannot be serialized: the sandbox has no mounts to
    read one from).  The universe is :func:`pit_universe`'s per-date answer,
    not the resolution's own (that is the universe of the resolution's own
    decision date alone, a different date than every earlier rebalance date
    in the grid) — and the decision time is the one the loop sliced at.
    """
    import pyarrow as pa

    from contract.window import MarketWindow

    universe = pit_universe(resolution, decision_time.date())
    frames = {
        stream: pa.table({symbol: [] for symbol in per_symbol})
        for stream, per_symbol in resolution.slices.items()
    }
    return MarketWindow(decision_time, universe=universe, frames=frames)


def execute_signal(
    resolution: WindowResolution,
    code: str,
    *,
    seed: int,
    rebalance_dates: Optional[Iterable[dt.date]] = None,
    sandbox: Optional[SignalSandbox] = None,
    materialize: Optional[Callable[[WindowResolution, dt.datetime], Any]] = None,
) -> SignalExecution:
    """Execute ``code``'s ``signal`` inside the sandbox, one vector per rebalance date.

    Pipeline step 2 (§6.1): for each rebalance date, a :class:`MarketWindow`
    is materialized sliced to that date's decision time (from the
    resolution's surviving partitions), serialized over a payload channel
    (feature 14), run in the sandbox, and the raw score vector collected.  The
    result is a :class:`SignalExecution` keyed by rebalance date — "a raw score
    vector per rebalance date" — with the contract problems attached but not
    acted upon (feature 12 decides the consequence).

    ``resolution`` is the host-side slice from feature 72.  ``code`` is the
    signal source; its ``signal`` entrypoint is executed (feature 11).
    ``seed`` is the signal's only source of randomness, required.
    ``rebalance_dates`` defaults to the resolution's surviving bars dates (the
    natural rebalance grid — see :func:`_default_rebalance_dates`); pass an
    explicit iterable to score at a chosen set of dates.  ``sandbox`` defaults
    to a :class:`SignalSandbox` with §5.2's budgets; inject one to stub the
    process or substitute a gVisor runner.  ``materialize`` defaults to
    :func:`_materialize_default`; inject the production lake reader where the
    sealed snapshot is actually read.

    Raises :class:`~evaluator.EvaluatorSignalError` when the orchestration
    itself fails — no rebalance grid, a materialize that returns a non-window —
    a failure of the step, not of the signal it ran (a failed signal is a
    :class:`~evaluator._sandbox.SandboxResult`, recorded per date).
    """
    sandbox = sandbox if sandbox is not None else SignalSandbox()
    materialize_fn = materialize if materialize is not None else _materialize_default
    dates = tuple(sorted(set(rebalance_dates))) if rebalance_dates is not None else _default_rebalance_dates(resolution)
    if not dates:
        raise EvaluatorSignalError(
            "no rebalance dates to score: execute_signal needs a rebalance grid, "
            "either passed explicitly or resolved from the window's surviving bars"
        )

    vectors: dict[dt.date, RawScoreVector] = {}
    for rebalance_date in dates:
        decision_time = dt.datetime.combine(rebalance_date, _MIDNIGHT_UTC)
        window = materialize_fn(resolution, decision_time)
        # The materialize seam must produce a window the sandbox can serialize —
        # one exposing to_arrow().  Refused by name rather than failing later in
        # the child, so the caller learns the reader returned the wrong shape.
        if not hasattr(window, "to_arrow"):
            raise EvaluatorSignalError(
                f"materialize returned {window!r}, which has no to_arrow(); a "
                "materialized MarketWindow is required so the sandbox can send it "
                "over the payload channel (feature 14)"
            )
        result: SandboxResult = sandbox.run(code, window, seed=seed)
        vectors[rebalance_date] = RawScoreVector(
            rebalance_date=rebalance_date,
            decision_time=decision_time,
            universe=tuple(window.universe) if hasattr(window, "universe") else (),
            scores=result.scores,
            problems=list(result.problems),
            seed=seed if result.seed is None else result.seed,
            contract_version=result.contract_version,
        )

    return SignalExecution(
        snapshot_name=resolution.snapshot_name,
        code_hash=_sha256_hex(code),
        seed=seed,
        vectors=vectors,
    )
