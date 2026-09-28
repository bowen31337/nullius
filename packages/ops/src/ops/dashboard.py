"""Feature 351's surface: the Streamlit dashboard, primary panel first.

app_spec.xml, "Observability & Dashboards", feature 351: *System renders
a Streamlit dashboard whose primary panel displays FDR_deploy rather
than an equity curve.*  The category's root (feature 341, the GET
/metrics/fdr-deploy route) established the seam every later feature
hangs from; this module is the one that hangs a *screen* from it — the
operator surface the spec's ``ui_layout`` draws: *"Operator surface is
a Streamlit dashboard reading the Postgres metrics table, which is the
simpler option the architecture explicitly permits at this scale.  The
primary panel is FDR_deploy with its provenance triple"* (docs §16's
stack line: *"a single Postgres metrics table with a Streamlit
dashboard if you would rather not run infrastructure"*).

**§16's one bolded sentence is the whole design brief.**  *"**The
top-line dashboard number is ``FDR_deploy``, not Sharpe.**  If the
primary chart is an equity curve, the system's actual purpose has been
quietly abandoned."*  The app spec's design system carries the rule
over as the one binding presentation rule in scope (*"the top-line
number is FDR_deploy and never an equity curve; any panel that would
promote profit above epistemic state is rejected at review"*) and its
success criteria state the acceptance test (*"The operator reads
FDR_deploy as the primary figure with its provenance triple visible …
No screen presents an equity curve above the fold"*).  This module
holds that law three ways, each concrete:

* **structurally** — the page model (:class:`DashboardPage`) has
  exactly one primary seat, and the only type that fills it
  (:class:`FdrDeployPanel`) is derived wholly from feature 341's
  :class:`~ops.fdr_route.FdrDeployResponse`; there is no field
  anywhere on the model a returns series, a NAV curve or a Sharpe
  could occupy, so the substitution cannot be *represented*, let
  alone rendered;
* **at review** — constructing a page whose primary panel does not
  answer the FDR panel's display contract is refused by name
  (:class:`~ops.errors.DashboardRenderError`), the model-level
  spelling of the spec's "rejected at review": the failure §16 names
  is a *quiet* abandonment, and a quiet acceptance of a foreign
  primary panel is the same failure one layer up;
* **in order** — :meth:`OperatorDashboard.render` emits the primary
  panel's numeral before any chart and draws the only chart it ever
  draws from the panel's own FDR_deploy trend, so nothing renders
  above the fold but epistemic state.

**The page is a reader of the route, the route a reader of the store.**
The dashboard owns no figure of its own — the member's law, stated in
its package docstring, is delegation — so :class:`FdrDeployPanel` is
built from feature 341's response and derives every display read from
it: the numeral is the response's newest campaign figure, the plate
beneath it the response's own attribution (the campaign that measured
it and the instant it was computed), and the trend drawn below the
fold is the same history the numeral was drawn from — one answer, not
two that could disagree.  prd §4.1.3's barred figure (the raw
in-campaign rate) is unreachable here by the same delegation: the
response cannot carry it, so no panel built from a response can
display it.

**The triple beside the figure is read from the campaign's own node
rows — the one read the panel does *not* take from the response.**
app_spec.xml's ``ui_layout`` draws the primary panel whole: *"The
primary panel is FDR_deploy with its provenance triple"*, and its M5
success criteria state the acceptance (*"The operator reads
FDR_deploy as the primary figure with its provenance triple visible"*).
The browser validation of the user journeys found the page rendering
the figure without the triple (docs/user-journeys/RESULTS.md, run 1,
J06 — *"No triple is shown"*), and this module closes that gap the way
J06's own line draws it: the newest campaign's ``evaluator_hash``,
``snapshot_hash`` and ``cost_model_hash`` — §9.1's three ``CHAR(64)``
columns on the ``node`` table, feature 99's, stamped by the writer the
way feature 87 stamps the ledger's — are read from *that campaign's
node rows* in the one database the route already carries, and rendered
beside the numeral in short form with the full-width spelling held on
the value (J06: *"short form, full on hover/expand"* — the value is
the expand).  Three states, and only three:

* **recorded** — the campaign's node rows all carry the same complete
  triple, and that triple renders: the figure is attributed to the
  evaluator that scored it, the snapshot it sliced and the cost model
  that priced it, the reproducibility §16's structured-logging line
  assumes (*"every evaluation emits one record carrying the full
  provenance triple"*);
* **provenance unrecorded** — no node row carries a complete triple,
  whether because the campaign closed no node into the table, the
  table or its columns have not been brought yet, or the rows predate
  feature 99's stamp (the NULL the migrations' legacy repair leaves,
  the same spelling the ledger's read gives a row that predates
  feature 87's) — and the panel says *provenance unrecorded*, J06's
  own words, never a hash nobody recorded;
* **mixed provenance** — the campaign's node rows carry more than one
  distinct triple, and the panel renders the error message that names
  the disagreement, displays no triple and averages none (J06: *"one
  whose nodes disagree is refused as mixed provenance, never
  averaged"*): picking either triple would misattribute the figure to
  one evaluator when the campaign ran under two, the quietly-wrong
  attribution this family refuses everywhere it can.

A row that predates the stamp states no triple and so cannot disagree
— the join is over *complete* triples, and a statement nobody made
cannot contradict one somebody did.  A term that is not the
hexdigest's own 64-hex spelling is refused by name, because a hash
that names nothing rendered beside the figure would be provenance no
audit can replay.  And a *broken* read — a database that will not
open, a row that will not read — refuses the render rather than
folding into the unrecorded words: "provenance unrecorded" is reserved
for the state where no node carries the triple, and a broken read
wearing it would hide the break behind an honest-sounding absence.
Only the schema-absent spellings (no ``node`` table, no trio columns —
the discoverable states the migrations' own chain ordering names) fold
into unrecorded, because there the rows honestly carry nothing.

**Each point of the trend is labelled by its campaign's
``computed_at`` instant — never a bare index.**  The journey
validation found the populated page's chart drawing its x-axis as a
bare ``0, 1, 2`` (*"with no campaign or date"*, docs/user-journeys/
RESULTS.md run 1, J02), and this module closes that gap the way the
feature's own clause spells it: the panel answers the trend's
*points* — each campaign's figure paired with the instant that
campaign was computed, oldest first (:attr:`FdrDeployPanel.points`)
— and the render hands the carrier each point labelled by its
instant, the instant column named ``x=`` and the figure column
``y=`` (the two column names the one spelling each already carries:
:data:`COMPUTED_AT_LABEL`, the response's own field name for the
instant, and :data:`FDR_DEPLOY_LABEL`, §16's name for the figure).
The label is the instant rather than the campaign id because the
instant is the fact the trend's own order reads — the store answers
oldest-first *by ``computed_at``* — so the operator reading the
figure across campaigns (prd §12's M3 exit, *"``FDR_deploy``
improves"*, a falling sequence) can ask *when* each point was
measured, which a chart whose x-axis carried only position could
never answer.

**The qualifier beside the figure is read from the one spelling.**
§16 lists the research metric as *"``FDR_deploy`` at π₀ = 0.9"*, and
the scoring member's own law is that *"the base rate travels in the
row beside the number"* — so the panel's headline carries the
qualifier, read at display time through
:func:`~ops.fdr_route.require_scoring` from
:data:`scoring.DEPLOYMENT_BASE_RATE` (π₀, spelled once in
:mod:`scoring._fdr`), never re-stated as a literal here: a dashboard
that hard-coded ``0.9`` would be a second place the deployment
projection's constant could drift from the one feature 267 reweights
under and the M3 gate judges.

**An empty trend renders an honest absence, never a flawless numeral.**
Feature 341's route answers a deployment that has closed no campaign
with ``None`` figures and a falsy value, and its own docstring hands
this surface its law: *"The dashboard this route feeds renders no
numeral for it; what it must never render is a flawless one."*  The
render emits a dash where the numeral would be and words that say why
— no ``0.0``, which is a *measurement* (a campaign that projected to
no false discoveries), and no chart of an empty series either.

**An absent route is refused, never answered around.**  The seat's
docstring (:mod:`app.modules.ops`) names this module as the caller
that must take exactly this stance: *"a caller that needs the
top-line figure and resolves ``None`` must refuse to proceed rather
than rendering a numeral nobody measured.  The dashboard this route
feeds (feature 351's) is that caller."*  :meth:`OperatorDashboard.
composed` honours it — a composed application that carries no
``ops-fdr-deploy`` route (no ``DATABASE_URL``, member not scanned) is
refused with :class:`~ops.errors.DashboardRenderError` naming the
repair — and a *failed* read propagates as feature 341's own
:class:`~ops.errors.FdrDeployMetricError`, already this member's
vocabulary: re-wrapping it would only bury the route that refused.

**Feature 352's chrome hangs off the page beside the seat, exactly
where the page model promised it could.**  The dashboard now reads a
second figure — the remaining clean epoch count, the spec's
``ui_layout`` *"the remaining clean epoch count sit in permanent
chrome"* and its success criteria's *"sees the remaining clean epoch
count at all times"* — and the whole of that feature lives in
:mod:`ops.chrome`, which this module only wires and renders: the
count is read through a gauge (the promotion member's own, feature
297's, reached through a deferred door) held beside the route, the
page model *requires* its chrome so a chromeless page cannot be
represented, and the render emits the chrome strip as one caption
beneath the title — above the fold, on every page, including the
honest-absence one — before the primary panel's header.  Chrome
grows; the top line does not move: the primary numeral is still the
page's one ``metric``, the trend still the one chart, and the count
is furniture — visible always, competing never.  See
:mod:`ops.chrome`'s own docstring for the feature's law whole.

**The instrument lamps hang there too — the second strip of the same
chrome, and the rail is feature 342's own answer.**  app_spec.xml's
``ui_layout`` names both strips in one clause (*"instrument status
lamps and the remaining clean epoch count sit in permanent chrome"*)
and its M5 success criteria state the acceptance a second time
(*"sees instrument status as three binary lamps"*); the user-journey
validation found the page rendering only the count (docs/user-journeys
J04), and this module closes that gap by *reading the rail through the
member's own route*: the dashboard holds the composed
``ops-instrument-status`` endpoint (feature 342's
:class:`~ops.instrument_status.InstrumentStatusEndpoint`, each lamp
the owning member's own verdict) beside the route and the gauge, the
page model requires its lamps so a lampless page cannot be
represented, and the render emits one caption per lamp — canary, KS
guard, ingest, in docs §5.4's order, above the count strip — on every
page the dashboard draws.  Each lamp renders *lit* or *dark*, and a
lamp with no reading renders *no reading*, never lit: the three
states live in :mod:`ops.chrome` (the value, the state words, the
strip's lines), and the whole law with them.  A rail read that fails
arrives as feature 342's own
:class:`~ops.errors.InstrumentStatusError` — already this member's
vocabulary — and propagates untranslated, the same stance the route's
own refusal enjoys one seat over.

**Streamlit is the deployment's ambient dependency, not a workspace
one.**  §16's stack line names Streamlit the way it names Postgres —
an environment the operator runs, not a library the research loop
links against — so this member's pyproject gains no third-party edge
and the lockfile none either, and the render seam is duck-typed: the
carrier is handed in (:meth:`OperatorDashboard.render`'s ``st``) or
resolved through :func:`require_streamlit`, deferred past module scope
for the same scan-order reason :func:`~ops.fdr_route.require_scoring`
defers the scoring member — a module-scope ``import streamlit`` would
make this package's *import* depend on an environment the factory's
scan never promised to have it.  The contract is the calls the render
makes (``set_page_config``, ``title``, ``header``, ``metric``,
``caption``, ``line_chart``), duck-checked rather than
``isinstance``-guarded, because the factory's scan imports members
under synthetic names and the contract — not the class — is what
crosses every seam in this workspace.  The numeral is rendered
without a ``delta``: Streamlit colours a delta green-up, and the
figure has no "up is good" direction — a lower false discovery rate
is better — so the colour would state the opposite of the measurement
(green-up / red-down is also the first row of docs/design.md's
explicitly rejected table, though that document's console is out of
scope for this spec).

**The entrypoint is the module itself.**  ``streamlit run
packages/ops/src/ops/dashboard.py`` executes this file as a script,
outside the package import machinery, so the guard at the top of the
module puts the member's ``src/`` on ``sys.path`` and resolves
``__package__`` before the relative imports run — the same
reach-the-package-root discipline the member's test suites bootstrap
with — and the ``__main__`` block at the bottom calls :func:`main`,
which composes the application through the seat and renders.  A rerun
(Streamlit re-executes the page on every interaction) re-runs the
whole path: the route holds no cache, so the numeral is the store's
state at the moment of the rerun, not a fact about when the page was
first opened.

**A refusal the entrypoint catches is displayed, never escaped as a
traceback.**  The validation found the misconfigured deployment's
page rendering the refusal as a raw Python traceback — absolute
filesystem paths included, plus Streamlit's *Ask Google / Ask
ChatGPT* buttons (docs/user-journeys/RESULTS.md run 1, J03) — and
this module closes that gap at the one seam it lives on:
:func:`main`, the door ``streamlit run`` lands on.  A traceback is a
*programmer's* answer to a refusal this workspace already spells as
an *operator's* one — every message in the render vocabulary names
what is wrong and the one repair — so :func:`main` resolves the
carrier *first* (a deployment without Streamlit still gets the
deferred door's own repair words — the one refusal there is nothing
to display it with), then runs compose-and-render inside a single
``except`` over :class:`~ops.errors.OpsError`, the member's base, so
every way the page can refuse to draw — the composition door's
:class:`~ops.errors.DashboardRenderError`, the route's
:class:`~ops.errors.FdrDeployMetricError`, the rail's
:class:`~ops.errors.InstrumentStatusError` — displays as one
:func:`render_refusal` line: the code word
(:data:`DASHBOARD_REFUSAL_CODE`) beside the refusal's own words, one
line, no traceback and no filesystem path (the member's standing
constraint on every refusal it answers), and nothing else on the page
— no numeral, no chrome, no chart, because :meth:`OperatorDashboard.
render` asks the whole page before it emits anything and a refused
page is refused whole.  The refusal is not swallowed into a page:
:func:`main` answers ``None`` because no page drew, and a
programmatic caller that wants the exception still composes and
renders directly — :meth:`OperatorDashboard.render` raises, exactly
as its own tests pin.

Stdlib-only, like the rest of the member: :mod:`dataclasses` for the
page model, :mod:`sqlite3` for the node-table read (the triple's own
SELECT, translated through the workspace's one URL-to-path grammar),
:mod:`contextlib`/:mod:`pathlib`/:mod:`urllib.parse` for the plumbing
around it, :mod:`typing` for ``Any``/``Optional`` — streamlit and the
scoring member are both deferred past module scope and past builder
time, so importing this module (and composing the component it
registers) performs no I/O and no sibling import.
"""

