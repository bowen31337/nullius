"""The scoring member's error vocabulary.

One base class (:class:`ScoringError`) so a caller — the replay engine,
the dreaming loop's argmax, an operator script, a later feature in this
category — can catch every failure of the objective's arithmetic with a
single ``except``, the discipline :mod:`bootstrap.errors`,
:mod:`discovery.errors` and :mod:`policy_runtime.errors` state for their
own trees.  The categories this member will grow are visible in
app_spec.xml's "Objective Scoring & CVaR Aggregation" from the start —
the β-terms (257 through 262), the cross-world aggregation (263), the
scorer-process calibration figures (265 through 269) — and each carries
its own refusals when it lands; a subclass is added then, named for what
the caller must do about it, not for the line that raised.

Feature 256 needs exactly one: :class:`WorldObjectiveError`, the refusal
of a per-world objective ask that cannot be scored.  Feature 263 adds the
aggregation's own: :class:`AggregationError`, the refusal of a cross-world
ask that cannot be blended (see :mod:`scoring._aggregate` for that law's
own statement of which asks those are).  Feature 264 adds
:class:`RegimeIndexError`, the refusal of an ask whose arithmetic would
average across regimes — *"indexing aggregation strata by regime instead"*
— and it sits **beside** :class:`AggregationError` rather than under it,
which is worth stating because the two are one feature apart and share an
input.  Feature 262 adds the β-terms' first: :class:`OrthogonalityError`,
the refusal of a bonus ask that cannot be measured; feature 261 adds the
penalties' first, :class:`SwitchPenaltyError`, the refusal of a switch
charge that cannot be counted; feature 260 adds
:class:`DivergencePenaltyError`, the refusal of a sim-reality divergence
that cannot be read; feature 259 adds :class:`DeflationPenaltyError`,
the refusal of a multiple-testing haircut that cannot be trusted; feature
258 adds :class:`NullPickPenaltyError`, the refusal of a planted-null
penalty that cannot be charged — the five β-terms this member has so far,
and the place the last one (257) will add its own when it lands.  Feature
265 adds the scorer process's own: :class:`NullPickRateError`, the
refusal of a null pick rate that cannot be computed — the first class of
the category's state-bound half, and the one place in this member whose
refusals can name a *read* that failed rather than only an ask that was
malformed (see that class's docstring for why those are stated apart).
263 refuses an ask it cannot *blend*: a λ outside the band, a
stratum handed over with no worlds, a carrier it cannot read.  264 refuses
an ask it cannot *partition*: scores with no labels, a scored world the
census never binned, a labelled world no score was earned for, a declared
regime the join does not cover.  Both end in a mean somebody did not
choose, but the repairs differ — a mis-set knob or a malformed carrier
against a census that has not run — and folding them would put two
different next steps behind one ``except``.  The same reasoning
:mod:`regime.errors` states for putting
:class:`~regime.errors.StratumAssignmentError` beside
:class:`~regime.errors.CoverageError`.  And 262's refusal sits beside
256's for the member's own version of that reason: the objective refuses
an ask that cannot be *scored* (a pick panel with no ratio in it), the
bonus refuses one whose *payment* cannot be measured (a book that misses
the epoch, a panel that did not measure the score it sits beside, a
coefficient that flips the term's sign), and the two repairs send the
operator to different members — sequestration against the resident
array.  And 261's refusal sits beside
both of theirs for the member's own version of that reason: the switch
penalty refuses an ask whose *charge* cannot be counted (a regime path
that is not an ordered sequence of names, a horizon nobody labelled
read as zero switches, a price or a coefficient that flips the term's
sign), and its repairs differ from both — a census that has not run
against a cost model that mis-set its price — so folding it under
either would send the operator looking for a sequestration fault in
the labeler.  And 260's refusal sits beside all three for the member's
own version of that reason: the divergence penalty refuses an ask
whose *divergence* cannot be read (a coefficient that flips the term's
sign, a forward or backtest information coefficient that is absent, or
one outside the ``[−1, 1]`` an information coefficient is bounded by),
and its repair lands on the forward-test record — a member none of the
other three refusals names — so folding it would send the operator
hunting for a sequencing or labelling fault in a data path this term
never reads.  And 259's refusal sits beside all four for the member's
own version of that reason: the deflation penalty refuses an ask whose
*count* cannot be trusted (a coefficient that flips the term's sign, a
deflation input handed over as a bare number rather than the
``K_effective`` derivation, a total that is not a count of trials), and
its repair lands on the trial ledger — a member none of the other four
refusals names — so folding it would send the operator hunting for a
sequestration, resident-array, labelling or forward-record fault in a
data path this term never reads.  And 258's refusal sits beside all five
for the member's own version of that reason: the null-pick penalty
refuses an ask whose *false discovery* cannot be charged (a coefficient
that flips the term's sign, a rate that is not a fraction of committed
picks — a count of null picks being the likeliest thing handed over under
that field name), and its repair lands on the scorer process §4.2 gives
the sidecar key to — feature 265's component, which no other refusal on
this list names — so folding it would send the operator hunting for a
sequestration, resident-array, labelling, forward-record or ledger fault
in a data path this term never reads either.  Every refusal the eight
classes carry is a fact about the *ask* — a world that is not a name, a
pick that names no node, a sequestered panel that cannot define a ratio,
a stratum that holds no worlds, a λ outside the band prd §7.2 states, a
pool whose labels and scores are not one set — and nothing was read from
any store and nothing is written when one raises, so the repair is always
to re-consider what was handed in.  That is a smaller taxonomy than the
store-owning members need because the objective is pure arithmetic: it has
no ordering laws to contradict and no deployment state to be absent.  The
division of labour that keeps it small is stated in
:mod:`scoring._objective` and worth restating here, because the two
refusals a caller might expect from a "scoring" member and does not get
are deliberate:

* **the non-committing policy is not this member's refusal.**  prd §438
  and docs §598 spell it as a *score*, ``−∞``, and feature 222 owns that
  value (:data:`policy_runtime.NON_COMMITTING_SCORE`, spelled once
  there) — the miss is answered by the termination, which routes the
  scorer only when a pick exists, so this member's arithmetic never sees
  a pickless ask and never invents an error for one.
* **a deployment with no data is not this member's refusal either.**
  Reaching the sequestered epoch's return readings is the replay
  engine's data access; the objective is a function of the readings it
  is handed.  A caller that has none has not been refused — it has not
  yet asked.
"""

