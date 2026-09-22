"""``signal_agent`` — the hypothesis-authoring agent's contract seam.

app_spec.xml, "Hypothesis Authoring Agent", feature 205: *System writes a
signal function conforming to the declared contract, which returns source
that the sandbox executes.*  This package is that feature, and the category
it opens (``plugin="signal-agent"``, features 205-216) attaches to it: 206's
read-every-proposal-in-full, 207's proposal-plus-score history, 208's refusal
of summarized guidance, 209's retry diagnosis, 210's anti-convergence clause,
211's stated mechanism, 212's legal theme set, 213's dead-territory refusal,
214's mechanism
discrimination and 215's tree diversity are each a further statement about
what the agent is asked for and what is recorded about the asking.

**Feature 212 rides the same seat.**  *System rejects a proposal whose theme
root falls outside the configured legal set, which returns an illegal_theme
error message* is the second feature this member owns a law for, and it lives
in :mod:`signal_agent._themes`: one committed artifact
(:data:`COMMITTED_LEGAL_THEMES`, PRD §9.3's six), one compiler that refuses a
document that is not a set, and :class:`SignalThemeGate` — the law, which
answers as a value and raises only at ``require``.  It composes as a second
component under :data:`THEMES_COMPONENT_NAME` rather than replacing feature
205's, for the registry-replacement reason below.

**Feature 213 rides a third seat, beside it — and is deliberately not part of
it.**  *System rejects any root opening in structurally dead territory such as
sub-30-minute liquidity-taking strategies* is the third feature this member
owns a law for, and it lives in :mod:`signal_agent._dead_territory`: one
committed artifact (:data:`COMMITTED_DEAD_TERRITORY`, PRD §9.4's three), one
compiler that refuses a document that is not a list, and
:class:`DeadTerritoryGate` — the law, which answers as a value and raises only
at ``require``.  It composes as a third component under
:data:`DEAD_TERRITORY_COMPONENT_NAME` rather than replacing feature 205's or
feature 212's, for the registry-replacement reason below.  It is a *denylist*
where feature 212 is an *allowlist* — feature 212 asks *is the space admitted?*,
feature 213 asks *is the mechanism live?* — and the two laws are independent
questions, so the second gate carries nothing of the first's set.  A proposal
is admitted only when feature 212 admits its space *and* feature 213 clears its
mechanism; the two refusals are distinct classes (:class:`IllegalThemeError`
and :class:`DeadTerritoryError`), each greppable on its own.

**Feature 211 and feature 210 each ride their own seat too.**  Feature 211's
*stated mechanism* lives in :mod:`signal_agent._mechanism`; feature 210's
*explicit anti-convergence clause* lives in
:mod:`signal_agent._anti_convergence`, and it is the member's only law whose
subject is a *pair* — the prompt a campaign ships against the proposal it is
about to open.  It compiles one committed clause
(:data:`COMMITTED_ANTI_CONVERGENCE`, PRD §C3's, quoted verbatim from the PRD),
screens a campaign's authoring prompt against it verbatim
(:meth:`AntiConvergenceGate.require_in`), and judges each proposal's
*structure with every numeric literal erased* against the campaign's own
history (:meth:`AntiConvergenceGate.admit`) — which is the one axis
docs/nullius-tech-architecture.md §14.1 says nothing downstream catches: a bad
proposal costs one trial charge to refuse, but *"a converged tree is not caught
by anything"*.  It composes as a fifth component under
:data:`ANTI_CONVERGENCE_COMPONENT_NAME`.  It is deliberately not folded into
feature 211's law, which compares what the agent *claims*: a weak model asked
for the 400th variant of one indicator states it in fresh prose, so the claim
differs while the structure repeats.

**Feature 209 rides a sixth seat, and it is the member's second law with no
committed artifact.**  *Agent distinguishes a flawed core mechanism from a
sound idea undermined by a located bug, which returns a retry decision for only
the second case* — PRD §C3's *"the former is not worth retrying, the latter is,
but only with the bug actually located in code rather than guessed from the
write-up"* — lives in :mod:`signal_agent._diagnosis`: no document (what counts
as a located bug is *a position the proposal's own parse tree occupies*,
a fact about the source rather than a deployment decision), one resolution rule
(:func:`locate_defect`), one derived reading of the parser's own position
(:func:`first_defect`), and :class:`MechanismDiagnosis` — the law, which
answers as a value and raises only at ``require``.  It composes as a sixth
component under :data:`DIAGNOSIS_COMPONENT_NAME`, sorting between
``signal-agent-dead-territory`` and ``signal-agent-stated-mechanism`` so the
six stay contiguous.

Its *shape* is the feature: the retry decision is a returned value with
``retry`` **computed** from the reason, and the write-up cannot move it — a
caller's complaint sentences can separate the two refusals from each other but
can never buy a retry, because only a resolved code location can.  That is why
this member's vocabulary gained exactly one class for feature 209 and it is the
*refusal* (:class:`FlawedMechanismError`, a **sibling** of
:class:`AgentSourceError` rather than a subclass, because it asserts the
opposite repair to the three refusals that do subclass — a driver must not
re-prompt a branch the diagnosis just closed).  It is the one law here whose
verdict is about the *idea* rather than about the source, which is feature 211's
subject too and the reason that one's refusals are siblings as well.

**What this member is, and what it deliberately is not.**  §14.1 gives the
signal agent its seat — *"Signal agent, roots (depth 0-1) ... Signal agent,
depth >= 2"* — and PRD §C3 describes it as *"a coding agent writing signal
functions against the §3 contract"*.  The prose, the model choices and the
provider rotation are §14.1's subject and the ``providers`` category's
(192-204); the *prompt text* is a document a campaign ships.  What is left,
and what is load-bearing in a way prose is not, is the **seam**: the one
place that answers *did the agent write a signal function conforming to the
declared contract, and is what it wrote the source the sandbox will
execute?*  That question is asked of every proposal, its answer gates whether
a node exists at all, and it is the question this member owns.

So the member ships a **law** rather than a prompt-builder or an LLM client:
:class:`~signal_agent.SignalContract`, a stateless facade that reads the
declared ABI out of :mod:`contract.signal` — never restating it — judges a
proposal through :func:`contract.validate_signal_signature`, and hands back
the exact source §5.2's ``code=node.code`` will carry together with the
``code_hash`` §9.1 stores.  Nothing here calls a model; nothing here holds a
campaign, a node or a store; nothing here invents a second copy of the
entrypoint's name.

**Why the law and not a prompt.**  A prompt is a document a run records;
it is feature 206-210's subject (what must be read, what must not be
injected, what diagnosis is required) and it changes between campaigns.  The
contract does not change with it: §5.1 declares one entrypoint, feature 15
stamps every stored node with the ABI it was written against, and §12's
replay is bit-reproducible only because the entrypoint is fixed.  A member
that owned the prompt *and* the conformance check would let the second drift
with the first.  This member owns the second, and
:meth:`SignalContract.declaration` emits the first half — the *facts* an agent
is asked to write against — as a mapping, which is the shape that cannot
accidentally become guidance: PRD C3 and §14.1 forbid injecting directional
prose distilled from history, and feature 208 makes refusing it a feature.

**Composition is a plain registration.**  The ``@register("signal-agent")``
builder at the foot of this file fires when the module loader scans the
workspace members the root ``pyproject.toml`` declares — no registry, router,
entry-points table or app factory is edited to wire this in, and the app
package reaches the composed component through the seat at
``src/app/modules/signal-agent/``.

The registration lives **in** ``__init__.py`` rather than in a submodule, and
that is load-bearing twice over.  A submodule's ``@register`` fires only on
the first import in a process, so a second ``create_app()`` would find the
component missing; and the builder must be reachable by the scan, which
imports this package and nothing below it.
"""

