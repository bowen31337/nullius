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

The two refusals, and why there are exactly two
------------------------------------------------

The feature's sentence names **one property** — *a 1 million token context
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

Stdlib-only, like the rest of this tree: these errors describe a selection
criterion over facts a deployment states about a rate card, and nothing here
dials a provider, reads a price list, or imports an SDK.
"""

from __future__ import annotations

__all__ = [
    "DepthModelError",
    "InsufficientContextError",
    "LongContextSurchargeError",
]


class DepthModelError(Exception):
    """Base of the depth-role taxonomy — a model was refused for the depth role.

    One base class so a deployment's campaign launcher, its registry check
    and a suite can catch every failure of feature 198's sentence — a window
    below the bar, a surcharge under it, a candidate that is not a candidate
    — with a single ``except``, the way :class:`providers.ProviderError`
    gives the call seam one handle and :class:`providers.ModelPinError`
    gives the authoring record one.  The base is deliberately unrelated to
    both: refusing a model *before* the campaign runs is not a call that
    failed and not a node that cannot be pinned, and a caller that catches
    those must not have this answered in their place.

    Also raised directly for the malformations no subclass describes — a
    non-record candidate, a blank model name, a non-positive token count —
    on the grounds the module docstring gives: those are bad *descriptions*
    rather than failed *criteria*, and the taxonomy splits by question, not
    by call site.
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
