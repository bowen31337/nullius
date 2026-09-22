"""Features 205, 206, 208, 209, 210, 211, 212 and 213's plugin seam: composition, and the seats.

Three contracts, all held from the side this member owns:

* **composition by convention** — the factory scans the workspace, imports
  this package, the ``@register`` builders fire, and the composed application
  carries a ``signal-agent`` component, a ``signal-agent-anti-convergence`` one,
  a ``signal-agent-dead-territory`` one, a ``signal-agent-diagnosis`` one, a
  ``signal-agent-guidance`` one, a ``signal-agent-history`` one, a
  ``signal-agent-stated-mechanism`` one and a ``signal-agent-themes`` one under
  the member's own names.  No registry, router, entry-points table or app
  factory was edited to make that true, and this suite keeps it true under the
  three loader hazards the bootstrap, sandbox and cost-model suites state for
  their own components: the synthetic-name copy (pin by name, module suffix and
  behaviour — never ``isinstance``), the second composition (a ``@register``
  outside ``__init__.py`` would fire once and silently drop out of every later
  ``create_app()``; all eight builders live in ``__init__.py`` and the test
  asserts on the *second* application or it passes vacuously), and the
  **registry-replacement** hazard a second component introduces — the registry
  is keyed by name, so a builder that took ``signal-agent`` for itself would
  silently replace feature 205's law rather than sit beside it, which is why
  the eight are asserted together and each law is checked *after* all eight
  fired.

* **the seats** — ``app.modules.signal-agent`` answers *what is the composed
  authoring law?*, and ``.anti_convergence``, ``.dead_territory``,
  ``.diagnosis``, ``.guidance``, ``.history``, ``.mechanism`` and ``.themes``
  answer it for the seven laws that follow, each importing the member only
  under ``TYPE_CHECKING`` and answering ``None`` — not an exception — when
  nothing is registered.  A seat's
  ``None`` is a statement about *composition*, never about a proposal: the
  verdicts are the laws' own returned values, and reading one ``None`` as "no
  signal was adopted", "the agent opened in an illegal theme" or "the mechanism
  is live" would collapse a deployment problem into a research result.  Three
  of the seats' ``None`` values matter twice over, because a composed law that
  answers *the opposite way* is the opposite complaint — feature 212's admits
  nothing on a drifted artifact, so it refuses every proposal; feature 210's
  applied half admits everything on an empty campaign; and feature 209's
  answers *do not retry* every branch it is asked about, which the seat's
  ``None`` must not be read as — and an operator who could not tell them apart
  would not know whether to widen the document, fix the clause or re-prompt the
  agent.

Each seat's directory name carries a hyphen and so is not a valid dotted import
path; they are reached the way the factory reaches such a package —
``importlib.import_module`` with the hyphenated name.
"""

from __future__ import annotations

import importlib
import inspect
import uuid
from pathlib import Path

import pytest
import signal_agent as member

from app.module_loader import (
    Application,
    Registration,
    create_app,
    workspace_scan_roots,
)

MEMBER_SRC = Path(member.__file__).resolve().parent.parent

# The seats' directory names are hyphenated, so importlib loads them the way
# the factory's scan does.
seat = importlib.import_module("app.modules.signal-agent")
theme_seat = importlib.import_module("app.modules.signal-agent.themes")
dead_seat = importlib.import_module("app.modules.signal-agent.dead_territory")
mechanism_seat = importlib.import_module("app.modules.signal-agent.mechanism")
anti_convergence_seat = importlib.import_module(
    "app.modules.signal-agent.anti_convergence"
)
diagnosis_seat = importlib.import_module("app.modules.signal-agent.diagnosis")
history_seat = importlib.import_module("app.modules.signal-agent.history")
guidance_seat = importlib.import_module("app.modules.signal-agent.guidance")

_CONFORMING = (
    "def signal(ctx, seed):\n"
    "    return pl.Series([1.0] * len(ctx.universe))\n"
)

#: A root the committed set names, and one it does not.  Taken from the
#: artifact's own vocabulary rather than invented, so a claim about the
#: *composed* gate is a claim about the deployment's set.
_LEGAL_THEME = "order-flow-imbalance"
_ILLEGAL_THEME = "sub-30-minute-liquidity-taking"

#: A mechanism the committed denylist names as dead.  Taken from the artifact's
#: own vocabulary rather than invented, so a claim about the *composed* gate is
#: a claim about the deployment's denylist.
_DEAD_MECHANISM = "sub-30-minute-liquidity-taking"
_LIVE_MECHANISM = "order-flow-imbalance"

#: A stated mechanism for the composed-law check.  Not from any committed
#: artifact — feature 211 has none, its subject is what the *agent* wrote — so
#: this is prose of the shape a rationale takes, spelled once and compared
#: across the loader's two copies of the member.
_STATED_MECHANISM = (
    "Cross-sectional momentum decays after liquidity shocks; fade the "
    "third-day reversal."
)

#: A proposal the campaign already holds, and the 400th variant of it — one
#: indicator, two lookbacks.  Feature 210's headline case spelled in the
#: smallest source that shows it, so a claim about the *composed* gate is a
#: claim about §14.1's collapse rather than about an abstraction.
_HELD = "def signal(ctx, seed):\n    return ctx.close.rolling_mean(20)\n"
_TWEAK = "def signal(ctx, seed):\n    return ctx.close.rolling_mean(60)\n"

#: A proposal the parser hands back a position for, and the failure sentence a
#: deployment would have seen first.  Feature 209's headline case spelled in the
#: smallest pair that shows it — a missing colon, and the sentence the contract
#: validator reports for the source that follows — so a claim about the
#: *composed* diagnosis is a claim about §C3's distinction rather than about an
#: abstraction.
_BROKEN = "def signal(ctx, seed)\n    return ctx.close.rolling_mean(20)\n"
_COMPLAINT = "signal source does not compile: expected ':'"

#: A prior proposal and the node it belongs to, for feature 206's composed-law
#: check.  Not from any committed artifact — like feature 211 and feature 209,
#: this law compiles nothing; what counts as the whole history is the caller's
#: own tree query — so this is one proposal of the shape a history carries,
#: spelled once and compared across the loader's two copies.
_PRIOR_PROPOSAL = "def signal(ctx, seed):\n    return ctx.close.rolling_mean(20)\n"
_HISTORY_NODE = "1f3d2b4a-5c6e-4f70-8192-a3b4c5d6e7f8"

#: An authoring prompt of declared parts, and the same prompt with one part
#: that declares itself distilled from the history, for feature 208's
#: composed-law check.  Not from any committed artifact — like the history law,
#: this gate compiles nothing; what counts as injected guidance is a
#: declaration the prompt's own parts carry — so these are the shapes an
#: assembler produces, spelled once and compared across the loader's two
#: copies.
_UNGUIDED_PARTS = {
    "contract": "entrypoint signal(ctx, seed); universe closes",
    "history": _PRIOR_PROPOSAL,
}
_GUIDED_PARTS = dict(
    _UNGUIDED_PARTS,
    context={"text": "prefer continuation", "derived_from": "prior proposals"},
)


def _assert_is_the_authoring_law(component: object) -> None:
    """The composed component is the law, across the loader's copies.

    Name, then behaviour — the discipline the bootstrap member's component
    test states, because the loader imports the member under a synthetic name
    and ``isinstance`` across the two copies cannot hold.  The behaviour check
    is the decisive one and it is the feature's own subject: the composed law
    must *adopt* the source the canonically-imported law adopts, and refuse
    what it refuses, with the same code hash.
    """
    assert type(component).__name__ == "SignalContract"
    assert type(component).__module__.endswith("signal_agent._authoring")

    for verb in ("adopt", "validate", "signature", "declaration"):
        assert callable(getattr(component, verb)), verb

    composed = component.adopt(_CONFORMING)  # type: ignore[attr-defined]
    direct = member.signal_contract().adopt(_CONFORMING)
    assert composed.adopted == direct.adopted
    assert composed.reason == direct.reason
    assert composed.code_hash == direct.code_hash
    # Compared by value: the composed law's declaration is assembled from the
    # scanned copy's contract member, so the two mappings are equal but their
    # `accessors` tuples come from two module objects.  The values are the
    # claim; object identity across the boundary is not available.
    assert dict(component.declaration()) == dict(  # type: ignore[attr-defined]
        member.signal_contract().declaration()
    )


# -- Composition -------------------------------------------------------------


