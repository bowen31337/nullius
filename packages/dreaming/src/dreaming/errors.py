"""The dreaming member's error vocabulary — feature 270's two faces.

One base class (:class:`DreamingError`) so a caller — the campaign loop that
closes a cycle, the replay member's writer, an operator script, a later feature
in this category — can catch every failure of the dreaming path with a single
``except``.  The subclasses split by *what the caller must do about it*, not by
which line of code raised, the discipline :mod:`bootstrap.errors`,
:mod:`nulloracle.errors` and :mod:`discovery.errors` state for their own trees.

**This member opens with two classes, and the split between them is the whole
of feature 270.**  app_spec.xml, "Dreaming Loop & Meta-Selection", feature 270:
*System rejects a replay pool mutation during a dreaming iteration, holding the
pool fixed for the cycle.*  That sentence names one **rule** — the pool does
not move while an iteration holds it — and the rule can be broken from two
sides, which is what the two classes are:

* :class:`FreezeRequestError` — the *holding* could not be asked for as the
  caller asked for it.  An iteration id that is not text, or a freeze object
  handed a database URL this member cannot speak.  Every one of these is a
  fact about the **request**: nothing was read, nothing was written, and the
  repair is to re-consider what was asked for.
* :class:`PoolFrozenError` — the pool is held fixed and it **moved anyway**,
  or something tried to move it.  Every one of these is a fact about the
  **world**: the ask was well formed, and the contradiction is between the
  statement being run (or the pool as found) and the freeze that is open.
  The repair is never to re-send a corrected ask.
* :class:`PoolTooThinError` — the pool holds fewer worlds than the ladder
  floor, so a dreaming run is refused *before it starts*.  This is a fact
  about the **pool's size**, not about a malformed ask or a moving pool; the
  repair is to grow the pool (or run fixed exploration), never to re-send the
  same run.

Folding the two together would make a caller that must react differently to
*my iteration id was a typo* and *the cycle's pool is being written into* catch
one class and re-inspect something it cannot tell apart — the failure the
workspace's error discipline names everywhere, and the reason
:class:`~discovery.errors.IllegalThemeError` and
:class:`~discovery.errors.VoidCampaignError` each insist on sitting beside the
planning error rather than under it.

**Feature 277's two classes take the same split for the revision cap.**
:class:`CapRequestError` is the *ask* face — a malformed id, figure, rung,
instant or URL, refused before anything is read or written, exactly as
:class:`FreezeRequestError` is for feature 270's asks — and
:class:`CapRecordError` is the *store* face — a database that holds no pool to
cap, or a row that will not read back — exactly as :class:`PoolFrozenError`
is for feature 270's world.  The cap's refusals deliberately translate at the
seam from the member's one spellings of the shared rules (the iteration-id
rule, the URL translation, the stamp format all live in
:mod:`dreaming.cycle`), so a caller of the cap never meets the freeze's
vocabulary for an act that held nothing; the one refusal this member mints
for a thin pool stays feature 275's, delegated, in feature 275's word.

**Feature 276's ceiling is a third sentence, and its class is its own rather
than a face of the floor's.**  §12.1's ladder has three rungs and this member
now carries all three: the floor refuses a run below 20 worlds
(:class:`PoolTooThinError`), the *schedule* answers the cap a cycle runs under
(feature 277's ``dreaming.cap``), and the *ceiling* refuses a sweep wider than
the thin rung funds (:class:`RevisionCeilingError`).  The ceiling's class sits
beside :class:`PoolTooThinError` rather than under it because the two would
otherwise be caught together and their repairs are different: a thin pool means
*grow the pool before dreaming at all*, while a too-wide sweep means *this pool
may dream — lower ``M`` to the band's cap, or grow the pool until the raise
applies*.  It is likewise not feature 277's :class:`CapRequestError`: a count
of 40 is a well-formed ask and a legal one one rung up, so nothing about it is
malformed.  The band's edges and its cap are *not* respelled here or in
``dreaming.ceiling`` — they are feature 275's floor and feature 277's
``CAPPED_SWEEP_CAP`` / ``FULL_DREAMING_WORLDS``, consumed from the modules that
state them, so the ladder has one spelling per rung.

**Feature 278's split takes the ask/store split the cap states, for the act of
splitting.**  :class:`SplitRequestError` is the *ask* face — world ids that are
not non-empty text, a pool handed with the same world twice, a rotation that is
not text, a train fraction outside ``(0, 1)``, a world asked of a predicate the
split does not hold, or no database named at all — and :class:`SplitStoreError`
is the *store* face: a database that holds no pool tables, so there is no pool
to split.  The two repairs differ exactly as the cap's do (re-consider the ask
against point at the pool the replay loop lives in), and the one refusal this
vocabulary never mints is the thin pool's: a pool below the ladder floor is
feature 275's fact, delegated to :func:`dreaming.ladder.rejects_thin_pool` in
the floor's own word, the same delegation the cap and the ceiling perform.

**Feature 281 rejects a comparison, and its two classes are the two halves of
that rejection.**  §11.0's rule — *"Raw FDR is a proportion, and proportions are
power-poor … Fix the statistic, not the ambition"* — has a refusal and a
replacement, and they fail differently: :class:`ProportionComparisonError` is
raised when the caller asked for a **difference in proportions**, whose repair
is *ask for the paired continuous statistic instead*, while
:class:`PairedComparisonError` is raised when the paired statistic **is** what
was asked for and the worlds handed to it do not pair, whose repair is
*compare the arms over the worlds that carry both*.  The first is a fact about
the **question**; the second is a fact about the **evidence**.  They are
siblings under the one base and neither is a face of the other, for the reason
every pair in this module is split: a caller that must react differently to
*your statistic is wrong* and *your worlds are wrong* cannot catch one class
and tell them apart.  Both are also deliberately not :class:`PoolTooThinError`
— feature 275's floor judges the pool against §12.1's ladder rung *before* any
comparison runs, in the floor's own word, and a pool it admits can still fail
to pair; the repairs are different (grow the pool, against compare the arms
over their shared worlds) so the classes are different.

**Feature 282 holds a family out, and its two classes take the ask/store
split the cap and the split state.**  app_spec.xml, feature 282: *System
computes leave-one-family-out transfer by holding an entire theme root out of
the pool, which returns the delta on that held-out theme.*  §4.5 makes the
metric a standing requirement (*"the only honest way to tell learned research
discipline from memorized family texture"*), and a requirement with two
halves fails in two places: :class:`TransferRequestError` is the *ask* face —
a family census that is not a mapping of non-empty world ids to non-empty
roots (a bare string refused where a mapping belongs, because Python would
iterate its characters as worlds), a theme root that is blank or one the pool
does not carry, a bare string where an arm's readings belong, one policy
named as both arms, or no database named at all — and
:class:`TransferStoreError` is the *store* face: a database that holds no
pool tables (no pool to hold a family out of), or a family census that
disagrees with the pool's membership in **either direction** — worlds the
pool holds that no family names, or worlds a family names that the pool does
not hold — because *"holding an entire theme root out of the pool"* is a
claim about the pool and at the store seam the pool is ground truth.  The
pair deliberately does not mint what the features it delegates to already
own: a retained pool below the ladder floor is feature 275's refusal,
delegated in the floor's word, and everything about the readings on the
held-out family — a world only one arm carries, a family too small to spread,
a non-finite figure — is feature 281's, delegated in the comparison's own
vocabulary, because the delta on a held-out theme *is* a paired comparison
over that theme's worlds.  No code word: feature 282's verb is *computes*, so
every refusal opens with its subject — the shape features 276's and 278's
classes state for their own code-word-free sentences.

**Feature 280 bars a winner, and its three classes split by the one thing
the caller must do about it.**  app_spec.xml, feature 280: *System rejects a
winning revision whose advantage falls below the square root of twice the
log of M scaled by score deviation.*  The ask/store pair the cap, the split
and the transfer state covers this feature's two *developer* facts —
:class:`BarRequestError` for a malformed ask (an advantage that is not a
finite real, an ``M`` that is not a whole number of one or more, a deviation
that is not strictly positive, a world count of none, a blank iteration id,
a comparison that is not a :class:`~dreaming.paired.PairedDifference`, or no
database named) and :class:`BarRecordError` for a store that holds no ``M``
to read (a database without the pool, translated at the seam from the cap's
own record class, or a cycle with no recorded cap — the *"a bar computed
over an ``M`` nobody recorded is a bar over a number nobody ran"* refusal).
But the verdict itself is a **third repair neither half can state**:
:class:`SelectionBarError` is raised when the figures were honest, the
record was there, and the answer is *no* — the winner does not survive the
selection noise of its own tournament — and the repair is *keep the
incumbent*, which the paper's ``V^{m★} ≥ V^0`` holds by construction (with
the incumbent in the candidate set, feature 273, the incumbent *is* the
argmax when nothing clears).  A caller that caught the verdict as the ask's
class would re-send the same honest figures forever; one that caught it as
the store's would re-point at a database that was fine.  The verdict carries
the module's one code (:data:`dreaming.bar.SELECTION_BAR_CODE`,
``advantage_below_bar``), minted on the ``pool_frozen`` / ``pool_too_thin``
/ ``proportion_comparison`` convention because it is the one refusal an
operator greps a deployment log for — *why did this cycle keep the
incumbent?* — while the ask and store faces open with their subjects, the
stance :class:`CapRequestError` states.  It is deliberately none of the
member's other verdicts: not :class:`PairedComparisonError` (the comparison
grounded fine; the subject is the noise of winning, not the pairing of
worlds), not :class:`RevisionCeilingError` (the sweep was legal — the
ceiling refuses it *before* it runs, the bar refuses the winner *after*),
and not :class:`CapRequestError` or :class:`CapRecordError`, which are
translated at the bar's seam for the reason every translation in this member
gives: the caller asked for a bar, and must not be told the cap could not be
recorded.

**Feature 279 rotates the split, and its two classes take the ask/store split
the cap and the split state.**  app_spec.xml, feature 279: *System rotates the
holdout split every cycle, persisting which worlds were held out per
iteration.*  The sentence has a per-cycle act and a record, and they fail in
the two places the member's other store seams fail:
:class:`HoldoutRequestError` is the *ask* face — an iteration id that is not
non-empty text (and so names no cycle to rotate for), a train fraction that
names no exact share in ``(0, 1)``, an instant that is not timezone-aware, or
a URL that names no database or one this member cannot speak — and
:class:`HoldoutRecordError` is the *store* face: a database that holds no pool
tables (no pool to hold worlds out of), or a recorded row whose stamp, worlds
or fraction will not read back.  The pair deliberately mints nothing the
features it delegates to already own: a pool below the ladder floor is feature
275's refusal, delegated through the split's judgment in the floor's own word,
and everything about the 70/30 arithmetic — the rank, the sizes, the
disjointness — is feature 278's, consumed from :mod:`dreaming.split` rather
than respelled, with its one request class translated at this seam so a caller
recording a rotation never meets the split's word for an act that split
nothing.  No code word, for the reason :class:`RevisionCeilingError` gives:
feature 279's sentence mandates none, so every refusal opens with its subject
— the cycle, the pool or the row that was wrong.

**Why :class:`PoolFrozenError` is its own class and not a borrowed one.**
Three members already read this pool and each has its own vocabulary for its
own act — :class:`~tripwires.errors.TripwireExcisionError`,
:class:`~canary.CanaryVoidError`, :class:`~bootstrap.BootstrapPoolError` — and
none of them means *the pool is held fixed*, because none of them is about the
dreaming loop's cycle.  The workspace contract is additionally that no member
imports another, so this class cannot be a subclass of one of them even if the
meaning were close.  A caller that wants every failure of this member's path
catches :class:`DreamingError`; a caller that wants to know *specifically*
that a write collided with a cycle catches :class:`PoolFrozenError` and reads
the iteration id out of the message.

**The two codes.**  :data:`dreaming.cycle.FREEZE_CODE` (``pool_frozen``) opens
every :class:`PoolFrozenError` message, so the rejection is greppable by the
one word that names it — the convention §7.3's ``heterogeneous_world``, §7.4's
``void_campaign`` and feature 241's ``illegal_theme`` already follow in this
workspace.  This module deliberately does **not** carry feature 275's
``pool_too_thin``: the ladder's floor is a precondition *on a run* (feature
275's sentence, and its own code), while this member's sentence is about a run
that is already going and must not have its pool moved underneath it.
"""

