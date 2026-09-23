"""Feature 262, the beta-six orthogonality bonus — the formula's last
term, its only addition, measured against the committed book.

app_spec.xml, "Objective Scoring & CVaR Aggregation", feature 262: *System
adds a beta-six orthogonality bonus measured against the committed book,
which returns the final world score* — the last line of the block
docs/alpha-engine-prd.md §7.1 states (line 318) and
docs/nullius-tech-architecture.md §10.3 restates (line 495):

    V_i^m =   IR_oos( π^m.commit() | book_t )   # committed pick, sequestered epoch
            − β₁ · trials_charged               # five penalties, each its own feature
            …
            + β₆ · orthogonality(committed book)   # ← this module's line (§7.1 line 324)

β₆ is the one term with a ``+`` in front of it, and that is the feature's
whole character: five of the six β-terms take away (statistical budget,
planted nulls, multiple testing, sim-reality divergence, switching), and
this one *pays* — for the only thing a committed pick can offer that the
book it joins does not already hold.  :func:`orthogonality_bonus` lands
that payment through :meth:`WorldScore.adjusted` — exactly the seam the
objective's own docstring promised the six β-terms would ride, "visible,
signed, and arguable" — and answers the moved :class:`~scoring.WorldScore`:
the *final world score* of the feature's second clause, final because it
is the formula's last term, not because the arithmetic here is last to
compose (features 257 and 258 will land their penalties through the
same seam as they arrive, and the order the caller applies terms in is
the caller's).

**Orthogonality is ``1 − |ρ|``, and ρ is the population correlation of
the pick's and the book's sequestered panels.**  The measurement is the
Pearson correlation of the two per-date return series over the pick's
sequestered dates, in the member's one convention: population statistics
(``ddof=0`` — the epoch is the whole sample, the same stance the
information ratio takes), summed with :func:`math.fsum` over dates sorted
before they are read, so the answer is exact and iteration-order
independent.  The absolute value is the half of the definition that is a
decision rather than a convention, and it is deliberate: the book
*explains* a pick in either sign.  A pick perfectly correlated with the
book is redundancy the book already holds, and a pick perfectly
anti-correlated with it is the same redundancy wearing a hedge's clothes
— the book spans that direction exactly as fully, which is why §6.2's
closed form orthogonalizes against the book's return series and not
against its sign.  ``1 − |ρ|`` is therefore the fraction of the pick's
direction the book does not span: ``0`` for redundancy (either sign),
``1`` for a pick the book says nothing about, and the bonus pays in
proportion — the arithmetic meaning of *"measured against the committed
book"*.

**Measured on the sequestered epoch that earned the score — and pinned
to it.**  The bonus is an out-of-sample figure like everything else in
§7.1's block, so it is measured over the same sequestered panel that
measured the leading term, not over any window the caller has to spare.
The book's panel must cover every date the pick's panel holds — a book
that misses a sequestered date is a hole in the resident array, not a
zero return (feature 75's absence rule, restated for the book the way
feature 83 restated it for the in-sample marginal IR) — and a book that
holds dates outside the epoch simply has them unread: the pick's priced
grid defines the panel, the stance feature 83 takes for the book's
signals.  And the pick panel handed here must be *the* panel the score
was measured on, enforced rather than assumed: the seam recomputes the
information ratio of the handed panel in the objective's own spelling
(imported from :mod:`scoring._objective`, not restated — one spelling of
the ratio per member is the member's own law) and refuses, naming both
numbers, unless it reproduces :attr:`WorldScore.ir_oos` to the bit.  The
two computations are the same code over the same values, so the equality
is exact when the panel is the one and a float apart when it is not; the
refusal is what keeps the bonus auditable, because a bonus measured on
one panel and bolted onto a score measured on another is precisely the
"hidden reweighting folded in before anyone can see it" the objective
refuses to be — the same self-consistency discipline the evaluator's
marginal IR holds over its own terms, held here across a feature
boundary inside the member.

**The term can only add.**  ``β₆ · orthogonality`` is non-negative by
construction on both of its factors: orthogonality is in ``[0, 1]`` by
the absolute value, the coefficient is refused when negative (below),
and ρ itself is clamped into ``[−1, 1]`` — not as a measurement
decision, since ρ is mathematically bounded there, but as the numerical
guard that keeps a last-ulp float error (a computed ``1 + 2⁻⁵²`` for a
collinear pair) from manufacturing a *negative* bonus through the one
seam whose sign the formula states.  The guarantee this buys is worth
its one line: no book, however a pick is placed against it, can push a
score *down* through β₆.  A penalty for diversification would be a
strange objective indeed, and no float gets to invent one.

**β₆ is the caller's knob, carried with a stated default.**  Neither
document sizes the coefficient — §7.1 spells the term and moves on — so
:data:`BETA_SIX_DEFAULT` states a parameterization rather than hiding a
constant, the stance feature 263's :data:`~scoring.LAMBDA_DEFAULT` takes
for λ and feature 228's ``PRIOR_STRENGTH`` for its shrinkage prior: the
dreaming loop's offline tuning is expected to set it per cycle, and
every finite non-negative value composes identically.  The default is
``0.25`` — a quarter of a ratio unit at full orthogonality, visible
beside a leading term of order one, large enough to argue about and
small enough that no policy ever preferred being uncorrelated to being
*right*.  A deployment's chosen coefficient is deployment state the
replay already persists beside the score it moved
(``replay_score.beta``, feature 255's *"the beta at which it was
scored"*), which is the other reason the number crosses this seam as an
argument and never as a member-held constant.  Negative values are
refused and zero is not: the spec's own verb is *adds*, and a negative
coefficient would counterfeit a penalty through the bonus seam —
teaching the loop to prefer book-redundant picks — while a zero merely
declines an incentive the documents never sized, an ablation that is a
deployment's to make.

**A book that never varied is refused, not paid.**  The correlation
against a constant series is ``0/0`` — undefined, not zero — and the
two cheap readings of that fact are both wrong: paying the full bonus
(a constant book "explains nothing", so every pick looks free) would
sell diversification nobody measured, and paying nothing would rank a
fact the arithmetic cannot state.  The refusal is the honest third
reading, and it mirrors the objective's own: a constant *pick* panel
cannot define the ratio the consistency check recomputes, so the pick
side of the pair is already refused one feature earlier by
:class:`~scoring.WorldObjectiveError` before this module ever reaches
for its own.

**The vocabulary of the refusals.**  This module's own rejections are
:class:`~scoring.OrthogonalityError` — a coefficient that flips the
term's sign, a carrier exposing no measurement to pin the panel against
or no ``adjusted`` seam to ride, a panel that did not measure the score
it sits beside, a book panel that is malformed, misses the epoch, or
never varied.  The pick panel's *shape* refusals are deliberately
feature 256's own and stay 256's: this seam recomputes 256's number
from 256's shapes through 256's code, so a pick panel that is not a
mapping of dates to finite reals, or too short, or constant raises
:class:`~scoring.WorldObjectiveError` untranslated — the repair is the
same wherever the panel was rejected, both classes share the
:class:`~scoring.ScoringError` base a replay loop's single ``except``
catches, and translating the messages would put one failure behind two
names.  :class:`~scoring.OrthogonalityError` sits **beside**
:class:`~scoring.WorldObjectiveError`, never under it, for the reason
the aggregation's sibling classes are kept apart: the objective refuses
an ask that cannot be *scored*, this module refuses one whose *bonus*
cannot be measured, and the repairs differ — a bad pick panel is a
sequestration problem, a bad book panel is a resident-array problem,
and folding them would send the operator to the wrong member.

**What this law deliberately does not do.**  It does not touch the
leading term — the book's contribution arrives as this visible, signed,
arguable term or not at all, so a pick's ``ir_oos`` is the same number
with the bonus applied and without (a leading term that quietly netted
the book would make β₆ double-count, the hazard :mod:`scoring._objective`
states for exactly this feature).  It does not compute the in-sample
``ir_marginal`` — that is the evaluator's §6.2 closed form, already on
the node record the policy read; β₆ is the *out-of-sample* twin, measured
on the sequestered epoch the policy never saw, which is why it is scored
here and not read off the node.  It does not aggregate (263/264), does
not calibrate (265-269), and persists nothing — the ``replay_score`` row
is the replay plugin's (feature 255), and it already carries the score
and the β.  And it takes no component and no seat: like the blend and
the index it is pure arithmetic — no store, no clock, no environment —
so the composed ``scoring`` component stays the per-world objective and
this term is reached through the member's own namespace, the growth
pattern every free seam in this workspace takes.

Stdlib only, and import-cheap: :mod:`datetime`, :mod:`math`,
:mod:`numbers`, the :mod:`collections.abc` mapping protocol,
:mod:`~typing` under annotation deferral, and the member's own objective
and error — no third-party import at module scope, so the factory's
scan (which imports this package to fire its ``@register`` builder) pays
nothing for the law.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Mapping
from numbers import Real

from ._objective import WorldScore, _ir_oos, _panel_readings
from .errors import OrthogonalityError

__all__ = [
    "BETA_SIX_DEFAULT",
    "orthogonality_bonus",
]

#: The β₆ a caller that names none gets.  Neither prd §7.1 nor docs §10.3
#: sizes the coefficient — the formula spells ``+ β₆ · orthogonality`` and
#: moves on — so this is a stated parameterization rather than a hidden
#: constant, the stance feature 263's ``LAMBDA_DEFAULT`` takes for λ and
#: feature 228's ``PRIOR_STRENGTH`` for its prior: the dreaming loop's
#: offline tuning is expected to set it per cycle, and every finite
#: non-negative value composes identically.  A quarter of a ratio unit at
#: full orthogonality — visible beside a leading term of order one, never
#: large enough that being uncorrelated beats being right — and dyadic,
#: so the fixtures that pin the law are exact in binary.  The coefficient
#: a deployment actually ran is its own state, persisted beside the score
#: it moved (``replay_score.beta``, feature 255).
BETA_SIX_DEFAULT: float = 0.25


def orthogonality_bonus(
    score: object,
    pick_returns: Mapping[dt.date, float],
    book_returns: Mapping[dt.date, float],
    *,
    beta: float = BETA_SIX_DEFAULT,
) -> WorldScore:
    """Add the beta-six orthogonality bonus to a world score — §7.1's
    last term, measured against the committed book.

    The feature's verb.  ``score`` is the world score the bonus lands on
    — feature 256's :class:`~scoring.WorldScore`, read duck-typed by the
    two attributes this law needs (``ir_oos``, the measurement the panel
    is pinned against, and ``adjusted``, the seam every β-term rides) and
    never by ``isinstance``, because the module loader imports this
    member under a synthetic name and re-executes it, so a score this
    process composed may be a second ``WorldScore`` class object.  The
    answer is that carrier's own ``adjusted`` return: the same world,
    pick, epoch and frozen measurement, with :attr:`WorldScore.score`
    moved up by ``beta · (1 − |ρ|)`` — never down, by the law above.

    ``pick_returns`` is the committed pick's sequestered panel — *the*
    panel the score was measured on, not a panel like it: the seam
    recomputes the panel's information ratio in the objective's own
    spelling and refuses unless it reproduces the carrier's ``ir_oos``
    to the bit, so a bonus can never be measured on data the score never
    saw.  ``book_returns`` is the committed book's per-date return series
    — the ``book_t`` of §7.1's leading term, as one reading per date over
    the same sequestered epoch.  It must cover every date the pick's
    panel holds (a hole is refused, never zero-filled) and dates it holds
    outside the epoch are left unread.  ``beta`` is the β₆ the bonus is
    weighted by, keyword-only, :data:`BETA_SIX_DEFAULT` when unnamed.

    Refuses, with :class:`~scoring.OrthogonalityError` and nothing
    partial:

    * a ``beta`` that is not a finite real, or is negative — the
      spec's verb is *adds*, and a negative coefficient would
      counterfeit a penalty through the bonus seam;
    * a carrier that exposes no finite ``ir_oos`` to pin the panel
      against, or no callable ``adjusted`` to ride;
    * a ``pick_returns`` panel whose recomputed ratio is not the
      carrier's ``ir_oos`` — the panel did not measure this score;
    * a ``book_returns`` panel that is not a mapping of dates to finite
      reals, that misses a date of the sequestered epoch (named), or
      that never varied across it (a correlation of ``0/0`` is
      undefined, and no bonus is invented for it).

    A malformed ``pick_returns`` panel — not a mapping, keys that are
    not dates, readings that are not finite reals, fewer than
    :data:`~scoring.IR_DATES_MINIMUM` dates, a series that never varied —
    is refused with feature 256's own :class:`~scoring.WorldObjectiveError`,
    untranslated, because the shape of a pick panel is 256's law and this
    seam recomputes 256's number through 256's code.

    Deterministic and pure: no store, no clock, no environment, and the
    same panels answer the same score to the last bit regardless of
    either mapping's iteration order (dates are sorted before they are
    read and every sum is a :func:`math.fsum`) — the determinism law the
    objective holds for the leading term, held here for the last one.
    """
    weight = _require_beta(beta)
    measured = _measured_ir_oos(score)
    adjusted = _require_adjusted_seam(score)
    dates, pick_values = _panel_readings(pick_returns)
    ratio = _ir_oos(dates, pick_values)
    if ratio != measured:
        raise OrthogonalityError(
            f"the panel handed to measure the beta-six bonus reduces to an "
            f"information ratio of {ratio!r}, but the score it was handed "
            f"beside carries ir_oos {measured!r}: the bonus is measured "
            f"against the committed book on the sequestered epoch that "
            f"earned the score, so the panel must be the one the objective "
            f"read — hand the same panel world_objective measured, and a "
            f"panel that measures a different ratio belongs to a different "
            f"score (feature 262, prd §7.1)"
        )
    book_values = _book_on(dates, book_returns)
    rho = _correlation(pick_values, book_values)
    return adjusted(weight * (1.0 - abs(rho)))


# -- the seam's private vocabulary ----------------------------------------------


def _require_beta(beta: object) -> float:
    """Narrow β₆ to a finite non-negative ``float``, refusing the rest.

    ``bool`` is refused before the real check (a ``bool`` is an ``int``
    in Python's hierarchy and not a coefficient); NaN and ±inf are
    refused with it — a NaN weight would make the delta a NaN the
    ranking silently drops, and an infinite one is not a coefficient
    anyone tuned.  Negative is refused on the feature's own sentence:
    the spec's verb is *adds*, and a negative β₆ would counterfeit a
    penalty through the bonus seam, teaching the loop to prefer picks
    the book already spans.  Zero is admitted — an ablation the
    documents leave to the deployment, not a contradiction of the term.
    """
    if isinstance(beta, bool) or not isinstance(beta, Real):
        raise OrthogonalityError(
            f"beta must be the beta-six coefficient as a real number, got "
            f"{beta!r} ({type(beta).__name__}): the orthogonality bonus is "
            f"weighted by a coefficient the deployment chose and the "
            f"replay_score row persists (feature 255), and a value that is "
            f"not a real has no place in either (feature 262, prd §7.1)"
        )
    weight = float(beta)
    if not math.isfinite(weight):
        raise OrthogonalityError(
            f"beta must be finite, got {weight!r}: a NaN weight would turn "
            f"the bonus into a NaN the dreaming loop's argmax silently "
            f"drops, and an infinite one is not a coefficient anyone tuned "
            f"(feature 262, prd §7.1)"
        )
    if weight < 0.0:
        raise OrthogonalityError(
            f"beta must not be negative, got {weight!r}: the spec's verb is "
            f"adds — beta-six is the per-world objective's one addition, "
            f"paid for the direction the committed book does not span — and "
            f"a negative coefficient would counterfeit a penalty through "
            f"the bonus seam, teaching the loop to prefer book-redundant "
            f"picks; a penalty term is features 257 through 261's business, "
            f"each with its own sign (feature 262, prd §7.1)"
        )
    return weight


def _measured_ir_oos(score: object) -> float:
    """The carrier's frozen measurement, read duck-typed and validated.

    The bonus is pinned to the sequestered epoch that earned the score by
    recomputing the panel's ratio against this number, so it is read
    first, before any arithmetic: a carrier exposing no ``ir_oos``, or one
    that is not a finite real, has nothing to pin against and is refused
    as the wiring fault it is — the two attributes this law reads are
    ``ir_oos`` and ``adjusted``, and nothing else, which is what proves
    the seam validates what it reads rather than the type it was handed.
    """
    measured = getattr(score, "ir_oos", None)
    if isinstance(measured, bool) or not isinstance(measured, Real):
        raise OrthogonalityError(
            f"the beta-six bonus lands on a world score, read by the "
            f"measurement it was earned with, and this carrier exposes no "
            f"readable ir_oos (got {measured!r} on a "
            f"{type(score).__name__}): hand feature 256's WorldScore — any "
            f"object exposing a finite ir_oos and the adjusted seam its "
            f"terms ride satisfies the seam, whatever copy of the member "
            f"composed it (feature 262, prd §7.1)"
        )
    narrowed = float(measured)
    if not math.isfinite(narrowed):
        raise OrthogonalityError(
            f"the score the beta-six bonus lands on carries a non-finite "
            f"ir_oos ({measured!r}): the measurement is frozen finite by "
            f"feature 256's construction, so a carrier holding anything "
            f"else was not built by the objective and has no sequestered "
            f"epoch to pin a panel against (feature 262)"
        )
    return narrowed


def _require_adjusted_seam(score: object) -> object:
    """The carrier's ``adjusted`` seam, read duck-typed and checked.

    The bonus reaches the score through :meth:`WorldScore.adjusted` — the
    one seam the objective ships for the six β-terms — so the callable is
    read up front with the measurement: a carrier that validates the one
    and lacks the other is refused before any arithmetic runs, naming the
    seam, because the repair is at the caller's wiring and not in any
    panel the caller might also have got wrong.
    """
    seam = getattr(score, "adjusted", None)
    if not callable(seam):
        raise OrthogonalityError(
            f"the beta-six bonus rides WorldScore.adjusted — the one seam "
            f"the objective ships for the six beta-terms — and this "
            f"carrier exposes no callable adjusted (got {seam!r} on a "
            f"{type(score).__name__}): hand feature 256's WorldScore, or "
            f"any object exposing its two faces (a finite ir_oos and the "
            f"adjusted the terms ride), and the bonus composes onto it "
            f"(feature 262, prd §7.1)"
        )
    return seam


def _book_on(dates: list[dt.date], book_returns: object) -> list[float]:
    """The committed book's readings on the sequestered dates, paired.

    The book panel is validated in this module's own vocabulary (it is
    feature 262's input, not 256's): a mapping of calendar dates to
    finite reals — ``datetime`` keys refused as dates with a clock
    bolted on, ``bool`` and NaN and ±inf readings refused before they
    can dress a correlation.  Every date of the pick's sequestered epoch
    must be covered: a book that misses one is a hole in the resident
    array, not a zero return, and zero-filling would fabricate the very
    orthogonality the term pays for (a zero is trivially uncorrelated
    with anything).  Dates the book holds outside the epoch are left
    unread — the pick's priced grid defines the panel, the stance
    feature 83 takes for the evaluator's book signals — so a book
    covering the whole campaign horizon composes with the sequestered
    slice of it untouched.
    """
    if not isinstance(book_returns, Mapping):
        raise OrthogonalityError(
            f"the committed book's panel must be a mapping of dates to "
            f"readings, got {book_returns!r} ({type(book_returns).__name__}): "
            f"one reading per date is the panel's own law — the book is "
            f"measured against the pick on the sequestered epoch, and a "
            f"sequence cannot say which reading belongs to which date "
            f"(feature 262, prd §7.1)"
        )
    readings: dict[dt.date, float] = {}
    for day, reading in book_returns.items():
        if isinstance(day, dt.datetime) or not isinstance(day, dt.date):
            raise OrthogonalityError(
                f"the committed book's panel must be keyed by dates, and "
                f"one of its keys is {day!r} ({type(day).__name__}): the "
                f"bonus is the correlation of two per-date series over the "
                f"sequestered epoch, and a book keyed by anything else — a "
                f"datetime, a string, a number — is not the book's panel "
                f"shape (feature 262)"
            )
        readings[day] = _finite(
            reading, f"the book's reading for {day.isoformat()}"
        )
    missing = [day for day in dates if day not in readings]
    if missing:
        first = missing[0]  # the epoch's dates arrive sorted, so this is
        # the earliest hole — deterministic under any iteration order.
        raise OrthogonalityError(
            f"the committed book has no return on {first.isoformat()}, one "
            f"of the {len(missing)} sequestered date(s) of the pick's epoch "
            f"it does not cover: a book signal that misses a sequestered "
            f"date is a hole in the resident array, not a zero return — "
            f"zero-filling would fabricate the very orthogonality this term "
            f"pays for, so the book must cover every date the pick was "
            f"measured on (feature 262, prd §7.1)"
        )
    return [readings[day] for day in dates]


def _finite(value: object, field: str) -> float:
    """Narrow a book reading to a finite ``float``, refusing the rest.

    The same discipline the objective applies to the pick's readings,
    in this module's own vocabulary because the book is this feature's
    input: ``int`` admitted and narrowed, ``bool`` refused before it, a
    non-real refused as a type fault rather than escaping as a
    ``TypeError`` from inside the arithmetic, and NaN and ±inf refused
    because a reading that is not a measurement would reach the bonus
    dressed as one.
    """
    if isinstance(value, bool) or not isinstance(value, Real):
        raise OrthogonalityError(
            f"{field} must be a per-date reading as a real number, got "
            f"{value!r} ({type(value).__name__}): the committed book's "
            f"panel reduces to a correlation against the pick's, and a "
            f"value that is not a real has no place in one (feature 262)"
        )
    narrowed = float(value)
    if not math.isfinite(narrowed):
        raise OrthogonalityError(
            f"{field} is not finite ({value!r}); a NaN or ±inf would reach "
            f"the orthogonality bonus dressed as a measurement — the same "
            f"law the pick's own panel holds one feature earlier "
            f"(feature 262, prd §7.1)"
        )
    return narrowed


def _correlation(pick_values: list[float], book_values: list[float]) -> float:
    """The population correlation of the two paired series — the member's
    one convention, stated for two series.

    Means, deviations and variances in the population convention
    (``ddof=0``: the sequestered epoch is the whole sample the pair was
    measured over, the stance the information ratio takes for one),
    every sum a :func:`math.fsum` over the dates in sorted order, so the
    answer is exact and iteration-order independent.  A book that never
    varied is refused here — the correlation against a constant is
    ``0/0``, undefined rather than zero, and paying the full bonus for it
    would sell diversification nobody measured.  The pick side cannot be
    constant: ``_ir_oos`` refused that panel one step up, and this is the
    same arithmetic over the same values.  The answer is clamped into
    ``[−1, 1]`` — ρ is mathematically bounded there and the clamp only
    ever eats a last-ulp float error, but it keeps ``1 − |ρ|`` from going
    negative on a collinear pair, which is the one way a float could
    counterfeit a penalty through the formula's only addition.
    """
    count = len(pick_values)
    pick_mean = math.fsum(pick_values) / count
    book_mean = math.fsum(book_values) / count
    covariance = (
        math.fsum(
            (pick - pick_mean) * (book - book_mean)
            for pick, book in zip(pick_values, book_values, strict=True)
        )
        / count
    )
    pick_std = math.sqrt(
        math.fsum((pick - pick_mean) ** 2 for pick in pick_values) / count
    )
    book_std = math.sqrt(
        math.fsum((book - book_mean) ** 2 for book in book_values) / count
    )
    if book_std == 0.0:
        raise OrthogonalityError(
            f"the committed book returned a constant reading across all "
            f"{count} dates of the sequestered epoch, so its standard "
            f"deviation is zero and its correlation with the pick is "
            f"undefined (0/0, not zero); refusing rather than paying the "
            f"full bonus for diversification nobody measured — a book "
            f"that never varied has no direction to span or to miss "
            f"(feature 262, prd §7.1)"
        )
    rho = covariance / (pick_std * book_std)
    if rho > 1.0:
        return 1.0
    if rho < -1.0:
        return -1.0
    return rho
