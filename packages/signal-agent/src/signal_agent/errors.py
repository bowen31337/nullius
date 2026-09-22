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

* :class:`AntiConvergenceError` — the *convergence* contract.  A proposal's
  structure — every numeric literal erased — is one the campaign already
  holds, so the branch would re-open a mechanism the tree already contains
  under different parameters.  Feature 210's own sentence is the refusal —
  *"a tree never collapses into 400 parameter tweaks of one indicator"* —
  and, like :class:`IllegalThemeError` and :class:`DeadTerritoryError`, it
  is a subclass of :class:`AgentSourceError` because the subject is what
  the agent proposed and the repair is the same re-prompt.  It is a
  distinct class because this is the one failure §14.1 says nothing else
  catches, so an operator asking "how often did the tree re-submit a
  structure it already held?" is asking the question the feature exists to
  make answerable.  It is also raised, on its own path, when a proposal is
  not parseable source at all — the ``not_a_proposal`` case, which opens
  with its own code because the defect is at the call site rather than in
  the tree.

* :class:`AntiConvergenceClauseError` — the *configuration* contract for
  feature 210's clause and for the prompt that must carry it: an
  ``anti_convergence.json`` that cannot be compiled, or a campaign's
  authoring prompt that does not carry the committed clause (the
  ``clause_absent`` refusal).  Like :class:`ThemeSetError` and
  :class:`DeadTerritorySetError` it is a statement about the *deployment*
  rather than about a proposal: no agent action repairs it, and the
  campaign driver's retry logic must not see one and re-prompt — a dropped
  clause is fixed by editing the prompt, not by spending trial budget
  asking a model to fix a template.  It is a sibling of those two, not a
  subclass, because the artifact that drifted is a third file.

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

* :class:`MechanismStatementError` — the *statement* contract for feature
  211's ``stated_mechanism``.  A proposal's economic rationale could not be
  established as the thing it claims to be: a value that is not text at all,
  text with nothing in it, or — on the write path — a statement that
  disagrees with the one the node already records.  It is a sibling of
  :class:`AgentSourceError`, not a subclass: the subject is the *rationale*
  the agent gave rather than the source it wrote, and an operator asking
  "how often did the agent state no mechanism?" is asking a question the
  source contract's own failures do not answer.  Neither is it a
  :class:`ThemeSetError` shape: a blank rationale is a proposal-level fact
  that a re-prompt repairs, unlike a drifted committed document.

  * :class:`MechanismConflictError` — the *same* contract, distinguished by
  repair.  The row already states a different mechanism, so the caller must
  stop trying to re-state a node's history, which is not something a re-prompt
  of the agent changes.  It is a subclass of
  :class:`MechanismStatementError` for the same reason
  :class:`IllegalThemeError` is one of :class:`AgentSourceError`: the subject
  is still the statement being persisted, and a caller that catches the
  statement contract must not lose this refusal through a clause that no
  longer matches.

* :class:`FlawedMechanismError` — feature 209's *diagnosis* contract.  A
  branch failed, something was reported against it, and nothing in the
  proposal's own source explains the failure — so the mechanism is what is
  implicated, and PRD §C3 says it "is not worth retrying".  Raised by
  :meth:`~signal_agent.MechanismDiagnosis.require` and only by it, on its own
  path, and it is the answer the *driver* must hear on the last line before it
  writes a retry prompt.

  **It is a sibling of :class:`AgentSourceError`, and that is this tree's
  sharpest inheritance decision.**  The three refusals under
  :class:`AgentSourceError` — illegal theme, dead territory, convergence — are
  each a fact about *what the agent wrote*, and each asserts the same repair:
  re-prompt it.  That is why they subclass.  This refusal asserts the
  *opposite* repair.  A caller's ``except AgentSourceError:`` handler exists to
  re-prompt, and letting it catch "the mechanism is flawed" would make that
  handler spend trial budget on the branch the diagnosis just said to close —
  which is the one thing feature 209 exists to prevent, and §14.1 prices it
  ("a bad proposal is caught by the evaluator at a cost of one trial charge").
  The subject is also different in kind: the source is exactly what this
  sentence holds blameless, and what failed is the *mechanism* — the same
  subject feature 211's rationale is about, and the same reason that one is a
  sibling too.

  The distinct class buys the *query* as well: "how often did the diagnosis
  close a branch rather than retry it?" is a question about research yield, and
  a caller that could not separate it from a signature bug would have to match
  on message text to ask it.

* :class:`MechanismNotScoredError` — the *barrier* clause of feature 211's
  own sentence, *"never as a scored input"*.  Raised by
  :meth:`~signal_agent.StatedMechanism.require_scored_input`, and only by
  it: a caller asked to admit the mechanism into a scoring path is refused
  by name, because the mechanism is the agent's prose rationale and every
  metric this system reports is a measurement of the *source* — letting
  prose in would make ``agent_model_id`` stratification, the M3 paired
  comparison and the deflation term functions of what an LLM wrote.  It is
  deliberately **not** under :class:`AgentSourceError` and deliberately not
  under :class:`MechanismStatementError`: no agent action repairs it and no
  re-prompt changes it, because the defect is in the *caller's wiring*
  rather than in the agent's answer.  The separation is the one
  :class:`ThemeSetError` draws between a broken document and a refused
  proposal, restated for a refusal that is about this system's own code.

