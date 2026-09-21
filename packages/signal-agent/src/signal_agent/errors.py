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

* :class:`IllegalThemeError` — the *theme* contract.  A proposal's theme
  root is outside the configured legal set, so the branch opens in
  territory PRD §9 never admitted.  Feature 212's own sentence is the
  refusal — *"which returns an illegal_theme error message"* — and this is
  the exception its ``illegal_theme`` message arrives as.  It is a
  subclass of :class:`AgentSourceError` deliberately: *what* the agent
  wrote is the subject either way, the repair (re-prompt it to open inside
  the admitted space) is the same repair, and a caller that already
  catches the source contract must not lose a theme refusal through a
  clause that no longer matches.  It is a distinct class because the two
  refusals are *grepped* differently — an operator asking how often the
  tree opened outside the legal set is asking a question the source
  contract's own failures do not answer.

* :class:`IllegalThemeError` — the *theme* contract.  A proposal's theme
  root is outside the configured legal set, so the branch opens in
  territory PRD §9 never admitted.  Feature 212's own sentence is the
  refusal — *"which returns an illegal_theme error message"* — and this is
  the exception its ``illegal_theme`` message arrives as.  It is a
  subclass of :class:`AgentSourceError` deliberately: *what* the agent
  wrote is the subject either way, the repair (re-prompt it to open inside
  the admitted space) is the same repair, and a caller that already
  catches the source contract must not lose a theme refusal through a
  clause that no longer matches.  It is a distinct class because the two
  refusals are *grepped* differently — an operator asking how often the
  tree opened outside the legal set is asking a question the source
  contract's own failures do not answer.