from __future__ import annotations

__all__ = [
    "BarRecordError",
    "BarRequestError",
    "CapRecordError",
    "CapRequestError",
    "DreamingError",
    "FreezeRequestError",
    "HoldoutRecordError",
    "HoldoutRequestError",
    "PairedComparisonError",
    "PoolFrozenError",
    "PoolTooThinError",
    "ProportionComparisonError",
    "RevisionCeilingError",
    "RevisionError",
    "RevisionRequestError",
    "SelectionBarError",
    "SplitRequestError",
    "SplitStoreError",
    "TransferRequestError",
    "TransferStoreError",
]


class DreamingError(Exception):
    """Base class for every failure of the dreaming loop's path."""


class FreezeRequestError(DreamingError):
    """The freeze could not be held as the caller asked for it.

    Raised before anything is read or written: an iteration id that is not
    non-empty text, an instant that is not a timezone-aware datetime, or a
    store handed a database URL this member cannot speak.  Each is a fact
    about the *request*, and the repair is to re-consider what was asked for —
    exactly as :class:`~discovery.errors.CampaignPlanningError` states for the
    campaign planner's own malformed asks, and for the same reason: the
    failure is identical however often it is retried.

    Deliberately **not** a :class:`PoolFrozenError`.  Nothing is frozen while
    this is raised — no row has been written and no iteration holds anything —
    so a caller that caught the two together would read *your ask was
    malformed* as *the pool is under a cycle right now*.
    """


