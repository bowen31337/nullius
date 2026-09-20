"""The artifact content — pipeline step 12's rendering half, feature 85.

app_spec.xml feature 85: *"System persists the full artifact to the artifact
store plus the scalar metrics to the tree store as the final pipeline step."*
docs/nullius-tech-architecture.md §6.1 names the step —
``12. persist   artifact → ART, scalars → TREE`` — and §9.2 lays out the files
this module renders and §9.1 the ``node`` row's scalar columns the companion
module (:mod:`evaluator._persist_store`) carries across the tree seam.

This module owns the *content* of each §9.2 artifact file — turning the measured
records steps 7–9 produced into the exact payload of each file — and defines the
injected :class:`ArtifactWriter` seam the artifacts member speaks. It does not
own the Parquet *encoding* or the on-disk path: those are the artifacts member's
(features 170, 172), and the boundary is the writer's, exactly as the workspace
contract keeps members from importing siblings. The split is the one this
package already uses — feature 73's sandbox, feature 76's oracle, feature 84's
ledger are all injected structural seams — and it is the split feature 85 owns:
this member renders the content of each file from the records it holds as
values, and the writer owns the bytes and the path.

**Stdlib-only, and the Parquet boundary is the writer's.** The renderers here
assemble JSON-ready structures and the per-date turnover series with dates,
mappings and arithmetic; they produce no Parquet bytes, so no polars, no pyarrow,
no lake, no HTTP and no import of any other member. The ``signal_returns.parquet``
and ``ic_series.parquet`` and ``turnover_series.parquet`` files are written
through the seam as a :class:`ArtifactPayload` whose ``kind`` is ``"parquet"``
and whose source is the record; the writer turns that source into bytes, so the
Polars boundary stays at the edge of the package where every other member keeps
it. That is what makes importing this member cost composition — and the replay
path §1 forbids from reaching the evaluator — nothing at all.

**What this module does not do.** It persists nothing (that is
:mod:`evaluator._persist_store`, which drives the two seams in one transaction),
it computes no metric (steps 7–9 did that), it renders no ``code.py`` content
(the signal's source is the caller's, passed in optionally as a ``code``
payload), and it decides no node identity or non-metric column (the tree
member's). It answers exactly the rendering questions step 12 puts in scope:
*what does each §9.2 file contain, and what shape does the artifact writer
speak?*
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Protocol

from ._costs import PostCostReturns
from ._decay import DECAY_HORIZONS, DecayProfile
from ._errors import EvaluatorArtifactError
from ._metrics import NodeMetrics

__all__ = [
    "ArtifactPayload",
    "ArtifactWriter",
    "render_decay_profile",
    "render_exec_trace",
    "render_regime_attribution",
    "render_turnover_series",
]

#: The pipeline-step name, in §6.1's own spelling — ``12. persist artifact →
#: ART, scalars → TREE``. Shared vocabulary: the feature sentence, the renderers
#: below and the callers that name where a file's content comes from all spell
#: the one step, and they spell it once.
PERSIST_STEP: str = "persist"

#: The artifact kinds the writer encodes — the three media §9.2's files come in.
#: ``"json"`` carries JSON text, ``"code"`` carries the caller's signal source,
#: and ``"parquet"`` carries a record the writer encodes to Parquet bytes. The
#: kind is part of the payload's identity, so the writer knows which encoder to
#: reach for without inspecting the content — a parquet payload is never
#: mistaken for a text one.
ArtifactKind = str  # "json" | "parquet" | "code"

# The sentinel a renderer uses to tell "the record carries no such attribute"
# from "the attribute is None" — a missing field is a record of another shape,
# and the refusal must name it.
_MISSING: Any = object()


class ArtifactWriter(Protocol):
    """The artifact store's seam — how a node's files reach the store.

    Injected, not imported: the workspace contract keeps this member from
    reaching the artifacts member, so the writer is an object exposing the two
    methods the artifacts member's writer speaks, satisfied structurally with no
    adapter — the same way feature 73's sandbox, feature 76's oracle and feature
    84's ledger are injected.

    .. py:method:: write_artifact(node_id, campaign_id, filename, payload) -> None

        Write one file of one node's artifact directory. The path is the
        writer's — ``<campaign_id>/<node_id>/<filename>`` per §9.2 — and the
        encoding is the writer's: a ``"parquet"`` payload becomes Parquet bytes,
        a ``"json"`` or ``"code"`` payload becomes bytes of its text. Called once
        per §9.2 file.

    .. py:method:: flush(node_id) -> None

        Commit one node's directory. The writes above are staged; ``flush`` is
        the commit point, so a failure before it leaves nothing half-written —
        the transaction boundary :mod:`evaluator._persist_store` relies on to
        refuse a half node.
    """

    def write_artifact(
        self,
        node_id: str,
        campaign_id: str,
        filename: str,
        payload: "ArtifactPayload",
    ) -> None:
        """Write one file of one node's artifact directory."""
        ...

    def flush(self, node_id: str) -> None:
        """Commit one node's directory — the write's commit point."""
        ...


