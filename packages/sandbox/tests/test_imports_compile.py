"""Feature 167: the allowlist compile — a ceiling that cannot be read is refused.

The sentence's first half, at the seam a *configuration* is written: *System
rejects a submitted module importing anything outside the configured
allowlist* — and "the configured allowlist" is only a refusable condition if
the configuration itself is a document this member can read.  A ceiling is
written by trusted code — an operator, a deployment manifest, a CI check
recompiling the committed artifact — so a document that cannot be read is
refused with an exception the caller cannot ignore
(:class:`~sandbox.AllowlistDocumentError`), the same split feature 157's
compile draws for its own document and for the same reason: a screen run
against a half-read ceiling would be reporting decisions over a law nobody
wrote.

The one deliberate contrast with feature 157's compile is pinned here too:
an isolation policy that names no components is refused (a membership law
that vouches for nothing has no subject), while an allowlist that admits no
terms is *legal* — the strictest ceiling there is, refusing every submission
that imports anything.  A ceiling and a membership law fail in opposite
directions, and the compiles say so in opposite ways.
"""

from __future__ import annotations

import json

import pytest
from _documents import (
    COMMITTED_ALLOWLIST_TERMS,
    OS_MODULE,
    POLARS,
    allowlist_document,
    committed_allowlist_document,
)
from sandbox import (
    IMPORTS_POLICY_KIND,
    AllowlistDocumentError,
    compile_imports_allowlist,
    load_imports_allowlist,
)


class TestCompliantDocuments:
    """The documents the compiler admits, and what it hands back."""

    def test_a_compliant_document_compiles(self) -> None:
        """The base case, so the refusals below are refusals of drift rather
        than refusals of everything."""
        ceiling = compile_imports_allowlist(committed_allowlist_document())
        assert ceiling.terms() == COMMITTED_ALLOWLIST_TERMS

    def test_the_terms_come_back_in_document_order(self) -> None:
        """Order is the document's, so a reader auditing the compiled
        ceiling against the file sees the same list — the same property the
        isolation policy's components carry."""
        ceiling = compile_imports_allowlist(allowlist_document(POLARS, "math"))
        assert ceiling.terms() == ("polars", "math")

    def test_the_compiled_kind_is_the_marker(self) -> None:
        """A caller holding a compiled ceiling can say which law it is
        without re-reading the document it came from."""
        assert compile_imports_allowlist(committed_allowlist_document()).kind == (
            IMPORTS_POLICY_KIND
        )

    def test_an_empty_allowlist_is_the_strictest_ceiling_not_a_refusal(self) -> None:
        """The contrast with feature 157's compile, stated as behaviour: a
        membership law naming no components is refused, a ceiling admitting
        no terms is the strongest version of itself.  A deployment that
        wants "no imports at all" writes it as an empty list, and every
        submission importing anything is refused against it."""
        ceiling = compile_imports_allowlist(allowlist_document())
        assert ceiling.terms() == ()
        assert ceiling.covers("math") is False


class TestTheCoverageRule:
    """Prefix coverage: an entry admits itself and its subtree, never its
    parent."""

    def test_a_term_is_covered_by_its_own_entry(self) -> None:
        ceiling = compile_imports_allowlist(allowlist_document(POLARS))
        assert ceiling.covers(POLARS) is True

    def test_a_term_is_covered_by_an_ancestor_entry(self) -> None:
        """``polars`` admits ``polars.DataFrame`` and every deeper path — a
        from-import landing on a subpackage is judged as the subpackage and
        covered by the package's entry."""
        ceiling = compile_imports_allowlist(allowlist_document(POLARS))
        assert ceiling.covers("polars.DataFrame") is True
        assert ceiling.covers("polars.lazyframe.frame") is True

    def test_a_parent_is_not_covered_by_a_child_entry(self) -> None:
        """The half-check the prefix rule exists to close: importing a
        parent executes the parent, so an entry naming ``numpy.linalg``
        does not admit ``numpy``."""
        ceiling = compile_imports_allowlist(allowlist_document("numpy.linalg"))
        assert ceiling.covers("numpy") is False
        assert ceiling.covers("numpy.linalg") is True

    def test_a_sibling_is_not_covered_by_a_sibling_entry(self) -> None:
        """Coverage runs down the tree, not across it."""
        ceiling = compile_imports_allowlist(allowlist_document("numpy.linalg"))
        assert ceiling.covers("numpy.fft") is False

    def test_a_term_the_ceiling_never_names_is_not_covered(self) -> None:
        ceiling = compile_imports_allowlist(committed_allowlist_document())
        assert ceiling.covers(OS_MODULE) is False

    def test_a_relative_spelling_is_covered_by_nothing(self) -> None:
        """The allowlist's terms are absolute dotted names, so a relative
        import is outside the ceiling *by construction* — no configuration
        can ever vouch for one, which is the property that makes the
        screen's relative-import refusal in :mod:`test_imports_screen` a
        fact about the grammar rather than about one deployment's list."""
        ceiling = compile_imports_allowlist(allowlist_document("sibling"))
        assert ceiling.covers(".sibling") is False
        assert ceiling.covers(".") is False

    def test_a_non_string_is_covered_by_nothing(self) -> None:
        """The conservative answer: a value that names no module is
        admitted by no entry, the answer the screen's refusal gives it."""
        ceiling = compile_imports_allowlist(allowlist_document(POLARS))
        assert ceiling.covers(None) is False
        assert ceiling.covers(42) is False