class PoolFrozenError(DreamingError):
    """The replay pool was held fixed for a cycle, and it moved anyway.

    app_spec.xml, "Dreaming Loop & Meta-Selection", feature 270: *System
    rejects a replay pool mutation during a dreaming iteration, holding the
    pool fixed for the cycle.*  This is the *rejects* of that sentence, and it
    carries **three faces of the one question** — *did the pool move while an
    iteration held it?* — the shape
    :class:`~discovery.errors.IllegalThemeError` documents for its own two:

    * **A writer was refused.**  An insert, update or delete on one of the
      pool's tables was attempted while an iteration held the freeze.  This is
      the face the feature's sentence names, and it is enforced **in the
      database** — by a ``BEFORE`` trigger over the pool's tables that
      consults this member's open-freeze row — rather than by a Python
      wrapper, which is the property that makes it a rule instead of a
      convention: a raw ``sqlite3`` session, the replay member's own writer or
      a hand-run ``UPDATE`` is refused exactly as a caller that went through
      :meth:`~dreaming.cycle.CycleFreeze.guard` is.  A guard the writer could
      walk around by opening the database itself would be no guard at all.
    * **A second iteration tried to hold a pool already held.**  §12.1's loop
      runs *one* cycle at a time — the holdout rotation (feature 279) and the
      revision cap (feature 277) are per-cycle facts — so two open freezes
      would be two cycles walking one pool with neither able to say which
      scores belonged to which.  The store refuses the second with this class
      rather than silently nesting, and names the iteration that holds it.
    * **The pool was found changed when the freeze was checked.**  A freeze
      records the pool's commitment — its membership digest and its size —
      when it opens, and :meth:`~dreaming.cycle.CycleFreeze.verify` compares
      that against the pool as it stands.  A difference means the pool moved
      while it was supposed to be fixed, which is the failure the first face
      exists to prevent and which the commitment exists to *detect*: a
      trigger can be dropped, a database restored from a backup, a table
      replaced by a hand.  This face is what makes "holding the pool fixed" an
      observable claim rather than a promise.

    One class rather than three because they are one predicate read from three
    sides, and because the repair a caller makes is the same for all of them:
    **stop writing, or close the iteration.**  It is emphatically not a
    corrected re-ask — nothing about any of these statements is malformed, and
    the write a caller attempted would be perfectly legal in the next cycle,
    when no iteration is holding anything.

    Every message opens with :data:`dreaming.cycle.FREEZE_CODE`
    (``pool_frozen``), names the iteration doing the holding, and — for the
    first face — the table and the operation that was refused, so an operator
    reading a refusal can identify both ends of the collision: *which* cycle
    was walking the pool and *what* was reaching into it.
    """


class PoolTooThinError(DreamingError):
    """The pool holds fewer worlds than the ladder floor, so a dreaming run is refused.

    app_spec.xml, "Dreaming Loop & Meta-Selection", feature 275: *System
    rejects a dreaming run when the pool holds fewer than 20 worlds, which
    returns a ``pool_too_thin`` error message.*  docs/alpha-engine-prd.md
    §12.1 states the rule this class enforces, and states it as a precondition
    *on a run that has not started* rather than as a caveat on one that is
    going:

        Below 20 worlds: **do not run dreaming.** Fixed exploration; accumulate
        history.

    This is the ladder's floor, and it is a **different sentence from feature
    270's**, with a different repair — which is why it is its own class beside
    :class:`PoolFrozenError` rather than a face of it.  :class:`PoolFrozenError`
    is about a cycle that is *already running* and whose pool must not move
    underneath it (its repair is *stop writing, or close the iteration*);
    :class:`PoolTooThinError` is about a run that *has not begun* and should not
    begin, because a tournament held over so few worlds has no statistical
    power — §10.3.1's paired comparison cannot clear its bar on a handful of
    worlds, and selecting the max over ``M`` revisions scored on them is the
    multiple-testing problem one level up with nothing to average it out.  The
    repair is never to re-send the same run: it is to grow the pool, or to run
    fixed exploration and accumulate history until the pool clears the floor.

    **Why this class is a sibling and not borrowed.**  The workspace contract is
    that no member imports another, so this class cannot be a subclass of the
    pool's own :class:`~bootstrap.BootstrapPoolError` even where the meaning is
    close, and it must not be feature 270's :class:`PoolFrozenError`, whose word
    (``pool_frozen``) names a *moving* pool rather than a *thin* one — a caller
    that caught the thin-pool refusal as *the pool is held* would wait for a
    cycle that does not exist.  A caller that wants every failure of this
    member's path catches :class:`DreamingError`; a caller that wants to know
    *specifically* that the run was refused for lack of worlds catches
    :class:`PoolTooThinError` and reads the figure and the floor out of the
    message.

    Every message opens with :data:`dreaming.ladder.POOL_TOO_THIN_CODE`
    (``pool_too_thin``), states the pool's figure and the floor it fell short
    of, and names §12.1, so an operator reading a refusal can see both ends of
    the judgement: *how many worlds the pool held* and *which floor it was
    measured against*.
    """


