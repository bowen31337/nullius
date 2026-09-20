"""``p`` from a branch's true information ratio — feature 120.

app_spec.xml, "Null Oracle & Planted Nulls", feature 120: *System draws the
geometric flip depth with probability decreasing in the parent true information
ratio, which returns a distribution varying across campaigns.*  Feature 119 is
the geometric — the draw, and the store that writes ``d`` onto the branch's
parent node — and it takes ``p`` as a validated argument, deliberately:
*"What the depth is drawn from — ``p`` decreasing in the parent's true IR,
varied across campaigns — is feature 120's, and feature 120 is the module that
knows how to read a branch's true information ratio and turn it into a
probability."*  This is that module.

**Three claims, and which of them is new here.**  The sentence says three things
and they are worth separating, because two are already fixed elsewhere:

* *"draws the geometric flip depth"* — feature 119's, imported rather than
  reproduced.  This module computes a probability and hands it to
  :meth:`~nulloracle.flipdepth.FlipDepth.persist`; the inversion, the seed, the
  column the depth lands on and the refusals on ``p`` are all feature 119's, and
  none of them is restated here.
* *"probability decreasing in the parent true information ratio"* — this
  module's map, :func:`probability_from_true_ir`, and the whole of §7.3's design
  argument.  docs/nullius-tech-architecture.md §7.3 spells the draw as
  ``d ~ Geometric(p)`` with *"p decreasing in the parent's TRUE ir → strong
  mechanisms support more refinement before exhausting"*, and
  docs/alpha-engine-prd.md §4.1.2 states the consequence in the currency that
  matters: *"a constant ``d`` teaches the policy 'always stop at depth 4,' which
  is worth nothing."*  A ``p`` that did not fall as the parent's true edge rose
  would decouple the stopping test from branch quality, and the flip depth would
  stop measuring anything a policy could learn from.
* *"which returns a distribution varying across campaigns"* — this module's
  campaign draw, :func:`campaign_offset`, and the part a plausible-looking
  implementation gets wrong.  §7.3's last line is an instruction, not a remark:
  *"Vary ``p`` across campaigns."*  So the probability is not a function of the
  true IR alone: each campaign carries a shift drawn from its own id, and two
  campaigns holding branches of *identical* true IR draw from *different*
  distributions.  Without that, every campaign in the pool is one world
  re-labelled, and a policy tuned on one transfers to all of them for the wrong
  reason — which is the homogeneity §7.3's world pool exists to avoid.

**Why a logistic, and why its asymptotes are strictly inside ``(0, 1)``.**  §7.3
fixes the shape — decreasing — and the shape leaves the codomain open: an
inverse, an exponential and a clipped line all decrease.  What picks the
logistic is the boundary feature 119 draws around ``p``.  Feature 119 refuses a
``p`` outside the *open* interval ``(0, 1)`` — a ``p`` of 1 collapses the
geometric to a constant depth of 1 and a ``p`` of 0 makes its mean ``1/p``
unbounded — and it refuses rather than clamps, because *"a clamped probability
would be a probability no campaign was designed with."*  A map whose codomain
included 0 or 1 would therefore hand this module's own caller a value feature
119 must refuse: the two features would disagree about what a probability is,
and the disagreement would surface as an exception on a perfectly ordinary
branch — an unboundedly strong mechanism, say.  The logistic onto
``[PROBABILITY_FLOOR, PROBABILITY_CEILING]`` has neither endpoint inside the
forbidden set, so ``p`` is a genuine probability for *every* finite true IR and
feature 119's open-interval refusal can never fire from a legitimate draw.  The
guarantee is structural, the same way the geometric's support ``{1, 2, 3, …}``
is what makes *"every root stays real"* structural rather than validated: a
root sits at depth 0, and a support that starts at 1 cannot reach it.

The extremes are handled rather than hoped for.  The stable form of the logistic
is evaluated with a branch on the exponent, so a very strong mechanism lands on
the floor and a very weak one on the ceiling instead of raising the library's
``OverflowError`` out of the middle of a campaign loop — and both endpoints are
still strictly inside ``(0, 1)``, which is what keeps feature 119's guarantee
intact at the boundary and not only in the interior.

**The true IR is an argument, not a column, and that is the information barrier
talking.**  ``true_ir`` is the planted world's own knowledge of how much real
edge a branch's mechanism has.  §4.2 gives ``is_null`` to exactly one component
— the replay scorer — and the same discipline governs the ground truth beside
it: the null labels live in §7.1's sealed sidecar, and the true IR that decided
where a branch flips lives in the campaign loop's hands.  It is **not** a stored
column, and this module does not invent one.  ``node`` carries ``ir_standalone``
and ``ir_marginal``, and both are *measured* quantities the agent's own
evaluation produced — reading either as though it were the true IR would hand
the search the oracle's answer key and turn the detectability test into a
tautology.  So the true IR arrives as an argument from the caller that holds the
world, exactly as feature 117's workspace count and feature 119's ``p`` do, and
this module never reads it from a database.

**The campaign is read, not trusted.**  The shift that varies the distribution
across campaigns is a fact about a campaign, so :meth:`TrueIRFlipDepth.draw`
takes it from the node's own ``campaign_id`` — feature 97's column on the row
the discovery loop created — rather than from an argument a caller could get
wrong.  A caller-supplied campaign id that disagreed with the row's would vary
the distribution by the wrong campaign, and the drift would be invisible: the
depth would persist and resolve like any other.  Two store-contract facts are
refused by name on the way, in the spelling every store in this member uses: a
node the table does not hold, and a campaign the table does not hold.  The
checks are reads, not creates — the node is created by the discovery loop and
the campaign by its planner, both before any flip is drawn.

**The campaign must be the type that has flips.**  §7.3: *"Campaigns are
homogeneous in null type"*, and only the Type-D regime has a flip depth at all —
a Type-R branch's null-ness is a root selection inherited by the whole subtree,
and §7.3's ``p_from_true_ir`` appears in the Type-D branch of its pseudocode and
nowhere else.  So ``campaign.campaign_type`` is confirmed to be ``'Type-D'``
before a depth is drawn, and any other type is refused with the type named.  The
refusal is not pedantry: feature 121 resolves Type-D requests and refuses a
Type-R node by name, so a flip drawn onto a Type-R branch would be a depth
written down that no read path would ever serve — a boundary in a world that has
none, and a Type-B failure count measuring a flip that never happened.

**What is returned, and why it is a value rather than a number.**  The sentence
ends *"which returns a distribution varying across campaigns"*, so the read path
returns the distribution rather than only the probability:
:class:`FlipDepthDistribution` carries the campaign, the parent's true IR, the
campaign's drawn shift, and the probability the two produce together, and it
refuses to exist if its own fields disagree.  A pair of campaigns that differ
only in a shift is then *legible* as differing rather than merely unequal, which
is the whole of "varying across campaigns": an auditor can say which campaign
moved the distribution and by how much.

**Stdlib only, and import-cheap.**  ``math``, ``sqlite3``, ``os``,
``contextlib`` and ``urllib.parse``; no third-party import at module scope, so
the factory's scan — which imports this package to fire its ``@register`` —
pays nothing for this module, the same discipline feature 117's, feature 119's
and feature 121's stores state and for the same reason: the member already
defers ``cryptography`` to first use, and a store that pulled a driver in at
import would undo that.  The generator behind :func:`campaign_offset` is
imported where it is used, as feature 119's uniform is.
"""

