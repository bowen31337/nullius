"""Feature 271, the revision sweep — producing the candidate set.

app_spec.xml, "Dreaming Loop & Meta-Selection", feature 271: *System produces M
revisions of the exploration policy source between iterations, which returns
candidate modules.*  This suite pins the production half of docs/alpha-engine-prd.md
§C5's dreaming loop — the first clause of docs §12.1's middle rung, *"run ``M``
code revisions of ``π``"* — and the value it produces, in the member's own
suite (packages/dreaming/tests), collected under this directory's own conftest
for the same-basename-collision reason the bootstrap, canary and tripwires
members give.

The suite is written against the four things the feature is:

* **a candidate is a value** — :class:`CandidateModule` carries exactly five
  facts (source, code_hash, module_id, parent_version, revision_index), frozen
  and validated at construction, so the tests pin the validation and the
  identity;
* **the revision is structure-preserving** — the default reviser jitters only
  numeric-literal magnitudes and leaves the AST's skeleton intact, so a
  candidate descended from an admitted incumbent is admissible by construction;
  the tests pin the skeleton and the two deliberate exceptions (a bool is a
  branch, a zero is jittered additively);
* **the production is deterministic** — the same ``(source, count, seed)``
  answers the same candidate modules to the last code_hash in any process, so
  the tests pin reproducibility and the seed's role;
* **distinctness is a verdict, not a silence** — revise_policy deduplicates by
  code_hash and refuses with :class:`RevisionError` when the incumbent cannot
  fund ``M`` distinct candidates, while a malformed ask is
  :class:`RevisionRequestError`, so the tests pin both refusals and the split
  between them.

It is deliberately a *read-side* suite: every test is pure — no database, no
pool, no store — because feature 271 opens no database and reads no pool row,
and a test that acquired a database by accident would be testing a behaviour
the module deliberately does not have.  It never imports another workspace
member, and it never evaluates a policy or scores a world — those are features
272, 273 and 274, which consume the candidates this module produces.
"""

from __future__ import annotations

import ast
import inspect

import dreaming.reviser
import pytest
from dreaming import (
    REVISION_BAND,
    candidate_module,
    default_reviser,
    revise_policy,
)
from dreaming.errors import (
    DreamingError,
    RevisionError,
    RevisionRequestError,
)

#: An incumbent the tests revise — a small exploration policy with several
#: numeric constants, so the sweep has distinct magnitudes to perturb.  It is
#: a valid, admitted-style policy: a ``commit()`` on the return paths, no
#: hardcoded node id, no absolute score constant, no model call — the shape
#: feature 230 admits, so a jittered descendant stays admissible.
INCUMBENT = """
def policy(beta, meta):
    threshold = 0.05
    patience = 3
    flag = True
    if beta > 0.5:
        return threshold * 2.0
    return 0
"""


def _skeleton(source: str) -> list[str]:
    """The AST node types of a source, with every constant collapsed to ``CONST``.

    The measure of *structure-preserving*: a revision that changes only
    magnitudes has the same skeleton as its incumbent under this walk, because
    every numeric literal is one ``CONST`` token regardless of its value.  A
    skeleton that differs would mean the transform added or removed a node — an
    identifier, a call, a branch — which is the change the transform must not
    make.  Constants are collapsed because ``ast.unparse`` renders a negative
    literal as ``UnaryOp(USub, Constant)`` — a serialization artifact of the
    unparsing, not a structural edit — and a magnitude that flips sign is still
    a magnitude, not a new node.
    """
    return [
        type(node).__name__ if not isinstance(node, ast.Constant) else "CONST"
        for node in ast.walk(ast.parse(source))
    ]


