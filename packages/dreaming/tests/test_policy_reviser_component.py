"""The policy reviser's composition seam: the component as the loader composes it.

The policy-development authoring addition's feature 10 sentence:

    System creates a "policy-reviser" component, registered with ``@register``
    in ``dreaming/__init__.py``.  Its builder answers an ``LLMReviser`` over a
    ``providers.AuthoringSession`` with the "live-providers" resolver, or
    ``None`` when ``providers.load_authoring_config()`` answers ``None``.

Feature 9 built the reviser — the model-driven transform feature 271's
``revise_policy`` seam takes.  This suite holds the *wiring* of it: the
registration contract every member's component suite states for its own
component, the ``None`` a deployment that authors nothing composes to, and the
two restraints the sentence states in as many words — the builder makes **no
model call** and **reads no API key**.

The loader's two properties shape the composition half exactly as they shape
``test_component.py``'s: the scan imports each member under a synthetic name,
so the composed reviser is pinned by class name, module suffix and behaviour
rather than by ``isinstance``; and the loader re-executes a package's
``__init__`` on every ``create_app()`` but not an already-cached submodule, so
the ``@register`` lives in ``__init__.py`` to fire on *every* composition.

**How the no-credential claim is held testable.**  The builder's whole
journey is one variable, one config parse and three lazy constructions, and
the one place a credential would be read is the resolver's ``resolve()``,
reached only when the session's ``provider_for`` is asked for a pin.  So the
suite composes the application over a config file whose policy pin's vendor
key is *deliberately absent*, and asserts three things: composition answered a
reviser at all (a builder that read a key would have refused), the session
resolved nothing (``providers == {}`` — no pin was ever asked for), and the
first *ask* for the policy pin refuses with the live registry's own
``ProviderNotConfiguredError`` **naming the variable** — which is both the
proof the session holds the live-providers resolver (a fake would not refuse
in that vocabulary) and the proof the read was deferred past composition to
the first revision, where an operator can act on the name.

**The sweep is asserted unmoved.**  The sentence's last clause —
*``revise_policy``'s default reviser stays ``default_reviser``* — is held as
the behavioural fact it is: a sweep run with no ``reviser`` answers the same
candidates the same explicit ``default_reviser`` sweep answers, determinism
being feature 271's own contract, so a wiring that had quietly moved the
default would fail the equality rather than pass by reading source.

No test here opens a network connection or reads a real credential: the one
provider ask the suite makes is the ask a deployment with no keys makes, and
it asserts the refusal it gets back.
"""

from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

import pytest

# The providers root, added here beside the import for the same reason
# test_llm_reviser.py states: the member's conftest puts the app and dreaming
# roots on ``sys.path``; this suite also reads the providers member's
# vocabulary (the config value, the live registry's refusal), and the builder
# under test imports that member at build time, so the suite collects the same
# way whichever sibling was collected first.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_PROVIDERS_SRC = str(_REPO_ROOT / "packages" / "providers" / "src")
if _PROVIDERS_SRC not in sys.path:
    sys.path.insert(0, _PROVIDERS_SRC)

import dreaming as member
from dreaming.reviser import default_reviser, revise_policy
from providers import AuthoringConfig, AuthoringConfigError, ProviderNotConfiguredError

from app.module_loader import (
    Application,
    Registration,
    create_app,
    scan_components,
)

#: The policy pin the suite's config file names — a google pin, whose live
#: credential variable (``NULLIUS_GOOGLE_API_KEY``, per the live registry's
#: own table) no test in this workspace sets, so the suite's asks are refused
#: by the variable's absence rather than by anything the suite put there.
POLICY_PIN = "google/gemini-3.1-pro/20260801"

#: The live credential variable the policy pin's vendor reads — spelled here
#: so the assertion that the refusal names it reads the same string the
#: registry greps for, and a rename on either side fails a test.
POLICY_KEY_ENV = "NULLIUS_GOOGLE_API_KEY"