from __future__ import annotations

import math
import os
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .assignment import normalize_node_id
from .errors import KsGuardError
from .flipdepth import FlipDepth

__all__ = [
    "CAMPAIGN_SPREAD",
    "CAMPAIGN_TABLE",
    "DATABASE_URL_ENV",
    "NODE_TABLE",
    "PROBABILITY_CEILING",
    "PROBABILITY_FLOOR",
    "TRUE_IR_MIDPOINT",
    "TRUE_IR_SCALE",
    "TYPE_D_CAMPAIGN_TYPE",
    "FlipDepthDistribution",
    "TrueIRFlipDepth",
    "campaign_as_seed",
    "campaign_offset",
    "draw_flip_depth",
    "flip_depth_distribution",
    "probability_from_true_ir",
]

#: The environment variable naming the relational store — the one spelling
#: every store in this workspace already uses (the ledger's, the guard's, the
#: verdict's, the fraction's, the flip depth's, the resolution's), restated here
#: so each store states its own contract and none imports another's.
DATABASE_URL_ENV = "DATABASE_URL"

#: The tree store's node table — feature 97's, the table the branch's row lives
#: on and the table this store reads the node's campaign from.  Spelled once
#: here, beside the read that uses it, so this module and the migration cannot
#: drift apart on what the node table is called; the same spelling
#: :mod:`nulloracle.flipdepth` and :mod:`nulloracle.resolution` state for the
#: same reason — all three join the same rows.
NODE_TABLE = "node"

#: The campaign table — named so the store can read a node's campaign and
#: confirm it is a Type-D campaign before a flip depth is drawn.  Spelled once
#: here, and once in :mod:`nulloracle.phi`, :mod:`nulloracle.ksguard`,
#: :mod:`nulloracle.verdict`, :mod:`nulloracle.flipdepth` and
#: :mod:`nulloracle.resolution`, so the writers and readers of the campaign row
#: cannot drift apart on what the campaign table is called.
CAMPAIGN_TABLE = "campaign"

#: The campaign type this probability is for — §7.3's stopping-test regime, the
#: one whose null-ness is a depth rather than a root inheritance and therefore
#: the only one a flip depth exists in.  The value
#: ``migrations/versions/0111_campaign_table.py`` documents and the campaign's
#: planner writes; spelled once here so the gate and the refusal share one
#: spelling of the regime they require.
TYPE_D_CAMPAIGN_TYPE = "Type-D"

#: The logistic's lower asymptote — the probability a branch of unbounded true
#: information ratio is drawn with, and with it the deepest a flip can be drawn
#: on average (``1 / PROBABILITY_FLOOR = 20``).  Strictly greater than 0 so that
#: feature 119's open lower bound is never reached: a ``p`` of exactly 0 makes
#: the geometric's mean ``1/p`` unbounded, and feature 119 refuses it rather
#: than clamping it.
PROBABILITY_FLOOR = 0.05