from __future__ import annotations

__all__ = [
    "AggregationError",
    "DeflationPenaltyError",
    "DivergencePenaltyError",
    "NullPickPenaltyError",
    "NullPickRateError",
    "OrthogonalityError",
    "RegimeIndexError",
    "ScoringError",
    "SwitchPenaltyError",
    "WorldObjectiveError",
]


class ScoringError(Exception):
    """The base class of every refusal the scoring member raises.

    Deliberately not the base of the ``−∞`` a non-committing policy
    earns — that is a score, not an error (feature 222, prd §438) — and
    not the base of any failure in the data paths that feed the
    objective.  Catching this class catches the objective's own laws and
    nothing else, which is what a replay loop wrapping its scoring step
    in a single ``except`` needs to be true.
    """


class WorldObjectiveError(ScoringError):
    """A per-world objective ask that cannot be scored (feature 256).

    The ask was malformed — a world id that is not a name, a pick that
    names no node, a sequestered panel that cannot define an information
    ratio (fewer than two dates, a series that never varied, a reading
    that is not a finite real) — and the refusal names which, because
    the repair differs: a malformed pick is a wiring fault at the
    replay's commit seam, an undefined ratio is a data-coverage fact
    about the sequestered epoch, and conflating the two would send the
    operator looking in the wrong place.

    No partial value escapes a refusal: the objective either answers a
    frozen :class:`~scoring.WorldScore` or raises, so a caller can never
    hold a half-scored world it must remember to discard.
    """


class AggregationError(ScoringError):
    """A cross-world aggregation ask that cannot be blended (feature 263).

    The ask was malformed — strata that are not a mapping of stratum name
    to that stratum's world scores, a stratum that holds no worlds (whose
    mean would be a number nobody measured), a world carried by two
    strata or twice by one, a carrier that is not a world score, or a λ
    outside prd §7.2's ``[0.5, 0.7]`` band — and the refusal names which,
    because the repairs differ: an unstratified collection of scores is
    the plain mean over regimes that feature 264 exists to reject, an
    empty stratum is a coverage hole feature 286's ``empty_stratum``
    warning reports on the ledger (not a figure this blend may invent),
    and an out-of-band λ is a mis-set knob, not a broken input.

    No partial value escapes a refusal: the aggregation either answers a
    frozen :class:`~scoring.AggregatedObjective` or raises, so a caller
    can never hold a half-blended score it must remember to discard —
    the same guarantee :class:`WorldObjectiveError` makes one feature
    earlier, held here for the number the dreaming loop's argmax ranks
    candidates on (feature 274).
    """


