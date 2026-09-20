"""Persisting the decay profile — feature 81's other half.

app_spec.xml feature 81: *"System computes a decay profile measuring
information coefficient at each of the five horizons, **persisting it as a
stored array**."*  The computation lives in :mod:`evaluator._decay`; this
module writes it down.  The split is the one this package already uses three
times — ``_identity`` computes and ``_store`` persists for feature 70,
``_costs`` and ``_cost_store`` for 79, ``_capacity`` and ``_capacity_store``
for 82 — and for the same reason: a caller that had to wire the two together
at every call site would eventually wire them together differently at one of
them.

**The stored array is the point, and it is stored twice over.**  The feature
names *one* value — the array — and this table carries it literally, as the
JSON array §9.2 files as ``decay_profile.json``:

.. code-block:: text

    /artifacts/<campaign_id>/<node_id>/
      decay_profile.json

alongside the per-horizon terms the array was reduced from.  That looks like
duplication and is deliberately not: the array is what a reader *consumes*
(positional over ``h = 1, 2, 5, 10, 20``, with ``null`` for a horizon the
window was too short to measure), and the terms are what makes it
*checkable*.  On the read path the terms are reconstructed into
:class:`~evaluator.HorizonDecay` records — each re-deriving its own mean from
its own per-date series — the profile is rebuilt from them, and the stored
array must then equal the array those terms reduce to.  A row whose array was
edited while its terms were left alone, or the reverse, is refused rather than
handed back as a plausible-looking curve.  That is the same defence
``row_to_return`` applies to a stored net that does not equal its own gross
less its own charge and :mod:`evaluator._capacity_store` to a capacity that
does not solve from its own terms, for the same reason: what downstream trusts
is the stored number, and the live loop reads this array entry by entry when it
asks whether a promoted signal's decay has moved.

**Where "a stored array" is stored, and who writes the file.**  §9.2's
directory is owned by the artifacts member (feature 169), which writes
``decay_profile.json`` (feature 172) — exactly as it owns
``signal_returns.parquet`` (feature 170) and ``regime_attribution.json``.  This
module does not write that file: it owns the *evaluator's* half of the feature
— measuring the array and getting it somewhere durable — and it stores it in
the workspace's relational store, addressed by ``DATABASE_URL``, the same
stance feature 79's cost store and feature 82's capacity store take and argue.
The caller holding a campaign and a node artifact directory is what later
writes the JSON, reading this store through :meth:`DecayStore.load`, so the
artifact and the row cannot disagree about what was measured.

**The grain: one row per evaluation per cost model.**  The profile is one
value per evaluation — five positions, one axis — so the table is keyed
``(node_id, venue, version)``, the same key the signal-returns grid and the
capacity table carry, and for the same reason: two fee schedules net different
post-cost returns out of the same gross ones, so the IC measured under one is
not a partial answer to a question about the other, and §15 treats a changed
cost model as its own failure case rather than as noise.  There is no second
table: unlike feature 82's pair, the profile is one object, and splitting the
array from its terms across tables would create a half-written state a reader
would have to refuse rather than a check it could perform — the terms travel
on the row, in one transaction, and the single row is either wholly consistent
with itself or refused.

**Assign-once in effect, though the write is an upsert**, on the same terms the
signal-returns and capacity stores state: the primary key names the evaluation
and the cost model, so a re-measurement over the same bundle refreshes the
stored array rather than adding a second row — and a duplicate row would read
to the live loop as a second observation of the same signal.  The upsert
rewrites the measured values and nothing that *names* the row, so it cannot
re-key a stored profile into a different one.  A *changed* number under an
existing key is not refused: the key names the inputs, so a changed number is a
producer that re-measured, and the last write wins.  What is refused is a row
that cannot be *believed* — an array that disagrees with its own terms, or
terms that disagree with their own series.

**Schema.**  Floats round-trip exactly (JSON numbers are Python reprs; SQLite
TEXT is exact), so the read path's comparisons are exact rather than tolerant,
which is what lets the array-versus-terms check be an equality rather than a
tolerance.  The schema is created idempotently on connect — ``CREATE TABLE IF
NOT EXISTS``, the contract every store in this package states — so a fresh
database and an existing one take one path and no migration step is needed for
this member.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path
from typing import Any, Optional, Union
from urllib.parse import unquote, urlparse

from ._costs import CostModelRef, cost_model_ref
from ._decay import DECAY_HORIZONS, DecayProfile, HorizonDecay
from ._errors import EvaluatorDecayError, EvaluatorStoreError

__all__ = [
    "DATABASE_URL_ENV",
    "DECAY_PROFILE_TABLE",
    "DecayStore",
    "load_decay_profile",
    "persist_decay_profile",
]

#: The environment variable naming the relational store — the one spelling the
#: identity, cost and capacity stores already use, restated here so each store
#: states its own contract (and so no store imports another's).
DATABASE_URL_ENV = "DATABASE_URL"

#: The table the decay profile lives in — one row per evaluation per cost
#: model, carrying the stored array beside the per-horizon terms it reduces
#: from.  Named for §9.2's artifact, ``decay_profile.json``, the way the
#: signal-returns and regime-attribution tables are named for theirs.
DECAY_PROFILE_TABLE = "decay_profile"

_SCHEMA = f"""
-- Feature 81: the decay profile, one row per evaluation per cost model.
--
-- The grain is per-evaluation because the profile is: one five-position array
-- on one axis, plus the per-horizon terms it was reduced from.
-- `(node_id, venue, version)` is the key — the key the signal-returns grid
-- and the capacity table already carry, for the same reason: two fee schedules
-- net different post-cost returns out of the same gross ones, and the IC is
-- measured against those net returns, so the cost model is in the identity of
-- the profile rather than beside it.
--
-- `decay_array` is the feature's own value ("persisting it as a stored
-- array"): a JSON array, one entry per spec horizon in the spec's order, each
-- a number or `null` for a horizon the window was too short to measure —
-- absence carried as null, never as zero, the distinction the whole package
-- maintains.
--
-- `horizon_terms` is JSON, one entry per spec horizon: the terms
-- (`dates`, `mean_ic`, `ic_series`) or `null` for an un-measured horizon. The
-- terms are stored (not just the array) so the read path can rebuild each
-- entry from its own per-date series and refuse a row whose array disagrees
-- with the terms it claims to reduce from — the tamper defence the
-- signal-returns reader applies to `gross - charge` and the capacity reader to
-- a capacity that does not solve from its own terms.
--
-- `ic_series` is stored in full rather than summarised because it is the
-- series §9.2 files separately as `ic_series.parquet` (feature 171) and the
-- dates feature 80's `ic_tstat` is computed over: a mean alone cannot be
-- re-read as a series, and the stored row could not be checked against itself
-- without it.
CREATE TABLE IF NOT EXISTS {DECAY_PROFILE_TABLE} (
    node_id       TEXT NOT NULL,   -- the evaluation this profile measures
    venue         TEXT NOT NULL,   -- feature 59's cost model pair
    version       TEXT NOT NULL,
    snapshot_name TEXT NOT NULL,   -- provenance: which sealed world
    decay_array   TEXT NOT NULL,   -- JSON: the stored array, one entry per horizon
    horizon_terms TEXT NOT NULL,   -- JSON: per-horizon terms or null
    PRIMARY KEY (node_id, venue, version)
);
"""


# -- The JSON spellings ---------------------------------------------------------


def _terms_to_json(horizon_ics: Mapping[int, Optional[HorizonDecay]]) -> str:
    """The per-horizon terms as one JSON object.

    Keys are the horizon as a string (JSON object keys are strings), values
    carry the three terms or ``null`` for an un-measured horizon.  The
    per-date series is nested one level further, keyed by ISO date — the same
    wire spelling every date crosses a boundary as elsewhere in this package.
    Floats serialize as their repr, which round-trips exactly, so the read
    path's checks are equality rather than tolerance.
    """
    return json.dumps(
        {
            str(horizon): (
                None
                if decay is None
                else {
                    "dates": decay.dates,
                    "mean_ic": decay.mean_ic,
                    "ic_series": {
                        day.isoformat(): decay.ic_series[day]
                        for day in sorted(decay.ic_series)
                    },
                }
            )
            for horizon, decay in sorted(horizon_ics.items())
        }
    )


def _array_to_json(horizon_ics: Mapping[int, Optional[HorizonDecay]]) -> str:
    """The stored array as one JSON array, positional over the spec's axis.

    Entry ``i`` is the horizon's mean information coefficient — *reduced from*
    the terms written beside it, never a second measurement — so the read path
    can rebuild the profile from the terms and require the two to agree.
    """
    return json.dumps(
        [
            None if horizon_ics[horizon] is None else horizon_ics[horizon].mean_ic
            for horizon in DECAY_HORIZONS
        ]
    )


def _decode_terms(payload: Any, *, node_id: str) -> dict[int, Optional[HorizonDecay]]:
    """The stored per-horizon terms, back as the records they came from.

    Every horizon the spec names must be present — the writer spells all five
    — and each present value must reconstruct: :class:`HorizonDecay` re-derives
    its own mean from its own per-date series and refuses a record that is not
    its own terms' answer, so this decode *is* the tamper check, not a step
    before one.
    """
    try:
        decoded = json.loads(payload)
    except ValueError as exc:
        raise EvaluatorStoreError(
            f"the stored decay horizon terms for node {node_id!r} are not "
            f"valid JSON: {exc}"
        ) from exc
    if not isinstance(decoded, dict) or set(decoded) != {
        str(horizon) for horizon in DECAY_HORIZONS
    }:
        raise EvaluatorStoreError(
            f"the stored decay horizon terms for node {node_id!r} do not carry "
            "exactly one entry per horizon the spec names; rows are written "
            "with all five, so these did not come out of this store's writer"
        )
    terms: dict[int, Optional[HorizonDecay]] = {}
    for horizon in DECAY_HORIZONS:
        entry = decoded[str(horizon)]
        if entry is None:
            terms[horizon] = None
            continue
        try:
            series = {
                _iso_day(day, node_id=node_id): value
                for day, value in entry["ic_series"].items()
            }
            terms[horizon] = HorizonDecay(
                horizon=horizon,
                dates=entry["dates"],
                mean_ic=entry["mean_ic"],
                ic_series=series,
            )
        except (KeyError, TypeError, AttributeError, EvaluatorDecayError) as exc:
            raise EvaluatorStoreError(
                f"a stored decay entry for horizon {horizon} of node "
                f"{node_id!r} does not reconstruct: {exc}; the row was written "
                "or edited outside this package, and a mean that is not its own "
                "series' mean is a number the artifact would trust and be wrong "
                "by"
            ) from exc
    return terms


def _decode_array(payload: Any, *, node_id: str) -> tuple[Optional[float], ...]:
    """The stored array, checked for shape before it is checked for agreement.

    A JSON array whose length is the axis — one entry per horizon the spec
    names, each a finite number or ``null``.  The values are *not* trusted
    here: :func:`_decode_terms` reconstructs the terms, the profile re-derives
    the array from them, and the caller compares the two — so a hand-edited
    array is caught by the comparison rather than by this decode, and the two
    checks stay separate so the refusal can name which one failed.
    """
    try:
        decoded = json.loads(payload)
    except ValueError as exc:
        raise EvaluatorStoreError(
            f"the stored decay array for node {node_id!r} is not valid JSON: "
            f"{exc}"
        ) from exc
    if not isinstance(decoded, list) or len(decoded) != len(DECAY_HORIZONS):
        length = len(decoded) if isinstance(decoded, list) else "not an array"
        raise EvaluatorStoreError(
            f"the stored decay array for node {node_id!r} carries {length} "
            f"entries; the array is positional over the spec's five horizons "
            f"({', '.join(str(h) for h in DECAY_HORIZONS)}), and rows are "
            "written with one entry each — this did not come out of this "
            "store's writer"
        )
    values: list[Optional[float]] = []
    for position, entry in enumerate(decoded):
        if entry is None:
            values.append(None)
            continue
        if isinstance(entry, bool) or not isinstance(entry, (int, float)):
            raise EvaluatorStoreError(
                f"the stored decay array for node {node_id!r} carries "
                f"{entry!r} at position {position}; the array holds an "
                "information coefficient or null per horizon, and an entry "
                "that is neither is not a stored measurement"
            )
        if not math.isfinite(entry):
            # ``json.loads`` accepts ``NaN``/``Infinity`` — Python's own
            # extensions, not JSON — so a row carrying one is caught here
            # rather than allowed to reach the comparison, where a NaN would
            # silently disagree with everything and be reported as a
            # tampered row instead of an unreadable one.
            raise EvaluatorStoreError(
                f"the stored decay array for node {node_id!r} carries "
                f"{entry!r} at position {position}; a stored coefficient is a "
                "finite number or null, and an infinite or NaN entry is a "
                "number no measurement produced"
            )
        values.append(float(entry))
    return tuple(values)


def _iso_day(value: Any, *, node_id: str) -> dt.date:
    """One ISO date string from a stored series, as a calendar date."""
    try:
        return dt.date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise EvaluatorStoreError(
            f"the stored decay series for node {node_id!r} carries {value!r}, "
            "which is not an ISO 8601 calendar date; series are written as ISO "
            "date strings"
        ) from exc


def _sqlite_path(database_url: str) -> Optional[Path]:
    """Translate a ``sqlite:///`` URL into a path (``None`` for in-memory).

    The same convention the identity, cost and capacity stores document:
    ``sqlite:///foo.db`` is relative, an absolute path carries its leading
    slash after the triple, and any other scheme is refused loudly rather than
    silently mis-parsed.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise EvaluatorStoreError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: this "
            "store speaks sqlite:/// (the spec's single-machine allowance); "
            f"point {DATABASE_URL_ENV} at a sqlite database"
        )
    if parsed.netloc not in ("", "localhost"):
        raise EvaluatorStoreError(
            f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
            f"{parsed.netloc!r}"
        )
    path = unquote(parsed.path).removeprefix("/")
    return Path(path) if path else None


