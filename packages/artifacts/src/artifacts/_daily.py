"""The downsampled daily return series — §9.3's scaling caveat, feature 180.

app_spec.xml, "Tree & Artifact Persistence", feature 180: *System
downsamples a high-frequency return series to daily for replay-time
computation, retaining the fine series for promotion decisions.*
docs/nullius-tech-architecture.md §9.3 draws the line that sentence
answers, in the scaling caveat it records against the resident campaign
arrays:

    Moving to intraday rebalancing (5-minute bars, ``T ≈ 200,000``)
    scales every figure above by 100× and the resident set to ~80 GB.
    At that point, downsample to daily for replay-time IR and retain the
    high-frequency series only for the final promotion decision.

**Two series, one node, two decisions.**  §9.2's ``signal_returns.parquet``
is the node's returns kept whole at the finest grain the evaluator
computed them — one row per ``(rebalance date, horizon, symbol)`` — so
that marginal contribution can be recomputed against any book at replay
time (:mod:`artifacts._returns`, feature 170).  That file is the *fine*
series, and it is what the final promotion decision reads.  This module
adds a second file, ``daily_returns.parquet`` — the *daily* series: the
node's fine grid reduced to one equal-weight per-date return, the coarser
input replay-time IR is computed over once the bars are finer than daily.
The two files are distinct artifacts for distinct decisions, and the
distinction is load-bearing: the daily file is *derived from* the fine
grid and persisted beside it, but the fine grid is never reduced,
overwritten or dropped by the downsample — a replay measuring IR over the
daily series still has the whole grid to promote against, which is the
"retaining the fine series" the feature's sentence pins.

**The reduction is the evaluator's own, restated for the daily file.**
The daily value of a date is the equal-weight per-date post-cost return
at the pinned horizon — ``fsum`` over the day's ``post_cost_return`` over
the count of symbols that date holds, feature 80's own reduction of a
priced panel to "the equal-weight book's" per-date return, the very
series ``ir_standalone`` and ``ir_marginal`` are defined over, and the
one feature 174's dense campaign load applies at campaign scale.  This
module does not re-derive that arithmetic: it reads the node's grid
through feature 170's read side (:func:`~artifacts.signal_returns`, every
row, nothing reduced — there is no second decoder to trust) and applies
the same mean over each date's own cross-section, so a symbol entering or
leaving the panel re-weights the day the way the turnover metric says it
does.  The daily series is therefore the fine grid collapsed on one axis
— the symbol axis — while the horizon axis is pinned and the date axis is
kept.

**The horizon is a policy, not a guess.**  The fine grid is five horizons
deep and the daily series holds one, so the downsample pins a horizon —
the shortest horizon **every** priced date of the node's grid covers, the
evaluator's ``METRICS_HORIZON`` policy ("the shortest horizon the priced
panel covers", :mod:`evaluator._metrics`) restated for the daily file,
the same policy feature 174 pins at campaign scale: the fastest-turning,
best-evidenced, hardest-hit horizon is the axis the daily replay sits on,
and a function of the grid rather than a caller's guess is what makes two
downsamples of one node answer the same series.  A caller measuring at
another horizon may pin it with ``horizon=``; the grid is on disk in full
precisely so another axis can be loaded, and the default is a policy
rather than a knob.  A date a pinned horizon did not reach is left out of
the daily series rather than written as a stand-in, and a grid covering
no date at the pinned horizon at all refuses — that is not a sparse
measurement but a node the pinned axis does not answer.

**Absence is a missing key, not zero — and the daily file keeps it honest.**
A date the grid priced at some horizons but not the pinned one has no row
to reduce, so it has no daily return to record: the downsample leaves it
out of the series rather than writing a stand-in.  Zero would be the lie —
zero is a *measurement* ("the signal returned nothing") — and the
alignment layer's own rule ("a target that cannot be computed is
**absent**, never zero-filled") holds here too.  Rather than a NaN cell on
a dense axis the downsample stores a sparse date-keyed series, feature
171's own shape: a date the pinned horizon measured is a key the mapping
holds, a date it did not reach is a key the mapping does not hold, and a
caller asking whether a date was on the axis asks ``in``, not ``isnan``.
The daily file is a *stored measurement*, so it keeps the float64 the
evaluator computed (:mod:`artifacts._series` says so in as many words —
the daily value is read once per node, not once per replay, so there is
no residency to shrink the way §9.3's ``float32`` shrinks the resident
array).  A date the grid covers at the pinned horizon is a real number;
a date it does not is not in the series at all.

**It rides feature 169's staged write path and feature 171's series
codec, and is a new name, not a replacement.**  The daily series is one
``{date: value}`` mapping, exactly feature 171's shape, so it is rendered
and read by feature 171's own codec (:func:`~artifacts._series.
encode_series` / :func:`~artifacts._series.decode_series`, the
``date32``/``float64`` schema, the Zstd codec) rather than a second one —
one shape, one codec, one set of refusals, and the same Parquet-with-Zstd
bytes a DuckDB scan reads in place (§4.1).  It stages through
:meth:`~artifacts.ArtifactStore.write` and publishes by the node's one
:meth:`~artifacts.ArtifactStore.commit`, the same discipline feature 169
states: a failure before the commit publishes nothing, a
:meth:`~artifacts.ArtifactStore.discard` rolls it back with every other
staged file, and a refresh replaces it wholesale.  The one thing that
distinguishes this file from feature 171's two is that the node already
holds a published directory when the daily file is added, and ``commit``
publishes the *staged set* as the node's directory — replacing it
wholesale — so a downsample that staged only ``daily_returns.parquet``
would publish a node that had lost its grid.  The persist therefore
re-stages every file the node already holds alongside the daily file and
commits the union once: the fine grid comes back exactly as it was, the
daily file joins it, and a refresh of the daily file re-stages the one
name, keeping the last bytes, never a splice of two runs.  The grid is
never this module's to write.

**The read side answers the shape this writer emits, and refuses what it
cannot.**  :func:`daily_returns` answers a ``{date: value}`` by the
node's same two keys and through the store's read surface — the one §1
grants the replay engine, and nothing else.  Bytes that are not Parquet,
a file whose columns are not ``date32``/``float64``, a null or non-finite
entry, a duplicate date and a file naming a node other than the one it
was read from each refuse with
:class:`~artifacts._errors.ArtifactStoreError` rather than answering a
stand-in — feature 171's own refusals, answered through the one codec.
Nothing is reduced on the way out: every date the downsample produced is
answered, because a caller that asks for the daily series is asking for the
daily series, and a date the pinned axis did not reach is the honest "this
date was not on the pinned axis" rather than a zero dressed as one.

**pyarrow is imported lazily, on the seam the rest of this category
uses.**  The member is imported by the factory's workspace scan, so
anything imported at module scope is imported during composition; a hard
``import pyarrow`` here would make pyarrow a precondition for *composing
the application*, a much larger blast radius than this file needs —
feature 169's keying, write path and read side need no Arrow at all.  So
:func:`require_arrow` defers the import to first use, exactly as
feature 171's series module does, and names the missing dependency when
it is reached without one.  The parquet *dependency* is declared in this
member's ``pyproject.toml`` all the same: the seam lives in the member
that declares it.
"""

