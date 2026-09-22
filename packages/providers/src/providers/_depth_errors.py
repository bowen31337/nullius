"""The failure modes of admitting a depth model — feature 198.

app_spec.xml, "LLM Provider Tiering & Agent Pinning", feature 198: *System
rejects a depth model without a 1 million token context at flat pricing,
because calls at depth 2 or greater carry a large history.*  This module is
the vocabulary of that refusal, and it is a **third base class** in this
package — one that deliberately shares no ancestor with
:class:`providers.ProviderError` or :class:`providers.ModelPinError`, for the
same reason those two share none with each other: a caller's ``except``
clause answers one question, and the three questions are different ones.

* :class:`~providers.ProviderError` answers *did the model call work?* — the
  seam's contract, violated by a provider that answered wrong.
* :class:`~providers.ModelPinError` answers *is this node's authoring record
  pinnable?* — a record that cannot be read as a model identity.
* :class:`DepthModelError` answers *may this model serve the depth role?* —
  a selection a deployment makes **before** any call is placed and any node
  is authored.

A candidate refused here has not been called, so it is not a provider
contract that failed; and it pins no node, so there is no record to read.
Folding it under either existing base would make every ``except`` of that
base answer a question it never asked — a deployment catching
``ProviderError`` to find a broken backend would instead be told a rate card
it never ran was shaped wrong — and that is the collapse this package's
other two taxonomies each refuse in their own docstrings.

The base is also raised *directly*, for the failures no subclass describes:
a candidate that is not a :class:`~providers.DepthModel` at all, a name that
is not a non-empty string, a context window that is not a positive token
count, a surcharge threshold that is not a positive one.  These are
malformed *descriptions* rather than failed *criteria*, and the move is the
one :class:`providers.ModelPinError` makes for an unusable store URL and a
non-UUID node id: a contract violation that is genuinely none of the named
cases has no subclass to wear, and minting one class per call site is how a
taxonomy stops describing anything.  The subclasses below each answer a
question a caller can act on; "your int is not an int" has no such question
beyond the message itself.

The four refusals, and why they share one base
----------------------------------------------

Feature 198's sentence names **one property** — *a 1 million token context
at flat pricing* — and a property that is a conjunction fails in exactly as
many ways as it has conjuncts.  Two, then:

* :class:`InsufficientContextError` — the window is below the bar.  The
  load-bearing refusal, and architecture §14.1's own words: *"Context is a
  hard selection criterion, not a spec-sheet line"* — at ~1k tokens per
  ``proposal.md`` plus its ``score.json``, a 500-node campaign carries
  roughly 500K tokens of history by the late rounds, and *"a model with a
  256K window physically cannot execute the defining prompt of this system
  in a mature wide campaign."*  The refusal is about the **role**, not the
  model: §14.1's table lists a 262K self-hosted tier as the right model for
  early-depth nodes, narrow campaigns and the §10.6 bootstrap worlds, where
  histories are short and self-contained.  Such a model is a well-formed
  candidate that may not serve *this* role — which is why the record
  (:class:`~providers.DepthModel`) constructs happily at 262K and only the
  gate (:func:`providers.require_depth_model`) refuses.

* :class:`LongContextSurchargeError` — the window is large enough but the
  pricing is not flat through it: the rate card reprices the *whole request*
  above an input threshold that sits below the bar.  §14.2's surcharge table
  is the source — OpenAI's tiers reprice above 272K input (2× input, 1.5×
  output), Gemini Pro above 200K — and §14.2 names the failure mode: *"the
  **average** depth call carries ~300K tokens of context and late calls
  exceed 600K. That is not a tail case, it is the modal case — and it sits
  above every major provider's long-context threshold."*  A threshold below
  the bar therefore sits under the modal depth call, and the headline rate
  is not the rate this role pays — the trap §14.2 spells out for OpenAI's
  cheap tiers, whose per-request price doubles once history crosses 272K,
  which it does by roughly node 220.

The window is refused before the pricing, and the ordering is a decision
rather than a convenience: a model that physically cannot hold the history
fails on physics, and what it would have cost never becomes relevant.  A
caller meeting both lacks (a cheap tier with a short window *and* a
surcharge) is told the one that no pricing choice can repair.

**Feature 199 is the role criterion's second layer, and its two refusals
join the same base rather than minting a new one.**  app_spec.xml feature
199: *"System rejects a depth model whose verified served context limit is
below the campaign history size, rather than trusting a published figure"* —
architecture §14.1's own instruction, in the same paragraph the 256K clause
comes from: *"Verify the served context limit (``--max-model-len``), not the
marketing number."*  So the second layer asks the **same question** feature
198's gate asks — *may this model take the depth role's calls?* — with two
differences: the fact is the number the deployment actually **serves**
rather than the number the card **publishes**, and the bar is **this
campaign's** history rather than the fixed one million.  Its property is
again a conjunction — *a verified served limit at or above the campaign's
history* — and fails in its own two ways:

* :class:`ServedContextUnverifiedError` — the number is a published figure
  rather than the served limit.  The load-bearing refusal of the second
  layer, and the whole of the sentence's *rather than*: the marketing number
  is a claim about a model, and ``--max-model-len`` is the fact about the
  deployment serving it.  A 1M published window behind a 262K served limit
  is a 262K model, and §14.1's 256K clause is exactly the failure that
  arrives through the spec sheet.

* :class:`ServedContextBelowHistoryError` — the served limit is verified and
  it is under the campaign's history: §14.1's *"a model with a 256K window
  physically cannot execute the defining prompt of this system in a mature
  wide campaign"*, measured against this campaign's own history (at ~1k
  tokens per ``proposal.md`` plus its ``score.json``, a 500-node campaign
  carries roughly 500K tokens of it by the late rounds; §14.2 measures the
  average depth call at ~300K and late calls beyond 600K).

The two are separate classes because the repairs are separate — *re-probe
the served model* against *shorten the campaign or serve a larger window* —
and they are ordered as listed: **an unverified number cannot be compared at
all**, so a caller holding a published figure that also looks too small is
told the figure was never a measurement, not that a measurement came up
short.  You cannot conclude *this deployment's served limit is below the
history* from a marketing number; that inference is precisely what the
sentence forbids.

**Why these two join :class:`DepthModelError` rather than a seventh base.**
The package's bases split along the *axis of the question*, and this is the
same axis as 198's: the model's capacity to hold the role's history.  Both
layers are consulted by the same actor at the same moment — before any call
is placed and any node is authored — and a caller's ``except
DepthModelError:`` should mean *my depth model was refused* whichever layer
refused it.  Forcing two ``except`` clauses here would make the one question
two, which is the collapse each of this package's taxonomies refuses in its
own docstring.  The contrast is the other bases, which split along genuinely
different facts: :class:`providers.ModelPinError` is a *provenance record*
(and feature 204's five join it because *"the columns are one row"*),
:class:`providers.DepthCacheError` is the *money*, :class:`providers.
DepthScheduleError` the *time*, :class:`providers.BatchRoutingError` the
*endpoint*, and :class:`providers.ProviderError` the *call* itself.  Feature
199 is none of those; it is the same capacity question asked of a measured
fact, so it extends this base the way feature 204 extended feature 203's.

Stdlib-only, like the rest of this tree: these errors describe selection
criteria over facts a deployment states about a rate card and measures about
a served model, and nothing here dials a provider, reads a price list, or
imports an SDK.
"""