class OrthogonalityError(ScoringError):
    """A beta-six bonus ask that cannot be measured (feature 262).

    The ask was malformed in this term's own inputs — a coefficient that
    is not a finite non-negative real (the spec's verb is *adds*, and a
    negative one would counterfeit a penalty through the bonus seam), a
    score carrier exposing no finite ``ir_oos`` to pin the sequestered
    panel against or no ``adjusted`` seam to ride, a pick panel whose
    recomputed ratio is not the measurement the score carries (the bonus
    would be measured on data the score never saw), or a committed-book
    panel that is not a mapping of dates to finite reals, that misses a
    date of the sequestered epoch, or that never varied across it (a
    correlation of ``0/0`` is undefined, and no bonus is invented for
    one) — and the refusal names which, because the repairs differ: a
    mis-set knob against a book the resident array under-covers against
    a caller re-using a panel from another score.

    The pick panel's *shape* refusals are deliberately not this class's:
    they are feature 256's own :class:`WorldObjectiveError`, raised by
    256's code through the recomputation this seam performs, because a
    panel that cannot define an information ratio is refused the same
    way wherever it was rejected and both classes share the
    :class:`ScoringError` base a replay loop's single ``except``
    catches.  Beside :class:`WorldObjectiveError`, never under it: 256
    refuses an ask that cannot be *scored*, this class refuses one
    whose *bonus* cannot be measured, and folding them would send the
    operator looking for a sequestration fault in the resident array.

    No partial value escapes a refusal: the bonus either answers the
    moved :class:`~scoring.WorldScore` or raises, so a caller can never
    hold a half-paid score it must remember to discard — the guarantee
    :class:`WorldObjectiveError` makes one feature earlier and every
    β-term landing after this one inherits by riding the same frozen
    seam.
    """


class SwitchPenaltyError(ScoringError):
    """A beta-five switch charge that cannot be counted (feature 261).

    The ask was malformed in this term's own inputs — a coefficient or
    a switch cost that is not a finite non-negative real (the spec's
    verb is *subtracts*, and a negative coefficient would counterfeit a
    bonus through the penalty seam while a negative cost would pay the
    policy for every crossing it makes), a score carrier exposing no
    ``adjusted`` seam to ride, or a regime path that is not an ordered
    sequence of names, holds a label that names no regime, or holds no
    windows at all (an unlabelled horizon's count is unknown, not
    zero) — and the refusal names which, because the repairs differ: a
    mis-set knob against a cost model's price against a census that has
    not run over the scored epoch.

    Beside :class:`WorldObjectiveError` and :class:`OrthogonalityError`,
    never under either: 256 refuses an ask that cannot be *scored*, 262
    refuses one whose *bonus* cannot be measured, this class refuses one
    whose *charge* cannot be counted, and the three repairs send the
    operator to different members — sequestration, the resident array,
    the regime labeler.

    No partial value escapes a refusal: the penalty either answers the
    moved :class:`~scoring.WorldScore` or raises, so a caller can never
    hold a half-charged score it must remember to discard — the
    guarantee :class:`WorldObjectiveError` makes one feature earlier and
    every β-term landing through the same frozen seam inherits.
    """


class DivergencePenaltyError(ScoringError):
    """A beta-four divergence charge that cannot be measured (feature 260).

    The ask was malformed in this term's own inputs — a coefficient that
    is not a finite non-negative real (the spec's verb is *subtracts*, and
    a negative one would counterfeit a bonus through the penalty seam,
    teaching the loop to prefer the families whose backtests flattered
    them most), a score carrier exposing no ``adjusted`` seam to ride, or
    an ``ic_forward``/``ic_backtest`` that is not a finite real in
    ``[−1, 1]`` — and the refusal names which, because the repairs differ:
    a mis-set knob against a backtest metric the evaluator wrote wrongly
    against a forward figure the forward-tracking member wrote wrongly.

    The *absence* of a forward IC is deliberately not representable here,
    and that is the class's sharpest edge rather than an omission: prd
    §7.1's own sentence is that β₄ *"is computable only for nodes that
    have been through the forward-test queue"*, so a pick with no forward
    record has no figure to hand over and a caller with none must not call
    this term — but a stand-in *must not* be read as a zero either way
    (read as zero, an absent forward IC charges the pick its entire
    backtest figure on no evidence; read as "no divergence", it pays it in
    full).  Neither is a measurement, so the seam takes two figures and
    refuses anything that is not one.  The same stance
    :class:`SwitchPenaltyError` takes toward an unlabelled horizon, whose
    switch count is unknown rather than zero.

    Beside :class:`WorldObjectiveError`, :class:`OrthogonalityError` and
    :class:`SwitchPenaltyError`, never under any of them: 256 refuses an
    ask that cannot be *scored*, 262 one whose *bonus* cannot be measured,
    261 one whose *charge* cannot be counted, and this class one whose
    *divergence* cannot be read — the four repairs sending the operator to
    different members (sequestration, the resident array, the regime
    labeler, the forward-test record).

    No partial value escapes a refusal: the penalty either answers the
    moved :class:`~scoring.WorldScore` or raises, so a caller can never
    hold a half-charged score it must remember to discard — the guarantee
    :class:`WorldObjectiveError` makes one feature earlier and every
    β-term landing through the same frozen seam inherits.
    """


