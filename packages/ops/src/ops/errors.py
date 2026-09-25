"""The ops member's refusal vocabulary.

One base class (:class:`OpsError`) so a caller — an HTTP adapter over
the metrics routes, the dashboard's data fetch, a future feature 342
lamp reader — can catch every observability refusal in one ``except``
clause, exactly the way :class:`~regime.errors.RegimeError` and
:class:`~book.errors.BookConstructionError` serve their members.  The
subclasses split by *where the refusal happens*, which is what makes
each one actionable: the split is by surface, because a surface is the
unit the category's features name (feature 341's fdr-deploy route, 342's
instrument-status, 343's regime-coverage, 348's evaluation log record,
349's replay log record, 350's live-metrics store, 351's dashboard), and
a caller asking one surface
must not have to import another surface's error to catch its own
refusals — and a surface that renders *within* another (the chrome
within the dashboard) shares its vocabulary rather than splitting it,
so a caller guarding one render catches every way the page can refuse
to draw.

What the member refuses, and why loudly: every figure this member serves
is a number an operator steers the system by (§16 makes ``FDR_deploy``
the top-line number precisely because it is the one worth staring at), so
a quietly-defaulted answer is the failure mode the whole observability
category exists to rule out.  An absent figure is answered as an absence
on the response (feature 267's discoverable-state stance, restated at the
route); a *broken* figure — a history the response cannot hold, a store
that cannot be asked, a live metric that measured but never landed — is
refused, in this vocabulary, with the original chained.

Feature 350 adds the live-metrics store's own: :class:`LiveMetricError`,
the refusal of a live metric that cannot be persisted or read — an
unknown metric name, a value that is not the shape the metric's name
fixes, a store that cannot be asked.  It is the store-surface sibling of
:class:`FdrDeployMetricError`: one names the metric and the bound it
broke, the other names the top-line figure's own states, and a caller
that catches :class:`OpsError` catches both without importing a module it
never reached for.

Feature 349 adds the replay log record's own: :class:`ReplayLogError`,
the refusal of an ask that names no replay — the emission seam's
vocabulary, stated where the store-surface features state theirs.  It
is the first vocabulary this member's *emission* surfaces carry (the
route, the store and the dashboard are all *answer* surfaces), and its
law is therefore the ordering one: the ask is refused **before
anything is emitted**, because a malformed record on a log stream
would be structured testimony nobody measured — the quietly-defaulted
figure this category exists to rule out, in its log-shaped form, and
the one medium where it cannot be corrected by a re-read.

Feature 348 adds the evaluation log record's own:
:class:`EvaluationLogError`, the replay half's sibling over §16's
other record — the refusal of an ask that names no evaluation, stated
under the same ordering law (before anything is emitted) and for the
same reason: the pair ships on one parent logger, and one knob must
not mix testimony nobody booked onto the stream it gates.

Feature 347 adds the meta-overfit gap store's own:
:class:`MetaOverfitGapError`, the refusal of a gap that cannot be the
indicator it claims — a train or holdout mean that is not a measurement
of a half, a size that is not a count of worlds, a stored difference
that disagrees with the two sides beside it, a store that cannot be
asked.  It is the store-surface sibling of :class:`LiveMetricError`
one feature over, and it carries the same asymmetry: an *absent*
indicator is a discoverable state answered as an absence (no cycle has
closed a gap out yet), while a *broken* one is refused, because a
divergence that is quietly defaulted is exactly the overfitting this
category exists to make visible.
"""

from __future__ import annotations

__all__ = [
    "DashboardRenderError",
    "EvaluationLogError",
    "FdrDeployMetricError",
    "LiveMetricError",
    "MetaOverfitGapError",
    "OpsError",
    "ReplayLogError",
]


class OpsError(Exception):
    """The base of every ops-member refusal.

    Catch this to catch the member as a whole.  It is deliberately empty:
    the words live on the subclasses, where the refusal's own argument is
    stated, and a bare ``OpsError`` reaching a caller would name a refusal
    nobody wrote an argument for.
    """


class FdrDeployMetricError(OpsError):
    """Feature 341's refusals: the top-line figure's own error states.

    Raised in exactly two places, both in :mod:`ops.fdr_route`, and the
    split between them is the member-seam law the whole workspace states
    for error vocabulary: a helper that raises *another member's* error
    escapes through this member's call path, and a caller who wrote
    ``except FdrDeployMetricError`` — the whole point of the route owning
    a class — would take the process down with an error from a module it
    never imported.  So:

    * a history the response cannot hold — a malformed triple, a figure
      that is not a finite fraction, instants that run backwards — is
      refused here at construction, because a frozen value that validated
      nothing would hand a hand-built history the store's own guarantees
      never stood behind; and
    * a read that failed is *translated* here from feature 267's
      :class:`~scoring.FdrDeployError` (chained, never swallowed), because
      the rows are the scoring member's and the route is this member's,
      and the refusal's vocabulary must live where the caller catches it.

    Never raised for an *empty* trend: a deployment that has closed no
    campaign is a discoverable state the response answers with an absence,
    not a refusal — the stance feature 267's own ``history()`` takes and
    prd §11's target is read across.
    """