from __future__ import annotations

if __package__ in (None, ""):  # pragma: no cover - the streamlit-run script path
    # `streamlit run packages/ops/src/ops/dashboard.py` executes this
    # file as a script: no package context, so the relative imports
    # below would fail before the dashboard ever rendered.  Put the
    # member's src/ on sys.path and resolve __package__ — the same
    # reach-the-package-root bootstrap the member's test suites use —
    # and only when the module is NOT being imported as ops.dashboard.
    import sys as _sys
    from pathlib import Path as _Path

    _member_src = str(_Path(__file__).resolve().parents[1])
    if _member_src not in _sys.path:
        _sys.path.insert(0, _member_src)
    __package__ = "ops"

import sqlite3
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote, urlparse

from app.module_loader import create_app
from app.modules.ops import fdr_deploy_component, instrument_status_component

from .chrome import (
    EPOCH_COUNT_LABEL,
    EpochCountChrome,
    EpochCountGauge,
    InstrumentLampsChrome,
    require_promotion,
)
from .errors import DashboardRenderError, OpsError
from .fdr_route import (
    FDR_DEPLOY_ROUTE,
    FdrDeployEndpoint,
    FdrDeployResponse,
    require_scoring,
)
from .instrument_status import INSTRUMENT_STATUS_ROUTE, InstrumentStatusEndpoint

__all__ = [
    "COMPUTED_AT_LABEL",
    "DASHBOARD_PAGE_TITLE",
    "DASHBOARD_REFUSAL_CODE",
    "DASHBOARD_TITLE",
    "FDR_DEPLOY_LABEL",
    "PROVENANCE_COLUMNS",
    "PROVENANCE_UNRECORDED",
    "CampaignProvenance",
    "DashboardPage",
    "FdrDeployPanel",
    "NodeProvenanceReader",
    "OperatorDashboard",
    "main",
    "render_refusal",
    "require_streamlit",
]

#: The primary metric's label — §16's own spelling of the top-line
#: number's name ("The top-line dashboard number is ``FDR_deploy``, not
#: Sharpe"), carried once so the numeral's label, the panel's headline
#: and the spec's figure cannot drift apart on the name.
FDR_DEPLOY_LABEL = "FDR_deploy"

#: The trend chart's label column — the name of the fact each point of
#: the trend is labelled by: the response's own field name for the
#: instant the campaign was computed (``computed_at``, the label the
#: trend's own order reads), carried once so the panel's points, the
#: chart's x column and the render's ``x=`` spelling cannot drift apart
#: on what labels a point.  The label is the instant, never a bare
#: index and never the campaign id beside it in the row (see
#: :attr:`FdrDeployPanel.points` for the law whole).
COMPUTED_AT_LABEL = "computed_at"

#: The dashboard's visible title — one word, the deployment's name.
#: Chrome, not content: it states whose metrics these are and nothing
#: else (no return figure in the navigation — there is no screen where
#: that is the question being asked).
DASHBOARD_TITLE = "Nullius"

#: The browser tab's title for the dashboard page — the Streamlit page
#: configuration's ``page_title``, emitted before anything renders
#: because Streamlit only honours it as the first command on the page.
DASHBOARD_PAGE_TITLE = "Nullius — deployment metrics"

#: The provenance triple's three names, in §9.1's own order — the same
#: spelling the ledger member carries as its
#: :data:`ledger.provenance.PROVENANCE_COLUMNS` and migration 0116 adds
#: to the ``node`` table, restated here because a member states its own
#: contract: the SELECT the reader makes names its columns from this
#: tuple, so the panel's read and the schema's columns cannot drift
#: apart on which three terms are the triple.
PROVENANCE_COLUMNS = ("evaluator_hash", "snapshot_hash", "cost_model_hash")

#: The words the panel renders when the campaign's node rows carry no
#: complete triple — J06's own spelling (*"A campaign with no recorded
#: triple says provenance unrecorded"*), carried once so the render, the
#: tests and the journey's acceptance line cannot drift apart on the
#: words of the honest absence.  Never a hash nobody recorded, and never
#: a broken read wearing these words (see :class:`CampaignProvenance`).
PROVENANCE_UNRECORDED = "provenance unrecorded"

#: The dashboard refusal's code word — the one greppable token every
#: operator-facing refusal display carries, J03's own ask (*"what is
#: wrong, the code word, and the one repair"*).  The refusal's own
#: message already names what is wrong and the one repair (the
#: workspace's law for every typed error this member raises); the code
#: word is the token an operator greps the docs and the logs for, and
#: it is one word for the whole display because the display answers one
#: question — *the dashboard refused; what repair does its own message
#: name?* — with the *which surface refused* half already carried by
#: the message's own words.  Spelled once here so the display
#: (:func:`render_refusal`), the tests and the journey's acceptance
#: cannot drift apart on it.
DASHBOARD_REFUSAL_CODE = "dashboard_refusal"

