"""The marginal information ratio — pipeline step 9, feature 83.

app_spec.xml feature 83: *"System computes ir_marginal by orthogonalizing the
candidate against the current book, which returns the incremental information
ratio."*  docs/nullius-tech-architecture.md §6.1 names the step —
``9. marginal_ir        orthogonalize vs. current book → ir_marginal`` — and
§9.1 names where it lands: the ``node`` table's ``ir_marginal`` column, beside
the ``ic_mean`` / ``ic_tstat`` / ``ir_standalone`` / ``turnover`` feature 80
writes.  docs/alpha-engine-prd.md's node block spells the same metric under
``metrics`` (``ir_marginal: float  # vs. current book — see §6.2``) and §6.2
gives its definition in one line:

    ``ir_marginal(v | book) = IR(book ∪ {v}) − IR(book)``

The computation lives here; :mod:`evaluator._marginal_store` writes it down, on
the split this package already uses five times (``_identity`` computes and
``_store`` persists for feature 70, ``_costs``/``_cost_store`` for 79,
``_capacity``/``_capacity_store`` for 82, ``_decay``/``_decay_store`` for 81,
``_metrics``/``_metrics_store`` for 80), and it is the split feature 83 owns:
this module computes the incremental information ratio, and the store persists
it.

Four decisions carry the feature, and each is a pin rather than a knob:

*the marginal IR is the *increase* in the equal-weight book's information ratio
when the candidate joins it, and that is feature 80's ``ir_standalone``
definition applied to a book.*
    The definition is §6.2's ``IR(book ∪ {v}) − IR(book)`` verbatim.  The
    information ratio of a set of signals is the mean over the rebalance dates
    of the set's equal-weight per-date return divided by the population standard
    deviation of those returns — *exactly* the coefficient feature 80 pins for
    ``ir_standalone`` (:func:`_information_ratio`, one spelling), where
    ``ir_standalone`` is the special case of a book of one — the candidate
    alone.  ``ir_marginal`` is the same ratio measured twice and differenced:
    once over the current book, once over the book with the candidate added,
    and the difference is the candidate's *incremental* contribution.  This is
    what "orthogonalizing the candidate against the current book" *means* as a
    number: a candidate whose per-date returns the book already explains moves
    the combined portfolio's return series barely, so its two ratios are close
    and its marginal IR is near zero; a candidate the book does not explain
    moves the combined series, and its marginal IR is the distance.  It is not
    a second definition of the information ratio — it is feature 80's, applied
    to a book and to that book plus one — so a reader comparing a node's
    ``ir_standalone`` against its ``ir_marginal`` is comparing two numbers
    measured on one axis.

*the candidate and the book are measured on one priced panel, over one pinned
horizon, and that is feature 80's panel, not a second one.*
    The candidate's per-date returns are step 7's own record —
    :class:`~evaluator.PostCostReturns`, the per-symbol, per-bar, per-horizon
    ``gross − charge`` series priced by the shared cost library — reduced to the
    equal-weight per-date return the way feature 80 reduces it (the mean over
    the symbols that date holds).  The book arrives as each existing signal's
    per-date return series, on the same rebalance grid, and every one is
    required to cover every date the candidate was priced on — a book signal
    that misses a priced date is a hole in the resident array, not a zero
    return (feature 75's absence rule, restated for the book).  Both are
    measured over :data:`METRICS_HORIZON` — the shortest horizon the priced
    panel covers, resolved the same way feature 80 resolves it — so the
    marginal IR sits on one axis with ``ic_mean``, the decay profile and the
    capacity estimate, all measured over one priced panel, and two deployments
    of the same evaluator report the same number for the same node.  A horizon
    the panel does not cover is *absent*, not zero, and a panel that covers
    fewer than two dates is refused outright (an information ratio over one date
    names a zero standard deviation and a fabricated infinity — the same stance
    :func:`compute_node_metrics` takes on ``ic_tstat``).

*the book is equal-weight, and that is a convention, not a parameter.*
    Each existing signal enters the book with weight ``1/k`` (``k`` the number
    of signals the book holds), and the candidate joins it at ``1/(k+1)`` with
    the book re-normalized to match — the equal-weight convention feature 80's
    ``ir_standalone`` and feature 82's capacity both use, so the marginal IR is
    the increment to the same book those metrics size.  It is not a caller's
    knob: a weight is a portfolio decision the replay path §1 keeps out of the
    evaluator, and a marginal IR computed under an ad-hoc weighting would not be
    comparable across nodes or across cycles, which is what a stored scalar that
    is compared must be.  The book must hold at least one signal — a book of
    zero signals has no information ratio to increment from, and that question
    is feature 80's ``ir_standalone`` (the candidate alone).

*the scalar is a scalar, and the per-date returns that reduce to it are carried
beside it.*
    The feature names one scalar — ``ir_marginal`` — but a scalar alone cannot
    be checked or read, so the record carries the terms it reduces from: the
    book's information ratio, the combined book-plus-candidate information
    ratio, the candidate's own standalone information ratio, the book size and
    the per-date equal-weight book, combined and candidate returns.  Each ratio
    must be the information ratio of its own per-date returns, and ``ir_marginal``
    must be the combined ratio less the book ratio — enforced at construction and
    again on every read-back, the defence the identity store applies to a hash
    that does not fold from its terms and the metrics store to an ``ic_mean``
    that is not its own series' mean.

**Absence is not zero**, three times over.  A horizon the priced panel does not
cover carries no marginal IR — a panel that covers no horizon at all is refused
outright (nothing measured), and a panel that covers fewer than two dates is
refused rather than defaulted (an information ratio over one date names a zero
standard deviation and a fabricated infinity).  A book signal that misses a date
the candidate was priced on is simply absent from that date — refused, not
zero-filled — and a book whose equal-weight return never varies across its dates
is refused rather than divided by zero (a book that never varied has no
information ratio to increment).

**What this module does not do.**  It computes no other metric — ``ic_mean``,
``ic_tstat``, ``ir_standalone`` and ``turnover`` are feature 80's, the decay
profile feature 81, capacity and regime attribution feature 82, ``cost_adjusted_ir``
and ``perturb_stability`` are step 10's tripwire metrics — it does not price (step
7's :func:`apply_costs` produced the returns), align (75), gate (76), normalize
(feature 74's ``normalize_scores`` ran three steps earlier; this step takes the
post-cost returns), choose a portfolio weight, or persist (:mod:`evaluator._marginal_store`
owns the write).  It takes step 7's record and the current book and answers
exactly the one question step 9 puts in its scope: *how much does this candidate
add to the information ratio of the book that already stands?*

**The layering note.**  This module is stdlib-only — dates, mappings, square
roots and arithmetic; no polars, no pyarrow, no lake, no environment, no HTTP,
and no import of any other member.  The returns arrive as values (feature 79's
record and the book's per-date series), so the Polars boundary stays at the edge
of the package where every other member keeps it, which is what makes importing
this member cost composition — and the replay path §1 forbids from reaching the
evaluator — nothing at all.  It depends on no other member: the horizon policy
it shares with feature 80 is resolved here in its own terms, and the information
ratio it uses is pinned here rather than borrowed.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from ._align import HORIZONS
from ._costs import PostCostReturns
from ._errors import EvaluatorMarginalError

__all__ = [
    "MARGINAL_IR_STEP",
    "MarginalIR",
    "compute_marginal_ir",
]

#: The pipeline-step name, in §6.1's own spelling.  Step 9 is the marginal-IR
#: step — ``marginal_ir    orthogonalize vs. current book → ir_marginal`` — and
#: this module owns it.  Shared vocabulary: the feature sentence, the §6.2
#: formula, the refusals below, and every reader of a persisted marginal IR name
#: the one step that computes the candidate's increment, and they name it once.
MARGINAL_IR_STEP: str = "marginal_ir"


def _marginal_horizon(returns: PostCostReturns) -> int:
    """The horizon the marginal IR is computed over — the shortest covered.

    The shortest horizon :data:`HORIZONS` names that the priced panel actually
    covers — the first horizon, in the spec's ascending order, whose series has
    at least one rebalance date — which is :data:`METRICS_HORIZON`, the same
    one pinned horizon feature 80 reduces its four scalars over and for the
    same reason: the fastest-turning, best-evidenced, hardest-hit horizon is
    the strongest claim the candidate can make, and "shortest supported" is a
    function of the panel rather than a caller's knob, so two deployments report
    the same marginal IR for the same node.  Resolved here in this module's own
    terms rather than borrowed from :mod:`evaluator._metrics`, so this module
    imports no sibling — the independence that keeps it import-cheap.

    Refused when the panel covers no horizon at all: a bundle whose every series
    is empty measured nothing, and there is no marginal IR to store — the same
    stance :func:`apply_costs`, :func:`estimate_capacity` and
    :func:`compute_node_metrics` take.
    """
    for horizon in HORIZONS:
        if returns.series[horizon].dates():
            return horizon
    raise EvaluatorMarginalError(
        "the post-cost panel covers no horizon at any of the horizons the "
        f"spec names ({', '.join(str(h) for h in HORIZONS)}), so there is "
        "nothing to compute ir_marginal over; the priced panel measured no "
        "rebalance date — score and price an alignment with coverage first "
        "(features 75 through 79)"
    )


def _information_ratio(
    per_date: Mapping[dt.date, float],
    *,
    horizon: int,
    label: str,
) -> tuple[float, float]:
    """The equal-weight book's information ratio, and its population std.

    The mean per-date return divided by the population standard deviation of
    those returns — the one spelling of the information ratio feature 80 pins
    for ``ir_standalone``, so ``ir_marginal`` and ``ir_standalone`` are measured
    on one axis.  The population convention (``ddof=0``: the dates are the whole
    sample the candidate was measured over, not a draw from a larger
    super-population) and ``fsum`` (exact regardless of iteration order) are
    feature 80's, restated here so this module borrows nothing.

    Refused rather than defaulted when the ratio is undefined: fewer than two
    dates (a standard deviation over one date is zero and the ratio a fabricated
    infinity), or a return that never varies across its dates (a book that never
    varied has no reward-to-variance ratio — the same stance the coefficient
    takes on a constant side).
    """
    days = sorted(per_date)
    count = len(days)
    if count < 2:
        raise EvaluatorMarginalError(
            f"the {label} was priced on {count} rebalance date(s) at horizon "
            f"{horizon}; an information ratio is a mean over a standard "
            "deviation, and a standard deviation over a single date is zero — "
            "refusing rather than dividing by a fabricated infinity (score and "
            "price an alignment with coverage first, features 75 through 79)"
        )
    values = [per_date[day] for day in days]
    mean = math.fsum(values) / count
    variance = math.fsum((value - mean) ** 2 for value in values) / count
    std = math.sqrt(variance)
    if std == 0.0:
        raise EvaluatorMarginalError(
            f"the {label} returned a constant per-date return across its "
            f"{count} dates at horizon {horizon}, so its standard deviation is "
            "zero and its information ratio is undefined; refusing rather than "
            "dividing by zero — a book whose return never varied has no "
            "reward-to-variance ratio to increment"
        )
    return mean / std, std


@dataclass(frozen=True)
class MarginalIR:
    """Step 9's incremental information ratio — ``IR(book ∪ {v}) − IR(book)``.

    The one number feature 83 persists on the node record, pinned to the §6.2
    closed form (see the module docstring), measured over one horizon — the
    shortest the priced panel covers — and stamped with the evaluation's
    provenance (node, sealed snapshot, cost model) for the reason the capacity,
    decay and metrics records carry it: the ratio is a function of a *priced*
    panel, two fee schedules net different post-cost returns out of the same
    gross ones, so the pair belongs in the identity of the marginal IR and in
    the store's key beside the node, exactly as it is in the signal-returns,
    capacity, decay and node-metrics tables.

    The terms are carried beside the number because a scalar alone cannot be
    checked or read: :attr:`book_ir`, :attr:`combined_ir` and :attr:`candidate_ir`
    say what the increment was measured between, :attr:`dates` and
    :attr:`book_size` say how much evidence and how large a book stood behind it,
    and :attr:`book_returns`, :attr:`combined_returns` and :attr:`candidate_returns`
    are the per-date returns each ratio reduces from — each ratio must be the
    information ratio of its own per-date returns and :attr:`ir_marginal` their
    difference, enforced at construction and again on every read-back, the
    defence the identity store applies to a hash that does not fold from its
    terms.
    """

    #: The node whose candidate signal was measured.
    node_id: str
    #: The canonical name of the sealed snapshot the panel was measured in.
    snapshot_name: str
    #: The cost model the returns were netted against.
    cost_model: object
    #: The horizon the marginal IR was computed over — the shortest covered.
    horizon: int
    #: How many rebalance dates the horizon measured — the evidence behind the ratio.
    dates: int
    #: How many signals the current book held — the denominator of the book weight.
    book_size: int
    #: The equal-weight book's information ratio — ``IR(book)``.
    book_ir: float
    #: The equal-weight book-plus-candidate information ratio — ``IR(book ∪ {v})``.
    combined_ir: float
    #: The candidate's own standalone information ratio — the IR of the candidate alone.
    candidate_ir: float
    #: ``combined_ir − book_ir`` — ``ir_marginal``, the candidate's increment.
    ir_marginal: float
    #: The per-date equal-weight book returns — the series ``book_ir`` reduces from.
    book_returns: Mapping[dt.date, float]
    #: The per-date equal-weight book-plus-candidate returns — the series
    #: ``combined_ir`` reduces from.
    combined_returns: Mapping[dt.date, float]
    #: The per-date equal-weight candidate returns — the series ``candidate_ir``
    #: reduces from.
    candidate_returns: Mapping[dt.date, float]

    def __post_init__(self) -> None:
        # object.__setattr__ where the constructor normalizes; this record
        # validates only, like the node metrics and per-horizon capacity it sits beside.
        if not isinstance(self.node_id, str) or not self.node_id.strip():
            raise EvaluatorMarginalError(
                "a marginal IR must name the node whose candidate it measures, "
                f"got {self.node_id!r}"
            )
        if not isinstance(self.snapshot_name, str) or not self.snapshot_name.strip():
            raise EvaluatorMarginalError(
                "a marginal IR must name the sealed snapshot its panel was "
                f"measured in, got {self.snapshot_name!r}"
            )
        if isinstance(self.horizon, bool) or not isinstance(self.horizon, int):
            raise EvaluatorMarginalError(
                f"a marginal IR's horizon must be an integer period count, "
                f"got {self.horizon!r}"
            )
        if self.horizon not in HORIZONS:
            raise EvaluatorMarginalError(
                f"horizon {self.horizon} is not one of the horizons the spec "
                f"names ({', '.join(str(h) for h in HORIZONS)}); the marginal "
                "IR is computed over one pinned horizon, and that horizon is "
                "one the spec covers"
            )
        if isinstance(self.book_size, bool) or not isinstance(self.book_size, int):
            raise EvaluatorMarginalError(
                f"a marginal IR's book_size must be an integer signal count, "
                f"got {self.book_size!r}"
            )
        if self.book_size < 1:
            raise EvaluatorMarginalError(
                "a marginal IR's book must hold at least one signal; a book of "
                "zero signals has no information ratio to increment from — that "
                "question is the candidate's standalone IR (feature 80)"
            )
        captured_book: dict[dt.date, float] = {}
        captured_combined: dict[dt.date, float] = {}
        captured_candidate: dict[dt.date, float] = {}
        for field, label, target in (
            (self.book_returns, "book", captured_book),
            (self.combined_returns, "combined", captured_combined),
            (self.candidate_returns, "candidate", captured_candidate),
        ):
            if not isinstance(field, Mapping):
                raise EvaluatorMarginalError(
                    f"a marginal IR's {label}_returns must map rebalance date "
                    f"to a return, got {type(field).__name__}"
                )
            for day, value in field.items():
                if not isinstance(day, dt.date) or isinstance(day, dt.datetime):
                    raise EvaluatorMarginalError(
                        f"a marginal IR's {label} return on {day.isoformat()} "
                        f"must be a number, got {value!r}"
                    )
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise EvaluatorMarginalError(
                        f"a marginal IR's {label} return on {day.isoformat()} "
                        f"must be a number, got {value!r}"
                    )
                if not math.isfinite(float(value)):
                    raise EvaluatorMarginalError(
                        f"a marginal IR's {label} return on {day.isoformat()} is "
                        f"not finite ({value!r}); a NaN or ±inf would reach the "
                        "node record dressed as a measurement"
                    )
                target[day] = float(value)
        object.__setattr__(self, "book_returns", MappingProxyType(captured_book))
        object.__setattr__(
            self, "combined_returns", MappingProxyType(captured_combined)
        )
        object.__setattr__(
            self, "candidate_returns", MappingProxyType(captured_candidate)
        )
        if not captured_book or not captured_combined or not captured_candidate:
            raise EvaluatorMarginalError(
                "a marginal IR carries an empty book, combined or candidate "
                "return series; a horizon that measured no date carries no "
                "information ratio — refuse the bundle before constructing the "
                "record"
            )
        if (
            self.dates != len(captured_book)
            or self.dates != len(captured_combined)
            or self.dates != len(captured_candidate)
        ):
            raise EvaluatorMarginalError(
                f"the marginal IR claims {self.dates} measured dates but its "
                f"book_returns carry {len(captured_book)}, its combined_returns "
                f"carry {len(captured_combined)} and its candidate_returns carry "
                f"{len(captured_candidate)}; the count is the denominator of "
                "every information ratio here, and a record whose denominator "
                "disagrees with its own series is a record no reader can size "
                "the evidence behind"
            )
        for field in ("book_ir", "combined_ir", "candidate_ir", "ir_marginal"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise EvaluatorMarginalError(
                    f"a marginal IR's {field} must be a number, got {value!r}"
                )
            if not math.isfinite(float(value)):
                raise EvaluatorMarginalError(
                    f"a marginal IR's {field} is not finite ({value!r}); a NaN "
                    "or ±inf would reach the node record dressed as a "
                    "measurement"
                )
            object.__setattr__(self, field, float(value))
        # Each ratio must be the information ratio of its own per-date returns,
        # and the marginal IR their difference — the self-consistency that makes
        # the record a check rather than a claim.
        recombinant_ir, _ = _information_ratio(
            captured_combined, horizon=self.horizon, label="combined book"
        )
        if self.combined_ir != recombinant_ir:
            raise EvaluatorMarginalError(
                f"the marginal IR says combined_ir is {self.combined_ir!r} but "
                f"its own combined_returns give {recombinant_ir!r}; the record "
                "disagrees with itself, so it was built somewhere other than "
                "this module's arithmetic — a scalar the node record would "
                "trust and be wrong by"
            )
        rebook_ir, _ = _information_ratio(
            captured_book, horizon=self.horizon, label="book"
        )
        if self.book_ir != rebook_ir:
            raise EvaluatorMarginalError(
                f"the marginal IR says book_ir is {self.book_ir!r} but its own "
                f"book_returns give {rebook_ir!r}; the record disagrees with "
                "itself, so it was built somewhere other than this module's "
                "arithmetic"
            )
        recandidate_ir, _ = _information_ratio(
            captured_candidate, horizon=self.horizon, label="candidate"
        )
        if self.candidate_ir != recandidate_ir:
            raise EvaluatorMarginalError(
                f"the marginal IR says candidate_ir is {self.candidate_ir!r} "
                f"but its own candidate_returns give {recandidate_ir!r}; the "
                "record disagrees with itself — the candidate's standalone IR "
                "must be the information ratio of the candidate's own per-date "
                "returns"
            )
        expected_marginal = self.combined_ir - self.book_ir
        if self.ir_marginal != expected_marginal:
            raise EvaluatorMarginalError(
                f"the marginal IR says ir_marginal is {self.ir_marginal!r} but "
                f"its own combined_ir − book_ir is {expected_marginal!r}; the "
                "record disagrees with itself — ir_marginal is the increment, "
                "and a record whose increment is not the difference of its own "
                "two ratios is a record no reader can trust"
            )

    def __hash__(self) -> int:
        # The mappings are not hashable until they collapse to tuples; the fold
        # keeps __hash__ consistent with __eq__, as every record in this
        # package does.
        return hash(
            (
                self.node_id,
                self.snapshot_name,
                self.cost_model,
                self.horizon,
                self.book_size,
                self.book_ir,
                self.combined_ir,
                self.candidate_ir,
                self.ir_marginal,
                tuple(sorted(self.book_returns.items())),
                tuple(sorted(self.combined_returns.items())),
                tuple(sorted(self.candidate_returns.items())),
            )
        )

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"MarginalIR(node={self.node_id!r}, horizon={self.horizon}, "
            f"book_size={self.book_size}, book_ir={self.book_ir:+.3f}, "
            f"combined_ir={self.combined_ir:+.3f}, "
            f"candidate_ir={self.candidate_ir:+.3f}, "
            f"marginal={self.ir_marginal:+.3f}, {self.dates} dates)"
        )


def compute_marginal_ir(
    returns: PostCostReturns,
    book: Mapping[str, Mapping[dt.date, float]],
) -> MarginalIR:
    """Compute the candidate's incremental information ratio — step 9's answer.

    Feature 83's computation, over :data:`METRICS_HORIZON` (the shortest horizon
    the priced panel covers): reduce the candidate's post-cost returns to the
    equal-weight per-date return the way feature 80 does (the mean over the
    symbols each date holds), form the equal-weight book's per-date return
    (``1/k`` on each of the ``k`` signals) and the equal-weight book-plus-
    candidate per-date return (``1/(k+1)`` on each signal and the candidate),
    take each set's information ratio (mean over population standard deviation),
    and return their difference — ``IR(book ∪ {v}) − IR(book)``.

    ``returns`` is step 7's own record (:class:`~evaluator.PostCostReturns`),
    and ``book`` is the current book as ``{signal name: {rebalance date:
    per-date return}}`` — each existing signal's per-date return series on the
    same rebalance grid the candidate was priced on, the resident array §9.3
    keeps pinned in RAM.  Every book signal must cover every date the candidate
    was priced on — a book signal that misses a priced date is refused, not
    zero-filled (feature 75's absence rule, restated for the book).  The book
    must hold at least one signal.

    Raises :class:`~evaluator.EvaluatorMarginalError`, each with its reason (see
    ``_errors``): a ``returns`` that is not step 7's own result; a ``book``
    mapping that is malformed, empty, carries a non-finite value, names an empty
    signal, or misses a date the candidate was priced on; a book of zero signals
    (that is the candidate's standalone IR); a panel that covers no horizon at
    all (nothing measured); a horizon with fewer than two priced dates (an
    information ratio over one date names a zero standard deviation and a
    fabricated infinity); a book or combined book whose per-date return never
    varies (its standard deviation is zero); and — via the record — a hand-built
    marginal IR whose ratios do not reduce from their own per-date returns.
    """
    if not isinstance(returns, PostCostReturns):
        raise EvaluatorMarginalError(
            "compute_marginal_ir reduces step 7's own result — a "
            "PostCostReturns, the priced series the cost schedule produced — "
            f"got {type(returns).__name__}; the marginal IR is measured from "
            "the post-cost returns, and the gross series alone cannot say which "
            "schedule priced them"
        )
    if not isinstance(book, Mapping):
        raise EvaluatorMarginalError(
            "the current book must map signal name to {rebalance date: "
            f"per-date return}}, got {type(book).__name__}; pass each existing "
            "signal's per-date return series on the priced grid"
        )
    if not book:
        raise EvaluatorMarginalError(
            "the current book is empty; ir_marginal is the increment to a book, "
            "and a book of zero signals has no information ratio to increment "
            "from — that question is the candidate's standalone IR (feature 80)"
        )
    validated: dict[str, Mapping[dt.date, float]] = {}
    for name, series in book.items():
        if not isinstance(name, str) or not name.strip():
            raise EvaluatorMarginalError(
                f"the current book's signal names must be non-empty strings, "
                f"got {name!r}"
            )
        if name in validated:
            raise EvaluatorMarginalError(
                f"the current book names {name!r} twice; one signal, one series"
            )
        if not isinstance(series, Mapping):
            raise EvaluatorMarginalError(
                f"the current book's returns for {name!r} must map rebalance "
                f"date to a return, got {type(series).__name__}"
            )
        row: dict[dt.date, float] = {}
        for day, value in series.items():
            if not isinstance(day, dt.date) or isinstance(day, dt.datetime):
                raise EvaluatorMarginalError(
                    f"the current book's returns for {name!r} must be keyed by "
                    f"calendar dates, got {day!r}"
                )
            if day in row:
                raise EvaluatorMarginalError(
                    f"the current book's returns for {name!r} carry "
                    f"{day.isoformat()} twice under different spellings; one "
                    "bar, one return"
                )
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise EvaluatorMarginalError(
                    f"the current book's return for {name!r} on "
                    f"{day.isoformat()} must be a number, got {value!r}"
                )
            number = float(value)
            if not math.isfinite(number):
                raise EvaluatorMarginalError(
                    f"the current book's return for {name!r} on "
                    f"{day.isoformat()} is not finite ({value!r}); a NaN or ±inf "
                    "would reach the marginal IR dressed as a measurement"
                )
            row[day] = number
        validated[name] = MappingProxyType(row)

    horizon = _marginal_horizon(returns)
    series = returns.series[horizon]
    candidate_return: dict[dt.date, float] = {}
    for day in series.dates():
        returns_row = series.at(day)
        if not returns_row:
            # The priced grid defines the panel; a date this horizon did not
            # price has no forward return to pair, and inventing one is the
            # look-ahead the alignment refuses.
            continue
        candidate_return[day] = math.fsum(returns_row.values()) / len(returns_row)
    if not candidate_return:
        raise EvaluatorMarginalError(
            "the priced panel and the current book share no rebalance date at "
            "the marginal-IR horizon, so no information ratio was measured and "
            "there is no marginal IR to store — score and price an alignment "
            "with coverage first (features 75 through 79)"
        )

    # Every book signal must cover every date the candidate was priced on — a
    # book signal that misses a priced date is a hole in the resident array, not
    # a zero return (feature 75's absence rule, restated for the book).
    priced_dates = set(candidate_return)
    book_returns: dict[dt.date, float] = {}
    combined_acc: dict[dt.date, float] = {}
    for day in sorted(priced_dates):
        book_sum = 0.0
        per_date_combined = 0.0
        for name, row_values in validated.items():
            if day not in row_values:
                raise EvaluatorMarginalError(
                    f"the current book's signal {name!r} has no return on "
                    f"{day.isoformat()}, which the candidate was priced on; a "
                    "book signal that misses a priced date is a hole in the "
                    "resident array, not a zero return — every book signal must "
                    "cover every date the candidate was priced on"
                )
            book_sum += row_values[day]
            per_date_combined += row_values[day]
        book_returns[day] = book_sum / len(validated)
        per_date_combined += candidate_return[day]
        combined_acc[day] = per_date_combined / (len(validated) + 1)

    book_ir, _ = _information_ratio(
        book_returns, horizon=horizon, label="equal-weight book"
    )
    combined_ir, _ = _information_ratio(
        combined_acc, horizon=horizon, label="equal-weight book plus candidate"
    )
    candidate_ir, _ = _information_ratio(
        candidate_return, horizon=horizon, label="candidate"
    )
    ir_marginal = combined_ir - book_ir

    return MarginalIR(
        node_id=returns.node_id,
        snapshot_name=returns.snapshot_name,
        cost_model=returns.cost_model,
        horizon=horizon,
        dates=len(candidate_return),
        book_size=len(validated),
        book_ir=book_ir,
        combined_ir=combined_ir,
        candidate_ir=candidate_ir,
        ir_marginal=ir_marginal,
        book_returns=book_returns,
        combined_returns=combined_acc,
        candidate_returns=candidate_return,
    )