# -- The store -------------------------------------------------------------------


class DecayStore:
    """Reads and writes the ``decay_profile`` table for one database.

    Bound to a database URL at construction; construction performs no I/O (the
    path is resolved and the schema created on first use), so composing an
    application that carries this store touches no disk — the stance every
    store in this workspace takes.  Like the identity, cost and capacity
    stores, and unlike the snapshot member's manifest store, it refuses rather
    than degrading when no store is configured: feature 81's text is
    "persisting", and §9.2's ``decay_profile.json`` is what the live loop reads
    back.
    """

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise EvaluatorStoreError(
                f"{DATABASE_URL_ENV} must be a non-empty database URL"
            )
        self._database_url = database_url.strip()
        self._path: Optional[Path] = None
        self._resolved = False

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(cls, env: Optional[Mapping[str, str]] = None) -> "DecayStore":
        """The store ``DATABASE_URL`` names, or a refusal when it names none.

        An empty or whitespace-only value counts as unset, the way the shared
        fixtures treat an empty ``TEST_DATABASE_URL``.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "")
        if raw is None or not raw.strip():
            raise EvaluatorStoreError(
                f"{DATABASE_URL_ENV} is not set, so there is no store to "
                "persist the decay profile into (app_spec.xml feature 81); set "
                f"{DATABASE_URL_ENV} to the system's database"
            )
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The URL this store was bound to."""
        return self._database_url

    # -- The row ------------------------------------------------------------

    def persist(self, profile: DecayProfile) -> DecayProfile:
        """Write one evaluation's decay profile; return the record.

        The array is written beside the terms it reduces from, in one row and
        one transaction, so a reader never sees an array whose terms are
        missing or vice versa.  One upsert on the evaluation's key, so a
        re-measurement over the same bundle refreshes the stored array rather
        than adding a second row — a duplicate would read to the live loop as a
        second observation of the same signal's decay.

        The upsert refreshes the measured values and nothing that *names* the
        row, so a re-measurement cannot re-key a stored profile.  A store that
        cannot be reached, an unsupported URL scheme, a locked or unwritable
        database — every one surfaces as
        :class:`~evaluator.EvaluatorStoreError`, deliberately not swallowed: an
        array that was measured and never landed is the state feature 81's
        "persisting" exists to rule out.
        """
        if not isinstance(profile, DecayProfile):
            raise EvaluatorDecayError(
                "persist_decay_profile writes step 8's own result — a "
                f"DecayProfile — got {type(profile).__name__}; the array it "
                "stores carries the cost model its returns were priced under, "
                "and anything else has none"
            )
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    f"""
                    INSERT INTO {DECAY_PROFILE_TABLE} (
                        node_id, venue, version, snapshot_name, decay_array,
                        horizon_terms
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(node_id, venue, version) DO UPDATE SET
                        snapshot_name = excluded.snapshot_name,
                        decay_array   = excluded.decay_array,
                        horizon_terms = excluded.horizon_terms
                    """,
                    (
                        profile.node_id,
                        profile.cost_model.venue,
                        profile.cost_model.version,
                        profile.snapshot_name,
                        _array_to_json(profile.horizon_ics),
                        _terms_to_json(profile.horizon_ics),
                    ),
                )
        except (sqlite3.Error, OSError) as exc:
            raise EvaluatorStoreError(
                f"could not persist the decay profile for node "
                f"{profile.node_id!r}: {exc}"
            ) from exc
        return profile

    def load(
        self,
        node_id: str,
        cost_model: Union[CostModelRef, object],
    ) -> Optional[DecayProfile]:
        """Read one evaluation's decay profile back, or ``None``.

        The reader the artifacts member's ``decay_profile.json`` writer
        (feature 172) resolves against: given the node and the cost model a
        score names, answer with the profile that was stored — or ``None``, the
        honest answer for an evaluation this store never measured, on the same
        stance the identity, cost and capacity stores' readers take.

        The ``(venue, version)`` the caller names is *part of the question*,
        not a filter over it: an IC measured under one fee schedule is not a
        partial answer to a question about another.

        What comes back is *checked*, not trusted: each entry re-derives its own
        mean from its own per-date series, the array is re-derived from the
        terms, and the stored array must equal it — so a row whose array was
        edited while its terms were left alone is refused here rather than
        handed back as a plausible-looking decay curve.
        """
        if not isinstance(node_id, str) or not node_id.strip():
            raise EvaluatorStoreError(
                "a node id must be a non-empty string to read a decay profile "
                f"by, got {node_id!r}"
            )
        ref = cost_model_ref(cost_model)
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    f"""
                    SELECT snapshot_name, decay_array, horizon_terms
                    FROM {DECAY_PROFILE_TABLE}
                    WHERE node_id = ? AND venue = ? AND version = ?
                    """,
                    (node_id, ref.venue, ref.version),
                ).fetchone()
        except (sqlite3.Error, OSError) as exc:
            raise EvaluatorStoreError(
                f"could not read the decay profile for node {node_id!r} under "
                f"{ref.reference}: {exc}"
            ) from exc
        if row is None:
            return None
        snapshot_name, array_json, terms_json = row
        terms = _decode_terms(terms_json, node_id=node_id)
        stored_array = _decode_array(array_json, node_id=node_id)
        try:
            profile = DecayProfile(
                node_id=node_id,
                snapshot_name=snapshot_name,
                cost_model=ref,
                horizon_ics=terms,
            )
        except EvaluatorDecayError as exc:
            raise EvaluatorStoreError(
                f"the stored decay row for node {node_id!r} under "
                f"{ref.reference} does not reconstruct: {exc}; the row was "
                "written or edited outside this package"
            ) from exc
        derived = profile.as_array()
        if stored_array != derived:
            raise EvaluatorStoreError(
                f"the stored decay array for node {node_id!r} under "
                f"{ref.reference} is "
                f"{[None if v is None else round(v, 6) for v in stored_array]} "
                "but its own horizon terms reduce to "
                f"{[None if v is None else round(v, 6) for v in derived]}; the "
                "row disagrees with itself, so it was written or edited outside "
                "this package — a stored array that is not the array its terms "
                "measure is a decay curve the live loop would read and act on"
            )
        return profile

    # -- Connection ---------------------------------------------------------

    def _resolve_path(self) -> Optional[Path]:
        """Resolve the sqlite path once, refusing schemes this store cannot read.

        Deferred out of ``__init__`` so construction performs no I/O.  An
        in-memory URL resolves to ``None``, which :meth:`_connect` reads as
        "use ``:memory:``" — per-connection, which is why the schema is created
        on every connect rather than cached.
        """
        if self._resolved:
            return self._path
        self._path = _sqlite_path(self._database_url)
        self._resolved = True
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """Open the store and ensure its schema exists.

        Idempotent on every connect, so a fresh database and an existing one
        take the same path.  The caller owns the connection.
        """
        self._resolve_path()
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self._path)
        else:
            connection = sqlite3.connect(":memory:")
        with connection:
            connection.executescript(_SCHEMA)
        return connection