#: The logistic's upper asymptote — the probability a branch with no true edge
#: at all is drawn with, and with it the shallowest a flip can be drawn on
#: average (``1 / PROBABILITY_CEILING ≈ 1.05``, i.e. essentially at the first
#: refinement).  Strictly less than 1 for feature 119's reason at the other end:
#: a ``p`` of exactly 1 collapses the geometric to a constant depth of 1, which
#: is the "always stop at depth 1" docs/alpha-engine-prd.md §4.1.2 warns teaches
#: the policy nothing.
PROBABILITY_CEILING = 0.95

#: The true information ratio at which the logistic is at its midpoint, i.e. the
#: ratio of a mechanism with no edge.  Zero rather than a positive number
#: because the true IR is signed — an information ratio on the same axis feature
#: 80's ``ir_standalone`` and feature 83's ``ir_marginal`` are measured on — and
#: a branch whose mechanism is genuinely worthless is the natural centre of the
#: map.  At ``true_ir = 0`` and no campaign shift, ``p`` is
#: ``(PROBABILITY_FLOOR + PROBABILITY_CEILING) / 2 = 0.5``: a mean flip depth of
#: 2.
TRUE_IR_MIDPOINT = 0.0

#: How far, in true-IR units, a branch must move from :data:`TRUE_IR_MIDPOINT`
#: for the logistic to advance one step toward an asymptote.  ``0.5`` puts a
#: mechanism at ``true_ir = 0.5`` (a respectable standalone information ratio)
#: at ``p ≈ 0.29`` and one at ``1.5`` at ``p ≈ 0.09`` — mean flip depths of
#: about 3.4 and about 10.8, deep enough that a strong mechanism supports
#: several refinements before its branch exhausts, which is the whole of §7.3's
#: *"strong mechanisms support more refinement before exhausting."*
TRUE_IR_SCALE = 0.5

#: How far, in true-IR units, a campaign's shift may move the map.  One
#: :data:`TRUE_IR_SCALE` step in either direction, so two campaigns holding
#: branches of the same true IR draw from distributions differing by up to two
#: logistic steps — at ``true_ir = 1.0``, a ``p`` of about ``0.29`` in the
#: unshifted case and about ``0.09`` at the far end, i.e. mean flip depths of
#: about 3.4 and about 10.8.  Large enough that §7.3's *"Vary ``p`` across
#: campaigns"* is a real variation rather than a rounding difference, and
#: bounded so that the campaign's shift never dominates the parent's true edge:
#: within a campaign the ordering by true IR is exactly preserved, so a strong
#: mechanism still supports more refinement than a weak one in *every* campaign.
CAMPAIGN_SPREAD = 0.5

#: The exponent at or above which the stable logistic takes its asymptote
#: instead of evaluating ``math.exp``, which raises ``OverflowError`` rather
#: than returning ``inf`` past this point.  Kept beside the map that needs it so
#: the boundary is stated once and not re-derived at each call site; the value
#: is far past any ratio this system produces, and the branch exists so that a
#: preposterous one lands on :data:`PROBABILITY_FLOOR` — still a genuine
#: probability — rather than raising out of the middle of a campaign loop.
_EXP_LIMIT = 709.0


def probability_from_true_ir(
    true_ir: Any, *, campaign_offset: Any = 0.0
) -> float:
    """§7.3's ``p``: a probability **decreasing** in the parent's true IR.

    The whole of feature 120's map in one call — ``p`` falls monotonically from
    :data:`PROBABILITY_CEILING` toward :data:`PROBABILITY_FLOOR` as the branch's
    true information ratio rises, which is §7.3's *"p decreasing in the parent's
    TRUE ir → strong mechanisms support more refinement before exhausting."*  The
    geometric's mean is ``1/p``, so a strong mechanism flips deep and keeps
    refining while a mechanism with no real edge flips almost at once: the
    stopping test gets harder exactly where the world is more worth exploring.

    ``campaign_offset`` is the campaign's own shift — the number
    :func:`campaign_offset` draws from a campaign's id — added to the true IR
    before the map is applied.  It is a keyword argument with a neutral default
    so the pure map is testable on its own, and it is *added* rather than
    multiplied so that monotonicity in ``true_ir`` survives it exactly: for a
    fixed campaign the shift is a constant, so ``p`` is still decreasing in the
    parent's true IR in every campaign — strictly so across the range a ratio
    actually occupies, and flat only at the asymptote beyond it — whatever shift
    that campaign drew.  §7.3's two instructions — decreasing in the true IR,
    varying across campaigns — are therefore satisfied together rather than
    traded off against each other.

    The returned value always lies in
    ``[PROBABILITY_FLOOR, PROBABILITY_CEILING]``, which is strictly inside
    feature 119's open interval ``(0, 1)``.  That is the point of the asymptotes
    rather than a side effect: feature 119 refuses a ``p`` of 0 or 1 rather than
    clamping it, so a map that could reach either would hand a perfectly
    ordinary branch — one with an unbounded true IR, or a worthless one — a
    probability its own draw must refuse.  Here the codomain cannot reach the
    forbidden endpoints, so the two features never disagree about what a
    probability is.

    Refuses, and names what it refuses:

    * a ``true_ir`` that is a bool — ``True`` and ``False`` are not information
      ratios, and a truthy-looking ``True`` would be mapped as the ratio ``1``;
    * a ``true_ir`` that is not a real number — an information ratio is a real;
    * a ``true_ir`` that is not finite — ``nan`` compares false against every
      bound the map applies and ``inf`` would sit past the asymptote the map is
      meant to approach, so either would draw a depth no campaign designed;
    * a ``campaign_offset`` that is not a finite real, for the same reasons: it
      is an IR-unit shift, and a shift that is not one moves the map nowhere a
      campaign drew.
    """
    ratio = _require_real(true_ir, "true_ir")
    offset = _require_real(campaign_offset, "campaign_offset")
    exponent = (ratio + offset - TRUE_IR_MIDPOINT) / TRUE_IR_SCALE
    if exponent >= _EXP_LIMIT:
        weight = 0.0
    else:
        weight = 1.0 / (1.0 + math.exp(exponent))
    return PROBABILITY_FLOOR + (PROBABILITY_CEILING - PROBABILITY_FLOOR) * weight