#: The primary panel's display contract — the reads the render makes of
#: whatever occupies the page's primary seat.  A carrier that does not
#: answer them all is not an FDR_deploy panel, and the page refuses it
#: (see :class:`DashboardPage`): the named, actionable spelling of the
#: spec's "rejected at review".  ``provenance`` is the triple's seat —
#: the read the render makes beside the numeral — and the carrier it
#: answers is itself judged against :data:`_PROVENANCE_CONTRACT`.
_PRIMARY_PANEL_CONTRACT = (
    "figure",
    "trend",
    "qualifier",
    "headline",
    "numeral",
    "plate",
    "series",
    "points",
    "provenance",
)

#: The permanent chrome's display contract — the reads the render makes
#: of whatever occupies the page's chrome seat (feature 352's, the
#: extension point the class docstring below named one feature ahead
#: of the feature that used it).  A carrier that does not answer them
#: all cannot sit in permanent chrome, and the page refuses it (see
#: :class:`DashboardPage`): the spec's *"the remaining clean epoch
#: count sit in permanent chrome"* and *"sees the remaining clean epoch
#: count at all times"* are one law, and a page that could be built
#: without a carrier answering the count would be a page on which
#: depletion could go unseen.
_CHROME_CONTRACT = (
    "count",
    "numeral",
    "line",
)

#: The instrument lamps' display contract — the reads the render makes
#: of whatever occupies the page's lamps seat (docs §5.4's rail, the
#: second strip of the permanent chrome, named beside the count in
#: app_spec.xml's ``ui_layout``: *"instrument status lamps and the
#: remaining clean epoch count sit in permanent chrome"*).  A carrier
#: that does not answer them all cannot sit in permanent chrome, and
#: the page refuses it (see :class:`DashboardPage`): the spec's M5
#: line — *"sees instrument status as three binary lamps"* — and the
#: journeys addition's own clause — *"a lamp with no reading as no
#: reading rather than lit"* — are one law, and a page that could be
#: built without a carrier answering the rail would be a page on which
#: the one question §5.4 says everything below it depends on (*"is any
#: lamp out?"*) could go unasked.
_LAMPS_CONTRACT = (
    "lamps",
    "states",
    "lines",
)

#: The provenance carrier's display contract — the reads the render (and
#: the tests) make of whatever the primary panel holds in its
#: ``provenance`` seat.  ``triple`` is the full-width spelling J06's
#: *"full on hover/expand"* names (the value the caller expands);
#: ``unrecorded`` and ``mixed`` are the two states the panel must be
#: able to name; ``line`` is the one the render draws.  A carrier that
#: does not answer them all cannot sit beside the figure, and the page
#: refuses it (see :class:`DashboardPage`): app_spec.xml's ``ui_layout``
#: draws the primary panel whole — *"The primary panel is FDR_deploy
#: with its provenance triple"* — and a page that could be built with a
#: provenance seat that cannot state its own reading would be a page on
#: which the figure could render unattributed, the exact gap J06's
#: validation found on the first render.
_PROVENANCE_CONTRACT = (
    "triple",
    "unrecorded",
    "mixed",
    "line",
)

#: The Streamlit calls the render makes — the whole contract a render
#: carrier must answer, spelled once so the duck-check, the render and
#: the tests cannot drift apart on what "a streamlit" is here.
_RENDER_CARRIER_CONTRACT = (
    "set_page_config",
    "title",
    "header",
    "metric",
    "caption",
    "line_chart",
)

#: The hash spelling every provenance term must already carry — 64 hex
#: characters, the digest of the artifact the term names (§9.1's
#: ``CHAR(64)`` columns; a sha256 digest rendered as hex is exactly 64
#: characters, which is why the length is the schema's own spelling of
#: "a hash" and not a tuning knob).
_PROVENANCE_HASH_LENGTH = 64

#: The alphabet of those 64 characters, lowercased — the fold the
#: ledger's canonicalization performs, so a row stamped in uppercase
#: and one stamped in lowercase name the same artifact.
_PROVENANCE_HEX = frozenset("0123456789abcdef")

#: How much of each hash the short form renders — J06's *"short form,
#: full on hover/expand"*.  Twelve characters is the prefix a terminal
#: and a tooltip both keep on one line; the value
#: (:attr:`CampaignProvenance.triple`) carries the whole digest for
#: the expand.
_SHORT_HASH_CHARS = 12

#: The labels the short form renders the three terms under — the
#: column names' own words, spaced the way a caption reads.
_PROVENANCE_LABELS = ("evaluator", "snapshot", "cost model")


def require_streamlit() -> Any:
    """Import and return the :mod:`streamlit` module, or raise loudly.

    The mirror of :func:`~ops.fdr_route.require_scoring`, for the one
    ambient dependency this member's surface renders through.  Deferred
    past module scope and past builder time for the same scan-order
    reason: the factory's workspace scan imports this package to fire
    its ``@register``, and nothing promises the scanning environment
    carries a UI library the research loop never links against — §16's
    stack line names Streamlit the way it names Postgres, an
    environment the operator runs.  A deployment that genuinely renders
    the dashboard is told which wheel is missing rather than shown a
    bare :class:`ImportError`.
    """
    try:
        import streamlit
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "the ops member's dashboard renders through Streamlit (docs "
            "§16's stack line: a single metrics table with a Streamlit "
            "dashboard), and Streamlit is not importable in this "
            "environment; install it where the dashboard runs (uv pip "
            "install streamlit in the deployment environment) — the "
            "workspace lockfile deliberately carries no third-party edge "
            "for it, so the render seam stays duck-typed and this member "
            "imports without it (feature 351, docs §16)"
        ) from exc
    return streamlit


