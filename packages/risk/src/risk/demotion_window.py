"""Feature 327: the observation window an auto-demotion must be taken over.

app_spec.xml, "Risk Supervisor & Kill Switches", feature 327: *"System
requires a statistically meaningful observation window before
auto-demotion fires, which rejects a demotion on a thin sample."*  The
requirement is not new with this feature — it has been sitting inside the
demotion row's own trigger since the architecture was written:
``docs/nullius-tech-architecture.md`` §13.3's table spells the row as
**Live IC < 40% of backtest IC over a meaningful window — Auto-demote the
signal**, and ``docs/alpha-engine-prd.md`` C10 carries both halves into
one product sentence: *"if live IC falls below 40% of backtest IC over a
statistically meaningful window, demote automatically."*  Feature 326
took the first half — the ratio, judged against the 40 percent bound and
persisted — and read the second half as decoration.  This feature is the
second half read as law: **the window is a precondition of the firing,
and a demotion attempted without it is rejected, not recorded.**

Four parts carry the whole contract, and the verb is *requires*:

* **The window is the count of observed days, handed over, never
  derived.**  The live IC the ratio divides is the *mean* of the observed
  rows — feature 333's record is one row per day — and a mean over three
  days and a mean over ninety are the same number and are not the same
  fact.  Feature 337 states that sentence in its own module and carries
  ``observed_days`` beside the ratio on its answer for exactly this
  reason: *"the count is the evidence prd §11's criterion is stated
  over"*.  The supervisor reads both off the forward member's public seam
  (:func:`forward.retention.forward_ic_retention`) and hands both over,
  the same "hand over, never derive" barrier :mod:`risk.demotion` holds
  toward the coefficients themselves: a member reaches into no sibling's
  tables, so this module names no forward column, opens no forward
  record, and counts nothing itself.  What the count *is over* — days,
  not rows-in-general — is the forward member's own grain, restated here
  only in the parameter's name.

* **"Statistically meaningful" is a requirement the deployment states,
  not a number this module guesses.**  The spec says *"statistically
  meaningful"* and names no number, and the one number the PRD does name
  in this neighbourhood — §11's *"at 90 days"* — is the *promotion*
  criterion's horizon, spelled in the promotion member's own criteria
  object, not a demotion line anybody drew here.  So
  ``minimum_observed_days`` arrives as a **required keyword with no
  default**, exactly as feature 328's threshold does for its band: a
  supervisor that guessed a window would demote on a track record nobody
  vouched for, which is the same act this feature exists to refuse with a
  shorter number.  A minimum of zero or less is refused rather than
  honoured — a gate open at every sample is the *absence* of this
  feature, not its configuration, and honouring it would read as a
  deployment that had set a window when it had set nothing at all.

* **The window is judged only once the ratio has fired.**  A ratio at or
  above :data:`~risk.demotion.DEMOTION_BOUND` answers ``None`` and the
  window is moot: the sentence requires the window *"before auto-demotion
  fires"*, and a held ratio is not a demotion firing — it is a signal
  this feature has no opinion about.  A supervisor that swept every cycle
  would otherwise raise on every young signal it was perfectly happy
  with, and the operator's log would teach them to ignore the token.  The
  asymmetry is feature 326's own, one level up: its no-store refusal
  bites only *"once the ratio has been judged to have fired"*, and this
  rejection bites only once the ratio has been judged to demote.  The
  counts' own terms are validated on every call regardless — a malformed
  ask is refused whether or not the ratio fired, because a caller that
  cannot state its evidence cannot be told it was happy.

* **A demotion on a thin sample is rejected, loudly.**  Not a silent
  ``None``: the demotion the caller asked for is below the bound and
  would have fired, and answering ``None`` would fold *"the signal is
  fine"* and *"the signal looks decayed but is not yet proven so"* into
  one indistinguishable answer — the two facts an operator most needs to
  tell apart on a young record.  So the rejection is a typed
  :class:`~risk.errors.RiskDemotionWindowError` carrying the
  :class:`DemotionWindow` it acted on, greppable by its token, and it
  leaves no row and does not so much as open the store: nothing was
  demoted, so there is nothing to account for.  The rejection is not a
  state and nobody clears it — it is re-judged on every cycle and stops
  being true by itself as the record accrues days, the same shape
  :mod:`risk.feed_staleness` gives its watchdog, and for the same
  reason: the condition it names is a fact about accumulating evidence,
  not a decision that stands.

**Why the window matters at all: the demotion is irreversible.**  Feature
326's table is first-write-wins with no clear — one signal, one demotion,
the first ratio and the first moment on record forever.  A demotion fired
on a thin sample is therefore not a demotion that can be walked back
tomorrow when the mean regresses: it is a signal that lost its promotion
on a fluke, permanently, by the very table designed to make demotions
permanent.  The live IC mean over a handful of days has a variance wide
enough to fall below any bound by chance alone, which is the whole
content of *"statistically meaningful"* — the window is what stands
between a fallen signal and noise that looks like one.

**The boundary: a window that has reached the minimum is meaningful.**
``observed_days >= minimum_observed_days`` is meaningful; strictly below
is thin.  A record that has observed exactly the required number of days
*has* a window of that many days — the requirement is met at it, not
past it, the reading the PRD's own *"at 90 days"* gives the word "at",
and the reason the boundary tests in this member's suite pin equality
rather than approximating it.  The thin side is strictly ``<``, joining
the workspace's boundary conventions beside it (feature 326's strict
``<`` on the ratio, feature 314's on the posture, feature 312's
neighbour rule).

**A meaningful window demotes exactly as feature 326 did — by
delegating to it, wholesale.**  :func:`demote_over_meaningful_window`
never restates the persistence: once the window is meaningful and the
ratio has fired, the act is handed to
:func:`risk.demotion.demote_on_ic_drop` and inherits everything that
spelling holds — first-write-wins over the ``node_id`` primary key, the
no-store refusal once the demotion has fired, the kernel-read process
identity, the re-read on a raced insert.  Nothing here opens the store,
validates the URL or stamps a moment, and that absence is deliberate: a
second spelling of any of those would be a second way for two demotions
of one signal to disagree.  The node, the ratio and the bound are
validated through feature 326's own validators before the comparison, so
one spelling of what those terms are decides both seams.

**Nothing is persisted by this module, and no component is registered.**
The demotion row is feature 326's five facts — the ratio, the bound, the
moment, the signal, the process — and the window is a judgement, not a
record: adding the count to the row would re-state feature 326's table
for a fact the rejection already names in its message, and a demotion
that fired carries its window's *consequence* (it fired), not its
evidence.  There is no fifth builder for the same reason feature 326
registered none: the gate owns no table and no state an application could
carry, and the supervisor process that judges reaches the module-level
spelling without composing, exactly as it reaches the demotion, the
channel and the flatten before it.  And as with the demotion itself:
this module sends no kill, flattens nothing and touches no order — it
gates one signal's promotion, and the weight that follows a demotion is
whichever process consumes :mod:`risk.demotion`'s record, not a second
way to stop the order layer minted here.

**No clock is read anywhere in this module.**  The window is a *count of
days* handed over, not a span this module measures between two instants:
the days were already counted by the member that observed them, and a
second counting — a ``date`` subtraction against a "now" this module
supplied itself — would be a second opinion about evidence this module
has explicitly decided not to derive.  The module imports no datetime at
all, and that absence is the barrier stated in its imports.

Storage is unchanged by this feature: when the window is meaningful the
delegation lands the row in ``risk_signal_demotion`` through
``DATABASE_URL`` exactly as before, and when it is not, nothing is opened
at all — the rejection, like the held ratio, is a judgement that costs no
I/O.  The absence of a store cuts the way feature 326's no-store refusal
already cuts, reached one judgement later: a thin sample is rejected
before any store is demanded (there is no demotion to account for), a
meaningful window over a firing ratio with no store named is refused by
feature 326's own spelling (from that moment the signal is demoted and
nothing would record why), and a held ratio answers ``None`` on the same
absence for the same reason it always has.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .demotion import (
    DEMOTION_BOUND,
    NODE_ID_COLUMN,
    SignalDemotion,
    _require_bound,
    _require_ratio,
    _require_uuid,
    demote_on_ic_drop,
)
from .errors import DEMOTION_WINDOW_CODE, RiskDemotionWindowError

__all__ = [
    "DemotionWindow",
    "demote_over_meaningful_window",
]


# -- The counts' own terms --------------------------------------------------------


def _validated_observed_days(value: object) -> int:
    """Return ``value`` as a whole positive observed-day count, or refuse it.

    The count is how many days carried a measurement — the mean's
    denominator, the figure feature 337 carries beside the ratio as *the
    evidence for it*.  Whole and positive, and ``bool`` refused *before*
    the number is looked at, for the reason :mod:`risk.demotion` refuses
    it toward the ratio: ``isinstance(True, int)`` is true in Python, so a
    ``observed_days=True`` would pass a naive numeric check and put a
    one-day window behind a demotion nobody meant to vouch for.  Zero and
    negatives are refused here rather than answered as "thin": a signal
    with no observed day has no live coefficient for a retention ratio to
    have been taken over at all — the forward member refuses that state
    earlier, by name — so a zero reaching here is a caller asserting an
    absence the seam it claims to have read already refuses.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise RiskDemotionWindowError(
            f"{DEMOTION_WINDOW_CODE}: observed_days must be the number of "
            f"days the signal was measured as a whole number — got "
            f"{value!r} ({type(value).__name__}); the count is the evidence "
            "the demotion line is stated over, and a ratio handed over an "
            "unstated number of days is a figure §C10's line would act on "
            "without knowing how much track record stood behind it "
            "(feature 327)"
        )
    if value < 1:
        raise RiskDemotionWindowError(
            f"{DEMOTION_WINDOW_CODE}: observed_days must be at least 1 — "
            f"got {value}; a signal with no observed day has no live "
            "coefficient for a retention ratio to have been taken over, "
            "and that absence is the forward member's own refusal rather "
            "than a window this feature could judge (feature 327)"
        )
    return value