@dataclass(frozen=True)
class ArtifactPayload:
    """The content half of one §9.2 file — encoding-agnostic.

    What this member hands the writer: the file's name, the medium it comes in
    (``kind``), and the content that medium carries. The writer turns the content
    into bytes and puts it at ``<campaign_id>/<node_id>/<filename>``. The three
    kinds carry different content: ``"json"`` carries :attr:`json_text`,
    ``"code"`` carries :attr:`code_text`, and ``"parquet"`` carries neither — its
    bytes come from the writer encoding the record this payload names. A payload
    carries exactly the content its kind asks for and no other: a parquet payload
    carries no text, and a text payload carries no source, so the writer never
    has to guess which field to read — the failure a payload that carried both a
    text and a parquet source would invite.

    Frozen, because a payload is a value handed to a seam, and a value that could
    be edited between the render and the write would be a file whose content the
    renderer no longer vouches for.
    """

    #: The file's name — one of §9.2's spellings (``signal_returns.parquet``,
    #: ``decay_profile.json``, …).
    filename: str
    #: The medium this file comes in — ``"json"``, ``"parquet"`` or ``"code"``.
    kind: ArtifactKind
    #: The JSON text of a ``"json"`` file — the rendered content, already
    #: serialized. Absent for a ``"parquet"`` or ``"code"`` file.
    json_text: Optional[str] = None
    #: The signal source of a ``"code"`` file — the caller's ``code.py``. Absent
    #: for a ``"json"`` or ``"parquet"`` file.
    code_text: Optional[str] = None
    #: The record a ``"parquet"`` file is encoded from — the writer's source.
    #: Absent for a ``"json"`` or ``"code"`` file.
    source: Optional[object] = None

    def __post_init__(self) -> None:
        if self.kind not in ("json", "parquet", "code"):
            raise EvaluatorArtifactError(
                f"an artifact payload's kind must be 'json', 'parquet' or "
                f"'code' — the three media §9.2's files come in — got "
                f"{self.kind!r}; the writer reaches for an encoder by kind, and "
                "a payload in an unknown medium cannot be written"
            )
        # Each kind carries exactly its own content. A parquet payload carries
        # a source and no text; a text payload carries text and no source;
        # carrying the wrong field for the kind is a file whose content the
        # renderer did not intend.
        if self.kind == "parquet" and self.source is None:
            raise EvaluatorArtifactError(
                f"a 'parquet' artifact payload carries the record the writer "
                f"encodes — got no source for {self.filename!r}; the Parquet "
                "bytes are the writer's to produce from a source, and a parquet "
                "payload without one is a file the writer cannot write"
            )
        if self.kind == "parquet" and (
            self.json_text is not None or self.code_text is not None
        ):
            raise EvaluatorArtifactError(
                "a 'parquet' artifact payload carries the record the writer "
                "encodes, never text — got json_text or code_text; the Parquet "
                "bytes are the writer's to produce, and a parquet payload with "
                "text asks the writer to serialize what it cannot"
            )
        if self.kind == "json" and self.json_text is None:
            raise EvaluatorArtifactError(
                "a 'json' artifact payload carries the serialized JSON text — "
                f"got none for {self.filename!r}; a json file with no text is a "
                "file the writer cannot write"
            )
        if self.kind == "code" and self.code_text is None:
            raise EvaluatorArtifactError(
                "a 'code' artifact payload carries the signal source — got "
                f"none for {self.filename!r}; a code file with no source is a "
                "file the writer cannot write"
            )


