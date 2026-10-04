"""Feature 6's wiring: the live backends leave the member as exports and a component.

The live-providers addition's sixth feature is the seam between its five
private modules and everything that will call through them: the twelve names
the backends, the registry and the budget wrapper live under are exported from
the package (added to ``__all__``, re-exported from the modules that own them),
and the package registers an eighth component — ``live-providers`` — whose
builder answers a resolver that turns a pinned model back into a live provider.

The two halves every ``*_component`` suite in this member asks, restated in
this feature's terms.  The **registration** half: ``import providers`` joins
the application with a live resolver in it, no central registry edited.  The
**composition** half: ``create_app().get("live-providers")`` hands that
resolver back.

Two properties are this feature's own, and both are about *when* the
environment is read:

* **building reads no variable and makes no call.**  Which credentials a
  deployment holds is a question only a ``resolve()`` asks, so a composition
  on a box with no keys at all (a CI run, an offline replay against recorded
  fixtures) carries the resolver exactly as a production deployment does.
  Asserted by refusing every ``NULLIUS_`` read and every ``urlopen`` while the
  builder runs, and by composing a full application with every live variable
  deleted;

* **only ``resolve()`` reads credentials, at call time.**  The resolver holds
  no snapshot of the environment — the same once-composed resolver refuses a
  pin while the variable is unset and answers one the moment it appears, which
  is what keeps a launcher's later ``export`` from being silently ignored.

No test here opens a socket or reads a real credential.  The keys are fake and
key-shaped, and every rendering a test captures — a provider's ``repr``, a
refusal's message, the resolver itself — is asserted free of them.
"""

from __future__ import annotations

import importlib
import os
import urllib.request
from types import ModuleType
from typing import Any

import providers
import pytest
from providers._live import SELF_HOSTED_API_KEY_ENV

#: Fake credentials — key-shaped, not key-real.  Neither would open a door
#: anywhere; the point is that a suite can hunt for the literal value in every
#: rendering and prove it never escaped.  ``DECOY`` is spelled like the bare
#: claw-forge name's value would be, because one test plants it there and
#: asserts the composed resolver stayed blind to it.
FAKE_KEY = "fake-nullius-key-not-a-credential"
DECOY = "claw-forge-harness-key"

#: The pins a test resolves.  One hosted vendor per backend covers both, and
#: nothing about the resolver is bound to either — that is asserted, not
#: assumed, by resolving both through one resolver below.
PIN = providers.ModelPin("anthropic", "claude-opus-5", "20260401")
DEEPSEEK_PIN = providers.ModelPin("deepseek", "deepseek-chat", "20260401")

#: The variable names, spelled once so an assertion that a refusal *names* one
#: compares against the same string the registry reads.
ANTHROPIC_KEY_ENV = "NULLIUS_ANTHROPIC_API_KEY"
DEEPSEEK_KEY_ENV = "NULLIUS_DEEPSEEK_API_KEY"

#: Every variable the live path reads — the required table plus the optional
#: self-hosted key — so a test that refuses or deletes "every live variable"
#: and the registry's own reading list cannot drift apart.
_LIVE_VARS = frozenset((*providers.LIVE_PROVIDER_ENV_VARS.values(), SELF_HOSTED_API_KEY_ENV))

#: The twelve names feature 6 exports, each with the private module that owns
#: it: the package surface is a re-export, not a second definition, and the
#: identity assertion below is what pins that.
_HOMES = {
    "AnthropicProvider": "_anthropic",
    "ProviderRequestError": "_anthropic",
    "OpenAICompatProvider": "_openai_compat",
    "live_provider": "_live",
    "require_served": "_live",
    "LIVE_PROVIDER_ENV_VARS": "_live",
    "ServedModelMismatchError": "_live",
    "BudgetedProvider": "_budget",
    "BudgetExhaustedError": "_budget",
    "ProviderHostRefusedError": "_live_http",
    "ProviderTransportError": "_live_http",
    "ProviderHTTPError": "_live_http",
}


@pytest.fixture(scope="module")
def application():
    """The composed application, built **once** for this suite's tests.

    Composition is the expensive thing a member suite does (the factory calls
    every member's builder), and — the property under test — nothing about
    this feature's component depends on the environment, so one application
    serves every test that reads a resolver off it.  The environment a
    ``resolve()`` reads is read at resolve time, never folded into the build,
    which is why per-test ``monkeypatch`` fakes still steer the one resolver:
    the fakes change after the build, and the resolver follows.
    """
    from app.module_loader import create_app

    return create_app()


