"""The campaign record, created before any node is expanded — feature 232.

app_spec.xml, "Discovery Orchestrator & Campaigns", feature 232: *System
creates a campaign record capturing type, workspace count and null fraction
before any node is expanded.*  docs/nullius-tech-architecture.md §5 states
what the record is for — *"One campaign = one discovery tree ``T_t``"*, the
unit the inner exploration loop runs against — and §4.1 fixes the three
things the record captures before the loop begins.

**This module is the writer eight other stores were built to read.**  The
``campaign`` table is not created here: ``migrations/versions/
0111_campaign_table.py`` (feature 104) creates it, and its docstring states
this feature's ordering as a fact about the table — *"the discovery
orchestrator writes the campaign record before any node is expanded (the
spec's 'before any node is expanded' ordering — the fraction is fixed at
planning time, not learned from the run)"*.  Seven stores in the null-oracle
member open that table idempotently and then **refuse to create its row**,
each in as many words:

* :mod:`nulloracle.phi` — *"``null_fraction`` is fixed before any node is
  expanded — the migration states the fraction is 'fixed at planning time,
  not learned from the run' — which is the planner's job (feature 232's
  ``discovery`` plugin), not this member's.  So this store … refuses to
  *create* the row: a store that inserted the missing campaign would be
  inventing the row the type and the workspace count belong on."*
* :mod:`nulloracle.plan` — *"the planner creates the campaign, before any
  node is expanded"*, restated in its gate's own refusal.
* :mod:`nulloracle.flipdepth`, :mod:`.irprob`, :mod:`.ksguard`,
  :mod:`.verdict`, :mod:`.selection` — the same refusal, for the same
  reason, each naming the missing campaign by id.

This module is that planner.  It is the one place in the workspace where a
row lands in ``campaign``, and the seven readers' refusals are the contract
it satisfies.

**The three captured facts, and why each is what it is.**

*``campaign_type``* — §7.3's assignment regime: Type-R (a null root
inherits its null status down the whole subtree, ~70% of campaigns) or
Type-D (every root real, a branch flips null at a randomised depth, ~30%).
The two are never mixed within one tree, and feature 122's gate reads this
very column to pronounce the ``heterogeneous_world`` refusal, so the value
is validated here against §7.3's closed set rather than stored as an
unchecked string: a campaign row carrying anything else is a declaration
the gate could not compare, and the orchestrator is the writer that must
not produce one.

*``workspace_count``* — ``W``, the well count of the discovery tree (§5
loop 1: *"``W`` parallel workers = concurrent evaluation slots"*).  It is
the caller's, taken as an argument, because the orchestrator is the caller
that knows the ``W`` it planned with.  It is validated as a genuine
positive integer — ``True`` is not a count, ``0`` divides by zero in
§4.1.1's ``2/W``, and a fractional well count is not a count.

*``null_fraction``* — §4.1.1's ``φ``, and the record's headline design
choice.  It is **derived here** from ``W`` by :func:`null_fraction`, not
taken from the caller, and that is this feature's own decision rather than
a convenience: §4.1.1 states φ *as a function of W* — *"``φ = clip(max(2/W,
0.15), 0.15, 0.35)``, W = parallel workspaces"* — and the whole blinding
discipline is built on the number being the planner's rather than a
caller's guess.  A caller-supplied φ would let a campaign be recorded with
a fraction no ``W`` produces, which is precisely the state feature 117's
store refuses to *write* onto a campaign later.  Deriving it here means
the two writers cannot disagree: there is one arithmetic, and this is the
call that runs it at planning time.

**The clip is restated here, and a cross-member test is what makes the
restatement safe.**  The workspace contract is that no member imports
another (``packages/artifacts/tests/test_profiles.py`` states it;
``packages/sandbox/tests/test_budget_law.py`` demonstrates the remedy), so
this member cannot call :func:`nulloracle.null_fraction` — and §4.1.1's
band would otherwise be spelled in two members with nothing keeping them
in step.  ``packages/discovery/tests/test_cross_member.py`` is the seam:
it imports :mod:`nulloracle.phi` in-function and asserts that
:data:`PHI_FLOOR`, :data:`PHI_CEILING` and :func:`null_fraction` agree with
this module's, value for value.  A rename or a re-clip on the null-oracle
side fails one test rather than producing a campaign whose φ and whose
``null_fraction`` column mean different things.

**The ordering law is checked against ``node``, and ``node`` is never
created here.**  Feature 232's clause is *"before any node is expanded"*,
and the honest way to check it is to read the tree: if the ``node`` table
holds a row whose ``campaign_id`` is this campaign's, a node has been
expanded and the record was not created first.  Two consequences follow,
and both are deliberate:

* the ``node`` table is **probed, never created**.  It is feature 97's
  (``migrations/versions/0118_node_table.py``), not this member's; a
  planner that created a tree table would be writing a schema it does not
  own, and the seven readers' discipline — open the table you read,
  invent nothing — is the one this member follows too.
* an **absent** ``node`` table is not a refusal.  A store that has never
  held a node is one where nothing has been expanded, which is exactly the
  state feature 232 wants a campaign created in.  The probe is a read-only
  ``sqlite_master`` lookup (:data:`_NODE_TABLE_EXISTS_SQL`, the idiom
  ``bootstrap/_census.py`` uses for its own absent-table refusal), so the
  check costs nothing when there is no tree yet.

The check and the write are **one unit of work** — a single transaction —
so a node expanded between the probe and the ``INSERT`` cannot slip past
it.  The window is closed by the transaction rather than narrowed by
ordering, because the ordering is the thing being enforced.

**Idempotent by campaign identity, because every store in this workspace
is** — and the two halves of that idempotence are different acts:

* *re-issuing the identical plan* returns the stored record, including its
  original ``created_at``.  A retry is the same planning call arriving
  twice (a reclaimed spot instance, a loop that re-ran its first step),
  and the row *is* the creation event: a retry did not move it, so the
  default's value is read back rather than re-minted.  ``calibration_status``
  stays ``'ok'`` and ``ks_pvalue`` stays ``NULL``, which is what "created
  before the KS test ran" means (feature 123's guard fills the p-value, and
  feature 124's verdict may later advance the status to ``VOID``; a re-run
  of the *planner* must not resurrect either).
* *a plan that disagrees* with the stored row is refused
  (:class:`~discovery.errors.CampaignOrderError`).  §7.3 fixes a
  campaign's declared regime at planning time and §4.1.1 fixes its ``W``,
  so a second declaration naming different ones is not an update — it is
  two campaigns wearing one id, and a world that was already planned under
  the first.  The repair is a fresh campaign id, which is why this is an
  ordering refusal and not a planning one.

The ordering check runs on the **absent-row** path only, and that
asymmetry is deliberate rather than an oversight: where a record already
exists, the ordering law was satisfied (or broken) in the past, and
re-refusing a retry would punish the retry without changing any fact about
the world.  Where no record exists, the tree is the evidence, and it is
read fresh on every such call.

**The record returned is read back from the table, not built from the
arguments.**  ``id`` is minted by the table's own default when the caller
supplies none (``0111``'s dialect-split ``gen_random_uuid()`` /
``randomblob`` v4 expression), ``created_at`` is the table's, and the two
columns this feature deliberately does *not* name are read back as the
table left them.  A record assembled from the caller's arguments would
report an id nobody stored and a ``created_at`` that is a different instant
from the row's — and features 123 and 124 write against this row by id, so
the id a planner hands back has to be the id the table holds.

**Stdlib only, and import-cheap.**  ``sqlite3`` and ``urllib.parse``; no
third-party import at module scope, so the factory's scan — which imports
this package to fire its ``@register`` — pays nothing for this module.  The
store resolves its path lazily and opens nothing until an operation needs
it, so composing an application never touches a database, and the first
:meth:`~discovery.campaign.CampaignRecords.create` is where the planning
happens.
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .errors import CampaignOrderError, CampaignPlanningError

__all__ = [
    "CALIBRATION_STATUS_DEFAULT",
    "CAMPAIGN_TABLE",
    "CAMPAIGN_TYPE_COLUMN",
    "CREATED_AT_COLUMN",
    "DATABASE_URL_ENV",
    "ID_COLUMN",
    "NODE_TABLE",
    "NULL_FRACTION_COLUMN",
    "PHI_CEILING",
    "PHI_FLOOR",
    "REGIMES",
    "TYPE_D_CAMPAIGN_TYPE",
    "TYPE_R_CAMPAIGN_TYPE",
    "WORKSPACE_COUNT_COLUMN",
    "CampaignRecord",
    "CampaignRecords",
    "create_campaign",
    "null_fraction",
]

#: The environment variable naming the relational store — the one spelling
#: every store in this workspace already uses (the ledger's, the null
#: oracle's seven, the bootstrap pool's, the repository-level conftest's),
#: restated here so this store states its own contract and imports nobody
#: else's.
DATABASE_URL_ENV = "DATABASE_URL"

#: The table the campaign row lands in — feature 104's, created by
#: ``migrations/versions/0111_campaign_table.py``.  Spelled once here, and
#: once in each of the seven null-oracle stores that read it, so the writer
#: and the readers cannot drift apart on what the campaign table is called.
CAMPAIGN_TABLE = "campaign"

#: The tree store's node table — feature 97's, created by
#: ``migrations/versions/0118_node_table.py``.  Read here for exactly one
#: question — *has anything been expanded under this campaign yet?* — and
#: never created: this member owns the campaign row's planning columns, and
#: the tree's schema belongs to the features that declare it.
NODE_TABLE = "node"

#: The campaign row's minted identity.  Read back rather than assumed when
#: the caller supplies none, because the table's own default mints it and
#: features 123 and 124 write against this row by id.
ID_COLUMN = "id"

#: The campaign row's declared regime — §7.3's type, the column feature
#: 122's gate compares the tree's assignments against.
CAMPAIGN_TYPE_COLUMN = "campaign_type"

#: The campaign row's workspace count — ``W``, the denominator of §4.1.1's
#: fraction and the well count of the discovery tree.
WORKSPACE_COUNT_COLUMN = "workspace_count"

#: The campaign row's planted-null fraction — ``φ``, derived here from ``W``
#: and stored, not left to be re-derived by every reader.  ``0111``'s
#: docstring: *"it is stored, not derived … the value that lands here is the
#: planner's, already clipped"*.
NULL_FRACTION_COLUMN = "null_fraction"

#: The campaign row's creation instant.  The row *is* the creation event,
#: and the table's default records it; a re-issued plan reads it back rather
#: than re-minting it, so a retry cannot move the moment a campaign began.
CREATED_AT_COLUMN = "created_at"

#: The campaign row's calibration verdict as the table leaves a fresh row.
#: Read back and reported, never written: feature 123's guard persists the
#: p-value and feature 124's verdict advances this column to ``'VOID'``, and a
#: planner that re-wrote either would resurrect a calibration someone else had
#: already pronounced on.
#:
#: ``'ok'`` is ``0111``'s literal default — the migration spells it as a
#: literal rather than a keyword because SQLite has no boolean keyword for a
#: text column — and it is the null-oracle member's
#: ``CALIBRATION_STATUS_OK``, which ``test_cross_member.py`` pins.  Only the
#: fresh-row value is stated here: ``'VOID'`` is feature 124's word, and a
#: planner that spelled it would be the second place that vocabulary lived.
CALIBRATION_STATUS_DEFAULT = "ok"

#: §4.1.1's clip floor — the smallest fraction a campaign plants.
PHI_FLOOR = 0.15

#: §4.1.1's clip ceiling — the largest fraction a campaign plants.
PHI_CEILING = 0.35

#: §7.3's two assignment regimes, as the closed set a declared campaign type
#: must be one of.  The values are the ones ``0111_campaign_table.py``
#: documents and the ones the null-oracle member's writers and gate compare
#: against; ``test_cross_member.py`` pins that agreement, since no member may
#: import another.
TYPE_R_CAMPAIGN_TYPE = "Type-R"
TYPE_D_CAMPAIGN_TYPE = "Type-D"
REGIMES = (TYPE_R_CAMPAIGN_TYPE, TYPE_D_CAMPAIGN_TYPE)

#: The read-only probe that answers *does this database hold a tree at all?*
#: ``sqlite_master`` is read (never the rows), which makes the check safe on
#: a database this process has no business writing to — the idiom
#: :mod:`bootstrap._census` uses for its own absent-table refusal.  A
#: parameterised statement, so the table name is a bound value rather than
#: interpolated text.
_NODE_TABLE_EXISTS_SQL = (
    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?"
)


def null_fraction(workspace_count: Any) -> float:
    """§4.1.1's planted-null fraction: ``φ = clip(max(2/W, 0.15), 0.15, 0.35)``.

    The arithmetic the record's headline number is planned with, transcribed
    from §4.1.1's own block — note the **inner ``max`` as well as the outer
    clip**, which is how the PRD writes it::

        φ = clip( max(2/W, 0.15), 0.15, 0.35 )        W = parallel workspaces

    Both halves are implemented here even though the inner ``max`` cannot
    change the answer — ``max(2/W, PHI_FLOOR)`` only engages where
    ``2/W < PHI_FLOOR`` (``W > 13``), and the outer clip already lifts that
    whole region to the floor, so the two spellings agree at every ``W``.  It
    is spelled the PRD's way anyway, for a reason that is about maintenance
    rather than arithmetic: the spec's expression is the one a reader checks
    against, and a transcription that is *equivalent* but not identical
    invites the next reader to "fix" a discrepancy that is not there.  The
    PRD also *explains* the term — §4.1.1 calls φ "a floor problem, not a rate
    problem" — so dropping it would drop the sentence's subject.

    The clip is not decoration: ``2/W`` decreases in ``W``, so a small
    campaign's fraction is held at the ceiling and a large one's lifted to the
    floor.  §4.1.1's argument for the band is that *"a tree needs at least two
    null roots and two real roots or it contributes almost nothing to either
    sensitivity or specificity"*: at ``W = 10`` a flat 0.15 yields 1.5
    expected nulls, which is too thin; at ``W = 32`` it yields 5 and is fine
    — *"0.15 is sufficient once W ≥ 16 and insufficient below it"*.

    Refuses a ``workspace_count`` that is not a genuine positive integer, and
    names what it refuses, for the same reasons
    :func:`nulloracle.null_fraction` states from the other side of the seam:

    * a ``bool`` — ``True`` and ``False`` are not counts, and a
      truthy-looking ``True`` would plan the ceiling for a "campaign" of one
      well that is not a campaign at all;
    * a non-``int`` — a fractional well count is not a count, and §5's ``W``
      is *"parallel workspaces"*, a number of them;
    * ``W < 1`` — ``W = 0`` divides by zero and ``W < 0`` is not a count, so a
      fraction computed from either would be a fraction no campaign was
      designed with.

    The returned value is always inside ``[PHI_FLOOR, PHI_CEILING]``: the clip
    is applied unconditionally, so a caller gets a fraction it can store
    without re-checking the band.  A ``2/W`` inside the band is returned
    unchanged; one outside it is clamped, which is the clip's whole purpose
    rather than an error to report — so a ``W`` whose fraction the band
    *adjusts* is accepted, and what is refused is a ``W`` that makes ``2/W``
    meaningless.
    """
    if isinstance(workspace_count, bool) or not isinstance(workspace_count, int):
        raise CampaignPlanningError(
            f"workspace_count must be a positive integer, got "
            f"{workspace_count!r} ({type(workspace_count).__name__}); §4.1.1's "
            "fraction is clip(max(2/W, 0.15), 0.15, 0.35) and W is the well "
            "count of the discovery tree — a count, and not a truthy-looking "
            "non-integer"
        )
    if workspace_count < 1:
        raise CampaignPlanningError(
            f"workspace_count must be at least 1, got {workspace_count!r}; "
            "§4.1.1's fraction is clip(max(2/W, 0.15), 0.15, 0.35), and W = 0 "
            "divides by zero while W < 0 is not a count a campaign was "
            "planned with"
        )
    raw = 2.0 / workspace_count
    # §4.1.1's expression, term for term: the inner max is the floor the PRD
    # argues for ("a floor problem, not a rate problem"), the outer clip the
    # ceiling.  The two agree with a plain clip(2/W, …) everywhere; see the
    # docstring for why the spec's spelling is the one written here.
    return min(max(raw, PHI_FLOOR), PHI_CEILING)


# -- Validation ------------------------------------------------------------------


def _validated_campaign_id(value: Any) -> str | None:
    """Validate a campaign id, returning canonical UUID text or ``None``.

    ``None`` is passed straight through, and that is the feature rather than
    a shortcut: the campaign's identity is minted by the table's own default
    when the planner does not supply one (``0111``'s ``gen_random_uuid()`` /
    ``randomblob`` v4 expression), so *"let the table mint it"* is a
    supported ask and not a missing argument.

    Anything else must be a :class:`uuid.UUID` or text ``uuid.UUID`` parses.
    The canonicalization is the one every id in this workspace gets, because
    the value joins ``node.campaign_id`` and the seven null-oracle stores'
    reads: a mixed-case key would make one campaign look like two.  A
    malformed id is refused here rather than stored, because a campaign whose
    id cannot be joined to the tree is a campaign no reader could resolve.
    """
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, str):
        text = value.strip()
        if text:
            try:
                return str(uuid.UUID(text))
            except ValueError:
                pass
    raise CampaignPlanningError(
        f"campaign_id {value!r} is not a UUID; a campaign's id is the value "
        "``node.campaign_id`` and every reader of the campaign row resolves, "
        "so an id that cannot join the tree store's key names no campaign "
        "this record could be created for"
    )


def _validated_campaign_type(value: Any) -> str:
    """Refuse a declared type that is neither of §7.3's two regimes.

    §7.3 fixes exactly two — the selection test and the stopping test — and
    feature 122's gate compares a tree's assignments against this very
    column, so a row carrying anything else is a declaration no comparison
    could trust.  The refusal names both accepted spellings rather than
    guessing at the nearest, because ``"Type R"``, ``"type-r"`` and
    ``"TYPER"`` are all one keystroke from a real regime and silently
    normalising one of them would store a declaration the gate does not
    have.
    """
    if value not in REGIMES:
        raise CampaignPlanningError(
            f"a campaign's {CAMPAIGN_TYPE_COLUMN} must be one of §7.3's two "
            f"regimes ({TYPE_R_CAMPAIGN_TYPE!r} or {TYPE_D_CAMPAIGN_TYPE!r}), "
            f"got {value!r} ({type(value).__name__}); a campaign is "
            "homogeneous in null type and feature 122's gate reads this "
            "column to say so, so a declaration that is neither regime is a "
            "row no comparison could trust"
        )
    return value


def _validated_workspace_count(value: Any) -> int:
    """Refuse a workspace count that is not a genuine positive integer.

    The same check :func:`null_fraction` applies, restated as its own
    function so the *record's* validation and the *arithmetic's* validation
    can be read separately — and so a caller passing a bad ``W`` is refused
    with the field named before any fraction is computed.  Delegating to the
    clip would work today and would leave the two roles welded together: the
    clip is §4.1.1's arithmetic, while *"a campaign records the count it was
    planned with"* is this feature's.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise CampaignPlanningError(
            f"{WORKSPACE_COUNT_COLUMN} must be a positive integer, got "
            f"{value!r} ({type(value).__name__}); W is the well count of the "
            "discovery tree, and a campaign records the count it was planned "
            "with"
        )
    if value < 1:
        raise CampaignPlanningError(
            f"{WORKSPACE_COUNT_COLUMN} must be at least 1, got {value!r}; a "
            "campaign with no wells is not a tree the inner loop could run "
            "against, and a negative count is not a count"
        )
    return value


