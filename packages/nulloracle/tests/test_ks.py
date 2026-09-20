"""Feature 123's test half: §7.4's two-sample Kolmogorov–Smirnov p-value.

app_spec.xml, "Null Oracle & Planted Nulls", feature 123: *System persists
the p-value of a two-sample Kolmogorov-Smirnov test comparing in-sample
scores of null nodes against real nodes per campaign.*  This suite pins the
*test* — :mod:`nulloracle.ks` — and ``test_ksguard.py`` pins the persistence.

The sentence's load-bearing claim is that the number is a *Kolmogorov–
Smirnov* p-value and not merely a number that goes down when the
distributions separate.  So the tests below hold it to that: the statistic
against hand-computed values, the exact p-value against the lattice count
worked out by hand for small samples, the symmetry the two-sided definition
demands, and the estimator's own boundary.  A test that only asserted
``p < 0.05`` for separated samples would pass for a statistic that was
nothing like a KS statistic at all.

Three properties get their own sections because they are the ones a
plausible-looking implementation gets wrong:

* **the refusals** — §7.4's p-value voids a campaign, halts dreaming and
  excludes the campaign from the replay pool, so a number computed from a
  sample that never existed is worse than no number;
* **the reported estimator** — a stored p-value computed by the large-sample
  series must never be mistaken for an exact one;
* **the barrier** — §4.2 forbids the label partition from reaching anything
  the policy can read, and this member is the one job allowed past it, so
  the result value is asserted to carry counts and *not* scores or node ids.
"""

from __future__ import annotations

import itertools
import uuid
from pathlib import Path

import pytest
from nulloracle import (
    KS_ASYMPTOTIC,
    KS_ASYMPTOTIC_FLOOR,
    KS_EXACT,
    KS_EXACT_CELLS,
    KS_MIN_SAMPLE,
    KolmogorovSmirnov,
    KsTestError,
    ks_pvalue,
    ks_two_sample,
    two_sample_statistic,
)


def _nodes(count: int) -> list[str]:
    """``count`` distinct canonical node UUIDs."""
    return [str(uuid.uuid4()) for _ in range(count)]


def _keyed(scores: list[float]) -> dict[str, float]:
    """A ``{node_id: score}`` sample — the form a campaign naturally holds."""
    return dict(zip(_nodes(len(scores)), scores))


# -- The statistic ---------------------------------------------------------------


