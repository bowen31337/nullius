"""The failure modes of the depth role's cache economics — feature 200.

app_spec.xml, "LLM Provider Tiering & Agent Pinning", feature 200: *System
persists the measured cache hit rate per campaign, because the depth model
is selected on cache-hit input price rather than list price.*  This module
is the vocabulary of that refusal, and it is a **sixth base class** in this
package — one that deliberately shares no ancestor with
:class:`providers.ProviderError`, :class:`providers.ModelPinError`,
:class:`providers.DepthModelError`, :class:`providers.DepthScheduleError`
or :class:`providers.BatchRoutingError`, for the same reason those five
share none with each other: a caller's ``except`` clause answers one
question, and the six questions are different ones.

* :class:`~providers.ProviderError` answers *did the model call work?* —
  the seam's contract, violated by a provider that answered wrong.
* :class:`~providers.ModelPinError` answers *is this node's authoring
  record pinnable?* — a record that cannot be read as a model identity.
* :class:`~providers.DepthModelError` answers *may this model serve the
  depth role?* — a selection a deployment makes **before** any call is
  placed and any node is authored.
* :class:`~providers.DepthScheduleError` answers *when may this
  campaign's depth runs happen?* — a scheduling that found no legal
  window, named a campaign nobody planned, or re-scheduled a run already
  scheduled under a different window.
* :class:`~providers.BatchRoutingError` answers *which endpoint does
  this call go to?* — a routing whose serving provider the card does not
  describe.
* :class:`DepthCacheError` answers *what does the depth role's input
  cost on the axis it is actually spent on, and what rate did this
  campaign's calls measure there?* — a selection asked to rank candidates
  a card prices by name, a measurement offered for a campaign nobody
  planned, or a re-measurement that contradicts the row it would
  overwrite.

A cache economics refusal has not placed a call (so it is not the provider
contract that failed), pins no node (so there is no authoring record to
read), gates no window and times no run (so no context bar or scheduling
was missed), and routes no endpoint.  It is the campaign's *money* that
could not be decided or accounted, and folding it under any of the other
five bases would make every ``except`` of that base answer a question it
never asked — a deployment catching ``DepthModelError`` to learn its
cheap tier was refused would instead be told a campaign id it never asked
about carried a different rate than the one stored, which is the collapse
each of this package's taxonomies refuses in its own docstring.

The base is also raised *directly*, for the failures no subclass
describes: a card whose price is not a finite non-negative number, a
cache-hit price above the list input price it discounts, a usage stream
that is not the token accounting feature 192 normalizes, a usage whose
cache-read count exceeds its own input count, a measurement of no calls.
These are malformed *descriptions* rather than failed *economics*, and
the move is the one :class:`providers.DepthScheduleError` makes for a
peak window carrying seconds and :class:`providers.DepthModelError`
makes for a blank model name: a contract violation that is genuinely
none of the named cases has no subclass to wear, and minting one class
per call site is how a taxonomy stops describing anything.

The three refusals, and why there are exactly three
---------------------------------------------------

The feature's sentence names **one act** on each side of its *because* —
*persist the measured rate*, on the side of the campaign, and *select on
cache-hit input price*, on the side of the model — and each act has one
way its premise can fail and one way its persistence can find a decision
already made:

* :class:`UnpricedModelError` — **the selection's premise failed.**  §14.1
  is an instruction, not an observation: *"Select the depth model on
  cache-hit price, not list price."*  A selection can only rank
  candidates on a price that is *stated*, so a candidate the card does
  not price is refused by name rather than silently skipped — because
  the alternative a silent skip invites is exactly the failure the
  feature exists to prevent: falling back to the list price, the number
  every rate card states and §14.1's own comparison shows to answer the
  wrong question (a model 20% cheaper on the list can be 4× dearer on
  the hit).  The refusal names the model and the card it asked for, the
  same shape :class:`~providers.UnknownProviderError` gives feature
  201's routing and for the same reason: a gap in the card is a
  configuration repair, not a routing — or here, a selection — to be
  guessed around.

* :class:`UnplannedCampaignError` — **the store's premise failed.**  The
  store measures *a campaign's* calls, and a campaign is a planned row —
  feature 232's record, created before any node is expanded, is the row
  every reader of a campaign joins by id.  A rate persisted for an id no
  campaign row holds is an accounting for calls that were never placed,
  persisted beside campaigns that placed them.  The refusal is the same
  fact :class:`~providers.UnknownCampaignError` states for feature
  202's scheduling — the campaign table does not hold this id — spelled
  for this feature's base rather than shared with the scheduler's,
  because a caller catching ``DepthCacheError`` to learn its measurement
  was refused must not have a scheduling refusal answered in its place,
  and the taxonomy splits by question even where the premise is the same
  one.

* :class:`CacheRateConflictError` — **the persistence found a
  measurement already made.**  One campaign is one run of the discovery
  loop (§5), and its calls are what they are: the token totals the row
  holds are the campaign's own accounting, re-derivable from the
  completions that served it and from nothing else.  Re-issuing the
  identical measurement returns the stored record, exactly as re-issuing
  an identical scheduling returns the stored window; a second
  measurement naming *different* totals is not an update but a
  contradiction — the same campaign cannot have hit cache at two rates —
  and the stored row is the fact.  The refusal names both totals and
  both rates, the same shape
  :class:`~providers.RunWindowConflictError` and
  :class:`~providers.ModelPinConflictError` give their own conflicts and
  for the same reason: the caller learns which value is stored and which
  it asked for, because that is the difference between an actionable
  refusal and a complaint.

Stdlib-only, like the rest of this tree: these errors describe a
selection over prices a deployment states and a measurement over token
counts feature 192's completions already carry, and nothing here dials a
provider, reads a price list, or imports an SDK.
"""