# -- The renderers ---------------------------------------------------------------


def render_decay_profile(profile: DecayProfile) -> list[Optional[float]]:
    """The decay profile as §9.2's ``decay_profile.json`` carries it.

    The five-position array, positional over :data:`DECAY_HORIZONS`, with
    ``None`` per un-measured horizon — exactly what
    :meth:`DecayProfile.as_array` returns, restated here as a list so the
    artifact spelling is the evaluator's rather than the record's. The array is
    positional rather than keyed because that is how the live loop consumes a
    stored profile — entry by entry against a forward one — and a mapping would
    have to be re-aligned by every reader. A horizon the window was too short to
    measure is ``None``, carried rather than dropped: un-measured is a different
    fact from zero, the distinction the whole package maintains.
    """
    if not isinstance(profile, DecayProfile):
        raise EvaluatorArtifactError(
            "render_decay_profile renders step 8's own result — a "
            f"DecayProfile — got {type(profile).__name__}; the stored array is "
            "the information coefficient at each horizon, and only the record "
            "feature 81 produced carries that array"
        )
    return list(profile.as_array())


def render_regime_attribution(attribution: object) -> dict[str, Any]:
    """The regime attribution as §9.2's ``regime_attribution.json`` carries it.

    ``{stratum: {horizon: {dates, mean_post_cost_return}}}`` plus
    ``unattributed_dates`` — the per-stratum, per-horizon split the artifact
    keeps. Strata are sorted and horizons are sorted, so the file is
    deterministic: two renders of one attribution produce byte-identical JSON,
    which is what replay needs from a fingerprint. Each stratum's horizon object
    carries only the horizons that stratum was measured at — absence, not zero —
    and a stratum measured at no horizon carries an empty object, the "write the
    zero" discipline the record itself states. The floats are carried as native
    Python floats; the persist layer serializes them, and JSON numbers are IEEE
    doubles either way, so a reader re-solving a stored value against its own
    terms meets the number it expects.
    """
    strata = getattr(attribution, "strata", _MISSING)
    unattributed = getattr(attribution, "unattributed_dates", _MISSING)
    if strata is _MISSING or unattributed is _MISSING:
        raise EvaluatorArtifactError(
            "render_regime_attribution renders step 8's own result — a "
            "RegimeAttribution, with a strata mapping and an "
            f"unattributed_dates count — got {type(attribution).__name__}; the "
            "per-stratum split is the attribution's content, and only the "
            "record feature 82 produced carries it"
        )
    if not isinstance(strata, Mapping):
        raise EvaluatorArtifactError(
            "a regime attribution's strata must map stratum name to its "
            f"slices, got {type(strata).__name__}"
        )
    if isinstance(unattributed, bool) or not isinstance(unattributed, int):
        raise EvaluatorArtifactError(
            f"a regime attribution's unattributed_dates must be an integer "
            f"count, got {unattributed!r}"
        )
    rendered: dict[str, Any] = {}
    for stratum_name in sorted(strata):
        slices = strata[stratum_name].slices
        rendered[stratum_name] = {
            str(horizon): {
                "dates": slices[horizon].dates,
                "mean_post_cost_return": slices[horizon].mean_post_cost_return,
            }
            for horizon in sorted(slices)
        }
    rendered["unattributed_dates"] = unattributed
    return rendered