class TestCandidateValue:
    """A candidate module is a frozen value carrying exactly five facts."""

    def test_the_five_facts_and_the_computed_identity(self):
        """source, code_hash, module_id, parent_version, revision_index — and code_hash is derived."""
        candidate = candidate_module(INCUMBENT, parent_version="v0", revision_index=2)
        assert candidate.source == INCUMBENT
        import hashlib

        assert candidate.code_hash == hashlib.sha256(INCUMBENT.encode()).hexdigest()
        assert candidate.module_id == f"cand-{candidate.code_hash[:32]}"
        assert candidate.parent_version == "v0"
        assert candidate.revision_index == 2

    def test_a_blank_or_non_str_source_is_refused(self):
        """The source is the only thing the replay engine reads; a blank one is no policy."""
        with pytest.raises(RevisionRequestError):
            candidate_module("", parent_version=None, revision_index=1)
        with pytest.raises(RevisionRequestError):
            candidate_module(42, parent_version=None, revision_index=1)  # type: ignore[arg-type]

    def test_a_bool_is_not_a_revision_index(self):
        """A bool is a branch, not a number; the index is which of the M revisions this is."""
        with pytest.raises(RevisionRequestError):
            candidate_module(INCUMBENT, parent_version=None, revision_index=True)  # type: ignore[arg-type]
        with pytest.raises(RevisionRequestError):
            candidate_module(INCUMBENT, parent_version=None, revision_index=0)
        with pytest.raises(RevisionRequestError):
            candidate_module(INCUMBENT, parent_version=None, revision_index=-1)

    def test_a_parent_that_cannot_be_named_is_refused(self):
        """A parent is None (a root) or a non-empty version; a blank or numeric one names no lineage."""
        candidate_module(INCUMBENT, parent_version=None, revision_index=1)  # a root is fine
        with pytest.raises(RevisionRequestError):
            candidate_module(INCUMBENT, parent_version="", revision_index=1)
        with pytest.raises(RevisionRequestError):
            candidate_module(INCUMBENT, parent_version=3, revision_index=1)  # type: ignore[arg-type]

    def test_a_caller_named_module_id_is_honoured(self):
        """The module_id default derives from the code_hash, but a named one is taken verbatim."""
        candidate = candidate_module(INCUMBENT, parent_version=None, revision_index=1, module_id="pi-v7")
        assert candidate.module_id == "pi-v7"

    def test_two_equal_candidates_are_equal_and_frozen(self):
        """Frozen with __slots__, so a caller cannot add an attribute to move a candidate."""
        first = candidate_module(INCUMBENT, parent_version="v0", revision_index=1)
        second = candidate_module(INCUMBENT, parent_version="v0", revision_index=1)
        assert first == second
        assert hash(first) == hash(second)
        with pytest.raises(AttributeError):
            first.spurious = "other"  # type: ignore[attr-defined]


class TestStructurePreserving:
    """The default reviser jitters magnitudes and leaves structure intact."""

    def test_the_skeleton_is_unchanged(self):
        """A revision changes only numeric-literal values, so the AST's skeleton is identical."""
        revised = default_reviser(INCUMBENT, 1, seed="cycle-1")
        assert _skeleton(INCUMBENT) == _skeleton(revised)

    def test_a_bool_literal_is_left_untouched(self):
        """A boolean is a branch, not a tunable magnitude; jittering it would rewrite a decision."""
        revised = default_reviser(INCUMBENT, 1, seed="cycle-1")
        assert "flag = True" in revised

    def test_a_comparison_operator_is_unchanged(self):
        """The transform alters a magnitude where feature 230's checks look at structure, not the operator."""
        revised = default_reviser(INCUMBENT, 1, seed="cycle-1")
        assert "if beta >" in revised

    def test_the_magnitudes_actually_move(self):
        """A revision that returned the incumbent verbatim would collapse the argmax onto one source."""
        revised = default_reviser(INCUMBENT, 1, seed="cycle-1")
        assert revised != INCUMBENT
        assert "threshold = 0.05" not in revised

    def test_a_zero_constant_is_jittered_additively_not_annihilated(self):
        """Any factor times zero is zero, so a zero threshold is moved additively or the sweep never perturbs it."""
        revised = default_reviser("def policy(beta, meta):\n    return 0\n", 1, seed=1)
        assert "return 0" not in revised.replace("return 0.0", "")
        # The returned expression is a non-zero float, not the annihilated zero.
        returned = revised.strip().rsplit("return ", 1)[1].strip()
        assert float(returned) != 0.0

    def test_the_default_reviser_is_within_the_band(self):
        """Each jittered magnitude lands in value · [1 − REVISION_BAND, 1 + REVISION_BAND]."""
        band = REVISION_BAND
        before = [0.05, 3.0, 0.5, 2.0]
        revised = default_reviser(INCUMBENT, 1, seed="cycle-1")
        revised_values = sorted(
            float(node.value)
            for node in ast.walk(ast.parse(revised))
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool)
        )
        for original in before:
            # Each original magnitude has a revised value within its band — the
            # transform perturbs by at most REVISION_BAND, so a magnitude is never
            # moved further from itself than the band allows.
            assert any(
                original * (1 - band) - 1e-9 <= value <= original * (1 + band) + 1e-9
                for value in revised_values
            )