def test_the_member_registers_under_the_specs_plugin_name() -> None:
    # The spec's own spelling (``plugin="signal-agent"``) and the member's are
    # one string; three spellings of one name is exactly the drift a test is
    # cheaper than.
    assert member.COMPONENT_NAME == "signal-agent"


def test_the_member_is_declared_in_the_scanned_workspace() -> None:
    member_root = MEMBER_SRC.parent
    assert (member_root / "pyproject.toml").is_file()
    assert MEMBER_SRC in workspace_scan_roots()


def test_the_scanned_application_carries_the_authoring_law() -> None:
    registry = Registration()
    app = create_app(MEMBER_SRC, registry=registry)
    assert "signal-agent" in app
    assert "signal-agent" in app.order
    _assert_is_the_authoring_law(app.get("signal-agent"))


def test_the_whole_workspace_composes_the_component_too() -> None:
    # The member's own scan root is not a special case: the declared workspace
    # is what the production factory scans.
    app = create_app()
    assert "signal-agent" in app
    _assert_is_the_authoring_law(app.get("signal-agent"))


def test_the_component_survives_a_second_composition() -> None:
    # The submodule-registration hazard: a ``@register`` outside ``__init__.py``
    # fires once, on the first import in the process, and silently drops out of
    # every later ``create_app()``.  Asserting on the *second* application is
    # what makes this test non-vacuous.
    first = create_app(MEMBER_SRC, registry=Registration())
    second = create_app(MEMBER_SRC, registry=Registration())
    assert "signal-agent" in first
    assert "signal-agent" in second
    _assert_is_the_authoring_law(second.get("signal-agent"))


def test_building_the_component_resolves_nothing() -> None:
    # The builder allocates one stateless law: the declared ABI is read out of
    # the contract member on the first question asked, not at composition time.
    # That is what keeps this component's presence independent of scan order,
    # and it is why holding the handle can fail at nothing.
    app = create_app(MEMBER_SRC, registry=Registration())
    law = app.get("signal-agent")
    assert law is not None
    assert type(law).__slots__ == ()
    # No contract attribute is cached on it, so there is nothing to go stale.
    assert not any(
        name in type(law).__dict__ for name in ("_contract", "contract", "_abi")
    )


# -- Feature 212's component ---------------------------------------------------


def _assert_is_the_theme_law(component: object) -> None:
    """The composed gate is the law, across the loader's copies.

    Name, then behaviour — never ``isinstance``, for the same reason the
    authoring law's check above is not.  The decisive check is feature 212's
    own subject: the composed gate must refuse what the canonically-imported
    one refuses, with the same ``illegal_theme`` message.
    """
    assert type(component).__name__ == "SignalThemeGate"
    assert type(component).__module__.endswith("signal_agent._themes")

    for verb in ("admit", "require", "covers", "legal", "title"):
        assert callable(getattr(component, verb)), verb

    composed = component.admit(_ILLEGAL_THEME)  # type: ignore[attr-defined]
    direct = member.signal_theme_gate().admit(_ILLEGAL_THEME)
    assert composed.admitted == direct.admitted is False
    assert composed.reason == direct.reason
    assert composed.detail == direct.detail
    # And the read side, compared by value: the composed gate's set comes from
    # the scanned copy's module, so the tuples are equal but are not the same
    # object across the loader's boundary.  The slugs are the claim.
    assert tuple(component.legal()) == tuple(  # type: ignore[attr-defined]
        member.signal_theme_gate().legal()
    )


def _assert_is_the_dead_territory_law(component: object) -> None:
    """The composed dead-territory gate is the law, across the loader's copies.

    Name, then behaviour — never ``isinstance``, for the same reason the
    authoring law's check above is not.  The decisive check is feature 213's
    own subject: the composed gate must refuse what the canonically-imported
    one refuses, with the same ``dead_territory`` message.
    """
    assert type(component).__name__ == "DeadTerritoryGate"
    assert type(component).__module__.endswith("signal_agent._dead_territory")

    for verb in ("admit", "require", "covers", "dead", "title"):
        assert callable(getattr(component, verb)), verb

    composed = component.admit(_DEAD_MECHANISM)  # type: ignore[attr-defined]
    direct = member.dead_territory_gate().admit(_DEAD_MECHANISM)
    assert composed.admitted == direct.admitted is False
    assert composed.reason == direct.reason
    assert composed.detail == direct.detail
    # And the read side, compared by value: the composed gate's list comes from
    # the scanned copy's module, so the tuples are equal but are not the same
    # object across the loader's boundary.  The mechanisms are the claim.
    assert tuple(component.dead()) == tuple(  # type: ignore[attr-defined]
        member.dead_territory_gate().dead()
    )


def _assert_is_the_mechanism_law(component: object) -> None:
    """The composed stated-mechanism law is the law, across the loader's copies.

    Name, then behaviour — never ``isinstance``, for the same reason the three
    checks above are not.  The decisive check here is feature 211's own
    *barrier* clause: the composed law must refuse the mechanism as a scored
    input with the same ``never_scored`` sentence, because that clause is the
    half of the feature that is answerable with no store at all and therefore
    the half every composition carries.  The store is *not* asserted present —
    a deployment composes this law with ``DATABASE_URL`` naming whatever it
    names, and the component test must not depend on the machine's environment.
    """
    assert type(component).__name__ == "StatedMechanism"
    assert type(component).__module__.endswith("signal_agent._mechanism")

    for verb in ("persist", "load", "duplicates", "stated", "scored_input"):
        assert callable(getattr(component, verb)), verb
    assert hasattr(type(component), "store"), "the store property is the handle's"

    composed = component.scored_input(_STATED_MECHANISM)  # type: ignore[attr-defined]
    direct = member.stated_mechanism().scored_input(_STATED_MECHANISM)
    assert composed.scored == direct.scored is False
    assert composed.detail == direct.detail
    # And the record's digest, compared by value across the boundary: the
    # composed law hashes with the scanned copy's module, so the digests are
    # equal but the strings are not the same object.  The digest is the claim.
    composed_record = member.MechanismRecord(
        node_id=str(uuid.uuid4()),
        reason=member.MechanismReason.STATED,
        detail="composed",
        statement=_STATED_MECHANISM,
    )
    assert composed_record.digest == member.mechanism_digest(_STATED_MECHANISM)


def _assert_is_the_anti_convergence_law(component: object) -> None:
    """The composed anti-convergence gate is the law, across the loader's copies.

    Name, then behaviour — never ``isinstance``, for the same reason the four
    checks above are not.  Feature 210 has two halves and this helper asserts
    both, because a gate that carried one and not the other would be a
    component that answered half its feature's question:

    * the *clause* half — the composed gate's clause text must equal the
      canonically-imported one's, and the composed gate must therefore certify
      a prompt built from it.  Compared by value: the composed gate's clause
      comes from the scanned copy's module, so the strings are equal but are
      not the same object across the loader's boundary;
    * the *applied* half — the composed gate must refuse a tweak with the same
      ``parameter_tweak`` sentence the canonically-imported one refuses it
      with, since that refusal is what feature 210's headline sentence is
      about.
    """
    assert type(component).__name__ == "AntiConvergenceGate"
    assert type(component).__module__.endswith("signal_agent._anti_convergence")

    for verb in ("admit", "require", "covers", "carries", "require_in", "text"):
        assert callable(getattr(component, verb)), verb
    assert hasattr(type(component), "clause"), "the clause property is the handle's"

    direct = member.anti_convergence_gate()
    assert component.text() == direct.text()  # type: ignore[attr-defined]
    assert component.carries(direct.text()) is True  # type: ignore[attr-defined]

    composed = component.admit(_TWEAK, held=[("n1", _HELD)])  # type: ignore[attr-defined]
    expected = direct.admit(_TWEAK, held=[("n1", _HELD)])
    assert composed.admitted == expected.admitted is False
    assert composed.reason == expected.reason
    assert composed.detail == expected.detail
    assert composed.digest == expected.digest