from __future__ import annotations

from app.module_loader import register

from . import _dead_territory, _diagnosis, _mechanism, _themes
from ._anti_convergence import (
    ANTI_CONVERGENCE_COMPONENT_NAME,
    ANTI_CONVERGENCE_POLICY_KIND,
    CLAUSE_ABSENT_CODE,
    COMMITTED_ANTI_CONVERGENCE,
    NOT_A_PROPOSAL_CODE,
    NOVEL_CODE,
    PARAMETER_TWEAK_CODE,
    AntiConvergenceClause,
    AntiConvergenceGate,
    AntiConvergenceReason,
    AntiConvergenceVerdict,
    anti_convergence_gate,
    committed_anti_convergence,
    compile_anti_convergence,
    load_anti_convergence,
    proposal_skeleton,
    skeleton_digest,
)
from ._authoring import (
    CONFORMS_CODE,
    AdoptionReason,
    SignalContract,
    SourceAdoption,
    require_contract,
    signal_contract,
    source_code_hash,
)
from ._dead_territory import (
    COMMITTED_DEAD_TERRITORY,
    DEAD_TERRITORY_CODE,
    DEAD_TERRITORY_POLICY_KIND,
    LIVE_TERRITORY_CODE,
    NOT_A_ROOT_CODE,
    DeadTerritory,
    DeadTerritoryGate,
    DeadTerritoryReason,
    DeadTerritoryVerdict,
    committed_dead_territory,
    compile_dead_territory,
    dead_territory_gate,
    load_dead_territory,
)
from ._diagnosis import (
    FLAWED_MECHANISM_CODE,
    LOCATED_BUG_CODE,
    MAX_LISTED_COMPLAINTS,
    MODULE_SYMBOL,
    NOT_A_DIAGNOSIS_CODE,
    SIGNAL_SOURCE_FILENAME,
    DiagnosisReason,
    DiagnosisVerdict,
    LocatedDefect,
    MechanismDiagnosis,
    first_defect,
    locate_defect,
    mechanism_diagnosis,
)
from ._mechanism import (
    CANONICAL_MECHANISM_MAX_WORDS,
    MECHANISM_COLUMN,
    MECHANISM_CONFLICT_CODE,
    MECHANISM_POLICY_REVISION,
    NEVER_SCORED_CODE,
    NOT_A_STATEMENT_CODE,
    STATED_MECHANISM_CODE,
    MechanismReason,
    MechanismRecord,
    MechanismScoredInput,
    MechanismStore,
    StatedMechanism,
    canonical_mechanism,
    mechanism_digest,
    stated_mechanism,
)
from ._themes import (
    COMMITTED_LEGAL_THEMES,
    ILLEGAL_THEME_CODE,
    LEGAL_THEME_CODE,
    LEGAL_THEMES_POLICY_KIND,
    NOT_A_THEME_CODE,
    LegalThemes,
    SignalThemeGate,
    ThemeAdmission,
    ThemeReason,
    committed_legal_themes,
    compile_legal_themes,
    load_legal_themes,
    signal_theme_gate,
)
from .errors import (
    AgentSourceError,
    AntiConvergenceClauseError,
    AntiConvergenceError,
    DeadTerritoryError,
    DeadTerritorySetError,
    FlawedMechanismError,
    IllegalThemeError,
    MechanismColumnError,
    MechanismConflictError,
    MechanismNodeNotRecordedError,
    MechanismNotScoredError,
    MechanismStatementError,
    MechanismStoreUnavailableError,
    SignalAgentError,
    ThemeSetError,
)