from __future__ import annotations

import datetime as dt
import math
from pathlib import Path
from typing import Any

from ._errors import ArtifactNotFoundError, ArtifactStoreError
from ._keys import validate_campaign_id, validate_node_id
from ._returns import SignalReturns, signal_returns
from ._series import decode_series, encode_series
from ._store import ArtifactStore

__all__ = [
    "DAILY_RETURNS_FILENAME",
    "daily_returns",
    "daily_returns_is_persisted",
    "persist_daily_returns",
]

#: The §9.3 name of the node's downsampled daily return series — the daily
#: counterpart to §9.2's ``signal_returns.parquet``, derived from the fine
#: grid and persisted beside it.  Spelled once here so the write path, the
#: read side and the tests this feature owns cannot drift apart on what the
#: file is called.
DAILY_RETURNS_FILENAME = "daily_returns.parquet"


# -- The write half ----------------------------------------------------------------


def persist_daily_returns(
    store: ArtifactStore,
    campaign_id: str,
    node_id: str,
    *,
    horizon: int | None = None,
) -> Path:
    """Downsample the node's fine grid to ``daily_returns.parquet`` and publish it.

    The feature's sentence as one call over feature 169's staged write
    path: the node's ``signal_returns.parquet`` — read back through
    feature 170's own read side, the only decoder this downsample trusts —
    is reduced to one equal-weight per-date post-cost return at the pinned
    horizon, rendered through feature 171's ``date32``/``float64`` series
    codec, and published by the node's one commit as a new file beside the
    fine grid.  The fine grid is never written, overwritten or dropped:
    the persist re-stages every file the node already holds alongside the
    daily file and commits the union once, because ``commit`` publishes the
    *staged set* as the node's directory (replacing it wholesale) and a
    downsample that staged only the daily file would publish a node that
    had lost its grid.

    The horizon is :data:`~artifacts._campaign.CAMPAIGN_LOAD_HORIZON`'s
    per-node twin — the shortest horizon every priced date of the node's
    grid covers, the evaluator's ``METRICS_HORIZON`` policy restated for
    the daily file — unless ``horizon`` pins another one explicitly.  A
    date the grid priced at some horizons but not the pinned one is left
    out of the daily series rather than written as a stand-in, and a grid
    covering no date at the pinned horizon refuses.

    Every refusal — a malformed key, a node with no published grid, a node
    whose grid covers no date at the pinned horizon, a pinned horizon no
    date covers — lands before the first staged byte, so a refused
    downsample leaves the staged set and the published directory exactly as
    they were.  Returns the staged path for a caller that wants to name
    what it staged; the commit, not this call, is the publication.
    """
    validate_campaign_id(campaign_id)
    validate_node_id(node_id)
    pinned = _pinned_horizon(store, campaign_id, node_id, requested=horizon)
    daily = _downsample(store, campaign_id, node_id, pinned)
    payload = encode_series(
        daily,
        filename=DAILY_RETURNS_FILENAME,
        campaign_id=campaign_id,
        node_id=node_id,
    )
    return _publish_with_grid(
        store, campaign_id, node_id, DAILY_RETURNS_FILENAME, payload
    )