class DeflationPenaltyError(ScoringError):
    """A beta-three deflation charge that cannot be trusted (feature 259).

    The ask was malformed in this term's own inputs — a coefficient that
    is not a finite non-negative real (the spec's verb is *subtracts*,
    and a negative one would counterfeit a bonus through the penalty
    seam, teaching the loop that searching profligately pays), a score
    carrier exposing no ``adjusted`` seam to ride, a ``k_effective``
    handed over as a bare number rather than the derivation (the shape a
    raw trial count takes — the ledger's row count, null nodes included —
    refused whatever its value, because no arithmetic on a number can say
    whether it was counted honestly), or a carrier whose ``total`` is not
    a non-negative count of trials — and the refusal names which, because
    the repairs differ: a mis-set knob against a caller that reached for
    the plain row count against a view the ledger's derivation never
    wrote.

    The *substitution* of a raw count is the class's sharpest edge and
    the feature's own sentence: *System rejects a deflation input taken
    from raw trial counts, computing the beta-three term from
    K_effective instead*.  prd §4 (line 123) is why — a null node
    *"consumed agent calls and CPU but* **no statistical degrees of
    freedom**. *It must not count toward ``K`` in the deflation term"*,
    so a count that includes them prices the calibration §4 tells the
    system to buy in research power it never spent — and a count that
    quietly drops a charged row understates the haircut, the one
    direction that lets a false discovery through.  Both failures wear
    the same shape at the seam (an honest-looking integer), which is why
    the seam refuses the shape rather than guessing at the value.

    Beside :class:`WorldObjectiveError`, :class:`OrthogonalityError`,
    :class:`SwitchPenaltyError` and :class:`DivergencePenaltyError`,
    never under any of them: 256 refuses an ask that cannot be *scored*,
    262 one whose *bonus* cannot be measured, 261 one whose *charge*
    cannot be counted, 260 one whose *divergence* cannot be read, and
    this class one whose *haircut* cannot be trusted — the five repairs
    sending the operator to different members (sequestration, the
    resident array, the regime labeler, the forward-test record, the
    trial ledger).

    No partial value escapes a refusal: the penalty either answers the
    moved :class:`~scoring.WorldScore` or raises, so a caller can never
    hold a half-charged score it must remember to discard — the guarantee
    :class:`WorldObjectiveError` makes one feature earlier and every
    β-term landing through the same frozen seam inherits.
    """


class NullPickPenaltyError(ScoringError):
    """A beta-two null-pick charge that cannot be charged (feature 258).

    The ask was malformed in this term's own inputs — a coefficient that
    is not a finite non-negative real (the spec's verb is *subtracts*, and
    a negative one would counterfeit a bonus through the penalty seam,
    teaching the loop that landing on the nulls §4 planted is profitable),
    a score carrier exposing no ``adjusted`` seam to ride, or a
    ``null_pick_rate`` that is not a finite real in ``[0, 1]`` — and the
    refusal names which, because the repairs differ: a mis-set knob
    against a rate the scorer process never computed against a *count* of
    null picks handed over where a fraction of committed picks belongs.

    The *count-for-a-rate* substitution is this class's sharpest edge.  The
    rate is prd §4.4's *"fraction of committed picks that are planted
    nulls"* (line 173), so it is a fraction of a whole and bounded in
    ``[0, 1]`` by construction — the same way an information coefficient
    is bounded because it is a correlation, which is why
    :class:`~scoring.DivergencePenaltyError` refuses an out-of-bound IC for
    its own term.  A figure outside the interval is not a high rate; it is
    a number that has stopped being one, and the likeliest thing wearing
    its name is the numerator alone.  Clamping it to an endpoint would
    charge a maximum penalty nobody measured, in either direction, so the
    figure is refused instead.

    Beside :class:`WorldObjectiveError`, :class:`OrthogonalityError`,
    :class:`SwitchPenaltyError`, :class:`DivergencePenaltyError` and
    :class:`DeflationPenaltyError`, never under any of them: 256 refuses an
    ask that cannot be *scored*, 262 one whose *bonus* cannot be measured,
    261 one whose *charge* cannot be counted, 260 one whose *divergence*
    cannot be read, 259 one whose *haircut* cannot be trusted, and this
    class one whose *false discovery* cannot be charged — the six repairs
    sending the operator to different members (sequestration, the resident
    array, the regime labeler, the forward-test record, the trial ledger,
    the scorer process §4.2 gives the sidecar key to).  It is
    :class:`SwitchPenaltyError`'s opposite number one feature over, and the
    two are deliberately *not* one class: β₅ charges a horizon's churn and
    β₂ charges the nulls the policy committed to, which prd §4.1.2's
    *"separate the error accounting"* (line 140) keeps apart.

    No partial value escapes a refusal: the penalty either answers the
    moved :class:`~scoring.WorldScore` or raises, so a caller can never
    hold a half-charged score it must remember to discard — the guarantee
    :class:`WorldObjectiveError` makes one feature earlier and every
    β-term landing through the same frozen seam inherits.
    """


