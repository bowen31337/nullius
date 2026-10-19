"""The campaign-grid backfill — ``python -m orchestrator.backfill_campaign_grid``.

additions_spec_engine_edge_recovery.xml, "Campaign Grid", feature 4, third
step: *"python -m orchestrator.backfill_campaign_grid [--dry-run]: for every
campaign row whose ``horizon`` is NULL, read one of its nodes'
``ic_series.parquet`` dates from the artifact dir; ``grid_first``/``grid_last``
are their min and max; horizon follows the grid: 183 or 235 weekly dates -> 5,
92 biweekly dates -> 10, 92 daily dates -> 1 (the three grids the configs in
use define; a campaign matching none is reported and left NULL);
``evaluation_config_sha256`` and ``oos_first_date`` stay NULL for backfilled
rows. Prints one JSON line per campaign and a summary; ``--dry-run`` writes
nothing. It is idempotent."*

**Why the artifacts, and not the campaign row.**  The grid is not on the row
for any campaign planned before ``0120_campaign_evaluation_grid.py`` ran —
that absence is the defect the diagnosis named, and the row cannot be asked
what it does not hold.  What a campaign's *nodes* do hold is their measured
``ic_series.parquet``: a date-keyed series written by the evaluation that
scored the node, whose keys are exactly the dates the grid ran on (the spec's
own words: *"the grid a campaign ran on is readable from any of its nodes'
ic_series dates"*, and the shape ``~/.local/share/nullius/artifacts/
<campaign>/<node>/ic_series.parquet`` it names).  So the grid is *read back*
off the artifact the run already published, never inferred from a config file
that may since have been edited — the difference between a record and a
reconstruction.

**Horizon follows the grid, and only for the three grids in use.**  The
horizon is not in the artifact (the series is keyed by rebalance date, not by
forward window), so it is recovered from the grid's *shape* — how many dates
there are and how they are spaced — which is what the spec's three cases
encode, each one a grid the configurations in use actually define:

===========================  ===========  ==========
dates on the grid            spacing      horizon
===========================  ===========  ==========
183 or 235                   7 days       5
92                           14 days      10
92                           1 day        1
===========================  ===========  ==========

Note the third column of rows two and three: 92 dates is ambiguous on count
alone and is disambiguated by the spacing between adjacent dates, which is why
:func:`_grid_shape` reads the dates rather than only counting them.  **A
campaign matching none of the three is reported and left NULL** — with a
``"reason"`` naming the count and spacing it did have, so an operator reading
the line learns *what* was found rather than only that nothing matched.  This
module deliberately does not guess: a horizon is the window a pick was
selected for, and a plausible-looking wrong horizon is worse than a NULL,
because ``m3_verdict``'s admission reads these columns to decide what may be
scored.

**A campaign whose artifacts cannot be read is reported, not skipped in
silence.**  Three cases, each its own reason on the line: no artifact
directory for the campaign at all (``no_artifact_node``), a node directory
with no readable series (``no_ic_series``), and a series this module's own
codec refuses (``unreadable_ic_series``).  Every one leaves the row's columns
exactly as they were.  A campaign with *no rows to fill* — one whose horizon
is already recorded — is not reported at all: it is not work this command has
anything to say about, and reporting thousands of already-filled rows would
bury the handful the command actually acted on.

**Idempotent, and ``--dry-run`` writes nothing.**  Idempotence does not come
from a marker: it comes from the selection rule.  The command selects rows
whose ``horizon`` *is NULL*, so a row this command filled is not selected on
the next run — the second run reports nothing and changes nothing, which is
also what ``--dry-run`` does while still reporting what it *would* have
written (each line carrying ``"dry_run": true``, so a reader of the output
can never mistake a rehearsal for a write).

**What is deliberately left NULL.**  ``evaluation_config_sha256`` and
``oos_first_date`` are, for every backfilled row.  Neither is recoverable
from an artifact: the digest names a *file* the run read, which may since
have been edited or deleted, and the out-of-sample first date is a property
of the configuration, not of anything the evaluation persisted.  Writing
``NULL`` there is the honest record — the same reading
``0120_campaign_evaluation_grid.py`` states for the five columns — and it is
what lets a later reader tell a backfilled row (grid known, configuration
unknown) from a driver-written one (both known).

**A missing ``DATABASE_URL`` or an unreadable store is refused by name.**  A
backfill that quietly did nothing would look exactly like a backfill with no
work to do, which is the one confusion this command exists to prevent, so the
configuration refusals exit :data:`EXIT_CONFIG` with the variable named and
nothing else on stdout.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
from collections.abc import Callable, Mapping, Sequence
from contextlib import closing
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from artifacts import ArtifactStore, ic_series, ic_series_is_persisted

__all__ = [
    "ARTIFACT_ROOT_ENV",
    "BACKFILL_CODE",
    "DATABASE_URL_ENV",
    "EXIT_CONFIG",
    "EXIT_OK",
    "EXIT_REFUSED",
    "GRID_COLUMNS_BACKFILLED",
    "GRID_FIRST_DATE_COLUMN",
    "GRID_LAST_DATE_COLUMN",
    "HORIZON_COLUMN",
    "KNOWN_GRIDS",
    "REASON_NO_ARTIFACT_NODE",
    "REASON_NO_IC_SERIES",
    "REASON_UNKNOWN_GRID",
    "REASON_UNREADABLE_IC_SERIES",
    "backfill",
    "grid_shape",
    "horizon_for_grid",
    "main",
]

#: The greppable code word every refusal this command prints itself opens
#: with.  Collaborators' own refusals (the artifact store's, sqlite's) are
#: printed verbatim, since each already carries its own vocabulary.
BACKFILL_CODE = "backfill_campaign_grid"

#: The environment variable naming the relational store — the workspace-wide
#: spelling, restated rather than imported for the reason every other CLI in
#: this member restates it: this module states its own contract.
DATABASE_URL_ENV = "DATABASE_URL"

#: The environment variable naming the artifact root, read through
#: :meth:`artifacts.ArtifactStore.from_env` so a deployment that sets it and
#: one that relies on the workspace default are served identically.  Named
#: here as well because the refusal for an unresolvable root is this
#: command's own line.
ARTIFACT_ROOT_ENV = "ARTIFACT_ROOT"

#: The three exits this command has.  ``EXIT_REFUSED`` is reserved for a
#: store or a database that could not be read at all — a *campaign* this
#: command cannot place is a reported line, never a failure exit, because the
#: spec's own behaviour for an unknown grid is "reported and left NULL" and a
#: run that processed fifty campaigns and reported three has succeeded.
EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_CONFIG = 2

#: The campaign row's three grid columns this command writes.  Only these
#: three: ``evaluation_config_sha256`` and ``oos_first_date`` stay NULL for
#: every backfilled row (see the module docstring).
HORIZON_COLUMN = "horizon"
GRID_FIRST_DATE_COLUMN = "grid_first_date"
GRID_LAST_DATE_COLUMN = "grid_last_date"

#: Those three, as one tuple — the columns this command's authority covers,
#: and what a reader (or a test) iterates rather than restating.  Named so
#: the *other* two of the five can be referred to by their absence:
#: ``evaluation_config_sha256`` and ``oos_first_date`` are never written
#: here.
GRID_COLUMNS_BACKFILLED: tuple[str, ...] = (
    HORIZON_COLUMN,
    GRID_FIRST_DATE_COLUMN,
    GRID_LAST_DATE_COLUMN,
)

#: The table this command reads campaigns from and updates — feature 104's,
#: created by ``migrations/versions/0111_campaign_table.py``.
CAMPAIGN_TABLE = "campaign"

#: Why a campaign's line says its columns were left alone.  Each is a
#: distinct fact an operator acts on differently, which is why they are three
#: strings rather than one: ``no_artifact_node`` means the artifacts are
#: somewhere else (a wrong root, a swept directory), ``no_ic_series`` means
#: the node directory exists but carries no series (a run that failed before
#: metrics), ``unreadable_ic_series`` means the file is there and this
#: module's decoder refuses it (corruption, or a file this system did not
#: write), and ``unknown_grid`` means the artifacts are fine and the grid is
#: simply not one of the three in use.
REASON_NO_ARTIFACT_NODE = "no_artifact_node"
REASON_NO_IC_SERIES = "no_ic_series"
REASON_UNREADABLE_IC_SERIES = "unreadable_ic_series"
REASON_UNKNOWN_GRID = "unknown_grid"

#: The three grids the configurations in use define, as
#: ``(horizon, frozenset of (date_count, spacing_days) shapes)``.  The
#: counting rule is the spec's own table; the spacing is what separates the
#: two 92-date grids, which are indistinguishable by count alone.
#:
#: * horizon 5 over a *weekly* grid — 183 dates (three years) or 235 (the
#:   five-year configs) at 7-day spacing;
#: * horizon 10 over a *biweekly* grid — 92 dates at 14-day spacing;
#: * horizon 1 over a *daily* grid — 92 dates at 1-day spacing.
KNOWN_GRIDS: tuple[tuple[int, frozenset[tuple[int, int]]], ...] = (
    (5, frozenset({(183, 7), (235, 7)})),
    (10, frozenset({(92, 14)})),
    (1, frozenset({(92, 1)})),
)


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into the filesystem path it names.

    The workspace's own translation, restated in this module for the reason
    every store restates it: a command that owns no schema still owns its
    refusals.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise _BackfillError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: this "
            "command speaks sqlite:///, the store the campaign table lives "
            "in on a single machine"
        )
    if parsed.netloc not in ("", "localhost"):
        raise _BackfillError(
            f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
            f"{parsed.netloc!r}"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path or path == ":memory:":
        raise _BackfillError(
            f"sqlite {DATABASE_URL_ENV} carries no database path"
        )
    return Path(path)


class _BackfillError(Exception):
    """A store or database fact that stops the whole run.

    Distinct from a per-campaign finding: a campaign this command cannot
    place is a *line*, and this exception is for the cases where no line
    could be produced at all — an unreadable database, a URL this command
    cannot speak.  Kept private because nothing outside this module
    constructs one.
    """


# -- The grid, read back off the artifact ---------------------------------------


def grid_shape(dates: Sequence[Any]) -> tuple[int, int] | None:
    """``(date count, spacing in days)`` for ``dates``, or ``None``.

    The two numbers :data:`KNOWN_GRIDS` is keyed by, as one value.  ``None``
    for a series with fewer than two dates: a single date has no spacing, and
    a grid of one date is not one of the three in use — *unknown*, reported
    and left NULL, rather than a horizon guessed off one observation.

    The spacing is the **difference between the first two dates** rather than
    a mode or an average over all adjacent pairs.  That is a deliberate
    choice, and it is the right one here: the three grids in use are exactly
    uniform, so the first gap is the spacing of the whole grid, and reading
    it from one pair rather than from a statistic means a series with a
    *single* irregularity somewhere in the middle is still recognised by its
    own leading shape instead of being averaged into a non-integer that
    matches nothing.  A grid that is irregular from the start answers a
    spacing no known grid carries and is reported as unknown, which is the
    correct outcome — an irregular grid is not one of the three.

    Dates may be :class:`datetime.date` objects (what
    :func:`artifacts.ic_series` answers) or ISO-8601 strings (what a hand-
    built fixture may carry); anything else answers ``None`` rather than
    being coerced.
    """
    calendar = [_as_date(value) for value in dates]
    if any(value is None for value in calendar):
        return None
    ordered = sorted(value for value in calendar if value is not None)
    if len(ordered) < 2:
        return None
    return len(ordered), (ordered[1] - ordered[0]).days


def _as_date(value: Any) -> Any:
    """One date from ``dt.date`` or ISO text, or ``None``."""
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return dt.date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


def _as_text(value: Any) -> str:
    """One grid date as the ISO text the campaign row stores.

    A :class:`datetime.date` from the real store renders through
    ``isoformat``; a string a fixture supplied is normalized through
    :func:`_as_date` first, so a row can never be written with a spelling
    the column's own readers would compare wrongly (see
    ``discovery.campaign._validated_grid_date``, which would refuse it).
    Raises for a value that is neither — but the caller only reaches this
    with a non-empty date list :func:`grid_shape` already validated, so that
    arm is unreachable rather than defended twice.
    """
    calendar = _as_date(value)
    if calendar is None:
        raise _BackfillError(
            f"a grid date {value!r} is neither a date nor ISO-8601 text, so "
            "the campaign row could not be written with it"
        )
    return calendar.isoformat()


def horizon_for_grid(shape: tuple[int, int] | None) -> int | None:
    """The horizon the spec's table assigns to ``shape``, or ``None``.

    ``None`` is the honest answer for a grid that matches none of the three
    — the spec's own *"a campaign matching none is reported and left NULL"*.
    """
    if shape is None:
        return None
    for horizon, shapes in KNOWN_GRIDS:
        if shape in shapes:
            return horizon
    return None


def _node_dates(
    store: ArtifactStore, campaign_id: str, node_ids: Sequence[str]
) -> tuple[list[Any], str | None]:
    """One readable series' dates for this campaign, and why there is none.

    Walks the campaign's node directories in the store's own sorted order and
    answers the **first** node whose series can be read — the spec's *"read
    one of its nodes' ``ic_series.parquet``"*, taken literally: every node of
    a campaign was scored on the same grid (the grid is the campaign's, which
    is the whole premise of the feature), so one node is enough and reading
    them all would be work with no possible effect on the answer.

    The three failure reasons are distinguished rather than collapsed, for
    the reason :data:`REASON_NO_ARTIFACT_NODE` documents.  A node whose
    directory holds no series does **not** stop the walk: a campaign whose
    first node failed its evaluation but whose second published one has a
    perfectly good grid to read, and refusing to look would report a
    readable campaign as unplaceable.
    """
    if not node_ids:
        return [], REASON_NO_ARTIFACT_NODE
    saw_a_file = False
    for node_id in node_ids:
        try:
            if ic_series_is_persisted(store, campaign_id, node_id):
                saw_a_file = True
                return sorted(ic_series(store, campaign_id, node_id)), None
        except Exception:  # noqa: BLE001, S112 - one node's fault, not the run's
            # A node directory that cannot even be probed (a permission
            # error, a symlink out of the store) must not abort the
            # campaign's line: the next node may answer, and if none does
            # the reason below says so.  Broad deliberately — the exception
            # vocabulary across the artifact seam is not enumerable.
            continue
    return [], (
        REASON_UNREADABLE_IC_SERIES if saw_a_file else REASON_NO_IC_SERIES
    )


# -- The database ---------------------------------------------------------------


def _read_pending_campaigns(connection: sqlite3.Connection) -> list[str]:
    """Every campaign row whose ``horizon`` is NULL, sorted by id.

    Sorted so two runs over the same store print their lines in the same
    order — the property that makes a backfill's output diffable against the
    previous run's, which is how an operator checks that nothing changed.

    ``horizon IS NULL`` is the selection rule, and it is also what makes the
    command idempotent (see the module docstring).  A row whose ``horizon``
    is set — by the driver, or by an earlier run of this command — is not
    selected, and therefore never rewritten: nothing here updates a campaign
    that already carries a grid.
    """
    cursor = connection.execute(
        f"SELECT id FROM {CAMPAIGN_TABLE} "
        f"WHERE {HORIZON_COLUMN} IS NULL ORDER BY id"
    )
    try:
        return [str(row[0]) for row in cursor.fetchall()]
    finally:
        cursor.close()


def _write_grid(
    connection: sqlite3.Connection,
    campaign_id: str,
    *,
    grid_first: str,
    grid_last: str,
    horizon: int,
) -> None:
    """Write one campaign's three backfilled columns.

    Three columns, one statement, one row.  ``evaluation_config_sha256`` and
    ``oos_first_date`` are not touched — not set to NULL, simply absent from
    the statement — so a row that somehow already carries either keeps it.
    That cannot happen through this command (it only selects rows whose
    ``horizon`` is NULL, and a driver-written row always has one), but the
    statement states it anyway: this command's authority is the three
    columns the artifacts can answer for.
    """
    connection.execute(
        f"UPDATE {CAMPAIGN_TABLE} SET {HORIZON_COLUMN} = ?, "
        f"{GRID_FIRST_DATE_COLUMN} = ?, {GRID_LAST_DATE_COLUMN} = ? "
        "WHERE id = ?",
        (horizon, grid_first, grid_last, campaign_id),
    )


# -- The command ----------------------------------------------------------------


def backfill(
    database_url: str,
    *,
    artifact_store: ArtifactStore,
    dry_run: bool = False,
    emit: Callable[[str], object] = print,
) -> int:
    """Fill every unplaced campaign's grid; one JSON line per campaign.

    The whole command as one call, so :func:`main` is only argument parsing
    and the environment, and so this behaviour can be driven directly by a
    test with a store of its own.

    Every selected campaign produces exactly one line — either a ``filled``
    line (the three values that landed, or ``dry_run: true`` with the values
    that would have) or a ``left_null`` line carrying a ``reason``.  The
    final ``summary`` line counts both, plus the campaigns seen, so a reader
    can tell *this run had no work* (``seen: 0``) from *this run could not
    place anything* (``seen: n, failed: n``) — a distinction the individual
    lines carry but a handicapped reader of the last line alone would miss.

    Writes are one transaction for the whole run: a store that fails partway
    through leaves every row exactly as it found it rather than a campaign
    half-updated, which matters because the row's three columns describe one
    grid and must land together.
    """
    path = _sqlite_path(database_url)
    if not path.exists():
        raise _BackfillError(
            f"{DATABASE_URL_ENV} names {path}, which does not exist; this "
            "command backfills campaigns out of a store that is already "
            "there"
        )
    filled = 0
    failed = 0
    with closing(sqlite3.connect(path)) as connection:
        try:
            pending = _read_pending_campaigns(connection)
        except sqlite3.Error as exc:
            raise _BackfillError(
                f"this database holds no readable {CAMPAIGN_TABLE} table "
                f"({exc}): the campaign row is created by "
                "migrations/versions/0111_campaign_table.py and the grid "
                "columns by 0120_campaign_evaluation_grid.py, so a store "
                f"the chain has not reached has nothing to backfill from "
                f"(and the grid columns it lacks are why this command exists "
                "at all)"
            ) from exc

        with connection:  # one transaction for every write below
            for campaign_id in pending:
                line = _campaign_line(
                    connection,
                    campaign_id,
                    artifact_store=artifact_store,
                    dry_run=dry_run,
                )
                if line["status"] == "filled":
                    filled += 1
                else:
                    failed += 1
                emit(json.dumps(line))

    emit(
        json.dumps(
            {
                "event": "summary",
                "seen": len(pending),
                "filled": filled,
                "left_null": failed,
                "dry_run": dry_run,
            }
        )
    )
    return EXIT_OK


def _campaign_line(
    connection: sqlite3.Connection,
    campaign_id: str,
    *,
    artifact_store: ArtifactStore,
    dry_run: bool,
) -> dict[str, Any]:
    """One campaign's report line, writing its grid unless ``dry_run``.

    The line is the same shape either way — ``status``, the id, and the
    values or the reason — with ``dry_run`` distinguishing the two, so a
    reader that diffs a rehearsal against the real run compares like with
    like.
    """
    node_ids = artifact_store.node_ids(campaign_id)
    dates, missing = _node_dates(artifact_store, campaign_id, node_ids)
    shape = grid_shape(dates)
    horizon = horizon_for_grid(shape)
    if horizon is None:
        return {
            "event": "campaign",
            "status": "left_null",
            "campaign_id": campaign_id,
            "reason": missing or REASON_UNKNOWN_GRID,
            "dates": len(dates),
            "spacing_days": None if shape is None else shape[1],
            "dry_run": dry_run,
        }
    # ``dates`` answers sorted (see :func:`_node_dates`), so the two ends are
    # its first and last entries; rendered through ``_as_text`` because a
    # hand-built fixture may carry ISO strings where the real store carries
    # ``dt.date`` objects.
    grid_first = _as_text(dates[0])
    grid_last = _as_text(dates[-1])
    if not dry_run:
        _write_grid(
            connection,
            campaign_id,
            grid_first=str(grid_first),
            grid_last=str(grid_last),
            horizon=horizon,
        )
    return {
        "event": "campaign",
        "status": "filled",
        "campaign_id": campaign_id,
        "horizon": horizon,
        "grid_first_date": str(grid_first),
        "grid_last_date": str(grid_last),
        "dates": len(dates),
        "dry_run": dry_run,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m orchestrator.backfill_campaign_grid",
        description=(
            "Backfill the evaluation grid on campaigns that have none: read "
            "the dates off one of each campaign's stored ic_series.parquet "
            "files and write horizon, grid_first_date and grid_last_date. "
            "Prints one JSON line per campaign and a summary line."
        ),
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="report what would be written and write nothing",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    artifact_store: ArtifactStore | None = None,
    emit: Callable[[str], object] = print,
) -> int:
    """``python -m orchestrator.backfill_campaign_grid [--dry-run]``.

    Reads ``DATABASE_URL`` and ``ARTIFACT_ROOT`` from ``env`` (the process
    environment when ``None``), resolves the artifact store, and runs
    :func:`backfill`, printing its lines through ``emit``.

    A missing ``DATABASE_URL`` exits :data:`EXIT_CONFIG` naming the variable
    and printing nothing on stdout — *a backfill with nothing to do* and *a
    backfill that could not run* must never look alike.  A database or
    artifact root that cannot be read at all exits :data:`EXIT_REFUSED` with
    the reason on stderr, verbatim: every refusal below already names what
    it is about.

    ``artifact_store`` is injected rather than resolved when a caller
    supplies one — the seam a test uses to point the command at a store it
    built, and the same stance every other operator CLI in this member takes
    toward its collaborators.
    """
    parser = _build_parser()
    arguments = parser.parse_args(argv)
    source = os.environ if env is None else env

    database_url = source.get(DATABASE_URL_ENV, "").strip()
    if not database_url:
        print(
            f"{BACKFILL_CODE}: {DATABASE_URL_ENV} must name the research "
            "database holding the campaigns to backfill",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    if artifact_store is None:
        try:
            artifact_store = ArtifactStore.from_env(source)
        except Exception as exc:  # noqa: BLE001 - the store's own refusal
            print(str(exc), file=sys.stderr)
            return EXIT_REFUSED

    try:
        return backfill(
            database_url,
            artifact_store=artifact_store,
            dry_run=arguments.dry_run,
            emit=emit,
        )
    except _BackfillError as exc:
        print(f"{BACKFILL_CODE}: {exc}", file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":  # pragma: no cover - the module's own door
    raise SystemExit(main())