__all__ = [
    "AGENT_ROLES",
    "ANTI_CONVERGENCE_COMPONENT_NAME",
    "ANTI_CONVERGENCE_POLICY_KIND",
    "CANONICAL_MECHANISM_MAX_WORDS",
    "CLAUSE_ABSENT_CODE",
    "COMMITTED_ANTI_CONVERGENCE",
    "COMMITTED_DEAD_TERRITORY",
    "COMMITTED_LEGAL_THEMES",
    "COMPONENT_NAME",
    "CONFORMS_CODE",
    "DEAD_TERRITORY_CODE",
    "DEAD_TERRITORY_COMPONENT_NAME",
    "DEAD_TERRITORY_POLICY_KIND",
    "DIAGNOSIS_COMPONENT_NAME",
    "FLAWED_MECHANISM_CODE",
    "ILLEGAL_THEME_CODE",
    "LEGAL_THEMES_POLICY_KIND",
    "LEGAL_THEME_CODE",
    "LIVE_TERRITORY_CODE",
    "LOCATED_BUG_CODE",
    "MAX_LISTED_COMPLAINTS",
    "MECHANISM_COLUMN",
    "MECHANISM_CONFLICT_CODE",
    "MECHANISM_POLICY_REVISION",
    "MODULE_SYMBOL",
    "NEVER_SCORED_CODE",
    "NOT_A_DIAGNOSIS_CODE",
    "NOT_A_PROPOSAL_CODE",
    "NOT_A_ROOT_CODE",
    "NOT_A_STATEMENT_CODE",
    "NOT_A_THEME_CODE",
    "NOVEL_CODE",
    "PARAMETER_TWEAK_CODE",
    "SIGNAL_SOURCE_FILENAME",
    "STATED_MECHANISM_CODE",
    "STATED_MECHANISM_COMPONENT_NAME",
    "THEMES_COMPONENT_NAME",
    "AdoptionReason",
    "AgentSourceError",
    "AntiConvergenceClause",
    "AntiConvergenceClauseError",
    "AntiConvergenceError",
    "AntiConvergenceGate",
    "AntiConvergenceReason",
    "AntiConvergenceVerdict",
    "DeadTerritory",
    "DeadTerritoryError",
    "DeadTerritoryGate",
    "DeadTerritoryReason",
    "DeadTerritorySetError",
    "DeadTerritoryVerdict",
    "DiagnosisReason",
    "DiagnosisVerdict",
    "FlawedMechanismError",
    "IllegalThemeError",
    "LegalThemes",
    "LocatedDefect",
    "MechanismColumnError",
    "MechanismConflictError",
    "MechanismDiagnosis",
    "MechanismNodeNotRecordedError",
    "MechanismNotScoredError",
    "MechanismReason",
    "MechanismRecord",
    "MechanismScoredInput",
    "MechanismStatementError",
    "MechanismStore",
    "MechanismStoreUnavailableError",
    "SignalAgentError",
    "SignalContract",
    "SignalThemeGate",
    "SourceAdoption",
    "StatedMechanism",
    "ThemeAdmission",
    "ThemeReason",
    "ThemeSetError",
    "anti_convergence_gate",
    "build_anti_convergence",
    "build_dead_territory_gate",
    "build_mechanism_diagnosis",
    "build_signal_contract",
    "build_signal_theme_gate",
    "build_stated_mechanism",
    "canonical_mechanism",
    "committed_anti_convergence",
    "committed_dead_territory",
    "committed_legal_themes",
    "compile_anti_convergence",
    "compile_dead_territory",
    "compile_legal_themes",
    "dead_territory_gate",
    "first_defect",
    "load_anti_convergence",
    "load_dead_territory",
    "load_legal_themes",
    "locate_defect",
    "mechanism_diagnosis",
    "mechanism_digest",
    "proposal_skeleton",
    "require_contract",
    "signal_contract",
    "signal_theme_gate",
    "skeleton_digest",
    "source_code_hash",
    "stated_mechanism",
]

