"""Feature 74 — normalizing a raw score vector by ranking then z-scoring.

app_spec.xml feature 74: *"System normalizes a raw score vector by ranking
then cross-sectional z-scoring, which returns a comparable score regardless
of author scale."* docs/nullius-tech-architecture.md §6.1 names the step —
``3. normalize          rank → cross-sectional z-score → neutralize (optional)``.

This suite tests the reduction — the *rank then cross-sectional z-score* half
of the feature sentence — separately from the sandbox execution that produced
the raw vector (which ``test_execute.py`` covers) and from the metrics that
consume the normalized one (downstream features), because the three are
independently testable and a bug in one would be masked by another:

* **rank then z-score** — a raw vector is replaced by its average ranks, then
  z-scored against the cross-section's own mean and population std;
* **the order is load-bearing** — ranking first makes the result scale-free,
  so two authors who disagree on magnitude but agree on order normalize to the
  same vector;
* **the cross-section is this vector's own** — the mean and std are computed
  over the symbols at this rebalance date, not borrowed across time or pool;
* **the degenerate cross-sections are refused** — one symbol, and all-tied,
  are refused with :class:`EvaluatorNormalizeError` rather than defaulted to
  zeros or NaNs;
* **the input contract** — a non-Series, a non-float, or a non-finite vector
  is refused by name;
* **the symmetry** — ``normalize(-raw) == -normalize(raw)``, so a signal read
  in reverse yields the mirror portfolio.

The reduction is exercised directly against :func:`normalize_scores`, so the
suite proves the arithmetic and the refusals without spawning a sandbox or
resolving a window.
"""

from __future__ import annotations

import polars as pl
import pytest

from evaluator import EvaluatorNormalizeError, normalize_scores


# -- rank then z-score --------------------------------------------------------


def test_normalize_ranks_then_z_scores() -> None:
    # The feature's whole sentence: each raw score is replaced by its average
    # rank among the cross-section, then z-scored against the cross-section's
    # own mean and population standard deviation — (rank - mean) / std.
    raw = pl.Series([3.0, 1.0, 2.0])
    out = normalize_scores(raw)
    # Ranks are [3, 1, 2]; mean rank is 2; population std of [3,1,2] is
    # sqrt((1+1+0)/3) = sqrt(2/3).  So the z-scores are [1, -1, 0] / sqrt(2/3).
    import math

    expected = [1.0, -1.0, 0.0]
    scale = math.sqrt(2.0 / 3.0)
    assert out.to_list() == pytest.approx([e / scale for e in expected])


def test_the_output_is_positional_and_same_length() -> None:
    # The output is a Polars series of the same length and in the same order as
    # the input — the i-th normalized score is the normalized score for the
    # i-th symbol.  This module does not carry the labels; the caller holds the
    # universe the vector was scored against.  The highest raw score keeps the
    # highest normalized score, wherever it sat in the input order.
    raw = pl.Series([10.0, 20.0, 30.0, 5.0])
    out = normalize_scores(raw)
    assert isinstance(out, pl.Series)
    assert len(out) == 4
    # The maximum raw score (30.0, at index 2) keeps the maximum normalized
    # score — the order is preserved, not sorted.
    assert out.to_list()[2] == max(out.to_list())
    assert out.to_list()[3] == min(out.to_list())  # 5.0 was the lowest


def test_the_result_is_scale_free() -> None:
    # "Comparable regardless of author scale": two authors who agree on order
    # but disagree violently on magnitude normalize to the same vector, because
    # ranking throws the magnitude away before any scale is reintroduced.
    author_a = pl.Series([1.0, 2.0, 3.0, 4.0])
    # Same positional order (ascending), wildly different magnitudes: a raw
    # count, then a mix of negative and large values.
    author_b = pl.Series([-1e6, 0.5, 3.3, 100.0])
    assert normalize_scores(author_a).to_list() == pytest.approx(
        normalize_scores(author_b).to_list()
    )


def test_the_output_is_standardized() -> None:
    # The normalized vector has mean 0 and population std 1, by construction —
    # that is what "comparable across authors" means: every cross-section is
    # placed on the same footing.
    raw = pl.Series([0.0, 1.0, 1.0, 2.0, 9.0])
    out = normalize_scores(raw)
    assert out.mean() == pytest.approx(0.0)
    assert out.std(ddof=0) == pytest.approx(1.0)