class CapRequestError(DreamingError):
    """The revision cap could not be asked for as the caller asked for it.

    app_spec.xml, "Dreaming Loop & Meta-Selection", feature 277: *System
    persists the revision cap used per cycle, raising M to 40 once the pool
    holds 50 or more worlds.*  This is the *ask* face of that sentence: an
    iteration id that is not non-empty text, a pool figure or a ladder rung
    that is not a world count, a raise boundary below the floor it must sit
    at or above, an instant that is not timezone-aware, a URL that names no
    database or one this member cannot speak.  Every one is a fact about the
    **request**, refused before anything is read or written, and the repair
    is to re-consider what was asked for — exactly the stance
    :class:`FreezeRequestError` takes for feature 270's own malformed asks.

    Deliberately **not** a :class:`FreezeRequestError`, though the shapes it
    refuses are the member's shared ones: the id rule, the URL translation
    and the stamp format are spelled once in :mod:`dreaming.cycle` and
    *translated* into this class at the cap's seam, because a caller that
    recorded a cap and caught the freeze's request class would read *your
    hold was malformed* about an act that held nothing — the seam discipline
    the whole workspace states for error vocabularies.  And deliberately not
    a :class:`PoolTooThinError`: a pool below the ladder floor is refused by
    the ladder's own judgment in its own word, and this class never speaks
    for it.

    No code word: feature 275's ``pool_too_thin`` is mandated by its own
    sentence and feature 270's codes name pool-facts, while every refusal
    here names its subject in its first words — the shape
    :class:`FreezeRequestError` itself takes.
    """


class CapRecordError(DreamingError):
    """The store could not ground a revision cap's record.

    The world-side face of feature 277's sentence: a database that holds no
    pool tables (so there is no pool to cap, and a row written against it
    would assert a tournament over nothing), or a recorded row whose stamp
    will not read back.  Each is a fact about the **store** rather than
    about the ask — the URL and the iteration were well formed — so the
    repair is to point at the database the replay pool lives in (or migrate
    it), never to re-send the same ask.

    A sibling of :class:`PoolFrozenError` rather than a face of it, because
    the two name different worlds: *the pool is held and something tried to
    move it* (feature 270's subject, repair: stop writing or close the
    cycle) against *there is no pool here to cap* (feature 277's own fact,
    repair: point at the pool).  A caller that caught one and read it as
    the other would wait for a cycle that does not exist, or close one that
    was never open.
    """


class RevisionCeilingError(DreamingError):
    """The sweep is wider than the pool's rung of the ladder funds.

    app_spec.xml, "Dreaming Loop & Meta-Selection", feature 276: *System
    rejects a revision count above 10 while the pool holds between 20 and 50
    worlds, so the selection bar stays low.*  docs/alpha-engine-prd.md §12.1
    states the rule as the middle row of its ladder — *"20–50: dreaming with
    ``M`` capped at 8–10 so the selection bar stays low; cap policy
    complexity"* — and this class is the refusal that enforces it.

    **Why it exists, in one figure.**  Appendix B's meta-level bar is
    ``true_advantage > √(2 ln M) · σ_V / √n_worlds``, so ``M`` enters the width
    of the multiple-testing correction the *selected* revision will be judged
    against: §12.1 computes ``n > 53`` worlds at ``M = 40``, and a pool of
    20–50 is short of that by construction.  A bar at ``M = 40`` is ≈1.27× the
    bar at ``M = 10``, so an uncapped sweep on the thin rung judges its winner
    against a bar the rung cannot afford — the same overfitting §12.1 names in
    *"the dreaming loop overfits its own replay pool"*.

    **Its repair is its own, which is why it is its own class.**  *Lower ``M``
    to the band's ceiling, or grow the pool until the raise applies.*  The two
    classes a caller could otherwise catch this as both name repairs that are
    wrong here: :class:`PoolTooThinError` means *do not dream at all, grow the
    pool first* — this pool may dream, just not that widely — and
    :class:`CapRequestError` means *the ask was malformed* — a count of 40 is
    perfectly well formed, and legal one rung up where feature 277 answers it.
    Folding these together would make a caller that must react differently to
    *your sweep is too wide for this pool* and *your pool is too thin to dream
    on* catch one class and re-inspect something it cannot tell apart, which is
    the failure this member's vocabulary is split to prevent.

    **No code word, and deliberately.**  Feature 275's ``pool_too_thin`` is
    mandated by its own sentence (*"which returns a ``pool_too_thin`` error
    message"*), and feature 276's sentence mandates none: it names its subject
    in prose.  So every message here opens with its subject — the count, the
    ceiling and the band — the shape :class:`CapRequestError` states for its
    own pair, so a reader is told *what to lower* rather than handed a token to
    grep for.  The one thin-pool refusal this member mints stays feature 275's,
    delegated, in feature 275's word.
    """