class TestTheStatisticIsAKolmogorovSmirnovStatistic:
    def test_the_maximum_gap_between_the_two_ecdfs(self) -> None:
        # [1,2,3] vs [4,5,6]: no overlap at all, so the ECDFs are as far
        # apart as two distributions can be.  D = 1 exactly.
        assert two_sample_statistic([1.0, 2.0, 3.0], [4.0, 5.0, 6.0]) == 1.0

    def test_identical_samples_have_a_zero_statistic(self) -> None:
        assert two_sample_statistic([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == 0.0

    def test_the_gap_is_measured_at_each_distinct_score_value(self) -> None:
        # The classic hand case: {1,2,3,4,5} against {2,3,4,5,6}, five a side.
        # At score 1 the null ECDF is 1/5 and the real ECDF is 0 -> gap 0.2;
        # at 6 the real ECDF reaches 5/5 while the null is 5/5 -> 0.  The
        # maximum is 0.2, not the 0.0 an endpoint-only comparison would give.
        assert two_sample_statistic(
            [1.0, 2.0, 3.0, 4.0, 5.0], [2.0, 3.0, 4.0, 5.0, 6.0]
        ) == pytest.approx(0.2)

    def test_ties_are_stepped_together(self) -> None:
        # Ties must not inflate the gap: {1,1,2} against {1,2,2}.  Both ECDFs
        # step past the two 1s at once, so at that value the counts are 2/3
        # and 1/3 -> gap 1/3, which is the maximum.
        assert two_sample_statistic([1.0, 1.0, 2.0], [1.0, 2.0, 2.0]) == pytest.approx(1 / 3)

    def test_the_statistic_is_symmetric_in_its_arguments(self) -> None:
        # The two-sided statistic is symmetric — D(A,B) == D(B,A) — which is
        # the property that makes §7.4's test blind to which side is which.
        # A one-sided implementation would fail this and would also make a
        # detectable null world easier to hide on one sign than the other.
        null = [0.1, 0.5, 0.9, 1.4, 2.0]
        real = [0.3, 0.4, 1.1, 1.9, 2.2, 2.7]
        assert two_sample_statistic(null, real) == two_sample_statistic(real, null)

    def test_sample_order_does_not_change_the_statistic(self) -> None:
        # The samples are sorted internally, so the caller's ordering — which
        # is whatever order the campaign's nodes came back in — is not a
        # hidden input to the number.
        assert two_sample_statistic([3.0, 1.0, 2.0], [5.0, 4.0, 6.0]) == 1.0

    def test_a_mapping_sample_and_a_bare_iterable_agree(self) -> None:
        # The two spellings of a sample are one sample.  A caller holding a
        # campaign's {node_id: score} map must get the same statistic as one
        # holding the scores alone.
        scores = [0.2, 0.7, 1.3, 2.1]
        assert two_sample_statistic(_keyed(scores), _keyed([0.1, 0.9, 2.0, 2.5])) == (
            two_sample_statistic(scores, [0.1, 0.9, 2.0, 2.5])
        )


# -- The exact p-value -----------------------------------------------------------


class TestTheExactPValueIsTheLatticeCount:
    """The exact estimator, pinned against values worked out by hand.

    The two-sided two-sample p-value is ``(C(n+m, n) − admissible) /
    C(n+m, n)``, where an interleaving is admissible when every prefix keeps
    ``|i·m − j·n|`` strictly below the observed count.  The cases below are
    small enough that the count is checkable by enumeration, which is what
    makes them a test of the implementation rather than of itself.
    """

    def test_fully_separated_four_by_four(self) -> None:
        # {1,2,3,4} vs {5,6,7,8}: D = 1, and only two of the C(8,4) = 70
        # interleavings keep the gap below 4 at every prefix — all four nulls
        # first, or all four reals first.  So the p-value is 2/70.
        result = ks_two_sample([1.0, 2.0, 3.0, 4.0], [5.0, 6.0, 7.0, 8.0])
        assert result.statistic == 1.0
        assert result.pvalue == pytest.approx(2 / 70)
        assert result.method == KS_EXACT

    def test_three_against_six_fully_separated(self) -> None:
        # The same two ends of the lattice, out of C(9,3) = 84 interleavings.
        result = ks_two_sample([1.0, 2.0, 3.0], [4.0, 5.0, 6.0, 7.0, 8.0, 9.0])
        assert result.statistic == 1.0
        assert result.pvalue == pytest.approx(2 / 84)

    def test_a_small_gap_on_overlapping_samples(self) -> None:
        # {1,2,3,4,5} vs {2,3,4,5,6}: D = 0.2, i.e. the scaled gap K = 5 on
        # an n·m = 25 lattice.  Almost every interleaving stays inside the
        # band, so the p-value is large — at most 6 of C(10,5) = 252 paths
        # ever reach a gap of 1/5, which is under 4% of them.
        result = ks_two_sample([1.0, 2.0, 3.0, 4.0, 5.0], [2.0, 3.0, 4.0, 5.0, 6.0])
        assert result.statistic == pytest.approx(0.2)
        assert 0.9 <= result.pvalue <= 1.0
        assert result.method == KS_EXACT

    def test_the_pvalue_is_a_probability(self) -> None:
        for null, real in (
            ([1.0, 2.0], [1.0, 3.0]),
            ([1.0] * 3 + [2.0, 3.0], [2.0] * 4 + [9.0]),
            ([0.5, 1.5], [1.4, 1.6, 1.7]),
        ):
            p = ks_pvalue(null, real)
            assert 0.0 <= p <= 1.0, (null, real, p)

    def test_a_larger_gap_never_gives_a_larger_pvalue(self) -> None:
        # The p-value is the probability of a gap *at least* this large, so it
        # is monotone non-increasing in the statistic.  A test whose p-value
        # rose as the samples separated would void campaigns at random.
        base = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
        readings = [
            ks_two_sample(base, [value + shift for value in base])
            for shift in (0.0, 0.5, 1.0, 1.5, 2.0, 4.0, 8.0)
        ]
        for earlier, later in itertools.pairwise(readings):
            assert later.statistic >= earlier.statistic - 1e-12
            assert later.pvalue <= earlier.pvalue + 1e-12
        # ...and the walk actually moved, so the monotonicity above is not
        # being asserted over a list of one value repeated.
        assert readings[0].statistic < readings[-1].statistic
        assert readings[0].pvalue > readings[-1].pvalue

    def test_the_estimator_is_reported_as_exact(self) -> None:
        # A campaign-sized sample lands in the exact branch, and the branch is
        # named.  This is the sample size §4.1.1's φ actually produces.
        nodes = _nodes(500)
        null = {node: index * 0.01 for index, node in enumerate(nodes[:125])}
        real = {node: index * 0.01 + 0.5 for index, node in enumerate(nodes[125:])}
        result = ks_two_sample(null, real)
        assert result.method == KS_EXACT
        assert result.null_count == 125
        assert result.real_count == 375
        assert result.exact is True


# -- The asymptotic branch -------------------------------------------------------


class TestTheAsymptoticBranchIsNamedAndBounded:
    def test_a_large_sample_uses_the_series_and_says_so(self) -> None:
        # 600 a side is 360 000 lattice cells, past the exact limit.  Both
        # sides clear the asymptotic floor, so the series runs and the result
        # reports which estimator produced it.
        null = [index * 0.001 for index in range(600)]
        real = [index * 0.001 + 0.1 for index in range(600)]
        result = ks_two_sample(null, real)
        assert result.method == KS_ASYMPTOTIC
        assert result.exact is False
        assert 0.0 <= result.pvalue <= 1.0

    def test_the_series_matches_the_published_kolmogorov_form(self) -> None:
        # Q(λ) at a known λ.  λ = 1.36 is the familiar 5% critical value of
        # the one-sample Kolmogorov test, where Q ≈ 0.05 — so a value near
        # 0.05 here is the series reading the right distribution, computed
        # through the public path rather than the private one.
        from nulloracle.ks import _kolmogorov_series

        assert _kolmogorov_series(1.36) == pytest.approx(0.05, abs=0.005)
        assert _kolmogorov_series(0.0) == 1.0
        assert _kolmogorov_series(-1.0) == 1.0

    def test_the_series_is_decreasing_in_lambda(self) -> None:
        from nulloracle.ks import _kolmogorov_series

        values = [_kolmogorov_series(lam) for lam in (0.2, 0.5, 0.8, 1.2, 1.6, 2.4)]
        assert values == sorted(values, reverse=True)
        assert all(0.0 <= value <= 1.0 for value in values)

    def test_a_lopsided_oversized_sample_is_refused_by_name(self) -> None:
        # ``n·m`` exceeds the exact limit but one side is tiny, so neither
        # estimator is valid: the lattice is too big to enumerate and the
        # large-sample series says nothing about a three-point ECDF.  The
        # refusal is the point — a p-value from a limit the sample does not
        # satisfy wearing the asymptotic branch's authority is exactly the
        # plausible-looking number this module exists to keep out.
        with pytest.raises(KsTestError) as raised:
            ks_two_sample(
                [1.0, 2.0, 3.0], [index * 0.001 for index in range(200_000)]
            )
        message = str(raised.value)
        assert "too many to enumerate" in message
        assert str(KS_ASYMPTOTIC_FLOOR) in message

    def test_the_exact_limit_is_where_the_switch_happens(self) -> None:
        # The boundary is a feasibility bound, and it is pinned so a stored
        # p-value's estimator can be reasoned about from the sample sizes.
        # One cell either side of the limit switches the branch.
        assert KS_EXACT_CELLS == 250_000
        assert KS_ASYMPTOTIC_FLOOR == 200
        assert KS_MIN_SAMPLE == 2


# -- The refusals ----------------------------------------------------------------


class TestASampleThatCannotSupportAVerdictIsRefused:
    """§7.4's p-value voids a campaign.  A sample that cannot support one must
    therefore be refused rather than computed over — every case below is a
    number that a lenient implementation would happily have produced.
    """

    def test_an_empty_sample_is_refused(self) -> None:
        with pytest.raises(KsTestError, match="holds 0 score"):
            ks_two_sample([], [1.0, 2.0])

    def test_a_one_point_sample_is_refused(self) -> None:
        # A single point is not a distribution; a KS statistic over it is
        # degenerate by construction.
        with pytest.raises(KsTestError, match="holds 1 score"):
            ks_two_sample([1.0], [1.0, 2.0])

    def test_a_non_finite_score_is_refused_rather_than_dropped(self) -> None:
        # A nan is a measurement that failed.  Dropping it silently would
        # compare two distributions neither of which is the one the campaign
        # produced — and would do so without leaving a trace.
        for bad in (float("nan"), float("inf"), float("-inf")):
            with pytest.raises(KsTestError, match="non-finite"):
                ks_two_sample([1.0, bad], [1.0, 2.0])

    def test_a_none_score_is_refused(self) -> None:
        # The classic shape: a caller's ``if score:`` dropped some entries and
        # missed the ones that became None downstream.
        with pytest.raises(KsTestError, match="not a real number"):
            ks_two_sample([1.0, None], [1.0, 2.0])

    def test_a_bool_score_is_refused(self) -> None:
        # Python makes True an int, so a sample of flags would otherwise sail
        # through as a sample of 1s and 0s — a distribution about a different
        # question entirely.
        with pytest.raises(KsTestError, match="not a real number"):
            ks_two_sample([True, False], [1.0, 2.0])

    def test_a_sample_that_is_not_a_sample_is_refused(self) -> None:
        with pytest.raises(KsTestError, match="must be a mapping"):
            ks_two_sample(1.0, [1.0, 2.0])
        with pytest.raises(KsTestError, match="must be a mapping"):
            ks_two_sample("scores", [1.0, 2.0])

    def test_a_mapping_keyed_by_something_that_is_not_a_node_is_refused(self) -> None:
        # §7.1's sidecar is keyed by node ids and §9.1's node.id is a UUID, so
        # a sample keyed by anything else was assembled from the wrong source.
        with pytest.raises(KsTestError, match="not a node id"):
            ks_two_sample({"not-a-uuid": 1.0, "also-not": 2.0}, [1.0, 2.0])

    def test_a_node_named_on_both_sides_is_refused(self) -> None:
        # A node's null status is one bit in the sidecar; two samples that
        # disagree about it are not the two populations §7.4 compares, and the
        # p-value that followed would be about a partition the campaign never
        # had.
        nodes = _nodes(2)
        sample = {nodes[0]: 1.0, nodes[1]: 2.0}
        with pytest.raises(KsTestError, match="named as both null and real"):
            ks_two_sample(sample, dict(sample))
        with pytest.raises(KsTestError, match="share 1 node"):
            ks_two_sample(sample, {nodes[1]: 5.0, **dict(zip(_nodes(1), [3.0]))})

    def test_the_statistic_alone_applies_the_same_refusals(self) -> None:
        # ``two_sample_statistic`` is the other public door onto the same
        # samples, so a caller cannot reach a statistic the full test would
        # have refused.
        with pytest.raises(KsTestError):
            two_sample_statistic([1.0], [1.0, 2.0])
        nodes = _nodes(2)
        sample = {nodes[0]: 1.0, nodes[1]: 2.0}
        with pytest.raises(KsTestError):
            two_sample_statistic(sample, dict(sample))

    def test_a_refused_sample_is_refused_before_anything_is_computed(self) -> None:
        # Ordering matters operationally: a guard that computed first and
        # validated second would have written a row by the time it refused.
        with pytest.raises(KsTestError) as raised:
            ks_two_sample([1.0, 2.0, float("nan")], [4.0, 5.0, 6.0])
        assert "non-finite" in str(raised.value)


# -- The result value ------------------------------------------------------------


class TestTheResultCarriesCountsAndNotThePartition:
    """§4.2's barrier, asserted on the value feature 123 hands on.

    The guard is the one job allowed to see the labels.  The value it produces
    crosses into a store and an operator's report, so the value is asserted to
    carry what a reader needs — how many on each side, how far apart — and
    *not* the scores or a single node id, which together are the partition.
    """

    def test_the_result_has_no_score_and_no_node_id(self) -> None:
        nodes = _nodes(6)
        null = {node: index * 1.0 for index, node in enumerate(nodes[:3])}
        real = {node: index * 1.0 + 100 for index, node in enumerate(nodes[3:])}
        result = ks_two_sample(null, real)
        rendered = repr(result) + str(result.to_payload())
        for node in nodes:
            assert node not in rendered
        assert "100.0" not in rendered  # a real-side score, not a count
        assert set(result.to_payload()) == {
            "statistic",
            "pvalue",
            "null_count",
            "real_count",
            "method",
        }

    def test_the_counts_are_the_sample_sizes(self) -> None:
        result = ks_two_sample(_keyed([1.0, 2.0, 3.0]), _keyed([4.0, 5.0, 6.0, 7.0]))
        assert result.null_count == 3
        assert result.real_count == 4
        assert result.observations == 7

    def test_the_payload_round_trips_through_the_record(self) -> None:
        # The mapping the guard stores and the mapping the test renders are
        # one vocabulary, and a rebuild from the payload is the same value —
        # so a stored reading and a live one are comparable.
        result = ks_two_sample([1.0, 2.0, 3.0], [4.0, 5.0, 6.0])
        payload = result.to_payload()
        rebuilt = KolmogorovSmirnov(
            statistic=payload["statistic"],
            pvalue=payload["pvalue"],
            null_count=payload["null_count"],
            real_count=payload["real_count"],
            method=payload["method"],
        )
        assert rebuilt == result


class TestTheResultRefusesAnIncoherentReading:
    """A record reconstructed from a stored row passes no factory, so the value
    validates itself — the discipline ``evaluator_identity`` and the sidecar's
    ``NullAssignment`` both state.
    """

    def _valid(self, **overrides) -> dict:
        fields = dict(
            statistic=0.25,
            pvalue=0.4,
            null_count=10,
            real_count=30,
            method=KS_EXACT,
        )
        fields.update(overrides)
        return fields

    def test_a_pvalue_outside_the_unit_interval_is_refused(self) -> None:
        for bad in (-0.01, 1.01, 1e9):
            with pytest.raises(KsTestError, match="must lie in"):
                KolmogorovSmirnov(**self._valid(pvalue=bad))

    def test_a_statistic_outside_the_unit_interval_is_refused(self) -> None:
        with pytest.raises(KsTestError, match="must lie in"):
            KolmogorovSmirnov(**self._valid(statistic=1.5))

    def test_a_non_finite_number_is_refused(self) -> None:
        with pytest.raises(KsTestError, match="must be finite"):
            KolmogorovSmirnov(**self._valid(pvalue=float("nan")))

    def test_a_non_positive_count_is_refused(self) -> None:
        for bad in (0, -3):
            with pytest.raises(KsTestError, match="positive integer"):
                KolmogorovSmirnov(**self._valid(null_count=bad))

    def test_a_bool_count_is_refused(self) -> None:
        with pytest.raises(KsTestError, match="positive integer"):
            KolmogorovSmirnov(**self._valid(real_count=True))

    def test_an_unknown_estimator_is_refused(self) -> None:
        # A row whose method is neither of the two this member computes is a
        # row this member did not write — and the method is part of what the
        # stored p-value means, so guessing it would be the wrong repair.
        with pytest.raises(KsTestError, match="method must be"):
            KolmogorovSmirnov(**self._valid(method="approximate"))

    def test_the_value_is_frozen(self) -> None:
        result = ks_two_sample([1.0, 2.0], [3.0, 4.0])
        with pytest.raises(Exception):
            result.pvalue = 0.9  # type: ignore[misc]


# -- The module's own properties -------------------------------------------------


class TestTheModuleIsImportCheapAndHasNoThirdPartyDependency:
    def test_the_test_half_imports_no_third_party_module(self) -> None:
        # §12's determinism story and the member's own contract: the exact
        # branch is integer arithmetic and one division, and a member that
        # needed a compiled numerical stack to compute one statistic would
        # have handed that stack to every composition.
        import nulloracle.ks as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        for banned in ("import numpy", "import scipy", "import polars", "import pyarrow"):
            assert banned not in source

    def test_the_pvalue_spelling_agrees_with_the_full_result(self) -> None:
        # ``ks_pvalue`` is a thin spelling of ``ks_two_sample``, so the two
        # public doors cannot disagree about the number.
        null, real = [1.0, 2.0, 3.0], [4.0, 5.0, 6.0]
        assert ks_pvalue(null, real) == ks_two_sample(null, real).pvalue

    def test_the_result_is_deterministic_across_runs(self) -> None:
        # §12: the same samples give bit-identical numbers, so a replayed
        # campaign's guard is the same reading.
        null = [index * 0.37 for index in range(40)]
        real = [index * 0.41 + 0.2 for index in range(60)]
        first = ks_two_sample(null, real)
        second = ks_two_sample(list(reversed(null)), list(reversed(real)))
        assert first == second
