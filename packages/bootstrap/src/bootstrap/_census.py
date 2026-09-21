"""The two pools' sizes, tracked independently — feature 186.

app_spec.xml, "Bootstrap Worlds", feature 186: *System tracks financial
world count independently from bootstrap world count, which returns both
figures separately.*  docs/nullius-tech-architecture.md §10.6 states the
rule the sentence exists to enforce, and states it as a reporting rule
before it states it as a counting rule:

    **Report the two pools separately.**  A gain that only appears on
    bootstrap worlds is a gain on hyperparameter search, not on alpha
    discovery.  The orchestrator tracks ``n_financial`` independently and
    the M3 gate is evaluated on financial holdout worlds only.

§10.6.1 restates the same rule for the ported half, in the one sentence
that makes the counting direction asymmetric — bootstrap worlds may raise
``n`` but must never raise ``n_financial``:

    ... it pads ``n``, never ``n_financial``.  The M3 gate is still
    evaluated on financial holdout worlds only.

**Why two figures cannot be one number, and why the code must say so.**
Every precondition in this system is a *world count* — §12.1's ladder
blocks dreaming below 20 worlds and caps ``M`` between 20 and 50, and
§10.3.1 derives ``n > 53`` from the paired comparison's power — so a
single ``n`` that mixed the two pools would let 45 generated
hyperparameter-search worlds stand in for 45 crypto campaigns, and the M3
gate would be evaluated on a pool it was never meant to see.  The failure
is silent in exactly the way §10.6 warns: the bootstrap pool *does* raise
a headline number, and a report that could not tell which pool the number
came from would read a gain on Lasso solving as a gain on alpha
discovery.  So this module ships no single count.  :class:`WorldCensus`
holds ``n_financial`` and ``n_bootstrap`` as two fields and its
:meth:`~WorldCensus.row` hands a report back those two and nothing else;
:attr:`~WorldCensus.total` exists because §12.1's ladder genuinely reads
the *total* ("below 20 worlds", "between 20 and 50", and §10.3.1's own
``n = pool.n_worlds()``), and it is documented as the ladder's reading so
that a caller reaching for it learns what it is not.

**"Independently" is a property of the two reads, not of two integers kept
apart.**  A census built by counting the rows of ``bootstrap_world`` and
trusting a caller for the other figure would satisfy the letter of the
sentence and defeat it, because the two numbers would then be comparable
in appearance only.  Both figures are therefore *read here, from one
database*, and the exclusion between them is enforced rather than assumed:

* The **bootstrap** figure is the pool's own answer
  (:meth:`~bootstrap.BootstrapPool.world_count`) — every authored row and
  every ported row, because §10.6 is explicit that *"Authored worlds and
  ported external worlds both qualify"* for padding ``n``.  It is the
  pool's answer rather than a second count taken here, so the number a
  census reports and the number the pool reports cannot drift apart.
* The **financial** figure is the count of distinct worlds the replay pool
  holds *besides the bootstrap half* — the ``world_id`` values of
  ``replay_score`` (migration ``0109``'s table, whose ``world_id`` column
  is the whole join) that ``bootstrap_world`` does not hold.  Distinct,
  because a ``replay_score`` row is one *(policy, world)* pair: §10.3.1
  replays every candidate revision across every stored world, so counting
  rows would multiply one world by the number of revisions that replayed
  against it and report a pool that grew every time the dreaming loop
  ran.  And *excluded*, because §10.6's whole point is that replays run
  against bootstrap worlds too — a census that counted every ``world_id``
  it saw would let the 45 worlds this category authors inflate
  ``n_financial`` to 45 the moment the loop scored them, which is the
  precise inversion of §10.6.1's *"pads ``n``, never ``n_financial``"*.

**The exclusion is by the pool's own membership, not by the id's shape.**
A bootstrap world id is text (``bootstrap-hpo-20260922-07``) and a
financial world id is a UUID, so a prefix test would happen to work today
— and would be wrong, because it makes the census's answer a fact about
how ids are spelled rather than about what the pool holds.  The pool is
the authority on which worlds are bootstrap worlds (its ``domain`` column
already carries §10.6's four branches, ``hpo``/``featsel``/``symreg``/
``ported``, and 182-183's domains will join it), so the census asks *the
pool*: a world id ``bootstrap_world`` holds is not a financial world, and
a domain this member grows later is excluded the day its row is written
rather than the day someone remembers to widen a prefix list.  The join
is spelled ``NOT EXISTS`` rather than ``NOT IN`` deliberately: SQL's
``NOT IN`` is *unknown* — and so silently empty — the moment the
subquery yields a ``NULL``, and a census that answered zero because a
hand-edited row was empty would report an empty financial pool to the
gate §10.3.1 blocks dreaming on.

**An absent ``replay_score`` is a refusal, not a zero.**  The two figures
live in one database — the one ``DATABASE_URL`` names and the pool
resolves, the same database feature 188 chose so that *"persists into the
replay pool"* is a statement about the pool the dreaming loop reads — and
a database that has no ``replay_score`` table at all has no replay pool
in it.  Answering zero there would be inventing a pool size, which is the
argument :mod:`ledger.store` makes for its own absent table, and here it
is sharper still: ``n_financial = 0`` is a *blocking* answer (the ladder
refuses to dream below 20 worlds), so a mis-pointed database would halt
dreaming with a number this member made up rather than with a refusal an
operator can read.  The census therefore names the table and the database
it could not find it in, and the caller that meant to count a migrated
deployment finds out immediately.

**The refusal vocabulary is the pool's, and that is the seam.**  Every
way a census can fail is a fact about the *pool* rather than about a
world or a label: the database holds no replay pool, the object handed in
is not a pool, a pool's own count answered something that is not a size.
None of those is a world that cannot be named
(:class:`~bootstrap.BootstrapWorldError`) or an arithmetic that had no
answer (:class:`~bootstrap.BootstrapScoringError`), so every refusal
raises :class:`~bootstrap.BootstrapPoolError` — "the ask was never about a
world" — and a fourth class would be a distinction the caller's ``except``
cannot act on.  The one refusal the census does *not* translate is the
pool's own: a ``DATABASE_URL`` scheme this store cannot speak is raised by
:meth:`~bootstrap.BootstrapPool.path` in the pool's vocabulary, which is
where it belongs, because the URL is the pool's contract and the census
was handed the pool — translating it here would be a second spelling of a
refusal the caller already has a ``except`` for.

**What this module deliberately does not ship.**  It renders no verdict —
feature 187's *"rejects a headline dreaming claim resting on bootstrap
worlds alone"* is a judgment about a claim, made where the claim and both
figures are visible, and a census that decided it would be answering a
question about a report from inside a counting module.  It persists
nothing (the figures are reads; the pool owns the rows and the replay
member owns the scores, and §9.1's evidence is not this member's to
write), charges no budget (feature 185's ``charges_budget`` is the
trial's fact), and adds no component: the census is a read over state the
two component builders already expose, so it is a free function beside
them, the way :func:`~bootstrap.ground_truth` and
:func:`~bootstrap.question_for` are — registering a third component for
it would put a third name in the registry for a question that resolves no
configuration of its own.

Stdlib only, and import-cheap: ``sqlite3`` and ``dataclasses``, no
third-party import at module scope, so the factory's scan — which imports
this package to fire its ``@register`` — pays nothing for the census.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from typing import Any

from ._pool import POOL_TABLE
from .errors import BootstrapPoolError

__all__ = [
    "REPLAY_SCORE_TABLE",
    "REPLAY_SCORE_WORLD_COLUMN",
    "WorldCensus",
    "world_census",
]

#: The table the financial half of the count is read from —
#: ``migrations/versions/0109_replay_score_and_policy_revision.py``'s, and
#: §10.6's *"the replay pool"* in app_spec.xml's own vocabulary.  Spelled
#: here rather than imported for the reason :mod:`tripwires.layout` and
#: :mod:`canary._void` spell it: this member never imports another
#: workspace member, and the name is the whole of what it needs to know
#: about a table it only reads.  The census writes nothing to it.
REPLAY_SCORE_TABLE = "replay_score"

#: **The column the whole feature turns on.**  ``replay_score.world_id``
#: is the stored world the policy was replayed against, so it is the one
#: place a financial world is *named* in this database — and therefore the
#: only column a financial world can be counted from.  It is
#: ``UUID NOT NULL`` in ``0109``'s DDL; the null guard in
#: :data:`_FINANCIAL_COUNT` is there for a row a hand had been to, not for
#: the shape the migration declares.
REPLAY_SCORE_WORLD_COLUMN = "world_id"

#: The financial half's whole read: distinct worlds the replay pool holds
#: that the bootstrap pool does not.
#:
#: Three clauses, each argued in the module docstring and each load-bearing:
#:
#: * ``COUNT(DISTINCT ...)`` — a ``replay_score`` row is one *(policy,
#:   world)* pair, so a plain ``COUNT`` would report a world once per
#:   revision that replayed against it and grow with every dreaming cycle;
#: * ``IS NOT NULL`` — ``DISTINCT`` treats ``NULL`` as a value, so a
#:   nullable world id would let one empty row add a phantom world to the
#:   count (``0109`` declares the column ``NOT NULL``, so this guard is
#:   for a row that wandered in from outside the write);
#: * ``NOT EXISTS`` rather than ``NOT IN`` — ``NOT IN`` over a subquery
#:   holding one ``NULL`` is unknown for every row and so answers zero,
#:   which is the answer this feature must never invent.
#:
#: The subquery reads ``bootstrap_world`` rather than a list of domains,
#: because the pool is the authority on which worlds are bootstrap worlds:
#: ``hpo``, ``ported`` and the ``featsel``/``symreg`` domains features
#: 182-183 will add are all excluded the moment their rows exist.
_FINANCIAL_COUNT = f"""
SELECT COUNT(DISTINCT r.{REPLAY_SCORE_WORLD_COLUMN})
FROM {REPLAY_SCORE_TABLE} AS r
WHERE r.{REPLAY_SCORE_WORLD_COLUMN} IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM {POOL_TABLE} AS b
      WHERE b.world_id = r.{REPLAY_SCORE_WORLD_COLUMN}
  )