class LiveMetricError(OpsError):
    """Feature 350's refusals: the live-metrics store's own error states.

    Raised in exactly the places :mod:`ops.live_metrics` states the
    store's contract, and the split between them is the member-seam law
    the whole workspace states for error vocabulary: a helper that raises
    *another module's* error escapes through this member's call path, and
    a caller who wrote ``except LiveMetricError`` — the whole point of the
    store owning a class — would take the process down with an error from
    a module it never imported.  So:

    * an unknown metric — a name that is not one of the closed set of four
      the sentence fixes (``ic_ratio``, ``fill_cost_bps``, ``reject_rate``,
      ``feed_staleness_s``) — is refused by name, because a value stored
      under a name the table does not know is a metric nobody measured and
      there is no column to put it in;
    * a value that is not a finite real, or that falls outside the bound
      the metric's name fixes (``ic_ratio`` and ``reject_rate`` inside
      their correlation/rate bounds; ``fill_cost_bps`` and
      ``feed_staleness_s`` finite with the sign the unit allows) is
      refused, because a value that could not be the metric it claims is a
      corruption at the door, not a measurement; and
    * a read or write that failed against the store is *translated* here
      from :class:`sqlite3.Error` (chained, never swallowed), because the
      table is this member's and the caller's single ``except
      LiveMetricError`` must catch a metric that measured but never landed
      rather than be taken down by the database's own error.

    Nothing is ever caught *into* an answer: a live metric that cannot be
    persisted is surfaced, and the repair is the store's — the same
    stance feature 267 takes toward a figure that measured but never
    landed, and the failure mode this feature exists to rule out.
    """


class DashboardRenderError(OpsError):
    """The dashboard render path's refusals — features 351's and
    352's, one vocabulary because one render refuses with it.

    Raised in :mod:`ops.dashboard` and :mod:`ops.chrome`, at the places
    the two features' sentences draw lines the render must not cross:

    * **a page whose primary panel is not the FDR one is refused at
      construction.**  docs §16 states the law this member exists to hold
      — *"If the primary chart is an equity curve, the system's actual
      purpose has been quietly abandoned"* — and the app spec's design
      system carries it over as the one binding presentation rule
      (*"the top-line number is FDR_deploy and never an equity curve; any
      panel that would promote profit above epistemic state is rejected at
      review"*).  The page model is that review: the primary seat answers
      the FDR panel's display contract or the page is refused by name, so
      the substitution never renders.
    * **an operator surface that resolves no route refuses to proceed
      rather than rendering a numeral nobody measured.**  The seat's own
      docstring names this caller as the one that must take that stance: a
      dashboard that quietly rendered ``0.0`` over an absent store would
      answer "a flawless system" for one that never ran — the
      quietly-defaulted number this whole category exists to rule out.
    * **a page whose chrome cannot answer the count is refused, and so is
      a count that is not one** (feature 352, the permanent chrome).  The
      spec's *"the remaining clean epoch count sit in permanent chrome"*
      and *"at all times"* are one law: a carrier that does not answer the
      chrome's display contract, or a figure that is not a non-negative
      count of rows, is refused by name rather than rendered — a strip on
      every page showing a number nobody derived would be depletion's own
      quietly-defaulted figure.
    * **a chrome read that fails is translated here from the promotion
      member's :class:`~promotion.errors.EpochChargeError`** (chained,
      never swallowed), the same seam law that translates the scoring
      store's failure into :class:`FdrDeployMetricError` one module over:
      a caller whose single ``except DashboardRenderError`` guards a
      render must not be taken down by an error from a module it never
      imported — and the read is never caught *into* an answer, because a
      chrome that quietly showed a full ledger while the epochs ran out
      unseen is the state prd §13 item 4's ledger exists to make visible,
      not hide.

    Not raised for an *empty* trend — that absence renders honestly (no
    numeral, the words that say why) — and not for a *zero* count, which
    is a measurement feature 297 answers and the chrome renders (the
    visible exhaustion, never a refusal).  Not raised for a failed store
    read either, which arrives as feature 341's own
    :class:`FdrDeployMetricError` and propagates untranslated: it is
    already this member's vocabulary, and re-wrapping it would only bury
    the route that refused.
    """