class RevisionRequestError(DreamingError):
    """The revision sweep could not be asked for as the caller asked for it.

    app_spec.xml, "Dreaming Loop & Meta-Selection", feature 271: *System
    produces M revisions of the exploration policy source between iterations,
    which returns candidate modules.*  This is the *ask* face of that
    sentence: an incumbent source that is not non-empty text, a revision count
    that is not a genuine positive integer, a seed that is neither text nor an
    integer, or a parent version that is not None or non-empty text.  Every
    one is a fact about the **request**, refused before anything is produced,
    and the repair is to re-consider what was asked for — exactly the stance
    :class:`CapRequestError` takes for feature 277's asks and
    :class:`FreezeRequestError` for feature 270's.

    Deliberately **not** a :class:`RevisionError`: nothing has been produced
    while this is raised, so a caller that caught the two together would read
    *your ask was malformed* as *the policy cannot fund M distinct revisions* —
    two failures a developer repairs differently, one by fixing the call and
    the other by growing the policy's authored constants or shrinking M.  It
    is likewise not :class:`PoolTooThinError`: a pool below the ladder floor is
    feature 275's precondition, judged from the pool before the sweep is ever
    asked for, and this module opens no database and reads no pool row.

    No code word, for the reason :class:`RevisionCeilingError` gives: feature
    271's verb is *produces*, so every refusal here opens with its subject —
    the source, the count, the seed or the parent version that was wrong — and
    a reader is told *what to fix in the ask* rather than handed a token to
    grep for.
    """


class RevisionError(DreamingError):
    """The revision sweep could not be produced from the incumbent as asked.

    The *verdict* face of feature 271's sentence: a revised source that does
    not parse, or — the common case — fewer than ``M`` *distinct* candidate
    modules remaining after deduplication.  A candidate's identity is its
    ``code_hash`` (the sha256 of its source), so two revisions that jitter the
    incumbent into the same text are one candidate, and a policy whose authored
    numeric constants cannot fund ``M`` distinct perturbations names no sweep
    of that size.  This is a fact about the **production**, not the ask — the
    ask was well formed and the count was legal — so the repair is never to
    re-send the same call: it is to grow the incumbent's authored constants or
    to shrink ``M``, the developer's decision rather than a corrected ask.

    Deliberately **not** a :class:`RevisionRequestError`: a count of 40 is a
    well-formed ask and a legal one one rung up, and folding these together
    would make a caller that must react differently to *your ask was
    malformed* and *this policy cannot fund that many revisions* catch one
    class and re-inspect something it cannot tell apart, which is the failure
    this member's vocabulary is split to prevent.  It is not
    :class:`SelectionBarError` either: that verdict is *the winner did not
    survive its own tournament — keep the incumbent*, a selection outcome an
    operator greps a deployment log for, while this verdict is a developer fact
    about the candidate set the sweep was built from.

    No code word, for the reason :class:`RevisionCeilingError` and
    :class:`RevisionRequestError` give: feature 271's sentence mandates none,
    so every refusal here opens with its subject — the shortfall or the
    unparseable source — and a reader is told *what the production could not
    do* rather than handed a token to grep for.
    """


class SplitRequestError(DreamingError):
    """The split could not be asked for as the caller asked for it.

    app_spec.xml, "Dreaming Loop & Meta-Selection", feature 278: *System splits
    the pool 70 to 30 into train and holdout, which returns selection on train
    with reporting on holdout.*  This is the *ask* face of that sentence: world
    ids that are not non-empty text, a pool handed with one world twice, a bare
    string where the pool's worlds belong (it names one world, not many), a
    rotation that is not text, a train fraction outside ``(0, 1)`` or one a
    rational reading cannot ground, a world asked of a predicate the split does
    not hold, or no database named for the pool to be read from.  Every one is
    a fact about the **request**, refused before anything is split, and the
    repair is to re-consider what was asked for — the stance
    :class:`FreezeRequestError` takes for feature 270's asks and
    :class:`CapRequestError` for feature 277's.

    Deliberately **not** a :class:`FreezeRequestError`, though one of its
    refusals is translated from the member's one spelling of what a
    ``sqlite:///`` URL names (:func:`dreaming.cycle.sqlite_path`): a caller
    that split a pool and caught the freeze's request class would read *your
    hold was malformed* about an act that held nothing — the seam discipline
    the whole workspace states for error vocabularies, applied inside the
    member exactly as ``dreaming.cap`` applies it.  And deliberately not a
    :class:`PoolTooThinError`: a pool below the ladder floor is feature 275's
    fact, refused by the ladder's own judgment in its own word, and this class
    never speaks for it.

    No code word, for the reason :class:`RevisionCeilingError` gives: feature
    278's sentence mandates none, so every message opens with its subject —
    the worlds, the rotation or the fraction that was wrong — and a reader is
    told *what to fix* rather than handed a token to grep for.
    """


class SplitStoreError(DreamingError):
    """The store could not ground a train/holdout split.

    The store-side face of feature 278's sentence: a database that holds no
    ``replay_score`` and no ``bootstrap_world`` table, so there is no pool
    here to split — a split written over it would partition worlds that do not
    exist while the cycle believed it had a train half to select on and a
    holdout half to report on.  A fact about the **store** rather than the ask
    (the URL was well formed and named a database), so the repair is to point
    ``DATABASE_URL`` at the database the replay pool lives in, or migrate it —
    never to re-send the same ask.

    A sibling of :class:`PoolFrozenError` and :class:`CapRecordError` rather
    than a face of either, because the three name different worlds: *the pool
    is held and something tried to move it* (feature 270), *there is no pool
    here to cap* (feature 277) and *there is no pool here to split* (feature
    278).  A caller that caught one and read it as another would wait for a
    cycle that does not exist, or close one that was never open, or re-send a
    split against a database that still holds nothing to split.
    """


