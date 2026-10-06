"""The bootstrap pool's fill CLI -- ``python -m bootstrap.fill``.

``additions_spec_operator_surfaces.xml``, "Middle Loop Operation" category,
feature 3: *System saves bootstrap worlds to the pool from* ``python -m
bootstrap.fill --count N --pool-seed S`` *(defaults 45 and 20260922), and
displays the pool's census as one JSON line.*  PRD M1.5 names the gap this
command closes: the library already builds and persists the pool (feature
188's :class:`~bootstrap.BootstrapPool`) and already counts it (feature
186's :func:`~bootstrap.world_census`), but nothing an operator can run
joins the two -- *"no command fills the bootstrap pool"*.  This module is
that join and nothing more: :meth:`~bootstrap.BootstrapPool.ensure_schema`,
then :meth:`~bootstrap.BootstrapPool.persist_worlds`, then
:func:`~bootstrap.world_census`, printed as one JSON line.

**Idempotence is the library's, inherited rather than reimplemented.**
:meth:`~bootstrap.BootstrapPool.persist_worlds`'s own upsert keeps a
world's first ``created_at`` and rewrites nothing else on a re-run with
the same ``pool_seed`` -- feature 188's "a re-run is a refresh, not a
re-draw".  So running this command twice with the same arguments writes no
new row, and the printed census is the same value both times.  This module
adds no idempotence of its own; it only must not stand in the way of the
library's.

**The one refusal this module adds: a ``pool_seed`` that disagrees with
what is already held.**  ``persist_worlds`` draws every world's id from
``(pool_seed, index)`` (:func:`~bootstrap.world_id_for`), so a *different*
``pool_seed`` does not collide with the held rows -- it draws a second,
differently-named batch and seats it beside the first, silently growing
the pool past the 40-50 band docs/nullius-tech-architecture.md §10.6
targets, with two draws under one roof.  That is a state no operator
asking "fill the pool" meant to reach, so this command reads the pool's
held authored worlds *before* drawing: if any exist and name a
``pool_seed`` other than the one asked for, it refuses -- naming both
seeds, writing nothing -- with the code word ``bootstrap_pool_populated``.
An empty pool has no held seed to disagree with, and a re-run naming the
same seed is the refresh feature 188 already made idempotent; neither is
refused.

**``--census`` skips the draw, not the schema.**  It still runs
``ensure_schema()`` (a lazy ``CREATE TABLE IF NOT EXISTS``, not a write of
any world) and it skips the pool-seed check above entirely -- there is
nothing to protect, because no draw is attempted -- then prints the same
shape of line a fill does, so a caller cannot tell from the output alone
whether a run drew worlds or only read what was already there.

**A database with no ``replay_score`` table reports zero financial
worlds, rather than refusing.**  :func:`~bootstrap.world_census` itself
treats an absent ``replay_score`` table as a refusal -- a deliberate
choice of feature 186's, because answering zero there could silently hide
an operator pointing the *dreaming* loop at the wrong database.  This
command's own job is narrower and comes first: an operator filling the
bootstrap pool, or only asking its census, has very often not yet run any
financial replay (or any other migration) against this database at all,
and a command whose own documented schema step is only
``ensure_schema()`` must not fail an empty, brand-new ``DATABASE_URL`` on
behalf of a table it never promised to create. So this module probes for
``replay_score`` itself before reading the census: the table exists, it
reads :func:`~bootstrap.world_census`'s real figure; it does not, the
financial figure is zero -- the measured state of a replay pool that is
not there yet, not a number invented to paper over a mistake. Once the
``replay_score`` table exists (migrated, whether or not it holds a row
yet), this module hands the read to :func:`~bootstrap.world_census`
unchanged, so the ordinary refusal vocabulary and the real financial
figure both apply from that point on.

**Exit codes**, the workspace's own convention (CLAUDE.md's five operator
verbs): 0 once the census is printed, whether this call drew anything or
only read it; 1 when a collaborator refuses -- the pool-seed conflict
above, or :meth:`~bootstrap.BootstrapPool.persist_worlds`'s own refusal of
a ``count`` outside ``[40, 50]``, or any other
:class:`~bootstrap.BootstrapError` -- printed verbatim, because every one
of those already opens with its own code word or names its own subject;
2 for a missing ``DATABASE_URL``, naming it.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections.abc import Callable, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass

import bootstrap

__all__ = [
    "EXIT_CONFIG",
    "EXIT_OK",
    "EXIT_REFUSED",
    "FILL_CODE",
    "POPULATED_CODE",
    "FillResult",
    "fill_pool",
    "main",
]

#: The greppable word this module's own configuration refusal opens with --
#: never a collaborator's, which already opens with its own (feature 188's
#: BootstrapPoolError text, or :data:`POPULATED_CODE` below).
FILL_CODE = "bootstrap_fill"

#: The code word feature 3's own sentence names: the pool already holds
#: authored worlds drawn from a ``pool_seed`` other than the one this run
#: asked for.
POPULATED_CODE = "bootstrap_pool_populated"

#: Done -- the census was printed, whether this call drew worlds or only read them.
EXIT_OK = 0
#: A collaborator refused: the pool-seed conflict, a bad ``count``, or any
#: other :class:`~bootstrap.BootstrapError`.
EXIT_REFUSED = 1
#: Missing configuration: no ``DATABASE_URL``.
EXIT_CONFIG = 2


@dataclass(frozen=True)
class FillResult:
    """The one JSON line this command prints -- the census, beside the seed it was taken against."""

    n_bootstrap: int
    n_financial: int
    total: int
    pool_seed: int

    def to_payload(self) -> dict[str, int]:
        """The result as the one JSON line this command prints, field order
        matching the feature's own sentence: ``n_bootstrap``, ``n_financial``,
        ``total``, ``pool_seed``."""
        return {
            "n_bootstrap": self.n_bootstrap,
            "n_financial": self.n_financial,
            "total": self.total,
            "pool_seed": self.pool_seed,
        }


def _has_replay_score_table(pool: bootstrap.BootstrapPool) -> bool:
    """Whether the pool's database holds a ``replay_score`` table yet.

    A plain ``sqlite_master`` probe -- never the rows -- so it is safe to
    ask before deciding which census read to make.  Spelled here rather
    than imported, the way every member in this workspace restates a probe
    over a table it only reads (:mod:`orchestrator.closeout`'s own
    ``_has_column`` is the same discipline for a column); the alternative
    would be reaching into :mod:`bootstrap._census`'s private helper for a
    question this module asks for its own, narrower reason.
    """
    with closing(sqlite3.connect(pool.path)) as connection:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (bootstrap.REPLAY_SCORE_TABLE,),
        ).fetchone()
    return row is not None


def _take_census(pool: bootstrap.BootstrapPool) -> bootstrap.WorldCensus:
    """The census this command prints -- tolerant of an unmigrated database.

    Reads :func:`~bootstrap.world_census` unchanged once ``replay_score``
    exists; before that, there is no replay pool to measure a financial
    figure from, and this command -- unlike feature 186's census -- must
    not refuse an operator who has only ever run ``ensure_schema()`` here.
    The zero it reports then is itself measured: a database that holds no
    ``replay_score`` table has recorded no financial replay, so zero is
    the honest count of what has not happened yet, not a guess standing in
    for one. ``n_bootstrap`` is always the pool's own
    :meth:`~bootstrap.BootstrapPool.world_count`, with or without the
    table, because the bootstrap half is this command's own table and
    never depends on another member's migration.
    """
    if _has_replay_score_table(pool):
        return bootstrap.world_census(pool)
    return bootstrap.WorldCensus(n_financial=0, n_bootstrap=pool.world_count())


def fill_pool(
    database_url: str,
    *,
    count: int = bootstrap.DEFAULT_POOL_SIZE,
    pool_seed: int = bootstrap.POOL_SEED,
    census_only: bool = False,
) -> FillResult:
    """Fill (or, with ``census_only``, just read) the pool at ``database_url``.

    Brings the database to the pool's shape
    (:meth:`~bootstrap.BootstrapPool.ensure_schema`), then -- unless
    ``census_only`` -- checks the pool's held authored worlds against
    ``pool_seed`` (see the module docstring) and, if they agree or there are
    none, draws (:meth:`~bootstrap.BootstrapPool.persist_worlds`).  Either
    way, it finishes by taking the census (:func:`_take_census`) and
    returns it paired with ``pool_seed``.

    Raises :class:`~bootstrap.BootstrapPoolError` -- unchanged, with the
    code word :data:`POPULATED_CODE` -- when the pool already holds
    authored worlds drawn from a different ``pool_seed``; propagates
    :meth:`~bootstrap.BootstrapPool.persist_worlds`'s own refusal of a
    ``count`` outside ``[40, 50]`` or of a seed collision unchanged, and
    (once ``replay_score`` exists) :func:`~bootstrap.world_census`'s own
    refusals unchanged.
    """
    pool = bootstrap.BootstrapPool(database_url)
    pool.ensure_schema()

    if not census_only:
        held_seeds = {record.pool_seed for record in pool.worlds()}
        if held_seeds and held_seeds != {pool_seed}:
            held = ", ".join(str(seed) for seed in sorted(held_seeds))
            raise bootstrap.BootstrapPoolError(
                f"{POPULATED_CODE}: the replay pool already holds authored "
                f"worlds drawn from pool_seed {held} -- asked to fill from "
                f"pool_seed {pool_seed!r} instead; persist_worlds draws "
                "every world's id from (pool_seed, index), so a different "
                "pool_seed would not refresh the held worlds, it would seat "
                "a second generation beside them -- growing the pool past "
                "the 40-50 band docs/nullius-tech-architecture.md §10.6 "
                "targets, with two draws under one roof.  Point "
                "--pool-seed at the seed already held, or fill a fresh "
                "database"
            )
        pool.persist_worlds(count, pool_seed=pool_seed)

    census = _take_census(pool)
    return FillResult(
        n_bootstrap=census.n_bootstrap,
        n_financial=census.n_financial,
        total=census.total,
        pool_seed=pool_seed,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m bootstrap.fill",
        description=(
            "Persist generated bootstrap worlds into the replay pool, and "
            "print the pool's census -- n_bootstrap, n_financial, total "
            "and pool_seed -- as one JSON line."
        ),
    )
    parser.add_argument(
        "--count",
        type=int,
        default=bootstrap.DEFAULT_POOL_SIZE,
        metavar="N",
        help=(
            f"worlds to persist, {bootstrap.MIN_POOL_SIZE}-"
            f"{bootstrap.MAX_POOL_SIZE} (default {bootstrap.DEFAULT_POOL_SIZE})"
        ),
    )
    parser.add_argument(
        "--pool-seed",
        dest="pool_seed",
        type=int,
        default=bootstrap.POOL_SEED,
        metavar="S",
        help=f"the draw's seed (default {bootstrap.POOL_SEED})",
    )
    parser.add_argument(
        "--census",
        action="store_true",
        help="print the pool's census without persisting any worlds",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    emit: Callable[[str], object] = print,
) -> int:
    """``python -m bootstrap.fill [--count N] [--pool-seed S] [--census]``.

    Reads ``DATABASE_URL`` from ``env`` (the process environment when
    ``None``) -- a missing or blank value exits :data:`EXIT_CONFIG`, naming
    the variable, before anything is read or written.  Otherwise runs
    :func:`fill_pool` and prints its one JSON line through ``emit``.  A
    refusal :func:`fill_pool` raises is printed to stderr verbatim (it
    already opens with its own code word) and answered :data:`EXIT_REFUSED`;
    nothing is written in that case.

    ``env`` and ``emit`` are this command's seams, taken exactly as the
    other operator CLIs in this workspace take them (see
    ``orchestrator.closeout``): ``env`` is where ``DATABASE_URL`` is read
    from, and ``emit`` is what the one JSON line is printed with -- so the
    suite drives this command in-process, with no subprocess and no real
    environment.
    """
    parser = _build_parser()
    arguments = parser.parse_args(argv)
    source = os.environ if env is None else env

    database_url = source.get(bootstrap.DATABASE_URL_ENV, "").strip()
    if not database_url:
        print(
            f"{FILL_CODE}: {bootstrap.DATABASE_URL_ENV} must name the "
            "database the replay pool persists into",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    try:
        result = fill_pool(
            database_url,
            count=arguments.count,
            pool_seed=arguments.pool_seed,
            census_only=arguments.census,
        )
    except bootstrap.BootstrapError as refusal:
        print(str(refusal), file=sys.stderr)
        return EXIT_REFUSED

    emit(json.dumps(result.to_payload()))
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - the module's own door
    raise SystemExit(main())
