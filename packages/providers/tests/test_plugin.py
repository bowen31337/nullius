"""The providers plugin registers by convention, contributing no component.

Feature 192 is a contract and a set of records, not a service the deployment
instantiates once, so the plugin's ``@register`` builder returns ``None`` and
contributes nothing to the composed application — but importing the module is
what joins the application, and the interface's records are importable
directly.  These tests assert both: the builder contributes nothing, and the
seams it defines are the ones the rest of the system builds on.
"""

from __future__ import annotations

import providers


def test_builder_contributes_no_component():
    # The provider interface is a contract, not a service: the builder returns
    # None so composition contributes nothing, and callers hold a provider
    # directly.
    assert providers.provider_interface() is None


def test_interface_records_are_importable_directly():
    # A caller, a suite and the sibling features (the recorded-fixture backend
    # of 193, the fixture recorder of 194) build on these seams by importing
    # them directly — there is one way to name the interface.
    for name in (
        "Provider",
        "Completion",
        "Request",
        "Message",
        "Usage",
        "RecordingProvider",
        "Exchange",
        "ProviderError",
        "CompletionMalformedError",
        "ProviderNotConfiguredError",
        "UnknownModelError",
    ):
        assert hasattr(providers, name)


def test_builder_is_registered_by_convention():
    # Importing the module joined the application: the builder is in the
    # current registry under its plugin name, with no central registry, router
    # or factory edited to add it.
    from app.module_loader import registered_components

    names = [c.name for c in registered_components()]
    assert "providers" in names