* :class:`TruncatedHistoryError` — feature 206's *history* contract.  A round
  handed its authoring step a history of prior proposals that is not the whole
  history: a subset chosen by a rule (a count, a recency window, a summary of
  a proposal standing in for it), a proposal read cut short, or a declared
  prior proposal silently absent.  Architecture §14.1 states the requirement
  the refusal is about — every prior ``proposal.md`` *"**in full** — not a
  sample, not recent cycles"* — and it is raised by
  :meth:`~signal_agent.ProposalHistory.require` and only by it, on the last
  line before the authoring call.

  **It is a sibling of :class:`AgentSourceError` and of
  :class:`FlawedMechanismError`, and the asymmetry is the same one both of
  those state.**  The three refusals under :class:`AgentSourceError` are facts
  about *what the agent wrote*, and a caller's existing
  ``except AgentSourceError:`` handler repairs them by re-prompting the agent.
  This refusal has nothing to do with what the agent wrote: the agent has not
  been called yet, and the defect is in the *run's own assembly* — the read
  that produced the prompt.  Letting that handler catch it would re-prompt an
  agent whose prompt was assembled from a cut history, buying a second
  proposal from the same cut history, which is the waste this feature exists
  to prevent.  The repair is to fix the assembler: fetch the missing nodes,
  finish the reads, then re-run the step.

  It is not under :class:`FlawedMechanismError` either, though both assert
  "do not re-prompt": that class is a judgment about a *hypothesis* reached
  from a failure the evaluator reported, and this one is a judgment about the
  *caller's own wiring*, reached before any proposal exists.  Keeping them
  apart preserves the query — "how often did the diagnosis close a branch?"
  and "how often did a round read a partial history?" are different questions
  about different parts of the system, and the second one is exactly the
  untested assumption §14.1:773 says *"should be measured before it is relied
  on"*.