* :class:`DeadTerritoryError` — the *viability* contract.  A proposal's
  theme root is a mechanism PRD §9.4 names as structurally dead at retail
  scale — triangular arbitrage, a holding period under ~30 minutes taking
  liquidity — so the branch opens in territory that cannot pay for itself
  however well the signal works.  Feature 213's own sentence is the
  refusal — a root in dead territory, carrying the ``dead_territory`` code
  the feature names — and, like :class:`IllegalThemeError`, it is a
  subclass of :class:`AgentSourceError` for the same reason: the subject is
  what the agent proposed, the repair is the same re-prompt, and a caller
  catching the source contract must not lose this refusal either.  It is a
  distinct class from :class:`IllegalThemeError` because the two questions
  are different in kind and an operator must be able to ask them
  separately: a root can be *legal* (inside §9.3's set) and yet *dead*
  (§9.4), and folding the two refusals into one class would make "how often
  did we open in dead territory?" unanswerable without reading messages.

* :class:`ThemeSetError` — the *configuration* contract for the legal
  theme set.  The committed legal theme set could not be read as a set: a
  missing marker, a slug that is not a slug, a theme listed twice, or an
  empty set — which is refused rather than compiled, because a legal set
  that names nothing is not a strict hypothesis space but the absence of
  PRD §9's decision.  Unlike the two above, this one is a statement about
  the *deployment* rather than about a proposal: no agent action repairs
  it, and the separation is the same one the sandbox member draws between a
  refused submission (:class:`sandbox.DisallowedImportError`) and a refused
  document (:class:`sandbox.AllowlistDocumentError`).

* :class:`DeadTerritorySetError` — the *configuration* contract for the
  dead-territory list.  The committed §9.4 denylist could not be read as a
  list: a missing marker, a slug that is not a slug, a mechanism listed
  twice, or a list that names nothing — refused rather than compiled,
  because a dead-territory list that names nothing is not a strict denylist
  but the absence of PRD §9.4's decision ("Do not let the agent open roots
  there").  Like :class:`ThemeSetError` it is a statement about the
  *deployment*, not a proposal: no agent action repairs it, and the
  campaign driver's retry logic must not see one and re-prompt.  It is a
  sibling of :class:`ThemeSetError`, not a subclass — the two documents are
  different artifacts and an operator reading the refusal must know which
  committed file drifted.

The split matters to this member's callers, and they are different
callers.  A *campaign driver* retrying a proposal needs
:class:`AgentSourceError` to be raised rather than a rejection value,
because the retry is the driver's decision: the failure carries the
validator's own problem list so the retry prompt can quote what was
wrong, and a member that had already turned "flawed mechanism" into
"retry" would have stolen feature 209's decision.  A *caller holding a
law's returned value* never sees any of these classes — the returned
:class:`~signal_agent.SourceAdoption` and
:class:`~signal_agent.ThemeAdmission` answer as values and the laws raise
only at their ``require`` methods, so a caller that wants to branch on a
refusal branches on ``adopted`` rather than on an exception.

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
    "DeadTerritoryError",
    "DeadTerritorySetError",
    "IllegalThemeError",
    "SignalAgentError",
    "ThemeSetError",
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


class IllegalThemeError(AgentSourceError):
    """A proposal opens a root outside the configured legal set.

    Raised by :meth:`~signal_agent.SignalThemeGate.require` — feature 212's
    bridge between the gate's returned refusal and the exception a caller
    wants on its last line before it opens a node.  The message is the
    gate's own sentence, opening with the code of the verdict that produced
    it — the ``illegal_theme`` code the feature names for a root outside
    the set, and the not-a-theme code for a value that was never a root to
    judge against one — so a campaign log and a retry prompt say the same
    thing.

    **It subclasses :class:`AgentSourceError`, and that is load-bearing.**
    The two refusals have one subject — what the agent proposed — and one
    repair: re-prompt it to open inside the space PRD §9 encoded.  A
    caller that already writes ``except AgentSourceError`` must not lose a
    theme refusal because its clause stopped matching, and a sibling class
    would have done exactly that at every call site written before feature
    212 existed.  What the distinct class buys is the *query*: "how often
    did the tree open outside the legal set?" is a question about
    territory, and a caller that could not separate it from a signature
    bug would have to match on message text to ask it.

    It is not raised for a theme root that is missing or not a string.
    That is :class:`ThemeSetError`'s sibling shape at the value layer —
    the gate answers it :attr:`~signal_agent.ThemeReason.NOT_A_THEME`, and
    a caller that *requires* an admission on such a value still gets this
    class from ``require`` with the not-a-theme sentence inside it: the
    two reasons differ to a caller branching on the returned value, and
    both are refusals to the caller on its last line.
    """


class DeadTerritoryError(AgentSourceError):
    """A proposal opens a root in territory PRD §9.4 names as structurally dead.

    Raised by :meth:`~signal_agent.DeadTerritoryGate.require` — feature
    213's bridge between the gate's returned refusal and the exception a
    caller wants on its last line before it opens a node.  The message is
    the gate's own sentence, opening with the code of the verdict that
    produced it — the ``dead_territory`` code the feature names for a root
    in structurally dead territory — so a campaign log and a retry prompt
    say the same thing.

    **It subclasses :class:`AgentSourceError`, and that is load-bearing.**
    The two refusals — this one, feature 212's :class:`IllegalThemeError`
    and feature 205's :class:`AgentSourceError` itself — have one subject —
    what the agent proposed — and one repair: re-prompt it to open inside a
    space that is both admitted and live.  A caller that already writes
    ``except AgentSourceError`` must not lose a dead-territory refusal
    because its clause stopped matching, and a sibling class would have done
    exactly that at every call site written before feature 213 existed.
    What the distinct class buys is the *query*: "how often did the tree
    open in dead territory?" is a question about *viability*, and it is a
    different question from both "how often did it open outside the legal
    set?" (feature 212, :class:`IllegalThemeError`) and "how often did the
    source not conform?" (feature 205).  A caller that could not separate
    the three would have to match on message text to ask any of them.

    It is deliberately **not** a subclass of :class:`IllegalThemeError`, and
    that is the load-bearing distinction feature 212's law is built around:
    a root can be *legal* — inside the human-admitted §9.3 set — and yet
    *dead* — a mechanism §9.4 says cannot pay for itself — and a dead root
    that wore the illegal-theme class would read as "the human never
    admitted this space", which is the wrong repair (widen the document,
    which cannot help, since the human *did* admit it) and the wrong query
    (it would fold a viability finding into a membership one).  The two
    refusals are siblings under the source contract, each greppable on its
    own class.
    """


class ThemeSetError(SignalAgentError):
    """The configured legal theme set is not a set this member can read.

    Raised when the committed artifact — or a caller's own document — cannot
    be compiled: a missing or wrong marker, a ``themes`` list that is not a
    list, an entry that is not an entry, a slug that is not a lowercase
    hyphenated slug, a theme listed twice, or a set that names no themes at
    all.  Feature 212's *"configured legal set"* is only a set if it was
    read whole, so a drift is refused at compile time rather than applied:
    half a set would refuse proposals the human admitted.

    It is deliberately **not** an :class:`AgentSourceError`.  These are not
    statements about a proposal — no agent action repairs a document, and
    the campaign driver's retry logic must not see one and re-prompt.  The
    separation is the one :mod:`sandbox.errors` draws between
    :class:`sandbox.DisallowedImportError` (this submission is refused) and
    :class:`sandbox.AllowlistDocumentError` (the deployment's allowlist is
    not one), and it is load-bearing here for the same reason: an operator
    who cannot tell "the agent opened in a bad theme" from "the theme set
    is broken" cannot tell which of the two to fix.
    """


class DeadTerritorySetError(SignalAgentError):
    """The committed dead-territory list is not a list this member can read.

    Raised when the committed §9.4 denylist — or a caller's own document —
    cannot be compiled: a missing or wrong marker, a ``mechanisms`` list
    that is not a list, an entry that is not an entry, a slug that is not a
    lowercase hyphenated slug, a mechanism listed twice, or a list that
    names nothing at all.  Feature 213's *"structurally dead territory"* is
    only a defined list if it was read whole, so a drift is refused at
    compile time rather than applied: half a denylist would let a dead root
    through, which is exactly the refusal PRD §9.4 exists to make ("Do not
    let the agent open roots there").

    It is deliberately **not** an :class:`AgentSourceError`, and it is
    deliberately a *sibling* of :class:`ThemeSetError` rather than a
    subclass of it.  It is not about a proposal — no agent action repairs a
    document, and the campaign driver's retry logic must not see one and
    re-prompt, the same reason :class:`ThemeSetError` is not an
    :class:`AgentSourceError`.  It is a sibling rather than a subclass
    because the two committed documents are different artifacts with
    different subjects — the §9.3 legal set versus the §9.4 dead-territory
    list — and an operator reading the refusal must know which file drifted
    and which to widen.  Folding the two set errors together would make
    "the denylist is broken" indistinguishable from "the legal set is
    broken", and the two are fixed in two different documents.
    """
