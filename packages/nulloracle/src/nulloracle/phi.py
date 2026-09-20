"""The planted-null fraction φ, computed from a campaign's workspace count.

app_spec.xml, "Null Oracle & Planted Nulls", feature 117: *System persists
the null fraction phi on the campaign, computed as a clip of 2 divided by the
workspace count against a floor of 0.15 and a ceiling of 0.35.*  This module
is that computation and the store that writes it down.  The computation is
the whole of the feature's load-bearing claim — ``φ = clip(2/W, 0.15,
0.35)`` — and it is deliberately the *only* place the clip is spelled, so the
number a campaign is planned with and the number a reader reads back are one
number, not two that could drift.

**Where φ lands, and why it is not a new column.**  The spec declares the
column: ``migrations/versions/0111_campaign_table.py`` creates ``campaign``
with ``null_fraction REAL NOT NULL`` and states exactly what it is for —
*"φ, the planted-null fraction, fixed at planning time as clip(2/W, 0.15,
0.35) … stored, not derived … the value that lands here is the planner's,
already clipped"* — and it is ``NOT NULL`` on purpose, so that a campaign
without a fraction is the one thing the planner never ships rather than a
state this store could paper over with a default.  This module is the writer
that column was created for, and it writes it there rather than into a table
of its own: feature 118's Type-R draw and feature 119's Type-D flip depth
read this fraction, and a second location would be a second answer.

**The fraction is a fact about a campaign, so the campaign is never created
here.**  ``null_fraction`` is fixed *before any node is expanded* — the
migration states the fraction is "fixed at planning time, not learned from
the run" — which is the planner's job (feature 232's ``discovery`` plugin),
not this member's.  So this store, like feature 123's guard and feature
124's verdict, opens the campaign table idempotently but refuses to *create*
the row: a store that inserted the missing campaign would be inventing the
row the type and the workspace count belong on, and a fraction written onto
a row this store invented would be a fraction nobody planned.  A campaign the
table does not hold raises :class:`~nulloracle.errors.KsGuardError` by name —
the same error the guard and the verdict raise for the same reason, because
all three join the campaign row and a malformed id or an unknown campaign is
the same kind of store-contract failure for each.

**The clip is validated, not merely applied.**  ``2/W`` is a decreasing
function of ``W``, so the clip is not decoration: it is the thing that keeps
a small campaign from planting a fraction larger than a third of its wells
and a large one from planting so few nulls that its KS guard is measuring
nothing.  The floor and the ceiling are constants of this module because
this module is the one place the fraction is computed — a second spelling
would be a second definition of the campaign's headline design choice.  The
computation refuses a workspace count that is not a genuine positive
integer: ``W`` is the well count of the discovery tree, and ``W = 0`` is a
division by zero, ``W < 0`` is not a count, and a non-integer ``W`` is not a
count either — feature 117's ``2/W`` is a count over a count, and a
truthy-looking non-integer would plant a fraction no campaign was designed
with.  The raw ``2/W`` is not itself refused when it falls outside the clip:
a small campaign's ``2/W`` genuinely exceeds the ceiling and a large one's
genuinely falls below the floor, and clamping those is the clip's job — what
is refused is a ``W`` that makes ``2/W`` meaningless, not a ``W`` whose
fraction the clip corrects.

**Stdlib only, and import-cheap.**  ``sqlite3`` and ``urllib.parse``; no
third-party import at module scope, so the factory's scan — which imports
this package to fire its ``@register`` — pays nothing for this module, the
same discipline feature 123's store states and for the same reason: the
member already defers ``cryptography`` to first use, and a store that pulled
a driver in at import would undo that.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .assignment import normalize_node_id
from .errors import KsGuardError

__all__ = [
    "CAMPAIGN_TABLE",
    "DATABASE_URL_ENV",
    "NULL_FRACTION_COLUMN",
    "PHI_CEILING",
    "PHI_FLOOR",
    "WORKSPACE_COUNT_COLUMN",
    "PlantedNullFraction",
    "null_fraction",
    "persist_null_fraction",
]

#: The environment variable naming the relational store — the one spelling
#: every store in this workspace already uses (the ledger's, the guard's, the
#: verdict's, the evaluator's five, the repository-level conftest's), restated
#: here so each store states its own contract and none imports another's.
DATABASE_URL_ENV = "DATABASE_URL"

#: The table the fraction is written to — feature 104's ``campaign``, created
#: by ``migrations/versions/0111_campaign_table.py``.  Spelled once here, and
#: once in :mod:`nulloracle.ksguard` and once in :mod:`nulloracle.verdict`, so
#: the three writers cannot drift apart on what the campaign table is called;
#: all three name the column the migration created.
CAMPAIGN_TABLE = "campaign"

#: The campaign row's planted-null fraction — feature 117's column.  Spelled
#: once here so the writer and the migration cannot drift apart on what the
#: fraction column is named.
NULL_FRACTION_COLUMN = "null_fraction"

#: The campaign row's workspace count — ``W``, the denominator of the
#: fraction.  Spelled once here so the writer names the column the migration
#: created rather than one it guessed.
WORKSPACE_COUNT_COLUMN = "workspace_count"

#: The clip's floor — the smallest fraction a campaign plants.  §4.1.1's own
#: value, kept as a constant of this module because this module is the one
#: place the fraction is computed, and a second spelling would be a second
#: definition of the campaign's headline design choice.
PHI_FLOOR = 0.15

#: The clip's ceiling — the largest fraction a campaign plants.  §4.1.1's own
#: value, kept beside :data:`PHI_FLOOR` for the same reason: the floor and the
#: ceiling are the two bounds the clip applies, and they belong where the clip
#: is.
PHI_CEILING = 0.35


def null_fraction(workspace_count: Any) -> float:
    """§4.1.1's planted-null fraction: ``φ = clip(2/W, 0.15, 0.35)``.

    The whole of feature 117's computation in one call: divide two by the
    workspace count and clip the result into the ``[0.15, 0.35]`` band.  The
    clip is not decoration — ``2/W`` is a decreasing function of ``W``, so a
    small campaign's fraction is held at the ceiling and a large one's lifted
    to the floor, and the band is what keeps a campaign from planting either
    more than a third of its wells or so few nulls that its KS guard has
    nothing to measure.

    Refuses a ``workspace_count`` that is not a genuine positive integer, and
    names what it refuses:

    * ``W`` that is a bool — ``True`` and ``False`` are not counts, and a
      truthy-looking ``True`` would plant ``φ = clip(2/1, …) = 0.35`` for a
      "campaign" of one well that is not a campaign at all;
    * ``W`` that is not an ``int`` — a fractional well count is not a count;
    * ``W < 1`` — ``W = 0`` is a division by zero and ``W < 0`` is not a
      count, and a fraction computed from either would be a fraction no
      campaign was designed with.

    The returned value is always inside ``[PHI_FLOOR, PHI_CEILING]``: the clip
    is applied unconditionally, so a caller gets a fraction it can plant
    without re-checking the band.  A ``2/W`` that lands inside the band is
    returned unchanged; one outside it is clamped, which is the clip's whole
    purpose rather than an error to report.
    """
    if isinstance(workspace_count, bool) or not isinstance(workspace_count, int):
        raise KsGuardError(
            f"workspace_count must be a positive integer, got {workspace_count!r} "
            f"({type(workspace_count).__name__}); φ is clip(2/W, 0.15, 0.35) and "
            "W is the well count of the discovery tree, a count and not a "
            "truthy-looking non-integer"
        )
    if workspace_count < 1:
        raise KsGuardError(
            f"workspace_count must be at least 1, got {workspace_count!r}; φ is "
            "clip(2/W, 0.15, 0.35), and W = 0 divides by zero while W < 0 is "
            "not a count a campaign was planned with"
        )
    raw = 2.0 / workspace_count
    return min(max(raw, PHI_FLOOR), PHI_CEILING)


class PlantedNullFraction:
    """The store that writes φ onto its campaign — feature 117's writer.

    Constructed with the database URL it reads from; :meth:`persist` writes
    ``clip(2/W, 0.15, 0.35)`` to ``campaign.null_fraction`` for one campaign,
    and :meth:`load` reads one campaign's stored fraction back.  The class
    resolves its path lazily, so constructing one performs no I/O —
    composition-time work must not touch the disk, the contract every store in
    this workspace states, and the one feature 123's and feature 124's stores
    state for the same campaign table.

    The store holds no scores and no labels: it writes one number, computed
    from one count, onto one column.  There is no field here that could leak a
    label partition, deliberately — see :mod:`nulloracle.assignment` and §4.2.
    """

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise KsGuardError(
                f"{DATABASE_URL_ENV} must be a non-empty database URL"
            )
        self._database_url = database_url.strip()
        # Resolved on first use rather than at construction: building the
        # store is composition-time work and must not touch the disk.
        self._path: Path | None = None

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(
        cls, env: Mapping[str, str] | None = None
    ) -> PlantedNullFraction | None:
        """The fraction store ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset.  Absent is not an
        error: it is a deployment without a relational store, which composes
        no fraction component — a discoverable state, not an exception — while
        the campaign planner that must fix §4.1.1's fraction is the caller
        that must not find itself in it.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The database URL this store reads from."""
        return self._database_url

    @property
    def path(self) -> Path:
        """The SQLite file backing this store, resolved on first use.

        Nothing is created at construction — the URL is translated (and a
        URL this member cannot speak is refused by name) the first time an
        operation needs it.
        """
        if self._path is None:
            self._path = _sqlite_path(self._database_url)
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """Open the database and ensure the campaign table exists, idempotently.

        ``CREATE TABLE IF NOT EXISTS`` on the campaign table — the contract
        every store in this workspace states and the one
        ``migrations/versions/0111_campaign_table.py`` describes for its
        orchestrator: a fresh database and an existing one take the same path,
        so no migration step is needed here and running the migration over a
        database this store created changes nothing.  The caller owns the
        connection; use it as a context manager to commit.
        """
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        with connection:
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {CAMPAIGN_TABLE} (
                    id                 UUID NOT NULL PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', abs(random()) % 4 + 1, 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
                    campaign_type      TEXT NOT NULL,
                    workspace_count    INT NOT NULL,
                    null_fraction      REAL NOT NULL,
                    calibration_status TEXT NOT NULL DEFAULT 'ok',
                    ks_pvalue          REAL,
                    created_at         TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                );
                """
            )
        return connection

    # -- Feature 117: the write -------------------------------------------

    def persist(self, campaign_id: Any, workspace_count: Any) -> float:
        """Compute §4.1.1's fraction for ``campaign_id`` and persist it.

        The whole of feature 117 in one call: the campaign is confirmed to
        exist, the fraction is computed as ``clip(2/W, 0.15, 0.35)`` from the
        caller's workspace count, and it is written to ``campaign.null_fraction``.

        The workspace count is the caller's — taken as an argument rather than
        read back from the row — because the fraction is fixed *at planning
        time*, before any node is expanded, and the planner is the caller that
        knows the ``W`` it planned the campaign with.  The value written is the
        clipped one, so the row carries the fraction the campaign was designed
        with, already bounded into ``[0.15, 0.35]``.

        Refuses, in this order, and each refusal names what it is about:

        1. a malformed ``campaign_id`` or a workspace count that is not a
           genuine positive integer (:class:`~nulloracle.errors.KsGuardError`)
           — the fraction is ``clip(2/W, 0.15, 0.35)``, and a ``W`` that is
           not a count cannot be its denominator;
        2. a campaign the table does not hold (:class:`~nulloracle.errors.
           KsGuardError`) — the fraction is a fact about a campaign, and
           writing it onto a row this store invented would fabricate the
           campaign the fraction belongs to;
        3. a write that could not be completed.

        The write is idempotent by campaign: re-running it on a campaign with
        the same ``W`` leaves the fraction unchanged, and with a different
        ``W`` refreshes it — the planner's ``W`` is the source of truth, and a
        campaign re-planned with a new workspace count is the exact thing a
        refreshed fraction records.  What the table holds is the latest
        planning decision and nothing else.
        """
        campaign = _validated_campaign_id(campaign_id)
        fraction = null_fraction(workspace_count)
        with closing(self._connect()) as connection, connection:
            self._require_campaign(connection, campaign)
            connection.execute(
                f"UPDATE {CAMPAIGN_TABLE} SET {NULL_FRACTION_COLUMN} = ? WHERE id = ?",
                (fraction, campaign),
            )
            stored = self._read_campaign_fraction(connection, campaign)
            if stored != fraction:
                raise KsGuardError(
                    f"campaign {campaign!r} was written half: the fraction row "
                    f"holds {fraction!r} and the campaign row holds {stored!r}; "
                    f"§4.1.1's fraction lives on the campaign and a fraction "
                    "whose written value and stored value disagree is not a "
                    "fraction"
                )
        return fraction

    def load(self, campaign_id: Any) -> float | None:
        """One campaign's stored fraction, or ``None`` when it is not held.

        ``None`` means *the campaign was never planned* — the orchestrator has
        not created it — which is the honest answer for an id the table does
        not hold.  It does **not** mean the read failed: an unreachable
        database raises, so a caller can never mistake a broken store for an
        unplanned campaign.  The value returned is the campaign row's own
        ``null_fraction`` — the clipped ``clip(2/W, 0.15, 0.35)`` feature 117
        persisted — the number features 118 and 119 read to draw their nulls.
        """
        campaign = _validated_campaign_id(campaign_id)
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                f"SELECT {NULL_FRACTION_COLUMN} FROM {CAMPAIGN_TABLE} WHERE id = ?",
                (campaign,),
            )
            try:
                row = cursor.fetchone()
            finally:
                cursor.close()
        if row is None:
            return None
        return row[0]

    def _require_campaign(self, connection: sqlite3.Connection, campaign: str) -> None:
        """Refuse a campaign the table does not hold, by name.

        The fraction joins the campaign row — features 118 and 119 read it
        there, the guard's and the verdict's writes land there — so a fraction
        run against a campaign nobody planned is a caller bug worth learning
        before a number lands nowhere.  The check is a read, not a create: a
        store that inserted the missing campaign would be inventing the row the
        type and the workspace count belong on.  The planner creates the
        campaign, before any node is expanded; this store only fills its
        fraction.
        """
        cursor = connection.execute(
            f"SELECT 1 FROM {CAMPAIGN_TABLE} WHERE id = ?", (campaign,)
        )
        try:
            found = cursor.fetchone()
        finally:
            cursor.close()
        if found is None:
            raise KsGuardError(
                f"the campaign table holds no row for {campaign!r}; §4.1.1's "
                "fraction is fixed *per campaign*, so a fraction that cannot be "
                "joined to the campaign it was planned for is refused rather "
                "than written onto a row this store would have to invent — the "
                "campaign is created by its planner, before any node is "
                "expanded"
            )

    def _read_campaign_fraction(
        self, connection: sqlite3.Connection, campaign: str
    ) -> Any:
        """The campaign row's ``null_fraction``, read back inside the transaction.

        The number the store just wrote, read back rather than trusted,
        because the fraction features 118 and 119 will draw their nulls from
        is the stored one — and a fraction whose written value and stored
        value disagree is not a fraction the campaign was planned with.  A
        campaign that vanished between the write and the read-back is refused:
        the fraction must be accounted for, and a campaign that cannot be
        re-read is a campaign whose fraction is unverifiable.
        """
        cursor = connection.execute(
            f"SELECT {NULL_FRACTION_COLUMN} FROM {CAMPAIGN_TABLE} WHERE id = ?",
            (campaign,),
        )
        try:
            row = cursor.fetchone()
        finally:
            cursor.close()
        if row is None:
            raise KsGuardError(
                f"campaign {campaign!r} vanished between the fraction write and "
                "its read-back; the fraction must be accounted for, and a "
                "campaign that cannot be re-read is a campaign whose fraction "
                "is unverifiable"
            )
        return row[0]


