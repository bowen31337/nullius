"""A voided campaign carries no usable calibration, so its promotions are refused.

app_spec.xml, "Promotion & Epoch Governance", feature 298: *System rejects a
promotion when the campaign ``calibration_status`` is ``VOID``, because a void
campaign carries no usable calibration.*  Its declared parent is feature 291 —
the pre-registration store, whose rows this gate stands in front of — and
docs/nullius-tech-architecture.md §7.4 is the rule the sentence serves, quoted
here as it is written, because the block is the sentence's own:

.. code-block:: text

    if ks_pvalue < 0.05:
        campaign.calibration_status = VOID
        alert("nulls may be detectable — investigate block length")
        halt_dreaming()

    A VOID campaign is excluded from the replay pool for FDR purposes.  This
    check is cheap, and skipping it means every headline number the system
    reports could be fiction.

The PRD is where the stake is stated, and it is stated in the sharpest words
this workspace has for anything: §4.3 *"the nulls are detectable, the agent may
be learning to identify them, and the campaign's calibration is **void** — the
PRD says in the same breath to *"investigate the block length and permutation
scheme before proceeding"*, and §14's risk table files the hazard as **Fatal** —
*"Agent learns to detect planted nulls"*, mitigated by *"§4.3 KS guard every
campaign"*.  A campaign in that state has lost its **control**: the planted
nulls are no longer a population the agent fails to distinguish, so a figure
measured inside that campaign is a figure with no denominator, and the sentence
this module implements is the promotion path's half of the same discipline.

**The finding is feature 124's; this refusal is this member's, and it is a
second gate rather than a second spelling of feature 243's.**  §7.4's verdict is
pronounced and persisted by :class:`nulloracle.verdict.CampaignVerdict` (feature
124), which writes the one column — ``campaign.calibration_status`` — that this
module *reads*.  Feature 243 (``discovery.manifest.admit_completed_campaigns``)
refuses a void campaign **when adding completed campaigns to the replay pool**,
and the temptation is to treat this feature as that gate under another name.  It
is not, and the difference is the noun.  Feature 243 judges **a batch of
completed campaigns** offered to a store, and its input is a sequence of
:class:`~discovery.manifest.CampaignManifest` values the replay path holds;
this feature judges **one promotion** — §13 item 7's decision about one
hypothesis — and its input is the node being promoted, which the replay path
never holds and a manifest is not shaped to carry.  Neither gate's caller can
call the other: the promotion path holds no manifest, and the pool's add holds
no node.  So this module does **not** import feature 243, does not call it, and
does not re-derive its batch refusal — but it does restate its **code word**,
which is the one thing that must match: an operator who greps
:data:`~promotion.errors.VOID_CALIBRATION_ERROR_CODE` lands on both gates,
because both are the same finding — a void campaign, seen from two doors.

**The campaign is reached from the node, and that traversal is this module's
whole read.**  A caller promoting a hypothesis holds a **node identity** —
feature 291's key, :data:`~promotion.pre_register.NODE_ID_COLUMN` — not a
campaign identity, and nothing in this member could answer *which campaign is
this node's?* before this feature.  So the read is two columns and one join:
``node.campaign_id``, declared by ``0118_node_table`` as the link from a
hypothesis back to the campaign that spawned it, names ``campaign.id``,
declared by ``0111_campaign_table`` as that row's own primary key.  The
traversal is not incidental plumbing — it is the feature, and it is why the
gate takes a node rather than a status.  (The two names differ and are spelled
separately below for that reason: a reader who confuses the node's reference
column with the campaign's key would join one row to nothing.)

**The comparison is exact, and nothing is normalised.**  ``"VOID"`` is the
value feature 124 writes and the value ``0111``'s own docstring names; ``"void"``
and ``"Void"`` are **not** it.  Case-folding here would be this module
pronouncing a verdict it only reads — the argument feature 243 states for its
own comparison, and it binds harder on this side of the two gates: this module
has no ``p``-value, no threshold and no test, so the *only* thing it knows about
a campaign's calibration is the spelling feature 124 left on the row.  A gate
that accepted a near-miss would be inventing a verdict of its own out of a
typo, in a category where the verdict it invents is the one §14 calls Fatal.

**The node and the campaign are both required; the pre-registration is not —
and that is the one design question this feature has to answer.**  Feature 299,
this member's other act on a promotion, probes for a
``promotion_registry`` row before it writes, and calls the probe *"why this
feature's ``depends_on="291"`` is load bearing rather than bibliographic"*.  The
tempting symmetry is to inherit that probe here, and it is deliberately **not**
inherited, for a reason the member's error vocabulary states as a law: a class is
split by the *repair* the caller must make, and the two repairs are different.
An absent pre-registration is a **form** failure whose repair is *pre-register
first* (§13 item 7's ordering, and 291's and 292's vocabulary); a void campaign
is an **evidence** failure whose repair is *that campaign's calibration is gone —
re-plan it, or promote from a campaign that stands*.  A gate that checked the
registry first would answer *pre-register first* to a caller whose real problem
is that its campaign was voided — the collapse :mod:`promotion.errors` refuses
one member over, where ``VoidCampaignError`` is kept out of
``CampaignPlanningError`` for exactly this reason.

What *is* required is what the read genuinely needs, and both absences are
refused **by name** rather than left to a database error:

* **the node** — an identity the tree does not hold names no hypothesis, so
  there is no ``campaign_id`` to follow and no campaign whose calibration could
  be judged.  This is also why the node probe is not optional: ``node.campaign_id``
  is enforced by *writers*, not by a foreign key — ``0118`` states that in so
  many words — so a node row is the only thing that can answer the traversal.
* **the campaign** — a node whose ``campaign_id`` names no row in ``campaign``
  is a hypothesis whose campaign was never planned (feature 232's writer creates
  the campaign row *before any node is expanded*, per ``0111``'s own words), so
  there is no status to read.  Refused with its own repair, because "plan the
  campaign" is not "promote a different node".

Note what the second refusal is **not**: it is not the *named-empty* trap
``0107`` detail 1 states, where a stratum named and holding nothing must stay
apart from a stratum nobody named.  Here there is no third state to keep apart —
a campaign either has a row, and that row carries a status (``0111`` declares the
column ``NOT NULL DEFAULT 'ok'``), or it has none.  ``None`` is therefore not a
value this module ever judges, which is why it needs no ``_ABSENT`` sentinel and
why :func:`rejects_void_calibration` refuses a blank status rather than reading
it as one.

**The refusal raises, and that is the point.**  A promotion whose campaign is
``'ok'`` returns its status; one whose campaign is ``VOID`` **raises**
:class:`~promotion.errors.VoidCalibrationError`, the shape feature 285 takes in
the regime member and for the same reason: the caller calls this on its last
line, so the stop has to be the function's own act rather than a boolean every
caller must remember to branch on — and the caller that forgets is precisely a
promotion of a hypothesis whose calibration was voided, which is the deployment
§7.4's *"excluded for FDR purposes"* exists to stop.

**What it returns when it does not raise.**  The status it judged, not ``None``.
Feature 285 returns nothing because a coverage reading has nothing else to say;
here the answer to *may this promotion proceed?* is *yes, under this
calibration*, and the caller that wants to log or carry it does not have to read
the row a second time.  It is the value it compared, not a *derived* one: no
translation, no default, nothing the store invented.

**Nothing is written, and the absence of a second record is the design, not an
omission.**  This is where the feature differs from its sibling 299 in the only
way that matters here: 299 *persists* the reason a promotion was blocked on
coverage, because a coverage figure is a reading of a ledger that moves and the
block's evidence has to outlive it.  A void campaign's evidence is already
persisted, on the row this module just read — §7.4's ``calibration_status``
column *is* the record of the finding, and it is the authority on it.  A second
row carrying a copy of it would be a second spelling of one fact, free to
disagree with the row a reader would check: the drift ``0111``'s own docstring
warns about when it says the ``VOID`` write *"is the moment a campaign's
calibration is voided"*, singular.  So a refusal here leaves the database
exactly as it was, and the audit trail is the campaign row — which is also the
stance feature 285 takes toward its own verdict (*"a verdict is not a persist"*).

**No component, no seat, no router, no second builder.**  The member's
registered surface stays feature 291's one store, and this feature is the
sharpest case for that rule: a builder takes no arguments and is built on every
``create_app()`` call, while *which campaign is void* is a fact about a row that
no composition can supply.  A component pointed at a campaign status would have
to be constructed per campaign, which is not what the factory's protocol can
express.  So the gate is constructed from a URL by the caller that has one —
exactly as this member's other act is — the composed
``promotion`` component still answers one question, and nothing here
edits a registry, router table or app factory.

**The DDL is the migrations', never this module's.**  The read names two tables
and neither is this feature's to declare: ``node`` is ``0118``'s and ``campaign``
is ``0111``'s, so :func:`promotion.schema.bootstrap_calibration_schema` runs
*those two files'* own ``statements("sqlite")`` — loaded by path, the way their
runner loads them — and this module authors no statement of its own.  That is
the same law :mod:`promotion.schema` states for the pre-registration store, and
the reason ``MIGRATION_ORDER`` is *not* widened to carry ``campaign``: that
constant is feature 291's set — the three tables one ``INSERT`` needs — and the
suite pins its contents as a claim about that insert.  This gate's set is two
tables and its own constant, because a bootstrap that ran the pre-registration's
three would create ``epoch_ledger`` and ``promotion_registry`` for an act that
reads neither.

**Stdlib only, and import-cheap.**  ``sqlite3``, ``os``, ``contextlib`` and this
member's own modules at module scope and nothing else: no third-party import and
no import of another workspace member, so the factory's scan imports this package
for the near-nothing it always did and a refused promotion costs its caller only
the connection it already had.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path
from typing import Any

from .errors import (
    VOID_CALIBRATION_ERROR_CODE,
    PromotionError,
    PromotionStoreError,
    VoidCalibrationError,
)
from .pre_register import (
    DATABASE_URL_ENV,
    NODE_ID_COLUMN,
    _sqlite_path,
    _validated_uuid,
)
from .schema import bootstrap_calibration_schema

__all__ = [
    "CALIBRATION_STATUS_COLUMN",
    "CALIBRATION_STATUS_OK",
    "CALIBRATION_STATUS_VOID",
    "CAMPAIGN_ID_COLUMN",
    "CAMPAIGN_TABLE",
    "NODE_TABLE",
    "PromotionCalibrations",
    "campaign_calibration",
    "rejects_void_calibration",
    "rejects_void_promotion",
]

#: The ``campaign`` table — feature 232's row, created by
#: ``migrations/versions/0111_campaign_table.py``.  Spelled once here as
#: :mod:`discovery.campaign`, :mod:`discovery.manifest` and
#: :mod:`nulloracle.verdict` each spell it for their own act, and pinned against
#: the migration's own ``TABLES`` in the member's suite rather than trusted.
CAMPAIGN_TABLE = "campaign"

#: ``node``, feature 232's campaign tree, restated rather than imported, as
#: :mod:`promotion.blocking` restates it for its own ``REFERENCES`` clause: a
#: rename on the discovery side would otherwise leave this gate reading a table
#: no writer fills, which is the failure the *absent node* refusal would report
#: as a hypothesis that does not exist.
NODE_TABLE = "node"

#: The node's row key — ``id``, the primary key ``0118`` declares, and the value
#: :data:`~promotion.pre_register.NODE_ID_COLUMN` holds on the registry side.
#: Spelled separately from the campaign's key because they are different
#: columns: this one *references*, and the next one *is referenced*.
NODE_KEY_COLUMN = "id"

#: The node's **reference** to its campaign — ``0118``'s column, and the first
#: half of the traversal this feature exists to perform.  Not to be confused
#: with :data:`CAMPAIGN_KEY_COLUMN`: a join written against the wrong one would
#: look for a campaign whose primary key is a node's reference, and would answer
#: *no such campaign* for every node in the tree.
CAMPAIGN_ID_COLUMN = "campaign_id"

#: The campaign's **own** key — ``id``, which ``0111`` declares ``NOT NULL
#: PRIMARY KEY``.  Feature 232's writer mints it; feature 243's manifest carries
#: it as ``campaign_id``; this gate resolves it *from* a node and reads by it.
CAMPAIGN_KEY_COLUMN = "id"

#: The campaign row's calibration verdict — the one column §7.4 writes and the
#: one column this feature reads.  Feature 124's ``CALIBRATION_COLUMN`` and
#: feature 243's ``CALIBRATION_STATUS_COLUMN`` spell the same three words for
#: their own acts; the member's suite pins the three against ``0111``'s DDL,
#: since no import may reach them.
CALIBRATION_STATUS_COLUMN = "calibration_status"

#: §7.4's verdict as the row carries it: the campaign's planted nulls were found
#: detectable, so the campaign carries no usable calibration.  Feature 124
#: *pronounces* it (:data:`nulloracle.verdict.CALIBRATION_STATUS_VOID`),
#: ``0111``'s ``DEFAULT 'ok'`` is the state it replaces, and feature 243 compares
#: against the same four letters.  Restated here rather than imported, for the
#: reason this member restates every foreign spelling — no member imports
#: another — and restated **exactly**: see the module docstring on why nothing
#: is normalised.
CALIBRATION_STATUS_VOID = "VOID"

#: The status a campaign carries until §7.4's guard indicts it — ``0111``'s own
#: ``DEFAULT``, restated so this module names the state a *clean* campaign is in
#: rather than only the state it refuses.  It is deliberately **not** a second
#: value this module compares against: :func:`rejects_void_calibration` refuses
#: ``VOID`` and admits everything else, so a status vocabulary this member does
#: not know — a later §7.4 state, say — is not silently refused here.  This
#: constant is here to be *named*, not to be a gate.
CALIBRATION_STATUS_OK = "ok"

#: The first half of the traversal: the campaign a promoted node came from.
#: Campaigns are keyed by their own ``id`` and referenced by ``campaign_id``, so
#: this is the one join column pair, and it is spelled rather than inlined so the
#: read and the absences it refuses cannot drift apart on which column was asked.
_NODE_CAMPAIGN_SQL = (
    f"SELECT {CAMPAIGN_ID_COLUMN} FROM {NODE_TABLE} "
    f"WHERE {NODE_KEY_COLUMN} = ? LIMIT 1"
)

#: The second half: the status of the campaign the node named.  ``0111``
#: declares the column ``NOT NULL DEFAULT 'ok'``, so a row that answers here
#: always carries text — and the value is nonetheless validated on the way out,
#: because SQLite's columns are dynamically typed and a hand that reached past
#: every writer in the workspace could land a number in it.  A gate that
#: compared such a value would refuse or admit a promotion on a status nobody
#: wrote.
_CAMPAIGN_STATUS_SQL = (
    f"SELECT {CALIBRATION_STATUS_COLUMN} FROM {CAMPAIGN_TABLE} "
    f"WHERE {CAMPAIGN_KEY_COLUMN} = ? LIMIT 1"
)


# -- The verdict -------------------------------------------------------------------


def rejects_void_calibration(campaign_id: Any, calibration_status: Any) -> str:
    """Refuse a promotion whose campaign is void — feature 298's judgment.

    Takes the campaign the promotion came from and the calibration status a
    reader found on that campaign's row, and either the promotion proceeds or it
    is refused.  This is the whole of the feature's sentence — *"System rejects a
    promotion when the campaign ``calibration_status`` is ``VOID``, because a
    void campaign carries no usable calibration"* — as one comparison, and it is
    the seam for the caller that **already holds the status**: the promotion path
    that read the campaign itself, a test judging a carrier, a later feature that
    reached the row its own way.  The caller that holds only the node being
    promoted asks :meth:`PromotionCalibrations.rejects_void_promotion` instead,
    which performs this module's one traversal and then delegates here, so there
    is one comparison in the member and not two.

    **It raises** :class:`~promotion.errors.VoidCalibrationError` when the status
    is exactly :data:`CALIBRATION_STATUS_VOID`, and returns the status otherwise.
    Raising rather than answering a boolean is feature 285's argument, and it
    binds harder here: a caller that forgets to branch on a boolean promotes a
    hypothesis whose calibration was voided, which is the outcome §7.4's
    *"excluded for FDR purposes"* and §14's **Fatal** filing exist to prevent.
    The stop is the function's own act.

    **The comparison is exact.**  ``"void"``, ``"Void"`` and ``"VOID "`` are all
    *not* the verdict, and each is admitted.  Normalising would be this module
    pronouncing a finding it merely reads — it has no p-value, no threshold and
    no test, so the spelling on the row is the whole of what it knows — and here
    the invented verdict is the one §14 calls Fatal.  The one place the word is
    fixed is the verdict module (feature 124); a gate that accepted a near-miss
    would be a second place it is decided.

    **What it returns when it does not raise** is the status it judged, so the
    caller that wants to log or carry it does not read the row twice.  It is the
    value it compared and not a derived one: nothing is translated, defaulted or
    graded — a status this member has never heard of is admitted, because
    refusing an unknown status would be this gate inventing a vocabulary for a
    verdict feature 124 owns.

    Refuses, in this order, each naming what it is about and both in
    :class:`~promotion.errors.VoidCalibrationError`:

    1. a ``campaign_id`` that is not a UUID — the refusal it raises must name
       *which* campaign was void, and an identity that names no row names no
       campaign an operator could go and read;
    2. a ``calibration_status`` that is not non-empty text — there is no verdict
       to compare, and neither admitting nor refusing a promotion on a status
       nobody wrote would be honest.  A blank string is refused rather than
       treated as *not void*: the column is ``NOT NULL DEFAULT 'ok'``, so a
       blank one is a row no writer in this workspace produced.
    """
    campaign = _calibration_campaign_id(campaign_id)
    status = _validated_status(calibration_status, campaign)
    if status != CALIBRATION_STATUS_VOID:
        return status
    raise VoidCalibrationError(
        f"{VOID_CALIBRATION_ERROR_CODE}: the campaign {campaign} this promotion "
        f"came from carries {CALIBRATION_STATUS_COLUMN}="
        f"{CALIBRATION_STATUS_VOID!r}, so the promotion is refused — a void "
        "campaign carries no usable calibration. docs/nullius-tech-"
        "architecture.md §7.4 voids a campaign whose planted nulls the KS guard "
        "(feature 124) found detectable (`if ks_pvalue < 0.05`), and "
        "docs/alpha-engine-prd.md files that hazard as Fatal because it voids "
        "*all* calibration: once the agent can pick the planted nulls out, they "
        "are no longer a control, so nothing measured inside that campaign can "
        "be read as evidence for anything — including for this promotion. The "
        "finding is already persisted on the campaign row this status was read "
        "from, which is why this refusal writes nothing. What to do about it is "
        "the caller's decision, and it is a decision rather than a retry: "
        "re-plan the campaign under a fresh id (§4.1), investigate the block "
        "length and permutation scheme the guard indicted (§4.3), or promote a "
        "hypothesis from a campaign whose calibration stands (feature 298)"
    )


# -- Validation --------------------------------------------------------------------


def _translated(exc: PromotionError, what: str) -> VoidCalibrationError:
    """Re-raise a sibling's refusal in this feature's vocabulary.

    The seam rule this workspace states at every member boundary, applied
    *inside* one member — the shape :func:`promotion.blocking._translated`
    takes toward the same two validators.  Feature 291's calendar of refusals
    raises ``PromotionError`` for a malformed identity and
    ``PromotionStoreError`` for a path it cannot speak, and a caller whose single
    ``except VoidCalibrationError`` guards its promotion path must not be
    defeated by a refusal phrased for a pre-registration: it would read *the body
    was malformed* where the truth is *this promotion was refused, or could not
    be judged*, and it would go on to promote a hypothesis from a campaign
    nobody checked.  The inner message is carried through, so nothing an operator
    needs is lost — only re-framed, with the frame naming which act was being
    performed.

    ``type(exc)(...)`` is deliberately **not** used: here the class itself is the
    thing being corrected, exactly as in the blocking store's sibling.
    """
    return VoidCalibrationError(
        f"{VOID_CALIBRATION_ERROR_CODE}: the {what} could not be reached to "
        f"judge this promotion: {exc}"
    )


def _calibration_campaign_id(value: Any) -> str:
    """Return ``value`` as a campaign identity, or refuse it in *this* vocabulary.

    Feature 291's identity validator is the one spelling this member has for *an
    id that joins the tree*, and a campaign's ``id`` is the same kind of value —
    ``0111`` declares it ``UUID`` and feature 232 mints it — so the rule is
    *used* rather than restated, the same move :mod:`promotion.blocking` makes
    for a node.  What it raises is ``PromotionError``, the member's ask face, and
    that is what the wrapper is for: the refusal has to arrive as a *void
    calibration* refusal, or a caller's single ``except VoidCalibrationError``
    walks through it and the promotion proceeds.
    """
    try:
        return _validated_uuid(value, CAMPAIGN_ID_COLUMN)
    except PromotionError as exc:
        raise _translated(exc, "campaign identity") from exc


def _validated_status(value: Any, campaign: str) -> str:
    """Return ``value`` as a calibration status, or refuse what cannot be one.

    Non-empty text, stripped — the rule feature 232's :class:`CampaignRecord` and
    feature 242's :class:`CampaignManifest` each apply to the same column for
    their own reason, restated here in this feature's vocabulary because no
    member imports another and this gate must not import the discovery member to
    learn what a status is.

    The strip is the only normalisation, and it is a *rejection* rather than a
    comparison rule: ``"VOID "`` with a trailing newline is read as ``"VOID"``
    and refused, while ``"void"`` is read as ``"void"`` and admitted.  Both are
    deliberate, and they are the two halves the workspace states separately — a
    store that let whitespace make two spellings of one status would persist a
    campaign whose voidness a later reader could not group by, and a gate that
    case-folded would be pronouncing feature 124's verdict itself.  Nothing else
    is normalised: the vocabulary is §7.4's, and the one place it is fixed is the
    module that pronounces it.

    A blank value is refused rather than treated as *not void*: ``0111`` declares
    ``NOT NULL DEFAULT 'ok'``, so a row carrying one is a row no writer here
    produced, and a gate that answered *this promotion may proceed* on a status
    that states nothing would be admitting a promotion on a hole.
    """
    if not isinstance(value, str) or not value.strip():
        raise VoidCalibrationError(
            f"{VOID_CALIBRATION_ERROR_CODE}: campaign {campaign} carries no "
            f"{CALIBRATION_STATUS_COLUMN} — got {value!r} "
            f"({type(value).__name__}); feature 298 rejects a promotion when that "
            "status is "
            f"{CALIBRATION_STATUS_VOID!r}, and a status that is not text states "
            "no verdict to compare. `0111` declares the column NOT NULL DEFAULT "
            f"{CALIBRATION_STATUS_OK!r}, so a blank or missing status is a row no "
            "writer in this workspace produced — read the campaign's row with "
            "feature 232's record (or §7.4's guard, which is what writes it) "
            "rather than judging a promotion on nothing (feature 298)"
        )
    return value.strip()


# -- The gate ----------------------------------------------------------------------


class PromotionCalibrations:
    """The gate that refuses a promotion whose campaign was voided — 298's act.

    Constructed with the database URL the campaign rows live in;
    :meth:`rejects_void_promotion` is the feature's act — the node being promoted
    in, the status it judged out, or a refusal — :meth:`campaign_calibration` is
    the same traversal *without* the verdict, for a caller that wants the figure
    rather than the decision.  The class resolves its path lazily, so
    constructing one performs no I/O: composition-time work must not touch the
    disk, the contract every store in this workspace states.

    The traversal is the feature, and it is why this gate takes a **node** rather
    than a status.  A caller promoting a hypothesis holds feature 291's node
    identity; the campaign that spawned that hypothesis is one column away
    (``node.campaign_id`` → ``campaign.id``), and no store in this member
    answered *which campaign is this node's* before this one.  The pair
    :meth:`campaign_calibration` / :func:`rejects_void_calibration` is the same
    traversal-plus-verdict split the member states elsewhere: the read is this
    class's, the verdict is the pure function's, and the act
    :meth:`rejects_void_promotion` is the two of them in the order that matters.

    **It holds no cache.**  A memo of campaign statuses would make *has this
    promotion's calibration been voided?* a question about this process's history
    — and the answer moves: §7.4's guard voids a campaign *after* it completes,
    so a gate that remembered a status across a long-lived process would admit a
    promotion whose campaign was voided a minute ago.  The row is the only record
    and the only thing an answer is drawn from, which is the same stance
    :class:`~promotion.pre_register.PreRegistrations` and
    :class:`~promotion.blocking.PromotionBlocks` take toward theirs.
    """

    def __init__(self, database_url: str) -> None:
        """Wire the gate to the database the campaign rows live in.

        The URL is validated here, before any call, because it is a fact about
        the *gate* rather than about any one promotion: a URL that is not a
        non-empty string names no table, and a gate that accepted one would
        fail identically on every judgment — the wrong place for a deployment
        to discover a wiring fault.
        """
        if not isinstance(database_url, str) or not database_url.strip():
            raise VoidCalibrationError(
                f"{VOID_CALIBRATION_ERROR_CODE}: {DATABASE_URL_ENV} must be a "
                "non-empty database URL. A campaign's calibration is a column on "
                "the campaign row (feature 124's verdict), and a gate pointed at "
                "nothing has no row to read — so it could neither admit nor "
                "refuse a promotion, which is the refusal a promotion path must "
                "never receive silently (feature 298)"
            )
        self._database_url = database_url.strip()
        # Resolved on first use rather than at construction: building the gate
        # is composition-time work and must not touch the disk.
        self._path: Path | None = None

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(
        cls, env: Mapping[str, str] | None = None
    ) -> PromotionCalibrations | None:
        """The gate ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset, the way every store in
        this workspace treats its configuration.  Absent is not an error: it is a
        deployment without a relational store, and the caller that must judge a
        promotion's calibration is the caller that must not find itself in it —
        §7.4 leaves nothing to fall back on, so a caller that treats this ``None``
        as *no void campaigns found* would promote a hypothesis whose campaign is
        void.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The database URL this gate reads from."""
        return self._database_url

    @property
    def path(self) -> Path:
        """The SQLite file behind the campaign rows, resolved on first use.

        Nothing is created at construction — the URL is translated (and a URL
        this member cannot speak is refused by name, in *this* feature's
        vocabulary) the first time an operation needs it.
        """
        if self._path is None:
            try:
                self._path = _sqlite_path(self._database_url)
            except PromotionStoreError as exc:
                raise _translated(exc, "database address") from exc
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """Open the gate's database, bringing the two tables it reads up.

        One statement of intent.  :func:`promotion.schema.
        bootstrap_calibration_schema` runs the *migrations'* own
        ``statements("sqlite")`` for the two tables this act reads — ``node``
        (``0118``) and ``campaign`` (``0111``) — so this gate authors no DDL,
        spells no column of either and cannot drift from their owners.  Both are
        ``CREATE TABLE IF NOT EXISTS``, so a fresh database, a fully migrated one
        and one a store in this member created earlier all take the same path.

        **The two tables and not the pre-registration's three.**  ``node`` and
        ``campaign`` are the whole of what the traversal and the read name;
        ``epoch_ledger`` and ``promotion_registry`` are feature 291's parents and
        are not read here, so bringing them up would create tables this act has
        no business filling — the over-creation :mod:`promotion.schema` argues
        about at the other store.  A deployment that has already run the chain
        holds all of them; a deployment that has run nothing gets exactly what
        this gate needs to answer, and its own writers fill the rest.

        **The foreign keys.** ``PRAGMA foreign_keys = ON`` — this member's other
        two stores set it, and this one is where the *absence* of a constraint
        matters: ``0118`` declares ``node.campaign_id`` **without** a
        ``REFERENCES`` clause (its own docstring says the reference is enforced
        by the writer), so nothing but this gate's own probe stands between a
        node and a campaign row that does not exist.  The pragma is kept for the
        same reason the others keep it — it makes the constraint hold against a
        hand that reaches past this store with a raw connection — and the probe
        below is what makes the *repair* nameable, because no SQLite error would
        ever be raised for the missing campaign at all.

        The caller owns the connection; use it as a context manager to commit —
        though nothing here writes.
        """
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            with connection:
                bootstrap_calibration_schema(connection)
        except PromotionError as exc:
            connection.close()
            raise _translated(exc, "database") from exc
        except sqlite3.Error as exc:
            connection.close()
            raise VoidCalibrationError(
                f"{VOID_CALIBRATION_ERROR_CODE}: the database at {path} could not "
                f"be brought to the revision a calibration judgement needs: {exc}. "
                f"The {CAMPAIGN_TABLE} table is created by migrations/versions/"
                "0111_campaign_table.py and the node table by 0118_node_table.py; "
                "this gate runs those files' own statements and authors none of "
                "its own (feature 298)"
            ) from exc
        return connection

    # -- Feature 298: the judgement -----------------------------------------

    def rejects_void_promotion(self, node_id: Any) -> str:
        """Judge one promotion's calibration — feature 298's act.

        The steps, in the order they must happen:

        1. **Validate the node** before anything is opened, so a malformed
           identity is refused without touching a database and a refused call
           leaves no file behind.
        2. **Follow the traversal**: the node's ``campaign_id``, then that
           campaign's ``calibration_status``.  Each step is probed rather than
           assumed, and each absence is refused *by name* with its own repair —
           a node the tree does not hold is a different problem from a node whose
           campaign was never planned, and SQLite would raise for neither
           (``node.campaign_id`` carries no ``REFERENCES`` clause at all).
        3. **Delegate the comparison** to :func:`rejects_void_calibration`, so
           the member has one spelling of §7.4's test and this method cannot
           disagree with the pure judgment a caller may use directly.

        Returns the calendar status it cleared — *"ok"* for every campaign the
        guard has not indicted, and any other vocabulary a later §7.4 state might
        carry, since this gate refuses ``VOID`` and nothing else.  Raises
        :class:`~promotion.errors.VoidCalibrationError` when the campaign is void,
        for the reasons :func:`rejects_void_calibration` states.

        **It writes nothing.**  §7.4's finding is already on the campaign row this
        read — that row *is* the record — so a refusal here leaves the database
        exactly as it was.  A caller that wants the refusal recorded somewhere
        else is asking for a fact the workspace already holds.
        """
        node = _calibration_node_id(node_id)
        with closing(self._connect()) as connection:
            campaign = self._campaign_of(connection, node)
            status = self._status_of(connection, node, campaign)
        return rejects_void_calibration(campaign, status)

    def campaign_calibration(self, node_id: Any) -> str:
        """The calibration status of the campaign a node came from — the read.

        The feature's read *without* its verdict, for a caller that wants the
        figure rather than the decision: an operator asking what a node's
        campaign is carrying, a report enumerating campaigns by state, a later
        feature that reached the row its own way.  Deliberately a separate verb
        rather than a ``judge=False`` flag on :meth:`rejects_void_promotion` —
        one question, one spelling — and deliberately not a second ``SELECT``
        either: the traversal lives in :meth:`_campaign_of` and
        :meth:`_status_of` and both verbs go through them, so the read a refusal
        was made on and the read a caller is handed cannot diverge.

        Refuses exactly what :meth:`rejects_void_promotion` refuses on its way to
        the comparison — a malformed node, an absent node, an absent campaign, a
        status that is not text — and answers no verdict of its own: a ``VOID``
        campaign is *returned*, not raised, because this is the reading and not
        the judgment.
        """
        node = _calibration_node_id(node_id)
        with closing(self._connect()) as connection:
            campaign = self._campaign_of(connection, node)
            return self._status_of(connection, node, campaign)

    # -- The traversal, spelled once ----------------------------------------

    def _campaign_of(self, connection: sqlite3.Connection, node: str) -> str:
        """The campaign a node came from, or a refusal naming which absence.

        The first half of the traversal, and the reason this gate takes a node.
        The ``node`` row is probed rather than assumed because it is the *only*
        thing that can answer *which campaign is this node's*: ``0118`` declares
        ``campaign_id UUID NOT NULL`` with **no** ``REFERENCES`` clause — its own
        docstring says the reference is enforced by the writer — so a node naming
        a campaign is trusted by the schema and can only be checked here.

        A node the tree does not hold is refused in this class rather than in the
        registry's vocabulary, and feature 299's argument for its own probe binds
        here too: SQLite's errors name neither the node nor the table, and the
        repair is specific enough to state.  The repair is *write the node* —
        feature 232's campaign record and the discovery loop's expansion are what
        create one — which is a different repair from the next refusal's.
        """
        cursor = connection.execute(_NODE_CAMPAIGN_SQL, (node,))
        try:
            row = cursor.fetchone()
        finally:
            cursor.close()
        if row is None:
            raise VoidCalibrationError(
                f"{VOID_CALIBRATION_ERROR_CODE}: {NODE_TABLE} holds no row for "
                f"{NODE_ID_COLUMN} {node}, so this promotion names no hypothesis "
                "in the tree and there is no campaign whose calibration could be "
                f"read. {NODE_TABLE}.{CAMPAIGN_ID_COLUMN} is the link from a "
                "hypothesis back to the campaign that spawned it (§4.1), and a "
                "node the tree does not hold carries no such link — so feature "
                "298's judgement has nothing to judge. Write the node (feature "
                "232's campaign record and the discovery loop's expansion are "
                "what create one) or promote the node the tree actually holds "
                "(feature 298)"
            )
        return _validated_campaign_reference(row[0], node)

    def _status_of(
        self, connection: sqlite3.Connection, node: str, campaign: str
    ) -> str:
        """The campaign's calibration status, or a refusal naming the absence.

        The second half of the traversal.  A node whose ``campaign_id`` names no
        ``campaign`` row is a hypothesis whose campaign was never planned —
        ``0111``'s own words are that feature 232's writer creates the campaign
        row *before any node is expanded* — so there is no status to read and
        nothing about this promotion's calibration is knowable.

        Refused separately from the absent node above because the repairs differ:
        *plan the campaign* is not *write the node*, and a caller that fixed the
        wrong one would meet the same refusal again.  This is the same split
        :mod:`regime.promotion` draws between a stratum named-and-empty and a
        stratum nobody named, and for the same reason — the two absences lead to
        different acts.

        **It is not the named-empty trap, and that is worth being precise about.**
        ``0107`` detail 1 keeps *a row saying zero* apart from *no row at all*,
        and here there is no third state to keep apart: ``0111`` declares the
        column ``NOT NULL DEFAULT 'ok'``, so a campaign with a row always has a
        status.  There is no sentinel to carry and no default to read — a
        campaign is either planned, and therefore carrying a verdict, or absent.
        """
        cursor = connection.execute(_CAMPAIGN_STATUS_SQL, (campaign,))
        try:
            row = cursor.fetchone()
        finally:
            cursor.close()
        if row is None:
            raise VoidCalibrationError(
                f"{VOID_CALIBRATION_ERROR_CODE}: {NODE_TABLE} {node} names "
                f"{CAMPAIGN_ID_COLUMN} {campaign}, and {CAMPAIGN_TABLE} holds no "
                "row for it — so this promotion's calibration has never been "
                f"fixed and there is no status to judge. {CAMPAIGN_TABLE}.id is "
                "the campaign's own key and node.campaign_id is enforced by the "
                "writer rather than by a foreign key, so a node whose campaign is "
                "absent is a node whose campaign was never planned: 0111's own "
                "words are that the campaign row is written before any node is "
                "expanded. Plan the campaign (feature 232) or promote a "
                "hypothesis from a campaign that was (feature 298)"
            )
        return _validated_status(row[0], campaign)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"{type(self).__name__}(database_url={self._database_url!r})"


def _calibration_node_id(value: Any) -> str:
    """Return ``value`` as a node identity, or refuse it in this vocabulary.

    The same seam :func:`_calibration_campaign_id` draws, over the same
    validator, for the other identity this feature names: a caller whose single
    ``except VoidCalibrationError`` guards its promotion path must not be
    defeated by a pre-registration's refusal for a malformed node, because it
    would read *the body was malformed* where the truth is *this promotion was
    not judged*.
    """
    try:
        return _validated_uuid(value, NODE_ID_COLUMN)
    except PromotionError as exc:
        raise _translated(exc, "node identity") from exc


def _validated_campaign_reference(value: Any, node: str) -> str:
    """Return a node's ``campaign_id`` as a campaign identity, or refuse it.

    ``0118`` declares the column ``UUID NOT NULL``, so a stored row always holds
    a UUID — but SQLite's columns are dynamically typed and nothing constrains
    this column to a *campaign*: a hand-edited row could name a UUID no campaign
    ever carried, and the refusal for that is the next step's (*the campaign is
    absent*), not this one's.  What is checked here is only that the value is an
    identity at all, so the message a caller sees names the right problem: a
    reference that is not a UUID is a corrupt node row, while a UUID naming no
    row is a campaign that was never planned.

    The refusal deliberately keeps this feature's class and names the node it came
    off — the difference between an operator learning *this node's row is not one
    the tree could have written* and learning only that some row somewhere is
    malformed.
    """
    try:
        return _validated_uuid(value, CAMPAIGN_ID_COLUMN)
    except PromotionError as exc:
        raise VoidCalibrationError(
            f"{VOID_CALIBRATION_ERROR_CODE}: {NODE_TABLE} {node} carries "
            f"{CAMPAIGN_ID_COLUMN} {value!r} ({type(value).__name__}), which is "
            f"not the identity of a campaign. 0118 declares the column UUID NOT "
            "NULL and feature 232's writer fills it with the campaign row's key, "
            "so a node row holding something else is not a row this workspace "
            "produced — and feature 298 cannot judge a promotion whose campaign "
            "it cannot name"
        ) from exc


# -- The module-level spellings -----------------------------------------------------


def _resolved_url(
    database_url: str | None, env: Mapping[str, str] | None
) -> str:
    """The URL the module-level spellings act on, or a refusal naming the gap.

    The same seam :func:`promotion.blocking.record_block` and
    :func:`regime.ledger.read_ledger` resolve, restated in this feature's
    vocabulary: an explicit URL wins, else ``DATABASE_URL``, and a deployment
    that names neither is refused *by name* rather than silently doing nothing.
    The silence is the dangerous failure here and not the refusal, and it is more
    dangerous than at the block store: a judgment that quietly did not happen
    leaves a promotion **proceeding on no calibration at all**, which is the
    state §7.4's exclusion exists to make impossible.  A caller that must judge a
    promotion has to treat this refusal as a stop.
    """
    source = os.environ if env is None else env
    url = (
        database_url
        if database_url is not None
        else source.get(DATABASE_URL_ENV, "").strip()
    )
    if not url:
        raise VoidCalibrationError(
            f"{VOID_CALIBRATION_ERROR_CODE}: no database is named — "
            f"{DATABASE_URL_ENV} is unset (and no database_url was supplied), so "
            "there is no campaign row to read this promotion's calibration from. "
            "§7.4 excludes a void campaign's results for FDR purposes, so a gate "
            "resolved from nothing is a refusal rather than a silent no-op — an "
            "unjudged promotion is not a clean one (feature 298)"
        )
    return url


def rejects_void_promotion(
    node_id: Any,
    *,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    """Judge one promotion's calibration — the module-level spelling of 298's act.

    The feature's sentence as one call, for the caller that wants the act without
    holding a gate — the promotion path's last line before a hypothesis is
    published.  The store is resolved from ``database_url``, else from
    ``DATABASE_URL``, exactly as :func:`promotion.pre_register.PreRegistrations.
    resolve` and :func:`promotion.blocking.blocked_promotion` resolve theirs.

    A :class:`~promotion.errors.VoidCalibrationError` from the gate or the
    resolution propagates unwrapped: the refusal already names the campaign or
    the absence and states the repair, and re-wrapping it here would put a second
    message in front of the one an operator needs.
    """
    url = _resolved_url(database_url, env)
    return PromotionCalibrations(url).rejects_void_promotion(node_id)


def campaign_calibration(
    node_id: Any,
    *,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    """Read one promotion's campaign status — the module-level spelling of the read.

    For the caller that holds a URL rather than a gate: an operator asking what a
    node's campaign is carrying, a report enumerating promotions by campaign
    state.  Resolved the same way :func:`rejects_void_promotion` resolves its
    gate, so the caller that judges through one spelling and reads through the
    other is reading the row the judgment was made on.

    Answers no verdict: a ``VOID`` campaign is returned as the string it is,
    because this is the reading and not the decision.
    """
    url = _resolved_url(database_url, env)
    return PromotionCalibrations(url).campaign_calibration(node_id)