def campaign_as_seed(campaign_id: Any) -> int:
    """A campaign id as a stable integer seed for its distribution's shift.

    The campaign's shift is drawn from a seeded generator, and the seed is the
    whole of the draw's reproducibility — §12's determinism contract forbids a
    campaign whose distribution was re-drawn on every request, exactly as it
    forbids a null node whose permutation seed was re-drawn.  The seed is
    derived from the campaign's canonical UUID: the hex of the id, as an
    integer, is a stable, collision-free mapping from a campaign to a seed, so
    the same campaign always shifts its distribution the same way and two
    campaigns shift independently.  Feature 119's :func:`~nulloracle.flipdepth.
    node_as_seed` is the same mapping for the same reason; this one is spelled
    beside the shift it feeds, for a *campaign's* id rather than a node's,
    because the two seeds feed two different draws and a reader following either
    should not have to cross modules to find it.
    """
    return int(_validated_campaign_id(campaign_id).replace("-", ""), 16)


def campaign_offset(campaign_id: Any) -> float:
    """The shift a campaign's distribution carries, in true-IR units.

    §7.3's last instruction is *"Vary ``p`` across campaigns"*, and this is
    where the variation comes from: one number per campaign, drawn uniformly
    from ``[-CAMPAIGN_SPREAD, +CAMPAIGN_SPREAD]`` from a generator seeded by the
    campaign's own id, and added to every branch's true IR in that campaign
    before :func:`probability_from_true_ir` is applied.

    The draw is uniform rather than anything cleverer on purpose.  §7.3 asks for
    the distribution to *vary* across campaigns; it does not ask for the
    variation to be tuned, and a variation whose shape was itself a design
    choice would be one more thing to justify and one more way for two campaigns
    to be accidentally identical.  A shift, rather than a change of slope or of
    midpoint, because it moves the *level* of the campaign's whole distribution
    while leaving the ordering by true IR untouched — so a strong mechanism
    supports more refinement than a weak one in every campaign, and *how much*
    more is what varies.

    Two calls with the same campaign id return the same shift: the seed is the
    campaign's, so a campaign replayed next year draws the same distribution it
    drew this year (§12), and a depth re-derived during a replay matches the
    depth that was persisted.
    """
    import random

    rng = random.Random(campaign_as_seed(campaign_id))
    return (2.0 * rng.random() - 1.0) * CAMPAIGN_SPREAD


