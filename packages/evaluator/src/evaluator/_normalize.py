"""Normalizing a raw score vector — pipeline step 3.

app_spec.xml feature 74: *"System normalizes a raw score vector by ranking
then cross-sectional z-scoring, which returns a comparable score regardless
of author scale."* docs/nullius-tech-architecture.md §6.1 names the step —
``3. normalize          rank → cross-sectional z-score → neutralize (optional)``
— and §5.2's worked example states the shape it takes and returns::

    raw = sandbox.run(...).scores   # pl.Series, positional against the universe
    norm = normalize(raw)           # pl.Series, same order, comparable across authors

The feature sentence has three phrases, and each is a decision this module
enforces rather than a choice it offers:

*by ranking then cross-sectional z-scoring*
    The order of the two verbs is load-bearing, and it is the order the
    sentence puts them in — rank *first*, z-score *second*.  A signal's raw
    output is on an arbitrary scale: one author emits log-odds, another emits
    a raw count of triggered events, a third emits something whose magnitude
    is meaningful only to itself.  Ranking throws the magnitude away and
    keeps only the order — the *i*-th symbol's rank among its peers — so two
    signals that agree on *which* symbols are best but disagree violently on
    *how much* are placed on the same footing before any scale is reintroduced.
    The z-score then rescales those ranks to a common, comparable metric:
    how far each symbol sits from the cross-sectional mean rank, in units of
    the cross-sectional standard deviation.  Doing it the other way —
    z-scoring the raw scores and then ranking — would be a different and
    worse feature: it would z-score a magnitude the feature exists to discard,
    and the ranking, which is the scale-free half, would be thrown away last.

*cross-sectional*
    The reduction is over the *symbols at this rebalance date*, not over time,
    not over the pool.  The mean and standard deviation are the mean and
    standard deviation of *this vector's* ranks — the cross-section the
    window handed the signal as its universe (feature 13's sorted universe,
    feature 46's stable ordering).  This is the sense in which the result is
    "comparable regardless of author scale": two authors scored against the
    same universe on the same date are each measured against that date's own
    cross-section, so a score is a statement of *relative* preference within
    one universe on one date, and nothing else.  The module does not reach
    across dates or symbols to borrow a scale — that would be the alignment
    step's job (feature 75), and it would couple one date's normalization to
    another's universe, which is exactly the look-ahead the pipeline is built
    to prevent.

*which returns a comparable score*
    The output is a :class:`polars.Series` of floats, positional against the
    input: the *i*-th normalized score is the normalized score for the *i*-th
    symbol, in the same order the raw vector carried.  The labels are not
    carried here — the window carries the labels and the series carries the
    values, positionally (feature 11, :func:`contract.signal.validate_signal_return`)
    — so this module takes and returns a bare positional vector and leaves the
    pairing to the caller, who already holds the universe the vector came from.

**The rank method, and why it is ``average``.**  Ties are not an edge case in
a signal's output — many signals saturate, round to a small set of levels, or
emit the same value for a whole block of symbols — so how ties in the raw
scores are broken is a first-order design decision, not a detail.  This module
uses the *average* (fractional) rank: symbols that tie share the mean of the
ranks they would have occupied, so a block of ``k`` tied symbols each receives
one identical rank rather than ``k`` different ones.  This is the only common
method that is *symmetric* — the ranks of a vector and of its negation are
mirror images, so ``normalize(-raw) == -normalize(raw)`` (verified), which a
long/short evaluator needs: a signal read in reverse must produce the mirror
portfolio, not a differently-tied one.  It is also the method that keeps the
sum of the ranks fixed at ``n(n+1)/2`` regardless of ties, so the mean rank is
always ``(n+1)/2`` and the z-score's centre is stable however the raw scores
cluster.  The alternatives each break one of these: ``ordinal`` invents an
order among equals, ``min``/``max`` shift the mean when ties appear, and
``dense`` collapses the spread so a large tied block dominates the deviation.

**The standard deviation, and why it is the population (``ddof=0``) form.**
The z-score here is a *definition* — the normalized score is ``(rank − mean) /
std`` — not an estimate of a larger population's spread, so the divisor is the
number of symbols ``n``, not ``n − 1``.  Using the sample form would make the
normalization depend on a statistical fiction (that these ``n`` symbols are a
random sample of some universe) that the feature does not assert, and would
rescale every score by ``sqrt(n / (n − 1))`` for no reason the document gives.
The population form is also the one whose value is fixed by the data alone:
for an untied vector of ``n`` distinct ranks the population std of the ranks
is a function of ``n`` only, so the normalization is reproducible from the
cross-section's size without reference to a sampling model.

**The degenerate cross-sections, and why they are refused, not defaulted.**
A z-score divides by the cross-sectional standard deviation, and that
deviation can be zero in exactly two cases, each of which the module refuses
with :class:`evaluator.EvaluatorNormalizeError` rather than returning zeros or
NaNs:

* *one symbol* — with ``n = 1`` there is one rank, its deviation from itself
  is zero, and "comparable across authors" is meaningless: a single symbol
  cannot be relatively preferred or dispreferred to anything.  A universe of
  one is not a cross-section; it is the empty-comparison case, and returning
  ``[0.0]`` would dress it up as a measurement.

* *all scores tied* — when every raw score is identical every rank is the
  mean rank, the deviation is zero everywhere, and the signal has expressed
  no preference at all.  Dividing by zero would give NaN; returning zeros
  would claim the signal produced a usable, comparable vector when it produced
  none.  Refusing names the condition — "the signal ranked nothing" — so the
  caller can record it as the *no-signal* case rather than persisting a vector
  of silent zeros that looks, to every downstream metric, like a real one.

The refusal is the feature: a normalized vector is only comparable when there
*was* a scale to remove, and a zero-deviation cross-section is the one place
there was not.  The alternative — a vector of zeros — is indistinguishable
from a genuine, well-behaved neutral signal, and that indistinguishability is
exactly the failure mode a comparable score must not permit.

**What this module does not do.**  It does not *neutralize* (the optional
third verb of §6.1 step 3) — removing the influence of a set of factors from
the scores is a separate, downstream concern that needs the factor exposures
this module is not given, and it is not in this feature's sentence.  It does
not align the normalized scores to targets (feature 75), apply costs (feature
79), or persist them.  It takes a raw positional score vector and returns a
normalized one, positionally, and answers exactly the one question the
pipeline puts in scope: *what is this cross-section's comparable score?*

**The layering note, and it is load-bearing.**  This module imports ``polars``
lazily, on the same seam :func:`contract._arrow.require_arrow` opens for
pyarrow and :func:`contract.signal.validate_signal_return` opens for polars.
The ``evaluator`` package is imported by the application factory's workspace
scan, so anything it imports at module scope is imported during composition —
including the replay path, which architecture §1 forbids from reaching the
evaluator at all.  A hard ``import polars`` here would make polars a
precondition for *composing the application*, a far larger blast radius than
feature 74 needs: the rank-then-z-score arithmetic is expressible without a
single float at import time, and the only thing that genuinely needs polars is
the vector reduction, reached on the normalization path.  Deferring the
import keeps the member import-safe in exactly the environments the workspace
contract promises one will be (factory scan, test sandbox, deterministic
replay path) while the reduction, which genuinely inspects a Polars series,
names the missing dependency the moment it is reached without it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ._errors import EvaluatorNormalizeError

if TYPE_CHECKING:  # pragma: no cover - typing only; polars is a runtime dependency
    import polars as pl

__all__ = ["normalize_scores"]


def _require_polars() -> "type[pl.Series]":
    """The Polars ``Series`` type, or a clear error naming how to obtain it.

    Deferred to first use rather than imported at module scope: the
    ``evaluator`` package is composed on every factory scan — including the
    replay path, which architecture §1 forbids from reaching the evaluator —
    so a hard import here would make polars a precondition for composing the
    whole application.  The reduction is the only operation that needs it, and
    it is reached only when a caller actually normalizes a vector.
    """
    try:
        import polars as pl
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency is declared
        raise EvaluatorNormalizeError(
            "normalize_scores requires polars, which the nullius-contract "
            "member declares for the signal return type; run `uv sync` "
            "(or `pip install polars`) in the workspace root"
        ) from exc
    return pl.Series


def normalize_scores(scores: Any) -> "pl.Series":
    """Normalize a raw score vector by ranking then cross-sectional z-scoring.

    Feature 74's whole sentence, as a pure function over one positional
    vector: each symbol's raw score is replaced by its *average rank* among
    the cross-section (ties share the mean of the ranks they would have
    occupied, so ``normalize(-raw) == -normalize(raw)``), and that rank is
    then turned into a z-score against the cross-section's own mean and
    population standard deviation — ``(rank − mean) / std`` — so the result is
    a comparable score regardless of the scale the signal's author chose.

    The input is a :class:`polars.Series` of finite floats, positional
    against the window's universe — the *i*-th value is the score for the
    *i*-th symbol (feature 11, the same positional contract
    :func:`contract.signal.validate_signal_return` validates a signal's
    return).  The output is a Polars series of the same length and in the same
    order: this module does not carry the labels, because the window carries
    the labels and the series carries the values, and the caller already holds
    the universe the vector was scored against.

    The reduction is refused — rather than silently defaulted — in the cases
    where a comparable score cannot be produced:

    * the input is not a Polars ``Series`` of finite floats — scores must be
      floats to be ranked and z-scored, and a NaN or ±inf anywhere would
      poison the cross-sectional reduction;
    * the vector holds a single symbol — one symbol is not a cross-section,
      so there is nothing to be relatively preferred within;
    * every raw score is identical — the signal expressed no preference, the
      cross-sectional deviation is zero, and dividing by it would return a
      vector of silent zeros indistinguishable from a genuine neutral signal.

    Each refusal names its condition, so a caller can record the *no-signal*
    case rather than persisting a fabricated measurement.
    """
    pl_series = _require_polars()

    if not isinstance(scores, pl_series):
        raise EvaluatorNormalizeError(
            f"raw scores must be a polars.Series, got {type(scores).__name__}; "
            "the evaluator ranks and z-scores a positional vector, the same "
            "shape contract.signal.validate_signal_return validates a signal's "
            "return (the i-th value is the score for the i-th symbol)"
        )

    series: "pl.Series" = scores

    if not series.dtype.is_float():
        raise EvaluatorNormalizeError(
            f"raw scores must be floating point, got dtype {series.dtype}; "
            "cast to Float64 before normalizing — the evaluator ranks and "
            "z-scores, so an integer or string vector is not a score"
        )

    finite = series.is_finite()
    if not finite.all():
        # Reported as one refusal rather than one per position: a single
        # non-finite value poisons the whole cross-sectional reduction, and
        # the caller acts on the vector, not on a position.
        raise EvaluatorNormalizeError(
            "raw scores contain a non-finite value (NaN or ±inf); scores must "
            "be finite so the cross-sectional rank-then-z-score reduction is "
            "not poisoned"
        )

    n = len(series)
    if n < 2:
        raise EvaluatorNormalizeError(
            f"cannot normalize {n} score(s): a cross-sectional z-score needs at "
            "least two symbols to be relatively preferred within — one symbol "
            "is not a cross-section, and a comparable score 'regardless of "
            "author scale' is meaningless with nothing to compare against"
        )

    # Rank first, then z-score — the order the feature names and the order the
    # scale-free half must come before the rescale.  The average (fractional)
    # rank is the only common method that is symmetric under negation, so a
    # signal read in reverse yields the mirror portfolio, and that keeps the
    # sum of the ranks fixed at n(n+1)/2 whatever the ties look like.
    ranks = series.rank(method="average")

    # The population standard deviation (ddof=0): the z-score is a definition
    # over this cross-section, not an estimate of a larger population, so the
    # divisor is n, not n - 1.  A deviation of zero here means the signal
    # expressed no preference — every rank equal — and dividing by it would
    # dress that "no signal" up as a usable measurement, so it is refused.
    mean_rank = ranks.mean()
    std_rank = ranks.std(ddof=0)
    if std_rank == 0.0:
        raise EvaluatorNormalizeError(
            "cannot normalize: every raw score is identical, so every rank is "
            "the mean rank and the cross-sectional deviation is zero — the "
            "signal expressed no preference, and dividing by zero would return "
            "a vector of silent zeros indistinguishable from a genuine neutral "
            "signal (feature 74 refuses the no-preference case rather than "
            "defaulting it)"
        )

    return (ranks - mean_rank) / std_rank