def render_turnover_series(
    returns: PostCostReturns, metrics: NodeMetrics
) -> dict[str, float]:
    """The per-date turnover as §9.2's ``turnover_series.parquet`` carries it.

    The equal-weight book's fractional turnover, one entry per rebalance that
    has a predecessor — ``½ · Σ |w_d − w_{d−1}|`` over the symbols each pair of
    consecutive dates holds — the same arithmetic :func:`compute_node_metrics`
    reduces to the single ``turnover`` scalar, restated here per date because the
    PRD's artifact keeps ``turnover_series`` in full (feature 169). The series is
    keyed by ISO date and ordered, so a reader walking it meets the dates in the
    order the book turned them over.

    The cross-section each rebalance held is read from the priced panel —
    :attr:`PostCostReturns.series` at :attr:`NodeMetrics.horizon`, the horizon
    the four scalars were measured over — because that panel is the one place the
    per-date symbol set is recorded in full. A symbol that enters or exits the
    panel between two dates moves its full weight, and the remaining symbols
    re-weight; both are captured by the ``|w_d − w_{d−1}|`` term with an absent
    symbol weighted at zero. Only dates the panel actually priced are carried — a
    horizon with an unpriced date has no book to turn over — the same support
    ``compute_node_metrics`` reduces over. ``returns`` and ``metrics`` must name
    the same node, so the series is the turnover of one book, not two panels
    spliced.
    """
    if not isinstance(returns, PostCostReturns):
        raise EvaluatorArtifactError(
            "render_turnover_series renders step 7's own result — a "
            f"PostCostReturns, the priced panel — got {type(returns).__name__}; "
            "the turnover is the book the post-cost returns priced turns over, "
            "and only that panel says which dates and symbols the series spans"
        )
    if not isinstance(metrics, NodeMetrics):
        raise EvaluatorArtifactError(
            "render_turnover_series renders step 8's own result — a "
            f"NodeMetrics, which names the horizon the turnover is measured "
            f"over — got {type(metrics).__name__}; the fractional turnover is a "
            "function of the panel the metrics reduced"
        )
    if metrics.node_id != returns.node_id:
        raise EvaluatorArtifactError(
            f"the turnover series is one node's: the metrics name node "
            f"{metrics.node_id!r} but the returns name {returns.node_id!r}; a "
            "turnover series over two different nodes' panels is a series no "
            "book turned over"
        )
    series = returns.series[metrics.horizon]
    # Only the dates the panel priced — the support compute_node_metrics reduces
    # over — in order, so each entry has the predecessor its turnover needs.
    ordered_days = [day for day in sorted(series.dates()) if series.at(day)]
    rendered: dict[str, float] = {}
    for prev_day, day in zip(ordered_days, ordered_days[1:]):
        prev_symbols = set(series.at(prev_day))
        day_symbols = set(series.at(day))
        prev_count = len(prev_symbols)
        day_count = len(day_symbols)
        prev_weight = 1.0 / prev_count if prev_count else 0.0
        day_weight = 1.0 / day_count if day_count else 0.0
        # Equal-weight within each date's own panel — 1/N on the N symbols that
        # date holds — so a symbol that enters or exits the panel moves its full
        # weight and the remaining symbols re-weight, which the |w_d − w_{d−1}|
        # term captures (an absent symbol's weight is 0). Summed over the union
        # of the two panels, halved — exactly compute_node_metrics' turnover.
        turnover = 0.5 * math.fsum(
            abs(
                (day_weight if symbol in day_symbols else 0.0)
                - (prev_weight if symbol in prev_symbols else 0.0)
            )
            for symbol in prev_symbols | day_symbols
        )
        rendered[day.isoformat()] = turnover
    return rendered


