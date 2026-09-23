"""What this member knows about the replay pool, stated once, with provenance.

Feature 270's subject is the *pool*, and the pool is not this member's: the
``replay_score`` table belongs to migration ``0109``
(``migrations/versions/0109_replay_score_and_policy_revision.py``), the
``bootstrap_world`` table belongs to feature 188 and was widened in place by
feature 191, and the campaign and node schemas above them belong to features
232-244.  This member holds the pool and refuses to let it move; it never
authors it.  So it needs the *names* of the pool's tables — a trigger cannot be
written over a table whose name is not known — and nothing else.

**The names are restated here, not imported.**  The workspace forbids one
member importing another: a member that imported ``bootstrap._pool`` for a
table name would couple a database's history to a package's import graph, and
the coupling would be invisible at the one place it matters — a deployment that
installed one member and not the other.  So this module is the same shape
:mod:`tripwires.layout` and :mod:`tripwires.excise` take for the identical
problem: the restatement sits in one module, the module says where each name
came from, and a test in this member's suite pins the spelling against the
owner so the restatement cannot drift from the thing it restates.

**The stand-in DDL is for standing a pool up, never for owning one.**  A
trigger can only be created over a table that exists, so this member's own
suite needs a pool to install its guards on, and it needs one without dragging
in a sibling member's package or running the shared migration chain.
:func:`pool_bootstrap_schema` answers exactly that: the *pool's* two tables, in
the shape their owners declare, with the columns reduced to what this member
reads — a key per row and, for the score table, the ``world_id`` the commitment
joins on.  It is deliberately **not** run by :mod:`dreaming.cycle`: a member
that created the pool's tables would be legislating a schema three features
short of it, which is the stance :mod:`tripwires.excise` states for its own
``0109`` bootstrap.  What the member itself creates is ``pool_freeze`` and
nothing else.
"""

from __future__ import annotations

__all__ = [
    "DATABASE_URL_ENV",
    "POOL_SCHEMA_BY_TABLE",
    "POOL_TABLES",
    "REPLAY_SCORE_COLUMNS",
    "REPLAY_SCORE_TABLE",
    "WORLD_COLUMNS",
    "WORLD_TABLE",
    "pool_bootstrap_schema",
    "pool_tables_present",
]

#: The environment variable naming the database the replay pool lives in.
#: Restated from the one spelling every relational store in this workspace
#: reads — the poison store, the nulloracle's stores, the bootstrap pool and
#: the replay pool's own seat all resolve ``DATABASE_URL`` — so the freeze
#: holds the pool in the database ``replay_score`` already lives in rather than
#: growing a second variable a deployment could point at a different file.  Two
#: variables would make "the pool is held" and "the pool is read" facts about
#: two different databases, and nothing in either would look wrong.
DATABASE_URL_ENV = "DATABASE_URL"

#: The pool's score table.  Provenance: migration ``0109``, whose docstring
#: names it *"the replay pool's evidence"*; app_spec.xml's §C5 vocabulary for
#: it is *"evaluate each [candidate] on every stored tree"*, and
#: docs/alpha-engine-prd.md §12.1 calls this table the thing the dreaming loop
#: *"overfits its own replay pool"* over.
REPLAY_SCORE_TABLE = "replay_score"

#: The pool's world table.  Provenance: feature 188 (``bootstrap._pool``)
#: authors it as ``bootstrap_world``; feature 191 widened it in place with the
#: ported half (a nullable ``seed`` and an either-or ``CHECK``).  §C5's *"every
#: stored world"* is this table's rows plus the replay pool's financial half,
#: and §10.3.1's *"every candidate revision against every stored world"* reads
#: its ids as the worlds a tournament is held over.
WORLD_TABLE = "bootstrap_world"

#: The two tables a hold covers, in the order the guards are created.  A tuple
#: rather than a set because :func:`dreaming.cycle.cycle_freeze_schema`'s
#: output is read by an operator and pinned by a test, and a stable ordering is
#: what makes two schema reads comparable — the ordering rule every store in
#: this workspace restates for its own reads.
POOL_TABLES = (REPLAY_SCORE_TABLE, WORLD_TABLE)