class ProportionComparisonError(DreamingError):
    """A policy comparison was asked for as a difference in proportions.

    app_spec.xml, "Dreaming Loop & Meta-Selection", feature 281: *System
    rejects a difference-in-proportions comparison, using a paired continuous
    statistic over the same worlds instead.*  This is the **rejects** of that
    sentence, and it is the half of the feature that comes first: §11.0 of
    docs/alpha-engine-prd.md states the rule in its own opening sentence —
    *"Raw FDR is a proportion, and proportions are power-poor"* — and
    docs/nullius-tech-architecture.md §10.3.1 states it as the reason the
    comparison is a paired IR test at all:

        Policy comparison uses a **paired** continuous statistic — OOS IR of
        the committed pick, same policy pair on the same worlds — not a
        difference in proportions.  A proportion test for ``0.30 → 0.21``
        needs ~364 independent commits per arm before clustering; the paired
        IR test needs ~56 worlds.

    **A committed-pick outcome is binary, and that is exactly the trap.**  The
    quantity §11.0 names — the false discovery *rate* — is a proportion: a
    count of committed picks that were right over the picks committed.  Two
    arms' rates are therefore two proportions, and testing the difference
    between them is the single most natural thing to reach for, which is why
    the sentence in the spec exists at all.  It is also unbuildable here: 364
    independent commits per arm at 80% power, before the design effect that
    clustering replays by world adds.  The §C5 loop runs ``M`` revisions
    against a pool of worlds, not thousands of independent commits, so a
    proportion test on this pool is a test with no power wearing a
    conventional name — *"that test is not buildable at this scale"*.

    **The repair is not to ask again, and it is not to widen the pool either.**
    §11.0's instruction is *"Fix the statistic, not the ambition"*: the
    comparison is a paired continuous statistic over the same worlds — the
    out-of-sample IR of the committed pick, continuous and zero in expectation
    under the null, differenced world by world.  So a caller that meets this
    class has asked the wrong *question*, and the answer is
    :func:`dreaming.paired.paired_ir_difference` over the same pool it was
    already holding — never more worlds, which would be paying the pool's
    price for a statistic that stays under-powered either way.  That is why it
    is its own class and not a face of :class:`PoolTooThinError`, whose repair
    (*grow the pool*) is the wrong action here, and not a face of
    :class:`PairedComparisonError`, which is the *other* half of feature 281:
    it is raised when the comparison **is** the right statistic and the pool
    it was handed cannot ground one.  A caller that caught the two together
    would read *your statistic is wrong* as *your worlds are wrong*.

    Every message opens with :data:`dreaming.paired.PROPORTION_CODE`
    (``proportion_comparison``), states the figure the caller named and what
    §11.0's arithmetic says that figure needs, and names the paired
    alternative — so an operator reading the refusal sees both ends of the
    judgement: *what was asked for* and *what to ask for instead*.
    """


class PairedComparisonError(DreamingError):
    """A paired comparison could not be grounded on the worlds it was handed.

    The second half of feature 281's sentence, and the point of *"over the
    same worlds"*: the comparison is paired, so it needs worlds that were
    **paired** — the same world carrying a figure for each arm of the
    comparison.  §10.3.1 spells the seam as *"same policy pair on the same
    worlds"*, and a difference of paired figures is only defined where both
    figures exist.

    Three ways the pool fails that, and the repair is the same for all three —
    *compare the arms over the worlds that carry both* — which is why this is
    one class and not three:

    * **a world carries only one arm's figure.**  The pair is incomplete: the
      world was replayed against one policy and not the other, so it
      contributes no difference.  Including it would mean inventing the
      missing arm; averaging it in as a zero difference would be the same
      invention spelled less visibly.
    * **the two arms' world sets are not the same worlds at all.**  Nothing is
      paired by construction, and the difference is between two populations
      rather than between two readings of one population — which is the
      *unpaired* comparison §11.0 rejects, arriving through the arithmetic
      rather than through the caller's request.
    * **fewer than two paired worlds survive.**  One world is one difference,
      and one difference has no spread; the sample deviation is a division by
      ``n − 1`` and at ``n = 1`` there is no deviation to divide by.  Reporting
      a t figure off it would mean reporting a spread this pool does not have.

    **Deliberately not a face of :class:`ProportionComparisonError`.**  That
    class's repair is *the statistic is the wrong one*; this class's repair is
    *the statistic is right and these worlds cannot ground it*, which the
    caller reaches by comparing the arms over their shared worlds — the pool's
    other worlds are not the fix, and a caller that caught the two together
    would go looking for a better statistic when its worlds were the problem.
    Nor is it a :class:`PoolTooThinError`: feature 275's floor judges the
    *pool* against §12.1's ladder rung, while this refusal is about the
    **overlap** of two arms within a pool the floor has already admitted — the
    thin-pool refusal fires before any comparison, in the floor's own word,
    and this class never speaks for it.

    Refusals open with :data:`dreaming.paired.PAIRED_CODE` (``unpaired_worlds``)
    — the greppable-code convention ``pool_frozen``, ``pool_too_thin``,
    ``illegal_theme`` and ``full_history_fit`` already follow in this workspace
    — and name the arm's world set, so an operator can see *which* worlds failed
    to pair rather than only that pairing failed.
    """


