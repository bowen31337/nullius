"""The failure modes of routing a depth call — feature 201.

app_spec.xml, "LLM Provider Tiering & Agent Pinning", feature 201: *System
routes depth calls through a batch endpoint when available, which returns
roughly half the synchronous rate.*  This module is the vocabulary of that
routing's refusals, and it is a **fifth base class** in this package — one
that deliberately shares no ancestor with
:class:`providers.ProviderError`, :class:`providers.ModelPinError`,
:class:`providers.DepthModelError` or :class:`providers.DepthScheduleError`,
for the reason each of those states for itself: a caller's ``except`` clause
answers one question, and these five questions are different ones.

* :class:`~providers.ProviderError` answers *did the model call work?*
* :class:`~providers.ModelPinError` answers *is this node's authoring record
  pinnable?*
* :class:`~providers.DepthModelError` answers *may this model serve the depth
  role?*
* :class:`~providers.DepthScheduleError` answers *when may this campaign's
  runs happen?*
* :class:`BatchRoutingError` answers *which endpoint does this call go to?*

The fifth is not a restatement of any of the four.  A call refused here has
not been placed, so it is not a provider contract that failed; it pins no
node; it is not a model refused for a role — the routing never sees a model
at all.  And it is emphatically not the scheduling question: feature 202
decides **when a campaign's runs happen** and this feature decides **which
endpoint serves a call**, which is why §14.2 can state them as two levers
that *"stack"*.  A deployment catching ``DepthScheduleError`` to learn that a
run could not be fitted outside the peak windows must not be told instead
that a pricing card named no offering for its provider — those are two
different repairs, one of them a calendar and one of them a config file.

The base is also raised *directly*, for the failures no subclass describes:
a card whose offering is missing a part, a provider name that is not a
non-empty string, an availability flag that is neither ``True`` nor
``False``, a rate multiple outside ``(0, 1]``, two offerings for one
provider, an ``offerings`` value that is not an iterable.  These are
malformed *descriptions* rather than failed *routings*, and the move is the
one :class:`providers.DepthModelError` makes for its own trivia: a contract
violation that is genuinely none of the named cases has no subclass to wear,
and minting one class per call site is how a taxonomy stops describing
anything.  The subclass below answers a question a caller can act on; "your
fraction is 1.4" has no such question beyond the message itself.

The one refusal, and why there is exactly one
---------------------------------------------

The feature's sentence has **one** way to fail.  *"Routes depth calls
through a batch endpoint when available"* is a routing that falls back: a
provider with no batch endpoint, and a call the caller did not declare
batchable, both route to the synchronous endpoint and both are ordinary
outcomes rather than refusals — the sentence's own *"when available"* is a
condition the routing reads, not an error it reports.

What is genuinely unanswerable is a **provider the card does not describe**:
routing is a choice between endpoints, the choice is read off the serving
provider's offering, and a card that never mentions the provider offers no
endpoints to choose between.  That is :class:`UnknownProviderError`, and it
is named rather than folded into the synchronous fallback for a load-bearing
reason — the fallback would bill a real call at the synchronous rate on the
strength of a card that simply forgot the provider, and the result would be
indistinguishable from a routing decision.  A configuration gap that looks
like a decision is the failure mode this feature exists to prevent, so it is
the one thing the routing refuses.

Stdlib-only, like the rest of this tree: these errors describe a choice
between two endpoints over facts a deployment states about a rate card, and
nothing here dials a provider, submits a job, or imports an SDK.
"""

from __future__ import annotations

__all__ = [
    "BatchRoutingError",
    "UnknownProviderError",
]


class BatchRoutingError(Exception):
    """Base of the batch-routing taxonomy — a depth call's endpoint could not be chosen.

    One base class so a deployment's campaign launcher, its cost accounting
    and a suite can catch every failure of feature 201's sentence — an
    undescribed provider, an offering missing a part, a malformed rate, a
    card that contradicts itself — with a single ``except``, the way
    :class:`providers.DepthModelError` gives feature 198's selection one
    handle and :class:`providers.DepthScheduleError` gives feature 202's
    scheduling one.  The base is deliberately unrelated to all four of its
    siblings: a routing that could not be decided is not a call that failed,
    not a node that cannot be pinned, not a model refused a role, and not a
    run that fits no window — and a caller catching any of those must not
    have this answered in their place.

    Also raised directly for the malformations no subclass describes — a
    non-record offering, a blank provider name, a non-bool availability, a
    rate outside ``(0, 1]``, a repeated provider, a non-iterable
    ``offerings`` — on the grounds the module docstring gives: those are bad
    *descriptions* rather than failed *routings*, and the taxonomy splits by
    question, not by call site.
    """


class UnknownProviderError(BatchRoutingError):
    """A depth call's serving provider is not described by the batch pricing card.

    The routing's one refusal, and the only fact in the feature's sentence
    that cannot be answered: *which endpoint does this call go to?* is read
    off the offering of the provider that serves it, and a card that does
    not describe that provider states no endpoints at all.

    Raised by :func:`providers.route_depth_call` before any endpoint is
    chosen.  It is deliberately **not** treated as *no batch endpoint
    available*: that reading would route the call synchronously — a real
    billing decision — on the strength of a card that never mentioned the
    provider, and nothing downstream could tell the difference between that
    and a routing that genuinely found no batch endpoint.  The repair is
    named in the refusal: add the provider's offering to the card, with
    ``available=False`` and a synchronous ``rate_multiple`` if the provider
    offers no batch API.

    Note that a provider the card *does* describe as ``available=False`` is
    not this error and never reaches a refusal at all — that is a stated
    fact about a provider, routed around rather than complained about.  The
    distinction between the two is the whole reason this class exists.
    """