* :class:`InjectedGuidanceError` — feature 208's *prompt* contract.  A round's
  authoring prompt carries a part that declares itself summarized directional
  guidance — a section whose declared role is guidance ("summary",
  "lessons", "insights", ...), or whose content declares itself distilled from
  the history — or the prompt was handed to the gate as a flat text with no
  parts to screen at all.  PRD §C3 states the requirement this refusal is
  about — *"Do not inject high-level directional guidance from history into
  the prompt"* — because the paper's Figure 5 found it *underperformed* the
  unguided version, and §14.1:773 agrees (*"Do not solve this by summarizing
  history into guidance"*) while splitting the neighbouring failure off to
  feature 206: truncating a proposal is a different operation from compressing
  it into prose.  Raised by :meth:`~signal_agent.GuidanceVerdict.require` and
  by :meth:`~signal_agent.PromptGuidanceGate.require`, and only there, on the
  last line before the prompt is flattened and shipped.

  **It is a sibling of :class:`AgentSourceError`, :class:`FlawedMechanismError`
  and :class:`TruncatedHistoryError`, and the asymmetry is the one those
  three state.**  The refusals under :class:`AgentSourceError` are facts about
  *what the agent wrote*, and a caller's pre-existing
  ``except AgentSourceError:`` handler repairs them by re-prompting — which
  is exactly wrong here, because the agent has not been called yet and would
  be re-prompted *with the same injected guidance*: the repair is to delete
  the section from the prompt and re-ship, which is the assembler's job.  It
  is a sibling of :class:`TruncatedHistoryError` rather than folded into it
  because the two are the halves of one §C3 sentence — *"Keep history as an
  interactive replay object, not as prose advice"* — and opposites a caller
  must tell apart: 206's says the prompt is *missing* the history's wholeness,
  this one says it *carries* prose about it.  An operator grepping a campaign
  log for one must not find the other.

* :class:`MechanismNodeNotRecordedError`,
  :class:`MechanismColumnError` and
  :class:`MechanismStoreUnavailableError` — the three *deployment* facts the
  mechanism's write path can meet.  There is no node to carry the column, the
  tree has not reached the revision that adds it, or the composed component
  was built with no ``DATABASE_URL`` at all.  Each is a statement about a
  database rather than about a proposal, so none is an
  :class:`AgentSourceError`, and the three are siblings of one another rather
  than subclasses because the three repairs are three different actions: write
  the node, run the migration chain, or point the deployment at a store.  An
  operator who could not tell them apart would not know which to do.

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

The vocabulary deliberately has no *retry* class, and feature 209's
arrival did not change that.  "A flawed core mechanism" and "a sound idea
undermined by a located bug" are two answers that feature attributes to a
*diagnosis*, and the retrying half of the decision is a value —
:class:`~signal_agent.MechanismDiagnosis` returns it, because a driver
deciding *whether* to spend a trial charge must be able to branch without
an exception in the way.  A retry-decision error would be an error type
whose only raiser is the caller that had already been told to retry, which
is a shape there is nothing to reason about.  What is *here* is the other
half: :class:`FlawedMechanismError`, the refusal, raised on the last line
before a retry prompt where a caller that established no location must not
be allowed to write one.

The **reader** classes arrived with the readers, and the reader's own split is
the same discipline one level on.  :class:`DiversityCohortError` is feature
215's and :class:`DiscriminationCohortError` is feature 214's, and they are
siblings rather than one class over one noun: the two features are handed
*different cohorts* — one a campaign's proposal history to count clusters over,
the other a caller-declared set of real branches to correlate a pair of gains
across — and each class's message has to say which cohort, in which table,
under which revision, cannot answer.  A shared *cohort* class would make an
operator reading *"the cohort cannot answer"* unable to tell whether a count
had failed on a missing model column or a correlation on a cohort of two
branches.  Each is a sibling of the three classes its own feature raises beside
it, and neither is an :class:`AgentSourceError`: nothing in either is about a
proposal's *source*.
"""

from __future__ import annotations

__all__ = [
    "AgentSourceError",
    "AntiConvergenceClauseError",
    "AntiConvergenceError",
    "DeadTerritoryError",
    "DeadTerritorySetError",
    "DiscriminationCohortError",
    "DiversityCohortError",
    "FlawedMechanismError",
    "IllegalThemeError",
    "InjectedGuidanceError",
    "MechanismColumnError",
    "MechanismConflictError",
    "MechanismNodeNotRecordedError",
    "MechanismNotScoredError",
    "MechanismStatementError",
    "MechanismStoreUnavailableError",
    "ProposalConflictError",
    "ProposalContentError",
    "ProposalHistoryStoreUnavailableError",
    "ProposalNodeNotRecordedError",
    "SignalAgentError",
    "ThemeSetError",
    "TruncatedHistoryError",
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


class AntiConvergenceError(AgentSourceError):
    """A proposal is a parameter tweak of a structure the campaign already holds.

    Raised by :meth:`~signal_agent.AntiConvergenceGate.require` — feature
    210's bridge between the gate's returned refusal and the exception a
    caller wants on its last line before it opens a node — and, on its own
    path, by :func:`~signal_agent.proposal_skeleton` and
    :func:`~signal_agent.skeleton_digest` when a proposal's structure cannot
    be read at all.  The message is the gate's own sentence, opening with
    the code of the verdict that produced it — ``parameter_tweak`` for the
    §14.1 collapse, ``not_a_proposal`` when there was nothing to screen — so
    a campaign log and a retry prompt say the same thing.

    **It subclasses :class:`AgentSourceError`, and that is load-bearing.**
    The subject either way is *what the agent proposed*: a 400th variant of
    one indicator is a perfectly conforming signal, written in conforming
    source, that opens no mechanism the tree lacks.  The repair is the same
    repair feature 212's and 213's refusals ask for — re-prompt the agent,
    with the duplicates named — and a caller that already writes
    ``except AgentSourceError`` must not lose a convergence refusal because
    its clause stopped matching.  A sibling class would have done exactly
    that at every call site written before feature 210 existed, and this is
    the one refusal in the member that fires *most often in practice*, so
    losing it silently is the worst of the five to lose.

    What the distinct class buys is the *query*.  "How often did the tree
    re-submit a structure it already held?" is a question about
    *convergence*, and docs/nullius-tech-architecture.md §14.1 says nothing
    else in the pipeline answers it: a bad proposal is caught by the
    evaluator at a cost of one trial charge, while a converged tree is not
    caught by anything — every node scores plausibly, the budget is fully
    consumed, and no other class in this vocabulary fires.  Folding this
    into :class:`AgentSourceError` would make a collapse indistinguishable
    from ordinary conformance churn, which is precisely the blind spot the
    feature exists to close.
    """


class AntiConvergenceClauseError(SignalAgentError):
    """The anti-convergence clause, or the prompt that must carry it, is unusable.

    One class for both halves of feature 210's *deployment* side, because
    they have one repair and one reader:

    * the committed clause at ``anti_convergence.json`` cannot be compiled —
      a missing or wrong marker, a ``clause`` that is not a clause, a
      ``slug``/``title``/``text`` that is not a non-empty string, or a slug
      outside the member's shared grammar.  Refused at compile time rather
      than applied, the same stance :class:`ThemeSetError` and
      :class:`DeadTerritorySetError` take for their own documents: a prompt
      screened against a clause that cannot be read is a prompt screened
      against nothing, and the campaign would author with PRD §C3's clause
      missing while believing it carried it.
    * the campaign's authoring prompt does not carry the clause — the
      refusal :meth:`~signal_agent.AntiConvergenceGate.require_in` raises,
      opening with the ``clause_absent`` code.  This is the half that makes
      *explicit* in "an explicit anti-convergence clause" a checked fact
      about a shipped prompt rather than a sentence somebody meant to write.

    **It is deliberately not an :class:`AgentSourceError`.**  Neither half
    is a statement about a proposal: no agent action repairs a drifted
    document, and a prompt that dropped the clause is repaired by editing
    the prompt rather than by re-prompting the model — which is precisely
    the distinction the campaign driver's retry logic turns on.  A driver
    that saw this class and re-prompted would spend trial budget asking a
    model to fix a template.

    **It is deliberately a sibling of :class:`ThemeSetError` and
    :class:`DeadTerritorySetError` rather than a subclass**, exactly as
    those two are siblings of each other: the three are three different
    committed artifacts (§9.3's legal set, §9.4's denylist, PRD §C3's
    clause) and an operator reading the refusal must know which file
    drifted.  The prompt half lives here rather than in a fourth class
    because it is a fact about *this* document — the prompt is refused for
    not carrying this clause, and a class that covered only the compile
    failures would leave the refusals an operator greps for most (prompts
    shipped without the clause) outside the class named after the clause.
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


class FlawedMechanismError(SignalAgentError):
    """A failed branch is not worth retrying — the mechanism is what failed.

    Raised by :meth:`~signal_agent.MechanismDiagnosis.require` — feature 209's
    bridge between the diagnosis's returned decision and the exception a caller
    wants on its last line before it writes a retry prompt.  The message is the
    law's own sentence, opening with the code of the verdict that produced it —
    ``flawed_mechanism`` for PRD §C3's *"the former is not worth retrying"*,
    and ``not_a_diagnosis`` when there was no failure to diagnose, or nothing
    that was source to locate a failure in — so a campaign log and a retry
    prompt say the same thing.

    **It is a sibling of :class:`AgentSourceError`, not a subclass, and the
    asymmetry is load-bearing at every call site written before feature 209
    existed.**  :class:`IllegalThemeError`, :class:`DeadTerritoryError` and
    :class:`AntiConvergenceError` subclass that base precisely so a caller's
    existing ``except AgentSourceError:`` handler keeps catching them — and
    that handler's repair is *re-prompt the agent*.  This refusal asserts the
    opposite repair: stop, close the branch, open another mechanism.  A caller
    that caught this through the same clause would re-prompt the branch the
    diagnosis just closed, spending a trial charge to learn nothing, which is
    the exact waste §14.1 names — *"A bad proposal is caught by the evaluator
    at a cost of one trial charge."*  The subject differs too: the three
    subclasses are facts about *what the agent wrote*, and this is a fact about
    the *idea* the code implements, with the source held blameless.

    What the distinct class buys is the *query*: "how often did the diagnosis
    close a branch rather than retry it?" is a question about research yield,
    and a caller that could not separate it from a signature bug would have to
    match on message text to ask it.  The separation is the one
    :class:`MechanismNotScoredError` draws for a refusal about this system's own
    wiring, applied to a refusal about a hypothesis.

    It is not raised for a *retryable* branch — there is no exception on that
    path at all, and that is feature 209's second clause: the decision is the
    law's returned value, and a caller that wants it branches on
    :attr:`~signal_agent.DiagnosisVerdict.retry` or takes the
    :class:`~signal_agent.LocatedDefect` from ``require``.
    """


class MechanismStatementError(SignalAgentError):
    """A proposal's stated mechanism is not a statement this member can persist.

    Raised when the agent's economic rationale cannot be established as the
    thing it claims to be: a value that is not text at all, text whose
    canonical form is empty (whitespace, or nothing), or — on the write path —
    a statement that disagrees with the one the node already records.  §9.1
    annotates the column ``-- dedup + human review ONLY, never scored``, and
    the first two refusals are about the *dedup* half: a rationale that
    normalizes to nothing names no mechanism for a reviewer to compare, and
    two of them would compare equal without stating anything.

    **It is a sibling of :class:`AgentSourceError`, and that is
    load-bearing.**  The two have different subjects — feature 205's is the
    *source* the agent wrote, this one is the *rationale* it gave for writing
    it — and different greps: an operator asking "how many proposals carried
    no economic rationale?" is asking a question the source contract's own
    failures do not answer.  A subclass would have made that query
    unanswerable without reading messages, and an agent that emits a flawless
    signal while stating no mechanism is a real and distinguishable case.

    **It is not a :class:`ThemeSetError` shape either.**  A blank rationale is
    a proposal-level fact that a re-prompt repairs; a drifted committed
    document is a deployment fact that no agent action touches.  The two are
    separated here for the same reason the member separates them everywhere
    else: the campaign driver's retry logic must re-prompt for one and must
    not for the other.
    """


class MechanismNotScoredError(SignalAgentError):
    """A caller tried to admit the stated mechanism into a scoring path.

    Raised by :meth:`~signal_agent.StatedMechanism.require_scored_input` — the
    bridge between the barrier's returned verdict and the exception a caller
    wants on its last line before it feeds the value into a scorer.  Feature
    211's own sentence is the refusal — a stated mechanism string is *"used for
    deduplication and human review, never as a scored input"* — and this is the
    exception that clause arrives as.

    **What it prevents is a leakage channel, not a wrong number.**  The stated
    mechanism is free text an authoring model wrote.  Every figure this system
    reports is a measurement of the *source* the same model wrote, and the
    workspace's provenance story rests on the two being separable: a score
    conditioned on the rationale would make ``agent_model_id`` stratification
    (PRD §5a), the M3 paired comparison (architecture §14.1) and the
    ``β₃`` deflation term all functions of what an LLM said about itself.  The
    failure would not look like a bug; it would look like a feature.

    **It is deliberately not an :class:`AgentSourceError` and deliberately not
    a :class:`MechanismStatementError`.**  No agent action repairs it and no
    re-prompt changes it: the defect is in this *system's* wiring rather than
    in an agent's answer, so a caller catching the proposal-level vocabulary
    must not catch this one by accident.  That is the same distinction
    :class:`ThemeSetError` draws between a broken document and a refused
    proposal, applied to a refusal that is about the caller's own code.
    """


class MechanismNodeNotRecordedError(SignalAgentError):
    """There is no node for the stated mechanism to be a column on.

    Raised by the mechanism store's write and read paths when the tree does not
    hold the id it was handed.  A stated mechanism is a column on a node —
    ``stated_mechanism TEXT`` on feature 97's table, added by feature 98's
    revision ``0117_identity_trio`` — so persisting one for an id the tree does
    not hold would mean writing a **row**, and the ``node`` table is the
    discovery tree's rather than this member's.

    It is a statement about the *caller's* tree rather than about a proposal,
    so it is not an :class:`AgentSourceError`: no re-prompt repairs it, and the
    repair is to record the node first.  It is a sibling of the two classes
    below rather than a subclass of either, because the three name three
    different repairs — write the node, run the migration chain, point the
    deployment at a store — and an operator who could not tell them apart would
    not know which to do.
    """


class MechanismColumnError(SignalAgentError):
    """The tree store has not reached the revision that adds the column.

    Raised when the database is reachable and holds no ``node`` table, or holds
    one without ``stated_mechanism``.  Both depths are one fact — this tree has
    not reached revision ``0117_identity_trio`` (feature 98) — seen at two
    levels, and the refusal names the revision because that is the whole
    actionable content: a mechanism has a documented prerequisite and this is
    the report that says so.

    The store probes the table rather than letting SQLite raise, which is the
    move :meth:`providers.AgentModelPins._require_columns` makes for its own
    trio and for the same reason: the driver answers *"no such column"* only
    once a statement mentions it, which reports the gap at a point where the
    message is about a statement rather than about the deployment.
    """


class MechanismConflictError(MechanismStatementError):
    """The node already states a *different* mechanism.

    Raised by the mechanism store's write path when a caller offers a statement
    that disagrees with the one the row holds.  A node's stated mechanism is
    history, on the same grounds its authoring model is
    (:class:`providers.ModelPinConflictError`): the rationale is what a human
    reviewer read and what the dedup pass compared against when the node's
    scores were recorded, so replacing it silently would leave every stored
    comparison referring to a claim the row no longer makes.

    **It is a subclass of :class:`MechanismStatementError`, and that is the
    opposite of the choice the four deployment classes make.**  The subject here
    *is* the proposal's statement — the caller is trying to record one, and
    recording a statement is what the write path's statement contract governs —
    so a caller that already catches *"this mechanism cannot be persisted as
    stated"* must not lose the conflict through a clause that no longer matches.
    The difference is *repair*, which is why it is also its own class rather
    than a bare ``MechanismStatementError``: a value that is not text or is
    blank is repaired by re-prompting the agent, and a conflict is repaired by
    the caller accepting that the node is spoken for.  Two repairs, one
    contract, one class each, and
    :data:`~signal_agent._mechanism.MECHANISM_CONFLICT_CODE` is the token that
    tells them apart in a log — the same arrangement
    :class:`IllegalThemeError` has under :class:`AgentSourceError`.
    """


class MechanismStoreUnavailableError(SignalAgentError):
    """The composed component carries no store, so nothing can be persisted.

    Raised when the mechanism law was composed with ``store=None`` — the state
    a deployment reaches by naming no ``DATABASE_URL`` — and a caller then asks
    it to persist, read back, or report duplicates.  The barrier clause is
    still answerable in that state, because it is a fact about the *caller*
    rather than about a row, and that is why ``None`` is a discoverable
    composition state rather than a builder that raises.

    **It is not an empty store.**  An empty store answers *no node states a
    mechanism here* about every id; this class says there is no database to
    have recorded one in.  The distinction is the one
    :func:`providers.build_agent_model_pins` draws for its own ``None``, and it
    matters here for the same reason: a mechanism persisted into nothing is a
    rationale no reviewer will ever read.
    """


class TruncatedHistoryError(SignalAgentError):
    """A history of prior proposals is not the whole history.

    Raised by :meth:`~signal_agent.ProposalHistory.require` — feature 206's
    bridge between the law's returned verdict and the exception a caller wants
    on its last line before the authoring call.  The message is the law's own
    sentence, opening with the code of the reason that produced it —
    ``truncated_history``, ``sampled_history``, ``missing_proposal`` or
    ``not_a_history`` — so a campaign log and an operator's grep say the same
    thing.

    **It is a sibling of :class:`AgentSourceError`, not a subclass, and the
    asymmetry is the one :class:`FlawedMechanismError` states.**  The three
    refusals under that base are facts about *what the agent wrote*, and a
    caller's pre-existing ``except AgentSourceError:`` handler exists to
    re-prompt.  This refusal is a fact about the *run*: the agent has not been
    called, because the prompt it would be called with was assembled from a
    history that is a sample, or cut short, or missing proposals the round
    declared.  A caller that caught this through the source contract's clause
    would re-prompt against the same partial history and get another proposal
    from it, which is the failure §14.1's *"not a sample, not recent cycles"*
    is written against.

    **It is also a sibling of :class:`FlawedMechanismError`**, though both
    say "do not re-prompt", because the subjects differ in kind: that one is a
    judgment about a hypothesis reached from a failure the evaluator reported,
    and this one is a judgment about the caller's own read, reached before any
    proposal exists.  The repairs differ too — the diagnosis closes the branch
    and opens another mechanism; this one fixes the assembler and re-runs the
    step.

    The distinct class buys the query: "how often did a round read a partial
    history?" is precisely the measurement §14.1:773 says is missing, because
    *"Truncating complete proposals is a different operation from compressing
    them into prose, and is probably safer — but it is an untested assumption
    and should be measured before it is relied on."*  A caller that had to
    match message text to count that would not measure it.

    No agent action repairs it, so it is not raised for anything the agent
    wrote; the offending entries are **named** in the sentence and never
    quoted, because the text of a proposal belongs in §9.2's artifact
    directory rather than in a log line.
    """


class InjectedGuidanceError(SignalAgentError):
    """An authoring prompt carries injected summarized directional guidance.

    Raised by :meth:`~signal_agent.GuidanceVerdict.require` and
    :meth:`~signal_agent.PromptGuidanceGate.require` — feature 208's bridge
    between the gate's returned verdict and the exception a caller wants on
    its last line before the prompt is flattened and shipped.  The message is
    the gate's own sentence, opening with the code of the reason that
    produced it — ``injected_guidance`` for a part declared as guidance by
    its role or its provenance, ``not_prompt_parts`` for a value that carried
    no screenable structure — so a campaign log and an operator's grep say
    the same thing.

    **What it prevents is the counterintuitive mistake.**  PRD §C3's whole
    warning — *"This is counterintuitive and most implementations get it
    backwards"* — is that summarizing the campaign's history into guidance
    for the agent *feels* like an improvement and measurably is not one: the
    paper's Figure 5 found the guided version underperformed the unguided one
    across both paradigms, because strong semantic priors about future search
    directions over-constrain the space and impede diverse exploration.  The
    section this refusal names was added by an implementation that believed
    it was helping, so the refusal carries the finding rather than a bare
    "not allowed" — a caller reading it learns *why* the section it was proud
    of is not in the prompt.

    **It is a sibling of :class:`AgentSourceError`, not a subclass, and the
    asymmetry is the one :class:`TruncatedHistoryError` states.**  The
    refusals under that base are facts about *what the agent wrote*, and a
    caller's pre-existing ``except AgentSourceError:`` handler repairs them
    by re-prompting.  This refusal has nothing to do with what the agent
    wrote: the agent has not been called, because the prompt it would be
    called *with* is the defect.  Letting that handler catch it would
    re-prompt an agent with the same injected guidance still in the prompt —
    buying another over-constrained search from the same over-constrained
    prompt — which is the waste this feature exists to prevent.  The repair
    is to fix the assembler: delete the section, keep the history as the
    interactive replay object §C3 asks for, and re-ship.

    **It is a sibling of :class:`TruncatedHistoryError` and of
    :class:`AntiConvergenceClauseError` rather than folded into either**,
    though all three are prompt-side refusals no re-prompt repairs.  From
    :class:`TruncatedHistoryError` it differs because §14.1:773 draws the
    line itself: *truncating* a complete proposal and *compressing* it into
    prose are different operations with different repairs — finish the read
    versus delete the section — and a caller that could not tell "the history
    arrived cut" from "somebody summarized it into advice" would not know
    which half of the assembler to fix.  From
    :class:`AntiConvergenceClauseError` it differs because the two are
    opposites about the *same* prompt: that one says the prompt is *missing*
    the one prose §C3 requires (the committed clause), and this one says it
    *carries* the class of prose §C3 forbids.  An operator grepping a
    campaign log for either must not find the other.

    The distinct class buys the *query*: "how often did a round's prompt
    carry injected guidance?" is the §14.1:773 instinct — measure the
    assumption before relying on it — applied to the other side of the
    truncation trade, and a caller that had to match message text to count it
    would not measure it.
    """


class ProposalContentError(SignalAgentError):
    """A proposal document or a score record is not something that can be stored.

    Raised by :mod:`signal_agent._proposal` for a value the *caller* got wrong
    rather than a fact about the proposal: a document that is not text or has
    no content, a score that is not a :class:`~signal_agent.ScoreRecord`, a
    node id or campaign id that is not UUID text, a stored row whose document
    does not hash to the identity beside it, or a stored score document that
    does not parse.

    **It is a sibling of :class:`AgentSourceError`, not a subclass, and the
    asymmetry is the one :class:`TruncatedHistoryError` states.**  The refusals
    under that base are facts about *what the agent wrote*, and a caller's
    pre-existing ``except AgentSourceError:`` handler exists to re-prompt.  A
    caller that caught this through that clause would re-prompt an agent whose
    proposal was never the problem — the document it wrote may be perfectly
    good and the *store* be holding a row with a corrupted digest, or the
    caller have passed a mapping where a record belongs.  None of those
    repairs is a re-prompt, so none of them may be reachable through that
    clause.

    The subclass :class:`ProposalConflictError` splits off the one case a
    caller can act on without a repair: the node it named already holds a
    different pair.  Both are greppable — this one by its own class, that one
    by its own.
    """


class ProposalHistoryStoreUnavailableError(SignalAgentError):
    """The composed component carries no store, so no history can be persisted.

    Raised when the proposal-history law was composed with ``store=None`` — the
    state a deployment reaches by naming no ``DATABASE_URL`` — and a caller
    then asks it to persist a pair or read one back.  It is the same split
    :class:`MechanismStoreUnavailableError` draws for feature 211's store, and
    it exists for the same reason: the factory builds every registered
    component on every ``create_app()``, so a builder that raised on a
    deployment with no database would take composition down workspace-wide.

    **It is not an empty store.**  An empty store answers *no proposal is
    recorded here* about every node; this class says there is no database to
    have recorded one in.  The distinction matters more here than it does for
    a single column, because this feature's subject is a *history*: an empty
    store is a campaign that has not proposed anything yet, and a missing store
    is a campaign whose proposals are being thrown away — and §14.1's whole
    read-everything requirement rests on the first being distinguishable from
    the second.

    It is also raised by :func:`signal_agent._proposal._sqlite_path` for a
    ``DATABASE_URL`` this store cannot speak (a non-SQLite scheme, a host, an
    in-memory database).  Those are the same statement at a different moment —
    the deployment has named no store *this member can use* — and a caller's
    repair is the same one: point ``DATABASE_URL`` at the tree.
    """


class ProposalNodeNotRecordedError(SignalAgentError):
    """A node's proposal cannot be recorded, or read, because the tree has no such node.

    Raised on both paths, and the two sentences differ because they answer
    different asks — one was about to write, the other about to read — while
    naming the same repair.  A node's proposal is keyed by the node id
    ``0118`` mints and its score half is *read off that node's row*, so a node
    the tree does not hold has no id to hang a history entry on and no metrics
    to snapshot: the discovery loop records the node first, and feature 232's
    campaign record is the writer that does it.

    It is a distinct class from :class:`ProposalContentError` because the
    repairs are different in kind: that one is a caller's value being wrong,
    and this one is the *tree* being a step behind — an operator reading a
    campaign that recorded nothing needs to know which, because one is a bug
    and the other is a loop that has not reached its persisting step yet.

    It is also raised when the database holds no ``node`` table at all, naming
    ``0118`` — the deployment's migration chain stopping short of the tree
    rather than a missing row.  Same class, because the fix is the same
    operation: bring the chain forward, then record the node.
    """


class ProposalConflictError(ProposalContentError):
    """A node already records a different proposal document, or a different score.

    Raised by :meth:`~signal_agent.ProposalStore.persist` when a node that
    already holds a recorded pair is offered one that disagrees — the same
    document under a different score, or a different document outright.  The
    message names both digests (or both score documents) so an operator can see
    which two writes are claiming one node.

    **The document half is history, not a field.**  It is what a later round
    reads *in full* (architecture §14.1) and what feature 206's identity check
    recomputes over, so replacing it would leave every stored score referring
    to a proposal the row no longer holds — the same argument
    :class:`MechanismConflictError` makes for a node's stated mechanism.  Two
    documents that differ are two proposals, and two proposals are two nodes.

    **The score half is evidence about a round.**  §14.1 reads the history —
    the proposal *plus its score* — to decide what to try next, so the figure
    beside a proposal is what a prior round saw.  A store that updated it in
    place would make every earlier round's reasoning describe a number that no
    longer exists, which is exactly the property feature 207's *"replayable"*
    is written against.  A genuinely new measurement belongs to the new
    attempt's node, and feature 239's derived identity already gives that
    attempt its own id.

    It subclasses :class:`ProposalContentError` because a caller branching on
    *"this value is not storable"* should catch it — and because the retry that
    is **not** a conflict (the identical pair re-issued) returns a record
    rather than raising, so a caller that sees this class knows it is holding a
    genuine disagreement rather than a repeat.
    """


class DiversityCohortError(SignalAgentError):
    """A campaign's diversity figure cannot be counted from the cohort handed in.

    Raised by feature 215's ``tree_diversity`` when the *cohort* it would count
    is not one a figure can be derived from: the handle it was given is not
    feature 207's proposal history, the campaign id names no campaign, the tree
    has not reached revision ``0115_agent_model_trio`` so no per-model stratum
    exists, a recorded proposal's node carries no ``agent_model_id``, or a
    value handed to :class:`~signal_agent.TreeDiversity`'s constructor — or
    built by it — is not a shape a count could have produced.

    **It is deliberately not an :class:`AgentSourceError`.**  Nothing here is
    about a proposal's *source*: the documents themselves may all be perfectly
    good, and no re-prompt repairs a missing column or an unmodellable row.  It
    is not a :class:`ProposalContentError` either, though it is the nearest
    neighbour — that class is about a *value the caller is trying to store*,
    and this one is about a *figure the caller is trying to read*.  A caller's
    ``except ProposalContentError`` handler exists to correct a document before
    writing it, and a diversity refusal moved through that clause would send it
    looking for a document to fix when the fault is in the tree or in the
    arguments.

    **It is a sibling of the two classes feature 215 raises beside it**, on the
    member's usual grounds (feature 186's *"no fourth error class"*, feature
    223's decision 6): the three name three different repairs — fix the tree's
    migration chain, fix the row that lost its model, fix the argument — and a
    single class would leave an operator unable to tell which of the three it
    was holding.  It is deliberately **not** a third spelling of
    :class:`~signal_agent.MechanismColumnError` or
    :class:`~signal_agent.ProposalNodeNotRecordedError`: those two already name
    0117's and 0118's prerequisites for their own features, and feature 215
    raises ``ProposalNodeNotRecordedError`` unchanged for the shared one (an
    absent ``node`` table) rather than minting a duplicate here.
    """


class DiscriminationCohortError(SignalAgentError):
    """A campaign's ``mechanism_discrimination`` cannot be read from the cohort.

    Raised by feature 214's ``mechanism_discrimination`` when §14.1's figure
    cannot be computed — or when a value claiming to *be* it could not have been
    measured.  The four families, in the order the law raises them:

    * **the handle or the arguments** — the object is not feature 207's proposal
      history, the campaign id is not a UUID, or the declared real-branch cohort
      is not a non-empty collection of node ids;
    * **the store's shape** — no ``replay_score`` table (``0109`` unreached, so
      there is no out-of-sample half), no ``campaign`` table (``0111``
      unreached), or a campaign the table does not hold;
    * **the cohort's pairing** — a declared branch with no recorded proposal,
      one whose recorded row belongs to another campaign, one whose snapshot
      carries no ``ir_marginal``, one with no committed run, or runs spanning
      more than one policy version;
    * **the arithmetic** — fewer than four pairs, a constant series on either
      side, an exactly perfect correlation, a gain that is not finite, or a
      stored row whose fields do not reconstruct into a reading.

    **It is deliberately not an :class:`AgentSourceError`**, for
    :class:`DiversityCohortError`'s reason word for word: the proposals behind
    the cohort may all be perfectly good, and no re-prompt of a model produces
    a ``replay_score`` row, a fourth branch, or a run under the cohort's
    revision.  It is not a :class:`ProposalContentError` either — that class is
    about a value the caller is trying to *store*, and this one is about a
    figure the caller is trying to *read*.  A caller holding this class has four
    different repairs in front of it and the message names which: bring the
    chain to ``0109``/``0111``, plan the campaign, freeze a cohort the store can
    pair, or expand the campaign until the interval exists.

    **It is a sibling of :class:`DiversityCohortError`, not a superclass or a
    subclass**, and the distinction is load-bearing rather than cosmetic.  The
    two features are handed different cohorts and read different tables, and a
    caller that caught the one while expecting the other would get the wrong
    remediation for a *plausible* reason: both messages say *cohort*, and a
    shared class would make them indistinguishable at the ``except`` line.  The
    member's rule is that a new class must buy a distinction a caller's handler
    can act on — this one buys exactly
    that, and nothing more.

    **Three of the refusals beside it are 207's, reused unchanged.**  An absent
    ``node_proposal`` table raises
    :class:`ProposalHistoryStoreUnavailableError`, an unparseable score document
    raises :class:`ProposalContentError`, and an absent ``node`` table raises
    :class:`ProposalNodeNotRecordedError` — each naming the one fact and the one
    repair it names for feature 207's own callers.  Minting feature-214 spellings
    of those three would be the duplicate class the member refuses: *"the same
    fact with the same repair, whoever asks"*.
    """