def _member_package(composed: object) -> ModuleType:
    """The member's own package, resolved through a composed object's class.

    The loader imports each member under the ``_nullius_scanned_<pkg>``
    alias, so the resolver an application hands back is an instance of the
    *scanned* copy's class — ``isinstance`` against the directly-imported
    ``providers`` names is False for one and the same source file.  Resolving
    the class's module and then its package root reaches the scanned copy's
    full public surface, which is the copy to build pins' answers and catch
    refusals from.  One helper per suite, on the member-wide convention.
    """
    submodule = importlib.import_module(type(composed).__module__)
    return importlib.import_module(submodule.__package__)


def _resolver_builder() -> Any:
    """The builder the *registry* holds for this feature's component.

    Asserted on through the registry rather than through
    ``providers.build_live_providers`` because the registry's is the callable
    the factory will actually call — the two can differ by module copy, and
    the registration protocol is the registry's to check.
    """
    from app.module_loader import registered_components

    return next(
        component.builder
        for component in registered_components()
        if component.name == providers.LIVE_PROVIDERS_COMPONENT
    )


class _RefusingEnviron(dict):
    """The real environment, minus every variable a credential could hide in.

    Reads of any live variable raise ``AssertionError`` — a read at build
    time is exactly the failure the guard exists to catch — while every other
    name behaves exactly as ``os.environ`` did, so nothing else sharing the
    process notices the substitution.
    """

    def __getitem__(self, name: object) -> str:
        if name in _LIVE_VARS:
            raise AssertionError(
                f"the build read the environment variable {name!r}, and the "
                f"component must resolve no variable — only resolve() may"
            )
        return super().__getitem__(name)

    def get(self, name: object, default: object = None) -> object:
        if name in _LIVE_VARS:
            raise AssertionError(
                f"the build read the environment variable {name!r}, and the "
                f"component must resolve no variable — only resolve() may"
            )
        return super().get(name, default)


# ── The exports: twelve names, re-exported from the modules that own them ─────


def test_every_live_export_is_listed_and_re_exported() -> None:
    # One pass over the twelve names: each is in ``__all__`` (the documented
    # surface a caller composes and imports against) and *is* the owning
    # module's object — a re-export, not a copy, so the class a caller
    # subclasses or the function a test monkeypatches is the one the registry
    # and the backends share.
    for name, home in _HOMES.items():
        assert name in providers.__all__
        module = importlib.import_module(f"providers.{home}")
        assert getattr(providers, name) is getattr(module, name)


def test_the_exported_surface_has_the_shape_callers_bind_against() -> None:
    # The kinds a caller relies on: two live backends and the budget wrapper
    # are the seam's own classes, the six failures join the interface's one
    # error base (a caller catching ``ProviderError`` catches every way the
    # live path stops), the registry's two operations are callable, and the
    # variable table is a read-only mapping.
    for cls in (
        providers.AnthropicProvider,
        providers.OpenAICompatProvider,
    ):
        assert issubclass(cls, providers.Provider)
    assert issubclass(providers.BudgetedProvider, providers.Provider)
    for error in (
        providers.ProviderHostRefusedError,
        providers.ProviderTransportError,
        providers.ProviderHTTPError,
        providers.ProviderRequestError,
        providers.ServedModelMismatchError,
        providers.BudgetExhaustedError,
    ):
        assert issubclass(error, providers.ProviderError)
    assert callable(providers.live_provider)
    assert callable(providers.require_served)
    with pytest.raises(TypeError):
        providers.LIVE_PROVIDER_ENV_VARS["anthropic"] = "NULLIUS_OTHER"  # type: ignore[index]


def test_the_pre_existing_surface_is_unchanged() -> None:
    # The addition only adds.  A sentinel from each of the package's earlier
    # features is still exported, still the same object its module owns, and
    # ``__all__`` carries no duplicate — the alphabetical discipline that
    # keeps the surface greppable.
    sentinel = {
        "Provider": "_provider",
        "prompt_hash": "_recorded",
        "FixtureStore": "_fixture",
        "ModelPin": "_pinning",
        "choose_run_window": "_schedule",
        "select_depth_model": "_cache",
        "route_depth_call": "_batch",
    }
    for name, home in sentinel.items():
        assert name in providers.__all__
        assert getattr(providers, name) is getattr(importlib.import_module(f"providers.{home}"), name)
    assert len(providers.__all__) == len(set(providers.__all__))


# ── The registration: by convention, in the package __init__ ──────────────────