def _assert_is_the_diagnosis_law(component: object) -> None:
    """The composed diagnosis is the law, across the loader's copies.

    Name, then behaviour — never ``isinstance``, for the same reason the five
    checks above are not.  Feature 209 has three clauses and this helper asserts
    all three, because a component that answered two of them would be one that
    decided the feature's question by halves:

    * *the distinction* — the composed law must resolve a defect in a proposal's
      own code to the same position the canonically-imported one resolves it to,
      compared by value across the loader's boundary;
    * *the retry for only the second case* — the composed law must refuse a
      branch whose source is what its author meant to write, with the same
      ``flawed_mechanism`` sentence, and must admit the one whose source does
      not parse;
    * *located in code rather than guessed from the write-up* — the same
      complaints handed to both copies must not move either one's ``retry``
      across the boundary.
    """
    assert type(component).__name__ == "MechanismDiagnosis"
    assert type(component).__module__.endswith("signal_agent._diagnosis")

    for verb in ("diagnose", "require", "retry", "locate"):
        assert callable(getattr(component, verb)), verb

    direct = member.mechanism_diagnosis()
    composed_located = component.locate(_HELD, 1)  # type: ignore[attr-defined]
    expected_located = direct.locate(_HELD, 1)
    assert composed_located is not None and expected_located is not None
    assert (composed_located.line, composed_located.column) == (
        expected_located.line,
        expected_located.column,
    )
    assert composed_located.symbol == expected_located.symbol
    assert composed_located.source_line == expected_located.source_line

    composed = component.diagnose(_BROKEN, [_COMPLAINT])  # type: ignore[attr-defined]
    expected = direct.diagnose(_BROKEN, [_COMPLAINT])
    assert composed.retry == expected.retry is True
    assert composed.reason == expected.reason
    assert composed.detail == expected.detail
    assert composed.defect is not None and expected.defect is not None
    assert composed.defect.source_line == expected.defect.source_line

    composed_flawed = component.diagnose(_HELD, [_COMPLAINT])  # type: ignore[attr-defined]
    expected_flawed = direct.diagnose(_HELD, [_COMPLAINT])
    assert composed_flawed.retry == expected_flawed.retry is False
    assert composed_flawed.reason == expected_flawed.reason
    assert composed_flawed.detail == expected_flawed.detail


def _assert_is_the_history_law(component: object) -> None:
    """The composed history law is the law, across the loader's copies.

    Name, then behaviour — never ``isinstance``, for the same reason the six
    checks above are not.  Feature 206 has two clauses and this helper asserts
    both, because a component that answered one of them would be a law that
    read the loader's declarations without ever checking the text:

    * *in full* — the composed law must refuse a proposal whose carried text
      does not hash to the identity §9.1 recorded for it, with the same
      ``truncated_history`` sentence, and admit the same history the
      canonically-imported law admits, compared by value across the boundary;
    * *not a sample* — the same declared-subset entry handed to both copies
      must not move either one's ``complete`` across the loader's boundary.
    """
    assert type(component).__name__ == "ProposalHistory"
    assert type(component).__module__.endswith("signal_agent._history")

    for verb in ("admit", "complete"):
        assert callable(getattr(component, verb)), verb

    direct = member.proposal_history()
    whole = [
        {
            "node_id": _HISTORY_NODE,
            "proposal": _PRIOR_PROPOSAL,
            "code_hash": member.source_code_hash(_PRIOR_PROPOSAL),
        }
    ]
    composed = component.admit(whole, prior_nodes=[_HISTORY_NODE])  # type: ignore[attr-defined]
    expected = direct.admit(whole, prior_nodes=[_HISTORY_NODE])
    assert composed.complete == expected.complete is True
    assert composed.reason == expected.reason
    assert composed.detail == expected.detail
    assert [entry.proposal for entry in composed.entries] == [
        entry.proposal for entry in expected.entries
    ]

    cut = [
        {
            "node_id": _HISTORY_NODE,
            "proposal": _PRIOR_PROPOSAL[:12],
            "code_hash": member.source_code_hash(_PRIOR_PROPOSAL),
        }
    ]
    composed_cut = component.admit(cut, prior_nodes=[_HISTORY_NODE])  # type: ignore[attr-defined]
    expected_cut = direct.admit(cut, prior_nodes=[_HISTORY_NODE])
    assert composed_cut.complete == expected_cut.complete is False
    assert composed_cut.reason == expected_cut.reason
    assert composed_cut.detail == expected_cut.detail

    sampled = [
        {"node_id": _HISTORY_NODE, "proposal": _PRIOR_PROPOSAL, "sampled_from": "recent"}
    ]
    assert (
        component.admit(sampled).complete  # type: ignore[attr-defined]
        == direct.admit(sampled).complete
        is False
    )


def _assert_is_the_guidance_law(component: object) -> None:
    """The composed guidance gate is the law, across the loader's copies.

    Name, then behaviour — never ``isinstance``, for the same reason the seven
    checks above are not.  Feature 208's clause is one refusal and this helper
    asserts it on both sides, because a component that answered only the
    admission half would be a gate that certified prompts while refusing to
    name the one thing §C3 forbids:

    * *unguided* — the composed gate must admit the declared-parts prompt the
      canonically-imported one admits, with the same sentence and the same
      parts, compared by value across the loader's boundary;
    * *injected guidance* — the composed gate must refuse the part that
      declares itself distilled from the history with the same
      ``injected_guidance`` sentence and the same named offenders.
    """
    assert type(component).__name__ == "PromptGuidanceGate"
    assert type(component).__module__.endswith("signal_agent._guidance")

    for verb in ("admit", "require", "unguided"):
        assert callable(getattr(component, verb)), verb

    direct = member.prompt_guidance_gate()
    composed = component.admit(_UNGUIDED_PARTS)  # type: ignore[attr-defined]
    expected = direct.admit(_UNGUIDED_PARTS)
    assert composed.admitted == expected.admitted is True
    assert composed.reason == expected.reason
    assert composed.detail == expected.detail
    assert [name for name, _ in composed.sections] == [
        name for name, _ in expected.sections
    ]

    composed_refusal = component.admit(_GUIDED_PARTS)  # type: ignore[attr-defined]
    expected_refusal = direct.admit(_GUIDED_PARTS)
    assert composed_refusal.admitted == expected_refusal.admitted is False
    assert composed_refusal.reason == expected_refusal.reason
    assert composed_refusal.detail == expected_refusal.detail
    assert tuple(composed_refusal.offenders) == tuple(expected_refusal.offenders)


def test_the_member_registers_the_theme_gate_under_its_own_name() -> None:
    # The registry is keyed by name, so this prefix is not cosmetic: a builder
    # that registered "signal-agent" a second time would *replace* feature
    # 205's law rather than sit beside it.  Asserted against the spec's plugin
    # namespace — the feature belongs to ``signal-agent`` — and against the
    # unprefixed name, which must not be what this component took.
    assert member.THEMES_COMPONENT_NAME == "signal-agent-themes"
    assert member.THEMES_COMPONENT_NAME != member.COMPONENT_NAME


def test_the_scanned_application_carries_all_eight_laws() -> None:
    # The eight, in one composition: feature 205's law, feature 206's history,
    # feature 208's gate, feature 209's diagnosis, feature 210's gate, feature
    # 212's gate, feature 213's gate and feature 211's law, each under its own
    # name, none having replaced another.
    app = create_app(MEMBER_SRC, registry=Registration())
    assert "signal-agent" in app
    assert member.ANTI_CONVERGENCE_COMPONENT_NAME in app
    assert member.DEAD_TERRITORY_COMPONENT_NAME in app
    assert member.DIAGNOSIS_COMPONENT_NAME in app
    assert member.GUIDANCE_COMPONENT_NAME in app
    assert member.HISTORY_COMPONENT_NAME in app
    assert member.THEMES_COMPONENT_NAME in app
    assert member.STATED_MECHANISM_COMPONENT_NAME in app
    _assert_is_the_authoring_law(app.get("signal-agent"))
    _assert_is_the_anti_convergence_law(app.get(member.ANTI_CONVERGENCE_COMPONENT_NAME))
    _assert_is_the_dead_territory_law(app.get(member.DEAD_TERRITORY_COMPONENT_NAME))
    _assert_is_the_diagnosis_law(app.get(member.DIAGNOSIS_COMPONENT_NAME))
    _assert_is_the_guidance_law(app.get(member.GUIDANCE_COMPONENT_NAME))
    _assert_is_the_history_law(app.get(member.HISTORY_COMPONENT_NAME))
    _assert_is_the_theme_law(app.get(member.THEMES_COMPONENT_NAME))
    _assert_is_the_mechanism_law(app.get(member.STATED_MECHANISM_COMPONENT_NAME))