#: ``replay_score``'s columns, in declaration order, restated from ``0109``.
#:
#: The member reads exactly two of these: ``id``, which the commitment hashes,
#: and ``world_id``, which is the world the score is about.  The other six are
#: carried anyway, and the whole row is carried rather than just the two names,
#: because a restatement that listed only the columns this feature happens to
#: read would be a restatement nobody could check against its owner without
#: opening the migration — the point of the list is that its *shape* is
#: recognisable as the owner's.  A column added to ``0109`` and not here is a
#: fact this member's suite reports.
REPLAY_SCORE_COLUMNS = (
    "id",
    "policy_version",
    "world_id",
    "beta",
    "score",
    "committed_pick",
    "is_holdout",
    "created_at",
)

#: ``bootstrap_world``'s columns as features 188/191 declare them.  The
#: nullable ``seed`` and the either-or ``CHECK`` are feature 191's widening —
#: *an authored world has a seed, a ported world has a provenance and no seed*
#: — and the whole row is listed for the reason
#: :data:`REPLAY_SCORE_COLUMNS`'s comment gives.  This member reads ``world_id``
#: and nothing else, which is the honest scope for it: a hold is about *which
#: worlds* are in the pool, never about what is in them.
WORLD_COLUMNS = (
    "world_id",
    "seed",
    "label",
    "provenance",
    "created_at",
)

#: The score table's stand-in body: the owner's column names **and its declared
#: affinities and nullability**, which is stricter than a stand-in has to be and
#: deliberately so.
#:
#: ``id`` is ``TEXT`` rather than ``0109``'s ``UUID`` — SQLite has no ``UUID``
#: affinity, and the commitment reads the key as text either way — and
#: ``created_at`` is ``TEXT`` rather than ``TIMESTAMPTZ``, for the reason
#: :data:`tripwires.layout.replay_pool_bootstrap_schema` leaves the migration's
#: ``DEFAULT`` clause off: SQLite's ``DEFAULT`` grammar accepts a function call
#: only parenthesised, and a column this member never writes needs no default.
#: Everything else is the owner's own word: ``policy_version`` and ``world_id``
#: ``NOT NULL``, ``beta`` and ``score`` ``REAL``, ``committed_pick`` nullable
#: (``0109`` declares it so, and says why — a candidate scored but not
#: committed), ``is_holdout`` ``BOOLEAN NOT NULL``.
#:
#: **The types are carried because a looser stand-in makes tests pass for the
#: wrong reason.**  A ``TEXT`` ``score`` would let a test that asserts a written
#: score compares equal to a float fail with a type error, and a nullable
#: ``policy_version`` would let a write that *should* trip the schema's own
#: ``NOT NULL`` succeed — which is the failure mode this member's guard
#: translation is specifically written not to hide.  A stand-in whose job
#: includes exercising those paths has to be able to fail the way the owner
#: does.
_SCORE_TABLE_BODY = """
(
    id             TEXT    NOT NULL PRIMARY KEY,
    policy_version TEXT    NOT NULL,
    world_id       TEXT    NOT NULL,
    beta           REAL    NOT NULL,
    score          REAL    NOT NULL,
    committed_pick TEXT,
    is_holdout     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at     TEXT    NOT NULL
)
"""

#: The world table's stand-in body, on the same terms: the owner's names and
#: the nullability features 188/191 declare — ``world_id`` the primary key, a
#: ``seed`` that is nullable because a *ported* world has none (feature 191's
#: widening), and a ``provenance`` that is nullable because an *authored* world
#: has none.  The either-or ``CHECK`` between them is deliberately **not**
#: restated; see :func:`pool_bootstrap_schema`.
_WORLD_TABLE_BODY = """
(
    world_id   TEXT NOT NULL PRIMARY KEY,
    seed       INTEGER,
    label      TEXT,
    provenance TEXT,
    created_at TEXT
)
"""