#: The component name this member registers under.  The spec's own plugin name
#: (``plugin="signal-agent"``), spelled once here so the composed application,
#: the app-namespace seat and this member's tests share one string rather than
#: three.
COMPONENT_NAME = "signal-agent"

#: The two roles §14.1 splits the signal agent into.  Declared as data because
#: the *tiering* is a fact about this category that later features state
#: refusals around (198-202 are about what a depth model must carry, 196-197
#: record which provider served a root call), and a role name spelled three
#: times is three spellings that can drift.  The tuple is ordered as §14.1's
#: table orders it: roots first, then depth.
AGENT_ROLES = ("root", "depth")

#: The component name feature 212's gate registers under.  Imported from
#: :mod:`signal_agent._themes` rather than re-spelled — the ``__all__`` entry
#: above re-exports it, so this is a name, not a second literal.  Unlike
#: :data:`COMPONENT_NAME`, which the spec's plugin declaration owns and which
#: this module is the single spelling of, this one is *also* the live name the
#: submodule's own doc references and its tests assert on, and two literals for
#: it would be the drift the single spelling exists to prevent.
#:
#: Prefixed, because the registry is keyed by name and this member now carries
#: two components: an unprefixed second registration would be a *spelling* of
#: ``signal-agent`` that replaced feature 205's law rather than sitting beside
#: it, which is the registry-replacement hazard
#: :data:`sandbox.imports.IMPORTS_COMPONENT_NAME` names for its own member.
#: ``signal-agent-themes`` sorts immediately after ``signal-agent`` in the
#: name-sorted ``app.order``, so the pair stays adjacent to the category it
#: belongs to.
THEMES_COMPONENT_NAME = _themes.THEMES_COMPONENT_NAME

