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

Feature 346 adds the discovery-rate store's own:
:class:`DiscoveryRateError`, the refusal of a figure that cannot be the
quotient it claims — a campaign id that joins no campaign, a count that
is not a whole number, a denominator that is zero (a rate over no
budget-charging trials is undefined), a denominator above the ledger's
own row count (feature 93's ``K_effective`` is a *subset* count and the
ledger is append-only), a stored rate that disagrees with the counts
beside it, a store that cannot be asked.  It is the third of the
store-surface siblings (:class:`LiveMetricError` and
:class:`MetaOverfitGapError` are the other two) and it carries the same
asymmetry, with one addition the other two do not need: an *absent*
rate is a discoverable state answered as an absence, a *zero* rate is a
measurement the store persists happily (a campaign that found nothing
measured exactly that, and prd §11 grades the metric by its direction),
and only a rate that could not have been divided is refused — because a
flattering denominator is precisely the failure the sentence's second
clause exists to prevent.

Feature 345 adds the Type-B depth store's own: :class:`TypeBDepthError`,
the refusal of a figure that cannot be the count it claims — a campaign
id that joins no campaign, a count that is not a whole number of error
events, a negative count, a count past the column's range, a label that
orders no trend, a store that cannot be asked.  It is the fourth of the
store-surface siblings (:class:`LiveMetricError`,
:class:`MetaOverfitGapError` and :class:`DiscoveryRateError` are the
other three) and it carries the family's asymmetry in its Type-B shape:
an *absent* figure is a discoverable state answered as an absence (no
campaign has closed a count out yet), a **zero count is the target
measurement the store persists happily** (a Type-D campaign that
deepened past nothing is exactly the state prd §11's *"falling across
campaigns"* is driving toward), and what is refused is a figure that
could not have been accounted — because the count is feature 269's own
answer, an integer of events the store hands back unchanged, and a
number that is not one is nobody's measurement.

Feature 344 adds the planted-null calibration store's own:
:class:`NullCalibrationError`, the refusal of a pair that cannot be the
calibration it claims — a campaign id that joins no campaign, a figure
that is not a fraction of a planted class, a label that orders no trend, a
store that cannot be asked.  It is the fifth of the store-surface siblings
(:class:`LiveMetricError`, :class:`MetaOverfitGapError`,
:class:`DiscoveryRateError` and :class:`TypeBDepthError` are the other
four) and it carries the family's asymmetry: an *absent* pair is a
discoverable state answered as an absence (no campaign has closed a
calibration out yet), **the endpoints are measurements the store
persists happily** — a sensitivity of ``0.0`` is a campaign that found
none of its reals, a specificity of ``1.0`` one that wrongly declared
nothing, both of them the honest corners feature 266 answers — and what
is refused is a pair that could not have been measured, because the
figures are feature 266's own answer over the campaign's planted
population and a number that is not a fraction of a class is nobody's
measurement.  The store derives nothing beyond them: no blend, no rate
over the two and no interval around either, so there is no derived-column
reconciliation to refuse here as there is at the sibling that computes its
own gap.

Feature 6 adds the four gate-evidence routes' shared own:
:class:`GateEvidenceMetricError`, the one class all four of
:mod:`ops.gate_evidence`'s endpoints translate into, because — unlike the
member's earlier routes, which each translate a *different* sibling
member's error — these four read this member's own stores and already
arrive in this member's own vocabulary
(:class:`NullCalibrationError`, :class:`TypeBDepthError`,
:class:`DiscoveryRateError`, :class:`MetaOverfitGapError`).  So:

* a hand-built history the response cannot hold — an entry that is not
  the owning store's own record type, a row whose ``recorded_at`` runs
  backwards from the one before it — is refused here at construction,
  because a frozen value that validated nothing would hand a hand-built
  trend the store's own guarantees it never stood behind; and
* a read that fails is *translated* here from whichever of the four
  store errors the read raised (chained, never swallowed), because the
  rows are each store's own and the route is this member's, and a
  caller that wrote ``except GateEvidenceMetricError`` across all four
  routes must not be taken down by an error from a module it never
  imported.

**Never raised for an absent trend.**  A deployment that has closed no
campaign or cycle out answers an empty history and a ``newest`` of
``None`` from every one of the four routes — a discoverable state, not a
refusal, exactly as it is at each of the four stores this class reads.
**Never raised for a zero measurement, either**: each store's own zero
(a flat discovery rate, a clean Type-B count, a calibration endpoint of
``0.0`` or ``1.0``, a gap of ``0.0``) is a measurement that store
persists happily, and this class never re-litigates that stance — what
it refuses is a trend that could not be the one a store answered.

Feature 343 adds the regime-coverage route's own:
:class:`RegimeCoverageMetricError`, the refusal of a distribution that
cannot be the pool's shape — a stratum named twice, a name that states
nothing, a count that is not a genuine non-negative integer, a ledger
whose §C7 mapping cannot be read, a coverage read that failed.  It is
feature 341's shape one surface on (a read-only route over another
member's store, its cross-member refusal translated at the seam), and it
carries §C7's own asymmetry: an *empty* ledger is a discoverable state
answered with no rows — the pool names nothing — while the two states a
careless surface would collapse into a zeroed distribution are held
apart, no ``DATABASE_URL`` composing no route at all and a *broken* read
refused in this vocabulary with the original chained.  A named-empty
stratum (``crash: 0``) is neither: it is a measurement the route serves.
"""

from __future__ import annotations

__all__ = [
    "DashboardRenderError",
    "DiscoveryRateError",
    "EvaluationLogError",
    "FdrDeployMetricError",
    "GateEvidenceMetricError",
    "InstrumentStatusError",
    "LiveMetricError",
    "MetaOverfitGapError",
    "NullCalibrationError",
    "OpsError",
    "RegimeCoverageMetricError",
    "ReplayLogError",
    "TypeBDepthError",
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


class DiscoveryRateError(OpsError):
    """Feature 346's refusals: the discovery-rate store's own error
    states.

    Raised in exactly the places :mod:`ops.discovery_rate` states the
    store's contract, and the split between them is the member-seam law
    the whole workspace states for error vocabulary: a helper that
    raised another module's error would escape through this member's
    call path, and a caller who wrote ``except DiscoveryRateError`` —
    the whole point of the store owning a class — would be taken down
    by an error from a module it never imported.  So:

    * an id that is not a UUID is refused, because §16's research
      metrics are *per campaign* and an id that cannot join the tree's
      campaign key names no campaign a rate could be persisted for;
    * a count that is not a whole number is refused, because the figure
      is a quotient of three counts and a fractional or flag-valued one
      would be this store inventing a figure the caller never stated;
    * a **denominator** of zero or less is refused *by name*, because
      the sentence says *budget-charging* trials and a campaign that
      spent no statistical degrees of freedom at all leaves the
      quotient undefined — answering ``0.0`` for it would persist the
      quietest possible claim about a research yield nobody measured;
    * a **denominator above the ledger's own row count** is refused,
      because feature 93's ``K_effective`` is the count of the ledger's
      rows whose ``charges_budget`` is true — *"excluding null nodes"* —
      so it is a *subset* count and can never exceed the size of the
      table it filters, and the ledger is append-only with no UPDATE
      and no DELETE (§8, enforced by role grants), so the pair cannot be
      produced honestly by any pruning either;
    * a stored row whose ``rate`` disagrees with the counts beside it is
      refused on the read, for the same reason feature 347 refuses a
      disagreeing gap: prd §11's grade is read off this column, and the
      two counts are the row's truth; and
    * a read or write that failed against the store is *translated*
      here from :class:`sqlite3.Error` (chained, never swallowed),
      because the table is this member's and the caller's single
      ``except DiscoveryRateError`` must catch a rate that measured but
      never landed rather than be taken down by the database's own
      error.

    **Never raised for an absent rate.**  A deployment that has closed
    no campaign out answers ``None`` from the point read and an empty
    sequence from the sweep — a discoverable state, not a refusal,
    exactly as an unclosed campaign is for feature 267's trend, an
    unclosed cycle for feature 347's gap and an unrecorded metric for
    feature 350's four tiles.  **Never raised for a zero, either**: a
    campaign that made no discoveries measured exactly that, and prd
    §11's *"trending up"* is a direction a flat zero is the honest
    bottom of — the zero is a figure the store persists, not a refusal
    it makes.  What is refused is a rate that could not be the figure it
    claims, and the failure mode this feature exists to rule out — a
    flattering denominator, or a quotient nobody divided — is refused
    rather than served.
    """


class TypeBDepthError(OpsError):
    """Feature 345's refusals: the Type-B depth store's own error
    states.

    Raised in exactly the places :mod:`ops.type_b_depth` states the
    store's contract, and the split between them is the member-seam law
    the whole workspace states for error vocabulary: a helper that raised
    another module's error would escape through this member's call path,
    and a caller who wrote ``except TypeBDepthError`` — the whole point
    of the store owning a class — would be taken down by an error from a
    module it never imported.  So:

    * an id that is not a UUID is refused, because §16's research
      metrics are *per campaign* and an id that cannot join the tree's
      campaign key — and the member's other research rows, keyed the
      same way — names no campaign a Type-B count could be persisted
      for;
    * a count that is not a whole number is refused, because the figure
      is feature 269's own ``depth_past_flip_errors`` — an integer of
      error events — and a fractional or flag-valued one would be this
      store inventing a figure the caller never stated;
    * a **negative count** is refused, because the count is of events
      that happened and there is no path by which fewer than none
      occurred;
    * a stored row whose count is not a count is refused on the read,
      because SQLite's columns are dynamically typed and a hand-edited
      row would otherwise reach prd §11's trend as an error figure
      nobody measured; and
    * a read or write that failed against the store is *translated* here
      from :class:`sqlite3.Error` (chained, never swallowed), because the
      table is this member's and the caller's single ``except
      TypeBDepthError`` must catch a count that measured but never
      landed rather than be taken down by the database's own error.

    **Never raised for an absent figure.**  A deployment that has closed
    no Type-D campaign out answers ``None`` from the point read and an
    empty sequence from the sweep — a discoverable state, not a refusal,
    exactly as an unclosed campaign is for feature 267's trend and
    feature 346's rate, an unclosed cycle for feature 347's gap and an
    unrecorded metric for feature 350's four tiles.  **Never raised for a
    zero, either**: a Type-D campaign that deepened past nothing measured
    exactly that, prd §11's *"falling across campaigns"* is a direction
    whose honest floor is a flat zero, and the zero is a figure the
    store persists, not a refusal it makes.  What is refused is a figure
    that could not have been accounted, and the failure mode this
    feature exists to rule out — a count nobody measured, quietly
    defaulted into the trend — is refused rather than served.
    """


class NullCalibrationError(OpsError):
    """Feature 344's refusals: the planted-null calibration store's own
    error states.

    Raised in exactly the places :mod:`ops.null_calibration` states the
    store's contract, and the split between them is the member-seam law
    the whole workspace states for error vocabulary: a helper that raised
    another module's error would escape through this member's call path,
    and a caller who wrote ``except NullCalibrationError`` — the whole
    point of the store owning a class — would be taken down by an error
    from a module it never imported.  So:

    * an id that is not a UUID is refused, because §16's research metrics
      are *per campaign* and an id that cannot join the tree's campaign
      key — and the member's other research rows, keyed the same way —
      names no campaign a calibration pair could be persisted for;
    * a figure that is not a finite real in ``[0, 1]`` is refused —
      ``bool`` before real, NaN and ±inf, and an out-of-bound value —
      because the pair is feature 266's own answer over the planted
      classes and a figure that is not a fraction of one is not a
      calibration; the likeliest thing wearing either name being a
      *count* of found reals or clean nulls, which clamped to an
      endpoint would persist a calibration nobody measured;
    * a stored row whose figure is not a finite real in ``[0, 1]`` — or
      whose id is not a campaign — is refused on the read, because
      SQLite will accept anything another tool inserts and a row this
      store could not have written would reach prd §11's trend as a
      calibration nobody measured; and
    * a read or write that failed against the store is *translated* here
      from :class:`sqlite3.Error` (chained, never swallowed), because
      the table is this member's and the caller's single ``except
      NullCalibrationError`` must catch a pair that measured but never
      landed rather than be taken down by the database's own error.

    **Never raised for an absent pair.**  A deployment that has closed no
    campaign out answers ``None`` from the point read and an empty
    sequence from the sweep — a discoverable state, not a refusal,
    exactly as an unclosed campaign is for feature 267's trend and
    feature 346's rate, an unclosed cycle for feature 347's gap and an
    unrecorded metric for feature 350's four tiles.  **Never raised for
    an endpoint, either**: a sensitivity of ``0.0`` is a campaign that
    found none of its reals and a specificity of ``1.0`` one that
    wrongly declared nothing — both are honest measurements feature 266
    answers deliberately, prd §11 tracks the pair without a target, and
    the store persists them as the figures they are.  What is refused is
    a pair that could not have been measured, and the failure mode this
    feature exists to rule out — a calibration nobody took, quietly
    defaulted into the trend — is refused rather than served.
    """


class GateEvidenceMetricError(OpsError):
    """Feature 6's refusals: the shared error of the four gate-evidence
    routes (:mod:`ops.gate_evidence`).

    Raised in exactly the places that module states its contract — a
    hand-built history the response cannot hold, and a read translated
    from whichever of this member's own four store errors
    (:class:`NullCalibrationError`, :class:`TypeBDepthError`,
    :class:`DiscoveryRateError`, :class:`MetaOverfitGapError`) the read
    raised, chained and never swallowed.  One class for all four routes,
    because unlike this member's cross-member routes each of the four
    reads this member's *own* stores and already arrives in this
    member's vocabulary — there is no sibling's error to keep separate.

    **Never raised for an absent trend or a zero measurement.**  Each of
    the four routes answers an empty history and a ``newest`` of
    ``None`` for a deployment that has closed no campaign or cycle out —
    a discoverable state — and serves a zero figure happily when a store
    measured one, the same stance each of the four stores already takes.
    What is refused is a trend that could not be the one a store
    answered.
    """


class RegimeCoverageMetricError(OpsError):
    """Feature 343's refusals: the regime-coverage route's own error
    states.

    Raised in exactly the places :mod:`ops.regime_coverage` states the
    route's contract, and the split between them is the member-seam law
    the whole workspace states for error vocabulary: a helper that raises
    *another member's* error escapes through this member's call path, and
    a caller who wrote ``except RegimeCoverageMetricError`` — the whole
    point of the route owning a class — would take the process down with
    an error from a module it never imported.  So:

    * a distribution the response cannot hold — a stratum named twice,
      an entry that is not a ``(stratum, world_count)`` pair, a name that
      states nothing, a count that is not a genuine non-negative integer
      (``bool`` refused before ``int``) — is refused here at
      construction, because a frozen value that validated nothing would
      hand a hand-built distribution the ledger's own guarantees never
      stood behind;
    * a ledger the route can reach but cannot read — a carrier whose
      ``ledger()`` answers something that does not carry §C7's
      ``{stratum: world_count}`` mapping — is refused by name rather than
      guessed at, because the alternative is this module assembling a
      distribution out of a value it does not understand; and
    * a read that failed is *translated* here from the regime member's
      :class:`~regime.CoverageError` (chained, never swallowed), because
      the rows are the regime member's and the route is this member's,
      and the refusal's vocabulary must live where the caller catches it.

    **Never raised for an empty ledger.**  A configured database where
    no census has run yet names no stratum, and that is a discoverable
    state the response answers with no rows, not a refusal — the stance
    feature 284's own read takes, and the same stance an absent campaign
    is for feature 341's trend.  The distinction this class exists to
    hold apart is the one §C7 turns on: an *empty* ledger (the pool
    names nothing) is answered, while a *broken* one — the store
    refusing, the mapping unreadable — is refused loudly, and neither is
    ever answered with a zeroed distribution nobody counted.
    """


class InstrumentStatusError(OpsError):
    """Feature 342's refusals: the instrument-status route's own error
    states.

    Raised in exactly the places :mod:`ops.instrument_status` states the
    route's contract, and the split between them is the member-seam law
    the whole workspace states for error vocabulary: a helper that raises
    *another member's* error escapes through this member's call path, and
    a caller who wrote ``except InstrumentStatusError`` — the whole point
    of the route owning a class — would take the process down with an
    error from a module it never imported.  **This route has three
    siblings to translate, not one**, because docs §5.4's rail has three
    lamps and each is the owning member's own read; so:

    * **the canary lamp** — a read that failed is *translated* here from
      the canary member's :class:`~canary.CanaryError` (chained, never
      swallowed).  §12's halt is that store's row, and this route is this
      member's, so the vocabulary must live where the caller catches it.
      A halt state that cannot be read is refused rather than answered
      around with a lit lamp — *"everything below them is worthless if
      any is out"* (docs §5.4) is exactly why a guess here is the worst
      of the alternatives;
    * **the KS-guard lamp** — a read that failed is translated from the
      nulloracle member's :class:`~nulloracle.KsGuardError`, and a trend
      read that failed from the scoring member's
      :class:`~scoring.FdrDeployError`, in the two separate places
      :meth:`~ops.instrument_status.InstrumentStatusEndpoint.get` states
      (the attribution and the finding).  A *half*-written guard reading
      — feature 123's own refusal — surfaces through this class rather
      than being answered with a lamp; and
    * **the ingest lamp** — a read that failed is translated from this
      member's own :class:`LiveMetricError` (the live-metrics store,
      feature 350), because the recorded ``feed_staleness_s`` reading is
      this member's own table and its refusal is the one the route can
      still name in its own words; and
    * **a rail the response cannot hold** — a lamp that is not a genuine
      bool, a p-value outside ``[0, 1]``, a negative or non-finite
      silence, a band that is not strictly positive, a lamp carried
      without the number that decides it, a KS lamp attributed to no
      campaign, or an ingest lamp whose bit *disagrees with its own
      reading* — is refused here at construction, because a frozen value
      that validated nothing would hand a hand-built rail this route's
      own guarantees, and own guarantees are what §5.4's rail is for.

    **Never raised for an absent lamp.**  A lamp nobody has measured —
    no campaign closed out, a campaign no job has guarded, no recorded
    feed reading, no configured band — is a discoverable state the
    response answers with ``None``, not a refusal: the stance feature
    267's empty history and feature 284's empty ledger already take, and
    the stance this route takes for all three lamps at once.  The
    distinction this class exists to hold apart is the one §5.4 turns
    on: an *unmeasured* instrument is answered as unmeasured, while a
    *broken* one — a store that refuses, a rail that contradicts itself
    — is refused loudly, and neither is ever answered with a lamp nobody
    read.
    """