def test_the_member_registers_the_resolver_under_its_own_name() -> None:
    # The decorator fired when this test module imported the member, and the
    # name it registered under is feature 6's — distinct from the seven that
    # went before it, on the same plugin-plus-contribution pattern.  The seven
    # are asserted present too, because "the existing components are
    # unchanged" is half of this feature's own sentence.
    from app.module_loader import registered_components

    names = {component.name for component in registered_components()}
    assert providers.LIVE_PROVIDERS_COMPONENT == "live-providers"
    assert providers.LIVE_PROVIDERS_COMPONENT in names
    assert providers.LIVE_PROVIDERS_COMPONENT not in (
        providers.PROVIDERS_COMPONENT,
        providers.AGENT_MODEL_PIN_COMPONENT,
        providers.DEPTH_RUN_WINDOW_COMPONENT,
        providers.DEPTH_CACHE_RATE_COMPONENT,
        providers.ROOT_SERVING_PROVIDER_COMPONENT,
        providers.ROOT_ROTATION_COMPONENT,
        providers.FIXTURE_STORE_COMPONENT,
    )
    for existing in (
        providers.PROVIDERS_COMPONENT,
        providers.AGENT_MODEL_PIN_COMPONENT,
        providers.DEPTH_RUN_WINDOW_COMPONENT,
        providers.DEPTH_CACHE_RATE_COMPONENT,
        providers.ROOT_SERVING_PROVIDER_COMPONENT,
        providers.ROOT_ROTATION_COMPONENT,
        providers.FIXTURE_STORE_COMPONENT,
    ):
        assert existing in names


def test_scanning_composes_the_resolver_without_a_central_registry(application) -> None:
    # The property the plugin convention exists for: an application built by
    # *scanning* the workspace holds feature 6's component, driven through
    # the loader's own scan because that is the path a deployment takes.
    assert providers.LIVE_PROVIDERS_COMPONENT in application.order
    assert providers.LIVE_PROVIDERS_COMPONENT in dict(application.components)


def test_a_second_composition_in_the_same_process_still_holds_the_resolver() -> None:
    # The submodule-registration trap, asserted directly: the loader imports
    # each member once per process, so a ``@register`` living anywhere but the
    # package ``__init__`` would silently vanish from every composition after
    # the first.  This is the eighth registration — the one that would bite,
    # added long after the first seven made the pattern look safe.
    from app.module_loader import create_app

    first = create_app()
    second = create_app()
    for composed in (first, second):
        assert providers.LIVE_PROVIDERS_COMPONENT in composed.order
        assert composed.get(providers.LIVE_PROVIDERS_COMPONENT) is not None


# ── Building: no variable read, no call made ──────────────────────────────────


def test_building_reads_no_variable_and_makes_no_call(monkeypatch) -> None:
    # The guard is the assertion.  Every variable the live path reads refuses
    # to be read, and the socket door refuses to open, while the builder the
    # *registry* holds runs — a builder that reached for a credential or a
    # vendor inside composition fails here rather than in a deployment that
    # has neither.  The resolver answers with nothing folded in: no provider,
    # no credential, no transport — the instance holds no state at all.
    monkeypatch.setattr(os, "environ", _RefusingEnviron(os.environ))

    def _no_socket(*args: object, **kwargs: object) -> None:
        raise AssertionError(
            f"the build opened a network connection ({args!r}), and the "
            f"component must make no call — only resolve() may"
        )

    monkeypatch.setattr(urllib.request, "urlopen", _no_socket)

    resolver = _resolver_builder()()

    assert callable(resolver.resolve)
    assert not vars(resolver)


def test_the_builder_takes_no_arguments_as_the_registration_protocol_requires() -> None:
    # The factory calls every registered builder with no arguments — that is
    # the protocol — so a builder that grew a parameter would break
    # composition for the whole application.
    resolver = _resolver_builder()()
    assert callable(resolver.resolve)


def test_composing_needs_no_credentials_at_all(monkeypatch) -> None:
    # The deployment-shaped statement of the same property: with every live
    # variable deleted, a *full* ``create_app()`` still answers the resolver —
    # composition succeeds on the CI box and the offline replay exactly as it
    # does in production, and the credential question is left for resolve().
    for name in _LIVE_VARS:
        monkeypatch.delenv(name, raising=False)
    from app.module_loader import create_app

    resolver = create_app().get("live-providers")

    assert resolver is not None
    assert callable(resolver.resolve)
    # ...and the resolver composed without credentials is the one that
    # refuses a pin naming the variable — the refusal is resolve's, not the
    # composition's, and it names the variable without rendering any value.
    member = _member_package(resolver)
    with pytest.raises(member.ProviderNotConfiguredError) as caught:
        resolver.resolve(PIN)
    assert ANTHROPIC_KEY_ENV in str(caught.value)