class ReplayLogError(OpsError):
    """Feature 349's refusals: the replay log record's own error states.

    Raised in exactly the places :mod:`ops.replay_log` states the
    emission seam's contract — the carrier reads and the record's own
    construction — and the split between them is the seam's law: the
    reader refuses a carrier that is not the terminal answer the replay
    produced, the record refuses values it could not honestly carry,
    and nothing else on the path refuses at all.  So:

    * a carrier with no ``score`` — not feature 249's
      :class:`~replay.TerminalPick` — and a carried pick that names no
      node are refused at the read, naming what arrived, because the
      record is shaped around the pair the terminal requirement answers
      (the pick absent-able, the score always present) and a carrier
      that answers neither half answers no completed scoring;
    * an id that is not a non-empty string, a beta that is not finite,
      a score that is not a real number or ``-inf`` — a NaN is refused,
      for the reason feature 249 refuses to score one and the row's
      writer refuses to persist one: it compares false against
      everything and would read as "no scoring" — and a committed pick
      that is neither a node id nor ``None`` are refused at
      construction, so a record built by hand is held to the law the
      emission path already passed.

    **Never raised for the miss.**  A policy that emitted no pick is
    scored ``-inf`` — feature 249's floor — and the miss's record is
    *emitted*, not refused: the log stream is where a dreaming cycle's
    miss rate is counted, and a seam that refused the miss would hide
    exactly the replays the rate is about.  What is refused is the ask,
    and every refusal fires **before anything is emitted** — a refused
    ask puts nothing on the stream, so the stream carries one record
    per replay and only records that are testimony of a scoring that
    completed.
    """


class EvaluationLogError(OpsError):
    """Feature 348's refusals: the evaluation log record's own error
    states.

    The replay half of §16's structured-logging pair states the
    emission law (:class:`ReplayLogError`, above) and this is its
    sibling for the evaluation half — the same law over a different
    record, raised in exactly the places :mod:`ops.evaluation_log`
    states the seam's contract (the carrier reads and the record's
    own construction), and nowhere else on the path.  So:

    * a carrier that does not state one of the five fields — the
      provenance triple plus ``node_id`` and ``campaign_id`` — is
      refused at the read, naming what arrived, because the record's
      schema is §16's sentence and a carrier that does not state a
      field names no evaluation the ledger could join;
    * a triple term of ``None`` — the pre-stamp read's spelling, a
      statement about the ledger's history rather than provenance an
      evaluation ran under — is refused, for the reason the ledger's
      own write seams refuse it: a charge that cannot name its
      evaluator, its snapshot and its cost model is a charge no
      replay can reproduce;
    * a hash that is not the sha256 hexdigest's own 64-hex spelling
      (a ``sha256:``-prefixed image reference, a short hash, a
      truncated value, a non-hex token, a non-string) and an id that
      is not a UUID are refused at construction, so a record built by
      hand is held to the law the emission path already passed.

    **Never raised for a failed evaluation.**  §16's sentence names
    identity fields and no verdict, and the trial's own row carries
    the outcome because a count of outcomes is what the ledger is
    for — a failed trial is as chargeable a fact as a successful one,
    and its record ships the same five fields a successful one's
    does, because the identity the record carries exists whatever the
    verdict was.  What is refused is the ask, and every refusal fires
    **before anything is emitted** — a refused ask puts nothing on
    the stream, so the stream carries one record per evaluation and
    only records that are testimony of an evaluation that was booked.
    """


class MetaOverfitGapError(OpsError):
    """Feature 347's refusals: the meta-overfit gap store's own error
    states.

    Raised in exactly the places :mod:`ops.meta_overfit` states the
    store's contract, and the split between them is the member-seam law
    the whole workspace states for error vocabulary: a helper that
    raised another module's error would escape through this member's
    call path, and a caller who wrote ``except MetaOverfitGapError`` —
    the whole point of the store owning a class — would be taken down by
    an error from a module it never imported.  So:

    * a train or holdout mean that is not a finite real — ``bool``
      refused before real, ``None`` refused as the unmeasured half it
      is — is refused at the door, because the gap is the difference of
      two *measurements* and a half that measured nothing has no gap
      to be taken from;
    * a world count that is not a positive integer is refused, because
      the count is the weight the halves' means are read under and a
      fractional or non-positive world count names a pool that was
      never split (``bool`` refused before ``int``, the family's law);
    * a stored row whose ``gap`` disagrees with the two means beside it
      — or whose means are not the split's own arithmetic — is refused
      on the read, because the table's difference must be the one its
      own columns recompute to and a row that lies about its own
      subtraction is a trend nobody can audit; and
    * a read or write that failed against the store is *translated*
      here from :class:`sqlite3.Error` (chained, never swallowed),
      because the table is this member's and the caller's single
      ``except MetaOverfitGapError`` must catch a divergence that
      measured but never landed rather than be taken down by the
      database's own error.

    **Never raised for an absent indicator.**  A deployment whose
    dreaming loop has closed no cycle out answers ``None`` from the
    point read and an empty sequence from the sweep — a discoverable
    state, not a refusal, exactly as an unclosed campaign is for
    feature 267's trend and an unrecorded live metric is for feature
    350's four tiles.  What is refused is a gap that could not be the
    indicator it claims, and the failure mode this feature exists to
    rule out — §12.1's *"dreaming overfits its own replay pool"*
    arriving as a number nobody measured — is refused rather than
    served.
    """