@pytest.fixture
def authoring_config(tmp_path: Path) -> Path:
    """A config file the front door parses — one pin per role, small ceilings.

    Every key the file holds is stated (the two with defaults included), so
    the file is a whole authoring statement rather than a exercise of the
    parser's fallbacks, and the composed reviser's config can be compared
    value-for-value against ``AuthoringConfig.from_file`` of the same bytes.
    """
    document = {
        "root_tier": [POLICY_PIN],
        "depth": "deepseek/deepseek-v4-flash/20260910",
        "policy": POLICY_PIN,
        "temperature": 0.4,
        "max_tokens": 4096,
        "max_input_tokens": 1_000_000,
        "max_output_tokens": 1_000_000,
    }
    path = tmp_path / "authoring.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


@pytest.fixture
def configured(monkeypatch, authoring_config: Path) -> Path:
    """The deployment names its authoring config, and holds no vendor key.

    Sets the one variable the front door reads and clears the one credential
    variable the policy pin's vendor would read — the state the
    no-model-call/no-API-key claims are asserted over, and the state a CI run
    of this suite is actually in.
    """
    monkeypatch.setenv("NULLIUS_AUTHORING_CONFIG", str(authoring_config))
    monkeypatch.delenv(POLICY_KEY_ENV, raising=False)
    return authoring_config


def _assert_is_the_reviser(component: object) -> None:
    """The composed component is the reviser, pinned across the loader's copies.

    Name, module suffix, then behaviour — the ladder ``test_component.py``
    climbs for the freeze, because the loader's synthetic-name copies make
    ``isinstance`` unusable.  The behaviour worth pinning here is the wiring's
    own: the reviser answers its records (empty — no call was made) and holds
    the two things it was constructed over.
    """
    assert type(component).__name__ == "LLMReviser"
    assert type(component).__module__.endswith("dreaming.llm_reviser")
    assert component.records == []
    assert component._session is not None
    # One config object binds both halves of the wiring — the reviser's knobs
    # and the session's pins are one deployment statement, not two that could
    # drift apart.
    assert component._config is component._session.config


# -- The registration ------------------------------------------------------------


def test_the_member_registers_the_policy_reviser_under_its_own_name() -> None:
    # The spec's own spelling, unprefixed like every component this workspace
    # names, exported beside it so the seat and the suite read one name.
    assert member.POLICY_REVISER_COMPONENT == "policy-reviser"
    assert "POLICY_REVISER_COMPONENT" in member.__all__


def test_the_builder_takes_no_arguments() -> None:
    # The registration protocol passes nothing; the builder resolves the one
    # variable it reads itself.
    assert list(inspect.signature(member.build_policy_reviser).parameters) == []


def test_the_scanned_application_carries_the_reviser(configured: Path) -> None:
    # The factory scans the members, this package's second ``@register`` fires,
    # and the composed application carries the reviser the deployment's config
    # wired — the feature's own sentence, both halves of it.
    app = create_app()

    assert member.POLICY_REVISER_COMPONENT in app
    assert member.POLICY_REVISER_COMPONENT in app.order
    _assert_is_the_reviser(app.get(member.POLICY_REVISER_COMPONENT))


def test_the_component_survives_a_second_composition(configured: Path) -> None:
    # The submodule-registration hazard, the reason the second ``@register``
    # lives in ``__init__.py`` beside the first: the loader caches imported
    # submodules, so a registration anywhere else would fire on the first
    # composition of a process and quietly drop out of every later one.
    for app in (create_app(), create_app(), create_app()):
        _assert_is_the_reviser(app.get(member.POLICY_REVISER_COMPONENT))
        assert member.POLICY_REVISER_COMPONENT in app.order


def test_scanning_registers_the_component_exactly_once() -> None:
    # A duplicate registration of one name is silently overridden by the
    # registry, so a second ``@register`` for this name would be invisible
    # everywhere except here.
    registry = Registration()
    scan_components(registry=registry)

    names = [component.name for component in registry.components()]
    assert names.count(member.POLICY_REVISER_COMPONENT) == 1


def test_the_name_lands_in_the_sorted_order(configured: Path) -> None:
    # ``app.order`` is name-sorted and other members' suites assert
    # adjacencies over it, so a new name is a claim about a shared ordering.
    # Asserted as inequalities against the two names this component's own
    # story names — the resolver it holds and the gate that judges its
    # candidates — rather than as ``+ 1`` adjacency, so a later member landing
    # between them does not fail this test for a reason that is not about this
    # one.  (``policy-reviser`` sorts before ``policy-runtime`` on the bare
    # string: the shared ``policy-r`` prefix is followed by ``e`` before
    # ``u``.)
    order = create_app().order

    assert order.index("live-providers") < order.index(
        member.POLICY_REVISER_COMPONENT
    )
    assert order.index(member.POLICY_REVISER_COMPONENT) < order.index(
        "policy-runtime"
    )


