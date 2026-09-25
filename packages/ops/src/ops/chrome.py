"""Feature 352's surface: the permanent chrome — the remaining clean
epoch count.

app_spec.xml, "Observability & Dashboards", feature 352: *System
displays the remaining clean epoch count in permanent dashboard chrome,
so depletion stays visible.*  The spec's ``ui_layout`` places it —
*"The primary panel is FDR_deploy with its provenance triple;
instrument status lamps and the remaining clean epoch count sit in
permanent chrome"* — and its success criteria state the acceptance:
*"The operator … sees the remaining clean epoch count at all times."*
Feature 351 landed the page and modelled its primary seat explicitly so
this content could hang beside it without moving the top line; this
module is that content — not a panel, not a figure competing with
§16's, but the page's *furniture*: the one strip that renders on every
page the dashboard ever draws, carrying the one number that tells the
operator how much system is left.

**The count is the promotion member's, read through its own gauge —
never re-spelled here.**  Feature 297 already answers exactly this
question — *"System reports remaining clean epochs as a depleting
count, which returns the figure so exhaustion is visible well before it
arrives"* — over the epoch ledger feature 294 persists (§13 item 4's
*"Sequestered epochs are retired permanently after 3 promotion
decisions.  Track in a ledger."*), and its derivation (a clean epoch is
one that has *not* served the budget) is shared with feature 296's
terminal verdict so the two cannot drift.  A chrome that re-implemented
any of that — its own ``SELECT``, its own ``served < budget``, its own
budget constant — would be a second place the system's remaining
lifetime could be computed two ways, and the operator staring at the
chrome would have no way to know which way they were staring at.  So
this module reaches the promotion member itself
(:func:`require_promotion`, the deferred-import door
:func:`~ops.fdr_route.require_scoring` opened for the scoring member)
and reads :class:`promotion.RemainingCleanEpochs` over
:class:`promotion.EpochCharges` — the gauge, over the charge store,
over the one table — and the figure on the screen is the figure
feature 297 returns, to the bit.

**"Permanent" is held three ways, the same three ways 351 held "rather
than an equity curve."**

* **structurally** — the page model (:class:`~ops.dashboard.
  DashboardPage`) *requires* its chrome: a page is not constructible
  without a carrier answering the chrome's display contract
  (:data:`_CHROME_CONTRACT` in the page module), so a chromeless
  dashboard cannot be *represented*, let alone rendered — the
  extension point 351's docstring named (*"chrome grows, the top line
  does not move"*) exercised one feature later, in the direction it
  promised;
* **in order** — :meth:`~ops.dashboard.OperatorDashboard.render` emits
  the chrome strip immediately beneath the title, before the primary
  panel's header, on **every** page: the populated page, and — the
  case "at all times" is really about — the honest-absence page where
  no campaign has closed and there is no numeral to read at all.  The
  one thing 351's render may draw above the primary numeral is chrome
  (its own test's words: *"Nothing renders above the numeral but
  chrome"*); this is that clause's other half, filled in;
* **by refusal** — a carrier that cannot answer the chrome's reads is
  refused by name (:class:`~ops.errors.DashboardRenderError`), a count
  that is not a non-negative count of rows is refused by name, and a
  ledger read that fails aborts the render in this member's
  vocabulary rather than being answered around.  A chrome that quietly
  showed a full ledger while the epochs ran out unseen is the state
  §13 item 4's ledger exists to make visible, not hide — feature
  297's own sentence for its absent-database refusal, and the failure
  mode this feature's whole clause (*"so depletion stays visible"*)
  exists to rule out.

**Zero is rendered, not refused — the visible exhaustion.**  Feature
297's law, inherited whole: a ledger that is empty, or whose every
epoch has served the budget, answers ``0``, and ``0`` is the *figure
the caller asked for* — §13 item 4's *"When clean epochs run out, the
system stops.  That is a legitimate terminal state."*  The chrome
renders the ``0`` exactly as it renders ``7``: no refusal, no blank,
and no quiet substitution, because a strip that went silent at the end
would hide the one moment it exists to show.  The contrast with the
primary panel's absence is deliberate and is the two features' split:
no campaign having closed is an *absence* (no numeral, words that say
why), while no clean epoch remaining is a *measurement* (the count is
zero, and the zero renders).

**The chrome is chrome, not content — one metric tile per page.**
§16's bolded sentence fixes the top-line number, and the render holds
that fixation structurally: the primary numeral is the page's one
``metric``, and the chrome strip is a ``caption`` — furniture, the
same word 351's own title docstring uses for what sits beside content.
A second metric tile for the count would put a figure *beside* the
top line in the same visual voice, and the count — a governance
gauge, not an epistemic figure — must never be readable as the
system's primary number.  Depletion stays visible as a persistent line
beneath the title, above the fold, on every render; it does not need
to shout, and it must not compete.

**One database, carried — never re-resolved.**  The gauge rides the
URL the route already resolved at composition (the composition fact
351 pinned: the route, the store component and the dashboard all point
at the one database ``DATABASE_URL`` names, §16's *"single Postgres
metrics table"* allowance).  :class:`EpochCountGauge` is constructed
over that carried URL and defers everything else — the promotion
import *and* the gauge construction — to the first ``remaining()``,
for the scan-order law :func:`~ops.fdr_route.require_scoring` states:
builders fire after the factory's scan has taken each member's
``src/`` back off ``sys.path``, so a build-time ``EpochCharges``
import would make this component's presence depend on an import that
is not promised to work at that moment.  From that first read on, the
gauge is the promotion member's own object and every law is its: the
whole-table read through feature 294's ``epochs`` seam, the shared
derivation, the refusal of a doubled row.

**No cache, because depletion moves.**  A chrome that memoised its
count would make "how much system is left?" a fact about when the
page was first opened — precisely the failure the feature's clause
names.  Every ``remaining()`` re-reads the ledger (feature 297's gauge
holds no cache either, for the same reason in its own words: a charge
lands in another process a moment after this one asked, and the epoch
that was clean is spent), so a promotion decision recorded between
two Streamlit reruns moves the second strip.

Stdlib-only at module scope, like the rest of the member:
:mod:`dataclasses` for the chrome value, :mod:`typing` for ``Any`` —
the promotion member is deferred past module scope and past builder
time, so importing this package (and composing the component that
renders it) performs no I/O and no sibling import.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .errors import DashboardRenderError

__all__ = [
    "EPOCH_COUNT_LABEL",
    "EpochCountChrome",
    "EpochCountGauge",
    "require_promotion",
]

#: The count's label — the spec's own phrase for the figure
#: (``ui_layout``: *"the remaining clean epoch count sit in permanent
#: chrome"*, feature 297's sentence: *"remaining clean epochs as a
#: depleting count"*), carried once so the chrome strip, the tests and
#: the spec cannot drift apart on the name of the thing depletion is
#: counted in.
EPOCH_COUNT_LABEL = "remaining clean epochs"


def require_promotion() -> Any:
    """Import and return the :mod:`promotion` member, or raise loudly.

    The mirror of :func:`~ops.fdr_route.require_scoring`, for the
    sibling that owns this chrome's figure: feature 297's gauge and
    feature 294's charge store live in the promotion member, and the
    count is read through them rather than re-spelled.  Deferred past
    module scope and past builder time for the same scan-order reason:
    the factory's workspace scan imports this package to fire its
    ``@register``, and the scan puts one member's ``src/`` on
    ``sys.path`` at a time — a module-scope ``import promotion`` here
    would make this member's *import* depend on scan order, and a
    build-time one would fire exactly where the import is not promised
    to work.  A deployment that genuinely needs the count and cannot
    reach the promotion member is told which wheel is missing rather
    than shown a bare :class:`ImportError`.
    """
    try:
        import promotion
    except ModuleNotFoundError as exc:  # pragma: no cover - declared dependency
        raise ModuleNotFoundError(
            "the ops member's chrome reads the remaining clean epoch "
            "count through the promotion member's own gauge (feature "
            "297's, over feature 294's ledger) rather than re-spelling "
            "the derivation, and that member is not importable in this "
            "environment; run `uv sync --all-packages` in the workspace "
            "root (or put packages/promotion/src on sys.path) so the "
            "gauge this chrome reads can be reached"
        ) from exc
    return promotion


# -- The chrome value ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EpochCountChrome:
    """The permanent chrome's content: the remaining clean epoch count.

    Thin by design, the same thinness :class:`~ops.dashboard.
    FdrDeployPanel` states for the primary seat: every guarantee this
    value's figure enjoys was earned where the figure was measured —
    feature 297's gauge, over feature 294's ledger, under the budget
    feature 295 reads — and the chrome adds exactly the display-shaped
    reads a render needs and re-spells nothing: no second derivation,
    no budget constant, no spelling of *clean* (the gauge already
    judged every row), no second read of the table.

    The figure is an ``int`` because it is a *count of rows* — the
    number of ledger rows that have not served §13 item 4's budget —
    and construction holds it to that: a non-negative ``int``, with
    ``bool`` refused first (``True`` is ``1`` in Python, and a flag
    where a count belongs would silently answer one clean epoch nobody
    sealed).  A negative count is refused because no count of rows is
    negative, and a figure that is not a count of rows — a fraction, a
    string, a ``None`` standing in for an unread gauge — is refused
    rather than rendered, because a strip that displayed it would be
    showing depletion nobody measured.  Both refusals are
    :class:`~ops.errors.DashboardRenderError`: they abort a render,
    and a caller guarding the render catches one vocabulary.

    There is deliberately no field here but the count.  The chrome's
    whole surface is one figure and its label — no trend, no history,
    no per-epoch detail (the ledger is the promotion member's to
    read, not this screen's to re-render), and nothing a P&L-shaped
    value could occupy, so the chrome cannot grow into a content
    panel one careless edit at a time.
    """

    #: The figure at the moment of the read — feature 297's count of
    #: ledger rows that have not served §13 item 4's budget.  Frozen
    #: testimony, like every value the page holds: the next render
    #: reads a fresh one.
    count: Any

    def __post_init__(self) -> None:
        if isinstance(self.count, bool) or not isinstance(self.count, int):
            raise DashboardRenderError(
                f"the dashboard chrome's remaining clean epoch count must "
                f"be a non-negative integer — got {self.count!r} "
                f"({type(self.count).__name__}). The count is feature "
                "297's figure — a count of ledger rows that have not "
                "served §13 item 4's budget, answered by the promotion "
                "member's own gauge — and a value that is not a count "
                "of rows is a figure nobody derived; rendering it would "
                "show depletion the ledger does not state (feature 352, "
                "prd §13 item 4)"
            )
        if self.count < 0:
            raise DashboardRenderError(
                f"the dashboard chrome's remaining clean epoch count must "
                f"be a non-negative integer — got {self.count!r}. The "
                "count is a count of ledger rows, and no count of rows "
                "is negative — a negative figure on a chrome that "
                "renders on every page would answer 'less than no "
                "system left', which is not a state the ledger can be "
                "in (feature 352, prd §13 item 4)"
            )

    @property
    def numeral(self) -> str:
        """The count as the render displays it — a bare integer, the
        form §13 item 4's budget is counted in.  Zero renders as
        ``"0"``: the spent ledger's answer is the figure itself, the
        visible exhaustion feature 297's sentence promises, not an
        absence to dash."""
        return str(self.count)

    @property
    def line(self) -> str:
        """The chrome strip as the render emits it — the count's one
        label and its figure (``"remaining clean epochs: 7"``), the
        whole of the permanent chrome's content.  Deliberately plain:
        chrome, not content — the strip states the figure and nothing
        else, the way the title states whose metrics these are and
        nothing else."""
        return f"{EPOCH_COUNT_LABEL}: {self.numeral}"


# -- The read seam -------------------------------------------------------------------


class EpochCountGauge:
    """The chrome's read seam: feature 297's gauge, deferred.

    The carrier the dashboard holds beside its route — the analogue
    of the route's :class:`~ops.fdr_route._DeferredFdrStore`, for the
    second figure the page reads.  Constructed over the database URL
    the route already resolved (the composition fact, carried — never
    re-read from the environment at render time, for the reason the
    deferred store states: the chrome and the top line must point at
    the one database the deployment named, not at whatever a later
    environment says), and it performs no I/O and imports no sibling
    until the first ``remaining()`` — which is precisely the moment
    the caller reached for the figure and therefore runs somewhere the
    declared dependency is importable.

    From that first read on, the work is the promotion member's own:
    ``EpochCharges(url)`` (feature 294's store, which brings the
    ledger up through the owning migration's own statements) wrapped
    in ``RemainingCleanEpochs`` (feature 297's gauge, which reads the
    whole table through the store's ``epochs`` seam and counts).  The
    gauge is constructed once and held — it caches nothing (feature
    297's own law, restated in this module's docstring), so every
    ``remaining()`` is a fresh whole-table read and depletion moves
    between renders.

    A refusal from the read propagates in the promotion member's own
    vocabulary — :class:`promotion.EpochChargeError` — because this
    carrier is the analogue of the route's
    :class:`~ops.fdr_route._DeferredFdrStore`, and that carrier's law
    is that the *seam caller* translates: the dashboard's
    :meth:`~ops.dashboard.OperatorDashboard.page` narrows the refusal
    into this member's :class:`~ops.errors.DashboardRenderError`, the
    original chained — the member-seam law :mod:`ops.fdr_route` states
    when it narrows the scoring store's failure into
    :class:`~ops.errors.FdrDeployMetricError`: a caller that guards
    the render with the dashboard's vocabulary must not be taken down
    by :class:`promotion.EpochChargeError`, an error from a module
    the caller never imported.  And neither the carrier nor the page
    ever catches a refusal *into* an answer, because every fallback
    count is a figure nobody measured, and a chrome showing one while
    the epochs ran out unseen is the state §13 item 4's ledger exists
    to make impossible.
    """

    def __init__(self, database_url: Any) -> None:
        """Wire the gauge to the database the ledger lives in.

        The URL is validated here, before any read, because it is a
        fact about the *chrome* rather than about any one count: a URL
        that is not a non-empty string names no ledger, and a gauge
        that accepted one would fail identically on every render —
        the wrong place for a deployment to discover a wiring fault.
        The URL the dashboard's own doors hand in is the route's
        carried one, already resolved; this refusal is for the caller
        that wires the gauge by hand.
        """
        if not isinstance(database_url, str) or not database_url.strip():
            raise DashboardRenderError(
                "the dashboard chrome's gauge must be wired to a "
                "non-empty database URL — the remaining clean epoch "
                "count is read from the epoch ledger in the database "
                "the deployment names (the same one DATABASE_URL named "
                "at composition, carried by the route), and a gauge "
                "pointed at nothing has no ledger to count. The chrome "
                "renders on every page, so it is refused at wiring "
                "rather than silently rendering a count nobody read "
                "(feature 352, prd §13 item 4)"
            )
        self._database_url = database_url.strip()
        # Resolved on first use rather than at construction: building
        # the dashboard is composition-time work and must not import a
        # sibling or touch a database — the deferral this class exists
        # to move, one act later than the route's own.
        self._gauge: Any = None

    @property
    def database_url(self) -> str:
        """The URL the gauge reads the ledger in — carried from the
        route's own resolution, not re-read, so the chrome cannot drift
        to a later environment."""
        return self._database_url

    def remaining(self) -> int:
        """The remaining clean epoch count — feature 297's figure, read
        through the promotion member's own gauge.

        The first call constructs the gauge over the carried URL
        (feature 294's charge store wrapped in feature 297's counting
        gate — the promotion member's objects, carrying the promotion
        member's laws); every call, first or later, asks it and
        answers what it answers.  A refusal the read raises — an
        unreadable ledger row, a doubled epoch, an unreachable
        database — propagates in the promotion member's vocabulary,
        the carrier stance the route's deferred store takes toward the
        scoring member's refusal: the translation into this member's
        render vocabulary is the seam caller's
        (:meth:`~ops.dashboard.OperatorDashboard.page`, where the
        ``except DashboardRenderError`` a render's caller writes is
        honoured), and nothing anywhere is ever caught into an answer —
        the count renders on every page or the render refuses, and
        there is no third behaviour a deployment could rely on.
        """
        promotion = require_promotion()
        if self._gauge is None:
            charges = promotion.EpochCharges(self._database_url)
            self._gauge = promotion.RemainingCleanEpochs(charges)
        return self._gauge.remaining()