from __future__ import annotations

__all__ = [
    "CacheRateConflictError",
    "DepthCacheError",
    "UnplannedCampaignError",
    "UnpricedModelError",
]


class DepthCacheError(Exception):
    """Base of the cache-economics taxonomy — the depth role's money could not be decided.

    One base class so a deployment's model selector, its campaign
    accountant and a suite can catch every failure of feature 200's
    sentence — a candidate the card does not price, a campaign nobody
    planned offered for measurement, a re-measurement that contradicts
    the stored row, a price that is not a finite number — with a single
    ``except``, the way :class:`providers.ProviderError` gives the call
    seam one handle, :class:`providers.DepthModelError` gives the
    depth-role gate one and :class:`providers.DepthScheduleError` gives
    the run-window store one.  The base is deliberately unrelated to all
    five of the others: selecting a model on its cache-hit economics is
    not a call that failed, not a node that cannot be pinned, not a
    window that was too small, and not an endpoint that went unchosen,
    and a caller catching any of those must not have this answered in
    their place.

    Also raised directly for the malformations no subclass describes — a
    negative or non-finite price, a cache-hit price above the list price
    it discounts, a measurement handed a stream that is not feature
    192's token accounting — on the grounds the module docstring gives:
    those are bad *descriptions* rather than failed *economics*, and the
    taxonomy splits by question, not by call site.
    """


class UnpricedModelError(DepthCacheError):
    """A depth-model candidate the cache-pricing card does not price.

    §14.1's instruction is *"Select the depth model on cache-hit price,
    not list price."* — and a selection can only rank on a price that is
    stated.  A card entry names a model and states both its prices; a
    candidate whose model the card omits is refused by name, because the
    two things a silent skip would invite are both failures this feature
    exists to prevent: the unpriced candidate would either drop out of a
    selection it was offered to (a selection over a subset nobody chose)
    or be ranked on its list price (the number §14.1 names as the wrong
    axis — a model 20% cheaper on the list can be 4× dearer on the hit,
    the ordering the whole feature turns on).  Raised by
    :func:`providers.select_depth_model`, naming the model and the card.

    The repair is the card, not the candidate: add the model's
    ``CachePrice`` — or stop offering it as a candidate, if it is not
    one.  The one repair that is never available is selecting it anyway
    on the list price, which is the trap the sentence's *because* names.
    """


class UnplannedCampaignError(DepthCacheError):
    """A campaign id the campaign table does not hold, offered for measurement.

    The store measures *a campaign's* calls, and a campaign is a planned
    row: feature 232's record, created before any node is expanded, is
    the row every reader of a campaign joins by id.  Measuring an id no
    row holds would persist an accounting for calls that were never
    placed, beside campaigns that placed them — the same refusal the
    null-oracle's seven stores make for a campaign id their table does
    not hold, and feature 202's scheduler makes from this same seam's
    other side.  Raised by :meth:`providers.DepthCacheRates.measure`,
    for an id the ``campaign`` table does not hold and for a database
    with no ``campaign`` table at all (a database where no campaign has
    ever been planned, which is the same fact about the id rather than a
    different one).

    The repair is the campaign record, not the id: plan the campaign
    (:func:`discovery.create_campaign`) first, then measure its runs.
    """


class CacheRateConflictError(DepthCacheError):
    """A campaign already measured with different token totals.

    One campaign is one run of the discovery loop, and its cache hit
    rate is a *measurement* of that run: the two token totals the row
    holds are re-derivable from the completions that served the campaign
    and from nothing else.  Re-issuing the identical measurement returns
    the stored record — a retry is the same measurement arriving twice,
    and the row is the fact it measured — while a second measurement
    naming different totals claims the same campaign hit cache at two
    rates, which is not an update but a contradiction.  Raised by
    :meth:`providers.DepthCacheRates.measure`, naming both totals and
    both rates, the same shape
    :class:`~providers.RunWindowConflictError` gives a window scheduled
    twice and for the same reason: the caller learns which value is
    stored and which it asked for.

    The repair is to read the stored record
    (:meth:`.DepthCacheRates.get`) — or, if the campaign genuinely ran
    twice, to plan the second run under its own campaign id, so each
    measurement measures one run.
    """