def _validated_campaign_id(value: Any) -> str:
    """Validate a campaign id, returning it in canonical UUID text.

    Delegates to :func:`~nulloracle.assignment.normalize_node_id` — the one
    spelling this member has for *an id that joins the tree store's
    ``node.id``*, and ``campaign``'s ``id`` is the same kind of value — but
    re-raises its refusal as :class:`~nulloracle.errors.KsGuardError`.
    The distinction is the taxonomy's: a malformed id handed to the *fraction*
    store is a store-contract failure, not a sidecar-schema one, and a caller
    reading ``SidecarError`` out of a fraction write would look in the wrong
    module for the cause.  The guard's, the verdict's and this module's stores
    share the same id kind and the same error, so a campaign whose fraction is
    fixed, whose p-value is persisted and whose verdict is pronounced are
    validated identically.
    """
    try:
        return normalize_node_id(value)
    except Exception as exc:
        raise KsGuardError(
            f"campaign_id {value!r} is not a UUID: {exc}"
        ) from exc


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into a filesystem path.

    The SQLAlchemy convention the workspace's ``DATABASE_URL`` already uses,
    restated here rather than imported so each store states its own contract.
    A non-SQLite scheme is refused loudly — the Postgres store arrives with
    the migration member — and a pathless (in-memory) URL is refused too: an
    in-memory database dies with the connection that opened it, and a
    campaign's fraction must outlive the planning call that produced it.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise KsGuardError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: this "
            "store speaks sqlite:/// (the spec's single-machine allowance); "
            f"point {DATABASE_URL_ENV} at a sqlite database"
        )
    if parsed.netloc not in ("", "localhost"):
        raise KsGuardError(
            f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
            f"{parsed.netloc!r}"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path or path == ":memory:":
        raise KsGuardError(
            f"sqlite {DATABASE_URL_ENV} carries no database path: an "
            "in-memory database would die with the connection that opened "
            "it, and a campaign's fraction must outlive the planning call "
            "that fixed it"
        )
    return Path(path)


def persist_null_fraction(
    campaign_id: Any,
    workspace_count: Any,
    *,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> float:
    """Fix §4.1.1's fraction on ``campaign_id`` and persist it — the module-level spelling.

    Feature 117's sentence as one call: the workspace count in, the clipped
    fraction out, written against its campaign.  The store is resolved from
    ``database_url``, else from ``DATABASE_URL``; a deployment that names
    neither is refused *by name* rather than silently doing nothing, because
    a fraction that quietly skipped its write would leave a campaign looking
    unplanned while the planner believed it had fixed φ — which is the failure
    mode this whole feature exists to rule out.

    A :class:`~nulloracle.errors.KsGuardError` from the store is left to
    propagate unwrapped; see the taxonomy for why "the fraction could not be
    written down" is a store-contract failure and not a computation one.
    """
    source = os.environ if env is None else env
    url = database_url if database_url is not None else source.get(DATABASE_URL_ENV, "").strip()
    if not url:
        raise KsGuardError(
            f"persist_null_fraction fixes a campaign's planted-null fraction "
            f"and nothing names a store: {DATABASE_URL_ENV} is unset (and no "
            "database_url was supplied), so φ could not be written down. "
            "§4.1.1's fraction is a fact that must actually land on the "
            "campaign — a campaign whose fraction silently went nowhere would "
            "look unplanned while its planner believed it had fixed φ"
        )
    return PlantedNullFraction(url).persist(campaign_id, workspace_count)