#: The component name feature 213's gate registers under.  Imported from
#: :mod:`signal_agent._dead_territory` rather than re-spelled — the ``__all__``
#: entry above re-exports it, so this is a name, not a second literal.  Unlike
#: :data:`COMPONENT_NAME`, which the spec's plugin declaration owns and which
#: this module is the single spelling of, this one is *also* the live name the
#: submodule's own doc references and its tests assert on, and two literals for
#: it would be the drift the single spelling exists to prevent.
#:
#: Prefixed, for the same reason :data:`THEMES_COMPONENT_NAME` is — an
#: unprefixed ``signal-agent`` a third time would replace feature 205's law —
#: and ``signal-agent-dead-territory`` sorts between ``signal-agent`` and
#: ``signal-agent-themes`` in the name-sorted ``app.order``, so the member's
#: three components stay contiguous in the category they belong to.
DEAD_TERRITORY_COMPONENT_NAME = _dead_territory.DEAD_TERRITORY_COMPONENT_NAME

#: The component name feature 211's law registers under.  Imported from
#: :mod:`signal_agent._mechanism` rather than re-spelled — the ``__all__`` entry
#: above re-exports it, so this is a name, not a second literal.  Unlike
#: :data:`COMPONENT_NAME`, which the spec's plugin declaration owns and which
#: this module is the single spelling of, this one is *also* the live name the
#: submodule's own doc references and its tests assert on, and two literals for
#: it would be the drift the single spelling exists to prevent.
#:
#: Prefixed, for the same reason :data:`THEMES_COMPONENT_NAME` and
#: :data:`DEAD_TERRITORY_COMPONENT_NAME` are — an unprefixed ``signal-agent`` a
#: fourth time would replace feature 205's law — and
#: ``signal-agent-stated-mechanism`` sorts between
#: ``signal-agent-dead-territory`` and ``signal-agent-themes`` in the
#: name-sorted ``app.order``, so the member's four components stay contiguous in
#: the category they belong to.
STATED_MECHANISM_COMPONENT_NAME = _mechanism.STATED_MECHANISM_COMPONENT_NAME

#: The component name feature 209's law registers under.  Imported from
#: :mod:`signal_agent._diagnosis` rather than re-spelled — the ``__all__`` entry
#: above re-exports it, so this is a name, not a second literal.  Unlike
#: :data:`COMPONENT_NAME`, which the spec's plugin declaration owns and which
#: this module is the single spelling of, this one is *also* the live name the
#: submodule's own doc references and its tests assert on, and two literals for
#: it would be the drift the single spelling exists to prevent.
#:
#: Prefixed, for the same reason :data:`THEMES_COMPONENT_NAME`,
#: :data:`DEAD_TERRITORY_COMPONENT_NAME` and
#: :data:`STATED_MECHANISM_COMPONENT_NAME` are — an unprefixed ``signal-agent``
#: a sixth time would replace feature 205's law — and
#: ``signal-agent-diagnosis`` sorts between ``signal-agent-dead-territory`` and
#: ``signal-agent-stated-mechanism`` in the name-sorted ``app.order``, so the
#: member's six components stay contiguous in the category they belong to.
DIAGNOSIS_COMPONENT_NAME = _diagnosis.DIAGNOSIS_COMPONENT_NAME


@register(COMPONENT_NAME)
def build_signal_contract() -> SignalContract:
    """Contribute feature 205's law to the composed application.

    The factory calls this during :func:`app.module_loader.create_app`.  It
    returns the stateless law — not a service, not a session, not an LLM
    client — and it **resolves nothing at construction**: the declared ABI is
    read out of :mod:`contract.signal` on the first question asked of the law,
    not here.  That is the same laziness the bootstrap member's world builders
    take for their datasets and the evaluator takes for its pinned image, and
    it is load-bearing for the same reason: the scan imports this package with
    *one* member's ``src/`` on ``sys.path`` at a time, so a builder that
    imported ``contract`` here would make this component's presence in the
    composed application depend on scan order.

    Holding the handle therefore computes nothing and can fail at nothing.  A
    caller that asks the law a question in a workspace where the contract
    member cannot be reached gets a named, actionable
    :class:`ModuleNotFoundError` from :func:`~signal_agent.require_contract`
    at that moment — which is a statement about the deployment's workspace, not
    about a signal, and is reported as such.
    """
    return signal_contract()


