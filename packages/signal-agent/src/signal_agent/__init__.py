"""``signal_agent`` — the hypothesis-authoring agent's contract seam.

app_spec.xml, "Hypothesis Authoring Agent", feature 205: *System writes a
signal function conforming to the declared contract, which returns source
that the sandbox executes.*  This package is that feature, and the category
it opens (``plugin="signal-agent"``, features 205-216) attaches to it: 206's
read-every-proposal-in-full, 207's proposal-plus-score history, 208's refusal
of summarized guidance, 209's retry diagnosis, 210's anti-convergence clause,
211's stated mechanism, 212's legal theme set, 214's mechanism
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

from . import _themes
from ._authoring import (
    CONFORMS_CODE,
    AdoptionReason,
    SignalContract,
    SourceAdoption,
    require_contract,
    signal_contract,
    source_code_hash,
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
    IllegalThemeError,
    SignalAgentError,
    ThemeSetError,
)

__all__ = [
    "AGENT_ROLES",
    "COMMITTED_LEGAL_THEMES",
    "COMPONENT_NAME",
    "CONFORMS_CODE",
    "ILLEGAL_THEME_CODE",
    "LEGAL_THEMES_POLICY_KIND",
    "LEGAL_THEME_CODE",
    "NOT_A_THEME_CODE",
    "THEMES_COMPONENT_NAME",
    "AdoptionReason",
    "AgentSourceError",
    "IllegalThemeError",
    "LegalThemes",
    "SignalAgentError",
    "SignalContract",
    "SignalThemeGate",
    "SourceAdoption",
    "ThemeAdmission",
    "ThemeReason",
    "ThemeSetError",
    "build_signal_contract",
    "build_signal_theme_gate",
    "committed_legal_themes",
    "compile_legal_themes",
    "load_legal_themes",
    "require_contract",
    "signal_contract",
    "signal_theme_gate",
    "source_code_hash",
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