#: The stand-in DDL per pool table, in :data:`POOL_TABLES` order.  A mapping
#: rather than two constants because :func:`pool_bootstrap_schema` and its
#: readers walk the pool's tables by name, and a table added to
#: :data:`POOL_TABLES` without a body here fails loudly at the lookup rather
#: than silently producing no DDL for it.
POOL_SCHEMA_BY_TABLE = {
    REPLAY_SCORE_TABLE: f"""
-- The replay pool's evidence, restated from migration 0109.  A stand-in for
-- this member's own suite to install its guards over: the member itself never
-- creates this table.
CREATE TABLE IF NOT EXISTS {REPLAY_SCORE_TABLE} {_SCORE_TABLE_BODY};
""",
    WORLD_TABLE: f"""
-- The pool's world table, restated from feature 188 as feature 191 widened it.
-- A stand-in, on the same terms as the score table above.
CREATE TABLE IF NOT EXISTS {WORLD_TABLE} {_WORLD_TABLE_BODY};
""",
}


def pool_bootstrap_schema(dialect: str = "sqlite") -> str:
    """The pool's two tables, as text, for standing a pool up.

    The DDL this member's suite runs to have a pool to hold; **not** what the
    member runs.  :func:`dreaming.cycle.cycle_freeze_schema` creates
    ``pool_freeze`` and the guards over these tables, and creates neither of
    the tables themselves — a member that authored the pool's schema would be
    legislating a schema three features short of it, the stance
    :mod:`tripwires.excise` states for its own ``0109`` bootstrap.

    ``dialect`` is accepted and checked, following
    :func:`tripwires.layout.replay_pool_bootstrap_schema` and for the same
    reason: the restatement's caller is declaring which engine it is standing
    the pool up on, and a dialect this module has never seen should be refused
    by name rather than handed SQLite DDL that will fail somewhere further
    from the ask.  The ``CHECK`` constraint feature 191 declares is deliberately
    absent: this member never writes a world row, so the either-or law it
    enforces is the *owner's* to state, and restating it here would be this
    member holding an opinion about a table it only reads.
    """
    if not isinstance(dialect, str) or dialect.lower() != "sqlite":
        raise ValueError(
            f"the replay pool's restated schema is sqlite only — got "
            f"{dialect!r}; this member restates the pool's shape for its own "
            "suite to stand a pool up on, and a dialect it has never seen is "
            "one whose DDL it cannot honestly spell"
        )
    return "\n".join(POOL_SCHEMA_BY_TABLE[table] for table in POOL_TABLES)


def pool_tables_present(connection) -> tuple[str, ...]:
    """Which of the pool's tables the database holds — the membership question.

    The one probe this module offers, and the reason it is here rather than in
    :mod:`dreaming.cycle`: it is a question *about the pool's shape*, which is
    what this module restates, and the cycle asks it for two different reasons
    — :meth:`dreaming.cycle.CycleFreeze.ensure_schema` refuses a database with
    no pool to hold, and :func:`dreaming.cycle.pool_commitment` refuses a pool
    table that is missing rather than counting it as empty.

    ``sqlite_master`` is read, never the rows, which makes it a safe question
    to ask before a read that would otherwise fail with "no such table" — the
    probe :mod:`ledger.store` makes for ``epoch_ledger`` and
    :mod:`tripwires` makes for the pool it must read.

    Takes an open connection rather than a path, so a caller that already has
    one does not pay for a second, and returns a tuple in
    :data:`POOL_TABLES` order so an absent-table report is stable.  A driver
    that cannot answer at all propagates its own error untouched: this function
    refuses nothing and invents nothing, which is what makes*"the pool is not
    here"* a fact the caller can distinguish from a fault in the question.
    """
    present = []
    for table in POOL_TABLES:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        if row is not None:
            present.append(table)
    return tuple(present)
