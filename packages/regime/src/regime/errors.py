"""The regime member's error vocabulary.

One base class (:class:`RegimeError`) so a caller — the promotion gate, the
coverage endpoint, an operator script, a later feature in this category —
can catch every failure of this member's path with a single ``except``.
The subclasses split by *what the caller must do about it*, not by which
line of code raised, the discipline :mod:`discovery.errors`,
:mod:`bootstrap.errors` and :mod:`nulloracle.errors` state for their own
trees.

:class:`CoverageError` is the category's first class, and it carries the
three faces of feature 283's one act — *System persists a
``regime_coverage`` count per stratum*:

* the **ask** — a stratum that is not non-empty text, or a ``world_count``
  that is not a genuine non-negative integer (``True`` is not a count, a
  negative number of worlds is not a number of worlds, and a fractional
  world is not a world).  Nothing was read and nothing was written; the
  repair is to re-send the ask with values the feature's sentence is about.
* the **row** — a stored row too corrupt to be a coverage count: a
  ``world_count`` column holding something that is not a non-negative
  integer, or an ``updated_at`` the table declares ``NOT NULL`` carrying
  nothing.  SQLite's columns are dynamically typed, so a raw ``INSERT``
  from another tool can land anything in this table, and a ledger read
  that swallowed it would report a count nobody wrote.  The repair is to
  the *data*, not to the call: an operator reads the stratum every
  message of this face names.
* the **address** — a ``DATABASE_URL`` this member cannot speak (a
  non-SQLite scheme, a host in a SQLite URL, no path at all, or an
  in-memory database, which would die with the connection that opened it
  and take the ledger with it).  The repair is to point the deployment at
  the database the ledger lives in.

One class rather than three because the caller's position is the same in
all three cases: the count it asked to persist was not persisted, and the
next step is to read which of the three faces the message names.  That is
the same repair :class:`~discovery.errors.AttemptLogError` gathers under
one class for its own act, and the contrast with this member's judgement
classes is the reason the split rule is worth stating here: feature 289's
:class:`DiversityClaimError` — a diversity claim refused on stratum
count — and feature 285's promotion block beside it are *judgement*
refusals whose repair is a decision about evidence rather than a
corrected re-ask, and they sit **beside** this class as siblings, not
under it — the shape
:class:`~discovery.errors.IllegalThemeError` takes beside
:class:`~discovery.errors.CampaignPlanningError`, and for the same reason:
a well-formed ask that runs into a configured space or a judged threshold
is not a malformed one, and folding the two would put two different
repairs behind one ``except``.

:class:`StratumAssignmentError` is that shape's first arrival — feature
290's, and a *fit* refusal rather than a judgement one: the census that
assigns each stored world a stratum refuses a full-history regime fit
(a labeler whose stated window is unbounded, or whose window spans a
world's whole usable series), and the repair is a corrected
configuration, not a decision about evidence and not a corrected row.
It sits beside :class:`CoverageError` for the same reason the judgement
classes will: the assignment is a different act from the persist, and a
caller that must react to *my labeler was configured as a full-history
fit* would misread it as *the ledger row could not be written* if the
two shared one ``except``.

:class:`BackfillProvenanceError` is feature 288's, and it is the third
class rather than a face of either of the first two because it is about a
different noun entirely: not a *count* and not an *assignment*, but a
world's **origin**.  Feature 287's backfill synthesizes worlds by
replaying stored discovery trees against historical epochs they were
never run on, and §C7's coverage number counts those worlds — so a
synthetic world that could not say which tree it came from would be
counted as one the system really traded, which is the masquerade feature
288's own sentence names.  Its repair is neither a corrected re-ask to
the ledger nor a corrected labeler configuration: it is to re-derive the
world from the tree and the epoch, or to correct the spelling that
produced it.  It opens every message with ``no_origin``, the greppable
one word the ``full_history_fit`` of the class above and
:mod:`discovery.errors`' ``illegal_theme`` and :mod:`dreaming.errors`'
``pool_frozen`` already establish.

:class:`DiversityClaimError` is feature 289's, and it is the judgement
refusal the paragraphs above reserved a sibling seat for: a
regime-diverse claim — the report that the replay pool spans regimes —
refused *while fewer than three strata hold stored worlds*.  It carries
the two faces of that one act:

* **the ask** — a ledger carrying no readable ``covered`` figure
  (nothing handed in, a string, a store where the reading belongs), or a
  floor that is not a positive whole count of strata.  Nothing about the
  pool was judged; the repair is to hand the judgment feature 284's
  reading and a floor that is a count.
* **the verdict** — the reading's covered strata fall below the floor.
  Every message opens with ``not_regime_diverse`` so the refusal is
  greppable by the one word that names the finding, and the repair is a
  decision about evidence, never a corrected re-ask: withdraw the claim,
  or raise the figure — the census (feature 290) and the backfill
  (feature 287) are the acts that do.

Deliberately **not** a :class:`CoverageError`, for the reason the first
paragraphs state: a caller catching the two together would read *the
coverage count could not be written* where the truth is *the pool does
not carry the diversity being claimed*, and the two repairs have nothing
in common.  Deliberately **not** a
:class:`StratumAssignmentError` or a :class:`BackfillProvenanceError`
either: nothing was assigned a stratum and no world states an origin —
the claim is the subject, and it is the only one this class speaks
about.

This member deliberately does **not** raise
:class:`feature_store.regime_labeler.FullHistoryFitError`, even though the
labeler that assigns worlds to strata is the source of the names this
ledger keys on: the workspace contract is that no member imports another,
and a caller reading a labeler refusal out of a *coverage persist* would
look in the wrong module for the cause — the labeler refuses a fit
(feature 58's law), while this member refuses a *row*.  Different acts,
different vocabularies; the seam between them is the caller that holds
both, and ``packages/regime/tests/test_cross_member.py`` is what keeps the
stratum count the two agree on honest.  Feature 290's census is where
that paragraph stops being a promise about the future and becomes the
seam itself: it duck-reads the labeler (``k``, ``window``,
``label_features``) and refuses in **this** vocabulary, so the
``full_history_fit`` a caller catches out of a census is this member's
class even when the labeler behind it is feature 58's — the law restated
at the one seam where the labeler's output becomes the ledger's input.
"""

