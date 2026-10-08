"""Gating the aligned targets through the null oracle — pipeline step 5.

app_spec.xml feature 76: *"System rejects a target substitution anywhere
outside the null_gate step, which is the only place the oracle supplies a
target series."* docs/nullius-tech-architecture.md §6.1 names the step —
``5. null_gate ── ask null oracle for the target series ── §7`` — and adds
the line the whole feature turns on: *"Step 5 is the only place the null
substitution happens."*

**What a substitution is, and why exactly one is allowed.** Step 4 aligned
the real forward returns — labels the sealed closes compute host-side.
Step 5 hands the evaluation's labels to the null oracle (§7.2) and the
pipeline measures against what comes back, because whether a node's
targets are the real ones or a block permutation of them is the experiment
the whole method runs on: a signal that looks good against permuted labels
is a signal that looks good against noise, and only the sidecar key (§7.1)
ever learns which world a node lived in. The substitution — real answers
swapped for permuted ones — is therefore not a fault this module prevents;
it is the *treatment*, and it happens in exactly one place because a
second place (one more code path that could hand the metrics a target
series) would be a second experiment nobody calibrated, run on evaluations
nobody consented to. So this module is a door with two signs on it:
:func:`gate_targets` asks the oracle — the only ask in the package — and
:func:`check_targets_gated` refuses, for any consumer holding a target
bundle, one that did not come out of that ask.

**The gate never compares values — principle P2 made code.** The gate
holds both the aligned series and the oracle's answer, so comparing them
is not merely possible; it is the one thing this module must never do.
§7.2: *"The caller cannot distinguish the two branches from the
response,"* and principle P2: *"Planted nulls only work if ``is_null`` is
physically unreachable"* — a gate that refused on value mismatch would
be a client-side null detector, and a leak here would silently void every
calibration number the system has ever produced (§7's KS guard runs where
the key is, precisely because detectability is the threat — not here,
where it would be the leak). The branch is indistinguishable by design;
the *supply channel* is not. What the gate pins — at the ask, and again at
the check for any consumer holding the result — is the channel's shape:

* *the support, exactly.* Both §7.2 branches preserve the aligned support
  exactly — the real branch returns the aligned returns, and the block
  permutation shuffles contiguous 20-day blocks without creating or
  destroying a bar — so an answer covering a date the alignment does not,
  or missing one it does, is not an answer either branch could have
  produced: it is a target series that arrived by some other path, and it
  is refused. The same holds per date for the symbols: the oracle answers
  for the cross-section that was scored, never wider (a label for a symbol
  nobody scored is a label for nobody) and never narrower (a shrunk answer
  would shrink what every downstream metric measures — the dressed-up
  emptiness feature 75's coverage refusal exists to reject).
* *the provenance, once.* One alignment reads one sealed world, and the
  gated bundle stamps the alignment's own snapshot and grid — a bundle
  checked against a *different* alignment (a stale oracle answer replayed
  into another evaluation) is refused however well-formed it is.
* *the directive, opaque.* ``charges_budget`` is the one bit §7.2 lets
  cross the barrier, and it crosses as a directive, never a label: the
  gate carries it through untouched, interprets nothing (feature 84's
  trial charge is the consumer), and refuses an oracle that answers the
  horizons it was asked with disagreeing directives — one evaluation asks
  one debit question, and an oracle that answers it two ways is an oracle
  speaking for two evaluations.

**The §7.2 seam is injected.** The oracle arrives as a callable taking an
:class:`OracleRequest` and returning an :class:`OracleResponse` — the same
seam feature 73's ``materialize`` opens: the service call is injected,
never reached for, so the gate is testable against a stub and the
deployment wires the HTTP client underneath. The request is built from the
alignment's own terms — the horizon (the gate asks once per *covered*
horizon; a horizon with nothing aligned has nothing to ask, and is carried
as the empty series feature 75's shape promise requires), the symbols that
horizon's cross-sections name, and that horizon's date span — plus the
node identity the caller supplies: ``node_id``, ``campaign_id`` and
``depth``, the last being the term a Type-D oracle resolves its flip on.
An oracle that raises propagates: its failures are its own, like an HTTP
client's, and dressing them as gate errors would hide the seam.

**What this module does not do.** It does not align (feature 75 — the
aligned series are the question's terms, not the answer's), purge or
embargo (features 77 and 78 — folds, not targets), apply costs (feature
79), or compute any metric (features 80 on); it does not interpret the
budget directive (feature 84); and it does not detect the branch — nobody
on this side of the sidecar key can. It takes an alignment and an oracle
and answers exactly the two questions step 5 puts in scope: *what target
series does the null oracle supply for this evaluation?* — and, for a
consumer already holding a bundle — *is this the one it supplied?*

**The layering note.** This module is stdlib-only — records, mappings and
dates; no polars, no pyarrow, no lake, no environment, no HTTP. The oracle
call is the injected seam, so importing this member pays nothing — not
even a socket — which keeps composition, and the replay path §1 forbids
from reaching the evaluator, as cheap as the alignment this module gates.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Tuple

from ._align import HORIZONS, AlignedTargets, TargetSeries
from ._errors import EvaluatorGateError

__all__ = [
    "NULL_GATE_STEP",
    "GateCheck",
    "GatedTargets",
    "Oracle",
    "OracleRequest",
    "OracleResponse",
    "check_targets_gated",
    "gate_targets",
]

#: The pipeline-step name, in §6.1's own spelling. Shared vocabulary: the
#: feature sentence, the refusals below, and every step that consumes the
#: gate's answer name the one step a target series may be substituted at,
#: and they name it once.
NULL_GATE_STEP: str = "null_gate"

#: The oracle seam — §7.2's client, injected into :func:`gate_targets`.
#: Takes the request, returns the response; an oracle that raises propagates
#: (its failures are its own, like an HTTP client's), and a return that is
#: not an :class:`OracleResponse` is refused by the gate.
Oracle = Callable[["OracleRequest"], "OracleResponse"]


# -- The §7.2 records ----------------------------------------------------------


def _as_name(value: object, field: str) -> str:
    """A request identity field — a non-empty string, checked by name.

    ``node_id`` and ``campaign_id`` are how the sidecar's schema
    (``{node_id: {is_null, perm_seed, block_days}}``) finds the node the
    oracle answers for, so an identity that is not a name would make the
    answer unattributable — refused rather than trimmed.
    """
    if not isinstance(value, str) or not value.strip():
        raise EvaluatorGateError(
            f"{field} must be a non-empty string — §7.2's request names the "
            f"node the oracle answers for — got {value!r}"
        )
    return value


def _as_response_date(key: object) -> dt.date:
    """One answer key, as a calendar :class:`datetime.date`.

    Accepted spellings: a ``date``, or an ISO string naming one — §7.2 is a
    service boundary, and ISO is the wire spelling.  A ``datetime`` is
    refused (it names an instant, and a target is day-granular: silently
    truncating it would be a guess about which candle the oracle meant),
    and anything else is refused by name.
    """
    if isinstance(key, dt.datetime):
        raise EvaluatorGateError(
            f"the oracle's answer is keyed by a datetime ({key!r}); targets are "
            "day-granular — key by the calendar date (or its ISO string)"
        )
    if isinstance(key, dt.date):
        return key
    if isinstance(key, str):
        try:
            return dt.date.fromisoformat(key)
        except ValueError as exc:
            raise EvaluatorGateError(
                f"the oracle's target date {key!r} is not an ISO date; the answer "
                "is keyed by calendar dates (or ISO date strings), one per bar"
            ) from exc
    raise EvaluatorGateError(
        f"the oracle's target dates must be dates or ISO date strings, got "
        f"{key!r} ({type(key).__name__})"
    )


@dataclass(frozen=True)
class OracleRequest:
    """§7.2's request — what the gate asks, one per covered horizon.

    ``POST /target`` carries ``{node_id, campaign_id, depth, horizon,
    symbols[], date_range}``; this record is that request as a value, built
    by :func:`gate_targets` from the alignment's own terms plus the node
    identity the caller supplies, so an oracle — or a test, or an audit log
    — reads exactly what the gate asked and nothing it did not.  Validated
    at construction, because the request is the experiment's own header:
    ``depth`` is the term a Type-D oracle resolves its flip on, and a
    depth that is not a count or an identity that is not a name would make
    the answer unattributable.  Hashable by the dataclass default — every
    field is a plain hashable value, unlike the records that carry
    mappings.
    """

    #: The node being evaluated — the identity the sidecar's schema is
    #: keyed by (``{node_id: {is_null, perm_seed, block_days}}``).
    node_id: str
    #: The campaign the node belongs to — campaigns are homogeneous in null
    #: type (§7.3), so the oracle needs the campaign to answer coherently.
    campaign_id: str
    #: The node's depth in its tree — the term a Type-D oracle resolves the
    #: flip with (below ``flip_depth`` real, at or beyond it permuted).
    depth: int
    #: The horizon this request asks for — one of :data:`HORIZONS`; the
    #: gate asks once per covered horizon, and the answer is filed under
    #: the horizon it answered.
    horizon: int
    #: The symbols the answer must cover — that horizon's cross-sections,
    #: sorted and de-duplicated: the oracle answers for the symbols that
    #: were scored.
    symbols: Tuple[str, ...]
    #: The span of that horizon's aligned dates, as ``(first, last)`` — the
    #: range the answer's dates must live inside.
    date_range: Tuple[dt.date, dt.date]

    def __post_init__(self) -> None:
        # object.__setattr__ throughout: frozen dataclass, and these are
        # normalizations of arguments the constructor accepted.
        object.__setattr__(self, "node_id", _as_name(self.node_id, "node_id"))
        object.__setattr__(
            self, "campaign_id", _as_name(self.campaign_id, "campaign_id")
        )
        if isinstance(self.depth, bool) or not isinstance(self.depth, int):
            raise EvaluatorGateError(
                "depth must be a non-negative integer tree depth — §7.2's "
                "Type-D oracle resolves its flip on it — got "
                f"{self.depth!r} ({type(self.depth).__name__})"
            )
        if self.depth < 0:
            raise EvaluatorGateError(
                f"depth must be a non-negative integer tree depth, got "
                f"{self.depth}; a negative depth names a place in no tree"
            )
        if (
            isinstance(self.horizon, bool)
            or not isinstance(self.horizon, int)
            or self.horizon not in HORIZONS
        ):
            raise EvaluatorGateError(
                "the request's horizon must be one of the horizons the spec "
                f"names ({', '.join(str(h) for h in HORIZONS)}), got "
                f"{self.horizon!r}; the gate asks once per covered horizon and "
                "feature 81 counts on the set"
            )
        if not isinstance(self.symbols, tuple) or not self.symbols:
            raise EvaluatorGateError(
                "symbols must be a non-empty tuple of the symbols the answer "
                f"must cover, got {self.symbols!r}; a covered horizon has a "
                "cross-section to ask for"
            )
        for symbol in self.symbols:
            if not isinstance(symbol, str) or not symbol:
                raise EvaluatorGateError(
                    f"symbols must be non-empty strings, got {symbol!r}"
                )
        if list(self.symbols) != sorted(set(self.symbols)):
            # One spelling of the cross-section, whatever order the
            # alignment enumerated it in — the request is a value two
            # callers must be able to compare.
            raise EvaluatorGateError(
                "symbols must arrive sorted and de-duplicated; the ask names "
                "the cross-section once"
            )
        if (
            not isinstance(self.date_range, tuple)
            or len(self.date_range) != 2
            or not all(
                isinstance(day, dt.date) and not isinstance(day, dt.datetime)
                for day in self.date_range
            )
        ):
            raise EvaluatorGateError(
                "date_range must be a pair of calendar dates (first, last) — "
                f"the span the answer's dates must live inside — got "
                f"{self.date_range!r}"
            )
        if self.date_range[0] > self.date_range[1]:
            raise EvaluatorGateError(
                f"date_range must run first-to-last, got {self.date_range!r}"
            )


@dataclass(frozen=True)
class OracleResponse:
    """§7.2's response — the target series, and the one bit that crosses.

    ``{target_series, charges_budget}``, and — the interface's own comment —
    ``is_null`` NEVER appears: nothing in the response may say which branch
    produced it, so nothing does.  The payload is validated at construction
    because the response is the wire value: whatever the deployment's
    client deserializes, a payload that is not a well-formed series is
    refused here, before the gate asks the harder question of whether the
    series is one the alignment backs.  ``charges_budget`` must be a bool
    and only a bool — it is *the only bit that crosses the barrier* (§7.2),
    and a bit is not an int that happens to be 0 or 1, just as a bool that
    happens to equal a score is not a score.
    """

    #: The supplied target series, as ``{rebalance date: {symbol: forward
    #: return}}`` — keyed at construction by calendar date or ISO date
    #: string (the wire spelling) and normalized to dates on capture, every
    #: value a finite number.  Which branch produced it is unknowable from
    #: this side, by design.
    target_series: Mapping[dt.date, Mapping[str, float]]
    #: The opaque budget directive — whether the evaluation charges
    #: statistical budget, carried through untouched and interpreted
    #: nowhere in this module (feature 84's trial charge is the consumer).
    charges_budget: bool

    def __post_init__(self) -> None:
        if not isinstance(self.charges_budget, bool):
            raise EvaluatorGateError(
                "charges_budget must be a bool — §7.2's opaque directive, the "
                f"only bit that crosses the barrier — got {self.charges_budget!r} "
                f"({type(self.charges_budget).__name__})"
            )
        if not isinstance(self.target_series, Mapping):
            raise EvaluatorGateError(
                "the response's target_series must map rebalance date to "
                "{symbol: forward return}, got "
                f"{type(self.target_series).__name__}"
            )
        captured: dict[dt.date, Mapping[str, float]] = {}
        for key, row in self.target_series.items():
            day = _as_response_date(key)
            if day in captured:
                raise EvaluatorGateError(
                    f"the response's target_series carries {day.isoformat()} "
                    "twice under different spellings; one bar, one answer"
                )
            if not isinstance(row, Mapping):
                raise EvaluatorGateError(
                    f"the response's row for {day.isoformat()} must map symbol "
                    f"to forward return, got {type(row).__name__}"
                )
            inner: dict[str, float] = {}
            for symbol, value in row.items():
                if not isinstance(symbol, str) or not symbol:
                    raise EvaluatorGateError(
                        f"the response's symbols for {day.isoformat()} must be "
                        f"non-empty strings, got {symbol!r}"
                    )
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise EvaluatorGateError(
                        f"the response's target for {symbol!r} on "
                        f"{day.isoformat()} must be a number, got {value!r}"
                    )
                target = float(value)
                if not math.isfinite(target):
                    raise EvaluatorGateError(
                        f"the response's target for {symbol!r} on "
                        f"{day.isoformat()} is not finite ({value!r}); a NaN or "
                        "±inf label would reach the metrics dressed as a "
                        "measurement"
                    )
                inner[symbol] = target
            captured[day] = MappingProxyType(inner)
        object.__setattr__(
            self, "target_series", MappingProxyType(captured)
        )

    def __hash__(self) -> int:
        # The mapping is not hashable until it collapses to tuples, and the
        # fold keeps __hash__ consistent with __eq__, as TargetSeries does.
        return hash(
            (
                self.charges_budget,
                tuple(
                    (day, tuple(sorted(row.items())))
                    for day, row in sorted(self.target_series.items())
                ),
            )
        )


# -- Step 5's result ------------------------------------------------------------


@dataclass(frozen=True)
class GatedTargets:
    """Step 5's whole result — the oracle-supplied series, and the directive.

    What the pipeline measures against from here on: one :class:`TargetSeries`
    per horizon (the *supplied* ones — values the oracle chose, about which
    no code on this side of the sidecar key can say anything), the grid and
    snapshot of the alignment that was gated, and the budget directive
    carried through opaquely.  Construction checks the bundle's own
    coherence — the closed horizon set, series filed under their own
    horizon, one snapshot, a sorted grid — exactly as :class:`AlignedTargets`
    does, because this record is the alignment's counterpart downstream:
    where the alignment says *what was scored and what could be measured*,
    the gated bundle says *what the oracle supplied for exactly that*.

    A bundle built by hand is **not** refused by this constructor — its
    shape can be perfectly coherent — and that is deliberate: the gate
    cannot tell a permuted branch from a real one by looking, so it does
    not pretend to.  What a hand-built bundle cannot do is pass
    :func:`check_targets_gated` against the alignment it claims, unless its
    support *is* the alignment's — and a hand-built bundle on the aligned
    support with shuffled values is indistinguishable from the oracle's own
    answer, which is the method's property (§7.2), not a hole in it.
    """

    #: The canonical name of the sealed snapshot the gated alignment — and
    #: therefore this bundle — belongs to.
    snapshot_name: str
    #: The rebalance dates the gated alignment was aligned over, ascending:
    #: what was scored, restated by the answer that will be measured.
    rebalance_dates: Tuple[dt.date, ...]
    #: The five supplied series, as ``{horizon: TargetSeries}`` — always one
    #: per horizon in :data:`HORIZONS`, a horizon with nothing aligned
    #: carried as an empty series (feature 75's shape promise, kept).
    series: Mapping[int, TargetSeries]
    #: The opaque budget directive, carried through from the oracle's
    #: answers untouched — interpreted nowhere in this module.
    charges_budget: bool

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot_name, str) or not self.snapshot_name.strip():
            raise EvaluatorGateError(
                "gated targets must name the sealed snapshot they were gated "
                f"over, got {self.snapshot_name!r}"
            )
        if not isinstance(self.rebalance_dates, tuple):
            raise EvaluatorGateError(
                "rebalance_dates must be a tuple of dates, got "
                f"{type(self.rebalance_dates).__name__}"
            )
        for day in self.rebalance_dates:
            if not isinstance(day, dt.date) or isinstance(day, dt.datetime):
                raise EvaluatorGateError(
                    f"rebalance dates must be calendar dates, got {day!r}"
                )
        if list(self.rebalance_dates) != sorted(set(self.rebalance_dates)):
            raise EvaluatorGateError(
                "rebalance_dates must arrive sorted and de-duplicated; the "
                "producer that emitted them drifted"
            )
        if not isinstance(self.charges_budget, bool):
            raise EvaluatorGateError(
                "charges_budget must be a bool — §7.2's opaque directive, the "
                f"only bit that crosses the barrier — got {self.charges_budget!r} "
                f"({type(self.charges_budget).__name__})"
            )
        if not isinstance(self.series, Mapping):
            raise EvaluatorGateError(
                "series must map horizon to TargetSeries, got "
                f"{type(self.series).__name__}"
            )
        carried = tuple(sorted(self.series))
        if carried != HORIZONS:
            raise EvaluatorGateError(
                "gated targets carry one series per horizon the spec names "
                f"({', '.join(str(h) for h in HORIZONS)}), got "
                f"{', '.join(str(h) for h in carried) or 'none'}"
            )
        for horizon, series in self.series.items():
            if series.horizon != horizon:
                raise EvaluatorGateError(
                    f"the series filed under horizon {horizon} carries horizon "
                    f"{series.horizon}; a series filed under the wrong horizon "
                    "is a pairing every downstream metric would trust and be "
                    "wrong by"
                )
            if series.snapshot_name != self.snapshot_name:
                raise EvaluatorGateError(
                    f"the horizon-{horizon} series names snapshot "
                    f"{series.snapshot_name!r} but the bundle names "
                    f"{self.snapshot_name!r}; one gate reads one sealed world"
                )
        object.__setattr__(
            self, "series", MappingProxyType(dict(self.series))
        )

    @property
    def horizons(self) -> Tuple[int, ...]:
        """The horizons carried, ascending — always :data:`HORIZONS`."""
        return HORIZONS

    def targets(self, horizon: int) -> TargetSeries:
        """One horizon's supplied target series.

        Refused for a horizon outside :data:`HORIZONS` — the set is closed,
        on the same terms as the alignment's own accessor, which this
        bundle mirrors.
        """
        if horizon not in self.series:
            raise EvaluatorGateError(
                f"horizon {horizon} is not one of the horizons this bundle "
                f"carries ({', '.join(str(h) for h in HORIZONS)}); the decay "
                "profile asks per horizon, and the set is the spec's, not the "
                "caller's to widen"
            )
        return self.series[horizon]

    def __hash__(self) -> int:
        # Same fold as AlignedTargets, for the same reason: the record is a
        # value, and the mapping is not hashable until it collapses to
        # tuples.
        return hash(
            (
                self.snapshot_name,
                self.rebalance_dates,
                self.charges_budget,
                tuple(sorted(self.series.items())),
            )
        )

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"GatedTargets(snapshot={self.snapshot_name!r}, "
            f"{len(self.rebalance_dates)} rebalance dates, "
            f"horizons={list(self.series)!r}, "
            f"charges_budget={self.charges_budget})"
        )


# -- The one spelling of the support rule ---------------------------------------


def _check_support(supplied: TargetSeries, aligned: TargetSeries) -> None:
    """Refuse a supplied series that does not live on the aligned support.

    Both §7.2 branches preserve the support exactly — the real branch
    returns the aligned returns, and the block permutation moves contiguous
    20-day blocks without creating or destroying a bar — so a horizon's
    answer must cover exactly the dates that horizon's alignment covers,
    and exactly the scored symbols on each of them.  Anything else did not
    come out of the oracle: it arrived by another path, and the refusal is
    the feature's own — a target substitution outside the
    :data:`NULL_GATE_STEP` step.  The *values* are never compared here or
    anywhere in this module; see the module docstring for why comparing
    them would be the one leak this architecture cannot survive.
    """
    supplied_days = set(supplied.dates())
    aligned_days = set(aligned.dates())
    if supplied_days != aligned_days:
        parts: list[str] = []
        missing = sorted(aligned_days - supplied_days)
        if missing:
            parts.append(
                f"{'date' if len(missing) == 1 else 'dates'} the alignment "
                f"covers that the answer does not ({', '.join(day.isoformat() for day in missing)})"
            )
        extra = sorted(supplied_days - aligned_days)
        if extra:
            parts.append(
                f"{'date' if len(extra) == 1 else 'dates'} no scored grid names "
                f"({', '.join(day.isoformat() for day in extra)})"
            )
        raise EvaluatorGateError(
            f"the supplied horizon-{aligned.horizon} series does not live on "
            f"the alignment's own support — {'; '.join(parts)} — a target "
            f"series that did not come through the {NULL_GATE_STEP} step is a "
            "substitution the pipeline refuses: the oracle answers on the "
            "support it was asked for (§7.2's branches preserve it exactly), "
            "so this one arrived by another path"
        )
    for day in aligned.dates():
        supplied_symbols = set(supplied.at(day))
        aligned_symbols = set(aligned.at(day))
        if supplied_symbols != aligned_symbols:
            missing = sorted(aligned_symbols - supplied_symbols)
            extra = sorted(supplied_symbols - aligned_symbols)
            raise EvaluatorGateError(
                f"the supplied horizon-{aligned.horizon} series answers "
                f"{day.isoformat()} for {', '.join(sorted(supplied_symbols)) or 'no symbols'}, "
                f"but that date's cross-section is {', '.join(sorted(aligned_symbols))}"
                + (
                    f" — missing {', '.join(missing)}"
                    if missing
                    else ""
                )
                + (
                    f" — carrying {', '.join(extra)}, whom nobody scored"
                    if extra
                    else ""
                )
                + f"; a target series outside the {NULL_GATE_STEP} step's "
                "supply is a substitution the pipeline refuses: the oracle "
                "answers for the cross-section it was asked for, no wider and "
                "no narrower"
            )


# -- The ask --------------------------------------------------------------------


def gate_targets(
    alignment: AlignedTargets,
    oracle: Oracle,
    *,
    node_id: str,
    campaign_id: str,
    depth: int,
) -> GatedTargets:
    """Ask the null oracle for the target series — pipeline step 5, the only ask.

    For every horizon in :data:`HORIZONS` that the ``alignment`` covers,
    build §7.2's request from the alignment's own terms — the horizon, the
    symbols that horizon's cross-sections name, that horizon's date span —
    plus the node identity (``node_id``, ``campaign_id``, ``depth``; a
    Type-D oracle resolves its flip on the depth) — and ask the injected
    ``oracle``.  Each answer is validated as a payload (by
    :class:`OracleResponse`'s constructor) and then as a supply (by the
    support rule): it must live on exactly the aligned support, per date
    and per symbol.  The result is a :class:`GatedTargets` — the five
    supplied series, the alignment's provenance, and the budget directive
    carried through opaquely.  A horizon with nothing aligned is not asked
    and is carried as an empty series.

    The answers' *values* are never compared to the aligned ones — the
    caller cannot distinguish the oracle's two branches, and a gate that
    tried would be the client-side null detector principle P2 forbids.  An
    oracle that raises propagates; a return that is not an
    :class:`OracleResponse` is refused by name.

    Raises :class:`EvaluatorGateError`, each with its reason (see
    ``_errors``): an ``alignment`` that is not step 4's own result; an
    ``oracle`` that is not callable; a node identity that is not a name or
    a depth that is not a non-negative count; an alignment with no
    computable target at any horizon (nothing to ask, so no evaluation to
    gate); an answer that is not an ``OracleResponse``, or whose support is
    not the alignment's own; and an oracle that answers the horizons with
    disagreeing budget directives.
    """
    if not isinstance(alignment, AlignedTargets):
        raise EvaluatorGateError(
            "gate_targets gates an AlignedTargets — step 4's own result, the "
            "terms the oracle is asked on — got "
            f"{type(alignment).__name__}"
        )
    if not callable(oracle):
        raise EvaluatorGateError(
            "the oracle must be a callable taking an OracleRequest and "
            "returning an OracleResponse — §7.2's seam, injected, never "
            f"reached for — got {type(oracle).__name__}"
        )
    node = _as_name(node_id, "node_id")
    campaign = _as_name(campaign_id, "campaign_id")
    if isinstance(depth, bool) or not isinstance(depth, int):
        raise EvaluatorGateError(
            "depth must be a non-negative integer tree depth — §7.2's Type-D "
            f"oracle resolves its flip on it — got {depth!r} "
            f"({type(depth).__name__})"
        )
    if depth < 0:
        raise EvaluatorGateError(
            f"depth must be a non-negative integer tree depth, got {depth}; "
            "a negative depth names a place in no tree"
        )

    covered = [horizon for horizon in HORIZONS if alignment.targets(horizon).dates()]
    if not covered:
        raise EvaluatorGateError(
            "the alignment carries no computable target at any horizon, so "
            "there is nothing to ask the oracle for and no evaluation to "
            "gate — align targets over a window first (feature 75)"
        )

    series: dict[int, TargetSeries] = {}
    # The directive is one bit per evaluation, so it is collected from the
    # answers and required to agree — the first answer sets it, and every
    # later one must repeat it (see the disagreement refusal below).
    directives: list[Tuple[int, bool]] = []
    for horizon in HORIZONS:
        aligned_series = alignment.targets(horizon)
        dates = aligned_series.dates()
        if not dates:
            # Nothing aligned, nothing asked: carried as the empty series
            # the bundle's shape promise requires (feature 75's five-horizon
            # rule), stamped with the alignment's own provenance.
            series[horizon] = TargetSeries(
                horizon=horizon,
                snapshot_name=alignment.snapshot_name,
                values=MappingProxyType({}),
            )
            continue
        symbols = tuple(
            sorted({symbol for day in dates for symbol in aligned_series.at(day)})
        )
        response = oracle(
            OracleRequest(
                node_id=node,
                campaign_id=campaign,
                depth=depth,
                horizon=horizon,
                symbols=symbols,
                date_range=(dates[0], dates[-1]),
            )
        )
        if not isinstance(response, OracleResponse):
            raise EvaluatorGateError(
                "the oracle must return an OracleResponse — §7.2's "
                "{target_series, charges_budget} — got "
                f"{type(response).__name__}; the seam's payload is validated "
                "at the record, and anything else is not an answer"
            )
        if directives and response.charges_budget != directives[0][1]:
            raise EvaluatorGateError(
                "the oracle's budget directive disagreed across the horizons "
                f"it was asked ({directives[0][1]!r} at horizon "
                f"{directives[0][0]}, then {response.charges_budget!r} at "
                f"horizon {horizon}); one evaluation asks one debit question, "
                "and §7.2's directive is the one bit that crosses the barrier "
                "— an oracle that answers it two ways is speaking for two "
                "evaluations"
            )
        directives.append((horizon, response.charges_budget))
        # Project each aligned date's answer onto that date's scored
        # cross-section. The request names one symbol tuple for the whole
        # grid, while the scored set varies by date (a signal leaves a
        # symbol unscored, e.g. a flat stablecoin), so the honest answer can
        # be wider on some dates (archive smoke 2a0700fa: USDCUSDT on
        # 2022-09-26). Extra symbols are dropped before anything reads the
        # series, identically on both branches, so they cannot widen what the
        # metrics measure. A narrower answer, or an extra or missing date, is
        # still refused by _check_support.
        aligned_days = set(aligned_series.dates())
        projected = {
            day: (
                {symbol: value for symbol, value in row.items()
                 if symbol in set(aligned_series.at(day))}
                if day in aligned_days
                else row
            )
            for day, row in response.target_series.items()
        }
        supplied = TargetSeries(
            horizon=horizon,
            snapshot_name=alignment.snapshot_name,
            values=projected,
        )
        _check_support(supplied, aligned_series)
        series[horizon] = supplied

    # directives is non-empty: `covered` is non-empty and every covered
    # horizon answered above.
    return GatedTargets(
        snapshot_name=alignment.snapshot_name,
        rebalance_dates=alignment.rebalance_dates,
        series=MappingProxyType(series),
        charges_budget=directives[0][1],
    )


# -- The rejection ---------------------------------------------------------------


@dataclass(frozen=True)
class GateCheck:
    """The verdict of a target-supply check — the certified binding, summarized.

    What :func:`check_targets_gated` returns when a bundle *is* the gate's
    own answer over the alignment it was checked against: the provenance
    both sides name, the grid both sides carry, the per-horizon coverage
    the answer lives on, and the opaque directive — a value to file beside
    the evaluation or compare across checks without recomputing (frozen,
    hashable).  Carried beside the bundle rather than instead of it: the
    check certifies a supply, and the bundle remains what the pipeline
    measures against.
    """

    #: The sealed snapshot both the alignment and the certified bundle name.
    snapshot_name: str
    #: The rebalance grid both sides carry — what was scored.
    rebalance_dates: Tuple[dt.date, ...]
    #: The dates each horizon's answer lives on, as ``{horizon: dates}`` —
    #: one entry per horizon in :data:`HORIZONS`, the alignment's own
    #: coverage restated.
    coverage: Mapping[int, Tuple[dt.date, ...]]
    #: The opaque budget directive, restated from the certified bundle.
    charges_budget: bool

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot_name, str) or not self.snapshot_name.strip():
            raise EvaluatorGateError(
                "a gate check must name the sealed snapshot it certified, got "
                f"{self.snapshot_name!r}"
            )
        if not isinstance(self.rebalance_dates, tuple):
            raise EvaluatorGateError(
                "rebalance_dates must be a tuple of dates, got "
                f"{type(self.rebalance_dates).__name__}"
            )
        for day in self.rebalance_dates:
            if not isinstance(day, dt.date) or isinstance(day, dt.datetime):
                raise EvaluatorGateError(
                    f"rebalance dates must be calendar dates, got {day!r}"
                )
        if list(self.rebalance_dates) != sorted(set(self.rebalance_dates)):
            raise EvaluatorGateError(
                "rebalance_dates must arrive sorted and de-duplicated"
            )
        if not isinstance(self.charges_budget, bool):
            raise EvaluatorGateError(
                "charges_budget must be a bool — the directive the certified "
                f"bundle carries — got {self.charges_budget!r} "
                f"({type(self.charges_budget).__name__})"
            )
        if not isinstance(self.coverage, Mapping):
            raise EvaluatorGateError(
                "coverage must map horizon to the dates that horizon's answer "
                f"lives on, got {type(self.coverage).__name__}"
            )
        if tuple(sorted(self.coverage)) != HORIZONS:
            raise EvaluatorGateError(
                "coverage carries one entry per horizon the spec names "
                f"({', '.join(str(h) for h in HORIZONS)}), got "
                f"{', '.join(str(h) for h in sorted(self.coverage)) or 'none'}"
            )
        captured: dict[int, Tuple[dt.date, ...]] = {}
        for horizon, days in self.coverage.items():
            if not isinstance(days, tuple):
                raise EvaluatorGateError(
                    f"the coverage for horizon {horizon} must be a tuple of "
                    f"dates, got {type(days).__name__}"
                )
            for day in days:
                if not isinstance(day, dt.date) or isinstance(day, dt.datetime):
                    raise EvaluatorGateError(
                        f"the coverage dates for horizon {horizon} must be "
                        f"calendar dates, got {day!r}"
                    )
            if list(days) != sorted(set(days)):
                raise EvaluatorGateError(
                    f"the coverage for horizon {horizon} must arrive sorted "
                    "and de-duplicated"
                )
            captured[horizon] = tuple(days)
        object.__setattr__(self, "coverage", MappingProxyType(captured))

    def __hash__(self) -> int:
        # The fold the bundle's hash uses, for the same reason: the record
        # is a value, and the coverage mapping collapses to tuples.
        return hash(
            (
                self.snapshot_name,
                self.rebalance_dates,
                self.charges_budget,
                tuple(sorted(self.coverage.items())),
            )
        )

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"GateCheck(snapshot={self.snapshot_name!r}, "
            f"{len(self.rebalance_dates)} rebalance dates, "
            f"charges_budget={self.charges_budget})"
        )


def check_targets_gated(gated: object, alignment: object) -> GateCheck:
    """Certify that a held target bundle is the gate's own answer — the rejection.

    The half of the feature the sentence leads with: *system rejects a
    target substitution anywhere outside the null_gate step*.  A consumer
    holding a :class:`GatedTargets` — or something claiming to be one —
    calls this with the alignment the evaluation ran, and the check
    certifies the supply: the bundle must be a ``GatedTargets`` at all; it
    must name the alignment's own sealed snapshot and carry the
    alignment's own rebalance grid (a stale answer replayed into another
    evaluation is a substitution, however well-formed); and every
    horizon's series must live on exactly that horizon's aligned support,
    per date and per symbol (the same rule :func:`gate_targets` enforced
    at the ask — §7.2's branches preserve the support exactly, so a bundle
    that does not match it did not come out of this gate).

    The check never compares values — a bundle on the aligned support with
    different values is indistinguishable from the oracle's own answer,
    and that indistinguishability is the method (§7.2), not a hole in the
    check.  What it refuses is the supply that arrived by any path other
    than the one ask in this package.

    Returns a :class:`GateCheck` summarizing the certified binding.  Raises
    :class:`EvaluatorGateError`, each with its reason (see ``_errors``): a
    ``gated`` that is not a ``GatedTargets`` (an alignment handed back, a
    raw mapping, a hand-built impostor of another type), an ``alignment``
    that is not step 4's own result, and every supply mismatch above.
    """
    if not isinstance(gated, GatedTargets):
        raise EvaluatorGateError(
            "check_targets_gated certifies the null gate's own answer — a "
            f"GatedTargets — got {type(gated).__name__}; the alignment is "
            "what was gated, not what the gate returned"
        )
    if not isinstance(alignment, AlignedTargets):
        raise EvaluatorGateError(
            "check_targets_gated checks against an AlignedTargets — step 4's "
            "own result, the support the gate was asked on — got "
            f"{type(alignment).__name__}"
        )
    if gated.snapshot_name != alignment.snapshot_name:
        raise EvaluatorGateError(
            f"the bundle names snapshot {gated.snapshot_name!r} but the "
            f"alignment names {alignment.snapshot_name!r}; a target series "
            "gated over one sealed world cannot be the null gate's answer "
            f"over another — a replayed answer is a substitution outside "
            f"the {NULL_GATE_STEP} step, refused however well-formed it is"
        )
    if gated.rebalance_dates != alignment.rebalance_dates:
        raise EvaluatorGateError(
            f"the bundle carries {len(gated.rebalance_dates)} rebalance dates "
            f"and the alignment carries {len(alignment.rebalance_dates)}; the "
            "gate answers on the grid it was asked on, so a bundle over "
            "another grid did not come out of this gate — it is a target "
            f"substitution outside the {NULL_GATE_STEP} step"
        )
    for horizon in HORIZONS:
        _check_support(gated.targets(horizon), alignment.targets(horizon))
    return GateCheck(
        snapshot_name=gated.snapshot_name,
        rebalance_dates=gated.rebalance_dates,
        coverage=MappingProxyType(
            {horizon: gated.targets(horizon).dates() for horizon in HORIZONS}
        ),
        charges_budget=gated.charges_budget,
    )
