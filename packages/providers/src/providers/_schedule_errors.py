"""The failure modes of scheduling a depth campaign — feature 202.

app_spec.xml, "LLM Provider Tiering & Agent Pinning", feature 202: *System
schedules depth campaigns outside a configured peak pricing window,
persisting the chosen window with each run.*  This module is the vocabulary
of that refusal, and it is a **fourth base class** in this package — one
that deliberately shares no ancestor with
:class:`providers.ProviderError`, :class:`providers.ModelPinError` or
:class:`providers.DepthModelError`, for the same reason those three share
none with each other: a caller's ``except`` clause answers one question,
and the four questions are different ones.

* :class:`~providers.ProviderError` answers *did the model call work?* —
  the seam's contract, violated by a provider that answered wrong.
* :class:`~providers.ModelPinError` answers *is this node's authoring
  record pinnable?* — a record that cannot be read as a model identity.
* :class:`~providers.DepthModelError` answers *may this model serve the
  depth role?* — a selection a deployment makes **before** any call is
  placed and any node is authored.
* :class:`DepthScheduleError` answers *when may this campaign's depth runs
  happen, and what window was chosen for them?* — a scheduling that found
  no legal window, named a campaign nobody planned, or re-scheduled a run
  that was already scheduled under a different window.

A scheduling refused here has not placed a call, so it is not the provider
contract that failed; it pins no node, so there is no authoring record to
read; and it selects no model, so no depth-role criterion was missed.  It
is the campaign's *time* that could not be decided, and folding it under
any of the other three bases would make every ``except`` of that base
answer a question it never asked — a deployment catching
``DepthModelError`` to learn its cheap tier was refused would instead be
told a campaign id it never asked about was unknown, which is the collapse
each of this package's taxonomies refuses in its own docstring.

The base is also raised *directly*, for the failures no subclass
describes: a peak window whose ends are not minute-granular UTC times of
day, a run length that is not a positive whole number of minutes, a
"scheduling instant" that names no instant, a stored row whose window
overlaps the very peaks the row itself records.  These are malformed
*descriptions* rather than failed *schedulings*, and the move is the one
:class:`providers.DepthModelError` makes for a blank model name and
:class:`providers.ModelPinError` makes for an unusable store URL: a
contract violation that is genuinely none of the named cases has no
subclass to wear, and minting one class per call site is how a taxonomy
stops describing anything.

The three refusals, and why there are exactly three
---------------------------------------------------

The feature's sentence names **one act** — *schedule the campaign outside
the configured peak window* — and an act with a premise, an arithmetic and
a persistence step fails in as many ways as it has steps.  Three, then:

* :class:`NoOffPeakWindowError` — the arithmetic failed.  §14.2's second
  free lever is *"DeepSeek prices by time of day — peak is 01:00–04:00 and
  06:00–10:00 UTC, off-peak is 50% lower. Schedule campaigns outside those
  windows."*, and a campaign whose expected run length exceeds the largest
  off-peak gap on that card has no window to be scheduled into: the whole
  premise of the lever is that the run fits where the pricing is cheap,
  and a run that cannot fit is not a run this lever can halve.  The
  refusal names the largest gap, because that is the number the caller's
  duration has to come under and the one the repair — a shorter declared
  run, or a card whose peaks leave a wider gap — turns on.

* :class:`UnknownCampaignError` — the premise failed.  The store schedules
  *runs of a campaign*, and a campaign is a row
  :func:`discovery.create_campaign` planned before any node was expanded
  (feature 232, the writer eight stores defer to); a window scheduled for
  an id no campaign row holds is a run that will never happen, persisted
  beside campaigns that did.  The refusal is the same one the
  null-oracle's seven stores make for a campaign id their table does not
  hold, from the other side of the same seam.

* :class:`RunWindowConflictError` — the persistence step found a decision
  already made.  One campaign is one run, and the row records the window
  that run was scheduled into; a second scheduling of the same campaign
  that names a *different* window is two schedules wearing one campaign,
  the same refusal :class:`~discovery.errors.CampaignOrderError` makes for
  a re-issued plan that disagrees with the stored row, and for the same
  reason: the stored decision is the fact, and the repair is to read it,
  not to move it.

Stdlib-only, like the rest of this tree: these errors describe a
scheduling decision over facts a deployment states about a rate card, and
nothing here dials a provider, reads a price list, or imports an SDK.
"""

from __future__ import annotations

