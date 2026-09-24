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
penalty that cannot be charged, and feature 257 adds the penalties' first
by feature number: :class:`TrialsPenaltyError`, the refusal of a
statistical-budget charge that cannot be counted — the six β-terms this
member now holds, each with its own refusal.  Feature
265 adds the scorer process's own: :class:`NullPickRateError`, the
refusal of a null pick rate that cannot be computed — the first class of
the category's state-bound half, and the one place in this member whose
refusals can name a *read* that failed rather than only an ask that was
malformed (see that class's docstring for why those are stated apart).
Feature 266 adds the calibration figures' own:
:class:`CalibrationFiguresError`, the refusal of a sensitivity and
specificity ask that cannot be measured — the population-shaped sibling
of the rate's ask, spoken in its own vocabulary because its refusals
name the *planted node* where 265's name the committed pick, and the one
other place in this member whose refusals can name a read that failed.
Feature 267 adds the deployed FDR's own: :class:`FdrDeployError`, the
refusal of a deployment false discovery rate that cannot be reweighted
— the projection of feature 266's pair at the deployment base rate, and
the per-campaign row it persists in, each refused in a vocabulary that
names the campaign and the corner rather than the pick and the plant.
Feature 269 adds the accounting's own: :class:`ErrorAccountingError`,
the refusal of an error accounting whose two figures cannot be kept
apart — the Type-A rate's ask and the Type-B depth facts each refused
in their own vocabulary, so prd §4.1.2's *"separate the error
accounting"* is held by the taxonomy and not only by the value's shape.
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
    "CalibrationFiguresError",
    "DeflationPenaltyError",
    "DivergencePenaltyError",
    "ErrorAccountingError",
    "FdrDeployError",
    "NullPickPenaltyError",
    "NullPickRateError",
    "OrthogonalityError",
    "RegimeIndexError",
    "ScoringError",
    "SwitchPenaltyError",
    "TrialsPenaltyError",
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


class TrialsPenaltyError(ScoringError):
    """A beta-one trials charge that cannot be counted (feature 257).

    The ask was malformed in this term's own inputs — a coefficient that
    is not a finite non-negative real (the spec's verb is *subtracts*, and
    a negative one would counterfeit a bonus through the penalty seam,
    teaching the loop that spending statistical budget pays), a score
    carrier exposing no ``adjusted`` seam to ride, or a ``trials_charged``
    that is not a non-negative integer count (a ``bool`` wearing an int's
    type, a negative count that would pay the policy for having searched,
    or a float — a measurement where a count of hypotheses belongs) — and
    the refusal names which, because the repairs differ: a mis-set knob
    against a carrier that is not a world score against a caller that
    reached for the wrong count.

    The *count-for-a-derivation* substitution is this class's sharpest
    edge and the feature's own boundary.  ``trials_charged`` is the **raw**
    statistical spend — feature 221's ``BudgetAccount.charged``, §6.1's
    ``trials_charged`` column, the plain number of budget-charging trials —
    and this term charges one ``β₁`` per unit of it, linearly.  It is
    deliberately **not** feature 259's ``K_effective``: β₁ and β₃ are two
    terms over the same resource, priced two different ways (β₁ the raw
    spend, β₃ the multiple-testing bar over the honest count), and handing
    the same derivation to both would charge β₁ on a filtered count and β₃
    on a raw one.  The seam therefore takes the count directly — it reads
    the one figure its own term names and never reaches for a ``total`` or
    a ``by_epoch`` breakdown — and a caller that hands a ``K_effective``
    derivation where a count belongs is refused: the honest counter is a
    count of trials, and this term wants the spend, not the derivation.

    Beside :class:`WorldObjectiveError`, :class:`OrthogonalityError`,
    :class:`SwitchPenaltyError`, :class:`DivergencePenaltyError`,
    :class:`DeflationPenaltyError` and :class:`NullPickPenaltyError`, never
    under any of them: 256 refuses an ask that cannot be *scored*, 262 one
    whose *bonus* cannot be measured, 261 one whose *charge* cannot be
    counted, 260 one whose *divergence* cannot be read, 259 one whose
    *haircut* cannot be trusted, 258 one whose *false discovery* cannot be
    charged, and this class one whose *statistical spend* cannot be counted —
    the seven repairs sending the operator to different members
    (sequestration, the resident array, the regime labeler, the
    forward-test record, the trial ledger, the scorer process, the budget
    account).  It is the penalties' first by feature number, and the six
    β-terms' refusals are deliberately *not* one class: each prices a
    different fact, and prd §7.1's formula keeps them as separate lines.

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

    And 257's refusal sits beside all six for the member's own version of
    that reason: the trials penalty refuses an ask whose *statistical
    spend* cannot be counted (a coefficient that flips the term's sign, a
    ``trials_charged`` that is not a non-negative integer count, a raw
    spend handed over as the ``K_effective`` derivation β₃ consumes
    instead), and its repair lands on the budget account — feature 221's
    ``BudgetAccount.charged`` and the ``trials_charged`` column, a data
    path none of the other six refusals names — so folding it would send
    the operator hunting for a sequestration, resident-array, labelling,
    forward-record, ledger, scorer or null-pick fault in a data path this
    term never reads.
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


class CalibrationFiguresError(ScoringError):
    """A sensitivity and specificity ask that cannot be measured
    (feature 266).

    The ask was malformed in this seam's own inputs — a ``population``
    that is not the planted nodes themselves (a mapping's keys are not
    its nodes, a bare string is one node spelled where the collection
    belongs), a population with no planted nodes at all, one planted
    node carried twice (the planted set is a whole, and a duplicate
    would double-count one denominator), a discovered pick the
    population does not hold (a claim the figures cover on neither
    side, and a fraction over a whole nobody chose), a population whose
    labels hold no real node (sensitivity's class is empty — nothing
    for a discovery to find, the one-sided plant prd §4.1.1's floor
    problem exists to keep out of a campaign), or one whose labels hold
    no null (specificity's class is empty — a population of nothing but
    reals cannot be wrongly declared against) — and the refusal names
    which, because the repairs differ: the caller's declaration of the
    whole against a campaign the oracle planted one-sidedly against a
    pick collection drawn from another population than the figures
    were.

    Two refusal families are deliberately *not* this class's.  A pick
    spelled wrongly arrives as :class:`~scoring.NullPickRateError`,
    propagated untranslated from the pick law feature 265 states, so
    the repair stays named where that law lives — the same stance
    feature 269's seam takes toward the same law.  And a *read* that
    failed — the sidecar unopenable, undecryptable, or holding no entry
    for a planted node, or an entry whose ``is_null`` is not a genuine
    bool — is translated *into* this class with the original chained,
    because the read's subject here is the population this feature
    declared and 265's wording names the committed pick; the read's
    laws are shared and its words are not (see
    :mod:`scoring._calibration` for the argument).

    Beside :class:`~scoring.NullPickRateError` and
    :class:`~scoring.ErrorAccountingError`, never under either: 265
    refuses the *rate* over the picks, 269 refuses the *split
    accounting* of the two error types, and this class refuses the
    *class-conditional figures* — the pair prd §4.1.3 reweights into
    ``FDR_deploy`` and feature 267 will consume exactly as handed.  The
    three repairs send the operator to different places (a sidecar that
    never answered a pick against a join that handed the accounting
    branches with no flips against a population that was empty, doubled,
    one-sided, or measured over picks it did not hold), and folding any
    two would send an operator tuning one repair when the thing to fix
    was another.

    No partial value escapes a refusal: the verb either answers a frozen
    :class:`~scoring.CalibrationFigures` or raises, so a caller can
    never hold a half-measured pair it must remember to discard — the
    guarantee :class:`WorldObjectiveError` makes one feature earlier and
    the one every figure this member answers inherits — and no label
    crosses either way, which is feature 265's own sentence held for
    this answer: the figures are returned while the labels stay in.
    """


class FdrDeployError(ScoringError):
    """A deployment false discovery rate that cannot be reweighted or
    persisted (feature 267).

    The ask was malformed in this seam's own inputs — a ``campaign`` id
    that is not a UUID (the row's key joins ``node.campaign_id`` and the
    discovery member's campaign record, and an id that cannot join them
    names no campaign a figure could be persisted for), a figures
    carrier that exposes no readable ``sensitivity``/``specificity``
    pair (a bare number being the likeliest wrong carrier, and the raw
    in-campaign rate the likeliest bare number — the one figure prd
    §4.1.3 forbids the dashboard and this seam refuses as an input), a
    figure that is not a finite real in ``[0, 1]`` (a duck-typed carrier
    owes the proof a constructor no longer stands behind), or the pair
    ``sensitivity 0.0, specificity 1.0`` — feature 266's honest answer
    for a campaign that committed to nothing, and the one pair whose
    reweighting is ``0/0`` at every base rate: no declaration was ever
    made, so no fraction of declarations is defined, and unknown is not
    zero — and the refusal names which, because the repairs differ: the
    caller's key against the carrier's wiring against a campaign this
    arithmetic must refuse rather than default.

    The store's own failures surface here too, translated with the
    original chained — no configured ``DATABASE_URL``, a scheme the
    store cannot speak, a locked or unwritable database, and a persisted
    row that does not read back as the projection of the pair it carries
    (a stored figure that disagrees with its own ``sensitivity`` and
    ``specificity``, or a base rate that is not the deployment's) —
    because the caller's single ``except ScoringError`` must catch a
    figure that measured but never landed, the same law
    :class:`~scoring.NullPickRateError` states for the read and the
    replay member states for its latency row.

    Beside :class:`~scoring.CalibrationFiguresError` and
    :class:`~scoring.NullPickRateError`, never under either: 265 refuses
    the *rate* over the picks, 266 refuses the *pair* over the plant,
    and this class refuses the *projection* of that pair to a deployment
    base rate and the per-campaign row it persists in — three repairs
    that send the operator to different places (a sidecar that never
    answered a pick, a population that was empty or one-sided, a corner
    the reweighting has no answer for and a store that would not take
    the write), and folding any two would send an operator tuning one
    repair when the thing to fix was another.

    No partial value escapes a refusal: the verb either answers one bare
    ``float`` or raises, so a caller can never hold a half-reweighted
    figure it must remember to discard — the guarantee every figure this
    member answers inherits — and no label is any the closer for the
    widening: the pair is handed over already measured, and the store
    this error guards never holds a sidecar key.
    """


class ErrorAccountingError(ScoringError):
    """An error accounting whose two figures cannot be kept apart
    (feature 269).

    The ask was malformed in this seam's own inputs — a scorer that
    exposes no callable ``null_pick_rate`` (the wiring fault, named
    before anything is read), an ``explored`` collection that is not the
    revealed prefix's facts (a mapping's keys are not its nodes, a bare
    string is one node spelled where the collection belongs), a node
    that names no node, carries a depth that is not a non-negative
    integer or a flip depth that is not an integer at least 1 (the
    geometric's support, below which a root would flip), a node whose
    branch carries no drawn flip (its position past it is *unknown*, and
    reading it as below would deflate the one figure the count exists
    to charge), a node carried twice (the revealed prefix is a set, and
    a duplicate would double-count one error), a process that fails
    while being asked (translated, with the original chained), or a
    process that answers a figure outside ``[0, 1]`` — a count of null
    picks being the likeliest thing wearing the rate's name, which the
    process's own law refuses to let out and the value refuses to
    receive — and the refusal names which, because the repairs differ:
    the caller's wiring against the join that resolved the branches
    against the deployment's sidecar against a process that answered a
    number nobody measured.

    Beside :class:`~scoring.NullPickRateError` and
    :class:`~scoring.NullPickPenaltyError`, never under either: 258
    refuses a *charge* that cannot be made on a rate the caller already
    holds, 265 refuses the *rate* itself, and this class refuses the
    *split accounting* — the two-figure answer prd §4.1.2 mandates and
    docs §7.3.1 says conflating *"was the original design's blind
    spot"*.  The three repairs send the operator to different places (a
    mis-set coefficient against a sidecar that is absent, unopenable or
    holds no entry for a pick, against a join that handed the accounting
    branches it had no flips for), and folding them would send an
    operator tuning β₂ when the thing to fix is that the Type-B facts
    never arrived.  A process that refuses the picks themselves refuses
    in 265's vocabulary, propagated untranslated through this seam —
    the pick law is 265's and so is its repair.

    No partial value escapes a refusal: the verb either answers a frozen
    :class:`~scoring.ErrorAccounting` or raises, so a caller can never
    hold a half-counted accounting it must remember to discard — the
    guarantee :class:`WorldObjectiveError` makes one feature earlier and
    the one every figure this member answers inherits.
    """