def test_the_eight_laws_stay_contiguous_in_the_name_sorted_order() -> None:
    # ``app.order`` is name-sorted, so the prefixed names are what keep the
    # member's eight components together in the category they belong to rather
    # than scattered by whatever the prefixes happened to be.  The eight names
    # sort as ``signal-agent`` < ``signal-agent-anti-convergence`` <
    # ``signal-agent-dead-territory`` < ``signal-agent-diagnosis`` <
    # ``signal-agent-guidance`` < ``signal-agent-history`` <
    # ``signal-agent-stated-mechanism`` < ``signal-agent-themes``, so feature
    # 210's gate lands immediately after feature 205's law — and the eight are
    # contiguous, with no unrelated component wedged between them.
    app = create_app(MEMBER_SRC, registry=Registration())
    order = list(app.order)
    positions = sorted(order.index(name) for name in (
        member.COMPONENT_NAME,
        member.ANTI_CONVERGENCE_COMPONENT_NAME,
        member.DEAD_TERRITORY_COMPONENT_NAME,
        member.DIAGNOSIS_COMPONENT_NAME,
        member.GUIDANCE_COMPONENT_NAME,
        member.HISTORY_COMPONENT_NAME,
        member.STATED_MECHANISM_COMPONENT_NAME,
        member.THEMES_COMPONENT_NAME,
    ))
    assert positions == [
        positions[0],
        positions[0] + 1,
        positions[0] + 2,
        positions[0] + 3,
        positions[0] + 4,
        positions[0] + 5,
        positions[0] + 6,
        positions[0] + 7,
    ]
    assert order[positions[0]] == member.COMPONENT_NAME
    assert order[positions[1]] == member.ANTI_CONVERGENCE_COMPONENT_NAME
    assert order[positions[2]] == member.DEAD_TERRITORY_COMPONENT_NAME
    assert order[positions[3]] == member.DIAGNOSIS_COMPONENT_NAME
    assert order[positions[4]] == member.GUIDANCE_COMPONENT_NAME
    assert order[positions[5]] == member.HISTORY_COMPONENT_NAME
    assert order[positions[6]] == member.STATED_MECHANISM_COMPONENT_NAME
    assert order[positions[7]] == member.THEMES_COMPONENT_NAME


def test_the_theme_component_survives_a_second_composition() -> None:
    # The submodule-registration hazard, checked on the *second* application:
    # a ``@register`` outside ``__init__.py`` fires once and drops out.
    first = create_app(MEMBER_SRC, registry=Registration())
    second = create_app(MEMBER_SRC, registry=Registration())
    assert member.THEMES_COMPONENT_NAME in first
    assert member.THEMES_COMPONENT_NAME in second
    _assert_is_the_theme_law(second.get(member.THEMES_COMPONENT_NAME))


def test_building_the_theme_gate_carries_the_committed_set() -> None:
    app = create_app(MEMBER_SRC, registry=Registration())
    gate = app.get(member.THEMES_COMPONENT_NAME)
    assert gate is not None
    # A non-None component carrying six slugs is proof the committed artifact
    # loaded — the member's builder compiles it, so there is no unconfigured
    # state a caller could confuse with a set that admits nothing.
    assert len(gate.themes) == 6
    assert gate.covers(_LEGAL_THEME) and not gate.covers(_ILLEGAL_THEME)


def test_a_drifted_artifact_does_not_take_composition_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The builder's documented contract, held to behaviour rather than to its
    # own prose: the factory builds every registered component on every
    # ``create_app()`` call, so a builder that *raised* on a drifted artifact
    # would take composition down for every unrelated feature in the workspace.
    # Instead it fails **closed** — an empty set admits no theme — and a caller
    # that must know why asks `committed_legal_themes()` for the named
    # refusal, which is the same division `build_sandbox_isolation` draws.
    monkeypatch.setattr(
        member,
        "committed_legal_themes",
        lambda: (_ for _ in ()).throw(member.ThemeSetError("drifted artifact")),
    )
    gate = member.build_signal_theme_gate()
    assert len(gate.themes) == 0
    refusal = gate.admit(_LEGAL_THEME)
    assert refusal.admitted is False
    assert "names no themes at all" in refusal.detail
    # And the named refusal is still reachable — the builder swallowed it into
    # a value, it did not lose it.
    with pytest.raises(member.ThemeSetError):
        member.committed_legal_themes()


def test_the_theme_builder_takes_no_arguments() -> None:
    # The factory's protocol: a zero-argument builder.  It reads a committed
    # artifact shipped inside the package and no environment at all, so it
    # composes in any process.
    from app.module_loader import scan_components

    builders = {
        component.name: component.builder
        for component in scan_components(MEMBER_SRC, registry=Registration())
    }
    assert builders[member.THEMES_COMPONENT_NAME].__name__ == (
        "build_signal_theme_gate"
    )
    assert list(
        inspect.signature(builders[member.THEMES_COMPONENT_NAME]).parameters
    ) == []


# -- Feature 213's component --------------------------------------------------


def test_the_member_registers_the_dead_territory_gate_under_its_own_name() -> None:
    # The registry is keyed by name, so this prefix is not cosmetic: a builder
    # that registered "signal-agent" a third time would *replace* feature
    # 205's law rather than sit beside it.  Asserted against the spec's plugin
    # namespace — the feature belongs to ``signal-agent`` — and against the
    # unprefixed name, which must not be what this component took, and against
    # the theme gate's name, which it must not collide with either.
    assert member.DEAD_TERRITORY_COMPONENT_NAME == "signal-agent-dead-territory"
    assert member.DEAD_TERRITORY_COMPONENT_NAME != member.COMPONENT_NAME
    assert member.DEAD_TERRITORY_COMPONENT_NAME != member.THEMES_COMPONENT_NAME


def test_building_the_dead_territory_gate_carries_the_committed_list() -> None:
    app = create_app(MEMBER_SRC, registry=Registration())
    gate = app.get(member.DEAD_TERRITORY_COMPONENT_NAME)
    assert gate is not None
    # A non-None component carrying PRD §9.4's three mechanisms is proof the
    # committed artifact loaded — the member's builder compiles it, so there is
    # no unconfigured state a caller could confuse with a denylist that refuses
    # nothing.
    assert len(gate.territory) == 3
    assert gate.covers(_DEAD_MECHANISM) and not gate.covers(_LIVE_MECHANISM)


def test_a_drifted_dead_territory_artifact_does_not_take_composition_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The builder's documented contract, held to behaviour rather than to its
    # own prose: the factory builds every registered component on every
    # ``create_app()`` call, so a builder that *raised* on a drifted artifact
    # would take composition down for every unrelated feature in the workspace.
    # Instead it fails **open** — an empty denylist refuses no theme — and a
    # caller that must know why asks `committed_dead_territory()` for the named
    # refusal, which is the same division `build_sandbox_isolation` draws.  This
    # is the one asymmetry with feature 212's builder, and it is load-bearing:
    # a down guardrail refuses fewer proposals than a system that refuses them
    # all, and the space (feature 212) still judges it.
    monkeypatch.setattr(
        member,
        "committed_dead_territory",
        lambda: (_ for _ in ()).throw(
            member.DeadTerritorySetError("drifted artifact")
        ),
    )
    gate = member.build_dead_territory_gate()
    assert len(gate.territory) == 0
    admission = gate.admit(_DEAD_MECHANISM)
    assert admission.admitted is True
    # And the named refusal is still reachable — the builder swallowed it into
    # a value, it did not lose it.
    with pytest.raises(member.DeadTerritorySetError):
        member.committed_dead_territory()


def test_the_dead_territory_builder_takes_no_arguments() -> None:
    # The factory's protocol: a zero-argument builder.  It reads a committed
    # artifact shipped inside the package and no environment at all, so it
    # composes in any process.
    from app.module_loader import scan_components

    builders = {
        component.name: component.builder
        for component in scan_components(MEMBER_SRC, registry=Registration())
    }
    assert builders[member.DEAD_TERRITORY_COMPONENT_NAME].__name__ == (
        "build_dead_territory_gate"
    )
    assert list(
        inspect.signature(builders[member.DEAD_TERRITORY_COMPONENT_NAME]).parameters
    ) == []


def test_the_member_registers_the_mechanism_law_under_its_own_name() -> None:
    # The registry is keyed by name, so this prefix is not cosmetic: a builder
    # that registered "signal-agent" a fourth time would *replace* feature 205's
    # law rather than sit beside it.  Asserted against the unprefixed name and
    # against the other two prefixed ones, either of which it must not collide
    # with — the assertion that would catch a copy-pasted constant.
    assert member.STATED_MECHANISM_COMPONENT_NAME == "signal-agent-stated-mechanism"
    assert member.STATED_MECHANISM_COMPONENT_NAME != member.COMPONENT_NAME
    assert (
        member.STATED_MECHANISM_COMPONENT_NAME != member.THEMES_COMPONENT_NAME
    )
    assert (
        member.STATED_MECHANISM_COMPONENT_NAME
        != member.DEAD_TERRITORY_COMPONENT_NAME
    )