class TransferRequestError(DreamingError):
    """A leave-one-family-out transfer could not be asked for as asked.

    app_spec.xml, "Dreaming Loop & Meta-Selection", feature 282: *System
    computes leave-one-family-out transfer by holding an entire theme root out
    of the pool, which returns the delta on that held-out theme.*  This is the
    *ask* face of that sentence: a family census that is not a mapping of
    non-empty world ids to non-empty theme roots (a bare string refused where
    a mapping belongs — Python would iterate its *characters*, and a pool
    handed as one world's id would silently become as many one-character
    worlds as it has letters), a theme root that is blank or one the pool
    does not carry (a root with no worlds removes nothing, so the delta on
    it would be a figure over no evidence that still looked like a
    measurement), a bare string where an arm's readings belong, one policy
    named as both arms (every difference exactly zero, reporting no transfer
    while looking like a measurement of it), or no database named for the
    pool to be read from.  Every one is a fact about the **request**,
    refused before anything is read or compared, and the repair is to
    re-consider what was asked for — the stance
    :class:`FreezeRequestError` takes for feature 270's asks,
    :class:`CapRequestError` for feature 277's and
    :class:`SplitRequestError` for feature 278's.

    Deliberately **not** a :class:`FreezeRequestError`, though one of its
    refusals is translated from the member's one spelling of what a
    ``sqlite:///`` URL names (:func:`dreaming.cycle.sqlite_path`): a caller
    that took a transfer and caught the freeze's request class would read
    *your hold was malformed* about an act that held nothing — the seam
    discipline the whole workspace states for error vocabularies.  And
    deliberately neither :class:`PoolTooThinError` nor
    :class:`PairedComparisonError`: the retained pool's size is the
    ladder's judgment, delegated to
    :func:`dreaming.ladder.rejects_thin_pool` in the floor's own word, and
    the readings on the held-out family are feature 281's, delegated to
    :func:`dreaming.paired.paired_ir_difference` in the comparison's own
    vocabulary — this class never speaks for either.

    No code word, for the reason :class:`RevisionCeilingError` gives:
    feature 282's verb is *computes* and mandates none, so every message
    opens with its subject — the families, the root or the arm that was
    wrong — and a reader is told *what to fix* rather than handed a token
    to grep for.
    """


class TransferStoreError(DreamingError):
    """The store could not ground a leave-one-family-out transfer.

    The store-side face of feature 282's sentence, and it is where the
    feature's own claim is checked: *"holding an entire theme root out of
    the pool"* is a claim **about the pool**, and at the store seam the pool
    is ground truth.  Two ways the store refuses to ground it, both facts
    about the **store** rather than the ask (the URL was well formed, the
    root was named, the arms were two policies):

    * **the database holds no pool tables** — no ``replay_score`` and no
      ``bootstrap_world``, so there is no pool here to hold a family out of,
      and a transfer written over it would report a delta on a family of
      worlds that were never read while nothing in the figure looked wrong.
    * **the family census disagrees with the pool's membership, in either
      direction.**  A census that misses pool worlds leaves them in no
      family — neither held out nor retained, invisible to a partition that
      claims to be *of the pool*, silently free to sit under a selection
      that believed their family was gone.  A census naming worlds the
      store does not hold grounds the figure partly on worlds that do not
      exist.  The refusal names the disagreement, because an operator
      holding a stale census should see the drift rather than a refusal
      about statistics.

    The repair is to point ``DATABASE_URL`` at the database the replay pool
    lives in (or migrate it), and to re-read the pool's families for every
    world it holds — never to re-send the same ask against the same stale
    census.  A sibling of :class:`PoolFrozenError`, :class:`CapRecordError`
    and :class:`SplitStoreError` rather than a face of any of them, because
    the four name different worlds: *the pool is held and something tried to
    move it* (feature 270), *there is no pool here to cap* (feature 277),
    *there is no pool here to split* (feature 278) and *there is no pool
    here — or no honest census of one — to hold a family out of* (feature
    282).
    """


class BarRequestError(DreamingError):
    """The selection bar could not be asked for as the caller asked for it.

    app_spec.xml, "Dreaming Loop & Meta-Selection", feature 280: *System
    rejects a winning revision whose advantage falls below the square root
    of twice the log of M scaled by score deviation.*  This is the *ask*
    face of that sentence: an advantage that is not a finite real (a ``nan``
    compared against the bar answers neither below nor above it), an ``M``
    that is not a whole number of one or more (the maximum of no scores is
    a figure no tournament produced), a score deviation that is not
    strictly positive (the degenerate pool the paired statistic refuses in
    its own word), a world count of none (a standard error over no worlds
    is a division by exactly nothing), a blank iteration id, a comparison
    that is not a :class:`~dreaming.paired.PairedDifference` (the
    advantage, the deviation and the world count are three figures one
    comparison already carries, and three loose numbers could come from
    three different measurements), or no database named for the record to
    be read from.  Every one is a fact about the **request**, refused
    before anything is read or computed, and the repair is to re-consider
    what was asked for — the stance :class:`FreezeRequestError` takes for
    feature 270's asks and the cap, split and transfer pairs take for
    their own.

    Deliberately **not** a :class:`CapRequestError`, though the store seam
    refuses a missing URL by translating the cap's own request class: the
    caller asked for a bar, and must not be told the cap could not be
    *recorded* about an act that recorded nothing — the seam discipline the
    whole workspace states for error vocabularies, applied inside the
    member exactly as ``dreaming.cap`` and ``dreaming.split`` apply it.

    No code word, for the reason :class:`CapRequestError` gives: the ask's
    refusals are developer facts, and every message opens with its subject
    so a reader is told *what to fix* rather than handed a token to grep
    for.
    """


class BarRecordError(DreamingError):
    """The store could not ground a selection bar's ``M``.

    The store-side face of feature 280's sentence, and it is where the
    feature's own claim is checked: Appendix B's bar reads ``M`` back from
    feature 277's record, so the record has to be there.  Two ways the
    store refuses to ground it, both facts about the **store** rather than
    the ask (the URL was well formed, the iteration named a cycle, the
    comparison was taken):

    * **the database holds no pool tables** — translated at the seam from
      the cap's own record class, because a store without the pool holds
      no dreaming cycles and so no caps to read, and the caller that asked
      for a bar must not be told a cap could not be recorded.
    * **no recorded cap names the iteration** — the refusal the cap's own
      module states the reason for in advance: *"a bar computed over an
      ``M`` nobody recorded is a bar over a number nobody ran."*  A bar
      guessed at an unrecorded ``M`` would mis-state the multiple-testing
      width by exactly the factor the bar exists to control.

    The repair is to point ``DATABASE_URL`` at the database the replay
    pool lives in (or migrate it), and to record the cycle's cap
    (:func:`dreaming.cap.record_cycle_cap`) before judging its winner —
    never to re-send the same ask against a store that still holds nothing
    to read.  A sibling of :class:`CapRecordError` and
    :class:`SplitStoreError` rather than a face of either, because the
    three name different worlds: *there is no pool here to cap* (feature
    277), *there is no pool here to split* (feature 278) and *there is no
    recorded ``M`` here to bar a winner at* (feature 280) — a caller that
    caught one and read it as another would migrate a database that held
    the pool, or record caps for a cycle whose winner had already been
    judged at a guessed figure.
    """