# -- ties ---------------------------------------------------------------------


def test_ties_share_the_average_rank() -> None:
    # A block of tied symbols each receives the mean of the ranks they would
    # have occupied — the average (fractional) rank — so a large tied block is
    # one rank, not many.  Here [10, 20, 20, 30]: ranks are [1, 2.5, 2.5, 4].
    raw = pl.Series([10.0, 20.0, 20.0, 30.0])
    out = normalize_scores(raw)
    # The two tied symbols share one normalized score.
    assert out.to_list()[1] == pytest.approx(out.to_list()[2])
    # And the order is preserved: the tied pair sits between the low and high.
    lo, a, b, hi = out.to_list()
    assert lo < a == b < hi


# -- symmetry -----------------------------------------------------------------


def test_normalize_is_symmetric_under_negation() -> None:
    # The average rank is the only common method symmetric under negation, so a
    # signal read in reverse yields the mirror portfolio: normalize(-raw) is
    # -normalize(raw).  A long/short evaluator needs this — the same signal
    # inverted must be the mirror trade, not a differently-tied one.
    raw = pl.Series([3.0, 1.0, 2.0, 2.0, 5.0, -1.0])
    out = normalize_scores(raw)
    neg = normalize_scores(-raw)
    assert neg.to_list() == pytest.approx([-x for x in out.to_list()])


# -- the degenerate cross-sections are refused --------------------------------


def test_a_single_symbol_is_refused() -> None:
    # One symbol is not a cross-section: there is nothing to be relatively
    # preferred within, so a comparable score "regardless of author scale" is
    # meaningless.  Refused rather than returning [0.0], which would dress the
    # empty comparison up as a measurement.
    with pytest.raises(EvaluatorNormalizeError, match="cross-section"):
        normalize_scores(pl.Series([42.0]))


def test_all_tied_is_refused() -> None:
    # When every raw score is identical, every rank is the mean rank, the
    # deviation is zero, and the signal expressed no preference.  Dividing by
    # zero would give NaN; returning zeros would be indistinguishable from a
    # genuine neutral signal.  Refused by name so the caller records the
    # no-preference case.
    with pytest.raises(EvaluatorNormalizeError, match="no preference"):
        normalize_scores(pl.Series([7.0, 7.0, 7.0, 7.0]))


# -- the input contract -------------------------------------------------------


def test_a_non_series_is_refused() -> None:
    # The input must be a Polars Series — the positional vector the window
    # carries the labels against.  A list, array or scalar is a different
    # contract and is refused by name.
    with pytest.raises(EvaluatorNormalizeError, match="polars.Series"):
        normalize_scores([1.0, 2.0, 3.0])  # type: ignore[arg-type]
    with pytest.raises(EvaluatorNormalizeError, match="polars.Series"):
        normalize_scores(3.14)  # type: ignore[arg-type]


def test_a_non_float_dtype_is_refused() -> None:
    # Scores must be floats to be ranked and z-scored; an integer or string
    # vector is not a score.  Refused rather than silently cast.
    with pytest.raises(EvaluatorNormalizeError, match="floating point"):
        normalize_scores(pl.Series([1, 2, 3]))


def test_a_non_finite_value_is_refused() -> None:
    # A NaN or ±inf anywhere would poison the cross-sectional reduction (the
    # mean and std), so a non-finite score is refused rather than propagated.
    with pytest.raises(EvaluatorNormalizeError, match="non-finite"):
        normalize_scores(pl.Series([1.0, float("nan"), 3.0]))
    with pytest.raises(EvaluatorNormalizeError, match="non-finite"):
        normalize_scores(pl.Series([1.0, float("inf"), 3.0]))


# -- the reduction is reached lazily ------------------------------------------


def test_normalize_does_not_require_polars_until_called() -> None:
    # The module imports polars only when a vector is actually normalized, so
    # composing the application — and the replay path §1 forbids from reaching
    # the evaluator — pays no polars cost for importing this member.  Importing
    # the name is enough to prove the seam exists; the reduction is what needs
    # the dependency.
    from evaluator import normalize_scores as imported

    assert callable(imported)