def test_the_mechanism_component_survives_a_second_composition() -> None:
    # The submodule-registration hazard, checked on the *second* application:
    # a ``@register`` outside ``__init__.py`` fires once and drops out.
    first = create_app(MEMBER_SRC, registry=Registration())
    second = create_app(MEMBER_SRC, registry=Registration())
    assert member.STATED_MECHANISM_COMPONENT_NAME in first
    assert member.STATED_MECHANISM_COMPONENT_NAME in second
    _assert_is_the_mechanism_law(second.get(member.STATED_MECHANISM_COMPONENT_NAME))


def test_the_mechanism_builder_takes_no_arguments() -> None:
    # The factory's protocol: a zero-argument builder.  It is the one builder in
    # this member that reads the environment — through
    # ``MechanismStore.resolve`` — and it still takes no *arguments*, which is
    # what the protocol requires; the environment is the seam, not a parameter.
    from app.module_loader import scan_components

    builders = {
        component.name: component.builder
        for component in scan_components(MEMBER_SRC, registry=Registration())
    }
    assert builders[member.STATED_MECHANISM_COMPONENT_NAME].__name__ == (
        "build_stated_mechanism"
    )
    assert list(
        inspect.signature(builders[member.STATED_MECHANISM_COMPONENT_NAME]).parameters
    ) == []


def test_a_missing_database_does_not_take_composition_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The builder's documented contract, held to behaviour rather than to its
    # own prose: the factory builds every registered component on every
    # ``create_app()`` call, so a builder that *raised* when ``DATABASE_URL``
    # names nothing would take composition down for every unrelated feature in
    # the workspace.  Instead it composes the law with ``store=None``.
    #
    # ``monkeypatch.delenv`` rather than a fixture that clears the environment:
    # this is the one claim in the suite that *is* about the absent variable,
    # and it is made once, in the open, with pytest undoing it.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    law = member.build_stated_mechanism()
    # The barrier still answers — that is the whole reason ``None`` is composed
    # rather than refused.
    assert law.scored_input(_STATED_MECHANISM).scored is False
    assert law.store is None
    # And the store-backed verbs refuse by name, which is what makes the
    # ``None`` a discoverable state rather than a silent one.
    with pytest.raises(member.MechanismStoreUnavailableError):
        law.stated()
    # It is *not* an empty store: an empty store answers "no node states a
    # mechanism here", and this answers that there is nowhere to have recorded
    # one.  The two are different facts with different repairs.
    assert "not an empty store" in str(
        _refusal_of(member.MechanismStoreUnavailableError, law.stated)
    )


def _refusal_of(error: type[BaseException], call) -> BaseException:
    """The exception ``call`` raises, asserted to be ``error``.

    A helper for the message assertions above: ``pytest.raises`` yields the
    exception through ``.value``, and spelling that out twice for one claim
    reads worse than naming what is being fetched.
    """
    with pytest.raises(error) as refusal:
        call()
    return refusal.value


def test_the_mechanism_builder_does_not_open_the_store_at_composition() -> None:
    # Construction performs no I/O: the URL is translated on first use, so a
    # ``DATABASE_URL`` whose scheme this member cannot speak is refused by name
    # the first time a mechanism is actually persisted, not when the component
    # is built.  Held to behaviour by building over a URL no SQLite store could
    # accept and showing the build succeeds.
    law = member.StatedMechanism(member.MechanismStore("postgresql://host/tree"))
    assert law.store is not None
    with pytest.raises(member.MechanismStoreUnavailableError):
        law.stated()


# -- Feature 209's component ---------------------------------------------------


def test_the_member_registers_the_diagnosis_under_its_own_name() -> None:
    # The registry is keyed by name, so this prefix is not cosmetic: a builder
    # that registered "signal-agent" a sixth time would *replace* feature 205's
    # law rather than sit beside it.  Asserted against the unprefixed name and
    # against each of the other four prefixed ones, any of which it must not
    # collide with — the assertion that would catch a copy-pasted constant.
    assert member.DIAGNOSIS_COMPONENT_NAME == "signal-agent-diagnosis"
    assert member.DIAGNOSIS_COMPONENT_NAME != member.COMPONENT_NAME
    for other in (
        member.ANTI_CONVERGENCE_COMPONENT_NAME,
        member.DEAD_TERRITORY_COMPONENT_NAME,
        member.STATED_MECHANISM_COMPONENT_NAME,
        member.THEMES_COMPONENT_NAME,
    ):
        assert member.DIAGNOSIS_COMPONENT_NAME != other, other


def test_the_diagnosis_component_survives_a_second_composition() -> None:
    # The submodule-registration hazard, checked on the *second* application:
    # a ``@register`` outside ``__init__.py`` fires once and drops out.
    first = create_app(MEMBER_SRC, registry=Registration())
    second = create_app(MEMBER_SRC, registry=Registration())
    assert member.DIAGNOSIS_COMPONENT_NAME in first
    assert member.DIAGNOSIS_COMPONENT_NAME in second
    _assert_is_the_diagnosis_law(second.get(member.DIAGNOSIS_COMPONENT_NAME))


def test_the_diagnosis_builder_takes_no_arguments() -> None:
    # The factory's protocol: a zero-argument builder.  It reads no committed
    # artifact and no environment at all, so it composes in any process — the
    # member's second builder of feature 205's shape, beside three that compile
    # a document and one that resolves a store.
    from app.module_loader import scan_components

    builders = {
        component.name: component.builder
        for component in scan_components(MEMBER_SRC, registry=Registration())
    }
    assert builders[member.DIAGNOSIS_COMPONENT_NAME].__name__ == (
        "build_mechanism_diagnosis"
    )
    assert list(
        inspect.signature(builders[member.DIAGNOSIS_COMPONENT_NAME]).parameters
    ) == []


def test_the_diagnosis_builder_has_no_drifted_artifact_to_fall_back_from() -> None:
    # The one builder in this member with no `except` branch, and that is the
    # feature rather than an omission: features 212's, 213's and 210's builders
    # each compile a committed document and therefore each document a
    # failure-as-a-value answer, while feature 209 compiles nothing — what
    # counts as a located bug is a fact about the proposal handed in.  Held to
    # behaviour by building the component over a *monkeypatched-away* world:
    # there is no symbol in this package whose absence degrades the gate,
    # because there is no artifact for it to read.  What this asserts is the
    # positive half — the composed law answers a proposal, immediately.
    law = member.build_mechanism_diagnosis()
    assert law.retry(_BROKEN) is True


def test_the_member_registers_the_history_under_its_own_name() -> None:
    # The registry is keyed by name, so this prefix is not cosmetic: a builder
    # that registered "signal-agent" a seventh time would *replace* feature
    # 205's law rather than sit beside it — and a builder that registered
    # "signal-agent-diagnosis" would replace feature 209's law.  Asserted
    # against the spec's plugin namespace (the feature belongs to
    # ``signal-agent``) and against the five sibling names it must not take.
    assert member.HISTORY_COMPONENT_NAME == "signal-agent-history"
    assert member.HISTORY_COMPONENT_NAME != member.COMPONENT_NAME
    assert member.HISTORY_COMPONENT_NAME != member.DIAGNOSIS_COMPONENT_NAME
    assert member.HISTORY_COMPONENT_NAME != member.STATED_MECHANISM_COMPONENT_NAME


def test_the_history_component_survives_a_second_composition() -> None:
    # The submodule-registration hazard, checked on the *second* application:
    # a ``@register`` outside ``__init__.py`` fires once and drops out.
    first = create_app(MEMBER_SRC, registry=Registration())
    second = create_app(MEMBER_SRC, registry=Registration())
    assert member.HISTORY_COMPONENT_NAME in first
    assert member.HISTORY_COMPONENT_NAME in second
    _assert_is_the_history_law(second.get(member.HISTORY_COMPONENT_NAME))