class SelectionBarError(DreamingError):
    """A winning revision's advantage did not survive its selection noise.

    app_spec.xml, "Dreaming Loop & Meta-Selection", feature 280: *System
    rejects a winning revision whose advantage falls below the square root
    of twice the log of M scaled by score deviation.*  docs/alpha-engine-prd.md
    §12.1 states the rule, and states it as the answer to the question the
    loop's own last clause raises — the argmax is a **max**, and a max is
    biased:

        the selected policy's true advantage survives selection noise only
        when  true_advantage > √(2 ln M) · σ_V / √n_worlds

    The expected maximum of ``M`` scores that carry no advantage at all is
    √(2 ln M) standard errors (§7.3's null max-Sharpe bar, *"the same
    multiple-testing problem one level up"*), so a winner at or below the
    bar is indistinguishable from the best of ``M`` nulls, and persisting
    it would enshrine selection noise as improvement while every figure in
    the record looked like a measurement.

    **Its repair is its own, which is why it is its own class.**  *Keep the
    incumbent* — the paper's ``V^{m★} ≥ V^0`` holds by construction once
    the incumbent is in the candidate set (feature 273): when nothing
    clears, the incumbent *is* the argmax.  The classes a caller could
    otherwise catch this as all name repairs that are wrong here:
    :class:`BarRequestError` means *re-send the figures* (they were
    honest), :class:`BarRecordError` means *point at the store* (it held
    the record), :class:`PairedComparisonError` means *the worlds will not
    pair* (they paired), and :class:`RevisionCeilingError` means *lower
    ``M`` before running* (the sweep already ran, legally — the ceiling
    refuses the sweep, this refuses the winner).  A caller that must react
    differently to *your figures were malformed* and *the tournament's best
    was noise* cannot catch one class and tell them apart.

    Every message opens with :data:`dreaming.bar.SELECTION_BAR_CODE`
    (``advantage_below_bar``), states the advantage, the bar and the three
    figures behind it, and names the repair — so an operator reading a
    deployment log sees both ends of the judgement: *what the winner
    earned* and *what surviving selection noise costs*.
    """


class HoldoutRequestError(DreamingError):
    """A cycle's holdout rotation could not be asked for as the caller asked.

    app_spec.xml, "Dreaming Loop & Meta-Selection", feature 279: *System
    rotates the holdout split every cycle, persisting which worlds were held
    out per iteration.*  This is the *ask* face of that sentence: an
    iteration id that is not non-empty text (a cycle that cannot be named
    cannot be rotated for — its holdout would be a record attributed to no
    cycle, and an operator reading the history could not say which
    tournament the worlds were held out of), a train fraction that names no
    exact share in ``(0, 1)`` (translated at the seam from the split's one
    spelling of the rule, because the 70/30 arithmetic is feature 278's), an
    instant that is not a timezone-aware datetime, or a URL that names no
    database or one this member cannot speak.  Every one is a fact about the
    **request**, refused before anything is read or written, and the repair
    is to re-consider what was asked for — the stance
    :class:`FreezeRequestError` takes for feature 270's asks and the cap,
    split, transfer and bar pairs take for their own.

    Deliberately **not** a :class:`FreezeRequestError` or a
    :class:`SplitRequestError`, though the rules it refuses are the member's
    shared ones: the iteration-id rule and the URL translation are spelled
    once in :mod:`dreaming.cycle` and the fraction rule once in
    :mod:`dreaming.split`, both *translated* into this class at the
    rotation's seam, because a caller that recorded a rotation and caught
    another feature's word would read *your hold was malformed* or *your
    split was malformed* about an act that held and split nothing — the seam
    discipline the whole workspace states for error vocabularies.  And
    deliberately not a :class:`PoolTooThinError`: a pool below the ladder
    floor is feature 275's fact, refused by the split's judgment in the
    floor's own word, and this class never speaks for it.

    No code word, for the reason :class:`CapRequestError` gives: feature
    279's sentence mandates none, so every message opens with its subject —
    the cycle, the fraction or the instant that was wrong — and a reader is
    told *what to fix* rather than handed a token to grep for.
    """


class HoldoutRecordError(DreamingError):
    """The store could not ground a cycle's holdout record.

    The store-side face of feature 279's sentence, and it is where the
    feature's own claim is checked: *"persisting which worlds were held out
    per iteration"* is a claim **about the pool** — the holdout is a share of
    the pool's worlds — and at the store seam the pool is ground truth.  Two
    ways the store refuses to ground it, both facts about the **store**
    rather than the ask (the URL was well formed, the iteration named a
    cycle, the fraction named a share):

    * **the database holds no pool tables** — no ``replay_score`` and no
      ``bootstrap_world``, so there is no pool here to hold worlds out of,
      and a row written against it would name worlds that were never read
      while the cycle believed its reporting half existed.  Refused *before*
      the record's table is created, so a refused record leaves no trace.
    * **a recorded row will not read back** — a stamp that is not the
      member's ISO-8601, a holdout half that is not a list of non-empty
      world ids, or a fraction that names no exact share: each is a value
      this member never writes, arrived by a hand, and a record that
      answered it would report a holdout nobody took.

    The repair is to point ``DATABASE_URL`` at the database the replay pool
    lives in (or migrate it), never to re-send the same ask against a store
    that still holds nothing to hold out of.  A sibling of
    :class:`PoolFrozenError`, :class:`CapRecordError`,
    :class:`SplitStoreError` and :class:`BarRecordError` rather than a face
    of any of them, because the five name different worlds: *the pool is
    held and something tried to move it* (feature 270), *there is no pool
    here to cap* (feature 277), *there is no pool here to split* (feature
    278), *there is no recorded ``M`` here to bar a winner at* (feature 280)
    and *there is no pool here — or no readable row — to hold worlds out
    of* (feature 279).
    """