@register(THEMES_COMPONENT_NAME)
def build_signal_theme_gate() -> SignalThemeGate:
    """Contribute feature 212's law to the composed application.

    The second component this member contributes, beside feature 205's law
    under its own name — the registry is keyed by name and a later registration
    of ``signal-agent`` would *replace* the authoring law, so a member carrying
    two controls carries two components, each answering its own feature's
    question.  Like :func:`build_signal_contract` it takes no arguments (the
    factory's registration protocol) and returns a law rather than a service,
    a session or an LLM client.

    **It compiles the committed artifact at build time**, which is the one
    place it differs from the builder above, and the difference is the
    feature's: feature 205's ABI is *declared* by another member and read
    lazily so its presence cannot depend on scan order, while feature 212's
    legal set ships inside this package
    (:data:`~signal_agent.COMMITTED_LEGAL_THEMES`), so there is nothing to
    defer and no member to reach.

    That compile can raise, and the raising is confined to the module-level
    convenience (:func:`~signal_agent.signal_theme_gate`), not here.  A drifted
    artifact is *reported*, not swallowed, and the report is the member's own:
    the component is built over the refusal-free path — an empty set, which
    admits nothing and so fails closed rather than open — and a caller that
    must know the set still names PRD §9.3's six asks
    :func:`~signal_agent.committed_legal_themes`, where a named
    :class:`~signal_agent.ThemeSetError` is the right answer.  The division is
    the same one :func:`sandbox.build_sandbox_isolation` draws between what
    composition may raise and what a caller that *requires* something must
    hear: the factory builds every registered component on every
    ``create_app()`` call, so a builder that raised on a drifted artifact would
    take composition down for every unrelated feature in the workspace.

    Holding the handle computes nothing beyond that one file read, and it can
    fail at nothing.
    """
    try:
        return SignalThemeGate(committed_legal_themes())
    except ThemeSetError:
        # Fail closed, as a value rather than by raising: an empty set admits
        # no theme, so a caller that skipped the check above refuses every
        # proposal instead of authoring into an unvalidated space.  Built by
        # construction rather than through the compiler on purpose — the
        # compiler *refuses* an empty set, because a deployment whose document
        # names nothing has not made PRD §9's decision, and that refusal is
        # exactly why this branch cannot reach for it.  A caller that must know
        # why asks `committed_legal_themes()` for the named refusal.
        return SignalThemeGate(
            LegalThemes(kind=LEGAL_THEMES_POLICY_KIND, themes=())
        )


@register(DEAD_TERRITORY_COMPONENT_NAME)
def build_dead_territory_gate() -> DeadTerritoryGate:
    """Contribute feature 213's law to the composed application.

    The third component this member contributes, beside feature 205's law and
    feature 212's gate, each under its own name — the registry is keyed by name
    and a later registration of either would *replace* that law, so a member
    carrying three controls carries three components, each answering its own
    feature's question.  Like the two builders above it takes no arguments (the
    factory's registration protocol) and returns a law rather than a service, a
    session or an LLM client.

    **It compiles the committed artifact at build time**, like feature 212's
    builder and unlike feature 205's: feature 213's dead-territory list ships
    inside this package (:data:`~signal_agent.COMMITTED_DEAD_TERRITORY`), so
    there is nothing to defer and no member to reach.

    That compile can raise, and the raising is confined to the module-level
    convenience (:func:`~signal_agent.dead_territory_gate`), not here.  A
    drifted artifact is *reported*, not swallowed, and the report is the
    member's own: the component is built over the refusal-free path — an empty
    denylist, which refuses nothing and so fails **open** rather than closed —
    and a caller that must know the list still names PRD §9.4's three asks
    :func:`~signal_agent.committed_dead_territory`, where a named
    :class:`~signal_agent.DeadTerritorySetError` is the right answer.

    **Fail open, where feature 212's builder fails closed — the one asymmetry,
    and it is load-bearing.**  Feature 212's builder falls back to an *empty
    set* on a drifted legal set, which admits nothing and so refuses every
    proposal: no legal set means no space, and authoring into no space must
    refuse.  This builder falls back to an *empty denylist* on a drifted
    denylist, which refuses nothing and so admits every proposal: a down
    guardrail is less catastrophic than a system that refuses *every* proposal,
    and the space still exists — feature 212 still judges it.  The compiler
    *refuses* an empty denylist, because a list that names no dead mechanism is
    the absence of PRD §9.4's decision, not a strict denylist; this branch
    hand-builds the empty denylist rather than reaching for the compiler, so
    the compiler's refusal is never the thing a run silently obeys.  The
    division is the same one :func:`sandbox.build_sandbox_isolation` draws
    between what composition may raise and what a caller that *requires*
    something must hear: the factory builds every registered component on every
    ``create_app()`` call, so a builder that raised on a drifted artifact would
    take composition down for every unrelated feature in the workspace.

    Holding the handle computes nothing beyond that one file read, and it can
    fail at nothing.
    """
    try:
        return DeadTerritoryGate(committed_dead_territory())
    except DeadTerritorySetError:
        # Fail open, as a value rather than by raising: an empty denylist
        # refuses no theme, so a caller that skipped the check above admits
        # every proposal instead of refusing them all.  Built by construction
        # rather than through the compiler on purpose — the compiler *refuses*
        # an empty denylist, because a deployment whose document names nothing
        # has not made PRD §9.4's decision, and that refusal is exactly why
        # this branch cannot reach for it.  A caller that must know why asks
        # `committed_dead_territory()` for the named refusal.
        return DeadTerritoryGate(
            DeadTerritory(kind=DEAD_TERRITORY_POLICY_KIND, mechanisms=())
        )