from __future__ import annotations

__all__ = [
    "DepthModelError",
    "InsufficientContextError",
    "LongContextSurchargeError",
    "ServedContextBelowHistoryError",
    "ServedContextUnverifiedError",
]


class DepthModelError(Exception):
    """Base of the depth-role taxonomy — a model was refused for the depth role.

    One base class so a deployment's campaign launcher, its registry check
    and a suite can catch every failure of the role's criterion — feature
    198's bar (*a 1 million token context at flat pricing*) and feature 199's
    verification (*a verified served limit at or above the campaign's
    history*) — with a single ``except``: a window below the bar, a
    surcharge under it, a served limit nobody measured, a served limit
    under the history, a candidate that is not a candidate.  The same
    one-handle discipline :class:`providers.ProviderError` gives the call
    seam and :class:`providers.ModelPinError` gives the authoring record.
    The base is deliberately unrelated to those: refusing a model *before*
    the campaign runs is not a call that failed and not a node that cannot
    be pinned, and a caller that catches those must not have this answered
    in their place.

    Features 198 and 199 share this base because they answer **one
    question** — *may this model take the depth role's calls?* — asked by
    the same actor at the same moment, of the same axis (the model's
    capacity to hold the role's history).  They differ in the *fact* (the
    published window against the served limit) and the *bar* (one million
    fixed against this campaign's history), not in the question; see the
    module docstring for why that is a shared base rather than a seventh.

    Also raised directly for the malformations no subclass describes — a
    non-record candidate, a blank model name, a non-positive token count, a
    history size that is not a positive count — on the grounds the module
    docstring gives: those are bad *descriptions* rather than failed
    *criteria*, and the taxonomy splits by question, not by call site.
    """


