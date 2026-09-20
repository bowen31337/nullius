"""Feature 167: the screen — every submission answered, and the answer is returned.

The sentence's second half, at the seam a *module* is offered: *System
rejects a submitted module importing anything outside the configured
allowlist, which returns a disallowed_import error message.*  The submission
is untrusted source the pipeline offers unattended, over thousands of
candidates, so the screen *answers* — a :class:`~sandbox.ModuleDecision`,
never a raise, for the same reason feature 157's gate answers runs rather
than raising per run — and the answer's ``detail`` *is* the
``disallowed_import`` error message the sentence names, beginning with the
greppable code and naming every offender with its line so the author repairs
them all rather than resubmitting to learn the rest.

The refusals are grouped by the reason each earns, because the reason is the
audit record: a submission that is not source at all, one that does not
parse, and one that imports outside the ceiling are three different facts
about three different failures, and collapsing them into one "refused" would
leave the loop unable to tell its own bug from the law working.

The last group proves the derivation is real: the screen admits *because the
compiled ceiling covers every term*, not because it was told to — so a
narrower hand-built ceiling refuses what the committed one admits, which is
exactly why a drifted artifact can never quietly widen the box.
"""

from __future__ import annotations

import pytest
from _documents import (
    OS_MODULE,
    POLARS,
    SOURCE_IMPORTING_PARENT,
    SOURCE_RELATIVE,
    SOURCE_UNPARSABLE,
    SOURCE_WITH_OS_AND_SOCKET,
    SOURCE_WITH_TIME,
    SOURCE_WITHIN,
    allowlist_document,
    committed_allowlist_document,
)
from sandbox import (
    DISALLOWED_IMPORT_CODE,
    IMPORTS_POLICY_KIND,
    AllowlistDocumentError,
    DisallowedImportError,
    ModuleDecision,
    ModuleReason,
    compile_imports_allowlist,
    screen_module,
)


@pytest.fixture()
def ceiling():
    """The committed document, compiled — the ceiling the screen answers for."""
    return compile_imports_allowlist(committed_allowlist_document())


class TestTheAdmittedSubmission:
    """The submission the law exists to let through."""

    def test_a_module_whose_imports_are_all_covered_is_admitted(self, ceiling) -> None:
        decision = screen_module(SOURCE_WITHIN, ceiling)
        assert decision.admitted is True
        assert decision.reason is ModuleReason.BY_ALLOWLIST

    def test_the_admission_counts_the_imports_it_checked(self, ceiling) -> None:
        """So 'all N imports checked' is a fact the decision carries rather
        than a claim a reader has to take on trust."""
        decision = screen_module(SOURCE_WITHIN, ceiling)
        assert "5" in decision.detail

    def test_a_module_importing_nothing_is_admitted(self, ceiling) -> None:
        """The law is about imports; a module that makes none violates
        nothing, whatever else it does — the screen is not a content
        filter, the same stance the isolation gate takes toward a run's
        payload."""
        decision = screen_module("x = 1\n", ceiling)
        assert decision.admitted is True

    def test_the_decision_forms_a_stable_audit_record(self, ceiling) -> None:
        """Two screens of one source compose the same reason; the reason is
        a closed enum, so an audit line is greppable."""
        first = screen_module(SOURCE_WITHIN, ceiling)
        second = screen_module(SOURCE_WITHIN, ceiling)
        assert first.reason == second.reason
        assert first.reason == "by-allowlist"

    def test_an_import_nested_in_a_function_is_still_an_import(self, ceiling) -> None:
        """'Anything' is total: an import that executes on some path is an
        import, and a screen that read only the top of the file would be
        reporting clean over the half it never checked."""
        source = "def f():\n    import os\n"
        decision = screen_module(source, ceiling)
        assert decision.admitted is False
        assert decision.reason is ModuleReason.OUTSIDE_ALLOWLIST

    def test_a_conditional_import_is_still_an_import(self, ceiling) -> None:
        source = "if False:\n    import socket\n"
        decision = screen_module(source, ceiling)
        assert decision.admitted is False


