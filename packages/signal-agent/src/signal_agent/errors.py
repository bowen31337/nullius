"""The signal-agent member's error vocabulary.

One base class (:class:`SignalAgentError`) so a caller — the campaign
driver, the tree store, an operator script, a later feature in this
category — can catch every failure of the authoring path with a single
``except``.  The subclasses split by *which contract* was violated rather
than by which line of code failed, the discipline
:mod:`bootstrap.errors`, :mod:`artifacts._errors` and :mod:`sandbox.errors`
state for their own trees:

* :class:`SignalAgentError` — raised by name, never bare.  A caller that
  wants the whole vocabulary in one ``except`` catches this; nothing in
  the member constructs it directly.

* :class:`AgentSourceError` — the *source* contract.  An
  agent-authored proposal could not be read as the thing it claims to be:
  text that is not text, text that is blank, or a source whose conforming
  entrypoint cannot be established.  This is the refusal feature 205's own
  sentence is about — *"a signal function conforming to the declared
  contract"* — and it is raised *before* the proposal becomes ledger
  history, because adopting a proposal the sandbox cannot invoke would
  spend a node's identity on code that has none.

The split matters to this member's two callers, and they are different
callers.  A *campaign driver* retrying a proposal needs
:class:`AgentSourceError` to be raised rather than a rejection value,
because the retry is the driver's decision: the failure carries the
validator's own problem list so the retry prompt can quote what was
wrong, and a member that had already turned "flawed mechanism" into
"retry" would have stolen feature 209's decision.  A *caller holding the
law's returned value* never sees either class — the returned
:class:`~signal_agent.SourceAdoption` answers as a value and the law
raises only at :meth:`~signal_agent.SourceAdoption.require`, so a caller
that wants to branch on a refusal branches on ``adopted`` rather than on
an exception.

The vocabulary deliberately has no *retry* class.  "A flawed core
mechanism" and "a sound idea undermined by a located bug" are two answers
feature 209 attributes to a *diagnosis*, and this member neither performs
that diagnosis nor records its outcome: a retry-decision error living
here would be an error type with no raiser, which is a shape the caller
would have to reason about for nothing.
"""

from __future__ import annotations

__all__ = [
    "AgentSourceError",
    "SignalAgentError",
]


class SignalAgentError(Exception):
    """Base class for every failure of the hypothesis-authoring path.

    Raised by name, never bare: a caller catching this has caught the whole
    vocabulary, and a caller catching a subclass has caught one contract.
    """


class AgentSourceError(SignalAgentError):
    """Agent-authored source could not be established as a conforming signal.

    Raised when a proposal cannot be adopted at all: the source is not a
    string, is blank, or does not compile and declare the entrypoint the
    sandbox invokes (feature 11's ``signal(ctx, seed)``, enforced by
    :func:`contract.validate_signal_signature`).  The message carries the
    validator's own problem list verbatim, because feature 206's
    read-everything requirement and feature 209's retry decision both need
    the *reason* rather than a boolean — a refusal that said only "not
    conforming" would force a caller to re-derive what the validator
    already said.

    The class exists so that "the agent wrote something the sandbox cannot
    invoke" is distinguishable from a *store* failure (a tree store that
    would not take the node) and from a *budget* failure (a trial the
    ledger would not charge).  The repairs are three different actions:
    re-prompt the agent, fix the store, or stop spending budget.
    """