# -- The None a deployment that authors nothing composes to ----------------------


def test_the_builder_degrades_to_none_without_a_config(monkeypatch) -> None:
    # An unset ``NULLIUS_AUTHORING_CONFIG`` composes no reviser — a
    # discoverable deployment state, not an exception, because a builder that
    # raised would take composition down for every unrelated feature in the
    # workspace.  The *refusal* belongs to the caller that must revise through
    # a model and finds no reviser to do it.
    monkeypatch.delenv("NULLIUS_AUTHORING_CONFIG", raising=False)

    assert create_app().get(member.POLICY_REVISER_COMPONENT) is None


def test_a_blank_variable_degrades_to_none(monkeypatch) -> None:
    # The front door's own second spelling of unset: whitespace-only counts as
    # absent, and the component follows the door rather than re-deciding it.
    monkeypatch.setenv("NULLIUS_AUTHORING_CONFIG", "   ")

    assert member.build_policy_reviser() is None


def test_an_application_without_the_component_answers_none() -> None:
    # No scan at all — nothing was registered — which is a statement about
    # *composition*, and deliberately not the same fact as a deployment that
    # named no config.
    assert Application().get(member.POLICY_REVISER_COMPONENT) is None


# -- The wiring: session, resolver, and the two restraints -----------------------


def test_the_composed_reviser_carries_the_stated_config(configured: Path) -> None:
    # The reviser answers the config the deployment's file parses into —
    # value-equal, because the config is frozen and value-equal by feature 2's
    # own design — so the wiring is over *this deployment's* pins and knobs
    # and not over some default.
    reviser = create_app().get(member.POLICY_REVISER_COMPONENT)
    expected = AuthoringConfig.from_file(configured)

    assert reviser._config == expected
    assert reviser._session.config == expected


def test_composition_resolves_no_provider_and_needs_no_credential(
    configured: Path,
) -> None:
    # The builder's two restraints, held as one state: over a config whose
    # vendor key is absent, composition answers the reviser (a builder that
    # read a key would have refused), the reviser has made no call
    # (``records`` empty), and the session resolved no pin (``providers``
    # empty — the one place a credential is read was never reached).
    reviser = create_app().get(member.POLICY_REVISER_COMPONENT)

    assert reviser.records == []
    assert reviser._session.providers == {}


def test_the_session_refuses_a_pin_in_the_live_registrys_own_vocabulary(
    configured: Path,
) -> None:
    # The wiring claim — *over a providers.AuthoringSession with the
    # "live-providers" resolver* — pinned behaviourally, because the resolver
    # is held privately and the vocabulary is the proof.  The first ask for
    # the policy pin reaches the live registry, which refuses in its own
    # words: ``ProviderNotConfiguredError`` naming the variable the operator
    # forgot and never a value.  A fake resolver would not refuse in this
    # vocabulary; a resolver read eagerly would have refused at composition,
    # which the test above just proved it did not.
    reviser = create_app().get(member.POLICY_REVISER_COMPONENT)

    with pytest.raises(ProviderNotConfiguredError, match=POLICY_KEY_ENV):
        reviser._session.provider_for(
            "policy",
            campaign_id="policy-development",
            node_id="revision-1",
        )