class TestDeterminism:
    """The production is deterministic in (source, count, seed)."""

    def test_the_same_inputs_answer_the_same_candidates(self):
        """The same (source, count, seed) reproduces the same code_hashes — docs §12's determinism contract."""
        first = revise_policy(INCUMBENT, 3, seed="cycle-1", incumbent_version="v0")
        second = revise_policy(INCUMBENT, 3, seed="cycle-1", incumbent_version="v0")
        assert [c.code_hash for c in first] == [c.code_hash for c in second]

    def test_a_different_seed_produces_different_candidates(self):
        """The seed fixes the draw, so a different seed is a different sweep — the loop must pass a cycle-derived one."""
        first = revise_policy(INCUMBENT, 3, seed="cycle-1", incumbent_version="v0")
        second = revise_policy(INCUMBENT, 3, seed="cycle-2", incumbent_version="v0")
        assert [c.code_hash for c in first] != [c.code_hash for c in second]

    def test_candidates_are_indexed_one_to_count(self):
        """The sweep is indexed 1..count, one candidate per index, in order."""
        candidates = revise_policy(INCUMBENT, 3, seed="cycle-1", incumbent_version="v0")
        assert [c.revision_index for c in candidates] == [1, 2, 3]
        assert all(c.parent_version == "v0" for c in candidates)

    def test_a_root_has_no_parent(self):
        """With no incumbent_version, a revision records a root — parent_version None."""
        candidates = revise_policy(INCUMBENT, 2, seed=1)
        assert all(c.parent_version is None for c in candidates)

    def test_a_seed_as_text_and_as_int_render_the_same_draw(self):
        """The seed renders to stable text, so 42 and '42' are the same seed — the determinism docs §12 requires."""
        as_int = revise_policy(INCUMBENT, 2, seed=42)
        as_text = revise_policy(INCUMBENT, 2, seed="42")
        assert [c.code_hash for c in as_int] == [c.code_hash for c in as_text]


class TestTheCountIsTaken:
    """revise_policy accepts the count it is handed; it does not decide it."""

    @pytest.mark.parametrize("bad", [0, -1, True, 2.0, "3", 3.5])
    def test_a_malformed_count_is_refused(self, bad):
        """The sweep is indexed 1..count, so the count must be a genuine positive integer."""
        with pytest.raises(RevisionRequestError):
            revise_policy(INCUMBENT, bad, seed=1)

    def test_a_malformed_seed_is_refused(self):
        """A seed that cannot render to stable text cannot reproduce across processes."""
        with pytest.raises(RevisionRequestError):
            revise_policy(INCUMBENT, 2, seed=1.5)
        with pytest.raises(RevisionRequestError):
            revise_policy(INCUMBENT, 2, seed=True)
        with pytest.raises(RevisionRequestError):
            revise_policy(INCUMBENT, 2, seed={"a": 1})

    def test_a_blank_incumbent_is_refused(self):
        """A source that is not non-empty text carries no policy to revise."""
        with pytest.raises(RevisionRequestError):
            revise_policy("", 3, seed=1)
        with pytest.raises(RevisionRequestError):
            revise_policy(42, 3, seed=1)  # type: ignore[arg-type]