def test_the_history_builder_takes_no_arguments() -> None:
    # The factory's protocol: a zero-argument builder.  It reads no committed
    # artifact and no environment at all, so it composes in any process — the
    # member's third builder of feature 205's shape, beside three that compile
    # a document and one that resolves a store.
    from app.module_loader import scan_components

    builders = {
        component.name: component.builder
        for component in scan_components(MEMBER_SRC, registry=Registration())
    }
    assert builders[member.HISTORY_COMPONENT_NAME].__name__ == "build_proposal_history"
    assert list(
        inspect.signature(builders[member.HISTORY_COMPONENT_NAME]).parameters
    ) == []


def test_the_history_builder_has_no_drifted_artifact_to_fall_back_from() -> None:
    # No `except` branch, and that is the feature rather than an omission:
    # features 212's, 213's and 210's builders each compile a committed
    # document and therefore each need a failure-as-a-value answer, while
    # feature 206 compiles nothing — what counts as the whole history is the
    # caller's own tree query for the round.  There is no symbol in this
    # package whose absence degrades the law, because there is no artifact for
    # it to read.  What this asserts is the positive half — the composed law
    # answers a history, immediately, before any agent is called.
    law = member.build_proposal_history()
    assert law.complete([]) is True
    assert law.complete([{"node_id": _HISTORY_NODE}]) is False


def test_the_history_verdict_is_a_value_rather_than_a_raise() -> None:
    # The feature's shape, asserted on the composed law: a caller measuring
    # handed history cannot do that through an exception, so the refusal is
    # the returned value and ``require`` is the one place it raises.
    law = member.build_proposal_history()
    refusal = law.admit([{"node_id": _HISTORY_NODE, "proposal": _PRIOR_PROPOSAL,
                          "truncated": True}])
    assert refusal.complete is False
    with pytest.raises(member.TruncatedHistoryError):
        refusal.require()


# -- Feature 208's component ----------------------------------------------------


def test_the_member_registers_the_guidance_gate_under_its_own_name() -> None:
    # The registry is keyed by name, so this prefix is not cosmetic: a builder
    # that registered "signal-agent" an eighth time would *replace* feature
    # 205's law rather than sit beside it — and a builder that registered
    # "signal-agent-diagnosis" or "signal-agent-history" would replace
    # feature 209's law or feature 206's.  Asserted against the spec's plugin
    # namespace (the feature belongs to ``signal-agent``) and against the
    # sibling names it must not take.
    assert member.GUIDANCE_COMPONENT_NAME == "signal-agent-guidance"
    assert member.GUIDANCE_COMPONENT_NAME != member.COMPONENT_NAME
    for other in (
        member.ANTI_CONVERGENCE_COMPONENT_NAME,
        member.DEAD_TERRITORY_COMPONENT_NAME,
        member.DIAGNOSIS_COMPONENT_NAME,
        member.HISTORY_COMPONENT_NAME,
        member.STATED_MECHANISM_COMPONENT_NAME,
        member.THEMES_COMPONENT_NAME,
    ):
        assert member.GUIDANCE_COMPONENT_NAME != other, other


def test_the_guidance_component_survives_a_second_composition() -> None:
    # The submodule-registration hazard, checked on the *second* application:
    # a ``@register`` outside ``__init__.py`` fires once and drops out.
    first = create_app(MEMBER_SRC, registry=Registration())
    second = create_app(MEMBER_SRC, registry=Registration())
    assert member.GUIDANCE_COMPONENT_NAME in first
    assert member.GUIDANCE_COMPONENT_NAME in second
    _assert_is_the_guidance_law(second.get(member.GUIDANCE_COMPONENT_NAME))


def test_the_guidance_builder_takes_no_arguments() -> None:
    # The factory's protocol: a zero-argument builder.  It reads no committed
    # artifact and no environment at all, so it composes in any process — the
    # member's fourth builder of feature 205's shape, beside three that compile
    # a document and one that resolves a store.
    from app.module_loader import scan_components

    builders = {
        component.name: component.builder
        for component in scan_components(MEMBER_SRC, registry=Registration())
    }
    assert builders[member.GUIDANCE_COMPONENT_NAME].__name__ == (
        "build_prompt_guidance"
    )
    assert list(
        inspect.signature(builders[member.GUIDANCE_COMPONENT_NAME]).parameters
    ) == []


def test_the_guidance_builder_has_no_drifted_artifact_to_fall_back_from() -> None:
    # No `except` branch, and that is the feature rather than an omission:
    # features 212's, 213's and 210's builders each compile a committed
    # document and therefore each need a failure-as-a-value answer, while
    # feature 208's gate compiles nothing — what counts as injected guidance
    # is a declaration the prompt's own parts carry.  There is no symbol in
    # this package whose absence degrades the gate, because there is no
    # artifact for it to read.  What this asserts is the positive half — the
    # composed gate answers a prompt, immediately, before any agent is called.
    gate = member.build_prompt_guidance()
    assert gate.unguided(_UNGUIDED_PARTS) is True
    assert gate.unguided(_GUIDED_PARTS) is False


def test_the_guidance_verdict_is_a_value_rather_than_a_raise() -> None:
    # The feature's shape, asserted on the composed gate: a caller measuring
    # its assemblies cannot do that through an exception, so the refusal is
    # the returned value and ``require`` is the one place it raises.
    gate = member.build_prompt_guidance()
    refusal = gate.admit(_GUIDED_PARTS)
    assert refusal.admitted is False
    with pytest.raises(member.InjectedGuidanceError):
        refusal.require()


# -- The seats -----------------------------------------------------------------



def test_the_seat_names_line_up() -> None:
    assert seat.COMPONENT_NAME == member.COMPONENT_NAME == "signal-agent"


def test_the_seat_answers_the_composed_law() -> None:
    app = create_app(MEMBER_SRC, registry=Registration())
    law = seat.signal_agent_component(app)
    _assert_is_the_authoring_law(law)


def test_the_seat_returns_none_when_nothing_is_registered() -> None:
    # An absent component is a discoverable state, not an exception — and it is
    # a statement about composition, never about a proposal.
    empty = Application(components={}, order=())
    assert seat.signal_agent_component(empty) is None


def test_the_seat_does_not_import_the_member_at_module_scope() -> None:
    # The app package must not depend on any workspace member at import time;
    # the member's type appears only under ``TYPE_CHECKING``, which the
    # interpreter never evaluates.  Asserted on the *parse tree* rather than on
    # the source text, because the seat's own docstring names the module it
    # does not import, and the member's import must be *found* — under the
    # guard, and nowhere else.
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(seat))
    live: list[str] = []
    guarded: list[str] = []

    def _collect(nodes, into: list[str]) -> None:
        for node in nodes:
            if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.dump(node.test):
                for nested in node.body:
                    _collect([nested], guarded)
                continue
            if isinstance(node, ast.Import):
                into.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                into.append(node.module or "")
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    _collect(child.body, into)

    _collect(tree.body, live)

    assert not any(name.startswith("signal_agent") for name in live), live
    # The member's import is present, and it is under the guard: a reader and a
    # type checker see the type, the interpreter never imports it.  Both halves
    # are asserted, because a seat that dropped the import entirely would pass
    # the first line while losing the typing the guard exists to provide.
    assert "signal_agent" in guarded, guarded


def test_the_seat_exports_only_the_component_accessor() -> None:
    # Asserted as an exact set: the failure this guards against is the seat
    # *growing* a re-export of the member's API, and a membership check cannot
    # see that.
    assert set(seat.__all__) == {"COMPONENT_NAME", "signal_agent_component"}


def test_the_seat_is_reachable_by_its_hyphenated_name() -> None:
    # Reached the way the factory reaches such a package.
    assert seat.__name__ == "app.modules.signal-agent"
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.modules.signal_agent")


def test_the_theme_seat_names_line_up() -> None:
    assert theme_seat.COMPONENT_NAME == member.THEMES_COMPONENT_NAME == (
        "signal-agent-themes"
    )


def test_the_theme_seat_answers_the_composed_gate() -> None:
    app = create_app(MEMBER_SRC, registry=Registration())
    gate = theme_seat.theme_gate_component(app)
    _assert_is_the_theme_law(gate)


def test_the_theme_seat_returns_none_when_nothing_is_registered() -> None:
    # An absent component is a discoverable state, not an exception — and it is
    # a statement about composition, never about a theme.  This is the
    # distinction that matters most here: a *composed* gate that admits nothing
    # is a present component refusing every proposal, which is the opposite
    # complaint and a different repair.
    empty = Application(components={}, order=())
    assert theme_seat.theme_gate_component(empty) is None