@dataclass(frozen=True)
class FlipDepthDistribution:
    """The distribution one campaign draws one branch's flip depth from.

    Feature 120's answer to *"what is the depth drawn from here?"* — the
    campaign, the branch's true information ratio, the campaign's drawn shift,
    and the probability the two produce together.  It carries the shift rather
    than only the probability for the reason feature 123's guard row carries the
    statistic and the sample sizes beside the p-value: ``p = 0.29`` in two
    campaigns is the same number reached from very different design decisions,
    and *"varying across campaigns"* is only legible if a reader can see which
    campaign moved the distribution and by how much.  This describes a
    distribution rather than reporting a draw — nothing here is random once the
    campaign is fixed — so a value holding one branch's inputs can be reported,
    compared and audited without a database.

    Constructed by :func:`flip_depth_distribution` (or by
    :meth:`TrueIRFlipDepth.distribution`) rather than by hand, and it refuses at
    construction to hold fields that disagree.  The probability is recomputed
    from the ratio and the shift the value carries, and a value whose
    ``probability`` is not what those two produce is refused by name — the same
    recompute-and-compare discipline :class:`~nulloracle.resolution.
    TypeDResolution` applies to ``real`` and :class:`~nulloracle.verdict.
    Verdict` applies to the status it pronounces, and for the same reason: this
    is the number a branch's draw will be made from, and a distribution whose
    stated probability and whose inputs disagree is not the distribution a
    branch's flip depth was drawn from.
    """

    #: The campaign whose distribution this is — the canonical UUID text of
    #: ``campaign.id``, the id the shift was drawn from.
    campaign_id: str
    #: The branch parent's true information ratio, as the campaign loop holds
    #: it.  The planted world's own fact, never a stored column (§4.2).
    true_ir: float
    #: The campaign's shift, in true-IR units — :func:`campaign_offset` of
    #: :attr:`campaign_id`, negative or positive.
    campaign_offset: float
    #: ``p`` — ``Geometric(p)``'s parameter for this branch, the value feature
    #: 119's draw takes.  Strictly inside ``(0, 1)`` for every finite ratio.
    probability: float

    def __post_init__(self) -> None:
        campaign = _validated_campaign_id(self.campaign_id)
        if campaign != self.campaign_id:
            raise KsGuardError(
                f"campaign_id {self.campaign_id!r} is not canonical UUID text "
                f"({campaign!r}); the distribution's shift is drawn from the "
                "campaign's id, and a value whose id cannot be joined to the "
                "campaign row is a distribution no campaign drew"
            )
        ratio = _require_real(self.true_ir, "true_ir")
        offset = _require_real(self.campaign_offset, "campaign_offset")
        probability = _validated_probability(self.probability)
        expected = probability_from_true_ir(ratio, campaign_offset=offset)
        if probability != expected:
            raise KsGuardError(
                f"the distribution says probability is {probability!r} but the "
                f"true IR {ratio!r} and the campaign shift {offset!r} it holds "
                f"produce {expected!r}; §7.3's p is a function of the parent's "
                "true IR and the campaign, and a distribution whose stated "
                "probability and whose inputs disagree is not the distribution "
                "a branch's flip depth was drawn from"
            )

    @property
    def mean_depth(self) -> float:
        """``1/p`` — the geometric's mean on the trial count, in days of depth.

        The figure §7.3's argument is actually about: a strong mechanism's
        branch runs for about ``1/p`` refinements before it flips, so a campaign
        whose shifts have raised ``p`` is a campaign whose branches exhaust
        sooner.  Reported beside :attr:`probability` because the two are the same
        fact in the two units an operator reasons in — a probability for the
        draw, a depth for the tree — and deriving it here keeps the division in
        one place.
        """
        return 1.0 / self.probability

    def to_payload(self) -> dict[str, Any]:
        """The distribution as a JSON-safe mapping.

        The four fields plus the derived mean, so a caller reporting *what this
        campaign draws* does not re-derive the arithmetic — and, deliberately,
        no node id and no label: none of these numbers is §7.1's secret, and a
        description of a distribution is a thing a log line or a campaign
        manifest may carry.
        """
        return {
            "campaign_id": self.campaign_id,
            "true_ir": self.true_ir,
            "campaign_offset": self.campaign_offset,
            "probability": self.probability,
            "mean_depth": self.mean_depth,
        }

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"FlipDepthDistribution(campaign_id={self.campaign_id!r}, "
            f"true_ir={self.true_ir!r}, "
            f"campaign_offset={self.campaign_offset!r}, "
            f"probability={self.probability!r})"
        )


def flip_depth_distribution(
    campaign_id: Any, true_ir: Any
) -> FlipDepthDistribution:
    """The distribution ``campaign_id`` draws a branch of ``true_ir`` from.

    Feature 120's two instructions composed in one call: the campaign's shift is
    drawn from its id, the true IR is shifted by it, and the pair is mapped to a
    probability.  No database is touched — the campaign's shift is a function of
    its *id* and nothing else — so a caller that holds the world's true IR but no
    relational store can still report the distribution it is drawing from, and
    the composed store below adds only the reads a *draw* needs.

    The campaign id is validated as a UUID before the shift is drawn, and the
    true IR as a finite real before the map is applied, so a malformed id or a
    ``nan`` is refused before anything is computed from it.
    """
    campaign = _validated_campaign_id(campaign_id)
    ratio = _require_real(true_ir, "true_ir")
    offset = campaign_offset(campaign)
    return FlipDepthDistribution(
        campaign_id=campaign,
        true_ir=ratio,
        campaign_offset=offset,
        probability=probability_from_true_ir(ratio, campaign_offset=offset),
    )


