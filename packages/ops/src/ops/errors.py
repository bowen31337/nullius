"""The ops member's refusal vocabulary.

One base class (:class:`OpsError`) so a caller — an HTTP adapter over
the metrics routes, the dashboard's data fetch, a future feature 342
lamp reader — can catch every observability refusal in one ``except``
clause, exactly the way :class:`~regime.errors.RegimeError` and
:class:`~book.errors.BookConstructionError` serve their members.  The
subclasses split by *where the refusal happens*, which is what makes
each one actionable: the split is by surface, because a surface is the
unit the category's features name (feature 341's fdr-deploy route, 342's
instrument-status, 343's regime-coverage, 351's dashboard), and a caller
asking one surface must not have to import another surface's error to
catch its own refusals.

What the member refuses, and why loudly: every figure this member
serves is a number an operator steers the system by (§16 makes
``FDR_deploy`` the top-line number precisely because it is the one
worth staring at), so a quietly-defaulted answer is the failure mode
the whole observability category exists to rule out.  An absent figure
is answered as an absence on the response (feature 267's
discoverable-state stance, restated at the route); a *broken* figure —
a history the response cannot hold, a store that cannot be asked — is
refused, in this vocabulary, with the original chained.
"""

from __future__ import annotations

__all__ = ["DashboardRenderError", "FdrDeployMetricError", "OpsError"]


class OpsError(Exception):
    """The base of every ops-member refusal.

    Catch this to catch the member as a whole.  It is deliberately
    empty: the words live on the subclasses, where the refusal's own
    argument is stated, and a bare ``OpsError`` reaching a caller would
    name a refusal nobody wrote an argument for.
    """


class FdrDeployMetricError(OpsError):
    """Feature 341's refusals: the top-line figure's own error states.

    Raised in exactly two places, both in :mod:`ops.fdr_route`, and the
    split between them is the member-seam law the whole workspace
    states for error vocabulary: a helper that raises *another
    member's* error escapes through this member's call path, and a
    caller who wrote ``except FdrDeployMetricError`` — the whole point
    of the route owning a class — would take the process down with an
    error from a module it never imported.  So:

    * a history the response cannot hold — a malformed triple, a
      figure that is not a finite fraction, instants that run
      backwards — is refused here at construction, because a frozen
      value that validated nothing would hand a hand-built history the
      store's own guarantees never stood behind; and
    * a read that failed is *translated* here from feature 267's
      :class:`~scoring.FdrDeployError` (chained, never swallowed),
      because the rows are the scoring member's and the route is this
      member's, and the refusal's vocabulary must live where the
      caller catches it.

    Never raised for an *empty* trend: a deployment that has closed no
    campaign is a discoverable state the response answers with an
    absence, not a refusal — the stance feature 267's own ``history()``
    takes and prd §11's target is read across.
    """


class DashboardRenderError(OpsError):
    """Feature 351's refusals: the render path's own error states.

    Raised in :mod:`ops.dashboard`, at the two places the dashboard's
    sentence draws a line the render must not cross:

    * **a page whose primary panel is not the FDR one is refused at
      construction.**  docs §16 states the law this member exists to
      hold — *"If the primary chart is an equity curve, the system's
      actual purpose has been quietly abandoned"* — and the app spec's
      design system carries it over as the one binding presentation
      rule (*"the top-line number is FDR_deploy and never an equity
      curve; any panel that would promote profit above epistemic state
      is rejected at review"*).  The page model is that review: the
      primary seat answers the FDR panel's display contract or the page
      is refused by name, so the substitution never renders.
    * **an operator surface that resolves no route refuses to proceed
      rather than rendering a numeral nobody measured.**  The seat's
      own docstring names this caller as the one that must take that
      stance: a dashboard that quietly rendered ``0.0`` over an absent
      store would answer "a flawless system" for one that never ran —
      the quietly-defaulted number this whole category exists to rule
      out.

    Not raised for an *empty* trend — that absence renders honestly
    (no numeral, the words that say why) — and not raised for a failed
    store read, which arrives as feature 341's own
    :class:`FdrDeployMetricError` and propagates untranslated: it is
    already this member's vocabulary, and re-wrapping it would only
    bury the route that refused.
    """
