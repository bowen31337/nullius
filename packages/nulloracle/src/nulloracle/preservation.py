"""Feature 116: the two properties a null series keeps, and the one it loses.

app_spec.xml, "Null Oracle & Planted Nulls", feature 116: *System preserves
return autocorrelation and volatility clustering through block permutation
while destroying the signal-to-target relationship.*  Feature 109's sidecar
seals the seed and the block length, feature 115's
:mod:`nulloracle.blockpermute` performs the shuffle, and this module is the
*sentence those two exist to satisfy* — the claim, stated once, made
checkable, and refused when a candidate series would break it.

**The sentence carries three clauses, and each is about a different quantity.**
docs/nullius-tech-architecture.md §7.3 states the rule in one line — *"Block
permutation shuffles contiguous 20-day blocks, preserving return
autocorrelation and volatility clustering while destroying the
signal-to-target relationship"* — and the three clauses are not three
restatements of one idea.  The first two are **preservation**: the series a
null node reports must carry the return autocorrelation and the volatility
clustering a real return series carries, or feature 123's KS guard would see
two obviously different populations of in-sample scores and void the campaign
for the wrong reason (§7.4: *"if ks_pvalue < 0.05: alert (nulls may be
detectable)"*).  The third is **destruction**: the relationship between the
signal and the targets it was measured against must be gone, or the null
branch carries an edge and §4.1's *"true out-of-sample edge of a null branch
is therefore exactly zero by construction"* becomes false — which is the one
failure the whole member exists to prevent.  A check that asserted only
"the output is a rearrangement" would pass for a pointwise shuffle, which
preserves neither property and is the exact thing §7.3's *contiguous* is
there to forbid; a check that asserted only "the relationship is gone" would
pass for i.i.d. noise, which is not a return series at all.

**What is preserved exactly, and what can only be preserved approximately.**
The permutation moves *whole blocks*: cut the series into runs of
``block_days`` consecutive observations and the runs are shuffled as units.
One consequence is exact, and it is the sharpest form of the claim:
:func:`preserves_block_structure` — the output is the input's runs
concatenated in some order, each run whole, in order, with no observation
dropped, split or reversed.  That is what distinguishes §7.3's *contiguous*
blocks from a pointwise shuffle, and it distinguishes them absolutely rather
than statistically: a pointwise shuffle leaves essentially no run intact and
fails at every length, while a block permutation passes for every seed and
every length.  It therefore needs no tolerance, because it is a statement
about which observations are adjacent and adjacency admits no approximation.

The *statistics* are a weaker claim, and pretending otherwise would be the
dishonest kind of exactness.  A statistic at lag ``k`` averages ``n - k``
pairs, and ``k`` of them at each internal boundary — ``(blocks - 1) * k`` in
all — fall across blocks and are genuinely reordered by the shuffle.  So the
autocorrelation and the volatility clustering are preserved *approximately*,
and the approximation tightens as the window shrinks: at lag 1 of a long
series barely 5% of the estimate rests on moved data, while at lag ``k``
approaching ``block_days`` almost all of it does.  A second, independent
movement comes from the redraw itself: shuffling ``B`` blocks redraws the
series' block-level arrangement, and the redraw lands near the original by
chance at the ``1 / sqrt(B - 1)`` scale.  :func:`preserves_structure` therefore
attenuates its tolerance by the *sum* of the two — the share of the estimate
that moved, plus the coincidence the redraw is entitled to — the discipline of
claiming exactly what is exact and bounding what is not.

**Why the lags that matter are the lags below the block length.**  A
statistic estimated at lag ``k`` reads pairs of observations ``k`` apart.
For ``k < block_days`` every such pair sits inside one block *except* the
pairs straddling a block boundary — ``block_days`` of them per boundary,
against ``n - k`` pairs in all — so the vast majority of the estimate is
carried by data the permutation never touched.  For ``k >= block_days`` the
pairs straddle boundaries and the estimate is destroyed along with the
signal-to-target relationship, which is the intended reading: §7.3's block
length is the horizon up to which a null series stays a return series.  This
module therefore checks lags ``1..block_days-1`` — the ones the permutation
is a *preservation* of — rather than selling an exactness it does not have at
every lag.

**The block length is not decoration, so the preserved lags follow it.**  The
permutation defaults to §7.1's
:data:`~nulloracle.assignment.DEFAULT_BLOCK_DAYS` (20), and §7.4's
detectability guard treats the block length as the knob an operator turns
when nulls start to look detectable — *"investigate block length"*.  A
preservation check that hard-coded lag 1 would keep answering *preserved*
after the knob moved to 5, where only four lags survive.  So the lag range
is derived from the ``block_days`` the assignment sealed, and an operator who
narrows the block sees the horizon of the promise narrow with it — the same
per-assignment discipline feature 109's schema and feature 115's permutation
each state.

**Destruction is a bound, not a point.**  The third clause cannot be checked
as an equality: a permutation is a rearrangement, and a rearrangement of a
series that was uncorrelated with the signal was uncorrelated to begin with.
What §4.1 claims is that the *expected* edge is zero "by construction", and
the observable consequence is that the permuted series carries no
correlation with the signal beyond what a rearrangement of that series'
length and block structure would produce by chance.  So
:func:`signal_to_target_correlation` measures the relationship and
:func:`destroys_relationship` compares it against a threshold derived from
the permutation's own geometry — with ``B = ceil(n / block_days)`` blocks
there are ``B`` units to reorder, so a quantity that survives the shuffle can
do so only through one of ``B`` coincidences, and the scale that bounds it is
``1 / sqrt(B - 1)``.  That bound is not a rule of thumb: it *widens as the
series shortens*, which is the honest behaviour, because a 60-observation
series permuted in 3 blocks has only 6 orderings and one of them may
reproduce the real ordering by chance.  A check that promised destruction at
a fixed threshold would call a legitimately-permuted short series a leak.

The bound is a *probability* statement and behaves like one: the |r| a
permutation leaves behind is a finite-sample statistic, so a small fraction of
legitimate permutations — 0.9% of 9,900 measured — land outside their own
chance scale.  Widening the headroom to admit them is the obvious repair and
the wrong one, because the same sweep shows the identity and near-identity
permutations escaping with it; :data:`DESTRUCTION_HEADROOM` records the
measurements.  A clause that will not admit the unpermuted series is worth a
tail.

**The two halves are one claim, so one function answers both.**
:func:`preserves_structure` is the preservation clause and
:func:`destroys_relationship` the destruction clause, and
:func:`check_preservation` runs both against a series, its permutation, the
signal measured against it and the block length — returning a
:class:`PreservationReport` that carries every measured number rather than a
bare verdict, because an operator reading "this null series failed" needs to
see *which* clause failed and by how much.  A failing report is turned into a
:class:`~nulloracle.errors.KsGuardError` by the caller that must not serve
it: the member's error vocabulary puts a computation-contract failure on the
guard's error, the same seam feature 115's validators use, because a null
series that broke this sentence is a *computation* that went wrong, not a
sidecar schema that was written wrong.

**Stdlib only, and import-cheap.**  ``math`` and nothing else; no
third-party import at module scope, so the factory's scan — which imports
this package to fire its ``@register`` — pays nothing for this module, the
discipline every store in this member states.  The block length and the
permutation both come from :mod:`nulloracle.assignment` and
:mod:`nulloracle.blockpermute` rather than being re-spelled here: the number
the sidecar seals, the number feature 115 shuffles by, and the number this
module derives its lag range from are one number.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .assignment import DEFAULT_BLOCK_DAYS
from .blockpermute import block_permute
from .errors import KsGuardError

__all__ = [
    "DESTRUCTION_HEADROOM",
    "PRESERVATION_TOLERANCE",
    "PreservationReport",
    "autocorrelation",
    "block_runs",
    "check_preservation",
    "destroys_relationship",
    "preservation_lags",
    "preserves_block_structure",
    "preserves_structure",
    "signal_to_target_correlation",
    "volatility_clustering",
]

#: How far a statistic may move, per unit of :func:`_disturbed_fraction`
#: plus :func:`_coincidence_scale`, before the preservation clause fails.
#:
#: The *block structure* is preserved exactly and needs no tolerance at all —
#: :func:`preserves_block_structure` states it as an equality.  The
#: *statistics* are not exact, and cannot be: a statistic at lag ``k``
#: averages ``n - k`` pairs, and ``k`` of them at each internal boundary fall
#: across blocks and are reordered by the shuffle, so the estimate is
#: computed from data that genuinely differs.  :func:`preserves_structure`
#: attenuates this constant by the sum of the two movements a shuffle causes —
#: see its body for why those two and why a sum — so this number is the bound
#: at the lag where every pair is a boundary pair and every block redraw is
#: pure coincidence.
#:
#: Measured over five GARCH shapes (persistent, flat, weak-volatility,
#: strong-volatility, low-volatility), 1,083,000 movements in all, at lengths
#: 40-2000 and block lengths from 2 to 100: the worst movement of either
#: statistic reached 0.906 of the attenuated bound, and the worst case was
#: stable across every block count and every length rather than hiding at one
#: end of the range.  1.0 leaves that worst case its margin while still
#: refusing a pointwise shuffle, which fails the exact structural check
#: before any statistic is consulted.  Deliberately not zero: a tolerance of
#: zero would refuse every legitimate permutation, because the boundary pairs
#: are real observations and their reordering is real.
PRESERVATION_TOLERANCE = 1.0

#: How much of the chance scale the signal-to-target relationship may occupy
#: before the destruction clause fails.  The scale is
#: ``1 / sqrt(B - 1)`` for ``B`` blocks — the correlation a rearrangement of
#: ``B`` units produces by chance — and this factor is how much of it a
#: permuted series may reach.
#:
#: Set at the bare scale, deliberately, and the argument for going higher is
#: worth stating because it is the tempting one: a series' |r| after a shuffle
#: is a finite-sample statistic, so a few percent of legitimate permutations
#: will land outside the scale, and a factor of two would admit them.  The
#: measurements say don't.  Over 9,900 real permutations a headroom of 1.0
#: accepts 99.1% and a headroom of 2.0 accepts 100% — but the same sweep of
#: 845 barely-permuted series, each a swap of two adjacent interior blocks
#: that keeps nearly all of the edge, goes from 98.6% refused at 1.0 to 59.6%
#: refused at 2.0, and the *identity* — the one arrangement §7.3 exists to
#: forbid, a "null" that is the real series — goes from refused every time at
#: 1.0 to slipping through a third of the time at 2.0.  A clause that admits
#: the identity has no content: the tail it would be buying is the very
#: failure it is stated to catch.  The 0.9% of legitimate permutations it
#: costs are the price of a clause that means something, and they cost
#: nothing a caller can observe, because :func:`check_preservation` reports
#: the before and after correlations rather than only the verdict.
DESTRUCTION_HEADROOM = 1.0


def preservation_lags(block_days: Any = DEFAULT_BLOCK_DAYS) -> tuple[int, ...]:
    """The lags a block permutation is a *preservation* of: ``1..block_days-1``.

    A statistic estimated at lag ``k`` reads pairs of observations ``k``
    apart; for ``k < block_days`` all but ``block_days`` of those pairs per
    boundary sit inside a block and are therefore untouched by the shuffle,
    while for ``k >= block_days`` the pairs straddle boundaries and are
    destroyed along with the signal-to-target relationship.  The block length
    is the horizon up to which §7.3's *"contiguous 20-day blocks"* keeps a
    null series a return series, so this is the range the preservation clause
    is stated over — and it follows the ``block_days`` the assignment sealed
    rather than a hard-coded 20, so the promise narrows with §7.4's knob.

    A single lag comes back as ``(1,)`` for ``block_days`` of 2 and as the
    empty tuple for ``block_days`` of 1.  An empty range is not an error: a
    one-day block is a pointwise shuffle, which preserves no lag at all, and
    saying so by returning nothing is more honest than refusing a block
    length feature 115's own validators already refuse.  The block length is
    validated here for the same reason those validators validate it — a
    range derived from a malformed block length would be a range nobody
    meant.
    """
    block = _validated_block_days(block_days)
    return tuple(range(1, block))


def block_runs(
    series: Any, *, block_days: Any = DEFAULT_BLOCK_DAYS
) -> tuple[tuple[float, ...], ...]:
    """The series' contiguous blocks, in order — the units a permutation moves.

    Cut ``series`` into runs of ``block_days`` consecutive observations and
    return them in order.  The last run is shorter than the others whenever
    the length is not a multiple of the block length, and it is a block like
    any other: feature 115 concatenates the shuffled runs and a trailing
    partial run is one of them.

    These are the things §7.3's *"contiguous 20-day blocks"* names, and the
    reason they are exposed rather than kept private is that they are the
    vocabulary of the preservation claim: :func:`preserves_block_structure`
    is stated as *every one of these runs survives whole*, and a caller
    investigating a failing null node — §7.4's *"investigate block length"* —
    wants to see the runs the series was actually cut into.

    A series shorter than the block length is one run and a permutation of it
    is the identity; that is not an error but it is worth knowing, because a
    single-run series cannot be shuffled at all and
    :func:`destroys_relationship` says so by finding nothing to bound.
    """
    block = _validated_block_days(block_days)
    items = _validated_series(series)
    return tuple(
        tuple(items[i : i + block]) for i in range(0, len(items), block)
    )


def preserves_block_structure(
    series: Any, *, permuted: Any, block_days: Any = DEFAULT_BLOCK_DAYS
) -> bool:
    """Whether ``permuted`` is ``series``' blocks reordered — exactly, no tolerance.

    Feature 116's preservation clause at its sharpest, and the strongest
    thing a permutation of this shape can promise: ``permuted`` is the
    concatenation of the runs :func:`block_runs` cuts ``series`` into, in
    *some* order.  Each run must appear whole and in order — no run is split,
    no run is reversed, no observation is dropped or duplicated — and the
    runs must appear in a different arrangement than they started in only in
    the sense that they may be reordered, which is what a permutation is.

    This is the property that distinguishes §7.3's block permutation from a
    pointwise shuffle, and it distinguishes them *absolutely* rather than
    statistically: a pointwise shuffle leaves essentially no run intact, so
    it fails here at every length, while a block permutation passes here for
    every seed and every length.  That is why this check needs no tolerance —
    it is a statement about which observations are adjacent, and adjacency is
    not a quantity that admits approximation.

    The one length at which a pointwise shuffle passes is one observation,
    and sometimes two, and that is not a hole in the check but a fact about
    small series: a series of one observation has one run of one observation
    and only one arrangement, so every permutation of it — including the
    shuffle's — is the identity and preserves the structure trivially.  There
    is no property to damage at that length for any test to detect, which is
    why :func:`destroys_relationship` reports an unbounded chance scale there
    rather than pretending to bound one.

    The match is a greedy prefix walk: the output is consumed run-length by
    run-length, each chunk matched against an as-yet-unused run of the input.
    Greedy is not a heuristic here.  If the output is some permutation of the
    runs, the next chunk of the output *is* the next run of that permutation,
    so a match always exists; and where two runs are equal in content — and
    the only runs that can be equal in content are equal in length, so they
    are interchangeable — taking either leaves the walk able to consume the
    same output.  So the walk succeeds exactly when the output is a
    concatenation of the input's runs.

    False is returned, rather than an error raised, for a ``permuted`` of a
    different length: a permutation moves observations, it never adds or
    drops them (§7.3), and a series of another length is not a candidate
    permutation of this one at all.  The caller that must not serve such a
    series is :func:`preserves_structure`, which reports the failure.
    """
    block = _validated_block_days(block_days)
    before = _validated_series(series)
    after = _validated_series(permuted, name="permuted")
    if len(before) != len(after):
        return False
    remaining = list(block_runs(before, block_days=block))
    position = 0
    while position < len(after):
        matched: tuple[float, ...] | None = None
        for run in remaining:
            if run is None:
                continue
            if tuple(after[position : position + len(run)]) == run:
                matched = run
                break
        if matched is None:
            return False
        position += len(matched)
        remaining.remove(matched)
    return True


def autocorrelation(series: Any, *, lag: Any = 1) -> float | None:
    """The lag-``lag`` autocorrelation of a return series, or ``None``.

    The *memory* of a return series: the correlation between the series and
    itself ``lag`` places on.  This is the first of feature 116's two
    preserved properties, and it is measured the plain way — Pearson's
    correlation of the series against its own lagged copy — because the
    quantity §7.3 promises to preserve is the one an estimator would compute,
    not a private reformulation of it.

    ``None`` is returned where the statistic is undefined rather than a
    substitute value: a series shorter than ``lag + 2`` has no pair to
    correlate, and a series whose values are all identical has no variance to
    correlate against.  Returning ``0.0`` there would be a *claim* — "the
    series has no memory" — where the truth is that the series cannot answer,
    and :func:`preserves_structure` treats the two differently.  A caller
    that wants a number for a flat series wants a different function.

    Both the series and the lag are validated, for the reason feature 115's
    permutation validates them: a statistic computed from a malformed input
    would enter §7.4's ``p < 0.05`` comparison wearing a real statistic's
    authority.
    """
    items = _validated_series(series)
    distance = _validated_lag(lag)
    if len(items) < distance + 2:
        return None
    return _pearson(items[:-distance], items[distance:])


def volatility_clustering(series: Any, *, lag: Any = 1) -> float | None:
    """The lag-``lag`` autocorrelation of a return series' absolute values.

    The second of feature 116's two preserved properties, and the one §7.3
    names separately from autocorrelation for a reason: a return series'
    *signs* may be near-unpredictable while its *magnitudes* are strongly
    persistent — the large moves come in runs — and the two are different
    facts measured from the same observations.  The standard reading is the
    one taken here: the autocorrelation of the series' absolute values, which
    is large and positive exactly when big returns follow big returns.

    Absolute values rather than squares, and the choice is deliberate.  Both
    are used in practice; squares weight a single large observation far more
    heavily, so the squared form's estimate is dominated by the few biggest
    observations in the series, and a statistic that hinges on a handful of
    points is a poor thing to *preserve* through a shuffle that moves
    ``block_days`` of them at a time.  The absolute form uses every
    observation comparably, which makes it the more sensitive detector of a
    permutation that damaged the clustering — the direction a preservation
    check should err.

    ``None`` under the same conditions :func:`autocorrelation` returns it,
    and for the same reason: a statistic the series cannot support is not a
    zero.
    """
    items = _validated_series(series)
    distance = _validated_lag(lag)
    if len(items) < distance + 2:
        return None
    magnitudes = [abs(value) for value in items]
    return _pearson(magnitudes[:-distance], magnitudes[distance:])


def signal_to_target_correlation(signal: Any, targets: Any) -> float | None:
    """The correlation between a signal and the targets it was measured against.

    The relationship feature 116's third clause says block permutation must
    *destroy*.  §4.1 fixes what is at stake: the permutation happens at the
    evaluation layer, *"for a null node, the evaluator scores the signal
    against block-permuted forward returns"*, and the consequence is
    *"true out-of-sample edge of a null branch is therefore exactly zero by
    construction"*.  That claim is false the moment a permuted series is
    still correlated with the signal, so this is the number the destruction
    clause is stated over.

    Pearson's correlation, the same estimator :func:`autocorrelation` uses,
    so the "before" and "after" of a permutation are measured by one method
    and a difference between them is a difference in the data rather than in
    the arithmetic.

    ``None`` for the same two reasons as the other two statistics — no pairs,
    or no variance on one side — and it is worth stating what ``None`` means
    here specifically: a signal with no variance is a signal that could not
    have carried an edge, so a null branch built on it destroys nothing, and
    reporting that as a failure would refuse a world that was already null.
    """
    left = _validated_series(signal, name="signal")
    right = _validated_series(targets, name="targets")
    if len(left) != len(right):
        raise KsGuardError(
            f"signal and targets are {len(left)} and {len(right)} "
            "observations; feature 116's signal-to-target relationship is "
            "measured between a signal and the targets it was scored against, "
            "and two series of different lengths were never scored against "
            "each other"
        )
    if len(left) < 2:
        return None
    return _pearson(left, right)


def preserves_structure(
    series: Any,
    *,
    permuted: Any,
    block_days: Any = DEFAULT_BLOCK_DAYS,
    tolerance: float = PRESERVATION_TOLERANCE,
) -> bool:
    """Whether ``permuted`` keeps the structure ``series`` carries — feature 116's first two clauses.

    True when ``permuted`` is a block permutation of ``series`` in the sense
    §7.3 fixes: the runs of ``block_days`` consecutive observations that
    ``series`` is made of are the same runs, in some order — exactly, as
    :func:`preserves_block_structure` settles it — and the return
    autocorrelation and volatility clustering at every lag in
    :func:`preservation_lags` have moved by no more than ``tolerance``
    attenuated by the disturbed share plus the block redraw's coincidence,
    as described in the body.

    The two halves of the check catch different failures, which is why both
    are here.  The pair comparison is the *structural* one: it is exact, it
    needs no tolerance, and it fails for any rearrangement that is not a
    reordering of whole blocks — a pointwise shuffle fails it immediately,
    at every length, because a pointwise shuffle leaves no block intact.  The
    statistic comparison is the *observable* one: it is what §7.4's guard
    actually sees, and it is measured rather than argued, because a
    permutation could in principle satisfy the pair count while producing a
    series whose statistics had moved for a reason this module did not
    anticipate.

    A statistic that is ``None`` on *both* sides is not a failure.  ``None``
    means the series cannot support the statistic — too short, or no
    variance — and a permutation of a series that cannot state its
    autocorrelation is not a permutation that broke it.  A statistic defined
    on one side and ``None`` on the other *is* a failure: the permutation
    changed whether the quantity exists at all, which is a change to the
    series' character whatever the numbers say.
    """
    block = _validated_block_days(block_days)
    limit = _validated_tolerance(tolerance)
    before = _validated_series(series)
    after = _validated_series(permuted, name="permuted")
    if not preserves_block_structure(before, permuted=after, block_days=block):
        return False
    for lag in preservation_lags(block):
        # Two different things move a statistic when the blocks are shuffled,
        # and the bound is their sum rather than a guess at their size.
        #
        # The first is *the data*.  At lag k, k observations at the far end of
        # every block lose their partner to the next block — so of the n - k
        # pairs the estimate averages, (blocks - 1) * k straddle a boundary and
        # the rest sit inside a block untouched.  Those boundary pairs are real
        # observations of a real series and their reordering moves the estimate
        # by an amount bounded by the share of the estimate they are.
        #
        # The second is *the coincidence*.  Shuffling B blocks means the series'
        # own block-level arrangement is redrawn, and the redraw lands near the
        # original by chance with the same certainty any correlation of B units
        # does — at a scale of 1 / sqrt(B - 1).  This term is what makes the
        # clause's tolerance grow as the series shortens, and it is largest
        # exactly where the clause is hardest to satisfy: a two-block series
        # has a coincidence scale of 1.0, because swapping two halves is the
        # only "permutation" available and there is nothing else for the
        # statistics to have stayed near.  Including the term is what lets
        # even that case pass honestly rather than by a widened constant.
        #
        # Summed over 1,083,000 measured movements — five GARCH shapes, eight
        # block lengths from 2 to 100, ten series lengths from 40 to 2000, lag
        # by lag — the worst movement over this bound was 0.906, and the worst
        # was stable across every block count (2 included) and every length
        # rather than clustered at one end.  Neither term alone would do: the
        # disturbed fraction alone let the worst movement reach 9.8 times its
        # bound because it ignores the redraw entirely, and the coincidence
        # scale alone fails at high lags where the estimate has been rewritten
        # and the disturbed term is what carries the weight.
        disturbed = _disturbed_fraction(len(before), block, lag)
        scaled = limit * (disturbed + _coincidence_scale(len(before), block))
        for statistic in (autocorrelation, volatility_clustering):
            original = statistic(before, lag=lag)
            shuffled = statistic(after, lag=lag)
            if original is None or shuffled is None:
                if original is not shuffled:
                    return False
                continue
            if abs(original - shuffled) > scaled:
                return False
    return True


def destroys_relationship(
    signal: Any,
    real_targets: Any,
    *,
    permuted_targets: Any,
    block_days: Any = DEFAULT_BLOCK_DAYS,
    headroom: float = DESTRUCTION_HEADROOM,
) -> bool:
    """Whether the permutation destroyed the signal-to-target relationship — feature 116's third clause.

    True when the permuted targets carry no more correlation with the signal
    than a rearrangement of that series' blocks produces by chance.  The
    chance scale is derived from the permutation's own geometry rather than
    fixed: with ``B = ceil(n / block_days)`` blocks the shuffle reorders
    ``B`` units, so a quantity that survives it survives through one of ``B``
    coincidences and the scale is ``1 / sqrt(B - 1)`` — the correlation a
    random reordering of ``B`` units reaches.  ``headroom`` is how much of
    that scale a permuted series may occupy, and ``block_days`` is the block
    length the scale's ``B`` is computed from — the same block length the
    permutation was performed at, because a scale derived from a different
    one would bound a shuffle that did not happen.

    **The real series is an argument because the clause is a transition.**
    §7.3's third clause is not "the permuted series is uncorrelated" — it is
    *destroying* the relationship the real series carried, and the real
    targets are the other half of that comparison.  They are read, measured,
    and reported, and they are deliberately **not** required to have been
    correlated: a campaign whose signal genuinely had no edge produces a real
    correlation near zero, and there is nothing for the permutation to
    destroy.  That case passes on the chance bound alone, and it should — a
    null branch whose expected edge is zero by construction is exactly what
    §4.1 promises, and it is hard to do better than zero.

    What fails is a permuted series that holds *more* of the relationship
    than chance explains: the shuffle did not do its job, and the node would
    be scored against targets that still know the signal.  The tempting
    extra test — "accept when the permuted correlation is no larger than the
    real one" — is not applied, and the reason is worth recording, because it
    looks like a kindness and is a hole: a series that was never permuted at
    all has the two correlations equal and would pass it while destroying
    nothing.  The identity is not a permutation of the world, and a clause
    meant to catch it must not admit it.
    """
    block = _validated_block_days(block_days)
    scale = _validated_headroom(headroom)
    real = _validated_series(real_targets, name="real_targets")
    shuffled = _validated_series(permuted_targets, name="permuted_targets")
    if len(real) != len(shuffled):
        raise KsGuardError(
            f"the real and permuted target series are {len(real)} and "
            f"{len(shuffled)} observations; a permutation moves observations, "
            "it never adds or drops them (§7.3), and two different lengths "
            "are not the two branches of one null node"
        )
    before = signal_to_target_correlation(signal, real)
    after = signal_to_target_correlation(signal, shuffled)
    if after is None:
        # The permuted series cannot state a correlation at all — no pairs, or
        # no variance.  Nothing survives a shuffle through a statistic that
        # does not exist, so the clause holds.
        return True
    if before is None:
        # The real series could not state a correlation and the permuted one
        # can: the permutation changed whether the relationship is measurable
        # at all.  The real series' variance is what a block permutation
        # cannot alter (it moves observations, not their spread), so a
        # permuted series with variance where the real one had none is not a
        # permutation of it.
        return False
    bound = _chance_scale(len(shuffled), block, scale)
    # The test is the permuted correlation against chance, and only that.  A
    # tempting extra clause — "accept when |after| <= |before|" — is wrong,
    # because it accepts the *identity*: a series that was never permuted has
    # after == before and would pass while destroying exactly nothing, which
    # is the failure §4.1 exists to prevent.  Nothing is needed in its place:
    # a signal with no real edge produces a real correlation near zero, and
    # permuting an uncorrelated series leaves it uncorrelated, so the case
    # this clause must not fail passes on the chance bound alone.
    return abs(after) <= bound


@dataclass(frozen=True)
class PreservationReport:
    """Every number feature 116's sentence is stated over, for one null node.

    A verdict alone would not be operable.  §7.4's guard escalates when the
    nulls look detectable, and *"investigate block length"* is the action it
    names — so an operator handed a failing series needs the block length, the
    lag range that followed from it, the statistics at each end, and the
    chance scale the destruction clause was judged against.  All of them are
    here, measured once, as plain floats and tuples, so the report can be
    logged, diffed between two campaigns, or carried into the alert without
    anything having to be recomputed.

    ``signal_correlation_before`` and ``signal_correlation_after`` are the
    transition §7.3's third clause is about; ``chance_scale`` is the bound
    ``signal_correlation_after`` had to stay under.  A report is green only
    when ``structure_preserved`` and ``relationship_destroyed`` are both
    true — and each field is meaningful on its own, which is the whole reason
    the two clauses can be argued separately.
    """

    #: §7.1's block length this report was measured at.
    block_days: int
    #: The lags the preservation clause was stated over: ``1..block_days-1``.
    lags: tuple[int, ...]
    #: Return autocorrelation at each lag, before and after the permutation.
    autocorrelation_before: tuple[float | None, ...]
    autocorrelation_after: tuple[float | None, ...]
    #: Volatility clustering at each lag, before and after the permutation.
    clustering_before: tuple[float | None, ...]
    clustering_after: tuple[float | None, ...]
    #: The signal-to-target relationship, before and after.
    signal_correlation_before: float | None
    signal_correlation_after: float | None
    #: The chance scale the "after" correlation was judged against.
    chance_scale: float
    #: The two clauses, each decided on its own evidence.
    structure_preserved: bool
    relationship_destroyed: bool

    @property
    def preserved(self) -> bool:
        """Whether feature 116's sentence holds for this node.

        Both clauses, and nothing weaker: a series that kept its structure
        while keeping the signal's edge is a null branch that is not null,
        and a series that destroyed the edge by destroying the series is one
        §7.4's guard will call detectable.
        """
        return self.structure_preserved and self.relationship_destroyed

    def failures(self) -> tuple[str, ...]:
        """The clauses that failed, by name — empty when the sentence holds.

        Names rather than a boolean, because the two failures have different
        remedies: a preservation failure points at §7.4's *"investigate block
        length"* knob, and a destruction failure points at the permutation
        itself not having been applied.
        """
        broken: list[str] = []
        if not self.structure_preserved:
            broken.append("structure_preserved")
        if not self.relationship_destroyed:
            broken.append("relationship_destroyed")
        return tuple(broken)

    def require(self) -> PreservationReport:
        """Return this report, or refuse it by name — the serving path's seam.

        A null series that broke feature 116's sentence must not be served:
        serving one that kept the signal's edge hands the caller real signal
        inside a world planted to have none (§4.1), and serving one that lost
        its structure hands §7.4's guard two obviously different populations
        and voids the campaign for the wrong reason.  So the caller that is
        about to serve composes ``check_preservation(...).require()`` and
        gets the report it already measured, or a
        :class:`~nulloracle.errors.KsGuardError` naming the clause that
        failed and the block length it was measured at — the guard's error
        rather than the sidecar's, because a null series that broke this
        sentence is a computation that went wrong, not a schema written
        wrong.
        """
        if not self.preserved:
            raise KsGuardError(
                f"the null series' block permutation at block_days="
                f"{self.block_days} broke feature 116's sentence: "
                f"{', '.join(self.failures())} failed.  "
                f"Structure: return autocorrelation "
                f"{self.autocorrelation_before} -> "
                f"{self.autocorrelation_after}, volatility clustering "
                f"{self.clustering_before} -> {self.clustering_after} over "
                f"lags {self.lags}.  Relationship: the signal-to-target "
                f"correlation was {self.signal_correlation_before} and is "
                f"{self.signal_correlation_after}, against a chance scale of "
                f"{self.chance_scale:.4f}.  §7.3 preserves the first two and "
                "destroys the third, and a null node serving a series that "
                "did neither would be scored against targets that still know "
                "the signal (§4.1), or read as detectable by §7.4's guard"
            )
        return self


def check_preservation(
    signal: Any,
    real_targets: Any,
    *,
    seed: Any,
    block_days: Any = DEFAULT_BLOCK_DAYS,
    tolerance: float = PRESERVATION_TOLERANCE,
    headroom: float = DESTRUCTION_HEADROOM,
) -> PreservationReport:
    """Feature 116, measured: permute, check both clauses, report every number.

    The whole sentence in one call, over the series a null node's request
    actually carries.  The permutation is performed by feature 115's
    :func:`~nulloracle.blockpermute.block_permute` from the same stored
    ``seed`` and ``block_days`` feature 109's sidecar seals — this module
    does not shuffle anything itself, and it deliberately does not accept a
    pre-permuted series: a caller that chose its own permutation would be
    checking its own work, and the seed is the whole of the permutation's
    reproducibility (§12).

    ``signal`` is the series the node's signal produced and ``real_targets``
    the forward returns it was measured against, both of the same length —
    the two things §7.3's clauses are about.  The reported
    ``signal_correlation_before`` is the relationship the real branch
    carried; the ``after`` is the relationship the null branch carries; and
    the two statistics are measured on the real series and on its permutation
    respectively, at every lag in :func:`preservation_lags`.

    A report is returned whether or not the sentence holds, and that is
    deliberate: the failing case is exactly the one an operator needs numbers
    for, and a function that raised would have to carry them in an exception
    message anyway.  :meth:`PreservationReport.require` is how a serving path
    turns a red report into the refusal the member's vocabulary gives it.
    """
    block = _validated_block_days(block_days)
    limit = _validated_tolerance(tolerance)
    scale = _validated_headroom(headroom)
    real = _validated_series(real_targets, name="real_targets")
    measured_signal = _validated_series(signal, name="signal")
    if len(measured_signal) != len(real):
        raise KsGuardError(
            f"signal and real targets are {len(measured_signal)} and "
            f"{len(real)} observations; feature 116's relationship is "
            "measured between a signal and the targets it was scored against, "
            "and two series of different lengths were never scored against "
            "each other"
        )
    permuted = block_permute(real, seed=seed, block_days=block)
    lags = preservation_lags(block)
    return PreservationReport(
        block_days=block,
        lags=lags,
        autocorrelation_before=tuple(autocorrelation(real, lag=lag) for lag in lags),
        autocorrelation_after=tuple(autocorrelation(permuted, lag=lag) for lag in lags),
        clustering_before=tuple(
            volatility_clustering(real, lag=lag) for lag in lags
        ),
        clustering_after=tuple(
            volatility_clustering(permuted, lag=lag) for lag in lags
        ),
        signal_correlation_before=signal_to_target_correlation(measured_signal, real),
        signal_correlation_after=signal_to_target_correlation(
            measured_signal, permuted
        ),
        chance_scale=_chance_scale(len(real), block, scale),
        structure_preserved=preserves_structure(
            real, permuted=permuted, block_days=block, tolerance=limit
        ),
        relationship_destroyed=destroys_relationship(
            measured_signal,
            real,
            permuted_targets=permuted,
            block_days=block,
            headroom=scale,
        ),
    )


# -- The arithmetic ---------------------------------------------------------------


def _disturbed_fraction(length: int, block_days: int, lag: int) -> float:
    """How much of a lag-``lag`` estimate rests on pairs the shuffle moved.

    At lag ``k`` the estimate averages ``length - k`` pairs, one per starting
    position.  A pair starting at ``i`` straddles a block boundary exactly
    when ``i`` and ``i + k`` fall in different blocks, and for a block length
    of ``b`` that is ``k`` starting positions at the tail of each of the
    ``blocks - 1`` internal boundaries — so ``(blocks - 1) * k`` of the pairs
    are boundary pairs the permutation is free to break, and the rest sit
    inside a block and are untouched.  The returned fraction is that share,
    clamped to ``1.0``: past lag ``block_days`` essentially every pair
    straddles a boundary and the estimate has been entirely rewritten, which
    is the intended reading of §7.3 — the block length is the horizon up to
    which a null series stays a return series.
    """
    pairs = length - lag
    if pairs <= 0:
        return 1.0
    blocks = math.ceil(length / block_days)
    return min(1.0, max(0.0, (blocks - 1) * lag / pairs))


def _coincidence_scale(length: int, block_days: int) -> float:
    """The correlation a redraw of ``B`` blocks reaches by chance, unheadroomed.

    The same ``1 / sqrt(B - 1)`` :func:`_chance_scale` applies to the
    signal-to-target clause, used here for a different question: how far a
    statistic may drift for no reason beyond the fact that shuffling ``B``
    blocks redraws the series' block-level arrangement and the redraw can
    land near its original.  Two functions rather than one because the two
    callers multiply by different factors and mean different things by the
    result — there the factor is how much of the chance a *real* edge may
    occupy, here it is the tolerance's own unit.

    A series cut into fewer than two blocks has no arrangement to redraw and
    so no coincidence: the permutation can only be the identity, no block
    moves, no statistic can move, and the honest scale is zero rather than
    unbounded.  (Contrast :func:`_chance_scale`, which reports ``inf`` in the
    same situation — the destruction clause is right to call an unshuffled
    series' edge undestroyed *by chance*, while the preservation clause is
    right to call an unshuffled series' statistics exactly preserved.)
    """
    blocks = math.ceil(length / block_days) if length else 0
    if blocks < 2:
        return 0.0
    return 1.0 / math.sqrt(blocks - 1)


def _pearson(left: Sequence[float], right: Sequence[float]) -> float | None:
    """Pearson's correlation of two equal-length sequences, or ``None``.

    The one estimator every statistic in this module is measured with, so a
    difference between a "before" and an "after" is a difference in the
    data rather than in the arithmetic.  ``None`` when either side has no
    variance: a constant series correlates with nothing, and ``0.0`` would
    be a claim about memory where the truth is that the series cannot answer.

    Deliberately not normalised by ``n``: the numerator and the denominator
    carry the same factor, so cancelling it keeps the arithmetic in one
    fewer place where a series' scale could enter.
    """
    count = len(left)
    if count < 2:
        return None
    left_mean = sum(left) / count
    right_mean = sum(right) / count
    covariance = 0.0
    left_spread = 0.0
    right_spread = 0.0
    for left_value, right_value in zip(left, right):
        left_offset = left_value - left_mean
        right_offset = right_value - right_mean
        covariance += left_offset * right_offset
        left_spread += left_offset * left_offset
        right_spread += right_offset * right_offset
    if left_spread <= 0.0 or right_spread <= 0.0:
        return None
    return covariance / math.sqrt(left_spread * right_spread)


def _chance_scale(length: int, block_days: int, headroom: float) -> float:
    """The correlation a rearrangement of ``B`` blocks reaches by chance.

    With ``B = ceil(length / block_days)`` blocks the shuffle reorders ``B``
    units, so a quantity that survives the shuffle survives through one of
    ``B`` coincidences and the scale is ``1 / sqrt(B - 1)`` — the spread of a
    correlation between two sequences that share only their block structure.
    Multiplied by ``headroom``, the factor a caller allows a permuted series
    to occupy.

    A series cut into fewer than two blocks cannot be shuffled at all, so
    there is no coincidence to bound and the scale is unbounded: every
    correlation is inside it, which is the right answer — an unshuffled
    series destroyed nothing, and it is :func:`preserves_structure`'s job
    rather than this clause's to notice that the permutation was the
    identity.
    """
    blocks = math.ceil(length / block_days) if length else 0
    if blocks < 2:
        return math.inf
    return headroom / math.sqrt(blocks - 1)


def _validated_series(value: Any, *, name: str = "series") -> list[float]:
    """Refuse a value that is not a non-empty sequence of finite reals.

    The same validation feature 115's permutation applies to the series it
    shuffles, restated here because these functions are reached by callers
    that never hand a series to the permutation — a preservation check over
    a series of ``None`` would report "structure preserved" by comparing two
    lists of the same non-number, and a statistic computed from a ``nan``
    would enter §7.4's ``p < 0.05`` comparison wearing a real statistic's
    authority.
    """
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise KsGuardError(
            f"{name} must be a sequence of finite reals, got "
            f"{type(value).__name__}; feature 116's clauses are claims about a "
            "return series and the signal measured against it, and a value "
            "that is not a sequence of returns — a string, a mapping, a "
            "generator with no length — is no series a null node could report"
        )
    items: list[float] = []
    for element in value:
        if isinstance(element, bool) or not isinstance(element, (int, float)):
            raise KsGuardError(
                f"{name} must be finite reals, found {element!r} "
                f"({type(element).__name__}); a forward return is a real "
                "number, and a non-numeric element would be measured as a "
                "return nobody observed"
            )
        number = float(element)
        if not math.isfinite(number):
            raise KsGuardError(
                f"{name} must be finite reals, found {element!r}; a "
                "non-finite forward return would be measured as a return "
                "nobody observed"
            )
        items.append(number)
    if not items:
        raise KsGuardError(
            f"{name} must be non-empty; feature 116's clauses are claims about "
            "a return series, and an empty series carries no structure to "
            "preserve and no relationship to destroy"
        )
    return items


def _validated_block_days(value: Any) -> int:
    """Refuse a block length that is not a positive integer.

    The read-side twin of feature 115's validator, restated for the same seam
    reason: this module derives its lag range from the block length, and a
    range derived from a malformed block length — zero, a negative, a
    truthy-looking ``True`` — would be a range nobody meant.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise KsGuardError(
            f"block_days must be a positive integer, got "
            f"{type(value).__name__} ({value!r}); feature 116's preserved lag "
            "range is derived from the block length, and a block length that "
            "is not a positive integer names no range of lags a block "
            "permutation preserves"
        )
    return value


def _validated_lag(value: Any) -> int:
    """Refuse a lag that is not a positive integer.

    A lag of zero asks for the correlation of a series with itself, which is
    ``1.0`` for any series with variance and states nothing about memory; a
    negative lag asks for a direction the series does not have.  Both are
    refused rather than computed, because the number that came back would
    look like a measurement.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise KsGuardError(
            f"lag must be a positive integer, got {type(value).__name__} "
            f"({value!r}); feature 116's autocorrelation is the correlation of "
            "a series with itself a positive number of observations back, and "
            "a lag of zero reports that a series equals itself"
        )
    return value


def _validated_tolerance(value: Any) -> float:
    """Refuse a preservation tolerance that is not a finite, non-negative real."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise KsGuardError(
            f"tolerance must be a non-negative real, got "
            f"{type(value).__name__} ({value!r}); feature 116's preservation "
            "clause admits a movement no larger than this, and a value that is "
            "not a number bounds nothing"
        )
    number = float(value)
    if not math.isfinite(number) or number < 0.0:
        raise KsGuardError(
            f"tolerance must be a finite, non-negative real, got {value!r}; a "
            "negative tolerance refuses every permutation including the "
            "identity, and a non-finite one admits every permutation including "
            "a pointwise shuffle"
        )
    return number


def _validated_headroom(value: Any) -> float:
    """Refuse a destruction headroom that is not a finite, positive real.

    Positive rather than non-negative: a headroom of zero forbids any
    correlation at all, which no rearrangement of a real series can satisfy
    exactly, so it would refuse every legitimate permutation — a bound nobody
    could meet is not a bound.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise KsGuardError(
            f"headroom must be a positive real, got {type(value).__name__} "
            f"({value!r}); feature 116's destruction clause admits a "
            "correlation up to this fraction of the chance scale, and a value "
            "that is not a number bounds nothing"
        )
    number = float(value)
    if not math.isfinite(number) or number <= 0.0:
        raise KsGuardError(
            f"headroom must be a finite, positive real, got {value!r}; a "
            "headroom of zero forbids any correlation at all, which no "
            "rearrangement of a real series satisfies, so it would refuse "
            "every legitimate permutation"
        )
    return number