class TrueIRFlipDepth:
    """The store that draws a Type-D branch's flip depth from its true IR.

    Constructed with the database URL it reads from; :meth:`distribution`
    answers what a campaign draws without touching the database, and
    :meth:`draw` reads the node's own campaign, confirms it is the Type-D
    regime, computes the probability §7.3 fixes and hands it to feature 119's
    store, which performs the draw and writes ``node.flip_depth``.  The class
    resolves its path lazily, so constructing one performs no I/O —
    composition-time work must not touch the disk, the contract every store in
    this workspace states.

    **The split between this store and feature 119's is the whole design.**  This
    module owns *what the depth is drawn from*: which campaign, which true IR,
    which probability.  Feature 119 owns *how a geometric is drawn and
    persisted*: the inversion, the seed, the column, the refusals on ``p``.
    :meth:`draw` therefore computes ``p`` here and delegates the write there
    rather than reproducing the draw — feature 119 takes ``p`` as an argument
    precisely so that the caller owning the probability's meaning supplies it,
    and this is that caller.  The two stores restate their own schema so neither
    reaches into the other's connection; the delegation is a call, not a
    coupling.

    The store holds no scores and no labels: it reads two columns of one node
    row and one column of one campaign row, and writes nothing at all itself.
    There is no field here that could leak a label partition, deliberately — see
    :mod:`nulloracle.assignment` and §4.2.
    """

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise KsGuardError(
                f"{DATABASE_URL_ENV} must be a non-empty database URL"
            )
        self._database_url = database_url.strip()
        # Resolved on first use rather than at construction: building the store
        # is composition-time work and must not touch the disk.
        self._path: Path | None = None

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(
        cls, env: Mapping[str, str] | None = None
    ) -> TrueIRFlipDepth | None:
        """The store ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset.  Absent is not an
        error: it is a deployment without a relational store, which composes no
        true-IR flip-depth component — a discoverable state, not an exception —
        while the campaign loop that must draw §7.3's Type-D flip depths is the
        caller that must not find itself in it.
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

        Nothing is created at construction — the URL is translated (and a URL
        this member cannot speak is refused by name) the first time an operation
        needs it.
        """
        if self._path is None:
            self._path = _sqlite_path(self._database_url)
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """Open the database, ensuring the node and campaign tables exist idempotently.

        The same ``CREATE TABLE IF NOT EXISTS`` dance :mod:`nulloracle.flipdepth`
        and :mod:`nulloracle.resolution` state, restated here rather than
        imported so each store owns its own contract — a fresh database, a
        migration-created one and a store-created one all end up the same schema,
        and re-opening changes nothing.  The node table is created with feature
        97's five structural columns and the campaign table with feature 104's
        own, the DDL ``migrations/versions/0118_node_table.py`` and
        ``migrations/versions/0111_campaign_table.py`` write.

        Feature 119's ``flip_depth`` column is deliberately **not** added here.
        This store never writes it: the draw is feature 119's, performed by
        feature 119's store, which owns that column and adds it to a table that
        predates it.  This store opens what it *reads* — the node's
        ``campaign_id`` and the campaign's ``campaign_type`` — and nothing more.
        """
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        with connection:
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {NODE_TABLE} (
                    id                 UUID NOT NULL PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', abs(random()) % 4 + 1, 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
                    parent_id          UUID,
                    campaign_id        UUID NOT NULL,
                    theme_root         TEXT NOT NULL,
                    depth              INT NOT NULL
                );
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

    # -- Feature 120: the distribution --------------------------------------

    def distribution(
        self, campaign_id: Any, true_ir: Any
    ) -> FlipDepthDistribution:
        """What ``campaign_id`` draws a branch of ``true_ir`` from — no reads.

        The pure half, spelled as a method so a caller holding a store answers
        the distribution question without a second import.  No database is
        touched: the campaign's shift is a function of its id, so this is safe
        to call in a report, a log line or a plan.
        """
        return flip_depth_distribution(campaign_id, true_ir)

    def distribution_for_node(
        self, node_id: Any, true_ir: Any
    ) -> FlipDepthDistribution:
        """The distribution ``node_id``'s branch is drawn from, campaign read from the row.

        The most a caller can learn without drawing: the node's own
        ``campaign_id`` is read from the tree store — not taken from an argument
        a caller could get wrong — the campaign is confirmed to exist and to be
        the Type-D regime, and the branch's true IR is mapped through *that*
        campaign's shift.  This is the read-side twin of feature 121's
        resolution: 121 refuses a node that is not a Type-D campaign's before it
        serves a target, and this refuses one before it reports the distribution
        it would be drawn from.

        Refuses, in this order, and each refusal names what it is about:

        1. a malformed ``node_id`` or a true IR that is not a finite real
           (:class:`~nulloracle.errors.KsGuardError`) — the probability is a
           function of a true information ratio, and a value that is not one
           cannot be its argument.  The check runs before the store is
           opened, so a refused ratio leaves no connection made;
        2. a node the table does not hold, or one that names no campaign
           (:class:`~nulloracle.errors.KsGuardError`) — the distribution is a
           fact about a branch in a campaign, and a distribution that cannot be
           joined to the campaign it was drawn in is refused rather than
           invented;
        3. a campaign the table does not hold, or one whose type is not
           ``'Type-D'`` (:class:`~nulloracle.errors.KsGuardError`) — §7.3:
           campaigns are homogeneous in null type, and only the Type-D regime
           has a flip depth for a distribution to describe.
        """
        node = _validated_node_id(node_id)
        _require_real(true_ir, "true_ir")
        with closing(self._connect()) as connection:
            campaign = self._require_type_d_campaign(connection, node)
        return self.distribution(campaign, true_ir)

    # -- Feature 120: the draw ----------------------------------------------

    def draw(self, node_id: Any, true_ir: Any) -> int:
        """Draw §7.3's Type-D flip depth for ``node_id``'s branch and persist it.

        Feature 120's sentence as one call: the node's true information ratio in,
        the probability out of §7.3's map, and the geometric depth feature 119
        draws from that probability written onto the node's ``flip_depth``.  The
        campaign — and therefore the shift that makes this campaign's
        distribution differ from another's — is read from the node's own row, so
        the depth a branch gets is the depth its campaign was designed to give
        it.

        The write is feature 119's, delegated rather than reproduced: this method
        ends by calling :meth:`nulloracle.flipdepth.FlipDepth.persist` with the
        probability it computed, which performs the inversion, checks the node
        and its campaign again, writes the column and reads it back.  A depth
        this method returns is therefore a depth that landed.

        The returned depth is always ``>= 1`` — the geometric's support — so
        *"every root stays real"* survives the extra indirection: the campaign's
        shift moves the probability, never the support, and no shift this module
        can draw makes ``p`` reach 0 or 1, so it can never make the draw
        degenerate.
        """
        node = _validated_node_id(node_id)
        _require_real(true_ir, "true_ir")
        with closing(self._connect()) as connection:
            campaign = self._require_type_d_campaign(connection, node)
        probability = self.distribution(campaign, true_ir).probability
        return FlipDepth(self._database_url).persist(node, probability)

    def _require_type_d_campaign(
        self, connection: sqlite3.Connection, node: str
    ) -> str:
        """The node's campaign id, once it is confirmed to be a Type-D one.

        The node's own ``campaign_id`` — feature 97's column on the row the
        discovery loop created — read rather than taken from the caller, because
        the shift that varies the distribution is a fact about the campaign and
        a caller-supplied id that disagreed with the row would vary it by the
        wrong campaign, invisibly: the depth would persist and resolve like any
        other.  §7.3's homogeneity rule is enforced on the way past — a campaign
        of any other type has no flip depth for a distribution to describe — and
        both refusals name the fact they are about, in the spelling every store
        in this member uses for the same two checks.
        """
        cursor = connection.execute(
            f"SELECT campaign_id FROM {NODE_TABLE} WHERE id = ?", (node,)
        )
        try:
            row = cursor.fetchone()
        finally:
            cursor.close()
        if row is None:
            raise KsGuardError(
                f"the node table holds no row for {node!r}; §7.3's Type-D flip "
                "depth is fixed *per branch*, so a probability that cannot be "
                "joined to the branch's parent node is refused rather than "
                "drawn against a row this store would have to invent — the node "
                "is created by the discovery loop, before any flip is drawn"
            )
        if row[0] is None:
            raise KsGuardError(
                f"node {node!r} names no campaign; §7.3's Type-D flip depth is "
                "a fact about a node in a campaign, and a distribution whose "
                "node belongs to no campaign is a distribution that hangs off "
                "nothing"
            )
        campaign = _validated_node_id(row[0])
        cursor = connection.execute(
            f"SELECT campaign_type FROM {CAMPAIGN_TABLE} WHERE id = ?",
            (campaign,),
        )
        try:
            found = cursor.fetchone()
        finally:
            cursor.close()
        if found is None:
            raise KsGuardError(
                f"the campaign table holds no row for {campaign!r}, the "
                f"campaign node {node!r} belongs to; §7.3's Type-D flip depth "
                "is a fact about a node in a campaign, and a distribution that "
                "cannot be joined to the campaign its node belongs to is "
                "refused rather than drawn against a campaign this store would "
                "have to invent"
            )
        found_type = found[0]
        if found_type != TYPE_D_CAMPAIGN_TYPE:
            raise KsGuardError(
                f"campaign {campaign!r} is a {found_type!r} campaign; §7.3's "
                f"flip depth is the {TYPE_D_CAMPAIGN_TYPE!r} regime (campaigns "
                "are homogeneous in null type), and a flip drawn in a "
                f"{found_type!r} campaign would be a depth written down that no "
                "resolution would serve — the branch's null-ness lives in the "
                "sidecar, not in a flip"
            )
        return campaign