class TestTheRefusalOutsideTheAllowlist:
    """The feature's headline: a module importing outside the ceiling."""

    def test_a_disallowed_module_is_refused(self, ceiling) -> None:
        decision = screen_module(SOURCE_WITH_TIME, ceiling)
        assert decision.admitted is False
        assert decision.reason is ModuleReason.OUTSIDE_ALLOWLIST

    def test_the_refusal_carries_the_features_own_code(self, ceiling) -> None:
        """The sentence says the rejection *returns a disallowed_import
        error message*; the returned detail is that message, and it begins
        with the one greppable token an operator or CI check looks for."""
        decision = screen_module(SOURCE_WITH_TIME, ceiling)
        assert decision.detail.startswith(DISALLOWED_IMPORT_CODE)

    def test_the_refusal_names_every_offender_not_only_the_first(self, ceiling) -> None:
        """The reader of the refusal is the author of the submission, and a
        screen that reported one offender at a time would be resubmitted to
        learn the rest — the same discipline the canary's collective
        refusal states for its own screen."""
        decision = screen_module(SOURCE_WITH_OS_AND_SOCKET, ceiling)
        assert OS_MODULE in decision.detail
        assert "socket" in decision.detail

    def test_the_refusal_names_the_line_each_offender_sits_on(self, ceiling) -> None:
        """So the repair is actionable: 'line 1' and 'line 3' are where the
        two offenders of :data:`SOURCE_WITH_OS_AND_SOCKET` live."""
        decision = screen_module(SOURCE_WITH_OS_AND_SOCKET, ceiling)
        assert "line 1: 'os'" in decision.detail
        assert "line 3: 'socket'" in decision.detail

    def test_the_refusal_names_the_ceiling_it_answered_for(self, ceiling) -> None:
        """An operator reading the refusal learns what the deployment
        admits, not merely that the submission was refused."""
        decision = screen_module(SOURCE_WITH_TIME, ceiling)
        assert IMPORTS_POLICY_KIND in decision.detail
        assert POLARS in decision.detail

    def test_an_aliased_import_does_not_launder_the_term(self, ceiling) -> None:
        """``import os as anything`` still executes ``os``; the alias is a
        name for the author, not for the law."""
        decision = screen_module("import os as _private\n", ceiling)
        assert decision.admitted is False
        assert "'os'" in decision.detail

    def test_a_relative_import_is_outside_by_construction(self, ceiling) -> None:
        """A submitted module is one module, not a package with siblings:
        the box holds no package for ``.`` to resolve against, and the
        ceiling's terms are absolute dotted names, so no configuration
        could ever vouch for one."""
        decision = screen_module(SOURCE_RELATIVE, ceiling)
        assert decision.admitted is False
        assert decision.reason is ModuleReason.OUTSIDE_ALLOWLIST
        assert "'.sibling'" in decision.detail

    def test_a_dotted_relative_import_is_spelled_as_written(self, ceiling) -> None:
        """``from .mod import x`` is refused naming ``.mod.x`` — the
        refusal's reader sees the term as the author wrote it, whichever
        relative shape it took."""
        decision = screen_module("from .mod import x\n", ceiling)
        assert decision.admitted is False
        assert "'.mod.x'" in decision.detail

    def test_a_star_import_is_outside_by_construction(self, ceiling) -> None:
        """The star binds everything at once and names a term no
        well-formed entry covers — the one term no allowlist can judge."""
        decision = screen_module("from os import *\n", ceiling)
        assert decision.admitted is False
        assert "'os.*'" in decision.detail

    def test_a_parent_is_outside_when_only_a_child_is_admitted(self) -> None:
        """The prefix rule's refusal half, seen from the screen: a ceiling
        naming only ``numpy.linalg`` does not admit ``import numpy``,
        because importing the parent executes the parent."""
        narrow = compile_imports_allowlist(allowlist_document("numpy.linalg"))
        decision = screen_module(SOURCE_IMPORTING_PARENT, narrow)
        assert decision.admitted is False
        assert decision.reason is ModuleReason.OUTSIDE_ALLOWLIST

    def test_one_disallowed_term_refuses_the_whole_module(self, ceiling) -> None:
        """The whole submission, not the offending import skipped: a module
        admitted with its disallowed import silently dropped is one whose
        file and whose execution disagree — the same whole-document
        refusal the compiles make."""
        source = "import math\nimport os\nfrom decimal import Decimal\n"
        decision = screen_module(source, ceiling)
        assert decision.admitted is False
        assert "1 of its 3" in decision.detail