def _validated_stored_fraction(value: Any, campaign: str) -> float:
    """Refuse a stored ``null_fraction`` that is not a fraction.

    Checked on the **read** path, where the value came out of the table
    rather than from this module's own clip, and therefore the only place a
    corrupt row is reachable.  The bounds are ``(0, 1)`` — *strictly*
    inside, both ends open — and that is deliberately **not** §4.1.1's band:

    * the band is feature 117's, and this member must not re-spell it as a
      constraint on other people's rows.  ``0111`` is the authority on the
      column and it declares no ``CHECK``; a planner that refused a
      stored ``0.10`` would be quietly tightening a schema it does not own.
    * ``(0, 1)`` is the minimal honest statement of what the column means —
      φ is *the fraction of the tree's wells that are null* — and it is the
      one bound §4.1.1's own premise supports independently of the clip:
      *"a tree needs at least two null roots and two real roots"*, so a
      campaign that is all nulls or all reals measures nothing, at either
      end.  ``clip`` always lands in ``[0.15, 0.35] ⊂ (0, 1)``, so the two
      never disagree about a fraction this member planned.

    ``bool`` is refused explicitly: ``True`` is an ``int`` in Python, and a
    truthy ``1`` would read as "every well is a null", the exact opposite of
    what a corrupted ``True`` in a ``REAL`` column means.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CampaignPlanningError(
            f"campaign {campaign!r} carries {NULL_FRACTION_COLUMN} {value!r} "
            f"({type(value).__name__}); §4.1.1's fraction is a fraction of a "
            "tree's wells, so a stored value that is not a real number is a "
            "row this record cannot report"
        )
    fraction = float(value)
    if not (0.0 < fraction < 1.0):
        raise CampaignPlanningError(
            f"campaign {campaign!r} carries {NULL_FRACTION_COLUMN} "
            f"{fraction!r}; a planted-null fraction is strictly inside (0, 1) "
            "— §4.1.1's own premise is that a tree needs at least two null "
            "roots and two real roots, so a campaign that is all nulls or "
            "all reals measures nothing, and a stored fraction at either end "
            "is a row this record refuses to report"
        )
    return fraction


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into the filesystem path it names.

    The SQLAlchemy convention the workspace's ``DATABASE_URL`` already uses,
    restated here rather than imported so each store states its own contract
    and the refusal is this member's own error class.  A non-SQLite scheme is
    refused loudly — the spec's single-machine allowance is what a stdlib
    store can speak — and a pathless (in-memory) URL is refused too: an
    in-memory database dies with the connection that opened it, and a
    campaign record must outlive the planning call that produced it, because
    the seven readers that join it and the whole replay pool that counts its
    completed trees open it in another process entirely.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise CampaignPlanningError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: this "
            "store speaks sqlite:/// (the spec's single-machine allowance); "
            f"point {DATABASE_URL_ENV} at the sqlite database the campaign "
            "table already lives in"
        )
    if parsed.netloc not in ("", "localhost"):
        raise CampaignPlanningError(
            f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
            f"{parsed.netloc!r}"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path or path == ":memory:":
        raise CampaignPlanningError(
            f"sqlite {DATABASE_URL_ENV} carries no database path: an "
            "in-memory database would die with the connection that opened it, "
            "and a campaign record must outlive the planning call that made "
            "it — the tree's nodes, the KS guard's p-value and the replay "
            "pool's census all join this row from another process"
        )
    return Path(path)


# -- The record ------------------------------------------------------------------


@dataclass(frozen=True)
class CampaignRecord:
    """One campaign's planning row, as the table holds it.

    The six fields are the whole of what feature 232's sentence captures plus
    the two the table carries beside them: ``campaign_id`` (the minted
    identity every node and every reader joins by), ``campaign_type`` (§7.3's
    regime), ``workspace_count`` (``W``), ``null_fraction`` (``φ``,
    ``clip(max(2/W, 0.15), 0.15, 0.35)``), ``calibration_status`` (``'ok'`` on a fresh
    row) and ``created_at`` (the instant the row — and therefore the
    campaign — began).  ``ks_pvalue`` is deliberately **not** a field: a
    freshly created campaign has not been read, so the column is ``NULL``,
    and a field here would invite a caller to read a p-value off a record
    the guard has not tested.  Feature 123's guard is where that number is
    read.

    Frozen, so a record that has been read back cannot be edited into a
    different campaign by a caller who kept a reference — the same
    discipline :class:`nulloracle.plan.CampaignPlan` and
    :class:`bootstrap.WorldRecord` state, and for the same reason: this value
    is the record of a decision, and a mutable one would let a caller retype
    a campaign in memory while the row said otherwise.

    Validated in :meth:`__post_init__` rather than only through the store,
    because ``dataclasses.replace`` and unpickling both rebuild instances
    past a factory's nose.  A record that exists is therefore one the
    feature's sentence could have produced.
    """

    campaign_id: str
    campaign_type: str
    workspace_count: int
    null_fraction: float
    calibration_status: str
    created_at: Any

    def __post_init__(self) -> None:
        # ``object.__setattr__`` because the dataclass is frozen: the
        # canonicalization below is normalization, not mutation of the
        # caller's values, and it is the only write this object ever takes.
        campaign = _validated_campaign_id(self.campaign_id)
        if campaign is None:
            # A record *read back* always has an identity — the table mints
            # one — so the None that :func:`_validated_campaign_id` accepts
            # on the write path is not a value a record may hold.  Refusing it
            # here is what keeps "let the table mint it" a property of the
            # *ask* rather than of a stored row.
            raise CampaignPlanningError(
                "a campaign record must carry the id the table minted; got "
                "None, which is the write path's 'let the default mint it' "
                "and not a value any stored row holds"
            )
        object.__setattr__(self, "campaign_id", campaign)
        object.__setattr__(
            self, "campaign_type", _validated_campaign_type(self.campaign_type)
        )
        object.__setattr__(
            self, "workspace_count", _validated_workspace_count(self.workspace_count)
        )
        fraction = _validated_stored_fraction(self.null_fraction, campaign)
        object.__setattr__(self, "null_fraction", fraction)
        # The status is read back rather than validated against a set: §7.4's
        # vocabulary is feature 124's (`'ok'` and `'VOID'`, and the verdict
        # module is the one place the second is spelled), and a planner that
        # refused an unknown status would be re-spelling a decision it does
        # not make.  What is checked is only that the column carried text at
        # all — a NULL status is a row `0111`'s NOT NULL forbids and this
        # member could not have written.
        if not isinstance(self.calibration_status, str) or not (
            self.calibration_status.strip()
        ):
            raise CampaignPlanningError(
                f"campaign {campaign!r} carries no calibration_status "
                f"({self.calibration_status!r}); `0111` declares the column "
                "NOT NULL DEFAULT 'ok', so a row without one is not a row "
                "this feature could have created"
            )

    @property
    def planted_nulls(self) -> float:
        """The expected number of null wells in this campaign's tree.

        ``φ · W`` — the figure §4.1.1's own argument is stated in
        (*"at W = 10 a flat 0.15 yields 1.5 expected nulls, which is too
        thin; at W = 32 it yields 5 and is fine"*), offered as a property
        because it is the number a reader actually reasons about when asking
        whether a campaign's calibration will be thin.  It is derived, never
        stored: the row holds the two facts (§4.1.1's *"stored, not
        derived"* is about ``null_fraction`` itself) and this is their
        product.
        """
        return self.null_fraction * self.workspace_count

    def row(self) -> dict[str, Any]:
        """The record as a store-shaped mapping — a fresh dict per call.

        The column names are the table's own, the same discipline
        :meth:`bootstrap.WorldRecord.row` and
        :meth:`nulloracle.plan.CampaignPlan.to_payload` state: a rendered
        mapping and a structured log record name the same things the same
        way.  ``ks_pvalue`` is absent rather than ``None``, because the
        column is not one this feature fills and reporting it as a null
        would suggest the planner had an opinion about it.
        """
        return {
            ID_COLUMN: self.campaign_id,
            CAMPAIGN_TYPE_COLUMN: self.campaign_type,
            WORKSPACE_COUNT_COLUMN: self.workspace_count,
            NULL_FRACTION_COLUMN: self.null_fraction,
            "calibration_status": self.calibration_status,
            CREATED_AT_COLUMN: self.created_at,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"{type(self).__name__}(campaign_id={self.campaign_id!r}, "
            f"campaign_type={self.campaign_type!r}, "
            f"workspace_count={self.workspace_count!r}, "
            f"null_fraction={self.null_fraction!r})"
        )


# -- The store -------------------------------------------------------------------


class CampaignRecords:
    """The store that creates a campaign's record before any node is expanded.

    Constructed with the database URL it writes to; :meth:`create` plans one
    campaign — validating the type and the workspace count, deriving
    §4.1.1's fraction, proving no node has been expanded under it, and
    inserting the row — and :meth:`get` reads one campaign's record back.
    The class resolves its path lazily, so constructing one performs no I/O:
    composition-time work must not touch the disk, the contract every store
    in this workspace states.

    The store holds no cache of the records it wrote: the row is the only
    record of what was planned, so it is the only thing an answer is drawn
    from — the same stance :class:`ledger.debit.DebitEndpoint` states for its
    own idempotence, and for the same reason.  A memo of planned campaigns
    would make "was this campaign created before its tree?" a question about
    *this process's* history rather than about the world, and the seven
    readers that join the row run in other processes entirely.
    """

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise CampaignPlanningError(
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
    ) -> CampaignRecords | None:
        """The store ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset.  Absent is not an
        error: it is a deployment without a relational store, which composes
        no campaign-records component — a discoverable state, not an
        exception — while the orchestrator that must create a campaign before
        it expands anything is the caller that must not find itself in it.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The database URL this store writes to."""
        return self._database_url

    @property
    def path(self) -> Path:
        """The SQLite file backing this store, resolved on first use.

        Nothing is created at construction — the URL is translated (and a URL
        this member cannot speak is refused by name) the first time an
        operation needs it.
        """
        if self._path is None:
            self._path = _sqlite_path(self._database_url)
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """Open the database this store reads and writes.

        The caller owns the connection; use it as a context manager to commit,
        which is what :meth:`create` does — the ordering check and the
        ``INSERT`` are one unit of work and must be one transaction.

        **No schema is created here**, and that is the inverse of every other
        store in this workspace.  The seven null-oracle stores each run
        ``CREATE TABLE IF NOT EXISTS campaign`` because they *read* a table
        the spec's migration owns and must degrade gracefully on a database
        the migration has not reached.  This store is the writer, and the
        ``CREATE`` would be exactly the wrong thing: it would let this member
        invent a campaign table whose columns are whatever this file happens
        to spell, when ``0111`` is the authority on the column list, the
        defaults and the ``NOT NULL``s.  So an unmigrated database raises
        SQLite's own ``no such table: campaign``, naming the table, rather
        than being silently given a table this member guessed at.  A
        deployment reaches this revision by running the migration, and one
        that has not is a fact an operator should read rather than a schema
        this member should improvise.
        """
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    # -- Feature 232: the create -------------------------------------------

    def create(
        self,
        campaign_type: Any,
        workspace_count: Any,
        *,
        campaign_id: Any = None,
    ) -> CampaignRecord:
        """Create one campaign's record, before any node is expanded.

        Feature 232's sentence as one call: the regime and the well count in,
        the stored campaign record out.  The steps, and why each is where it
        is:

        1. **Validate the ask.**  The type against §7.3's two regimes and the
           count as a genuine positive integer, both before anything is
           opened, so a malformed plan is refused without touching a
           database.
        2. **Derive §4.1.1's fraction** from the count by
           :func:`null_fraction` — never taken from the caller; see the
           module docstring for why the derivation is this feature's own
           decision.
        3. **Return the stored row if the campaign exists** — re-issuing the
           identical plan — or **refuse** when the plan disagrees with it.
           Both happen inside the same transaction as the insert below, so
           the answer cannot be stale.
        4. **Prove the ordering law**, on the absent-row path: refuse when
           the tree already holds a node under this campaign.  This is the
           clause feature 232 is *about*, and it is checked against the
           ``node`` table rather than against a convention.
        5. **Insert, then read back**, and return what the table holds rather
           than what the arguments said.  The minted id, the table's
           ``created_at`` and the untouched ``calibration_status`` are the
           row's, because features 123 and 124 write against that row by the
           id this call hands back.

        Refuses, in this order, each naming what it is about:

        * a type, count or id that is not the kind of value the feature's
          sentence is about (:class:`~discovery.errors.CampaignPlanningError`);
        * a re-issued plan that disagrees with the stored row
          (:class:`~discovery.errors.CampaignOrderError`) — §7.3 fixes the
          regime and §4.1.1 the count at planning time, so a second
          declaration naming different ones is two campaigns wearing one id;
        * a campaign whose tree already holds a node
          (:class:`~discovery.errors.CampaignOrderError`) — the record was
          not created before the first node was expanded;
        * a database with no ``campaign`` table, which raises SQLite's own
          ``no such table`` rather than being given a table this member
          invented — see :meth:`_connect`.

        The ordering check runs on the absent-row path only.  Where a record
        already exists the law was satisfied or broken in the past, and
        re-refusing a retry would punish the retry without changing any fact
        about the world.
        """
        campaign = _validated_campaign_id(campaign_id)
        regime = _validated_campaign_type(campaign_type)
        wells = _validated_workspace_count(workspace_count)
        fraction = null_fraction(wells)

        with closing(self._connect()) as connection, connection:
            if campaign is not None:
                stored = self._read_row(connection, campaign)
                if stored is not None:
                    return self._reissued(stored, regime, wells, fraction)
            self._require_no_expanded_node(connection, campaign)
            return self._insert(connection, campaign, regime, wells, fraction)

    def get(self, campaign_id: Any) -> CampaignRecord | None:
        """One campaign's record, or ``None`` when it is not held.

        ``None`` means *the campaign was never planned* — nothing has created
        it — which is the honest answer for an id the table does not hold.  It
        does **not** mean the read failed: an unreachable database raises, so
        a caller can never mistake a broken store for an unplanned campaign.
        The same distinction :meth:`nulloracle.phi.PlantedNullFraction.load`
        draws for the fraction column of this very row.

        The record returned is the whole row, so a caller can tell a campaign
        the KS guard has already voided (``calibration_status = 'VOID'`,
        feature 124) from a fresh one, and can read §4.1.1's fraction without
        re-deriving it.
        """
        campaign = _validated_campaign_id(campaign_id)
        if campaign is None:
            raise CampaignPlanningError(
                "get() reads one campaign's record and needs the id to read "
                "it by; got None, which is the *write* path's 'let the table "
                "mint it' and names no row"
            )
        with closing(self._connect()) as connection:
            row = self._read_row(connection, campaign)
        if row is None:
            return None
        return self._record_from_row(row)

    # -- The words ----------------------------------------------------------

    def _read_row(
        self, connection: sqlite3.Connection, campaign: str
    ) -> tuple[Any, ...] | None:
        """One campaign's row as the table holds it, or ``None`` when absent.

        Selected column by column rather than with ``SELECT *``: the order
        :meth:`_record_from_row` reads must be the order this names, and a
        migration that appends a column (features 123's and 124's writes
        already share this table) must not silently shift the fields.
        """
        cursor = connection.execute(
            f"SELECT {ID_COLUMN}, {CAMPAIGN_TYPE_COLUMN}, "
            f"{WORKSPACE_COUNT_COLUMN}, {NULL_FRACTION_COLUMN}, "
            f"calibration_status, {CREATED_AT_COLUMN} FROM {CAMPAIGN_TABLE} "
            f"WHERE {ID_COLUMN} = ?",
            (campaign,),
        )
        try:
            return cursor.fetchone()
        finally:
            cursor.close()

    def _record_from_row(self, row: tuple[Any, ...]) -> CampaignRecord:
        """Build a :class:`CampaignRecord` from a row, with the campaign named.

        The read path's one constructor, so :meth:`get` and :meth:`create`'s
        read-back cannot disagree about which column is which.  A validation
        refusal raised from the row names the campaign it came off — the row's
        id is the first field — which is the difference between an operator
        learning *this campaign's fraction is corrupt* and learning only that
        some number somewhere is not a fraction.
        """
        campaign = row[0]
        try:
            return CampaignRecord(
                campaign_id=campaign,
                campaign_type=row[1],
                workspace_count=row[2],
                null_fraction=row[3],
                calibration_status=row[4],
                created_at=row[5],
            )
        except CampaignPlanningError as exc:
            raise CampaignPlanningError(
                f"the campaign row for {campaign!r} could not be read as a "
                f"campaign record: {exc}"
            ) from exc

    def _reissued(
        self, row: tuple[Any, ...], regime: str, wells: int, fraction: float
    ) -> CampaignRecord:
        """Answer a re-issued plan: the stored record, or an ordering refusal.

        The identical plan — same regime, same count — returns the row the
        table holds, **including its original ``created_at`` and its current
        ``calibration_status``**.  A retry is the same planning call arriving
        twice (a reclaimed spot instance, a loop that re-ran its first step),
        and the row *is* the creation event: the retry did not move the
        moment the campaign began, and it certainly did not un-void a
        calibration feature 124's verdict had already pronounced on.

        A disagreement is refused, and the refusal names *both* values for
        each field that differs — ``"you asked for Type-D, the row says
        Type-R"`` is actionable in a way that ``"the plan disagrees"`` is
        not.  ``null_fraction`` is compared too, and it is the one field that
        can only differ *because* the count did: it is derived, so a fraction
        mismatch with an equal count means the stored row was written by
        something other than this arithmetic, which is worth naming
        separately rather than folding into the count's comparison.
        """
        stored = self._record_from_row(row)
        campaign = stored.campaign_id
        disagreements: list[str] = []
        if stored.campaign_type != regime:
            disagreements.append(
                f"{CAMPAIGN_TYPE_COLUMN}: the row says "
                f"{stored.campaign_type!r}, this plan says {regime!r}"
            )
        if stored.workspace_count != wells:
            disagreements.append(
                f"{WORKSPACE_COUNT_COLUMN}: the row says "
                f"{stored.workspace_count!r}, this plan says {wells!r}"
            )
        elif stored.null_fraction != fraction:
            disagreements.append(
                f"{NULL_FRACTION_COLUMN}: the row says "
                f"{stored.null_fraction!r} for {stored.workspace_count} wells, "
                f"and clip(2/{wells}, {PHI_FLOOR}, {PHI_CEILING}) is "
                f"{fraction!r} — the stored fraction is not this arithmetic's"
            )
        if disagreements:
            raise CampaignOrderError(
                f"campaign {campaign!r} already exists and this plan "
                f"disagrees with it ({'; '.join(disagreements)}); §7.3 fixes a "
                "campaign's declared regime and §4.1.1 fixes its workspace "
                "count at planning time, so a second declaration naming "
                "different ones is not an update — it is two campaigns "
                "wearing one id, and a world that was already planned under "
                "the first. Re-plan under a fresh campaign id"
            )
        return stored

    def _require_no_expanded_node(
        self, connection: sqlite3.Connection, campaign: str | None
    ) -> None:
        """Refuse when the campaign's tree already holds a node — feature 232's clause.

        The ordering law, checked against the tree itself.  A ``node`` row
        whose ``campaign_id`` is this campaign's is proof that the inner loop
        has already started expanding — §5 loop 1's ``CONTINUE(v)`` resumed a
        workspace, or a root was planted — and a record created after that is
        not the record feature 232 describes: the fraction it carries is
        supposed to be *"fixed at planning time, not learned from the run"*
        (``0111``'s own words), and a campaign whose first node predates its
        fraction was planned by nobody.

        ``campaign`` is ``None`` when the caller let the table mint the id.
        The check is then vacuous **by construction rather than by
        convenience**: a minted id is a fresh v4 UUID, so no ``node`` row can
        carry it — the tree it would be asking about does not exist yet, and
        an id nothing has ever referenced names no nodes.  Stated here
        because skipping a check silently is the kind of shortcut a later
        reader would have to re-derive, and because the vacuity has a
        premise: it holds while the id really is minted afresh by the
        table.  A caller-supplied id is checked unconditionally, which is
        the case that matters — the caller that plans a campaign under an id
        it already knows is exactly the caller that could be re-planning a
        tree that is already growing.

        An **absent** ``node`` table is not a refusal: a store that has never
        held a node is one where nothing has been expanded, which is exactly
        the state feature 232 wants a campaign created in.  The probe is
        read-only (see :data:`_NODE_TABLE_EXISTS_SQL`), because this member
        does not own the tree's schema and must not bring it into being.
        """
        if campaign is None:
            return
        if connection.execute(_NODE_TABLE_EXISTS_SQL, (NODE_TABLE,)).fetchone() is None:
            return
        cursor = connection.execute(
            f"SELECT COUNT(*) FROM {NODE_TABLE} WHERE campaign_id = ?",
            (campaign,),
        )
        try:
            row = cursor.fetchone()
        finally:
            cursor.close()
        expanded = 0 if row is None else int(row[0])
        if expanded:
            raise CampaignOrderError(
                f"campaign {campaign!r} already has {expanded} node"
                f"{'' if expanded == 1 else 's'} in the tree, so its record "
                "was not created before the first node was expanded — "
                "feature 232's ordering, and the one ``0111`` states as the "
                "reason this row exists at all: §4.1.1's fraction is *fixed "
                "at planning time, not learned from the run*, so a campaign "
                "whose tree is already growing has no planning-time fraction "
                "left to record. Create the record before the first "
                "expansion, or re-plan under a fresh campaign id"
            )

    def _insert(
        self,
        connection: sqlite3.Connection,
        campaign: str | None,
        regime: str,
        wells: int,
        fraction: float,
    ) -> CampaignRecord:
        """Insert the campaign row and read it back — the write itself.

        ``id`` is supplied only when the caller supplied one; otherwise the
        column's own default mints it (``0111``'s dialect-split
        ``gen_random_uuid()`` / ``randomblob`` v4 expression), which is why
        the ``INSERT`` has two spellings rather than one with a ``None`` in
        it: a bound ``NULL`` id would defeat the default and, on SQLite, land
        a NULL-keyed row — ``0111`` states that hazard in as many words and
        tightens the primary key to ``NOT NULL`` precisely to refuse it.

        ``campaign_type``, ``workspace_count`` and ``null_fraction`` are the
        three facts feature 232's sentence captures, and they are the only
        columns written: ``calibration_status`` takes the table's ``'ok'``
        default (so a fresh campaign is calibrated by construction, before
        the KS guard has read it) and ``ks_pvalue`` stays ``NULL`` (a
        ``NOT NULL`` there would fabricate a decisive p-value on a campaign
        the guard has not tested, which ``0111`` refuses for exactly that
        reason).

        The row is then **read back inside the same transaction** — the
        store's own answer, not the arguments' — so the returned ``id`` is
        the one the table holds and features 123 and 124 will write against,
        and an ``INSERT`` that somehow landed nothing is caught here rather
        than surfacing as a phantom campaign at the first reader.
        """
        if campaign is None:
            cursor = connection.execute(
                f"INSERT INTO {CAMPAIGN_TABLE} ({CAMPAIGN_TYPE_COLUMN}, "
                f"{WORKSPACE_COUNT_COLUMN}, {NULL_FRACTION_COLUMN}) "
                "VALUES (?, ?, ?)",
                (regime, wells, fraction),
            )
            identifier = cursor.lastrowid
            cursor.close()
            # ``lastrowid`` is a rowid, not the minted UUID, so the minted id
            # is read back by the row the insert just made rather than from
            # the cursor: the column's default is what produced it, and only
            # the table knows what that default answered.
            row = self._read_latest_row(connection, identifier)
        else:
            connection.execute(
                f"INSERT INTO {CAMPAIGN_TABLE} ({ID_COLUMN}, "
                f"{CAMPAIGN_TYPE_COLUMN}, {WORKSPACE_COUNT_COLUMN}, "
                f"{NULL_FRACTION_COLUMN}) VALUES (?, ?, ?, ?)",
                (campaign, regime, wells, fraction),
            )
            row = self._read_row(connection, campaign)
        if row is None:
            raise CampaignOrderError(
                f"the campaign row for {campaign or 'a minted id'!r} could not "
                "be read back after the insert; a campaign record must be "
                "accounted for, and a row that cannot be re-read is a record "
                "this store cannot vouch for"
            )
        return self._record_from_row(row)

    def _read_latest_row(
        self, connection: sqlite3.Connection, rowid: int | None
    ) -> tuple[Any, ...] | None:
        """The row just inserted under a minted id, read back by its rowid.

        The bridge between SQLite's ``lastrowid`` — which is the table's
        *rowid*, not the UUID the default minted — and the columns this store
        reads by.  A rowid of ``0`` or ``None`` is refused by name rather than
        queried for: ``0`` is not a valid rowid in SQLite, and a driver that
        answered ``None`` means the insert did not take, which the caller must
        hear about rather than have translated into a confusing empty read.
        """
        if not rowid:
            raise CampaignOrderError(
                "the campaign insert reported no rowid, so the minted id could "
                "not be read back; the row *is* the creation event (§4.1's "
                "planning-time fraction) and a record that cannot be re-read "
                "is a campaign this store cannot vouch for"
            )
        cursor = connection.execute(
            f"SELECT {ID_COLUMN}, {CAMPAIGN_TYPE_COLUMN}, "
            f"{WORKSPACE_COUNT_COLUMN}, {NULL_FRACTION_COLUMN}, "
            f"calibration_status, {CREATED_AT_COLUMN} FROM {CAMPAIGN_TABLE} "
            "WHERE rowid = ?",
            (rowid,),
        )
        try:
            return cursor.fetchone()
        finally:
            cursor.close()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"{type(self).__name__}(database_url={self._database_url!r})"


def create_campaign(
    campaign_type: Any,
    workspace_count: Any,
    *,
    campaign_id: Any = None,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> CampaignRecord:
    """Create one campaign's record — the module-level spelling.

    Feature 232's sentence as one call, for the caller that wants the act
    without holding a store: the regime and the well count in, the stored
    campaign record out.  The store is resolved from ``database_url``, else
    from ``DATABASE_URL``; a deployment that names neither is refused *by
    name* rather than silently doing nothing, because a planning call that
    quietly skipped its write would leave the orchestrator expanding a tree
    whose campaign does not exist — and the seven readers that join this row
    would refuse every node of it.

    A :class:`~discovery.errors.DiscoveryError` from the store is left to
    propagate unwrapped: the refusal already names the campaign and the fact,
    and re-wrapping it here would put a second message in front of the one an
    operator needs.
    """
    source = os.environ if env is None else env
    url = (
        database_url
        if database_url is not None
        else source.get(DATABASE_URL_ENV, "").strip()
    )
    if not url:
        raise CampaignPlanningError(
            "create_campaign creates a campaign record and nothing names a "
            f"store: {DATABASE_URL_ENV} is unset (and no database_url was "
            "supplied), so the campaign could not be recorded. Feature 232's "
            "record is a fact that must actually land in the table — an "
            "orchestrator that expanded a tree against a campaign nobody "
            "wrote would have every node it created refused by the stores "
            "that join this row"
        )
    return CampaignRecords(url).create(
        campaign_type, workspace_count, campaign_id=campaign_id
    )