def test_a_named_but_wrong_config_refuses_rather_than_authoring_nothing(
    monkeypatch, tmp_path: Path
) -> None:
    # The front door's own stance, restated at the component: a file that is
    # there and will not parse is a deployment that stated an authoring it
    # does not have, and the refusal naming the key is the operator's fact —
    # swallowing it into ``None`` would be the quieter failure the door's own
    # docstring refuses (the campaign would run with no model behind it and
    # learn nothing).  ``AuthoringConfigError`` is the providers member's
    # vocabulary, propagated unchanged at the seam.  The file is complete
    # except for the one knob past its range, so the refusal that fires is
    # the temperature's own — a missing key would be a different refusal
    # firing first for a different reason.
    broken = tmp_path / "broken.json"
    broken.write_text(
        json.dumps(
            {
                "root_tier": [POLICY_PIN],
                "depth": "deepseek/deepseek-v4-flash/20260910",
                "policy": POLICY_PIN,
                "temperature": 5,
                "max_tokens": 4096,
                "max_input_tokens": 1_000_000,
                "max_output_tokens": 1_000_000,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NULLIUS_AUTHORING_CONFIG", str(broken))

    with pytest.raises(AuthoringConfigError, match="temperature"):
        member.build_policy_reviser()


# -- The package's exports and the member's other component are unchanged --------

#: One name per module the package already re-exported, plus the two builders
#: and the two names the founding component's own seat asserts — the subset
#: net for "every existing export is unchanged": additions are the feature,
#: removals are a regression this catches wherever they land.
_EXISTING_EXPORTS = (
    "COMPONENT_NAME",
    "CycleFreeze",
    "DreamingError",
    "CandidateModule",
    "FamilyTransfer",
    "FreezeRecord",
    "HoldoutRecord",
    "IncumbentCandidate",
    "PairedDifference",
    "PoolSplit",
    "SweepReport",
    "build_cycle_freeze",
    "cycle_rotation",
    "default_reviser",
    "expected_triggers",
    "family_transfer",
    "include_incumbent",
    "ladder_floor",
    "missing_guards",
    "paired_ir_difference",
    "plan_sweep",
    "pool_tables_present",
    "record_cycle_holdout",
    "rejects_thin_pool",
    "rejects_uncapped_sweep",
    "revision_cap",
    "revise_policy",
    "select_argmax",
    "selection_bar",
    "split_replay_pool",
    "sqlite_path",
    "sweep_candidates",
)


def test_the_packages_existing_exports_are_unchanged() -> None:
    # The feature adds two names to ``__all__`` and removes none; the net is a
    # subset assertion rather than a snapshot so a later feature's additions
    # are not this suite's business.
    for name in _EXISTING_EXPORTS:
        assert name in member.__all__, name
    assert "LLMReviser" in member.__all__
    assert "ReviserOutputError" in member.__all__


def test_the_exported_error_is_the_module_own_class() -> None:
    # ``ReviserOutputError`` is feature 9's own class, re-exported — not a
    # copy — and it keeps its place under the member's one base, so a caller
    # catching ``DreamingError`` catches a bad answer beside a thin pool.
    assert member.ReviserOutputError.__module__.endswith("dreaming.llm_reviser")
    assert issubclass(member.ReviserOutputError, member.DreamingError)


def test_the_founding_component_is_unchanged_beside_it(
    monkeypatch, configured: Path, tmp_path: Path
) -> None:
    # A second component must not disturb the first: the same composed
    # application still carries the cycle freeze for the deployment's
    # database, pinned the way ``test_component.py`` pins it.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'composed.db'}")
    app = create_app()

    freeze = app.get(member.COMPONENT_NAME)
    assert type(freeze).__name__ == "CycleFreeze"
    assert type(freeze).__module__.endswith("dreaming.cycle")
    assert member.COMPONENT_NAME in app.order
    assert app.order.count(member.POLICY_REVISER_COMPONENT) == 1


# -- The sweep's default is unmoved ----------------------------------------------


def test_revise_policys_default_reviser_stays_default_reviser() -> None:
    # The sentence's last clause, held as behaviour: a sweep with no
    # ``reviser`` and a sweep naming ``default_reviser`` explicitly answer the
    # same candidates, because determinism in ``(source, count, seed)`` is
    # feature 271's own contract — so a wiring that had quietly re-pointed the
    # default at the model-driven reviser would fail the equality rather than
    # pass by reading source.  The parameter's default stays ``None``, the
    # sentinel the sweep itself resolves.
    incumbent = "def explore(ctx, seed):\n    threshold = 1.0\n    return threshold\n"

    assert revise_policy(incumbent, 3) == revise_policy(
        incumbent, 3, reviser=default_reviser
    )
    assert (
        inspect.signature(revise_policy).parameters["reviser"].default is None
    )