"""


@dataclass(frozen=True)
class WorldCensus:
    """Both pools' sizes, held separately — feature 186's whole value.

    Two fields and no third, because the feature's sentence says *both
    figures separately* and one figure that mixed them is the thing
    §10.6 exists to forbid.  ``n_financial`` counts the stored worlds of
    the replay pool that are **not** bootstrap worlds — the number §10.6
    says the orchestrator tracks independently and §10.6.1 says can never
    be padded — and ``n_bootstrap`` counts the worlds
    ``bootstrap_world`` holds, authored and ported alike, which §10.6's
    *"Authored worlds and ported external worlds both qualify"* is the
    reason to count as one figure rather than two.

    Frozen, so two callers holding one census hold the same pair of
    numbers, and equal by those two fields, so a census taken twice over
    an unchanged pool is one value a report can compare.  The counts are
    validated at construction rather than trusted: a hand-built census is
    a test's prerogative, and a negative or non-integer count would be a
    pool size no read could produce — the kind of value that reaches a
    gate precondition and blocks (or admits) a dreaming cycle on a number
    nobody measured.
    """

    n_financial: int
    n_bootstrap: int

    def __post_init__(self) -> None:
        for field in ("n_financial", "n_bootstrap"):
            value = getattr(self, field)
            # A ``bool`` is refused where a count belongs for the reason
            # the member refuses one on an axis and on an evidential bar:
            # ``True`` is ``1`` in Python, so a flag where a count belongs
            # would silently report a pool of one.
            if isinstance(value, bool) or not isinstance(value, int):
                raise BootstrapPoolError(
                    f"{field} is a count of worlds — got {value!r} "
                    f"({type(value).__name__}); the two figures are the "
                    "pools' sizes, and a value that is not a whole number "
                    "is a size no database could report"
                )
            if value < 0:
                raise BootstrapPoolError(
                    f"{field} is a count of worlds and cannot be negative "
                    f"— got {value!r}; a pool holds zero worlds or more, "
                    "and a negative size would reach §12.1's ladder as a "
                    "pool thinner than any pool this system can hold"
                )

    @property
    def total(self) -> int:
        """``n_financial + n_bootstrap`` — §12.1's ladder reading, and nothing else.

        The sum is a real figure with one reader: §12.1's ladder counts
        *worlds* — *"below 20 worlds"*, *"between 20 and 50"*, *"50+
        worlds"* — and §10.3.1's own fragment reads ``n = pool.n_worlds()``
        without asking which pool a world came from, because the *ladder*
        is a compute budget rather than a claim about alpha.  So the sum
        exists, and it is the only thing in this module that mixes the two
        pools.

        It is deliberately **not** what §10.6's M3 gate reads.  That gate
        is evaluated on financial holdout worlds only, which is
        :attr:`n_financial` and never this; a caller that reached for
        ``total`` where the gate belongs would be admitting 45 generated
        hyperparameter-search worlds as evidence about crypto alpha, which
        is the single failure both §10.6 and §10.6.1 name.  The property
        is named for what it is rather than derived at the call site so
        that the distinction is documented in one place.
        """
        return self.n_financial + self.n_bootstrap

    def row(self) -> dict[str, int]:
        """The census as a store-shaped mapping — a fresh dict per call.

        **The two figures and nothing else**, which is the feature's
        sentence taken literally: *"returns both figures separately"*.
        :attr:`total` is deliberately left out even though it is one
        addition away, because a report that wrote a mixed count beside
        the two would be a third number for a reader to reach for — and
        the reader who reached for it is the one §10.6 warns about.
        """
        return {"n_financial": self.n_financial, "n_bootstrap": self.n_bootstrap}

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"WorldCensus(n_financial={self.n_financial!r}, "
            f"n_bootstrap={self.n_bootstrap!r})"
        )


def _counting_pool(pool: Any) -> tuple[Any, Any]:
    """Check that ``pool`` is a bootstrap pool, and return its two readers.

    Duck-typed rather than ``isinstance``, for the reason feature 184's
    question and feature 189's labeling are: the module loader imports the
    member under a synthetic name and re-executes it, so the composed pool
    ``create_app()`` hands out is a *second* ``BootstrapPool`` class
    object, and an ``isinstance`` gate here would refuse the very pool the
    composition seam serves.  What is checked is the surface the census
    calls through — the ``world_count()`` it asks for the bootstrap figure
    and the ``path`` it reads the financial figure from — so a string, a
    dict or a bare object is refused naming what was missing.

    The attributes are *checked* here and *called* by
    :func:`world_census`, so a pool that is refused for its shape is
    refused before the census has touched the disk: a refusal that arrived
    after ``world_count()`` had already created a table would be a
    validation that ran too late to be one.
    """
    counter = getattr(pool, "world_count", None)
    if not callable(counter):
        raise BootstrapPoolError(
            f"a census counts a bootstrap pool — got {pool!r} "
            f"({type(pool).__name__}), which has no callable "
            "``world_count``; one of the two figures is the bootstrap "
            "pool's own count, and an object that is not a pool holds no "
            "worlds for it to report"
        )
    path = getattr(pool, "path", None)
    if path is None:
        raise BootstrapPoolError(
            f"a census reads both pools from one database — got {pool!r} "
            f"({type(pool).__name__}), which names no ``path``; the "
            "financial figure is counted from the replay pool's scores, "
            "and where the bootstrap pool lives is where those scores "
            "live (§10.6's pool is one pool)"
        )
    return counter, path


def _bootstrap_count(counter: Any) -> int:
    """The bootstrap figure, as the pool itself answers it.

    Read through the pool rather than recounted here so the number a
    census reports and the number :meth:`~bootstrap.BootstrapPool.
    world_count` reports are one read — a second ``COUNT(*)`` over the
    same table would be a second spelling of "how many worlds does the
    pool hold", free to drift from the first the day the pool's definition
    of a world changes.

    The answer is validated because a duck-typed pool is a caller's
    object, not this member's: a counter that returned ``None``, a string
    or a flag would put a value the census cannot vouch for into a figure
    §12.1's ladder blocks dreaming on.
    """
    held = counter()
    if isinstance(held, bool) or not isinstance(held, int) or held < 0:
        raise BootstrapPoolError(
            f"a pool's ``world_count()`` answers the number of worlds it "
            f"holds — got {held!r} ({type(held).__name__}); the bootstrap "
            "figure reaches §12.1's ladder as a pool size, and a value "
            "that is not a non-negative whole number is a size the census "
            "cannot report as measured"
        )
    return held


def _has_replay_pool(connection: sqlite3.Connection) -> bool:
    """Whether the database holds a ``replay_score`` table yet.

    ``sqlite_master`` is read (never the rows), which makes it a safe
    question to ask before the count — the probe :mod:`ledger.store` makes
    for ``epoch_ledger`` and :mod:`tripwires` makes for the pool it must
    read.  It is asked of the *table* rather than assumed, because the two
    states it tells apart are different facts: a migrated deployment with
    no scores yet genuinely holds zero financial worlds, while a database
    without the table has no replay pool in it at all, and the census must
    refuse the second rather than answer the first's zero for it.
    """
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (REPLAY_SCORE_TABLE,),
    ).fetchone()
    return row is not None


def world_census(pool: Any) -> WorldCensus:
    """Count both pools, separately, from the database they share.

    The one factory for the census, the way :func:`~bootstrap.question_for`
    is the one factory for the question and :func:`~bootstrap.ground_truth`
    the one factory for the labeling: a bootstrap pool in, the two figures
    out.  It answers feature 186's sentence whole — *"tracks financial
    world count independently from bootstrap world count, which returns
    both figures separately"* — by reading the two counts where both are
    visible, so neither can be derived from the other.

    ``n_bootstrap`` is :meth:`~bootstrap.BootstrapPool.world_count`'s own
    answer (authored rows and ported rows, §10.6's *"both qualify"*);
    ``n_financial`` is the number of distinct worlds recorded in
    ``replay_score`` that the bootstrap pool does not hold
    (:data:`_FINANCIAL_COUNT`, argued clause by clause above).  The two
    reads are made in the same database — the one the pool resolves — so
    *"the replay pool"* means one pool in both figures, exactly as feature
    188 chose when it persisted the bootstrap half into the database
    ``replay_score`` lives in.

    Refuses, in this order, each naming what it is about:

    1. an object that is not a bootstrap pool — no ``world_count`` to ask
       or no ``path`` to read — refused before anything touches the disk;
    2. a pool whose ``world_count()`` answers something that is not a
       non-negative whole number, and a database the pool cannot speak
       (:class:`~bootstrap.BootstrapPoolError`, raised by the pool's own
       path resolution and deliberately not translated: the URL is the
       pool's contract, and the census was handed the pool);
    3. a database holding no ``replay_score`` table — no replay pool to
       count a financial figure in, so the census refuses rather than
       answering the zero that would block §12.1's ladder with a number it
       invented.

    Reads only: the census writes no row to ``replay_score`` and none to
    ``bootstrap_world`` beyond the ``CREATE TABLE IF NOT EXISTS`` the
    pool's own read performs, so taking a census can never change the
    figures the next census reports.
    """
    counter, path = _counting_pool(pool)
    # The pool's own count first, and through the pool's own connection:
    # it is the read that brings ``bootstrap_world`` to its shape, so the
    # exclusion below is asked of a table that certainly exists.
    held = _bootstrap_count(counter)
    with closing(sqlite3.connect(path)) as connection:
        if not _has_replay_pool(connection):
            raise BootstrapPoolError(
                f"the database at {path} holds no {REPLAY_SCORE_TABLE} "
                "table, so there is no replay pool to count a financial "
                "world figure in — a census reports both pools' sizes, and "
                "a zero answered here would be a pool size this member "
                f"invented rather than measured (point {pool!r} at the "
                "database the replay pool lives in, or migrate it)"
            )
        (n_financial,) = connection.execute(_FINANCIAL_COUNT).fetchone()
    return WorldCensus(n_financial=int(n_financial), n_bootstrap=held)