class TestTheRefusalBeforeTheLaw:
    """Submissions the screen cannot check, kept apart from the headline."""

    def test_source_that_is_not_a_string_is_refused(self, ceiling) -> None:
        decision = screen_module(b"import math", ceiling)
        assert decision.admitted is False
        assert decision.reason is ModuleReason.UNREADABLE_SOURCE

    def test_blank_source_is_refused(self, ceiling) -> None:
        """The screen cannot admit what it cannot read, and passing blank
        source would be reporting clean over code it never checked — the
        vacuous green no admission screen may allow."""
        decision = screen_module("   \n\t", ceiling)
        assert decision.admitted is False
        assert decision.reason is ModuleReason.UNREADABLE_SOURCE

    def test_source_that_does_not_parse_is_refused(self, ceiling) -> None:
        decision = screen_module(SOURCE_UNPARSABLE, ceiling)
        assert decision.admitted is False
        assert decision.reason is ModuleReason.UNPARSABLE_SOURCE

    def test_the_unparsable_refusal_names_the_break(self, ceiling) -> None:
        """So the author learns their module does not parse — their bug —
        rather than a refusal about imports the reader would go hunting
        for."""
        decision = screen_module(SOURCE_UNPARSABLE, ceiling)
        assert "line 2" in decision.detail

    def test_the_refusals_before_the_law_carry_the_code_too(self, ceiling) -> None:
        """One feature, one spelling, whichever way the refusal arrived —
        the same discipline feature 157's gate applies to its unnamed and
        unknown runs."""
        for source in (None, "def broken(:"):
            decision = screen_module(source, ceiling)
            assert decision.detail.startswith(DISALLOWED_IMPORT_CODE), source

    def test_the_three_refusals_are_three_distinct_facts(self, ceiling) -> None:
        """Collapsing them into one 'refused' would leave the loop unable
        to tell its own syntax error from the law working."""
        reasons = {
            screen_module(None, ceiling).reason,
            screen_module("def broken(:", ceiling).reason,
            screen_module(SOURCE_WITH_TIME, ceiling).reason,
        }
        assert len(reasons) == 3


class TestTheDerivedAnswer:
    """The admission is computed from the compiled ceiling."""

    def test_the_screen_consults_the_ceiling_it_was_handed(self) -> None:
        """The coverage is the ceiling's, not a constant: the same source
        against two ceilings carrying different terms gets two answers."""
        committed = compile_imports_allowlist(committed_allowlist_document())
        polars_only = compile_imports_allowlist(allowlist_document(POLARS))
        source = "import math\n"
        assert screen_module(source, committed).admitted is True
        assert screen_module(source, polars_only).admitted is False

    def test_a_loose_ceiling_is_refused_rather_than_re_validated(self, ceiling) -> None:
        """The ceiling is a validated value: a caller that hands the screen
        a list — the hurried edit's mistake — hears it from the vocabulary's
        own error rather than an ``AttributeError`` mid-refusal."""
        with pytest.raises(AllowlistDocumentError):
            screen_module(SOURCE_WITHIN, ["math"])

    def test_an_empty_ceiling_refuses_everything_that_imports(self) -> None:
        """The strictest ceiling is a real deployment state, and the screen
        answers for it exactly as it answers for the committed one."""
        empty = compile_imports_allowlist(allowlist_document())
        assert screen_module("import math\n", empty).admitted is False
        assert screen_module("x = 1\n", empty).admitted is True


class TestRequire:
    """The bridge from the screen's answer to the exception a launcher wants."""

    def test_require_on_an_admitted_submission_is_a_no_op(self, ceiling) -> None:
        """So a launcher can call it unconditionally on the last line
        before it would have run the module, rather than branching and
        remembering."""
        assert screen_module(SOURCE_WITHIN, ceiling).require() is None

    def test_require_raises_the_members_own_error(self, ceiling) -> None:
        with pytest.raises(DisallowedImportError):
            screen_module(SOURCE_WITH_TIME, ceiling).require()

    def test_require_carries_the_screens_own_sentence(self, ceiling) -> None:
        """The exception is the decision's detail, so the raised message
        and the returned one cannot say different things — the sentence's
        'returns' and the launcher's 'raises' are one message in two
        shapes."""
        decision = screen_module(SOURCE_WITH_TIME, ceiling)
        with pytest.raises(DisallowedImportError) as raised:
            decision.require()
        assert str(raised.value) == decision.detail

    def test_a_decision_refusing_is_not_the_same_object_as_one_admitting(
        self, ceiling
    ) -> None:
        """Two decisions are two records, so an audit keeps both."""
        admitted = screen_module(SOURCE_WITHIN, ceiling)
        refused = screen_module(SOURCE_WITH_TIME, ceiling)
        assert isinstance(admitted, ModuleDecision) and isinstance(refused, ModuleDecision)
        assert admitted.admitted is not refused.admitted