def render_exec_trace(
    *,
    node_id: str,
    campaign_id: str,
    snapshot_name: str,
    evaluator_hash: str,
    cost_model: object,
    horizons: object,
    charges_budget: bool,
    steps_completed: tuple[int, ...],
) -> dict[str, Any]:
    """The run's deterministic fingerprint — §9.2's ``exec_trace.json``.

    The provenance replay needs to reconstruct one node's evaluation without
    reaching the evaluator (§1 forbids it): whose node it was, which campaign,
    which sealed snapshot, which evaluator image produced it (the ``evaluator_hash``
    feature 70 pins), which fee schedule priced it, which horizons it measured,
    whether the trial consumed budget, and which pipeline steps it completed.
    The fingerprint is deterministic — the same evaluation always renders the
    same trace — so replay can compare a stored trace against the run it is
    reconstructing and know they are one.

    ``horizons`` is the horizon axis the node measured over — :data:`HORIZONS`
    for a full run, :data:`DECAY_HORIZONS` for the decay axis — carried as a list
    so the trace states the panel's depth. ``steps_completed`` is the pipeline
    steps this node reached, in order; a node that failed early carries a shorter
    list, and the charge feature 84 writes is the record that the hypothesis was
    still consumed. ``cost_model`` is carried as its ``venue/version`` reference,
    the same spelling every node record stamps the fee schedule with.
    """
    if not isinstance(node_id, str) or not node_id.strip():
        raise EvaluatorArtifactError(
            f"an exec trace must name the node it fingerprints, got {node_id!r}"
        )
    if not isinstance(campaign_id, str) or not campaign_id.strip():
        raise EvaluatorArtifactError(
            "an exec trace must name the campaign the node was run under, got "
            f"{campaign_id!r}"
        )
    if not isinstance(snapshot_name, str) or not snapshot_name.strip():
        raise EvaluatorArtifactError(
            "an exec trace must name the sealed snapshot the node was measured "
            f"in, got {snapshot_name!r}"
        )
    if not isinstance(evaluator_hash, str) or not evaluator_hash.strip():
        raise EvaluatorArtifactError(
            "an exec trace must carry the evaluator hash the node was produced "
            f"with, got {evaluator_hash!r}; the hash is the fingerprint replay "
            "compares against, and a trace without one cannot say which "
            "evaluator produced the node"
        )
    if not hasattr(cost_model, "reference"):
        raise EvaluatorArtifactError(
            "an exec trace's cost model must carry a reference — the "
            "venue/version the fee schedule is stamped with — got "
            f"{type(cost_model).__name__}; the trace states which fee schedule "
            "priced the node"
        )
    if isinstance(charges_budget, bool):
        charges = charges_budget
    else:
        raise EvaluatorArtifactError(
            f"an exec trace's charges_budget must be a bool — whether the trial "
            f"consumed statistical budget — got {charges_budget!r}; the bit is "
            "the honest record of a consumed hypothesis, and a non-bool is not "
            "the bit feature 84 charges"
        )
    if not isinstance(steps_completed, (tuple, list)) or not all(
        isinstance(step, int) and not isinstance(step, bool)
        for step in steps_completed
    ):
        raise EvaluatorArtifactError(
            "an exec trace's steps_completed must be a sequence of pipeline "
            f"step numbers, got {steps_completed!r}; the trace states which "
            "steps the node reached, and a non-integer step is not a step"
        )
    try:
        horizon_list = list(horizons)
    except TypeError as exc:
        raise EvaluatorArtifactError(
            "an exec trace's horizons must be the horizon axis the node "
            f"measured over — HORIZONS or DECAY_HORIZONS — got {horizons!r}"
        ) from exc
    return {
        "node_id": node_id,
        "campaign_id": campaign_id,
        "snapshot_name": snapshot_name,
        "evaluator_hash": evaluator_hash,
        "cost_model": cost_model.reference,
        "horizons": horizon_list,
        "charges_budget": charges,
        "steps_completed": list(steps_completed),
    }