__all__ = [
    "DepthScheduleError",
    "NoOffPeakWindowError",
    "RunWindowConflictError",
    "UnknownCampaignError",
]


class DepthScheduleError(Exception):
    """Base of the scheduling taxonomy — a depth run's window could not be decided.

    One base class so a deployment's campaign launcher, its scheduler and a
    suite can catch every failure of feature 202's sentence — a duration
    that fits no off-peak gap, a campaign nobody planned, a run already
    scheduled under a different window, a peak window that is not a
    minute-granular UTC time of day — with a single ``except``, the way
    :class:`providers.ProviderError` gives the call seam one handle,
    :class:`providers.ModelPinError` gives the authoring record one and
    :class:`providers.DepthModelError` gives the depth-role selection one.
    The base is deliberately unrelated to all three: deciding *when* a
    campaign's runs happen is not a call that failed, not a node that
    cannot be pinned, and not a model that was refused a role, and a
    caller catching any of those must not have this answered in their
    place.

    Also raised directly for the malformations no subclass describes — a
    peak window carrying seconds, a run length of ninety seconds, a naive
    scheduling instant — on the grounds the module docstring gives: those
    are bad *descriptions* rather than failed *schedulings*, and the
    taxonomy splits by question, not by call site.
    """


class NoOffPeakWindowError(DepthScheduleError):
    """A run length that fits no gap outside the configured peak windows.

    §14.2's second free lever is time-of-day pricing: *"DeepSeek prices by
    time of day — peak is 01:00–04:00 and 06:00–10:00 UTC, off-peak is 50%
    lower. Schedule campaigns outside those windows."*  On that card the
    off-peak day is 04:00–06:00 and 10:00–01:00 — a two-hour gap and a
    fifteen-hour one — and a campaign whose declared run length exceeds
    the largest gap cannot be scheduled outside peak at all.  Raised by
    :func:`providers.choose_run_window` and by
    :meth:`providers.DepthRunWindows.schedule`, naming the largest gap the
    configured windows leave, because that is the number the duration has
    to come under and the one the repair turns on.

    The refusal is about the *pairing* of a duration with a rate card, not
    about either alone: a twenty-hour campaign is a fine campaign on a
    card that is flat by time of day, and the 01:00–04:00/06:00–10:00 card
    is a fine card for a run that fits its fifteen-hour gap.  A caller
    meeting this refusal shortens the declared run, re-configures against
    a card whose peaks leave a wider gap, or accepts the peak rate — the
    one thing it cannot do is persist a window the card contradicts.
    """


class UnknownCampaignError(DepthScheduleError):
    """A campaign id the campaign table does not hold, offered for scheduling.

    The store schedules *runs of a campaign*, and a campaign is a planned
    row: feature 232's record, created before any node is expanded, is the
    row every reader of a campaign joins by id.  Scheduling a run for an id
    no row holds would persist a window beside campaigns that exist, for a
    run that will never happen — the same refusal the null-oracle's seven
    stores make from the other side of the seam, each in as many words,
    and the one :meth:`providers.DepthRunWindows.schedule` makes here.
    Raised for an id the ``campaign`` table does not hold, and for a
    database with no ``campaign`` table at all, which is a database where
    no campaign has ever been planned and therefore a special case of the
    same fact rather than a different one.

    The repair is the campaign record, not the id: plan the campaign
    (:func:`discovery.create_campaign`) first, then schedule its runs.
    """


class RunWindowConflictError(DepthScheduleError):
    """A campaign already scheduled under a different window.

    One campaign is one run, and the ``depth_run_window`` row *is* the
    scheduling decision — the chosen window, the peak windows it was
    chosen against, and the instant the choice was made.  Re-issuing the
    identical scheduling returns that stored decision, exactly as
    re-issuing an identical campaign plan returns the stored record; a
    second scheduling that names a *different* window — a shorter declared
    run, a card whose peaks moved — is not an update but two schedules
    wearing one campaign, and the stored decision is the fact.  Raised by
    :meth:`providers.DepthRunWindows.schedule`, naming both windows, the
    same shape :class:`~providers.ModelPinConflictError` gives a node
    pinned under a different triple and for the same reason: the caller
    learns which value is stored and which it asked for, because that is
    the difference between an actionable refusal and a complaint.

    The repair is to read the stored window (:meth:`.DepthRunWindows.get`)
    or to plan the next run under its own campaign id — not to move a
    decision a run already carries.
    """
