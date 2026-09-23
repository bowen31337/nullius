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
    "CapRecordError",
    "CapRequestError",
    "DreamingError",
    "FreezeRequestError",
    "PoolFrozenError",
    "PoolTooThinError",
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