from __future__ import annotations

__all__ = [
    "BackfillProvenanceError",
    "CoverageError",
    "DiversityClaimError",
    "RegimeError",
    "StratumAssignmentError",
]


class RegimeError(Exception):
    """Base class for every failure of the regime member's path."""


class CoverageError(RegimeError):
    """A coverage count could not be persisted as asked.

    Raised for the ask (a malformed stratum or count), for the row (a
    stored value too corrupt to be a coverage count) and for the address
    (a ``DATABASE_URL`` this member cannot speak) — the three faces of
    feature 283's one act, and the three repairs the module docstring
    states.  Every message names the stratum it is about where one is in
    question, so an operator's log line says which row of the ledger the
    refusal concerns.
    """


class StratumAssignmentError(RegimeError):
    """A stored world could not be assigned a stratum as asked.

    Feature 290's refusal, and it carries the faces of the census's one
    act — *assign each stored world to a stratum with the causal
    rolling-window labeler*:

    * **the fit** — the full-history face the feature's own sentence
      leads with, opening with ``full_history_fit`` so it is greppable by
      the one word that names it: a labeler whose stated ``window`` is
      ``None`` or absent or not a finite positive integer (an unbounded
      span *is* a full-history fit), or whose window spans all of a
      world's usable feature vectors (the one fit behind that world's
      stratum would be a fit over its entire history).  The repair is to
      the configuration: a finite trailing window, strictly shorter than
      every world's series.
    * **the vocabulary** — a stratum set the labeler's label space
      cannot be checked against: the wrong count of names, a duplicate,
      a name that cannot be one.  The repair is to the declared
      vocabulary, which is the labeler's configuration.
    * **the world** — a world that cannot be binned: no id, no usable
      regime features, an answer outside the label space, or an id
      already counted.  Every message names the world it is about.

    Deliberately **not** the labeler's own
    :class:`feature_store.regime_labeler.FullHistoryFitError` — the
    module docstring above states the law — and deliberately **not** a
    :class:`CoverageError`: nothing failed to persist here, and a caller
    catching the two together would read *the ledger refused my row*
    where the truth is *the fit was configured as a full-history one*.
    """


class BackfillProvenanceError(RegimeError):
    """A backfilled world's origin could not be recorded, or was not there.

    Feature 288's refusal — *persist a backfilled world with its
    originating campaign reference, so backfill never masquerades as
    fresh history* — and it carries the faces of that one act:

    * **the ask** — a carrier that states no origin.  A world whose id
      carries no ``@`` separator is a synthetic world that names no tree
      it came from; so are a blank campaign half and a blank epoch half.
      Every message opens with ``no_origin`` so the refusal is greppable
      by the one word the feature's sentence turns on.  The repair is to
      *re-derive the world* from the stored tree and the epoch it was
      replayed against, rather than to re-send the name: a world that
      cannot say where it came from is exactly the world that must not be
      seated, because seating it is the masquerade.
    * **the disagreement** — a carrier, or a stored row, that states a
      ``campaign_id`` or ``epoch_id`` contradicting its own ``world_id``.
      A backfilled world's origin is read *out of* its identity (feature
      287 spelled the id ``<campaign_id>@<epoch_id>`` for that reason), so
      a world stating two origins has none a reader could rely on.  The
      repair is to the spelling the caller assembled the world with, or to
      the row an outside tool wrote; this store refuses rather than picking
      a half to believe.
    * **the vintage** — a stored row whose ``recorded_at`` is absent,
      although the table declares it ``NOT NULL``.  A recorded origin
      without an instant is not evidence of when the pool grew, so a row
      without one is not a record this store can report; the repair is to
      the data, and the message names the world.

    Deliberately **not** a :class:`CoverageError`: the two acts differ, and
    a caller catching them together would read *the coverage count could
    not be written* where the truth is *the synthetic world could not say
    where it came from*.  Deliberately **not** a
    :class:`StratumAssignmentError` either: nothing was assigned a stratum
    here.  A ``DATABASE_URL`` this member cannot speak is also **not** this
    class — it is an address fault, with the address repair
    :class:`CoverageError` already names for the same variable, so the
    member keeps one vocabulary for one fault and this class speaks only
    about a world's provenance.
    """


class DiversityClaimError(RegimeError):
    """A regime-diverse claim was refused on the strata that hold worlds.

    Raised for the ask (a ledger carrying no readable ``covered`` figure,
    or a floor that is not a positive whole count of strata) and for the
    verdict (fewer strata hold stored worlds than the regime-diversity
    floor demands) — the two faces of feature 289's one act, and the two
    repairs the module docstring states.  Every verdict message opens
    with ``not_regime_diverse``, states the figure and names the strata
    that hold stored worlds, and states the floor, so an operator's log
    line says what the claim leaned on and how far short it fell.

    A claim that meets the floor never sees this class — the judgment
    returns ``None`` and the caller proceeds — so the verdict face has no
    ``admitted`` spelling to catch by accident: every message this class
    raises is either about the ask or is a refusal.
    """