def test_the_theme_seat_does_not_import_the_member_at_module_scope() -> None:
    # The same two-sided assertion the authoring seat gets, for the same
    # reason: the app package must not depend on any workspace member at import
    # time, and the member's type must still be *present* under the guard or
    # the typing the guard exists for was lost.
    import ast

    tree = ast.parse(inspect.getsource(theme_seat))
    live: list[str] = []
    guarded: list[str] = []

    def _collect(nodes, into: list[str]) -> None:
        for node in nodes:
            if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.dump(node.test):
                for nested in node.body:
                    _collect([nested], guarded)
                continue
            if isinstance(node, ast.Import):
                into.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                into.append(node.module or "")
            for child in ast.iter_child_nodes(node):
                if isinstance(
                    child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                ):
                    _collect(child.body, into)

    _collect(tree.body, live)

    assert not any(name.startswith("signal_agent") for name in live), live
    assert "signal_agent" in guarded, guarded


def test_the_theme_seat_exports_only_the_component_accessor() -> None:
    # Asserted as an exact set: the failure this guards against is the seat
    # growing a re-export of the member's set, admission value or reasons.
    assert set(theme_seat.__all__) == {"COMPONENT_NAME", "theme_gate_component"}


def test_the_theme_seat_is_reachable_by_its_hyphenated_path() -> None:
    assert theme_seat.__name__ == "app.modules.signal-agent.themes"
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.modules.signal_agent.themes")


# -- The dead-territory seat --------------------------------------------------


def test_the_dead_territory_seat_names_line_up() -> None:
    assert dead_seat.COMPONENT_NAME == member.DEAD_TERRITORY_COMPONENT_NAME == (
        "signal-agent-dead-territory"
    )


def test_the_dead_territory_seat_answers_the_composed_law() -> None:
    app = create_app(MEMBER_SRC, registry=Registration())
    gate = dead_seat.dead_territory_component(app)
    _assert_is_the_dead_territory_law(gate)


def test_the_dead_territory_seat_returns_none_when_nothing_is_registered() -> None:
    # An absent component is a discoverable state, not an exception — and it is
    # a statement about composition, never about a mechanism.  This is the
    # distinction that matters most here: a *composed* gate that refuses nothing
    # (an empty denylist, which fails open) is a present component admitting
    # every proposal, which is the opposite complaint and a different repair.
    empty = Application(components={}, order=())
    assert dead_seat.dead_territory_component(empty) is None


def test_the_dead_territory_seat_does_not_import_the_member_at_module_scope() -> None:
    # The same two-sided assertion the authoring and theme seats get, for the
    # same reason: the app package must not depend on any workspace member at
    # import time, and the member's type must still be *present* under the guard
    # or the typing the guard exists for was lost.
    import ast

    tree = ast.parse(inspect.getsource(dead_seat))
    live: list[str] = []
    guarded: list[str] = []

    def _collect(nodes, into: list[str]) -> None:
        for node in nodes:
            if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.dump(node.test):
                for nested in node.body:
                    _collect([nested], guarded)
                continue
            if isinstance(node, ast.Import):
                into.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                into.append(node.module or "")
            for child in ast.iter_child_nodes(node):
                if isinstance(
                    child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                ):
                    _collect(child.body, into)

    _collect(tree.body, live)

    assert not any(name.startswith("signal_agent") for name in live), live
    assert "signal_agent" in guarded, guarded


def test_the_dead_territory_seat_exports_only_the_component_accessor() -> None:
    # Asserted as an exact set: the failure this guards against is the seat
    # growing a re-export of the member's list, verdict value or reasons.
    assert set(dead_seat.__all__) == {"COMPONENT_NAME", "dead_territory_component"}


def test_the_dead_territory_seat_is_reachable_by_its_hyphenated_path() -> None:
    assert dead_seat.__name__ == "app.modules.signal-agent.dead_territory"
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.modules.signal_agent.dead_territory")


# -- The mechanism seat -------------------------------------------------------


def test_the_mechanism_seat_names_line_up() -> None:
    assert mechanism_seat.COMPONENT_NAME == (
        member.STATED_MECHANISM_COMPONENT_NAME
    ) == "signal-agent-stated-mechanism"


def test_the_mechanism_seat_answers_the_composed_law() -> None:
    app = create_app(MEMBER_SRC, registry=Registration())
    law = mechanism_seat.stated_mechanism_component(app)
    _assert_is_the_mechanism_law(law)


def test_the_mechanism_seat_returns_none_when_nothing_is_registered() -> None:
    # An absent component is a discoverable state, not an exception — and this
    # seat's ``None`` is *narrower* than it looks, which is what this test says.
    # It means the member was not scanned.  It does **not** mean the law has no
    # store: a composed law carrying ``store=None`` is a *present* component
    # whose barrier still answers, and reading this ``None`` as that one would
    # collapse a scan problem into a deployment problem.  The two have different
    # repairs and the module docstring states both.
    empty = Application(components={}, order=())
    assert mechanism_seat.stated_mechanism_component(empty) is None


def test_the_mechanism_seat_does_not_import_the_member_at_module_scope() -> None:
    # The same two-sided assertion the other three seats get, for the same
    # reason: the app package must not depend on any workspace member at import
    # time, and the member's type must still be *present* under the guard or the
    # typing the guard exists for was lost.
    import ast

    tree = ast.parse(inspect.getsource(mechanism_seat))
    live: list[str] = []
    guarded: list[str] = []

    def _collect(nodes, into: list[str]) -> None:
        for node in nodes:
            if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.dump(node.test):
                for nested in node.body:
                    _collect([nested], guarded)
                continue
            if isinstance(node, ast.Import):
                into.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                into.append(node.module or "")
            for child in ast.iter_child_nodes(node):
                if isinstance(
                    child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                ):
                    _collect(child.body, into)

    _collect(tree.body, live)

    assert not any(name.startswith("signal_agent") for name in live), live
    assert "signal_agent" in guarded, guarded


def test_the_mechanism_seat_exports_only_the_component_accessor() -> None:
    # Asserted as an exact set: the failure this guards against is the seat
    # growing a re-export of the member's record, reasons, barrier verdict or
    # store.
    assert set(mechanism_seat.__all__) == {
        "COMPONENT_NAME",
        "stated_mechanism_component",
    }


def test_the_mechanism_seat_is_reachable_by_its_hyphenated_path() -> None:
    assert mechanism_seat.__name__ == "app.modules.signal-agent.mechanism"
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.modules.signal_agent.mechanism")


# -- The anti-convergence seat -------------------------------------------------


def test_the_anti_convergence_seat_names_line_up() -> None:
    assert anti_convergence_seat.COMPONENT_NAME == (
        member.ANTI_CONVERGENCE_COMPONENT_NAME
    ) == "signal-agent-anti-convergence"


def test_the_anti_convergence_seat_answers_the_composed_law() -> None:
    app = create_app(MEMBER_SRC, registry=Registration())
    gate = anti_convergence_seat.anti_convergence_component(app)
    _assert_is_the_anti_convergence_law(gate)


def test_the_anti_convergence_seat_returns_none_when_nothing_is_registered() -> None:
    # An absent component is a discoverable state, not an exception — and this
    # seat's ``None`` must not be read as feature 210's own answer, which is why
    # this module spells the confusion out twice.  A *present* gate with an
    # empty comparison set admits every proposal (a campaign that has proposed
    # nothing has converged on nothing), and a *present* gate whose clause
    # artifact drifted certifies no prompt at all — the opposite complaint in
    # each case, and both of them answers of a real component rather than of
    # this ``None``.
    empty = Application(components={}, order=())
    assert anti_convergence_seat.anti_convergence_component(empty) is None


def test_the_anti_convergence_seat_does_not_import_the_member_at_module_scope() -> None:
    # The same two-sided assertion the other four seats get, for the same
    # reason: the app package must not depend on any workspace member at import
    # time, and the member's type must still be *present* under the guard or the
    # typing the guard exists for was lost.
    import ast

    tree = ast.parse(inspect.getsource(anti_convergence_seat))
    live: list[str] = []
    guarded: list[str] = []

    def _collect(nodes, into: list[str]) -> None:
        for node in nodes:
            if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.dump(node.test):
                for nested in node.body:
                    _collect([nested], guarded)
                continue
            if isinstance(node, ast.Import):
                into.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                into.append(node.module or "")
            for child in ast.iter_child_nodes(node):
                if isinstance(
                    child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                ):
                    _collect(child.body, into)

    _collect(tree.body, live)

    assert not any(name.startswith("signal_agent") for name in live), live
    assert "signal_agent" in guarded, guarded