class InsufficientContextError(DepthModelError):
    """A depth-model candidate whose context window is below one million tokens.

    The hard criterion of architecture §14.1, in its own words a selection
    criterion and not a spec-sheet line: calls at depth 2 or greater carry
    the campaign's whole history, because the C3 prompt reads every prior
    ``proposal.md`` in full, and a window smaller than that history cannot
    hold the prompt the role exists to run.  Raised by
    :func:`providers.require_depth_model` for a candidate whose
    ``context_tokens`` is below :data:`providers.MIN_DEPTH_CONTEXT_TOKENS`.

    The refusal confines rather than condemns: §14.1's registry lists
    short-window models — the self-hosted 262K tier — as the right choice for
    early-depth nodes, narrow campaigns and the bootstrap worlds, where
    histories are short and self-contained.  The model is refused for *this*
    role; a caller who meant one of those roles is holding the right model
    and the wrong gate.
    """


class LongContextSurchargeError(DepthModelError):
    """A depth-model candidate whose pricing is not flat through one million tokens.

    The window is large enough and the rate card is wrong anyway: the
    provider reprices the **entire request** above an input-token threshold,
    and that threshold sits below the bar, so it sits under the modal depth
    call — §14.2 measures the average depth call at ~300K tokens of context
    and late calls beyond 600K, against thresholds of 272K and 200K.  The
    headline rate is therefore not the rate this role pays, which is the
    trap §14.2 names for OpenAI's cheap tiers: a request billed at 2× from
    the moment its history crosses the threshold, which a wide campaign
    crosses by roughly node 220.  Raised by
    :func:`providers.require_depth_model` for a candidate whose
    ``surcharge_threshold`` is below
    :data:`providers.MIN_DEPTH_CONTEXT_TOKENS`.
    """


class ServedContextUnverifiedError(DepthModelError):
    """A depth model whose context figure is a published number, not a served limit.

    Feature 199's first refusal, and the whole of the sentence's *rather than
    trusting a published figure*: architecture §14.1 does not merely prefer
    the measurement, it instructs the reader to **"verify the served context
    limit (``--max-model-len``), not the marketing number."**  The two are
    different facts about different things — the published figure is a claim
    about a model, and the served limit is what the deployment that will
    actually take the calls has been configured to attend over — and they
    come apart in exactly the direction that hurts, because a self-hosted
    deployment serving MIT weights behind a 262K ``--max-model-len`` is a
    262K model no matter what the checkpoint's card advertises.  §14.1's own
    clause (*"a model with a 256K window physically cannot execute the
    defining prompt of this system in a mature wide campaign"*) is the
    failure that arrives through the spec sheet when the figure is trusted.

    Raised by :func:`providers.require_served_context` for a measurement
    that carries :func:`providers.published_figure` — the named state, so a
    caller who holds only the marketing number **says so** rather than
    leaving a flag unset.  The repair is to probe the served model and state
    what it answered; the one repair this refusal rules out is admitting the
    candidate on the strength of the published number, which is the
    inference feature 199 exists to forbid.

    It is refused *before* the comparison against the campaign's history and
    independently of it, because **an unverified number cannot be compared
    at all**: a published figure that happens to look large enough is not a
    measurement that cleared the bar, and one that looks too small is not a
    measurement that failed it.
    """


class ServedContextBelowHistoryError(DepthModelError):
    """A verified served context limit below the campaign's history size.

    Feature 199's second refusal, on the law architecture §14.1 states in as
    many words: *"A model with a 256K window physically cannot execute the
    defining prompt of this system in a mature wide campaign."*  The depth
    role's C3 prompt reads every prior ``proposal.md`` **in full**, so the
    history *is* the prompt: at ~1k tokens per proposal plus its
    ``score.json``, a 500-node campaign carries roughly 500K tokens of it by
    the late rounds (§14.2 measures the average depth call at ~300K tokens
    and late calls beyond 600K).  A served window under that figure cannot
    hold the call the role exists to make, and the failure is physical — the
    request does not fit — so no pricing or routing choice downstream can
    repair it.

    Raised by :func:`providers.require_served_context` for a **verified**
    measurement whose ``served_tokens`` is below the ``history_tokens`` the
    caller declared for the campaign.  The refusal names both counts, because
    the difference between them is the margin the campaign would have to shed
    (or the window it would have to gain), and that number is the repair.

    The refusal confines rather than condemns, exactly as
    :class:`InsufficientContextError` does for the fixed bar: §14.1's own
    resolution is that such models *"are confined to early-depth nodes,
    narrow campaigns, and the §10.6 bootstrap worlds, where histories are
    short and self-contained"* — and this refusal is the same confinement
    arrived at per campaign, since a history under the served limit admits
    the very same model for that campaign.  Unlike feature 198's bar, the
    bar here is the campaign's own, so the same deployment may be admitted
    for a narrow campaign and refused for a wide one.
    """