def _validated_minimum(value: object) -> int:
    """Return ``value`` as a whole positive day requirement, or refuse it.

    The minimum is what *"statistically meaningful"* means for the
    deployment asking — a required keyword with no default, because the
    spec names the phrase and no number (see the module docstring).  The
    same whole-number and ``bool`` gates the observed count holds, and
    then one more: a minimum of zero or less is refused rather than
    honoured, because a gate open at every sample is not a lenient window
    but the absence of this feature — honouring it would let the demotion
    fire on the first day's noise while the record read as though a
    requirement had been set and met.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise RiskDemotionWindowError(
            f"{DEMOTION_WINDOW_CODE}: minimum_observed_days must state the "
            f"observation window the deployment requires as a whole number "
            f"of days — got {value!r} ({type(value).__name__}); the spec "
            "names *statistically meaningful* and no number, so the "
            "requirement is the deployment's to state, and a window that "
            "is not one number is a line nobody drew (feature 327)"
        )
    if value < 1:
        raise RiskDemotionWindowError(
            f"{DEMOTION_WINDOW_CODE}: minimum_observed_days must be at "
            f"least 1 — got {value!r}; a minimum of zero or less is a gate "
            "open at every sample, and the demotion would fire on the "
            "first day's noise, which is the act this feature exists to "
            "refuse rather than a window it could accept (feature 327)"
        )
    return value


# -- The window -------------------------------------------------------------------


@dataclass(frozen=True)
class DemotionWindow:
    """One demotion's observation window: the days seen, the days required.

    A *value* — frozen, self-describing — carrying the whole of feature
    327's judgement: this many days were observed, and the deployment
    required that many.  Both counts are whole positive numbers by
    construction (``__post_init__`` refuses anything else, the same
    value-layer-is-the-law discipline :class:`~risk.demotion.
    SignalDemotion` holds toward its own arithmetic), and the judgement
    itself is **derived, never stored**: ``meaningful`` and ``thin`` are
    properties over the two counts, so a window cannot disagree with its
    own numbers, and a caller holding one is holding the evidence and the
    requirement in one object.

    The window is deliberately constructible *thin*: a thin window is not
    a malformed one, it is the state the rejection names — the record is
    younger than the requirement, which is true of every promoted signal
    on its first day and stops being true by itself as days accrue.  What
    is refused is a count that is not a count (a ``bool``, a fraction, a
    word) or a requirement that states no requirement.
    """

    #: How many days carried a measurement — the mean's denominator,
    #: feature 337's own field name, handed over by whoever read the
    #: retention.  The *evidence* for the ratio, in the days it was
    #: measured over.
    observed_days: int
    #: How many observed days the deployment requires before a demotion
    #: may fire — the spelling of *"statistically meaningful"* for the
    #: caller asking.  A required keyword on the seam below; a field here
    #: so the refusal that names it and the caller that stated it hold
    #: one object.
    minimum_observed_days: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "observed_days", _validated_observed_days(self.observed_days)
        )
        object.__setattr__(
            self,
            "minimum_observed_days",
            _validated_minimum(self.minimum_observed_days),
        )

    @property
    def meaningful(self) -> bool:
        """Whether the window carries the days the requirement demands.

        ``>=``, pinned at equality: a record that has observed exactly the
        required number of days *has* a window of that many days, the
        reading the PRD's own *"at 90 days"* gives the word *at* — the
        requirement is met at the boundary, not past it.
        """
        return self.observed_days >= self.minimum_observed_days

    @property
    def thin(self) -> bool:
        """Whether the sample is too thin to demote on — strictly below.

        The state the rejection names, and the reason it is a property
        rather than a field: thin is not a fact anyone states, it is the
        comparison between the two that are.
        """
        return not self.meaningful

    @property
    def days_short(self) -> int:
        """How many more observed days the window needs, or zero.

        Composed rather than stored, because it is arithmetic over the two
        counts — a stored copy would be a second place for them to
        disagree with.  Zero on a meaningful window, so the property never
        answers a negative shortfall for a window that has passed its
        requirement.
        """
        return max(self.minimum_observed_days - self.observed_days, 0)


# -- The seam ---------------------------------------------------------------------


def demote_over_meaningful_window(
    node_id: object,
    *,
    ratio: object,
    observed_days: object,
    minimum_observed_days: object,
    bound: object = DEMOTION_BOUND,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
    supervisor_process_id: str | None = None,
) -> SignalDemotion | None:
    """Judge the window, then the demotion — the gated spelling of feature 326.

    The supervisor's one call once feature 327 is in force: hand over the
    signal's identity, the retention ratio the forward member computed,
    the observed-day count it computed the ratio over, and the window the
    deployment requires.  The judgement runs in the order the sentence
    states it — the ratio against the bound first, the window before the
    *firing* — and each stage has one answer:

    * **A held ratio answers ``None``**, window moot: a ratio at or above
      the bound is not a demotion firing, and a young signal this feature
      is happy with must not raise on evidence it was never asked to
      judge.  ``None`` is the answer, not an error, and no store is
      opened — feature 326's own answer, inherited before the window is
      ever consulted.
    * **A firing ratio over a thin sample is rejected** in
      :class:`~risk.errors.RiskDemotionWindowError`, the window riding on
      the error: the demotion the caller asked for would have fired, and
      the rejection says so — naming the days seen, the days required,
      and the ratio that fell — rather than folding *"fine"* and
      *"unproven"* into one silent ``None``.  No row is written and no
      store is opened; the rejection is re-judged next cycle and lifts by
      itself as the record accrues days.
    * **A firing ratio over a meaningful window demotes exactly as
      feature 326 does**, by delegating to
      :func:`risk.demotion.demote_on_ic_drop` — first-write-wins, the
      kernel-read process identity, the no-store refusal, all inherited
      and none restated.  The returned record is the row that landed.

    The counts' own terms are validated before anything else, so a
    malformed window is refused whether or not the ratio fired; the
    node, the ratio and the bound are validated through feature 326's own
    validators, so one spelling of what those terms are decides both
    seams.  ``minimum_observed_days`` is required and has no default —
    the spec names *"statistically meaningful"* and no number, and a
    supervisor that guessed a window would demote on a track record
    nobody vouched for.

    Raises :class:`~risk.errors.RiskDemotionWindowError` for a count that
    is not a whole positive number, a minimum that states no requirement,
    or a demotion on a sample thinner than the window; and
    :class:`~risk.errors.RiskSignalDemotionError` for a node that is not
    a signal identity, a ratio that is not a number, or a bound that is
    not a band (judged here, but through feature 326's own validators and
    in that feature's own words, so both seams refuse identically), and —
    this one *from* the delegation — for a fired demotion with no store
    named to record it.
    """
    window = DemotionWindow(
        observed_days=observed_days,
        minimum_observed_days=minimum_observed_days,
    )
    node = _require_uuid(node_id, NODE_ID_COLUMN)
    ratio_value = _require_ratio(ratio, "retention_ratio")
    bound_value = _require_bound(bound)
    if not (ratio_value < bound_value):
        # A held ratio is not a demotion firing, and the sentence requires
        # the window only "before auto-demotion fires": a supervisor
        # sweeping every cycle must not raise on the young signals it is
        # happy with, or the operator's log teaches them to ignore the
        # token.  Feature 326's own asymmetry, one level up.
        return None
    if window.thin:
        # The demotion would have fired, and the sample cannot carry it.
        # Rejected rather than answered: "the signal is fine" and "the
        # signal looks decayed but is not yet proven so" are the two facts
        # an operator most needs told apart on a young record, and a
        # silent None folds them into one.  Nothing is written and nothing
        # is opened -- the rejection is re-judged next cycle and lifts by
        # itself as the record accrues days.
        raise RiskDemotionWindowError(
            f"{DEMOTION_WINDOW_CODE}: the signal demotion of {node} is "
            f"rejected on a thin sample: {window.observed_days} observed "
            f"day(s) against the {window.minimum_observed_days} the "
            f"deployment requires, {window.days_short} short, for a "
            f"retention ratio of {ratio_value!r} below the "
            f"{bound_value!r} bound. A live IC mean over fewer days than "
            "the window has a variance wide enough to fall below the "
            "bound by chance alone, and the demotion is first-write-wins "
            "with no clear -- a signal demoted on noise keeps the loss of "
            "its promotion forever. The rejection lifts by itself as the "
            "record accrues days; nothing was demoted and nothing is on "
            "record (feature 327)",
            window=window,
        )
    return demote_on_ic_drop(
        node_id,
        ratio=ratio,
        bound=bound,
        database_url=database_url,
        env=env,
        supervisor_process_id=supervisor_process_id,
    )