@register(STATED_MECHANISM_COMPONENT_NAME)
def build_stated_mechanism() -> StatedMechanism:
    """Contribute feature 211's law to the composed application.

    The fourth component this member contributes, beside feature 205's law,
    feature 212's gate and feature 213's gate, each under its own name — the
    registry is keyed by name and a later registration of any of them would
    *replace* that law, so a member carrying four controls carries four
    components, each answering its own feature's question.  Like the three
    builders above it takes no arguments (the factory's registration protocol)
    and returns a law rather than a service, a session or an LLM client.

    **This is the one builder in the member that touches the environment, and
    the touching is the whole of what it does differently.**
    :meth:`~signal_agent.MechanismStore.resolve` reads ``DATABASE_URL`` — the
    variable every store on the data spine reads — and answers ``None`` when
    the deployment names none.  That ``None`` is composed rather than refused,
    and the reason is the shape of this feature:

    * The **barrier clause** — *"never as a scored input"* — is a fact about a
      caller's wiring and about §9.1's annotation, not about a row, so it
      answers in a deployment with no database at all.  Composing nothing here
      would make the one guardrail that needs no storage unavailable in exactly
      the deployment that has the least other protection.
    * The **store clause** is then a discoverable absence:
      :attr:`~signal_agent.StatedMechanism.store` reports the ``None`` and the
      four store-backed verbs raise
      :class:`~signal_agent.errors.MechanismStoreUnavailableError` by name.
      That is **not an empty store** — an empty store answers *no node states a
      mechanism here* about every id, while this says there is no database to
      have recorded one in — and the distinction is the one
      :func:`providers.build_agent_model_pins` draws for its own ``None``.

    **No I/O happens here.**  ``MechanismStore.resolve`` constructs a store and
    does not open one: the URL is translated on first use, so building this
    component never touches the disk and a ``DATABASE_URL`` whose scheme this
    member cannot speak is refused by name the first time a mechanism is
    actually persisted.  That is the contract every store in this workspace
    states, and here it also keeps composition free of the file system — which
    is what makes the factory's scan safe to run from any member's ``src/`` on
    ``sys.path``.

    Holding the handle computes nothing and can fail at nothing.
    """
    return stated_mechanism()


