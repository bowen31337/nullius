"""The deduplication gate — one code, one node, one trial — feature 179.

app_spec.xml, "Tree & Artifact Persistence", feature 179: *System
deduplicates a proposed node against stored ``code_hash`` values, which
rejects an exact duplicate before it charges a trial.*  docs/nullius-tech-
architecture.md §9.1 draws the column and its reader in the one line every
part of this rule stands on::

    code_hash   CHAR(64) NOT NULL,

    CREATE INDEX ON node (code_hash);        -- dedup

**Why an exact duplicate must be rejected rather than scored.**  The
trial ledger is the denominator of every calibration number the system
produces: §8 derives ``K_effective`` per epoch by counting the rows a null
oracle marked ``charges_budget`` true (feature 93), and the deflation term
that gates a campaign's headline rests on that count.  A node that is
byte-for-byte the code of a node already in the tree therefore cannot be
charged like a fresh hypothesis — it is the *same* hypothesis — and a
charge for it would inflate ``K_effective`` with a trial that measured
nothing.  §14.1 names the failure mode from the other end: *"A converged
tree is not caught by anything.  At roots, a weak model's failure mode is
proposing the 400th variant of one indicator."*  The exact duplicate is
the degenerate case of that convergence — the same signal, resubmitted —
and the place it is caught is here: before the evaluator runs, before the
sandbox is entered, before the debit.

**The gate is a pre-trial check, not a unique constraint.**  Migration
0113's ``node_code_hash`` index is deliberately **not** ``UNIQUE`` (feature
102 says "an index", and 0113's docstring argues the point at length), so
the guarantee feature 179 states is the writer's: the check runs *before*
the trial is charged and rejects the duplicate, and the index exists to
make that check cheap.  0113 names the exposure that leaves open — *"two
writers racing feature 179's check can both pass it and both charge a
trial"* — and names it as this feature's to close, suggesting *"a
serialized probe, or a unique index requested by its own migration"*.  A
unique index would be the constraint the spec withheld, and a constraint
arriving out of band is what 0113 declines to invent; so this module
closes it the other way, with the serialized probe:
:meth:`CodeHashIndex.probe` holds ``BEGIN IMMEDIATE`` on the tree store's
write lock across the check *and* the caller's write, so concurrent
proposals of one code serialise on the lock and every proposer after the
first is answered by the first's row rather than racing past the probe.
The probe hands the caller the connection it holds the lock on, so the
node row that is about to be charged is written inside the same
transaction — the reject-then-charge ordering made structural instead of
trusted to the caller.

**The check is over the whole tree, because the code hash is content
identity.**  §9.1 draws this feature's index on ``code_hash`` *alone* —
``CREATE INDEX ON node (code_hash);  -- dedup`` — where the lookup that
does want a campaign in its key is spelled beside it as
``(campaign_id, parent_id)``: the schema says which term an index keys on,
and this one names no campaign.  0113 and 0117 read the same fact from the
constraint side — *"two rows carrying the same one are the same node"* —
and the reason that index needs no ``UNIQUE`` is that *"two distinct nodes
may hash to the same code only by being the same code — the dedup gate
refuses that pair before either charges a trial, so the index has no
duplicate rows to find."*  That argument holds only if the gate refuses the
pair **anywhere in the tree**: a campaign-scoped gate would leave one code
in two campaigns and hand the index exactly the duplicate rows 0117 says it
has none of.

Nor does scoping it wider cost anything a re-test needs.  The temptation is
to read "a later campaign re-proposes this code against a different epoch"
as a legitimate second proposal, but §1 forecloses it: the replay engine
*"has read access to the artifact store and zero access to the evaluator or
sandbox"*, and that is *"what makes dreaming free"* — a stored node is
re-tested by replay, which charges no trial, never by re-proposing the same
bytes down the evaluation path.  So the comparison is against every stored
``code_hash``, and the read is the lookup this feature's index exists to
serve: ``WHERE code_hash = ?``, not a retreat of one campaign's rows to be
compared in Python.  Getting the scope wrong is not a scope error but a
half-gate — the second spelling of the same code, charged in full.

**The stored value is the identity, so the comparison is exact.**  §9.1
types the column ``CHAR(64)`` and the workspace's every writer computes it
with :func:`hashlib.sha256(...).hexdigest() <_canonical_code_hash>` — the
lowercase hexdigest, spelled once here and refused when it is anything
else.  ``"AB…"`` and ``"ab…"`` are one hash written two ways, so the
canonical spelling folds case rather than refusing a caller who
uppercased it, while a short hash, a ``sha256:``-prefixed image reference
or a non-string is refused by name: a proposal that cannot state its code
identity cannot be deduplicated, and guessing at it is how a duplicate
slips through the gate it was meant to fail.

**Three spellings, one decision.**  The comparison is spelled once — a
proposal is a duplicate when a stored row already holds its canonical code
hash — and everything else is a seam over the moments a proposal meets the
tree:

* :func:`reject_duplicate` — the *data* spelling.  A caller holding stored
  hashes as an iterable (a frontier it just read, a report's pool) hands
  them over with the proposal's hash and gets the hash back, or the
  refusal.  No store, no connection, and the whole of the feature's
  decision.
* :meth:`CodeHashIndex.check` — the *stored* spelling.  The gate runs the
  lookup feature 102's index exists to serve and hands what it finds to
  the same decision.  Read-only: the seam a reporting path uses to explain
  *why* a proposal would be rejected.
* :meth:`CodeHashIndex.probe` — the *serialized* spelling, and the one the
  ordering feature 179 states actually needs: the lock the check shares
  with the caller's write, so the reject-then-charge pair cannot be split
  by a concurrent proposer.  Read-only callers want :meth:`check`;
  proposal paths want this.

**Nothing here charges anything.**  This member owns the artifact
directory (feature 169) and this gate; the ledger is feature 84's and the
debit endpoint feature 95's.  Nor does this module write a ``node`` row:
§9.1's table is the tree member's DDL and its non-metric columns
(``theme_root``, ``depth``, the provenance triple) are the tree member's
to spell, so :meth:`CodeHashIndex.probe` hands the caller the locked
connection and the caller's own writer builds the row inside it.  What
this module owes the pipeline is the *ordering* — the check that stands
between a proposal and its trial — and it owes it in a form the caller
cannot accidentally reorder.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterable, Iterator, Mapping
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from ._errors import (
    ArtifactDeduplicatedError,
    ArtifactProposalError,
    ArtifactStoreError,
)

__all__ = [
    "CODE_HASH_COLUMN",
    "CODE_HASH_LENGTH",
    "CODE_HASH_ROLE",
    "DATABASE_URL_ENV",
    "DUPLICATE_CODE_HASH",
    "NODE_CODE_HASH_INDEX",
    "NODE_TABLE",
    "CodeHashIndex",
    "StoredCodeHash",
    "canonical_code_hash",
    "reject_duplicate",
]

#: The environment variable naming the relational store — the one spelling
#: every store in this workspace uses (the evaluator's stores, the ledger's,
#: the null oracle's guard), restated here so the gate states its own
#: contract and nothing imports another store's.
DATABASE_URL_ENV = "DATABASE_URL"

#: The tree store's node table — feature 97's.  The same spelling every
#: module that joins the tree states, so the gate and the table's owner
#: cannot drift apart on what the tree store is called.
NODE_TABLE = "node"

#: The column feature 179 deduplicates against — feature 98's own, §9.1's
#: ``code_hash CHAR(64) NOT NULL``.  Named here because it is the *subject*
#: of this feature's sentence rather than a column the gate happens to read.
CODE_HASH_COLUMN = "code_hash"

#: The index feature 102 created over that column and 0113 rendered as
#: ``node_code_hash``.  Carried by name so the read path can be spelled the
#: way the schema was built for and a reader can tell at a glance that this
#: feature's probe is the query the index exists to serve.  Purely
#: documentary at this level — SQLite chooses its own plan, and the gate's
#: ``SELECT`` names the columns, never the index.
NODE_CODE_HASH_INDEX = "node_code_hash"

#: §9.1's ``CHAR(64)`` — the length of a stored code hash, and the length
#: the canonical spelling is checked against.  A sha256 hexdigest and
#: nothing else.
CODE_HASH_LENGTH = 64

#: The role a refused value played, for a message that names which term of
#: the address was wrong.
CODE_HASH_ROLE = "code_hash"

#: The error code feature 179's refusal carries, in the spec's own
#: vocabulary for it.  The message begins with this word so the rejection is
#: greppable by the feature that defines it — the convention §7.3's
#: ``heterogeneous_world`` and §7.1's ``is_null_column`` refusals already
#: follow in this workspace.
DUPLICATE_CODE_HASH = "duplicate_code_hash"

#: The hexdigest alphabet, lowercase — the case every accepted spelling is
#: folded to before it is compared against this set.
_HEX_DIGITS = frozenset("0123456789abcdef")


def canonical_code_hash(value: Any) -> str:
    """Return ``value`` as the canonical 64-character code hash, or refuse it.

    §9.1 types the column ``CHAR(64)`` and every writer in this workspace
    fills it with ``hashlib.sha256(source.encode("utf-8")).hexdigest()``
    (the evaluator's step 6 is the reference spelling), so the canonical
    form is exactly that: 64 lowercase hex characters.  Case is *folded*,
    not refused — ``"AB…"`` and ``"ab…"`` are one digest written two ways,
    and a gate that treated them as two codes would let the second spelling
    of a duplicate through, which is the one thing this feature exists to
    prevent.

    Anything else is refused by name: a truncated or short hash, a
    ``sha256:``-prefixed image reference (the shape :mod:`snapshot` and
    :mod:`canary` deal in and the one the ledger's provenance validator
    refuses for the same reason — a term that names nothing is not made
    acceptable by arriving from somewhere else), a non-hex token, a
    non-string.  The refusal is loud because the alternative is silent: a
    proposal that cannot state its code identity cannot be deduplicated,
    so a gate that guessed at it would pass every duplicate it was handed.
    """
    if not isinstance(value, str):
        raise ArtifactProposalError(
            f"a proposed node's {CODE_HASH_ROLE} must be a string — the "
            f"sha256 hexdigest §9.1 stores as CHAR(64) — got "
            f"{type(value).__name__} {value!r}; the code hash is the "
            "identity feature 179 deduplicates on, and a value that is not "
            "one names no node this gate could compare against"
        )
    text = value.strip().casefold()
    if len(text) != CODE_HASH_LENGTH or any(
        char not in _HEX_DIGITS for char in text
    ):
        raise ArtifactProposalError(
            f"a proposed node's {CODE_HASH_ROLE} must be "
            f"{CODE_HASH_LENGTH} hexadecimal characters — got {value!r} "
            f"(length {len(text)}); §9.1 types the column CHAR(64) and the "
            "system computes it as sha256(source).hexdigest(), so a "
            "truncated hash, a prefixed reference or a non-hex token is a "
            "code identity nothing stored could ever equal — and a "
            "duplicate that cannot be compared is a duplicate that gets "
            "charged"
        )
    return text


def reject_duplicate(
    proposed_code_hash: Any,
    stored_code_hashes: Iterable[Any],
    *,
    node_id: str | None = None,
) -> str:
    """Return the canonical hash, or refuse when the tree already holds it.

    Feature 179's sentence as one call over *data*: the stored
    ``code_hash`` values (whatever the caller read — a frontier, a report's
    pool, a lookup this gate was not asked to re-run) and the hash a
    proposed node carries.  Returns the proposed hash canonicalized, so a
    caller can chain into the write it gates; raises
    :class:`~artifacts._errors.ArtifactDeduplicatedError` with the
    :data:`DUPLICATE_CODE_HASH` code when the value is already stored —
    *before* any trial is charged, which is the whole of the feature.

    The caller's ``node_id`` is carried into the refusal so the message
    names the proposal that collided as well as the code it collided on;
    it is optional because this spelling answers correctly without it (the
    decision is the hash comparison alone) and a caller holding no more
    than a list of hashes should not have to invent a name to ask the
    question.

    A malformed value on *either* side is refused rather than skipped.
    The stored hashes are validated with the same
    :func:`canonical_code_hash` the proposal is, deliberately: a stored
    row that does not hold a code hash is a tree this gate cannot vouch
    for, and quietly ignoring it would mean a duplicate hiding behind one
    corrupt row is charged like a fresh hypothesis.  That is a different
    fact from a duplicate and gets a different message, so an operator can
    tell "the proposal is a repeat" from "the store is not readable".
    """
    proposed = canonical_code_hash(proposed_code_hash)
    for stored in stored_code_hashes:
        try:
            existing = canonical_code_hash(stored)
        except ArtifactProposalError as exc:
            raise ArtifactProposalError(
                f"a stored {CODE_HASH_ROLE} value could not be read, so no "
                f"proposal can be deduplicated against it: {exc}"
            ) from exc
        if existing == proposed:
            raise _duplicate_refusal(
                proposed,
                node_id=node_id,
                stored_hash=existing,
            )
    return proposed


def _duplicate_refusal(
    code_hash: str,
    *,
    node_id: str | None,
    stored_hash: str,
) -> ArtifactDeduplicatedError:
    """The one refusal, spelled once for every seam that reaches it.

    Names the code, the proposal that collided and — the part a caller
    acts on — *what did not happen*: no trial was charged, because the
    rejection precedes the charge.  The ``duplicate_code_hash`` prefix is
    the spec's code for the rejection and is pinned as a prefix rather than
    a substring so a log line cannot carry it by accident.
    """
    proposed_by = f" for the proposed node {node_id!r}" if node_id else ""
    return ArtifactDeduplicatedError(
        f"{DUPLICATE_CODE_HASH}: the code hash {code_hash} of the node "
        f"proposed{proposed_by} is already stored in this tree; feature 179 "
        "rejects an exact duplicate before it charges a trial, and this "
        "rejection precedes the charge — no trial was debited for this "
        "proposal. §9.1 draws the index this lookup runs on over "
        "code_hash alone, because the column is *content* identity: two "
        "nodes carrying these exact bytes are not two hypotheses but one, "
        "and charging the second would inflate the K_effective the "
        "deflation term is computed from (§8, feature 93). Propose a "
        "structurally different signal — §14.1's anti-convergence clause "
        "is the same rule from the search side: a tree that collapses into "
        "parameter tweaks of one indicator consumes the budget and catches "
        "nothing. A stored node is re-tested by replay, which charges no "
        "trial, never by re-proposing its bytes down this path"
    )


# -- The stored spelling ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StoredCodeHash:
    """One row of the tree, as the dedup lookup reads it.

    The node's identity and the code hash it holds — the two columns §9.1's
    ``node_code_hash`` index covers for this feature's lookup.  Frozen for
    the reason every record in this workspace is: it is a value read across
    a seam, and a reservation answered from a value a caller could edit is
    a reservation nothing vouches for.
    """

    #: The node's id (``node.id``).
    node_id: str
    #: The canonical code hash the node carries (``node.code_hash``).
    code_hash: str


class CodeHashIndex:
    """The tree's stored code hashes, and the gate over them.

    Feature 179's store half: bound to a database URL at construction (see
    :meth:`resolve`), looking a proposed code hash up against the ``node``
    table's stored ones — the lookup ``node_code_hash`` exists to serve —
    and, through :meth:`probe`, serializing that lookup with the caller's
    write so two proposers holding one code cannot both charge.

    Construction performs no I/O, the contract every store in this
    workspace states: the connection is opened per operation, so composing
    an application that carries this gate touches no disk and a deployment
    with no ``DATABASE_URL`` composes ``None`` rather than taking
    composition down.

    **Why the gate is a store and not just a comparison.**  A bare
    comparison is enough for a caller who has already read the tree's
    hashes — :func:`reject_duplicate` is that spelling and it needs no
    store at all.  What a *proposal path* needs is the half that makes the
    comparison safe to run concurrently: the probe and the record of the
    proposal must be one transaction, or two proposers holding the same
    code both read "not stored" and both charge.  That is the exposure
    0113 names as this feature's to close, and :meth:`reserve` is where it
    is closed.
    """

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise ArtifactStoreError(
                f"{DATABASE_URL_ENV} must be a non-empty database URL"
            )
        self._database_url = database_url.strip()
        # Resolved on first use rather than at construction: building the
        # gate is composition-time work and must not touch the disk.
        self._path: Path | None = None

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(
        cls, env: Mapping[str, str] | None = None
    ) -> CodeHashIndex | None:
        """The gate ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset — the same
        treatment the shared fixtures give an empty ``TEST_DATABASE_URL``
        and every other store in this workspace gives this variable.
        Absent is not an error: it is a deployment without a relational
        store, which composes no gate — a discoverable state, not an
        exception.  **This method never raises**, because the factory
        builds every registered component on every
        :func:`~app.module_loader.create_app` call, and a builder that
        raised would take composition down for every unrelated feature.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> CodeHashIndex:
        """The gate ``DATABASE_URL`` names, refused by name when it names none.

        :meth:`resolve`'s strict twin, with the same spelling the artifact
        store's :meth:`~artifacts.ArtifactStore.from_env` uses: a caller
        that already knows it needs a gate — a proposal path about to charge
        a trial — asks for one and is told by name when the deployment has
        none, rather than being handed ``None`` to remember to check.  The
        builder takes the lenient spelling, because the factory builds every
        component on every ``create_app()`` and must not raise; a *proposal*
        is the caller that must not find itself ungated.

        Unlike :meth:`resolve` this may raise, and that is the point: the
        two spellings exist so "compose or not" and "I require one" are
        different calls rather than one call whose ``None`` a caller is
        trusted to have checked.
        """
        gate = cls.resolve(env)
        if gate is None:
            raise ArtifactStoreError(
                f"{DATABASE_URL_ENV} is not set, so there is no tree store "
                "to deduplicate a proposed node against; feature 179's gate "
                "rejects an exact duplicate before it charges a trial, and a "
                "proposal path that cannot look up the stored "
                f"code_hash values cannot keep that ordering — point "
                f"{DATABASE_URL_ENV} at the system's database"
            )
        return gate

    @property
    def database_url(self) -> str:
        """The database URL this gate reads and writes."""
        return self._database_url

    @property
    def path(self) -> Path:
        """The SQLite file behind this gate, resolved on first use.

        Nothing is created at construction — the URL is translated (and a
        URL this member cannot speak is refused by name) the first time an
        operation needs it.
        """
        if self._path is None:
            self._path = _sqlite_path(self._database_url)
        return self._path

    # -- The read ------------------------------------------------------------

    def holders(self, proposed_code_hash: Any) -> tuple[StoredCodeHash, ...]:
        """Every stored node whose ``code_hash`` is this one, sorted by id.

        Feature 179's lookup, spelled as the index §9.1 draws for it is
        spelled: ``WHERE code_hash = ?`` over ``node``, the query
        ``node_code_hash`` exists to serve.  Returns ``()`` for a code the
        tree does not hold — the common case, and the answer a proposal
        path acts on.  A non-empty answer *is* the refusal: those are the
        nodes the proposed one would duplicate, and a caller reporting why
        a proposal was rejected has their ids from here.

        A proposal that is not a code hash is refused by name before any
        read, because the alternative is a query that matches nothing and
        reads as "no duplicate" — the silent pass this gate exists to
        prevent.

        The canonical code hash of each row is *not* re-validated here;
        that is :func:`reject_duplicate`'s job on whichever seam the caller
        uses, and a read that refused would make a corrupt row
        indistinguishable from a store this gate could not open.

        An absent store, and a store holding no matching row, both answer
        ``()`` — no node in either holds this code, which is the same fact
        to a gate keyed by code.  A store that will not open or has no
        ``node`` table raises :class:`~artifacts._errors.ArtifactStoreError`:
        a gate that could not read the tree must never read as one that
        found no duplicate.
        """
        proposal = canonical_code_hash(proposed_code_hash)
        path = self.path
        if not path.exists():
            # No store at all: no node can be stored in it, so the true
            # answer is the empty tuple — the same answer a store with no
            # node table yet gives, and the same stance the null oracle's
            # tree-store guard takes toward an absent database.
            return ()
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    f"SELECT id, {CODE_HASH_COLUMN} FROM {NODE_TABLE} "
                    f"WHERE {CODE_HASH_COLUMN} = ? ORDER BY id",
                    (proposal,),
                ).fetchall()
        except sqlite3.Error as exc:
            raise ArtifactStoreError(
                f"the tree store at {path} could not be read for the code "
                f"hash {proposal}: {exc}; feature 179's dedup gate looks up "
                "the stored code hashes, and a gate that could not read them "
                "must never read as one that found no duplicate"
            ) from exc
        return tuple(
            StoredCodeHash(node_id=str(row[0]), code_hash=str(row[1]))
            for row in rows
        )

    def check(self, proposed_code_hash: Any) -> str:
        """Return the canonical hash, or refuse it as a stored duplicate.

        The *stored* spelling of the decision: :meth:`holders` runs the
        lookup and :func:`reject_duplicate` makes the call on it.  Nothing
        is written — this is the read-only check a caller runs when it
        wants to know whether a proposal is a repeat without committing
        anything, and the seam a reporting path uses to explain *why* a
        proposal would be rejected.
        """
        proposal = canonical_code_hash(proposed_code_hash)
        reject_duplicate(
            proposal,
            (entry.code_hash for entry in self.holders(proposal)),
        )
        return proposal

    # -- The gate ------------------------------------------------------------

    @contextmanager
    def probe(self, proposed_code_hash: Any) -> Iterator[sqlite3.Connection]:
        """Probe the tree under a write lock, yielding the locked connection.

        The *serialized* spelling of the decision — the one feature 179's
        ordering needs and the one migration 0113 named as this feature's to
        close: *"with a plain index, two writers racing feature 179's check
        can both pass it and both charge a trial, and only the application's
        reject-then-charge ordering stands between that and a double charge.
        That exposure is feature 179's to close — it is the feature that
        owns the check, and closing it there (a serialized probe, or a
        unique index requested by its own migration) keeps the constraint
        with the behaviour that depends on it."*  This is the serialized
        probe.

        Used as a context manager, it holds ``BEGIN IMMEDIATE`` on the tree
        store's write lock while the caller's body runs, so the probe and
        whatever the body writes are one serial region: no second proposer
        can read the tree between them.  The body receives the *connection*
        the lock is held on, so a caller that is about to record its node
        writes it on that same connection and its insert is inside the same
        transaction — which is the ordering made structural rather than
        trusted::

            with gate.probe(code_hash) as connection:
                connection.execute("INSERT INTO node (...) VALUES (...)", ...)

        On a clean exit the transaction commits and the lock releases; on a
        refusal from :func:`reject_duplicate` — which is raised *before*
        the caller's body runs, so a duplicate never reaches the write —
        the transaction rolls back and the lock releases with nothing
        written.  A body that raises rolls back too, so a failed write
        cannot leave a half-built node holding the lock.

        **The gate does not write the node row itself.**  §9.1's ``node``
        table is the tree member's DDL and its non-metric columns are the
        tree member's to spell; a gate that INSERTed a row here would be
        reaching across that boundary, and it would have to invent values
        for columns this feature knows nothing about (``theme_root``,
        ``depth``, the provenance triple).  What this feature owns is the
        *check* and the ordering around it, so it hands back the connection
        and lets the caller's own writer — which already knows how to build
        its rows — do the writing inside the lock.

        The connection is opened read-write and its parent directory is
        created on demand, because a caller's body writes through it; an
        empty database is a legitimate state (no node is stored in it, so
        no proposal is a duplicate) and is answered rather than refused.
        """
        proposal = canonical_code_hash(proposed_code_hash)
        path = self.path
        try:
            with closing(self._connect()) as connection:
                connection.isolation_level = None
                connection.execute("BEGIN IMMEDIATE")
                try:
                    rows = connection.execute(
                        f"SELECT id, {CODE_HASH_COLUMN} FROM {NODE_TABLE} "
                        f"WHERE {CODE_HASH_COLUMN} = ? ORDER BY id",
                        (proposal,),
                    ).fetchall()
                    reject_duplicate(
                        proposal,
                        (str(row[1]) for row in rows),
                    )
                    yield connection
                    connection.execute("COMMIT")
                except BaseException:
                    # Every exit — the refusal above, a failure in the
                    # caller's body, a KeyboardInterrupt — leaves the
                    # transaction open, so roll it back before the failure
                    # propagates: a caller after this one must not inherit a
                    # locked store from a probe that did not commit.
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                    raise
        except sqlite3.Error as exc:
            raise ArtifactStoreError(
                f"the tree store at {path} could not be probed for the code "
                f"hash {proposal}: {exc}; feature 179 rejects a duplicate "
                "before it charges a trial, and a probe that could not read "
                "the stored code hashes must refuse rather than let the "
                "caller proceed to the charge"
            ) from exc

    # -- Plumbing -------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """Open the store, creating the database file's parent if needed.

        The gate writes (a caller's body does, under :meth:`probe`'s lock),
        unlike this workspace's read-only audits, so the connection is an
        ordinary read-write one over the path ``DATABASE_URL`` names — the
        connection the tree member's own writers use, which is what lets a
        caller's insert ride the probe's transaction.  A driver that cannot
        open the file raises, and every caller above translates it into this
        member's error vocabulary rather than letting a ``sqlite3``
        exception out through a seam that speaks §9.1.
        """
        path = self.path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ArtifactStoreError(
                f"could not create the directory for the tree store at "
                f"{path.parent}: {exc}"
            ) from exc
        return sqlite3.connect(path)


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into a filesystem path.

    The SQLAlchemy convention ``DATABASE_URL`` already uses across this
    workspace, restated here rather than imported so each store states its
    own contract — the same spelling the evaluator's stores, the ledger's
    and the null oracle's guard state.  A non-SQLite scheme is refused
    loudly, and a pathless (in-memory) URL is refused too: a dedup gate
    whose store died with the connection that opened it would deduplicate
    against nothing, and every duplicate would be charged.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise ArtifactStoreError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: the "
            "dedup gate speaks sqlite:/// (the spec's single-machine "
            f"allowance); point {DATABASE_URL_ENV} at a sqlite database"
        )
    if parsed.netloc not in ("", "localhost"):
        raise ArtifactStoreError(
            f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
            f"{parsed.netloc!r}"
        )
    raw = unquote(parsed.path).removeprefix("/")
    if not raw or raw == ":memory:":
        raise ArtifactStoreError(
            f"sqlite {DATABASE_URL_ENV} carries no database path: an "
            "in-memory database would die with the connection that opened "
            "it, and a dedup gate that compared against one would find no "
            "duplicate and charge every repeat"
        )
    return Path(raw)
