"""Feature 167: the member's own surface — the facade over the law.

The component the factory composes (:class:`sandbox.SandboxImports`) is the
same stateless shape feature 157's :class:`sandbox.SandboxIsolation` gives
the isolation law: a facade over :mod:`sandbox.imports` and the committed
ceiling it compiled, so it carries the value a caller uses without
importing the member's submodules by name.  This file pins that surface:
which verbs exist, that each delegates rather than re-implements, that the
convenience constructor is the same call the builder makes minus
composition.

The delegation matters for the same reason it does on the isolation facade:
a ``screen`` that re-implemented the coverage rule would pass every test in
:mod:`test_imports_screen` that goes through :func:`~sandbox.screen_module`
while refusing nothing for a caller who used the component's own verb.  The
tests below drive the *component* and assert on the same law the module
tests assert on.
"""

from __future__ import annotations

import pytest
from _documents import (
    SOURCE_WITH_TIME,
    SOURCE_WITHIN,
    committed_allowlist_document,
)
from sandbox import (
    DISALLOWED_IMPORT_CODE,
    ModuleReason,
    SandboxImports,
    committed_imports_allowlist,
    compile_imports_allowlist,
    sandbox_imports,
)


@pytest.fixture()
def law() -> SandboxImports:
    """The composed component's value — the committed ceiling, as a facade."""
    return sandbox_imports()


class TestTheFacade:
    """The surface a caller holds when it holds the component."""

    def test_screen_returns_the_screens_decision(self, law) -> None:
        """One call into :mod:`sandbox.imports`, the decision back — the
        facade's ``screen`` is the module's gate, not a second one."""
        decision = law.screen(SOURCE_WITHIN)
        assert decision.admitted is True
        assert decision.reason is ModuleReason.BY_ALLOWLIST

    def test_the_facade_refuses_what_the_law_refuses(self, law) -> None:
        decision = law.screen(SOURCE_WITH_TIME)
        assert decision.admitted is False
        assert decision.detail.startswith(DISALLOWED_IMPORT_CODE)

    def test_require_is_the_bridge_to_the_members_own_error(self, law) -> None:
        """The launcher's verb: no-op on an admitted submission, the
        exception on a refused one — usable unconditionally on the last
        line before the module would have run."""
        from sandbox import DisallowedImportError

        assert law.require(SOURCE_WITHIN) is None
        with pytest.raises(DisallowedImportError):
            law.require(SOURCE_WITH_TIME)

    def test_covers_answers_for_one_term_without_a_submission(self, law) -> None:
        """The read side: *may sandboxed code import this?* is a question a
        deployment answers from the compiled artifact, not by submitting a
        module to find out."""
        assert law.covers("polars.DataFrame") is True
        assert law.covers("time") is False

    def test_terms_answers_in_document_order(self, law) -> None:
        assert law.terms() == committed_imports_allowlist().terms()

    def test_the_facade_answers_for_the_ceiling_it_was_built_with(self) -> None:
        """The coverage is the built ceiling's, not a constant the facade
        re-derives: a narrow facade refuses what the committed one admits."""
        narrow = SandboxImports(
            compile_imports_allowlist(committed_allowlist_document())
        )
        narrower = SandboxImports(compile_imports_allowlist({"policy": "sandbox-imports", "allow": []}))
        source = "import math\n"
        assert narrow.screen(source).admitted is True
        assert narrower.screen(source).admitted is False

    def test_the_allowlist_property_is_the_compiled_ceiling(self, law) -> None:
        """So a CI check or operator script reads the artifact through the
        component rather than re-deriving it."""
        assert law.allowlist.kind == "sandbox-imports"

    def test_the_convenience_constructor_is_the_builder_minus_composition(
        self, law
    ) -> None:
        """``sandbox_imports()`` and the composed component carry the same
        ceiling, so a caller that wants the law directly and a caller that
        asks the factory are answered by one law."""
        assert law.terms() == sandbox_imports().terms()