@register(ANTI_CONVERGENCE_COMPONENT_NAME)
def build_anti_convergence() -> AntiConvergenceGate:
    """Contribute feature 210's law to the composed application.

    The fifth component this member contributes, beside feature 205's law and
    features 212's, 213's and 211's gates, each under its own name — the
    registry is keyed by name and a later registration of any of them would
    *replace* that law, so a member carrying five controls carries five
    components, each answering its own feature's question.  Its name sorts
    between ``signal-agent`` and ``signal-agent-dead-territory``, so the five
    stay contiguous in the name-sorted ``app.order``.  Like the four builders
    above it takes no arguments (the factory's registration protocol) and
    returns a law rather than a service, a session or an LLM client.

    **It compiles the committed artifact at build time**, like features 212's
    and 213's builders and unlike feature 205's: feature 210's clause ships
    inside this package (:data:`~signal_agent.COMMITTED_ANTI_CONVERGENCE`), so
    there is nothing to defer and no member to reach.

    That compile can raise, and the raising is confined to the module-level
    convenience (:func:`~signal_agent.anti_convergence_gate`), not here — the
    same division feature 213's builder draws, and for the same reason: the
    factory builds every registered component on every ``create_app()`` call, so
    a builder that raised on a drifted artifact would take composition down for
    every unrelated feature in the workspace.  A caller that must know the
    clause still says what PRD §C3 requires asks
    :func:`~signal_agent.committed_anti_convergence`, where a named
    :class:`~signal_agent.errors.AntiConvergenceClauseError` is the right
    answer.

    **This is the one builder whose fallback is a gate that certifies nothing,
    and the fallback is built by construction rather than through the
    compiler.**  The compiler *refuses* a clause with blank text — a clause that
    names nothing is the absence of PRD §C3's decision — so a drifted artifact
    would have to be admitted here as a hand-built empty clause, which is
    exactly why this branch cannot reach for the compiler.

    Which polarity the empty clause takes is the load-bearing decision, and here
    it is the *opposite* of feature 213's, deliberately.  Feature 213's builder
    fails **open** on a drifted denylist: an empty denylist refuses nothing, and
    a down guardrail is less catastrophic than refusing every proposal in a
    space that still exists.  Feature 210's applied half fails the same way — an
    empty comparison set refuses nothing, because a campaign with no proposals
    yet has nowhere to have converged to.  But the *clause* half must fail
    **closed**, and the reason is arithmetic rather than caution: the screen is
    a substring test, the empty string is a substring of every string, so a
    hand-built empty clause would certify **every prompt** — a silent green tick
    on a prompt nobody checked, which is precisely §14.1's "a converged tree is
    not caught by anything" arriving as this member's own answer.  So
    :meth:`~signal_agent.AntiConvergenceGate.carries` refuses to certify when
    its own clause is unreadable, and a drifted artifact means no campaign can
    be screened — refused loudly and by name, until the file is fixed.

    Holding the handle computes nothing beyond that one file read, and it can
    fail at nothing.
    """
    try:
        return AntiConvergenceGate(committed_anti_convergence())
    except AntiConvergenceClauseError:
        # Fail *closed* on the clause half, as a value rather than by raising:
        # an unreadable clause certifies no prompt at all, so `carries` answers
        # False for everything until the artifact is fixed.  Built by
        # construction rather than through the compiler on purpose — the
        # compiler refuses a blank clause, and that refusal is exactly why this
        # branch cannot reach for it.  A caller that must know why asks
        # `committed_anti_convergence()` for the named refusal.
        return AntiConvergenceGate(
            AntiConvergenceClause(
                kind=ANTI_CONVERGENCE_POLICY_KIND,
                slug="anti-convergence",
                title="The explicit anti-convergence clause (unreadable artifact)",
                text="",
            )
        )


@register(DIAGNOSIS_COMPONENT_NAME)
def build_mechanism_diagnosis() -> MechanismDiagnosis:
    """Contribute feature 209's law to the composed application.

    The sixth component this member contributes, beside feature 205's law and
    features 210's, 211's, 212's and 213's gates, each under its own name — the
    registry is keyed by name and a later registration of any of them would
    *replace* that law, so a member carrying six controls carries six
    components, each answering its own feature's question.  Like the five
    builders above it takes no arguments (the factory's registration protocol)
    and returns a law rather than a service, a session or an LLM client.

    **This builder has no fallback branch, and that is the feature rather than
    an omission.**  Features 212's, 213's and 210's builders each compile a
    committed artifact and therefore each need a documented answer for a drifted
    one — a degraded gate built by construction, failing closed or open
    according to which half of the feature is at stake.  Feature 209's law
    compiles *nothing*: what counts as a located bug is *a position the
    proposal's own parse tree occupies*, which is a fact about the source handed
    in at call time rather than a deployment decision recorded in a file.  So
    there is no artifact to drift, no `except` to write, and nothing this
    builder can fail at.

    **It is the member's second builder of feature 205's shape** — a law whose
    construction computes nothing and resolves nothing.  The declared signal ABI
    is read out of the contract member on the first question asked of feature
    205's law; a proposal and its failures are handed *in* on every question
    asked of this one.  Both are what keeps presence in the composed application
    independent of scan order: this builder imports nothing outside this package
    and reaches no member, so the scan that puts one member's ``src/`` on
    ``sys.path`` at a time cannot make this component absent.

    Holding the handle therefore computes nothing and can fail at nothing, and
    the first :meth:`~signal_agent.MechanismDiagnosis.diagnose` is where a
    branch is judged.
    """
    return mechanism_diagnosis()
