"""Suite-local fixtures for the providers package's tests.

This suite lives inside the workspace member (``packages/providers/tests``)
rather than the repository-level ``tests/`` tree, so the shared fixtures in
``tests/conftest.py`` do not reach it — conftest scope follows directories.
The path bootstrap below puts the member's ``src/`` on ``sys.path`` — the same
mechanism the module loader uses when it scans members — because the root
project does not depend on this member and the venv therefore does not install
it; this suite runs with the repository's pytest (``uv run pytest
packages/providers`` from the workspace root).

The shared builders a test needs — a scripted provider, and the request and
completion constructors — are exposed as fixtures that return factory
callables, the way ``packages/snapshot``'s suite exposes its service.  They
are fixtures rather than a ``helpers.py`` imported by name because a bare
``from helpers import ...`` (or ``from conftest import ...``) resolves to
whichever suite's module was imported first the moment two suites run under
one pytest — the collision the ``infra/security`` suites avoid by importing
helpers on a full namespace path.  This member is not a namespace package, so
it follows the ``packages/`` convention instead: everything a test shares
lives in this conftest, and pytest injects it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from providers import (
    Completion,
    Message,
    Provider,
    Request,
    Usage,
)


class ScriptedProvider(Provider):
    """A test provider that answers from a caller-supplied function.

    The honest shape of a concrete provider: it puts its "transport" in
    :meth:`_complete` as a callable, and inherits the interface's request
    validation, completion validation and error vocabulary from the base
    class for free.  A suite drives the interface through it — the request a
    caller sends, the completion that comes back, the refusals when either is
    malformed — the way feature 150's suites drive the boundary through
    ``RecordingProviderClient``.
    """

    def __init__(self, responder, *, models=None):
        self._responder = responder
        self._models = models

    def _complete(self, request: Request) -> Completion:
        return self._responder(request)

    def check_model(self, model: str) -> str:
        if self._models is not None and model not in self._models:
            from providers import UnknownModelError

            raise UnknownModelError(
                f"this provider does not serve {model!r}; it serves "
                f"{sorted(self._models)}"
            )
        return model


@pytest.fixture
def scripted_provider():
    """Return the :class:`ScriptedProvider` class, for a test to instantiate.

    A factory fixture rather than a bare import: the test supplies the
    responder (and, where it wants to, the served-model set), so the provider
    is built per test with the transport that test is exercising.
    """
    return ScriptedProvider


@pytest.fixture
def make_completion():
    """Return a builder that makes a :class:`Completion` with sensible defaults."""

    def _make(content="answer", *, model="test-model", **usage):
        return Completion(
            content=content,
            model=model,
            usage=Usage(
                input_tokens=usage.get("input_tokens", 1),
                output_tokens=usage.get("output_tokens", 2),
                cache_read_tokens=usage.get("cache_read_tokens", 0),
            ),
        )

    return _make


@pytest.fixture
def make_request():
    """Return a builder that makes a :class:`Request` with sensible defaults."""

    def _make(*, model="test-model", temperature=0.0, max_tokens=64, bodies=()):
        return Request(
            messages=tuple(
                Message(role=role, content=content) for role, content in bodies
            ),
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    return _make