def _require_real(value: Any, label: str) -> float:
    """Refuse a value that is not a finite real, by name.

    The one check every number this module takes has to pass: a true information
    ratio and a campaign shift are both reals, and a bool, a string or a
    non-finite float is none of them.  ``nan`` is refused alongside ``inf``
    rather than falling through, because ``nan`` compares false against every
    bound the map applies — a ``nan`` ratio would take the else-branch of every
    comparison and draw a depth from a number nobody measured.  The ban on bools
    is the one feature 117 and feature 119 both state for their own arguments:
    ``True`` and ``False`` are ints in Python and are not quantities, and a
    truthy-looking ``True`` would be mapped as the ratio ``1``.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise KsGuardError(
            f"{label} must be a real number, got {type(value).__name__} "
            f"({value!r}); §7.3's p is decreasing in the parent's true "
            "information ratio, and a value that is not a real is not a ratio "
            "for a probability to be drawn from"
        )
    number = float(value)
    if not math.isfinite(number):
        raise KsGuardError(
            f"{label} must be a finite real, got {number!r}; the logistic that "
            "turns a true information ratio into a probability compares its "
            "argument against bounds, and nan compares false against every one "
            "of them while inf would sit past the asymptote the map is meant to "
            "approach"
        )
    return number


def _validated_probability(value: Any) -> float:
    """Refuse a value that is not a genuine probability in the open ``(0, 1)``.

    The same interval feature 119 validates its own ``p`` against, restated here
    rather than imported because this module refuses the value as a
    *distribution's* field rather than as a draw's argument.  A probability of
    exactly 1 collapses the geometric to a constant depth of 1 and one of exactly
    0 never terminates, so both are refused at the value's construction as well
    as at the draw — the value is what a caller carries around, and a
    distribution holding a probability its own draw would refuse is not a
    distribution a branch's flip depth was drawn from.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise KsGuardError(
            f"probability must be a real number in (0, 1), got "
            f"{type(value).__name__} ({value!r}); §7.3's flip depth is drawn "
            "from a geometric of probability p, and p is a probability"
        )
    number = float(value)
    if not math.isfinite(number) or number <= 0.0 or number >= 1.0:
        raise KsGuardError(
            f"probability must be strictly inside (0, 1), got {number!r}; a "
            "geometric of probability 1 collapses to a constant flip depth of "
            "1 and one of probability 0 never terminates, and §7.3's map holds "
            "itself strictly inside the interval so that neither can be drawn"
        )
    return number


