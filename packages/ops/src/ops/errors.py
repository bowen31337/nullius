"""The ops member's refusal vocabulary.

One base class (:class:`OpsError`) so a caller — an HTTP adapter over
the metrics routes, the dashboard's data fetch, a future feature 342
lamp reader — can catch every observability refusal in one ``except``
clause, exactly the way :class:`~regime.errors.RegimeError` and
:class:`~book.errors.BookConstructionError` serve their members.  The
subclasses split by *where the refusal happens*, which is what makes
each one actionable: the split is by route, because a route is the unit
the category's features name (feature 341's fdr-deploy, 342's
instrument-status, 343's regime-coverage), and a caller asking one
route must not have to import another route's error to catch its own
refusals.

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

__all__ = ["FdrDeployMetricError", "OpsError"]


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