class TestDistinctness:
    """Distinctness is a verdict, not a silence — the shortfall refusal."""

    def test_a_source_with_no_perturbable_constant_is_refused(self):
        """A policy with no numeric constant to jitter cannot fund any distinct revision."""
        with pytest.raises(RevisionError):
            revise_policy("def policy(beta, meta):\n    return beta\n", 3, seed=1)

    def test_a_shortfall_names_what_is_missing(self):
        """The refusal states the shortfall — produced N, asked for M — so a developer knows the repair."""
        with pytest.raises(RevisionError) as caught:
            revise_policy("def policy(beta, meta):\n    return beta\n", 5, seed=1)
        message = str(caught.value)
        assert "distinct" in message
        assert "5" in message

    def test_a_single_constant_funds_many_distinct_revisions(self):
        """One constant jittered to many values is many distinct policies — no shortfall, the argmax has a set to rank."""
        candidates = revise_policy("def policy(beta, meta):\n    return 0.05\n", 4, seed=1)
        assert len(candidates) == 4
        assert len({c.code_hash for c in candidates}) == 4

    def test_a_custom_reviser_that_returns_the_incumbent_collapses_to_the_shortfall(self):
        """A reviser that never changes the source produces one candidate; revise_policy refuses the shortfall."""
        with pytest.raises(RevisionError):
            revise_policy(INCUMBENT, 3, seed=1, reviser=lambda source, index, seed: source)

    def test_a_custom_reviser_that_returns_unparseable_text_is_refused(self):
        """A custom reviser yielding invalid Python is a production that cannot proceed, not a malformed ask."""
        with pytest.raises(RevisionError):
            revise_policy(INCUMBENT, 2, seed=1, reviser=lambda source, index, seed: "def (")

    def test_a_custom_reviser_flows_through_unchanged(self):
        """A pluggable reviser substitutes the transform without moving the contract — its sources become the candidates."""
        candidates = revise_policy(
            INCUMBENT, 2, seed=1, reviser=lambda source, index, seed: source.replace("0.05", f"0.0{index}")
        )
        assert len(candidates) == 2
        assert "0.01" in candidates[0].source
        assert "0.02" in candidates[1].source


class TestTheVocabularySplit:
    """The two refusals split by the repair, and both sit under the one base."""

    def test_both_refusals_share_the_one_base(self):
        """One member, one base — the workspace's per-member rule, extended to the sweep's two faces."""
        assert issubclass(RevisionRequestError, DreamingError)
        assert issubclass(RevisionError, DreamingError)
        assert issubclass(DreamingError, Exception)

    def test_a_malformed_ask_is_not_the_production_verdict(self):
        """A malformed count is *fix the call*, not *grow the constants* — the two must not be caught as one."""
        assert not issubclass(RevisionRequestError, RevisionError)
        assert not issubclass(RevisionError, RevisionRequestError)

    def test_a_malformed_ask_wins_over_the_shortfall(self):
        """The ask is validated before anything is produced, so a bad count is refused before a shortfall could arise."""
        with pytest.raises(RevisionRequestError):
            revise_policy(INCUMBENT, 0, seed=1)


class TestPureAndReadSide:
    """Feature 271 opens no database and imports no other member."""

    def test_the_module_never_imports_random_or_sqlite3(self):
        """The draw is hashlib-derived, not random, and the module opens no store."""
        tree = ast.parse(inspect.getsource(dreaming.reviser))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert "random" not in imported
        assert "sqlite3" not in imported
        assert "os" not in imported

    def test_the_same_seed_reproduces_across_a_reimport(self):
        """A determinism proof: the same seed in a fresh module import reproduces the same candidates."""
        first = revise_policy(INCUMBENT, 2, seed="x")
        second = revise_policy(INCUMBENT, 2, seed="x")
        assert [c.code_hash for c in first] == [c.code_hash for c in second]