def _validated_node_id(value: Any) -> str:
    """Validate a node id, returning it in canonical UUID text.

    Delegates to :func:`~nulloracle.assignment.normalize_node_id` — the one
    spelling this member has for *an id that joins the tree store's ``node.id``*
    — but re-raises its refusal as :class:`~nulloracle.errors.KsGuardError`.  The
    distinction is the taxonomy's: a malformed id handed to the *flip-depth*
    store is a store-contract failure, not a sidecar-schema one, and a caller
    reading ``SidecarError`` out of a true-IR draw would look in the wrong module
    for the cause.  The fraction's, the guard's, the verdict's, the flip depth's,
    the resolution's and this module's stores share the same id kind and the same
    error, so a node whose flip depth is drawn and a node whose flip is resolved
    are validated identically.
    """
    try:
        return normalize_node_id(value)
    except Exception as exc:
        raise KsGuardError(f"node_id {value!r} is not a UUID: {exc}") from exc


def _validated_campaign_id(value: Any) -> str:
    """Validate a campaign id, returning it in canonical UUID text.

    The same delegation as :func:`_validated_node_id` — a campaign id joins
    ``campaign.id`` exactly as a node id joins ``node.id``, and this member has
    one spelling for *an id that joins an id column* — with the refusal named
    for the campaign, so a caller reading the error learns which of the two
    arguments was wrong.  Spelled separately rather than parameterised, the way
    every sibling store spells its own: the message is the part a caller reads.
    """
    try:
        return normalize_node_id(value)
    except Exception as exc:
        raise KsGuardError(f"campaign_id {value!r} is not a UUID: {exc}") from exc


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into a filesystem path.

    The SQLAlchemy convention the workspace's ``DATABASE_URL`` already uses,
    restated here rather than imported so each store states its own contract.  A
    non-SQLite scheme is refused loudly — the Postgres store arrives with the
    migration member — and a pathless (in-memory) URL is refused too: an
    in-memory database dies with the connection that opened it, and a campaign's
    distribution must outlive the draw that produced it.
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
            f"sqlite {DATABASE_URL_ENV} carries no database path: an in-memory "
            "database would die with the connection that opened it, and the "
            "campaign a branch's distribution was drawn in must outlive the "
            "draw"
        )
    return Path(path)


def draw_flip_depth(
    node_id: Any,
    true_ir: Any,
    *,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> int:
    """Draw §7.3's Type-D flip depth for ``node_id``'s branch — the module-level spelling.

    Feature 120's sentence as one call: the branch's true information ratio in,
    the depth drawn from the probability §7.3 maps it to, written against the
    branch's parent node.  The store is resolved from ``database_url``, else from
    ``DATABASE_URL``; a deployment that names neither is refused *by name*
    rather than silently doing nothing, because a depth that quietly skipped its
    write would leave a branch looking undrawn while the campaign loop believed
    it had fixed the flip — the failure mode feature 119's own module-level
    spelling exists to rule out, and the reason this one repeats it.

    A :class:`~nulloracle.errors.KsGuardError` from either store propagates
    unwrapped; "the distribution could not be joined to its campaign" and "the
    depth could not be written down" are both store-contract failures and not
    computation ones.

    This is the seam the campaign loop calls, and the *only* place the true IR
    enters the system: §4.2 keeps the ground truth for exactly one component, and
    a loop that holds the world's true IRs is the caller this argument exists
    for.
    """
    source = os.environ if env is None else env
    url = (
        database_url
        if database_url is not None
        else source.get(DATABASE_URL_ENV, "").strip()
    )
    if not url:
        raise KsGuardError(
            "draw_flip_depth draws a branch's Type-D flip depth from its true "
            f"information ratio and nothing names a store: {DATABASE_URL_ENV} "
            "is unset (and no database_url was supplied), so the distribution "
            "could not be joined to its campaign and the depth could not be "
            "written down. §7.3's flip depth is a fact that must actually land "
            "on the branch's parent node — a branch whose depth silently went "
            "nowhere would look undrawn while its campaign loop believed it had "
            "fixed the flip"
        )
    return TrueIRFlipDepth(url).draw(node_id, true_ir)