def _publish_with_grid(
    store: ArtifactStore,
    campaign_id: str,
    node_id: str,
    filename: str,
    payload: bytes,
) -> Path:
    """Stage ``filename`` alongside the node's published files, then commit.

    ``commit`` publishes the staged set as the node's directory, replacing
    it wholesale, so a downsample that staged only the daily file would
    publish a node that had lost its grid.  The node's already-published
    files are therefore re-staged verbatim — the fine grid among them,
    read back byte for byte and never touched — and the new file joins
    them, so the one commit publishes the union: the grid exactly as it
    was, the daily file beside it.  A refresh re-stages the one name,
    keeping the last bytes, never a splice of two runs.
    """
    for existing in store.files(campaign_id, node_id):
        store.write(campaign_id, node_id, existing, store.read(campaign_id, node_id, existing))
    return store.write(campaign_id, node_id, filename, payload)


# -- The read half -----------------------------------------------------------------


def daily_returns(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> dict[dt.date, float]:
    """The node's downsampled daily return series, read back by date.

    The read side of the feature's file: the bytes persisted as
    ``daily_returns.parquet``, decoded and answered as ``{date: value}``
    in ascending date order — the per-date daily return the replay engine
    measures IR over once the bars are finer than daily, read through the
    store's read surface — the one §1 grants the replay engine, and
    nothing else.

    Refuses with :class:`~artifacts._errors.ArtifactNotFoundError` when the
    node holds no directory or its directory holds no
    ``daily_returns.parquet``, the refusal naming which half is missing —
    so a node that never downsampled stays distinguishable from one
    downsampled without its daily file.  Bytes this layer's writer cannot
    have produced — not Parquet, the wrong ``date32``/``float64`` columns,
    a null or non-finite entry, a duplicate date, a file naming a node
    other than the one it was read from — refuse with
    :class:`~artifacts._errors.ArtifactStoreError` rather than answering a
    stand-in, through feature 171's own codec.  A date the downsample did
    not measure (absent at the pinned horizon) is simply not a key of the
    mapping — the honest "no data here", not a zero dressed as a
    measurement, and not a NaN cell either — so a caller that asks whether
    a date was on the daily axis asks ``in``, not ``isnan``.
    """
    raw = store.read(campaign_id, node_id, DAILY_RETURNS_FILENAME)
    return decode_series(
        raw,
        filename=DAILY_RETURNS_FILENAME,
        campaign_id=campaign_id,
        node_id=node_id,
    )


def daily_returns_is_persisted(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> bool:
    """Whether the node's published artifact carries its daily return series.

    The feature's file as a fact: the node's directory is published *and*
    holds ``daily_returns.parquet``.  ``False`` for a node nothing was
    published for — staged-but-uncommitted is invisible by design, the
    discipline feature 169 states — and ``False`` for a directory
    published without the daily file, which is the state a reconciliation
    sweep exists to find.  Presence, not validity: a file this writer did
    not render is still a file at the name, and a sweep that wants its
    *content* checked asks :func:`daily_returns` and gets the refusal that
    names what is wrong.
    """
    return _is_persisted(store, campaign_id, node_id, DAILY_RETURNS_FILENAME)


def _is_persisted(
    store: ArtifactStore, campaign_id: str, node_id: str, filename: str
) -> bool:
    """Whether the node's published directory holds ``filename``.

    The shared half of this member's ``*_is_persisted`` predicates: a node
    that was never published is ``False`` (staged-but-uncommitted is
    invisible by design), and otherwise presence is a plain membership
    check against the published file set — presence, not validity, so a
    file this writer did not render still counts as present and a sweep
    that wants its content checked asks the read side.
    """
    if not store.has_node(campaign_id, node_id):
        return False
    return filename in store.files(campaign_id, node_id)


# -- The downsample, spelled once --------------------------------------------------


def _pinned_horizon(
    store: ArtifactStore,
    campaign_id: str,
    node_id: str,
    *,
    requested: int | None,
) -> int:
    """Resolve the one horizon the daily series is downsampled over.

    An explicit ``requested`` horizon is validated as the positive period
    count it must be (:func:`artifacts._returns._validated_horizon`, the
    one spelling of that rule) and answered — whether a date covers it is
    each date's own question, answered by :func:`_downsample`.

    Without one, this resolves the shortest horizon **every** priced date
    of the node's grid covers — the evaluator's ``METRICS_HORIZON`` policy
    ("the shortest horizon the priced panel covers") restated for the
    daily file, the same policy feature 174 pins at campaign scale.  A
    dense daily axis is one horizon deep for all its dates, so the
    per-date policy has to meet the intersection, and an empty
    intersection — a grid whose dates share no horizon — refuses rather
    than guessing: dates with no common horizon are measurements no single
    daily axis is defined over.
    """
    if requested is not None:
        return _validated_horizon(requested)
    panel = _grid(store, campaign_id, node_id)
    by_date: dict[dt.date, set[int]] = {}
    for row in panel.rows:
        by_date.setdefault(row.rebalance_date, set()).add(row.horizon)
    shared: set[int] | None = None
    for covered in by_date.values():
        shared = covered if shared is None else shared & covered
    if not shared:
        raise ArtifactStoreError(
            f"node {node_id!r} of campaign {campaign_id!r} covers no "
            "horizon every priced date shares — "
            + "; ".join(
                f"{day.isoformat()} covers {', '.join(str(h) for h in sorted(horizons))}"
                for day, horizons in sorted(by_date.items())
            )
            + "; a daily downsample is one horizon deep for every date at "
            "once, so a grid with no common horizon is measurements no "
            "single daily axis is defined over"
        )
    return min(shared)


def _grid(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> SignalReturns:
    """The node's fine grid, or the downsample's own refusal naming it.

    Reads through feature 170's read side — the only decoder this
    downsample trusts — but translates the read side's
    :class:`~artifacts._errors.ArtifactNotFoundError` ("no such node") into
    the downsample's precondition failure: a node with no fine grid has
    nothing to downsample, and a caller that asked to downsample a node's
    returns should be told the grid is missing, not that the node does not
    exist.
    """
    try:
        return signal_returns(store, campaign_id, node_id)
    except ArtifactNotFoundError as exc:
        raise ArtifactStoreError(
            f"node {node_id!r} of campaign {campaign_id!r} has no fine "
            f"signal-returns grid to downsample — {exc}; the daily series "
            "is derived from the node's priced grid, and a node that priced "
            "no grid has no returns to reduce (persist the grid first, on "
            "the axis the daily series shares)"
        ) from exc


def _validated_horizon(value: Any) -> int:
    """Return ``value`` as the positive period count it must be, or refuse it.

    A ``bool`` is refused even though it is an :class:`int` in Python:
    ``True`` is ``1``, and a flag where a period count belongs would
    silently measure the shortest horizon of the spec — the kind of
    mistake that produces a plausible number rather than an error.  The
    one spelling of this rule is feature 170's
    :func:`artifacts._returns._validated_horizon`; this module does not
    restate the evaluator's vocabulary, only the shape the axis needs.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise ArtifactStoreError(
            f"a daily downsample's horizon is an integer period count — got "
            f"{value!r} ({type(value).__name__}); the horizon is the axis the "
            "daily series is reduced over, and a row that does not name one "
            "belongs to no horizon any metric is measured over"
        )
    if value < 1:
        raise ArtifactStoreError(
            f"a daily downsample's horizon is a positive period count — got "
            f"{value!r}; a return is measured *forward* from its rebalance "
            "date, and a horizon of zero or fewer periods measures the bar it "
            "is already on"
        )
    return value


def _downsample(
    store: ArtifactStore,
    campaign_id: str,
    node_id: str,
    horizon: int,
) -> dict[dt.date, float]:
    """One node's fine grid reduced to its daily series — the equal-weight per-date return.

    Reads the node's ``signal_returns.parquet`` through feature 170's own
    read side — every row, nothing reduced, the only decoder this
    downsample trusts — keeps the rows at the pinned horizon, and reduces
    each date's cross-section to the mean of its post-cost returns:
    ``fsum`` over the day's values divided by their count, feature 80's own
    reduction of a priced panel to the equal-weight book's per-date return,
    the very series ``ir_standalone`` and ``ir_marginal`` are defined over.
    Equal-weight within each date's *own* cross-section, so a symbol
    entering or leaving the panel re-weights the day the way the turnover
    metric says it does.

    A date the grid priced at some horizons but not the pinned one is left
    out of the daily series entirely — there is no row to reduce for it, so
    there is no daily return to record, the same sparse-date-keyed shape
    feature 171's codec stores, where a date a series has no value for is
    simply not a key.  The daily axis therefore carries exactly the dates
    the pinned horizon measured, in ascending date order, and a date the
    pinned horizon did not reach is a key the mapping does not hold — a
    caller asking whether a date was on the axis asks ``in``, not
    ``isnan``.  Zero is not written for such a date (zero is a measurement,
    "the signal returned nothing") and neither is NaN (there is no cell to
    mark absent, only a key that is not there).  A grid that covers no date
    at the pinned horizon at all refuses — that is not a sparse measurement
    but a node the pinned axis does not answer, and an all-absent daily
    series is a document this writer never produced.

    The grid is read through feature 170's read side (:func:`_grid`), which
    answers a node it holds no directory for as the read side's honest "no
    such node"; :func:`_grid` translates that into the downsample's
    precondition failure, so a caller that asked to downsample a node's
    returns is told the grid is missing, not that the node does not exist.
    """
    panel = _grid(store, campaign_id, node_id)
    per_date: dict[dt.date, list[float]] = {}
    for row in panel.rows:
        if row.horizon == horizon:
            per_date.setdefault(row.rebalance_date, []).append(row.post_cost_return)
    if not per_date:
        raise ArtifactStoreError(
            f"node {node_id!r} of campaign {campaign_id!r} covers no "
            f"rebalance date at horizon {horizon} — its grid covers "
            f"{', '.join(str(h) for h in sorted({r.horizon for r in panel.rows})) or 'no horizon'}; "
            "the daily downsample is one horizon deep for every date, so a "
            "node the pinned axis does not measure has no daily series to "
            "answer (pin the horizon the grid covers, or persist the grid "
            "on the axis the daily series shares)"
        )
    return {
        day: math.fsum(per_date[day]) / len(per_date[day])
        for day in sorted(per_date)
    }