class RegimeIndexError(ScoringError):
    """A regime index that would average across regimes (feature 264).

    Feature 264's refusal — *System rejects a plain mean across regimes,
    indexing aggregation strata by regime instead* — and four of its faces
    open with :data:`scoring.PLAIN_MEAN_CODE` (``plain_mean``), the one
    word that names what the ask would have computed: scores with no
    labels to stratify them by, a scored world the census never binned, a
    labelled world no score was earned for, and a declared regime the join
    does not cover.  They are one class because they are one failure — a
    mean over whatever worlds or regimes happened to be present, which is
    prd §7.2's ``(1/t)·Σ V_i^m`` arrived at by four different routes — and
    the repair is the same in all four: close the partition, by running
    the census (feature 290) over the pool that was scored, or by handing
    over the worlds the labels cover.

    The remaining faces are ordinary shape refusals and carry no code: a
    ``strata`` vocabulary that cannot be checked against (not a sequence,
    empty, a repeated name, a name that names nothing), a label carrier
    whose ``stratum`` is not a name or names a regime outside the declared
    vocabulary, a world labelled or scored twice, a score carrier that is
    not a world score, and an ask with no legal regimes at all.

    Beside :class:`AggregationError`, never under it: 263 refuses an ask
    that cannot be *blended*, this class refuses an ask that cannot be
    *partitioned*, and the module docstring above states why the two
    repairs must stay distinguishable behind separate ``except``s.
    """


class NullPickRateError(ScoringError):
    """A null pick rate that cannot be computed (feature 265).

    Two kinds of refusal share this class because both mean *the rate is
    not a measurement anyone made*, and the seam must never answer one
    anyway:

    * **a malformed ask** — ``picks`` that is not the committed picks
      themselves (a mapping's keys are not its picks, a bare string is
      one pick spelled where the collection belongs), an ask with no
      picks at all (a rate over an empty denominator is undefined, not
      ``0.0``), a pick that names no node or whose node id cannot join
      the sidecar's UUID keys, or a sidecar-holding object that exposes
      no callable ``assignment(node_id)`` seam — and the refusal names
      which, because the repairs differ: the caller's wiring against the
      deployment's sidecar configuration;
    * **a label that is not an answer** — a committed pick the sidecar
      holds no entry for (its null status is *unknown*, and reading it as
      real would deflate exactly the figure prd §4.4 defines and §7.1
      line 327 makes the term without which none of this works), an entry
      whose ``is_null`` is not a genuine bool, or the sidecar's own
      failure while being read — a file that will not open, a key that
      does not decrypt, permissions that admit a second account —
      translated into this class at the seam, with the original chained,
      because the sidecar is another member's and a caller catching this
      member's vocabulary must not also catch the oracle's.

    The refusals name the *pick* and never the *branch*, the discipline
    :mod:`nulloracle.target` states for the oracle's own messages: which
    node was committed is the caller's fact, which nodes are null is the
    one fact this class exists to keep inside the process.

    Beside :class:`~scoring.NullPickPenaltyError`, never under it and
    never over it: 258 refuses a *charge* that cannot be made on a rate
    the caller already holds, this class refuses the *rate* itself — the
    computation 258's docstring names as this feature's contribution —
    and the two repairs send the operator to different places (a mis-set
    coefficient against a sidecar that is absent, unopenable, or holds
    no entry for a committed pick).  Folding them would send an operator
    tuning β₂ when the thing to fix is that the scorer process never
    computed a number at all.

    No partial value escapes a refusal: the verb either answers one bare
    ``float`` or raises, so a caller can never hold a half-counted rate it
    must remember to discard — and no label crosses either way, which is
    the feature's own sentence: the rate is returned while the labels stay
    in.
    """