def _canonical_provenance_hash(value: Any, column: str) -> str | None:
    """One provenance term as its canonical spelling, or ``None``.

    The read-side half of the law the ledger's
    :func:`ledger.provenance` canonicalization and this member's own
    :func:`ops.evaluation_log._canonical_hash` both state: ``None``
    passes untouched (it is the pre-stamp spelling, not a malformed
    one), a ``str`` is stripped and lowercased — uppercase and
    lowercase hex name the same artifact — and anything that is not 64
    hex characters after the fold is *refused by name*, because a hash
    is the one value whose whole meaning is naming an artifact, and a
    term that names nothing rendered beside the figure would be
    provenance no audit can replay.  The ``sha256:`` prefix gets its
    own refusal because it is the honest mistake — an image-reference
    spelling pasted where a bare digest belongs — and the message that
    names it is the one that repairs it.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise DashboardRenderError(
            f"the provenance term {column} on a node row is not a string "
            f"(got {type(value).__name__}): the column is §9.1's "
            f"CHAR(64) digest of the artifact it names, and a value that "
            f"is not text cannot name one; repair the row's writer "
            f"(feature 99's stamp) — never render the term (J06, docs §9.1)"
        )
    stripped = value.strip()
    if stripped.startswith("sha256:"):
        raise DashboardRenderError(
            f"the provenance term {column} on a node row carries the "
            f"sha256: image-reference prefix ({len(stripped)} "
            f"characters): the column wants the bare hexdigest — 64 hex "
            f"characters, uppercase folded, the spelling feature 87 "
            f"stamps on the ledger and feature 99 on the node — and an "
            f"image reference names a registry artifact, not the "
            f"evaluator, snapshot or cost model the triple must name; "
            f"the repair is the row's writer — strip the prefix at it "
            f"and stamp the digest (J06, docs §9.1)"
        )
    folded = stripped.lower()
    if len(folded) != _PROVENANCE_HASH_LENGTH or any(
        character not in _PROVENANCE_HEX for character in folded
    ):
        raise DashboardRenderError(
            f"the provenance term {column} on a node row is not a hash's "
            f"own spelling ({len(folded)} characters, hex only): the "
            f"column is §9.1's CHAR(64), and only a 64-character "
            f"hexdigest names the artifact the term is provenance for — "
            f"a shorter or non-hex value rendered beside the figure "
            f"would be provenance no audit can replay; repair the row's "
            f"writer (feature 99's stamp) rather than displaying it "
            f"(J06, docs §9.1)"
        )
    return folded


@dataclass(frozen=True, slots=True)
class CampaignProvenance:
    """One campaign's provenance reading — the node rows, judged.

    Frozen testimony over the rows the reader fetched for one campaign,
    each row the triple of §9.1's three ``CHAR(64)`` columns as the row
    holds it (``None`` the spelling of a term nobody stamped).  The
    judgement is the feature's own sentence, held where every caller
    shares it:

    * a row **carries** a triple only when all three terms are
      non-``None`` — a row that predates feature 99's stamp states no
      triple and so cannot disagree, the same read-side law the
      ledger's provenance gives a row that predates feature 87's;
    * :attr:`stamped` is the distinct complete triples the rows carry,
      first-seen order — never assembled across rows (a triple is one
      stamp on one row, and a Franken-triple of three rows' terms would
      name an evaluator, snapshot and cost model that never co-occurred);
    * **unrecorded** (:attr:`unrecorded`) is zero stamped triples, and
      renders J06's own words (:data:`PROVENANCE_UNRECORDED`) — never a
      hash nobody recorded;
    * **mixed** (:attr:`mixed`) is more than one, and renders the error
      message (:attr:`line`) that refuses the display and the average
      both — J06: *"one whose nodes disagree is refused as mixed
      provenance, never averaged"*;
    * exactly one stamped triple is the recorded state, and
      :attr:`triple` answers it whole (the full-width spelling J06's
      *"full on hover/expand"* names — the value the caller expands),
      with :attr:`line` carrying the short form beside the numeral.

    There is deliberately no constructor door that *decides* which
    triple a mixed campaign "really" ran under: the value holds the
    rows and answers the judgement, and a caller that wanted the
    average would have to build it in the open, where review finds it.
    """

    #: The campaign's node rows as the reader fetched them, each row
    #: ``(evaluator_hash, snapshot_hash, cost_model_hash)`` in §9.1's
    #: order, each term canonicalized or ``None``.  Empty when the
    #: campaign closed no node into the table or the schema has not
    #: been brought — both unrecorded, by the law above.
    rows: tuple[tuple[str | None, str | None, str | None], ...] = ()

    def __post_init__(self) -> None:
        canonical: list[tuple[str | None, str | None, str | None]] = []
        for row in self.rows:
            try:
                terms = tuple(row)
            except TypeError as exc:
                raise DashboardRenderError(
                    f"a CampaignProvenance's rows are the node table's "
                    f"(evaluator_hash, snapshot_hash, cost_model_hash) "
                    f"triples, and one of them is not a triple at all "
                    f"(got {type(row).__name__}): the reader fetches "
                    f"three columns per row, so a row that is not one is "
                    f"a read nobody made — repair the reader's SELECT, "
                    f"never render the term (J06, docs §9.1)"
                ) from exc
            if len(terms) != len(PROVENANCE_COLUMNS):
                raise DashboardRenderError(
                    f"a CampaignProvenance's rows are the node table's "
                    f"(evaluator_hash, snapshot_hash, cost_model_hash) "
                    f"triples, and one of them carries {len(terms)} "
                    f"terms: the triple is §9.1's three columns and a "
                    f"row with any other width is a read nobody made — "
                    f"repair the reader's SELECT, never render the term "
                    f"(J06, docs §9.1)"
                )
            canonical.append(
                tuple(
                    _canonical_provenance_hash(term, column)
                    for term, column in zip(terms, PROVENANCE_COLUMNS)
                )
            )
        object.__setattr__(self, "rows", tuple(canonical))

    @property
    def stamped(self) -> tuple[tuple[str, str, str], ...]:
        """The distinct complete triples the rows carry, first-seen
        order — the join the judgement runs over, and never a triple
        assembled across rows."""
        distinct: list[tuple[str, str, str]] = []
        for row in self.rows:
            if any(term is None for term in row):
                continue  # a row that predates the stamp states nothing
            if row not in distinct:
                distinct.append(row)
        return tuple(distinct)

    @property
    def unrecorded(self) -> bool:
        """Whether no node row carries a complete triple — the state
        :data:`PROVENANCE_UNRECORDED` names, reserved for it."""
        return not self.stamped

    @property
    def mixed(self) -> bool:
        """Whether the rows carry more than one distinct triple — the
        disagreement :attr:`line` refuses."""
        return len(self.stamped) > 1

    @property
    def triple(self) -> tuple[str, str, str] | None:
        """The campaign's one recorded triple, whole — the full-width
        spelling J06's *"full on hover/expand"* names.  ``None`` for
        the unrecorded and mixed states alike: neither has one triple
        to answer, and picking one anyway is the misattribution the
        mixed refusal exists to prevent."""
        return self.stamped[0] if len(self.stamped) == 1 else None

    @property
    def line(self) -> str:
        """The words the render draws beside the numeral — one line per
        state, and only three states: the recorded short form (each
        term's first :data:`_SHORT_HASH_CHARS` characters under its own
        label), the unrecorded words exactly
        (:data:`PROVENANCE_UNRECORDED`), or the mixed refusal, which
        displays no triple and averages none."""
        if self.unrecorded:
            return PROVENANCE_UNRECORDED
        if self.mixed:
            carrying = sum(
                1 for row in self.rows if all(term is not None for term in row)
            )
            return (
                f"mixed provenance: {carrying} node rows carry "
                f"{len(self.stamped)} distinct triples of "
                f"{', '.join(PROVENANCE_COLUMNS)} for this campaign — "
                f"none is displayed and none is averaged; the node rows "
                f"must agree before the figure can be attributed "
                f"(J06, docs §9.1)"
            )
        evaluator, snapshot, cost_model = self.stamped[0]
        return (
            "provenance: "
            + ", ".join(
                f"{label} {term[:_SHORT_HASH_CHARS]}…"
                for label, term in zip(
                    _PROVENANCE_LABELS, (evaluator, snapshot, cost_model)
                )
            )
        )


def _sqlite_path(database_url: str) -> Path:
    """The SQLite file a ``sqlite:///`` URL names — the workspace's one
    translation, spelled privately here because the reader must not
    import the scoring member for three lines of grammar.

    The same three refusals every store in this workspace documents
    (the scoring member's :func:`~scoring._fdr._sqlite_path` is the
    nearest spelling): only ``sqlite:///`` speaks, no host but
    ``localhost`` admitted, and a URL with no path refused — each a
    :class:`ValueError` the reader translates at its seam, so a
    misrouted Postgres URL cannot hide behind a mysterious file.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise ValueError(
            f"unsupported database URL scheme {parsed.scheme!r}: the "
            f"provenance reader speaks sqlite:/// (docs §16's "
            f"single-machine allowance), the same refusal every store "
            f"in this workspace documents"
        )
    if parsed.netloc not in ("", "localhost"):
        raise ValueError(
            f"the provenance reader's sqlite URL must not carry a host, "
            f"got {parsed.netloc!r}"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path:
        raise ValueError("the provenance reader's sqlite URL carries no path")
    return Path(path)


def _names_absent_schema(error: sqlite3.Error) -> bool:
    """Whether a refusal names the schema-absent states the migrations'
    own chain ordering makes discoverable — no ``node`` table (the
    table's migration has not run) or no trio columns (it has, feature
    99's has not).  These two fold into unrecorded because there the
    rows honestly carry nothing; every other refusal is a broken read
    and refuses the render (see :meth:`NodeProvenanceReader.reading`)."""
    message = str(error).lower()
    return "no such table" in message or "no such column" in message


class NodeProvenanceReader:
    """The reader behind the primary panel's triple: one campaign's
    node rows, over the one database the route carries.

    The panel's other reads arrive through feature 341's response; this
    one does not, because the response is the scoring member's
    per-campaign figures and the triple lives one table over — §9.1's
    ``node`` rows, feature 99's columns.  So the dashboard holds a
    reader beside the route, and :meth:`reading` is a plain stdlib
    ``SELECT`` of the three columns for one ``campaign_id``: no DDL
    ever (the node table is the migrations'), no join, no aggregation —
    the judgement over the rows is :class:`CampaignProvenance`'s, and
    the reader's whole job is to fetch the rows honestly and hand them
    over without editorializing.

    Construction validates the URL the way the chrome's gauge does
    (:class:`~ops.chrome.EpochCountGauge`'s wiring refusal): non-empty
    string or the render vocabulary's own refusal, because a reader
    pointed at nothing is a triple nobody can read.  The URL itself is
    *held*, not opened — construction performs no I/O, so composing the
    dashboard touches no disk, and the first :meth:`reading` is where
    the database opens.  The URL is the one the route resolved, never
    re-resolved from the environment: the figure and the triple it is
    attributed by ride one database, or the page could attribute one
    campaign's number to another campaign's evaluator.

    A read that fails refuses (:class:`~ops.errors.DashboardRenderError`
    — the render vocabulary, chained so the operator still sees
    sqlite's own words, and carrying no filesystem path), with exactly
    one fold: the schema-absent spellings (:func:`_names_absent_schema`)
    answer the unrecorded reading, because a deployment whose migrations
    have not brought the node table yet is the deployment's first page,
    and "provenance unrecorded" is the honest words for it.
    """

    def __init__(self, database_url: Any) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise DashboardRenderError(
                "the dashboard's provenance reader needs a non-empty "
                "database URL: the primary panel attributes the figure "
                "through the node table's triple (§9.1's evaluator_hash, "
                "snapshot_hash and cost_model_hash), and a reader "
                "pointed at nothing cannot read one. The reader rides "
                "the URL the route already carries (its store's "
                "database_url — the one-database law), so this refusal "
                "names a route that carries no store, and the repair is "
                "the route's: point DATABASE_URL at the metrics store "
                "(J06, docs §9.1)"
            )
        self._database_url = database_url

    @property
    def database_url(self) -> str:
        """The database this reader reads — the URL the route carried,
        never re-resolved from the environment."""
        return self._database_url

    def reading(self, campaign_id: Any) -> CampaignProvenance:
        """One campaign's node rows as a provenance reading.

        ``campaign_id`` must be the non-empty id the response named —
        the reader joins on ``node.campaign_id``, and an id that names
        nothing selects no rows, which would render *unrecorded* for a
        campaign that may have rows: the quiet wrong answer, refused
        loudly instead.  The rows come back as the table holds them
        (``None`` terms included), and the judgement over them is
        :class:`CampaignProvenance`'s.
        """
        if not isinstance(campaign_id, str) or not campaign_id.strip():
            raise DashboardRenderError(
                "the dashboard's provenance reader reads a campaign's "
                "node rows by id (the response's campaign_id — the "
                "newest campaign, whose figure the panel renders), and "
                f"it was handed {campaign_id!r}: an id that names "
                "nothing would select no rows and render 'provenance "
                "unrecorded' for a campaign that may carry the triple — "
                "the quiet wrong answer this member refuses everywhere; "
                "repair the caller's campaign id, never the reading "
                "(J06, docs §9.1)"
            )
        try:
            path = _sqlite_path(self._database_url)
            with closing(sqlite3.connect(path)) as connection:
                rows = connection.execute(
                    f"SELECT {', '.join(PROVENANCE_COLUMNS)} FROM node "
                    f"WHERE campaign_id = ?",
                    (campaign_id,),
                ).fetchall()
        except sqlite3.OperationalError as exc:
            if _names_absent_schema(exc):
                # The schema-absent fold: no node table (0118 has not
                # run) or no trio columns (0116 has not) is a
                # deployment state the chain's own ordering makes
                # discoverable, and the rows honestly carry nothing —
                # unrecorded, not broken.
                return CampaignProvenance(rows=())
            raise DashboardRenderError(
                f"the dashboard's provenance reader could not read the "
                f"node table for the campaign's triple: sqlite refused "
                f"the read ({type(exc).__name__}: {exc}). The primary "
                "panel attributes the figure through that triple, and "
                "a read that cannot be made is surfaced rather than "
                "answered around — 'provenance unrecorded' is reserved "
                "for the state where no node carries the triple, and a "
                "broken read wearing it would hide the break behind an "
                "honest-sounding absence; the repair is the database's "
                "(the original refusal is chained), never a fallback "
                "triple (J06, docs §9.1)"
            ) from exc
        except (sqlite3.Error, OSError, ValueError) as exc:
            # OSError detail through `strerror` only — the constraint
            # is the member's own: no dashboard refusal carries a
            # filesystem path, and an OSError's default text names the
            # file it failed on.  sqlite's own text never does, so it
            # carries; the ValueError from the URL grammar is static.
            if isinstance(exc, OSError):
                detail = getattr(exc, "strerror", None) or type(exc).__name__
            else:
                detail = str(exc)
            raise DashboardRenderError(
                f"the dashboard's provenance reader could not read the "
                f"node table for the campaign's triple: the read refused "
                f"({type(exc).__name__}: {detail}). The primary panel "
                "attributes the figure through that triple, and a read "
                "that cannot be made is surfaced rather than answered "
                "around — 'provenance unrecorded' is reserved for the "
                "state where no node carries the triple, and a broken "
                "read wearing it would hide the break behind an "
                "honest-sounding absence; the repair is the database's "
                "(the original refusal is chained), never a fallback "
                "triple (J06, docs §9.1)"
            ) from exc
        return CampaignProvenance(rows=tuple(tuple(row) for row in rows))


@dataclass(frozen=True, slots=True)
class FdrDeployPanel:
    """The dashboard's primary panel: §16's top-line figure, with its
    provenance visible beside it.

    Thin by design — the member's law is delegation, and every
    guarantee this panel's reads enjoy was earned by the value it
    holds: feature 341's :class:`~ops.fdr_route.FdrDeployResponse`,
    whose construction already rebuilt and narrowed the whole trend
    (each triple validated, the order held, the newest row the top
    line).  The panel adds exactly the display-shaped reads a render
    needs and re-spells nothing: no second validation of the figures,
    no second derivation of the top line, no base-rate literal (the
    qualifier is read through the scoring member's one spelling,
    :data:`scoring.DEPLOYMENT_BASE_RATE`, at display time).

    The provenance the spec's ``ui_layout`` demands visible — *"The
    primary panel is FDR_deploy with its provenance triple"* — arrives
    on two seats.  The response's own attribution is the plate:
    :attr:`figure` (the numeral), :attr:`campaign_id` and
    :attr:`computed_at` (the campaign that measured it and the instant
    it was computed), with :attr:`qualifier` beside them as §16's line
    carries it (*"``FDR_deploy`` at π₀ = 0.9"*).  And the *triple* —
    the ``evaluator_hash``, ``snapshot_hash`` and ``cost_model_hash``
    J06's acceptance names — is :attr:`provenance`: the reading the
    dashboard took from that campaign's node rows (see
    :class:`NodeProvenanceReader`), held beside the response so the
    figure and the words that attribute it cannot drift apart between
    the read and the render.  A top-line number an operator cannot
    attribute to the campaign that measured it — or to the evaluator,
    snapshot and cost model that produced it — is a number nobody can
    audit; the reasoning the route's own docstring gives for
    identifying the figure it answers, carried one seat further.

    There is deliberately no field an equity curve could occupy.  The
    panel's whole surface is the FDR_deploy trend and its provenance; a
    returns series, a NAV curve or a Sharpe has nowhere to land on this
    type, which is the structural half of the feature's *"rather than
    an equity curve"* clause — the refusal half lives at
    :class:`DashboardPage`, the ordering half in
    :meth:`OperatorDashboard.render`.

    An empty trend is the honest absence: falsy, every derived read
    ``None`` or empty — never ``0.0``, which would be a measurement no
    campaign made — and :attr:`provenance` the empty reading (no
    campaign closed, so no node rows were asked).
    """

    #: Feature 341's testimony — the validated per-campaign history the
    #: panel's every read derives from.
    response: FdrDeployResponse

    #: The campaign's provenance reading — the node rows' triple,
    #: judged: recorded (one unanimous triple), *provenance
    #: unrecorded* (no node carries one) or *mixed provenance* (the
    #: rows disagree, displayed as the refusal and never averaged).
    #: Required, with no default: every panel states its reading, the
    #: same "no chromeless construction" move the page's other seats
    #: take.
    provenance: CampaignProvenance

    @property
    def figure(self) -> Optional[float]:
        """§16's number: the newest campaign's ``FDR_deploy``, the
        deployment projection at π₀.  ``None`` when no campaign has
        closed — an absence, never a zero."""
        return self.response.fdr_deploy

    @property
    def campaign_id(self) -> Optional[str]:
        """The campaign the figure belongs to — its plate."""
        return self.response.campaign_id

    @property
    def computed_at(self) -> Optional[str]:
        """When the figure's campaign was computed (ISO 8601 UTC)."""
        return self.response.computed_at

    @property
    def trend(self) -> tuple[tuple[str, float, str], ...]:
        """The per-campaign figures, oldest first — the same history
        the numeral was drawn from, read as one answer."""
        return self.response.history

    @property
    def qualifier(self) -> float:
        """The deployment base rate the figure is pinned to — π₀, read
        from :data:`scoring.DEPLOYMENT_BASE_RATE` through the member's
        one deferred door, never re-spelled as a literal here."""
        return require_scoring().DEPLOYMENT_BASE_RATE

    @property
    def headline(self) -> str:
        """The panel's heading — §16's own line for the metric:
        ``"FDR_deploy at π₀ = 0.9"``, the qualifier carried beside the
        figure the way the scoring member's rows carry it beside the
        number."""
        return f"{FDR_DEPLOY_LABEL} at π₀ = {self.qualifier:g}"

    @property
    def numeral(self) -> Optional[str]:
        """The figure as the render displays it — a percentage, the
        form prd §11's target is stated in (*"< 25% at π₀ = 0.9"*).
        ``None`` when no campaign has closed: the render shows a dash,
        never a zero that would answer "a flawless system" for a
        deployment that never ran."""
        figure = self.figure
        return None if figure is None else f"{figure:.1%}"

    @property
    def plate(self) -> Optional[str]:
        """The provenance rendered beneath the numeral — the campaign
        that measured it and the instant it was computed.  ``None``
        when there is no figure to attribute."""
        if self.campaign_id is None:
            return None
        return f"campaign {self.campaign_id}, computed {self.computed_at}"

    @property
    def series(self) -> tuple[float, ...]:
        """The trend's figures, oldest first — the only series this
        panel can offer a chart, and the only one the dashboard ever
        draws."""
        return tuple(figure for _campaign, figure, _instant in self.trend)

    @property
    def points(self) -> tuple[tuple[str, float], ...]:
        """The trend's points, oldest first — each campaign's figure
        paired with the instant that campaign was computed, the label
        the chart draws the point under.

        J02's own words for the gap this read closes: the trend's
        x-axis rendered *"a bare ``0, 1, 2`` index with no campaign or
        date"*, and the feature's clause picks the date — each point
        labelled by its campaign's ``computed_at`` instant.  The label
        is the instant, not the campaign id beside it in the row,
        because the instant is the fact the trend's own order reads
        (the store answers oldest-first *by* ``computed_at``), so two
        points on the trend are two datable measurements and the
        operator can ask *when* each figure was computed.  A
        display-shaped read derived from the response's history alone
        — one answer, not a second ordering — and empty exactly when
        the trend is, so the honest-absence page still draws no chart
        of an empty series."""
        return tuple(
            (instant, figure) for _campaign, figure, instant in self.trend
        )

    def __bool__(self) -> bool:
        """Whether the deployment has closed a campaign at all — the
        same split the response pins: an absence (``False``, render no
        numeral) is not a measured ``0.0`` (``True``, render it)."""
        return bool(self.response)


@dataclass(frozen=True, slots=True)
class DashboardPage:
    """The dashboard's whole page: one primary panel, first, and its
    permanent chrome.

    The page model exists to hold the feature's ordering law where a
    test can reach it: the primary seat is the page's first and
    defining content, and the panel that fills it is the FDR one.
    Construction is the spec's review — *"any panel that would promote
    profit above epistemic state is rejected at review"* — made
    executable: a primary carrier that does not answer the FDR panel's
    display contract (:data:`_PRIMARY_PANEL_CONTRACT`) is refused by
    name, with §16's abandonment sentence in the refusal, because the
    failure that law describes is a quiet one — an equity curve that
    drifts into the primary seat renders nothing here, and the page
    says so instead.

    The second seat is feature 352's, and it is the other half of the
    same modelling decision: the chrome is a *required* field, so a
    page without it is not constructible — the spec's *"permanent
    chrome"* and *"at all times"* made structural, the same move the
    primary seat's contract makes for §16's law.  Its carrier answers
    the chrome's display contract (:data:`_CHROME_CONTRACT`) or the
    page is refused by name: a chrome that could not answer the count
    would be a strip rendering on every page with nothing to say, and
    the depletion it exists to show would go unseen exactly when it
    mattered.

    The third seat is the instrument lamps', and it is the same move a
    second time: docs §5.4's rail (*"three binary lamps at the top of
    the left rail, because everything below them is worthless if any
    is out"*) sits in the same permanent chrome the count does — the
    spec's ``ui_layout`` names the two strips in one clause — so the
    lamps are a *required* field too, and a carrier that does not
    answer the lamps' display contract (:data:`_LAMPS_CONTRACT`) is
    refused by name: a rail that could quietly go missing from a page
    is a page on which every numeral below it could be read without
    the one bit that says whether it may be believed.

    And the primary seat's *own* third check is the provenance one:
    a panel that answers the FDR panel's reads must also answer a
    ``provenance`` carrier that answers the provenance contract
    (:data:`_PROVENANCE_CONTRACT`) — the spec's ``ui_layout`` draws
    the primary panel whole (*"The primary panel is FDR_deploy with
    its provenance triple"*), and a page that could be built with a
    provenance seat that cannot state its reading would be a page on
    which the figure could render unattributed — the exact gap J06's
    validation found on the first render, refused at construction
    rather than re-opened.

    All three checks are duck-typed, not ``isinstance``-guarded, for the
    reason every seam in this workspace gives: the factory's scan
    imports members under synthetic names, so a composed panel is
    structurally this member's without being the same class object a
    direct import yields.  The contract is the carrier's public reads —
    and a carrier that answers all of them *is* an FDR_deploy panel
    (or an epoch-count chrome, or an instrument-lamps chrome) for
    every purpose the render has.

    Later features of this category hang their own content off the
    page — 352's chrome landed here beside the primary seat without
    moving the top line, and the lamps landed beside the chrome the
    same way, which was the point of modelling the seats explicitly:
    chrome grows, the top line does not.
    """

    primary: FdrDeployPanel
    chrome: EpochCountChrome
    lamps: InstrumentLampsChrome

    def __post_init__(self) -> None:
        missing = [
            name
            for name in _PRIMARY_PANEL_CONTRACT
            if not hasattr(self.primary, name)
        ]
        if missing:
            raise DashboardRenderError(
                f"a DashboardPage's primary panel is the FDR_deploy one "
                f"(an {FdrDeployPanel.__name__} or any carrier answering "
                f"its display contract: "
                f"{', '.join(_PRIMARY_PANEL_CONTRACT)}), and this carrier "
                f"does not answer: {', '.join(missing)}. Docs §16: 'If "
                f"the primary chart is an equity curve, the system's "
                f"actual purpose has been quietly abandoned' — the page "
                f"is the review that spec names, and the primary seat is "
                f"refused rather than rendered with a panel that promotes "
                f"anything above epistemic state (feature 351, docs §16)"
            )
        chrome_missing = [
            name for name in _CHROME_CONTRACT if not hasattr(self.chrome, name)
        ]
        if chrome_missing:
            raise DashboardRenderError(
                f"a DashboardPage's chrome is the permanent one (an "
                f"{EpochCountChrome.__name__} or any carrier answering "
                f"its display contract: "
                f"{', '.join(_CHROME_CONTRACT)}), and this carrier does "
                f"not answer: {', '.join(chrome_missing)}. The spec's "
                "operator reads the remaining clean epoch count at all "
                "times because it sits in permanent chrome, and a page "
                "that could be built without a carrier answering the "
                "count would be a page on which depletion could go "
                "unseen — §13 item 4's 'When clean epochs run out, the "
                "system stops' is a state the operator must see coming, "
                "not one to discover at the stop (feature 352, prd "
                "§13 item 4)"
            )
        lamps_missing = [
            name for name in _LAMPS_CONTRACT if not hasattr(self.lamps, name)
        ]
        if lamps_missing:
            raise DashboardRenderError(
                f"a DashboardPage's lamps are the permanent chrome's "
                f"instrument rail (an {InstrumentLampsChrome.__name__} "
                f"over feature 342's GET {INSTRUMENT_STATUS_ROUTE} "
                f"response, or any carrier answering its display "
                f"contract: {', '.join(_LAMPS_CONTRACT)}), and this "
                f"carrier does not answer: {', '.join(lamps_missing)}. "
                f"Docs §5.4 draws three binary lamps at the top of the "
                f"rail 'because everything below them is worthless if "
                f"any is out', the spec's operator 'sees instrument "
                f"status as three binary lamps' on every render, and a "
                "page that could be built without a carrier answering "
                "the rail would be a page on which the numerals could "
                "be read without the one bit that says whether they may "
                "be believed — the quiet abandonment §5.4's rail exists "
                "to make impossible (docs §5.4)"
            )
        provenance_missing = [
            name
            for name in _PROVENANCE_CONTRACT
            if not hasattr(getattr(self.primary, "provenance", None), name)
        ]
        if provenance_missing:
            raise DashboardRenderError(
                f"a DashboardPage's primary panel carries its provenance "
                f"triple (a {CampaignProvenance.__name__} over the "
                f"campaign's node rows, or any carrier answering its "
                f"display contract: "
                f"{', '.join(_PROVENANCE_CONTRACT)}), and this panel's "
                f"provenance does not answer: "
                f"{', '.join(provenance_missing)}. app_spec.xml's "
                "ui_layout draws the primary panel whole — 'The primary "
                "panel is FDR_deploy with its provenance triple' — and "
                "the journeys' own acceptance names the three states "
                "that seat must be able to state (the recorded triple, "
                "provenance unrecorded, mixed provenance refused rather "
                "than averaged); a page built with a provenance seat "
                "that cannot state its reading is the page J06's "
                "validation found rendering the figure with no triple "
                "beside it — an unattributable top line, refused at "
                "construction rather than re-opened (J06, docs §9.1)"
            )


class OperatorDashboard:
    """The operator surface: the primary panel with its permanent
    chrome, rendered over the composed route.

    Constructed over the route (:class:`~ops.fdr_route.FdrDeployEndpoint`
    or any carrier answering its ``get()``), the chrome's gauge
    (:class:`~ops.chrome.EpochCountGauge` or any carrier answering its
    ``remaining()``), the lamps' rail
    (:class:`~ops.instrument_status.InstrumentStatusEndpoint` or any
    carrier answering its ``get()``) *and* the primary panel's
    provenance reader (:class:`NodeProvenanceReader` or any carrier
    answering its ``reading()``) — four carriers, because the page
    reads its content from four owners: §16's top-line number from the
    scoring member's rows, §13 item 4's remaining clean epoch count from
    the promotion member's ledger, docs §5.4's three lamps from
    feature 342's own route (each bit the owning member's own verdict),
    and the triple that attributes the figure from §9.1's node rows.
    The gauge and the rail are required arguments, not options: a
    dashboard without either would be a dashboard whose chrome could
    quietly go missing, and "permanent" is a fact the constructor
    states rather than a behaviour it hopes for.  The reader is
    optional in *signature* only (``provenance=None`` wires it lazily
    over the route's own carried URL — the one-database law, so a
    three-argument construction from before the triple landed keeps
    composing over exactly the database it always did); a carrier
    handed in that cannot answer ``reading()`` is refused by name,
    the same duck-check every other seat takes.

    Every render is a fresh read of all four — the dashboard holds no
    cache of a previous page, for the reason the endpoint holds none:
    a campaign closed between two renders must move the second numeral,
    an epoch spent between two renders must move the second chrome
    strip, a lamp that goes out between two renders must darken the
    second rail, and a triple stamped between two renders must appear
    beside the second figure, because a cached figure of any of the
    four kinds would make the page a fact about when it was first
    opened rather than about what the system measured, what it has
    left, whether any of it may be believed, and who produced it.

    Two construction doors, one law each:

    * :meth:`from_env` — the builder's door, over the store
      ``DATABASE_URL`` names; ``None`` when it names none (an
      unconfigured store is a discoverable deployment state, and the
      composed application simply carries no dashboard, exactly as it
      carries no route — and no chrome without a dashboard, because
      both strips ride the same URL the route resolved; nor a reader,
      for the same reason);
    * :meth:`composed` — the operator's door, through the seat in the
      app package namespace; a composed application that carries no
      route is *refused*, because a render asked for by name is a
      caller that needs the figure and must not be shown a numeral
      nobody measured — and one that carries no instrument-status
      route is refused the same way, because the page it would render
      is a page whose lamps went missing rather than dark.
    """

    def __init__(
        self,
        route: Any,
        gauge: Any,
        rail: Any,
        provenance: Any = None,
    ) -> None:
        if not callable(getattr(route, "get", None)):
            raise TypeError(
                "OperatorDashboard renders over the composed fdr-deploy "
                "route (something with a get() answering feature 341's "
                f"GET {FDR_DEPLOY_ROUTE} response); got "
                f"{type(route).__name__}. The primary panel is §16's "
                "top-line figure read through the route that owns it, "
                "and a carrier that cannot answer the route's response "
                "cannot name the figure a dashboard would render "
                "(feature 351, docs §16)"
            )
        if not callable(getattr(gauge, "remaining", None)):
            raise TypeError(
                "OperatorDashboard renders the remaining clean epoch "
                "count in permanent chrome beside the primary panel "
                "(feature 352), and that count is read through a gauge "
                "— something with a remaining() answering feature 297's "
                f"figure; got {type(gauge).__name__}. The chrome renders "
                "on every page the dashboard draws, so a carrier that "
                "cannot answer the count cannot be a dashboard's gauge: "
                "there is no chromeless construction to fall back to "
                "(feature 352, prd §13 item 4)"
            )
        if not callable(getattr(rail, "get", None)):
            raise TypeError(
                "OperatorDashboard renders the instrument lamps in "
                "permanent chrome on every page (docs §5.4's rail: "
                "canary, KS guard, ingest), and the rail is read "
                "through feature 342's own route — something with a "
                f"get() answering the GET {INSTRUMENT_STATUS_ROUTE} "
                f"response; got {type(rail).__name__}. Each lamp is the "
                "owning member's own verdict, and a carrier that cannot "
                "answer the route's response cannot name a single bit "
                "of it: there is no lampless construction to fall back "
                "to, because the page it would render is the page §5.4 "
                "draws the rail to prevent — everything below it read "
                "as if the instruments were healthy (docs §5.4)"
            )
        if provenance is not None and not callable(
            getattr(provenance, "reading", None)
        ):
            raise TypeError(
                "OperatorDashboard renders the newest campaign's "
                "provenance triple beside the figure on the primary "
                "panel (evaluator_hash, snapshot_hash and "
                "cost_model_hash, §9.1's node-table columns), and the "
                "triple is read through a reader — something with a "
                "reading() answering one campaign's node rows; got "
                f"{type(provenance).__name__}. app_spec.xml's ui_layout "
                "draws the primary panel whole ('The primary panel is "
                "FDR_deploy with its provenance triple'), and a carrier "
                "that cannot answer the reading cannot name the triple "
                "the figure is attributed by: leave the argument unset "
                "and the dashboard wires its own reader over the URL "
                "the route carries, or hand it a reader — there is no "
                "tripleless construction to fall back to, because the "
                "page it would render is the unattributed top line "
                "J06's validation found (J06, docs §9.1)"
            )
        self._route = route
        self._gauge = gauge
        self._rail = rail
        self._provenance = provenance

    @property
    def route(self) -> Any:
        """The route this dashboard reads — feature 341's, held
        duck-typed across the seam."""
        return self._route

    @property
    def gauge(self) -> Any:
        """The gauge this dashboard's chrome reads — feature 297's
        figure, held duck-typed across the seam the way the route is."""
        return self._gauge

    @property
    def rail(self) -> Any:
        """The rail this dashboard's lamps read — feature 342's route,
        held duck-typed across the seam the way the route and the gauge
        are: each lamp the owning member's own verdict, read whole."""
        return self._rail

    @property
    def provenance(self) -> Any:
        """The reader this dashboard's triple reads — §9.1's node rows
        for the campaign the response names.  Wired lazily over the
        route's own carried URL when the constructor was handed none:
        the one-database law, held for the fourth surface (the figure,
        the count, the lamps and the triple all read one database), so
        a three-argument construction keeps composing over exactly the
        database it always did and a later environment cannot move the
        triple without moving the store it attributes."""
        if self._provenance is None:
            store = getattr(self._route, "store", None)
            url = getattr(store, "database_url", None)
            self._provenance = NodeProvenanceReader(url)
        return self._provenance

    # -- Construction -------------------------------------------------------

    @classmethod
    def from_env(
        cls, env: Optional[Mapping[str, str]] = None
    ) -> Optional["OperatorDashboard"]:
        """The dashboard over the route ``DATABASE_URL`` names, or
        ``None`` when it names none.

        The route's own :meth:`~ops.fdr_route.FdrDeployEndpoint.from_env`
        decides composition (absent, empty and whitespace-only all
        unset) and carries the deferred store — this door only wraps
        it, so the dashboard composes exactly when the route does and
        over the same database, with no second resolution to drift.
        The chrome's gauge is wired over the URL that route already
        resolved and carries (its store's ``database_url`` — the
        composition fact, read off the route rather than re-resolved
        from the environment), and the lamps' rail is the
        instrument-status route's own door over the same environment:
        it composes on the same unset semantics and reads its own
        band knob, so the top line, the count and the rail all point
        at the one database the deployment named, and a later
        environment cannot move the chrome without moving the store
        it counts.

        The rail door composing ``None`` while the route composed is
        refused rather than answered around: the two doors read the
        same variable, so the split can only mean the environment
        changed between the two reads, and a dashboard that rendered
        without its lamps would be the lampless page the constructor
        refuses — built anyway, at the one seam that could.  The
        provenance reader is wired over the same carried URL, beside
        the gauge: the figure, the count, the lamps and the triple
        all point at the one database the deployment named.
        """
        route = FdrDeployEndpoint.from_env(env)
        if route is None:
            return None
        rail = InstrumentStatusEndpoint.from_env(env)
        if rail is None:
            raise DashboardRenderError(
                f"the dashboard cannot be built without its instrument "
                f"rail: the fdr-deploy route composed over DATABASE_URL "
                f"but the instrument-status route did not "
                f"(GET {INSTRUMENT_STATUS_ROUTE} answers None over the "
                f"same variable — an unset spelling a moment after the "
                f"route read it set). The rail renders in permanent "
                "chrome on every page, and a page built without it "
                "would be the page docs §5.4 draws the rail to prevent: "
                "everything below it read as if the instruments were "
                "healthy; re-resolve the environment and compose again "
                "(docs §5.4)"
            )
        return cls(
            route,
            EpochCountGauge(route.store.database_url),
            rail,
            NodeProvenanceReader(route.store.database_url),
        )

    @classmethod
    def composed(cls, app: Any = None) -> "OperatorDashboard":
        """The dashboard over the application's composed route.

        Reached through the seats (:func:`app.modules.ops.
        fdr_deploy_component` and :func:`app.modules.ops.
        instrument_status_component`) — the accessors whose docstrings
        name this surface as their caller — so the operator surface
        never imports the member's stores directly and never grows a
        second reader of the per-campaign rows or of the rail's
        instruments.  With ``app`` given the components are read from
        it; without one the application is composed first — once — and
        both seats read from that one composition (the full declared
        workspace, in the environment the dashboard runs in).

        A composition that carries no ``ops-fdr-deploy`` component is
        refused: :class:`~ops.errors.DashboardRenderError`, naming the
        route and the environment variable that would compose it.  The
        alternative — rendering on without the figure — is the
        quietly-defaulted number this category exists to rule out.
        A composition that carries no ``ops-instrument-status``
        component is refused the same way, for the rail's own reason:
        the page it would render is a page whose lamps went missing
        rather than dark — a shorter rail than the design draws, which
        is the one screen where an instrument's state could go
        unasked.
        The chrome's gauge and the provenance reader are both wired
        over the composed route's own carried URL, the same ride
        :meth:`from_env` takes; a composed route that will not name
        its database (not the member's endpoint, a hand-registered
        stand-in) is refused by the gauge's — and the reader's — own
        wiring refusal rather than crashing the composition on an
        attribute it never promised.
        """
        application = app if app is not None else create_app()
        route = fdr_deploy_component(application)
        if route is None:
            raise DashboardRenderError(
                f"the dashboard cannot render: the composed application "
                f"carries no {FDR_DEPLOY_ROUTE} route (no ops-fdr-deploy "
                f"component — most often no DATABASE_URL configured, or "
                f"the ops member not scanned). The primary panel is docs "
                f"§16's top-line figure, and an operator surface that "
                f"needs it refuses to proceed rather than rendering a "
                f"numeral nobody measured; point DATABASE_URL at the "
                f"metrics store and compose again (feature 351, docs §16)"
            )
        rail = instrument_status_component(application)
        if rail is None:
            raise DashboardRenderError(
                f"the dashboard cannot render: the composed application "
                f"carries no {INSTRUMENT_STATUS_ROUTE} route (no "
                f"ops-instrument-status component — most often no "
                f"DATABASE_URL configured, or the ops member not "
                f"scanned), so the instrument lamps have no route to be "
                f"read through. Docs §5.4 draws canary, KS guard and "
                f"ingest at the top of the rail 'because everything "
                f"below them is worthless if any is out', and the one "
                f"thing worse than a dark rail is the rail quietly "
                f"absent while the numerals render on beneath where it "
                f"should be; point DATABASE_URL at the metrics store "
                f"and compose again (docs §5.4)"
            )
        store = getattr(route, "store", None)
        url = getattr(store, "database_url", None)
        return cls(route, EpochCountGauge(url), rail, NodeProvenanceReader(url))

    # -- The page and its render ---------------------------------------------

    def page(self) -> DashboardPage:
        """One fresh page over the route's answer, the triple's, the
        rail's and the gauge's.

        The whole content read is the route's ``get()`` — the store's
        own history, figures already rebuilt from the pair each row
        carries — and the page's figure content is built from the
        response alone.  The one read that is *not* the response's is
        the triple's: when the response names a campaign (it is
        truthy exactly when one closed), the campaign's node rows are
        read through :attr:`provenance` and held on the panel beside
        the response, so the figure and the words that attribute it
        are one page's facts rather than two reads that could
        disagree; when no campaign has closed there is no campaign
        whose rows to read, and the panel carries the empty reading
        rather than asking for an id the response never named.  The
        lamps' rail is read *after* those two and the chrome's count
        *after* that, in the order the page renders: the primary seat
        — figure and triple together — is the page's first and
        defining content, asked first, and a route that refuses
        aborts the page before a node row is ever read, a refusing
        triple before the rail is ever asked, and a rail that refuses
        before the gauge is — the load in the ordering law, and the
        reason a failing route read, a failing triple read, a failing
        rail read and a failing ledger read stay distinguishable (the
        route's arrives as feature 341's
        :class:`~ops.errors.FdrDeployMetricError`, the rail's as
        feature 342's :class:`~ops.errors.InstrumentStatusError` —
        each already this member's vocabulary, each propagated
        untranslated for the same reason: re-wrapping would only bury
        the surface that refused; the triple's and the gauge's arrive
        as the render vocabulary's own
        :class:`~ops.errors.DashboardRenderError`, translated at
        their seams).  None is ever caught into an answer, and none
        is cached: the next page re-asks all four.
        """
        response = self._route.get()
        provenance = (
            self.provenance.reading(response.campaign_id)
            if response
            else CampaignProvenance()
        )
        rail = self._rail.get()
        promotion = require_promotion()
        try:
            count = self._gauge.remaining()
        except promotion.EpochChargeError as exc:
            # The gauge's own refusal, translated at the member seam —
            # the route's move one figure over (``get()`` narrowing the
            # scoring store's refusal into FdrDeployMetricError): the
            # ledger is the promotion member's, the chrome is this
            # member's, and the vocabulary must live where the caller
            # catches it, so a single ``except
            # DashboardRenderError`` around a render guards every way
            # the page can refuse to draw.  The original is chained so
            # the operator still sees the gauge's own words — never
            # swallowed, never retried, and never answered around with
            # a count the ledger did not state.
            raise DashboardRenderError(
                f"the dashboard's chrome could not read the "
                f"{EPOCH_COUNT_LABEL} count: the promotion member's "
                f"gauge refused the ledger read: {exc!r}. The count "
                "renders in permanent chrome on every page precisely "
                "so depletion stays visible, and a read that cannot be "
                "made is surfaced rather than answered around — a "
                "chrome that quietly showed a full ledger while the "
                "epochs ran out unseen is the state §13 item 4's "
                "ledger exists to make visible, not hide; the repair "
                "is the ledger's (the original refusal is chained), "
                "never a fallback figure (feature 352, prd §13 item 4)"
            ) from exc
        return DashboardPage(
            primary=FdrDeployPanel(response=response, provenance=provenance),
            chrome=EpochCountChrome(count=count),
            lamps=InstrumentLampsChrome(response=rail),
        )

    def render(self, st: Any = None) -> DashboardPage:
        """Render one page through Streamlit and answer it.

        ``st`` is the render carrier — the real :mod:`streamlit`
        module when handed ``None`` (resolved through
        :func:`require_streamlit`), or any duck-typed stand-in a test
        records calls on.  The carrier is checked against the render
        contract (:data:`_RENDER_CARRIER_CONTRACT`) before anything
        emits, the same duck-check discipline the endpoint applies its
        store.

        The order is the features' law, made literal: page
        configuration, the title, the permanent chrome — the three
        lamp lines first (docs §5.4 draws the lamps *"at the top of
        the left rail"*, one caption per lamp, in the rail's own
        order, each carrying its own state word) and then feature
        352's strip, the remaining clean epoch count as one caption —
        on every page including the one where no campaign has closed
        — then the primary panel: its headline (the qualifier beside
        the figure's name), its numeral (no delta: the figure has no
        green-up direction), its provenance plate, the campaign's
        provenance line (the triple beside the figure — short form,
        the state words, or the mixed refusal), and only then the
        one chart the dashboard draws, the panel's own FDR_deploy
        trend — each point labelled by its campaign's
        ``computed_at`` instant (the chart handed two named
        columns, ``x=`` the instant's :data:`COMPUTED_AT_LABEL`
        and ``y=`` the figure's :data:`FDR_DEPLOY_LABEL`), never
        a bare index: J02's acceptance (*"its axis says which
        campaign/when each point is (not a bare 0, 1, 2
        index)"*) is answered by the date half the clause leaves
        a choice of.  The chrome is the one thing that renders above the
        numeral — furniture beside content, never a second metric
        competing with the top line — and nothing but the trend is
        ever charted.  The provenance line renders on the populated
        page only, beneath the plate it completes: the page with no
        campaign closed has no campaign whose triple could be read,
        and its words are the ones that say why there is no numeral.
        The page answered is the page that rendered, so a caller (or
        a test) can read exactly what the operator saw.
        """
        carrier = require_streamlit() if st is None else st
        missing = [
            name for name in _RENDER_CARRIER_CONTRACT
            if not callable(getattr(carrier, name, None))
        ]
        if missing:
            raise TypeError(
                "OperatorDashboard renders through a Streamlit carrier "
                f"(something callable for each of "
                f"{', '.join(_RENDER_CARRIER_CONTRACT)}); this carrier "
                f"does not answer: {', '.join(missing)}. The render is "
                f"duck-typed so the workspace never depends on the UI "
                f"library, and a carrier that cannot answer the calls "
                f"cannot render the primary panel (feature 351, docs §16)"
            )
        page = self.page()
        panel = page.primary
        carrier.set_page_config(page_title=DASHBOARD_PAGE_TITLE)
        carrier.title(DASHBOARD_TITLE)
        for line in page.lamps.lines:
            carrier.caption(line)
        carrier.caption(page.chrome.line)
        carrier.header(panel.headline)
        carrier.metric(label=FDR_DEPLOY_LABEL, value=panel.numeral or "—")
        if panel:
            carrier.caption(panel.plate or "")
            carrier.caption(panel.provenance.line)
            carrier.line_chart(
                {
                    COMPUTED_AT_LABEL: [
                        instant for instant, _figure in panel.points
                    ],
                    FDR_DEPLOY_LABEL: list(panel.series),
                },
                x=COMPUTED_AT_LABEL,
                y=FDR_DEPLOY_LABEL,
            )
        else:
            carrier.caption(
                "no campaign has closed, so no figure was measured"
            )
        return page


def render_refusal(carrier: Any, exc: OpsError) -> None:
    """Display one dashboard refusal as the operator's error message.

    J03's own ask, stated as the function's shape: the misconfigured
    deployment's page must answer the refusal with *"what is wrong,
    the code word, and the one repair"* — and nothing else.  The
    refusal's own message already carries the first and the third
    (every typed error this member raises names what is wrong and the
    one repair; the workspace's law, and the reason ``exc``'s words
    are passed through verbatim rather than paraphrased here — a
    paraphrase could drop the repair on the floor), so this function
    adds the second, the code word (:data:`DASHBOARD_REFUSAL_CODE`),
    as the line's first token: the greppable token an operator takes
    to the docs and the logs, spelled once as a constant so the
    display, the tests and the journey's acceptance line cannot drift
    apart on it.

    One line, no traceback and no filesystem path — the member's
    standing constraint on every refusal it answers, held at the one
    seam where a raw exception would otherwise reach the screen:
    Streamlit's unhandled-exception page renders the interpreter's
    own traceback, absolute paths included, plus the *Ask Google /
    Ask ChatGPT* buttons that post the text to a third-party service
    (the exact render docs/user-journeys/RESULTS.md run 1 found, J03)
    — so the refusal is *displayed* through the carrier's ``error``
    element instead of left to escape.  The element is duck-checked
    (a callable ``error``, the same discipline the render's own
    carrier contract takes) rather than ``isinstance``-guarded, for
    the same reason: the factory's scan imports members under
    synthetic names, and the contract — not the class — is what
    crosses every seam in this workspace.  A carrier with no element
    to be read through is refused by name rather than swallowed,
    because a refusal nobody can see is the quietly-broken page this
    whole member exists to rule out.

    Called by :func:`main` for every :class:`~ops.errors.OpsError`
    the compose-and-render path raises; callable on its own so the
    display itself is testable and a future surface (the chrome's,
    an adapter's) can show a refusal without re-spelling the code
    word (J03, docs §16).
    """
    if not callable(getattr(carrier, "error", None)):
        raise TypeError(
            "a dashboard refusal is displayed through the render "
            "carrier's error element (Streamlit's st.error — the one "
            "element that renders an operator-facing message rather "
            "than a traceback), and this carrier does not answer one "
            f"(got {type(carrier).__name__}). A refusal nobody can "
            "read is the quietly-broken page the display exists to "
            "prevent: hand a carrier that answers error() — the same "
            "duck-check discipline the render itself takes "
            "(J03, docs §16)"
        )
    carrier.error(f"{DASHBOARD_REFUSAL_CODE}: {exc}")


def main(app: Any = None, st: Any = None) -> DashboardPage | None:
    """The Streamlit entrypoint: compose, render — and display a
    refusal rather than escaping it.

    What ``streamlit run packages/ops/src/ops/dashboard.py`` lands on
    (through the ``__main__`` guard below).  The application is
    composed through the seat — the dashboard reads the *composed*
    route, the one the deployment's process actually carries — and the
    page renders through the real :mod:`streamlit`.  Both doors are
    parameterised so the entrypoint is testable without a UI process:
    ``app`` hands in an already-composed application, ``st`` a
    recording carrier.

    A refusal on that path is *displayed*, never escaped: the carrier
    is resolved *first* — before compose, before render — so a
    deployment without Streamlit still gets the deferred door's own
    repair words, the one refusal there is nothing to display it with
    (it raises, as its own tests pin) — and then compose-and-render
    runs inside a single ``except`` over :class:`~ops.errors.OpsError`,
    the member's base, so every way the page can refuse to draw (the
    composition door's :class:`~ops.errors.DashboardRenderError`, the
    route's :class:`~ops.errors.FdrDeployMetricError`, the rail's
    :class:`~ops.errors.InstrumentStatusError`) displays as one
    :func:`render_refusal` line — the code word beside the refusal's
    own words, no traceback and no filesystem path (J03's ask, and the
    member's standing constraint).  Nothing else renders: the page is
    asked whole before anything emits, so a refused page carries no
    numeral, no chrome and no chart.  The answer is ``None`` because
    no page drew — the refusal is not swallowed into one — and a
    programmatic caller that wants the exception still composes and
    renders directly (:meth:`OperatorDashboard.render` raises,
    exactly as its own tests pin).

    Every rerun re-runs the whole path: compose, read, render.  There
    is no cache anywhere in it, by design — the numeral on the screen
    is the store's state at the moment of the rerun.
    """
    carrier = require_streamlit() if st is None else st
    try:
        return OperatorDashboard.composed(app).render(st)
    except OpsError as exc:
        render_refusal(carrier, exc)
        return None


if __name__ == "__main__":  # pragma: no cover - the streamlit-run path
    main()