# ── The composition: one application, one resolver, resolve-time reads ─────────


def test_the_application_hands_back_the_resolver(application) -> None:
    # The spec's own sentence, spelled literally: ``create_app().get(
    # "live-providers")`` answers the resolver.  It is *that* application's
    # own component (not a fresh composition), it is the scanned copy's class
    # by name — the two-copies fact every composed-component suite in this
    # member records — and it is the member's class, one source file, twice.
    resolver = application.get("live-providers")

    assert resolver is dict(application.components)[providers.LIVE_PROVIDERS_COMPONENT]
    assert type(resolver).__name__ == "LiveProviderResolver"
    assert type(resolver).__module__.startswith("_nullius_scanned_providers")
    assert type(resolver) is not providers.LiveProviderResolver
    assert type(resolver).__name__ == providers.LiveProviderResolver.__name__
    assert callable(resolver.resolve)


def test_resolve_answers_the_registrys_provider_for_the_pinned_model(
    application, monkeypatch
) -> None:
    # The composition seam, end to end: a pin resolves through the once-built
    # resolver to the backend the registry chooses for its vendor, built for
    # the pin's model — the provider's own statement of what it will put on
    # the wire — and the fake key never reaches the rendering an operator
    # would actually read.
    monkeypatch.setenv(ANTHROPIC_KEY_ENV, FAKE_KEY)
    resolver = application.get("live-providers")
    member = _member_package(resolver)

    provider = resolver.resolve(PIN)

    assert isinstance(provider, member.AnthropicProvider)
    assert isinstance(provider, member.Provider)
    assert provider.check_model(PIN.model) == PIN.model
    assert FAKE_KEY not in repr(provider)
    assert FAKE_KEY not in repr(resolver)


def test_one_resolver_serves_every_vendor(application, monkeypatch) -> None:
    # Nothing about the resolver is bound at build time — not even *which*
    # vendor.  Two pins, two backends, one resolver: the vendor chooses the
    # backend per resolve, which is the registry's own rule inherited by the
    # composed door, and the key stays out of both renderings.
    monkeypatch.setenv(ANTHROPIC_KEY_ENV, FAKE_KEY)
    monkeypatch.setenv(DEEPSEEK_KEY_ENV, FAKE_KEY)
    resolver = application.get("live-providers")
    member = _member_package(resolver)

    hosted = resolver.resolve(PIN)
    clone = resolver.resolve(DEEPSEEK_PIN)

    assert isinstance(hosted, member.AnthropicProvider)
    assert isinstance(clone, member.OpenAICompatProvider)
    assert "deepseek" in repr(clone)
    assert FAKE_KEY not in repr(clone)


def test_resolve_reads_the_environment_at_call_time_not_build_time(
    application, monkeypatch
) -> None:
    # The load-bearing "only resolve() reads credentials", on one and the
    # same once-composed resolver: with the variable deleted the resolve
    # refuses naming it; with a fake set afterwards the *same* resolver
    # answers a provider.  A resolver that had snapshotted the environment
    # at build time would answer the second call with the first call's
    # world — exactly the launcher-exports-too-late failure this feature
    # exists not to have.
    monkeypatch.delenv(ANTHROPIC_KEY_ENV, raising=False)
    resolver = application.get("live-providers")
    member = _member_package(resolver)

    with pytest.raises(member.ProviderNotConfiguredError):
        resolver.resolve(PIN)

    monkeypatch.setenv(ANTHROPIC_KEY_ENV, FAKE_KEY)
    provider = resolver.resolve(PIN)

    assert type(provider).__name__ == "AnthropicProvider"
    assert provider.check_model(PIN.model) == PIN.model


def test_a_missing_credential_names_the_variable_and_never_a_value(
    application, monkeypatch
) -> None:
    # The refusal an operator acts on: the variable's name is in the message
    # and the values are not — not the unset one's neighbours, not the bare
    # claw-forge name planted where a research member must never read it.
    # A refusal is one of the three places a credential must never reach.
    for name in _LIVE_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", DECOY)
    resolver = application.get("live-providers")
    member = _member_package(resolver)

    with pytest.raises(member.ProviderNotConfiguredError) as caught:
        resolver.resolve(PIN)

    message = str(caught.value)
    assert ANTHROPIC_KEY_ENV in message
    assert FAKE_KEY not in message
    assert DECOY not in message
