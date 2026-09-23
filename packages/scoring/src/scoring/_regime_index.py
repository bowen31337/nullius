"""Feature 264, the regime index — the strata the blend is taken over,
keyed by regime and not by world.

app_spec.xml, "Objective Scoring & CVaR Aggregation", feature 264: *System
rejects a plain mean across regimes, indexing aggregation strata by regime
instead.*  Its dependency is feature 263, and the two sentences are one
thought split across a feature boundary: 263 states the blend
(``V^m = (1 − λ)·mean_g(V_g^m) + λ·min_g(V_g^m)``) and takes the worlds
*already grouped*; this feature is what grouping them means, and what
refuses the grouping that is not one.  prd §7.2's paragraph above the
formula is the whole reason the pair exists (docs/alpha-engine-prd.md
line 333, docs/nullius-tech-architecture.md §10.3): the paper averages —
``V^m = (1/t) Σ V_i^m`` — and *"that is correct only if worlds are
exchangeable.  Market regimes are not exchangeable."*  A mean over worlds
is therefore not a weaker version of the blend; it is a claim about the
pool that the pool does not satisfy.

**What is missing between the two laws, and what this module is.**  The
regime a world belongs to is not readable off a world score: feature 256's
:class:`~scoring.WorldScore` carries the identity, the measurement and the
objective, and no regime.  The labels are a second stream — feature 290's
census (`regime.census.assign_strata`, reached through the regime member's
own namespace, because a member never imports a member) assigns each
stored world a stratum with the causal rolling-window labeler, and answers
one ``world_id``/``stratum`` row per world.  So the seam between the two
halves is a *join*: labels on one side, scores on the other, and the
strata 263 blends over are what comes out.  :func:`regime_strata` is that
join — the feature's second clause, stated as its own verb — and
:func:`regime_aggregate` is the join composed with the blend, so the
aggregation this category actually performs is one call whose strata are
regimes by construction.

**A plain mean is reachable in exactly four ways, and all four are
refused.**  The feature's first clause is not a restatement of 263's
refusal of a non-mapping — it is a wider law, and it fires on the four
shapes that quietly average across regimes:

* **no labels at all.**  Scores with nothing to stratify them by are the
  paper's ``(1/t) Σ V_i^m`` verbatim.  This is the shape a caller reaches
  for when the census has not run yet, and it is the one ask where the
  numbers are all present and only the partition is missing — which is
  what makes it the dangerous one.
* **a scored world the census never binned.**  The pool holds ``M`` worlds
  and the ledger holds ``N < M`` labels, and the plain mean is what you
  get by averaging the ``M`` scores and reading the ``N`` labels as
  commentary.  The world that has no regime is precisely the world a mean
  swallows, and refusing it by name is the feature's teeth.
* **a labelled world no score was earned for.**  The mirror image, and the
  quieter failure: the index would omit the world, ``mean_g`` would be
  taken over a pool that is not the pool, and the blend would report a
  figure for strata it silently thinned.  Both directions are refused
  naming the world, because both end in an average over a set nobody
  chose.
* **a declared regime that holds no worlds.**  When the caller declares
  the regime vocabulary (see below) and one of its names is absent from
  the join, blending over the covered subset *is* a plain mean across the
  regimes present — and it is the §C7 hazard wearing this seam's name.
  §C7's doctrine is that a pool built in one regime is that regime
  (docs/alpha-engine-prd.md line 454: *"run six months in low-vol chop and
  your entire pool is low-vol chop"*), so the starved stratum is the fact
  that matters most and the one a subset-mean erases.  This refusal is
  what 263 cannot state from its own side — it never sees the starved
  stratum, because the index that dropped it never handed it over.

All four open with :data:`PLAIN_MEAN_CODE` (``plain_mean``), the one
greppable word naming what was rejected — the convention ``pool_frozen``
(feature 270), ``illegal_theme`` (feature 241) and ``full_history_fit``
(feature 290) already follow in this workspace.  Everything else this
module refuses is an ordinary shape refusal and carries no code: a label
carrier that is not one, a world labelled twice, a world scored twice, a
vocabulary that cannot be checked, an empty join.

**The regime vocabulary is the caller's to declare, and this module closes
nothing.**  ``strata`` is optional and defaults to ``None``, which means
*the regimes are whatever the labels name*.  A caller that knows its
vocabulary — the regime member's ``DEFAULT_STRATA``, a deployment's own
five names — may pass it, and then every label is checked against it and
every declared name must be covered by the join.  That is deliberately not
a closed set with a default: feature 283's `DEFAULT_STRATA` is an open
vocabulary, and its own module argues the case against the nearest
precedent — feature 241's legal theme set is closed and refuses near-misses
because *"choosing the space is the highest-value human input"*, while a
stratum name is not that, so *"nothing here refuses a stratum outside the
default three"*.  Closing the set here would be a second, stricter spelling
of a law one member over chose to leave open, and it would refuse the
five-stratum deployment that same paragraph says must work.  What this
module adds is the ability to *check* a declaration, which is why the
parameter exists at all: without it, a caller could hand world ids in the
``stratum`` field and get an index whose "regimes" are worlds, and nothing
would notice.

**The seams are duck-typed, and validate what they read.**  Two carriers
cross this module and neither is imported from the member that owns it:
the label rows, read by the two attributes the join needs (``world_id``
and ``stratum`` — feature 290's :class:`~regime.StratumAssignment` among
the objects that satisfy it), and the world scores, read by the two
attributes feature 263's blend reads (``world_id`` and finite ``score`` —
:class:`~scoring.WorldScore`).  The reason is the one every seam in this
member states: the module loader imports this package under a synthetic
name and re-executes it, so the objects composition hands out may be
second class objects of the right shape, and an ``isinstance`` would
refuse the very carriers the composed process produces.  What the seams
read they validate, and the identity laws the join's arithmetic depends on
are enforced from this side rather than trusted to the census: a world
labelled twice, a world scored twice, either half of the coverage mismatch,
and a label that is not a name are all refused here naming the world, on
the principle that a partition a caller assembled is data and not a
promise.

**The answer is a plain mapping, and that is a decision.**  Feature 263
answers a frozen :class:`~scoring.AggregatedObjective` because the blend
has terms, a λ and an audit trail to carry; the index has none of that —
it *is* the mapping 263's verb takes, and a wrapper would need unwrapping
at the one call site that consumes it.  :func:`regime_strata` therefore
answers a fresh ``dict`` of stratum name to a tuple of the caller's score
carriers, sorted by name and by world id inside each name, never aliased
to either input: the determinism law the per-world score states (docs
§10.1) is fixed at the index as well as at the blend, so two callers who
assembled the same labels and scores in different orders inspect the same
object and the dreaming loop's argmax (feature 274) ranks the same
candidates.

**Deterministic and pure, like the two laws it sits between.**  No store,
no clock, no environment — the pool and the ledger arrive as data, and the
labels the caller passes are the ones the census wrote.  Stdlib only:
:mod:`math` and :mod:`numbers` for the score seam's finiteness narrowing,
:mod:`collections.abc` for the shapes, and the member's own error and
blend — no third-party import at module scope, so the factory's scan
(which imports this package to fire its ``@register`` builder) pays
nothing for the law.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from numbers import Real
from typing import Any

from ._aggregate import LAMBDA_DEFAULT, AggregatedObjective, aggregate_objective
from .errors import RegimeIndexError

__all__ = [
    "PLAIN_MEAN_CODE",
    "regime_aggregate",
    "regime_strata",
]

#: The one word that opens every refusal of an ask whose arithmetic would
#: average across regimes — the feature's own first clause made greppable,
#: the convention ``pool_frozen`` (feature 270), ``illegal_theme`` (feature
#: 241) and ``full_history_fit`` (feature 290) already follow.  It opens
#: four faces, which the module docstring enumerates: no labels at all, a
#: scored world with no regime, a labelled world with no score, and a
#: declared regime that holds no worlds.  They are one word because they
#: are one failure — a mean over whatever worlds or regimes happened to be
#: present — and an operator greps for the number that was wrong, not for
#: which of the four ways the partition failed to close.
PLAIN_MEAN_CODE = "plain_mean"


def regime_strata(
    labels: Iterable[object],
    scores: Iterable[object],
    *,
    strata: Sequence[str] | None = None,
) -> dict[str, tuple[object, ...]]:
    """Index the world scores by regime — feature 264's verb, and the
    grouping feature 263's blend is taken over.

    ``labels`` are the regime rows the census assigned (each carrying
    ``world_id`` and ``stratum`` — feature 290's
    :class:`~regime.StratumAssignment` duck-typed), and ``scores`` are the
    world scores those worlds earned (each carrying ``world_id`` and a
    finite ``score`` — feature 256's :class:`~scoring.WorldScore`, read
    the way the blend reads it).  ``strata`` — keyword-only, optional — is
    the regime vocabulary the caller declares; ``None``, the default,
    means the regimes are whatever the labels name, and a declared
    vocabulary is checked in both directions (no label outside it, no name
    inside it left uncovered).

    Answers a fresh ``dict`` of stratum name to that stratum's score
    carriers, sorted by name and by world id within each name — the exact
    mapping :func:`~scoring.aggregate_objective` takes, so a caller that
    wants the blend passes this straight through, or calls
    :func:`regime_aggregate` and gets both acts in one.

    Refuses, with :class:`~scoring.RegimeIndexError` and nothing partial,
    every ask that would average across regimes — all four opening with
    :data:`PLAIN_MEAN_CODE` and each naming the world or the regime it is
    about:

    * no labels at all — scores with nothing to stratify them by;
    * a scored world the labels do not carry, and a labelled world no
      score was earned for — the join is a partition, and either half of a
      mismatch ends in a mean over a set nobody chose;
    * a declared regime the join does not cover — the subset-mean that
      erases §C7's starved stratum.

    And the ordinary shape refusals, without the code: a ``strata``
    vocabulary that is not a sequence of unique usable names; a label
    carrier that is not one, or whose ``stratum`` is not a name, or that
    names a regime outside a declared vocabulary; a world labelled twice
    or scored twice; a score carrier whose ``world_id`` is not a name or
    whose ``score`` is not a finite real; and an ask with no legal regimes
    to be taken over.

    Deterministic and pure: no store, no clock, no environment, and the
    same labels and scores answer the same mapping regardless of the order
    either arrived in.
    """
    vocabulary = _declared_vocabulary(strata)
    by_world = _labelled_worlds(labels, vocabulary)
    scored = _scored_worlds(scores)
    _require_one_pool(by_world, scored)
    index: dict[str, list[tuple[str, object]]] = {}
    for world_id, stratum in by_world.items():
        index.setdefault(stratum, []).append((world_id, scored[world_id]))
    if vocabulary is not None:
        _require_every_declared_regime_covered(index, vocabulary)
    return {
        stratum: tuple(carrier for _, carrier in sorted(index[stratum]))
        for stratum in sorted(index)
    }


def regime_aggregate(
    labels: Iterable[object],
    scores: Iterable[object],
    *,
    strata: Sequence[str] | None = None,
    lam: float = LAMBDA_DEFAULT,
) -> AggregatedObjective:
    """Index the scores by regime, then blend — the category's own
    aggregation, in one call whose strata are regimes by construction.

    :func:`regime_strata`'s act followed by
    :func:`~scoring.aggregate_objective`'s, with ``strata`` and ``lam``
    spelled exactly as the two verbs spell them.  The point of shipping it
    beside the two halves is not convenience but the feature's first
    clause: a caller that wants the cross-world number this category
    exists to produce has one call to make, so it never assembles a
    grouping by hand and never reaches the plain mean by assembling one
    wrong.

    Every refusal :func:`regime_strata` raises fires **before** the blend
    is asked for anything, so a plain-mean ask never reaches 263's
    arithmetic; and every refusal :func:`~scoring.aggregate_objective`
    raises — a λ outside prd §7.2's band, a stratum that holds no worlds —
    propagates unwrapped, because those are already this member's
    vocabulary and a second message in front of the one an operator needs
    would name the wrong act.
    """
    return aggregate_objective(regime_strata(labels, scores, strata=strata), lam=lam)


# -- the seam's private vocabulary --------------------------------------------


def _declared_vocabulary(strata: object) -> tuple[str, ...] | None:
    """The caller's declared regimes — checked, or ``None`` for an open set.

    ``None`` is the feature's own default and means the labels name their
    own regimes; every other value must be a sequence of unique usable
    names.  Checked before a single label is read, because a vocabulary
    that cannot be checked against is not a vocabulary, and a join
    validated against one would be validated against nothing.
    """
    if strata is None:
        return None
    if isinstance(strata, (str, bytes)) or not isinstance(strata, Sequence):
        raise RegimeIndexError(
            f"a declared regime vocabulary must be a sequence of regime "
            f"names, got {strata!r} ({type(strata).__name__}): a string is "
            f"one name, not the set of them, and a value that is not a "
            f"sequence cannot say which regimes a label may name; pass "
            f"``None`` to let the labels name their own regimes "
            f"(feature 264)"
        )
    names = tuple(
        _require_usable(name, "a declared regime", "one of the regimes a label may name")
        for name in strata
    )
    if len(set(names)) != len(names):
        duplicates = sorted({name for name in names if names.count(name) > 1})
        raise RegimeIndexError(
            f"a declared regime vocabulary must name each regime once, and "
            f"this one repeats {duplicates}: a vocabulary is the set a label "
            f"is checked against, and a name declared twice cannot be told "
            f"apart from a label that matched it twice (feature 264)"
        )
    if not names:
        raise RegimeIndexError(
            "a declared regime vocabulary must name at least one regime, "
            "and this one is empty: a vocabulary that admits no label "
            "refuses every world in the pool, which is a closed set rather "
            "than an empty one — pass ``None`` to let the labels name their "
            "own regimes (feature 264, prd §7.2)"
        )
    return names


def _labelled_worlds(
    labels: object, vocabulary: tuple[str, ...] | None
) -> dict[str, str]:
    """Read the census's rows — world id to regime name, or refuse.

    One pass, in the caller's own order (the answer is order-independent
    downstream).  Each row is read duck-typed for ``world_id`` and
    ``stratum`` and validated here, and a world labelled twice is refused
    in the *join's* vocabulary rather than the census's: feature 290
    refuses that too, but these rows are data by the time they arrive, and
    a partition a caller assembled is checked rather than trusted.
    """
    if isinstance(labels, (str, bytes)) or not isinstance(labels, Iterable):
        raise RegimeIndexError(
            f"the regime labels the strata are indexed by must arrive as an "
            f"iterable of label rows — each carrying a world_id and a "
            f"stratum, feature 290's StratumAssignment duck-typed — got "
            f"{labels!r} ({type(labels).__name__}): {PLAIN_MEAN_CODE}, "
            f"because an ask carrying no regime labels has no strata to "
            f"index and would average the scores across regimes "
            f"(feature 264, prd §7.2)"
        )
    by_world: dict[str, str] = {}
    for row in labels:
        world_id = _require_usable(
            getattr(row, "world_id", None),
            f"a regime label ({type(row).__name__})",
            "the world it labels, by a non-empty string",
        )
        stratum = _require_usable(
            getattr(row, "stratum", None),
            f"the regime of world {world_id!r}",
            "a regime named in non-empty text",
        )
        if vocabulary is not None and stratum not in vocabulary:
            raise RegimeIndexError(
                f"world {world_id!r} is labelled with regime {stratum!r}, "
                f"which the declared vocabulary does not name "
                f"({list(vocabulary)}): a label outside the declared set is "
                f"a stratum the caller's own ledger cannot show, and "
                f"indexing it anyway would blend over a regime nobody "
                f"declared (feature 264, prd §7.2)"
            )
        if (first := by_world.get(world_id)) is not None:
            raise RegimeIndexError(
                f"world {world_id!r} is labelled twice — with regime "
                f"{first!r} and again with {stratum!r}: each stored world is "
                f"assigned one stratum by the labeler, and a world carrying "
                f"two would be counted once per label in a mean that holds "
                f"it once (feature 264, prd §7.2)"
            )
        by_world[world_id] = stratum
    if not by_world:
        raise RegimeIndexError(
            f"the regime index was handed no labels at all: {PLAIN_MEAN_CODE}, "
            f"because scores with nothing to stratify them by are the "
            f"paper's (1/t)·Σ V_i^m — the mean prd §7.2 rejects on the "
            f"ground that market regimes are not exchangeable — and the "
            f"census that binned the pool (feature 290) is what supplies "
            f"the labels this verb indexes by (feature 264)"
        )
    return by_world


def _scored_worlds(scores: object) -> dict[str, object]:
    """Read the world scores — world id to carrier, or refuse.

    The score seam, read exactly as feature 263's blend reads it: duck-typed
    for ``world_id`` and a finite ``score``, never ``isinstance``, because
    the loader's synthetic-name re-execution makes a composed
    :class:`~scoring.WorldScore` a second class object of the right shape.
    A world scored twice is refused here for the reason a world labelled
    twice is: one world earns one score, and two would enter one mean
    twice.
    """
    if isinstance(scores, Mapping):
        # A mapping is read for its values, the spelling feature 263's
        # stratum seam accepts: iterating it would read world ids, which
        # are names, not scores.
        scores = scores.values()
    if isinstance(scores, (str, bytes)) or not isinstance(scores, Iterable):
        raise RegimeIndexError(
            f"the world scores the regimes are indexed over must arrive as "
            f"an iterable of world scores — each carrying a world_id and a "
            f"finite score, feature 256's WorldScore — got {scores!r} "
            f"({type(scores).__name__}): the index keys the scores by the "
            f"regimes their worlds were assigned, and a value that is not a "
            f"collection of scores has nothing to key (feature 264)"
        )
    by_world: dict[str, object] = {}
    for carrier in scores:
        world_id = _require_usable(
            getattr(carrier, "world_id", None),
            f"a world score ({type(carrier).__name__})",
            "the world it scores, by a non-empty string",
        )
        _require_finite_score(carrier, world_id)
        if world_id in by_world:
            raise RegimeIndexError(
                f"world {world_id!r} is scored twice: one world earns one "
                f"score — the pooled quantity the blend averages within a "
                f"stratum — and a world counted twice would weigh double in "
                f"the very figure that is supposed to weigh each world once "
                f"(feature 264, prd §7.2)"
            )
        by_world[world_id] = carrier
    return by_world


def _require_one_pool(by_world: dict[str, str], scored: dict[str, object]) -> None:
    """The join is a partition — the two sets must be the same set.

    Both halves of the mismatch are the same failure reached from either
    side, and both are refused naming the worlds and the direction, because
    the repairs differ: an unbinned world means the census has not run over
    the pool that was scored, and an unscored world means the pool holds a
    label for a world no score was earned in.
    """
    unbinned = sorted(set(scored) - set(by_world))
    if unbinned:
        raise RegimeIndexError(
            f"{len(unbinned)} scored world(s) carry no regime label "
            f"({unbinned[:5]}): {PLAIN_MEAN_CODE} — the pool was scored over "
            f"{len(scored)} worlds and the census binned {len(by_world)}, "
            f"and averaging the scores while reading the labels as "
            f"commentary is exactly the plain mean across regimes prd §7.2 "
            f"rejects; re-run the census (feature 290) over the pool that "
            f"was scored, or hand the index the worlds the labels cover "
            f"(feature 264)"
        )
    unscored = sorted(set(by_world) - set(scored))
    if unscored:
        raise RegimeIndexError(
            f"{len(unscored)} labelled world(s) earned no score "
            f"({unscored[:5]}): {PLAIN_MEAN_CODE} — the census binned "
            f"{len(by_world)} worlds and only {len(scored)} were scored, so "
            f"an index built from the overlap would blend over a pool that "
            f"is not the pool and report strata it silently thinned; the "
            f"worlds the ledger names and the worlds that earned a score are "
            f"one set, and this ask's are not (feature 264, prd §7.2)"
        )


def _require_every_declared_regime_covered(
    index: Mapping[str, list[tuple[str, object]]], vocabulary: tuple[str, ...]
) -> None:
    """Every declared regime must hold worlds — the §C7 refusal.

    The one plain-mean face feature 263 cannot state from its own side:
    the blend refuses a stratum it was *handed* with no worlds, but a
    stratum the index dropped never reaches it, and blending over the
    covered subset is a mean across the regimes that happened to be present
    — which is §C7's whole hazard (docs/alpha-engine-prd.md line 454), the
    starved regime being the fact a subset-mean erases.  The hole is named
    here in terms of the ledger and the warning that report it, so the
    repair is a backfill (feature 287) or a promotion block (feature 285)
    rather than a different blend.
    """
    starved = sorted(name for name in vocabulary if name not in index)
    if starved:
        raise RegimeIndexError(
            f"{len(starved)} declared regime(s) hold no worlds ({starved}): "
            f"{PLAIN_MEAN_CODE} — blending over the {len(index)} regime(s) "
            f"that are covered would weight the pool by which regimes it "
            f"happens to hold, and the starved stratum is the one §C7's "
            f"ledger exists to make visible (\"run six months in low-vol "
            f"chop and your entire pool is low-vol chop\"); name it in the "
            f"coverage ledger (feature 283), let the empty_stratum warning "
            f"report it (feature 286), and backfill the coverage (feature "
            f"287) before aggregating across the declared set (feature 264)"
        )


def _require_usable(value: Any, field: str, what: str) -> str:
    """Refuse a value that is not a usable name, answering it unchanged
    when it is.

    The objective's own name check (``_objective._require_name``) restated
    in this module's vocabulary, the practice ``_aggregate`` follows for
    its own: a ``bool`` is refused before the string check because ``True``
    would otherwise be read as a name by nothing, and a blank names
    nothing — and a world or a regime that cannot be named cannot be
    reported, counted once, or checked against a vocabulary.
    """
    if isinstance(value, bool) or not isinstance(value, str) or not value.strip():
        raise RegimeIndexError(
            f"{field} must name {what}, got {value!r} "
            f"({type(value).__name__}): the index keys the scores by a regime "
            f"name and enforces one world once by a world id, so a value that "
            f"names nothing has nothing to be keyed by (feature 264, prd §7.2)"
        )
    return value


def _require_finite_score(carrier: object, world_id: str) -> float:
    """Read a carrier's score and narrow it — a finite real, or refuse.

    The one scalar the index passes through untouched but must still
    vouch for, because the seam is duck-typed: a carrier whose ``score`` is
    not a finite real would otherwise reach 263's :func:`math.fsum` as a
    ``TypeError`` naming the wrong act, and the ``−∞`` the objective's
    vocabulary holds is feature 222's non-committing miss — which never
    carries a pick, so no indexed world may counterfeit it.
    """
    value = getattr(carrier, "score", None)
    if isinstance(value, bool) or not isinstance(value, Real):
        raise RegimeIndexError(
            f"the score of world {world_id!r} must be a real number, got "
            f"{value!r} ({type(value).__name__}): the index hands every score "
            f"to the blend's arithmetic unchanged, and a value that is not a "
            f"real is not a reading any stratum mean can hold "
            f"(feature 264, prd §7.2)"
        )
    narrowed = float(value)
    if not math.isfinite(narrowed):
        raise RegimeIndexError(
            f"the score of world {world_id!r} must be finite, got "
            f"{narrowed!r}: a NaN compares false against every score and would "
            f"drop out of the ranking this aggregate feeds, and the only −∞ "
            f"the objective's vocabulary holds is the non-committing miss, "
            f"which feature 222 owns (NON_COMMITTING_SCORE) and which never "
            f"carries a pick — so no indexed world may counterfeit it "
            f"(feature 264)"
        )
    return narrowed