class TestUnreadableDocuments:
    """The document contract: fail closed, the whole document."""

    def test_a_non_mapping_is_refused(self) -> None:
        with pytest.raises(AllowlistDocumentError):
            compile_imports_allowlist(["polars"])

    def test_a_missing_marker_is_refused(self) -> None:
        with pytest.raises(AllowlistDocumentError):
            compile_imports_allowlist({"allow": [POLARS]})

    def test_a_wrong_marker_is_refused(self) -> None:
        """A stray JSON file carrying an ``allow`` key is not this
        configuration — the marker is what says so."""
        with pytest.raises(AllowlistDocumentError):
            compile_imports_allowlist({"policy": "sandbox-isolation", "allow": [POLARS]})

    def test_a_non_string_marker_is_refused(self) -> None:
        with pytest.raises(AllowlistDocumentError):
            compile_imports_allowlist({"policy": 167, "allow": [POLARS]})

    def test_a_missing_allow_list_is_refused(self) -> None:
        with pytest.raises(AllowlistDocumentError):
            compile_imports_allowlist({"policy": IMPORTS_POLICY_KIND})

    def test_a_non_list_allow_is_refused(self) -> None:
        """A single term as a bare string is the drift a hurried edit
        writes; a compiler that accepted it would hold a ceiling of one
        character."""
        with pytest.raises(AllowlistDocumentError):
            compile_imports_allowlist({"policy": IMPORTS_POLICY_KIND, "allow": POLARS})

    @pytest.mark.parametrize(
        ("term", "why"),
        [
            ("", "an empty term"),
            (".polars", "a leading relative dot"),
            ("polars.", "a trailing dot"),
            ("polars..lazy", "an empty segment"),
            ("po lars", "a space"),
            ("polars.*", "a star"),
            ("1polars", "a leading digit"),
            (167, "not a string at all"),
        ],
    )
    def test_a_term_that_is_not_a_dotted_name_is_refused(self, term, why) -> None:
        """Each malformed spelling names no module an allowlist can judge,
        and a ceiling compiled with one would carry a hole no import could
        match — the parameterization is the audit of the grammar."""
        with pytest.raises(AllowlistDocumentError):
            compile_imports_allowlist({"policy": IMPORTS_POLICY_KIND, "allow": [term]})

    def test_a_duplicate_term_is_refused(self) -> None:
        """One term listed twice is one term described twice, and the
        applied ceiling would be whichever spelling came last — drift with
        extra steps, the same refusal feature 157's compile makes of a
        duplicate component name."""
        with pytest.raises(AllowlistDocumentError):
            compile_imports_allowlist(allowlist_document(POLARS, POLARS))

    def test_the_refusal_names_the_offending_term(self) -> None:
        """So the operator fixing the document knows which term to fix
        rather than merely that the document is wrong."""
        with pytest.raises(AllowlistDocumentError) as raised:
            compile_imports_allowlist(
                {"policy": IMPORTS_POLICY_KIND, "allow": [POLARS, "pol ars"]}
            )
        assert "pol ars" in str(raised.value)


class TestLoadingFromDisk:
    """The committed artifact is not privileged: the same law reads it."""

    def test_a_document_written_to_disk_compiles(self, tmp_path) -> None:
        path = tmp_path / "allowlist.json"
        path.write_text(json.dumps(committed_allowlist_document()), encoding="utf-8")
        assert load_imports_allowlist(path).terms() == COMMITTED_ALLOWLIST_TERMS

    def test_an_unreadable_file_is_refused(self, tmp_path) -> None:
        with pytest.raises(AllowlistDocumentError):
            load_imports_allowlist(tmp_path / "not-there.json")

    def test_a_file_of_invalid_json_is_refused(self, tmp_path) -> None:
        path = tmp_path / "broken.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(AllowlistDocumentError):
            load_imports_allowlist(path)

    def test_a_drifted_file_on_disk_is_refused_as_a_drift_in_memory_would_be(
        self, tmp_path
    ) -> None:
        """The posture that makes the committed artifact checkable: what
        would be refused as a document is refused as a file, so a drift
        written to disk never becomes the deployed ceiling."""
        path = tmp_path / "drifted.json"
        path.write_text(
            json.dumps({"policy": IMPORTS_POLICY_KIND, "allow": [POLARS, "os."]}),
            encoding="utf-8",
        )
        with pytest.raises(AllowlistDocumentError):
            load_imports_allowlist(path)