# -- The module-level spellings the pipeline calls -----------------------------


def persist_decay_profile(
    profile: DecayProfile,
    database_url: Optional[str] = None,
) -> DecayProfile:
    """Persist step 8's decay result; return the record that was written.

    Feature 81's two verbs, joined: :func:`evaluator.compute_decay_profile`
    measures the array and this writes it down.  ``database_url`` falls back to
    ``DATABASE_URL``, and a missing store is refused by name rather than
    silently skipped — feature 81 says "persisting", so an array that never
    landed is the gap it exists to close.
    """
    url = (
        database_url
        if database_url is not None
        else os.environ.get(DATABASE_URL_ENV)
    )
    if not url or not url.strip():
        raise EvaluatorStoreError(
            f"{DATABASE_URL_ENV} is not set, so there is no store to persist "
            "the decay profile into (app_spec.xml feature 81); set "
            f"{DATABASE_URL_ENV} to the system's database, or pass one "
            "explicitly"
        )
    return DecayStore(url.strip()).persist(profile)


def load_decay_profile(
    node_id: str,
    cost_model: Union[CostModelRef, object],
    database_url: Optional[str] = None,
) -> Optional[DecayProfile]:
    """Read one evaluation's decay profile back, or ``None``.

    The functional spelling of :meth:`DecayStore.load`, for a caller that has
    no store object and only a node and a cost model: the store is resolved
    from ``DATABASE_URL``, and a missing one is refused by name rather than
    answered with a ``None`` that would read as "never measured".
    """
    url = (
        database_url
        if database_url is not None
        else os.environ.get(DATABASE_URL_ENV)
    )
    if not url or not url.strip():
        raise EvaluatorStoreError(
            f"{DATABASE_URL_ENV} is not set, so there is no store to read the "
            f"decay profile for node {node_id!r} from; set "
            f"{DATABASE_URL_ENV} to the system's database, or pass one "
            "explicitly"
        )
    return DecayStore(url.strip()).load(node_id, cost_model)