def test_the_anti_convergence_seat_exports_only_the_component_accessor() -> None:
    # Asserted as an exact set: the failure this guards against is the seat
    # growing a re-export of the member's clause, verdict value, reasons or
    # compiler.
    assert set(anti_convergence_seat.__all__) == {
        "COMPONENT_NAME",
        "anti_convergence_component",
    }


def test_the_anti_convergence_seat_is_reachable_by_its_hyphenated_path() -> None:
    assert (
        anti_convergence_seat.__name__
        == "app.modules.signal-agent.anti_convergence"
    )
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.modules.signal_agent.anti_convergence")


# -- The diagnosis seat --------------------------------------------------------


def test_the_diagnosis_seat_names_line_up() -> None:
    assert diagnosis_seat.COMPONENT_NAME == (
        member.DIAGNOSIS_COMPONENT_NAME
    ) == "signal-agent-diagnosis"


def test_the_diagnosis_seat_answers_the_composed_law() -> None:
    app = create_app(MEMBER_SRC, registry=Registration())
    law = diagnosis_seat.mechanism_diagnosis_component(app)
    _assert_is_the_diagnosis_law(law)


def test_the_diagnosis_seat_returns_none_when_nothing_is_registered() -> None:
    # An absent component is a discoverable state, not an exception — and this
    # seat's ``None`` must not be read as either of feature 209's two answers.
    # Read as "do not retry" it closes a branch nobody diagnosed; read as
    # "retry" it spends a trial charge on the strength of a component that is
    # not there.  Both are the law's own returned values rather than this
    # ``None``, which is a statement about the scan.
    empty = Application(components={}, order=())
    assert diagnosis_seat.mechanism_diagnosis_component(empty) is None


def test_the_diagnosis_seat_does_not_import_the_member_at_module_scope() -> None:
    # The same two-sided assertion the other five seats get, for the same
    # reason: the app package must not depend on any workspace member at import
    # time, and the member's type must still be *present* under the guard or
    # the typing the guard exists for was lost.
    import ast

    tree = ast.parse(inspect.getsource(diagnosis_seat))
    live: list[str] = []
    guarded: list[str] = []

    def _collect(nodes, into: list[str]) -> None:
        for node in nodes:
            if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.dump(node.test):
                for nested in node.body:
                    _collect([nested], guarded)
                continue
            if isinstance(node, ast.Import):
                into.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                into.append(node.module or "")
            for child in ast.iter_child_nodes(node):
                if isinstance(
                    child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                ):
                    _collect(child.body, into)

    _collect(tree.body, live)

    assert not any(name.startswith("signal_agent") for name in live), live
    assert "signal_agent" in guarded, guarded


def test_the_diagnosis_seat_exports_only_the_component_accessor() -> None:
    # Asserted as an exact set: the failure this guards against is the seat
    # growing a re-export of the member's verdict, located defect or reasons.
    assert set(diagnosis_seat.__all__) == {
        "COMPONENT_NAME",
        "mechanism_diagnosis_component",
    }


def test_the_diagnosis_seat_is_reachable_by_its_hyphenated_path() -> None:
    assert diagnosis_seat.__name__ == "app.modules.signal-agent.diagnosis"
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.modules.signal_agent.diagnosis")


# -- The history seat ----------------------------------------------------------


def test_the_history_seat_names_line_up() -> None:
    assert history_seat.COMPONENT_NAME == (
        member.HISTORY_COMPONENT_NAME
    ) == "signal-agent-history"


def test_the_history_seat_answers_the_composed_law() -> None:
    app = create_app(MEMBER_SRC, registry=Registration())
    law = history_seat.proposal_history_component(app)
    _assert_is_the_history_law(law)


def test_the_history_seat_returns_none_when_nothing_is_registered() -> None:
    # An absent component is a discoverable state, not an exception — and this
    # seat's ``None`` must not be read as either of feature 206's two answers.
    # Read as "the history is whole" it proposes from a partial history, which
    # is the exact failure the feature exists to refuse; read as "the history
    # is cut" it refuses a round on the strength of a component that is not
    # there.  Both are the law's own returned value —
    # ``history.admit(entries)`` — rather than this ``None``, which is a
    # statement about the scan.
    empty = Application(components={}, order=())
    assert history_seat.proposal_history_component(empty) is None


def test_the_history_seat_does_not_import_the_member_at_module_scope() -> None:
    # The same two-sided assertion the other six seats get, for the same
    # reason: the app package must not depend on any workspace member at import
    # time, and the member's type must still be *present* under the guard or
    # the typing the guard exists for was lost.
    import ast

    tree = ast.parse(inspect.getsource(history_seat))
    live: list[str] = []
    guarded: list[str] = []

    def _collect(nodes, into: list[str]) -> None:
        for node in nodes:
            if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.dump(node.test):
                for nested in node.body:
                    _collect([nested], guarded)
                continue
            if isinstance(node, ast.Import):
                into.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                into.append(node.module or "")
            for child in ast.iter_child_nodes(node):
                if isinstance(
                    child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                ):
                    _collect(child.body, into)

    _collect(tree.body, live)

    assert not any(name.startswith("signal_agent") for name in live), live
    assert "signal_agent" in guarded, guarded


def test_the_history_seat_exports_only_the_component_accessor() -> None:
    # Asserted as an exact set: the failure this guards against is the seat
    # growing a re-export of the member's verdict, reasons, codes or the
    # ``PriorProposal`` an admitted history carries.
    assert set(history_seat.__all__) == {
        "COMPONENT_NAME",
        "proposal_history_component",
    }


def test_the_history_seat_is_reachable_by_its_hyphenated_path() -> None:
    assert history_seat.__name__ == "app.modules.signal-agent.history"
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.modules.signal_agent.history")


# -- The guidance seat ----------------------------------------------------------


def test_the_guidance_seat_names_line_up() -> None:
    assert guidance_seat.COMPONENT_NAME == (
        member.GUIDANCE_COMPONENT_NAME
    ) == "signal-agent-guidance"


def test_the_guidance_seat_answers_the_composed_law() -> None:
    app = create_app(MEMBER_SRC, registry=Registration())
    gate = guidance_seat.prompt_guidance_component(app)
    _assert_is_the_guidance_law(gate)


def test_the_guidance_seat_returns_none_when_nothing_is_registered() -> None:
    # An absent component is a discoverable state, not an exception — and this
    # seat's ``None`` must not be read as either of feature 208's two answers.
    # Read as "the prompt is unguided" it ships a prompt nobody screened,
    # which is PRD §C3's *"most implementations get it backwards"* arriving
    # through the app package's own seam; read as "it carries guidance" it
    # blocks a round on the strength of a component that is not there.  Both
    # are the law's own returned value — ``guidance.admit(prompt)`` — rather
    # than this ``None``, which is a statement about the scan.
    empty = Application(components={}, order=())
    assert guidance_seat.prompt_guidance_component(empty) is None


def test_the_guidance_seat_does_not_import_the_member_at_module_scope() -> None:
    # The same two-sided assertion the other seven seats get, for the same
    # reason: the app package must not depend on any workspace member at
    # import time, and the member's type must still be *present* under the
    # guard or the typing the guard exists for was lost.
    import ast

    tree = ast.parse(inspect.getsource(guidance_seat))
    live: list[str] = []
    guarded: list[str] = []

    def _collect(nodes, into: list[str]) -> None:
        for node in nodes:
            if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.dump(node.test):
                for nested in node.body:
                    _collect([nested], guarded)
                continue
            if isinstance(node, ast.Import):
                into.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                into.append(node.module or "")
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    _collect(child.body, into)

    _collect(tree.body, live)

    assert not any(name.startswith("signal_agent") for name in live), live
    assert "signal_agent" in guarded, guarded


def test_the_guidance_seat_exports_only_the_component_accessor() -> None:
    # Asserted as an exact set: the failure this guards against is the seat
    # growing a re-export of the member's verdict, reasons, codes or the
    # parts an admitted prompt carries.
    assert set(guidance_seat.__all__) == {
        "COMPONENT_NAME",
        "prompt_guidance_component",
    }


def test_the_guidance_seat_is_reachable_by_its_hyphenated_path() -> None:
    assert guidance_seat.__name__ == "app.modules.signal-agent.guidance"
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.modules.signal_agent.guidance")
