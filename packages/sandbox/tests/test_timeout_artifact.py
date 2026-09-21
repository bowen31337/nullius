"""Feature 163: the committed artifact — the budget the kill is checked against.

The step this file's subject makes checkable: *"exceeded its 30 second wall
clock budget"* is only a refusable condition if the deployment has a
written-down statement of what *the budget* is.  The committed document
(:data:`~sandbox.COMMITTED_TIMEOUT_POLICY`) is that statement — the number a
watchdog hard-kills at before anyone writes a stanza — and the tests here read
it the way an operator or a CI check would: compiled through the same refusal
as any change to it, holding exactly §5.2's thirty, and refusing to drift on
disk exactly as it refuses in memory, *whole document refused rather than the
offending value quietly applied*.

**Why this control ships a committed artifact.**  Features 165 and 166 state
their reason for having none — the seed is a value a run is *handed* and the
payload channel is a format, a direction and an alignment, neither something a
deployment could set differently.  This feature's subject is a number, and a
number a watchdog kills at is such a configuration: it has to be written down
before it can be audited, and every stored ``fail_class=timeout`` beside it
dates a kill to a budget.  A budget that lived only in a constant would be one
nobody could review for drift.

**What the artifact deliberately does not carry.**  The other three fields of
the same ``Limits(...)`` call — ``cpu_s``, ``mem_mb``, ``pids`` — belong to
feature 162's cgroup law.  The tests below pin that absence, because the
temptation to add "one more limit" to a file that already holds a limit is
exactly how one law's artifact becomes another law's second source of truth.
"""

from __future__ import annotations

import json

import pytest
from _documents import (
    AT_BUDGET_S,
    OVERRUN_S,
    WALL_S,
    WITHIN_S,
    committed_timeout_document,
    timeout_document,
    timeout_run,
)
from sandbox import (
    COMMITTED_TIMEOUT_POLICY,
    DEFAULT_WALL_S,
    TIMEOUT_POLICY_KIND,
    SandboxTimeoutError,
    TimeoutBudgetDocumentError,
    classify_duration,
    committed_timeout_policy,
    compile_timeout_policy,
    kill_timeout,
    load_timeout_policy,
)

#: §5.2's call site, verbatim for the one field this artifact owns.  Written as
#: data rather than read from :data:`sandbox.DEFAULT_WALL_S` for the reason the
#: other suites give: a test that read the constant would follow a rename of the
#: number rather than catch one.
SECTION_5_2_WALL_S: float = 30.0

#: The three fields of the *same* ``Limits(...)`` call that are deliberately not
#: in this file — feature 162's cgroup law owns each.  Named here so their
#: absence is a pinned fact rather than a coincidence.
FEATURE_162_FIELDS: tuple[str, ...] = ("cpu_s", "mem_mb", "pids")


class TestTheArtifact:
    """The document on disk, as facts rather than prose."""

    def test_the_artifact_exists_beside_the_module(self) -> None:
        """The committed budget ships with the law that checks against it, so a
        checkout cannot hold one without the other."""
        assert COMMITTED_TIMEOUT_POLICY.exists()

    def test_the_artifact_declares_its_kind(self) -> None:
        """It says what it is — the marker the compile holds it to, so a stray
        JSON file carrying a ``wall_s`` key cannot be read as this policy."""
        with COMMITTED_TIMEOUT_POLICY.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
        assert document["policy"] == TIMEOUT_POLICY_KIND

    def test_the_artifact_declares_section_5_2s_budget(self) -> None:
        """The number the feature's own sentence names, read off the file rather
        than the compiled object, so the two readers are checked against each
        other across the seam the builder actually takes."""
        with COMMITTED_TIMEOUT_POLICY.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
        assert document["wall_s"] == SECTION_5_2_WALL_S

    def test_the_artifact_holds_that_number_and_not_a_second_one(self) -> None:
        """The budget is a *scalar* here, and pinned exactly rather than by
        membership: a per-component table would be a knob nobody turns — §5.2
        passes one ``Limits(...)`` to every box — so a second budget arriving
        unnoticed fails here."""
        with COMMITTED_TIMEOUT_POLICY.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
        budgets = [key for key in document if "s" == key[-1] or "wall" in key]
        assert budgets == ["wall_s"]

    def test_the_artifact_leaves_the_cgroup_fields_to_feature_162(self) -> None:
        """``cpu_s``, ``mem_mb`` and ``pids`` are the same call's other three
        fields and they belong to feature 162's cgroup law.  A file that grew one
        of them would be a second source of truth for another law's subject."""
        with COMMITTED_TIMEOUT_POLICY.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
        for field in FEATURE_162_FIELDS:
            assert field not in document, field

    def test_the_artifact_carries_its_provenance(self) -> None:
        """Every committed document in this member has to be reviewable by a
        reader who has not read app_spec.xml: the ``_comment`` block is that
        reader's entry point, and a file stripped of it would leave "why thirty"
        answerable only by the person who wrote it."""
        with COMMITTED_TIMEOUT_POLICY.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
        comment = document["_comment"]
        assert isinstance(comment, list) and comment
        joined = "\n".join(comment)
        # The three citations the argument rests on, each named in the file:
        # §5.2's call site, the control table's own row, and §8/§9.1's
        # vocabulary.  A comment that lost one would leave the number
        # unexplained for the reader it exists for.
        assert "163" in joined
        assert "wall_s=30" in joined
        assert "fail_class=timeout" in joined


class TestTheCommittedBudget:
    """What the compiled artifact holds, and §5.2's stake in it."""

    def test_the_committed_budget_compiles_from_disk(self) -> None:
        """The loader's whole job, proven: read the committed file, refuse
        nothing about it, hand back a policy."""
        assert committed_timeout_policy().kind == TIMEOUT_POLICY_KIND

    def test_the_committed_budget_is_section_5_2s_thirty(self) -> None:
        """The feature's claim, read off the compiled object: this deployment
        hard-kills a run that holds a core past thirty seconds."""
        policy = committed_timeout_policy()
        assert policy.wall_s == SECTION_5_2_WALL_S
        assert policy.wall_s == DEFAULT_WALL_S

    def test_the_committed_budget_exactly_covers_the_signal_that_fits(self) -> None:
        """A budget is a claim in both directions: a run comfortably inside it is
        admitted (or the budget is too tight to be a budget), and one past it is
        killed (or the file is decoration).  Both through the committed policy,
        which is the object a dispatch actually consults."""
        policy = committed_timeout_policy()
        assert kill_timeout(timeout_run(elapsed_s=WITHIN_S), policy).killed is False
        assert kill_timeout(timeout_run(elapsed_s=OVERRUN_S), policy).killed is True

    def test_the_committed_budget_does_not_kill_at_its_exact_boundary(self) -> None:
        """*Exceeded* is strict, read through the committed artifact rather than
        through a hand-built policy: the boundary behaviour is the same on the
        path a deployment takes as it is in the law's own tests."""
        decision = kill_timeout(timeout_run(elapsed_s=AT_BUDGET_S), committed_timeout_policy())
        assert decision.killed is False

    def test_the_loader_and_the_committed_shortcut_agree(self) -> None:
        """``committed_timeout_policy`` is not privileged: it goes through the
        same read-and-compile as any other path, so a drift in the file is
        refused on both."""
        assert (
            load_timeout_policy(COMMITTED_TIMEOUT_POLICY).wall_s
            == committed_timeout_policy().wall_s
        )

    def test_the_compiled_budget_is_a_float_a_watchdog_can_compare(self) -> None:
        """The compiled number is what a ``timeout=`` parameter takes, and the
        classifier is what made it one — the document's ``30`` and the compiled
        ``30.0`` are the same measurement and only the second is comparable."""
        policy = committed_timeout_policy()
        assert isinstance(policy.wall_s, float)
        assert policy.wall_s == classify_duration(WALL_S)


class TestTheArtifactIsRefusedWhole:
    """A drifted document is refused, and the *whole* of it is.

    Every test below compiles through :func:`load_timeout_policy` from a file
    written to ``tmp_path`` — the path an operator's edit actually takes —
    rather than by calling the compiler directly, so the disk seam is exercised
    as well as the law.  The property under test throughout is that a refusal
    never half-applies: a policy that dropped the offending value and compiled
    the rest would be a deployment whose file and whose watchdog disagree, which
    is a kill at a number nobody wrote down arriving by another route.
    """

    def _write(self, tmp_path, document) -> object:
        path = tmp_path / "timeout.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def test_a_budget_other_than_the_committed_one_is_refused(self, tmp_path) -> None:
        """The headline drift: someone raises the budget so a slow signal stops
        timing out.  §5.2 fixes the number and the feature's sentence names it,
        so the file is refused rather than the new number quietly applied."""
        document = committed_timeout_document()
        document["wall_s"] = 120
        with pytest.raises(SandboxTimeoutError) as raised:
            load_timeout_policy(self._write(tmp_path, document))
        assert str(raised.value).startswith("timeout")
        assert "120" in str(raised.value)

    def test_a_budget_lowered_below_the_committed_one_is_refused_too(self, tmp_path) -> None:
        """The other direction, and it is not the harmless one: a budget tighter
        than §5.2's kills signals that would have finished, so every stored
        timeout beside it is a kill the deployment did not mean to make."""
        document = committed_timeout_document()
        document["wall_s"] = 5
        with pytest.raises(SandboxTimeoutError):
            load_timeout_policy(self._write(tmp_path, document))

    def test_a_budget_one_thousandth_off_is_refused(self, tmp_path) -> None:
        """The comparison is exact rather than approximate, so a drift that
        looks like floating-point noise at a glance fails here: "thirty" is a
        number in a file, not a tolerance."""
        document = committed_timeout_document()
        document["wall_s"] = SECTION_5_2_WALL_S + 0.001
        with pytest.raises(SandboxTimeoutError):
            load_timeout_policy(self._write(tmp_path, document))

    def test_a_text_budget_is_refused_rather_than_parsed(self, tmp_path) -> None:
        """``"30s"`` reads naturally to a human and is not this document's
        grammar.  §5.2 passes a number and the watchdog compares a number; a
        parser here would be this member inventing a grammar no runner reads."""
        document = committed_timeout_document()
        document["wall_s"] = "30s"
        with pytest.raises(TimeoutBudgetDocumentError) as raised:
            load_timeout_policy(self._write(tmp_path, document))
        assert "30s" in str(raised.value)

    def test_a_flag_budget_is_refused(self, tmp_path) -> None:
        """``true`` is an ``int`` to Python and is not a number of seconds.  A
        budget admitted as a flag would be one no run could ever exceed — a
        watchdog that never fires while the file says it will."""
        document = committed_timeout_document()
        document["wall_s"] = True
        with pytest.raises(TimeoutBudgetDocumentError):
            load_timeout_policy(self._write(tmp_path, document))

    def test_a_negative_budget_is_refused(self, tmp_path) -> None:
        """A negative budget kills every run at the instant it starts, which is
        a deployment that refuses its own workload."""
        document = committed_timeout_document()
        document["wall_s"] = -30
        with pytest.raises(TimeoutBudgetDocumentError):
            load_timeout_policy(self._write(tmp_path, document))

    def test_a_zero_budget_is_refused(self, tmp_path) -> None:
        """``0`` is the tempting second drift and it is *not* a shape refusal —
        zero is a number of seconds, just not a budget any run fits inside, so
        it is refused as a value rather than as a type."""
        document = committed_timeout_document()
        document["wall_s"] = 0
        with pytest.raises(SandboxTimeoutError):
            load_timeout_policy(self._write(tmp_path, document))

    def test_an_absent_budget_is_refused_rather_than_defaulted(self, tmp_path) -> None:
        """The one inference the compiler must not make: reading a missing
        ``wall_s`` as the default would be turning silence into the strongest
        promise the document makes.  'Unspecified' and 'killed at thirty by law'
        are different promises and only the second is this feature's."""
        document = timeout_document(include_wall=False)
        with pytest.raises(TimeoutBudgetDocumentError) as raised:
            load_timeout_policy(self._write(tmp_path, document))
        assert "wall_s" in str(raised.value)

    def test_a_foreign_marker_is_refused(self, tmp_path) -> None:
        """The document must say what it is.  A stray JSON file with a
        ``wall_s`` key — an unrelated deployment's config — is not this policy."""
        document = committed_timeout_document()
        document["policy"] = "some-other-policy"
        with pytest.raises(TimeoutBudgetDocumentError) as raised:
            load_timeout_policy(self._write(tmp_path, document))
        assert TIMEOUT_POLICY_KIND in str(raised.value)

    def test_a_marker_that_is_not_a_string_is_refused(self, tmp_path) -> None:
        """An unnamed policy holds nothing to a budget — 'unnamed' is not
        'thirty seconds' — so the marker is refused as a shape rather than
        compared as a string."""
        document = committed_timeout_document()
        document["policy"] = 163
        with pytest.raises(TimeoutBudgetDocumentError):
            load_timeout_policy(self._write(tmp_path, document))

    def test_a_blank_marker_is_refused(self, tmp_path) -> None:
        """``"  "`` is present and says nothing, so it is refused on the same
        grounds a missing one is."""
        document = committed_timeout_document()
        document["policy"] = "  "
        with pytest.raises(TimeoutBudgetDocumentError):
            load_timeout_policy(self._write(tmp_path, document))

    def test_a_document_that_is_not_a_mapping_is_refused(self, tmp_path) -> None:
        """A list or a string at the top level is a different document that
        happens to be JSON, and a compiler that guessed at its meaning would be
        writing policy rather than reading it."""
        path = tmp_path / "timeout.json"
        path.write_text(json.dumps([30]), encoding="utf-8")
        with pytest.raises(TimeoutBudgetDocumentError):
            load_timeout_policy(path)

    def test_an_unreadable_file_is_refused(self, tmp_path) -> None:
        """A budget that cannot be read is not one that kills nothing gracefully
        — it is one whose deployment has no watchdog law at all, so the caller
        is stopped rather than handed an empty policy."""
        with pytest.raises(TimeoutBudgetDocumentError) as raised:
            load_timeout_policy(tmp_path / "not-there.json")
        assert "could not read" in str(raised.value)

    def test_a_file_of_invalid_json_is_refused(self, tmp_path) -> None:
        """A truncated or hand-edited file reaches the same refusal as a
        well-formed drift: nothing is compiled from a document that cannot be
        parsed, rather than a partially-read one whose file and watchdog
        disagree."""
        path = tmp_path / "broken.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(TimeoutBudgetDocumentError) as raised:
            load_timeout_policy(path)
        assert "JSON" in str(raised.value)

    def test_a_drifted_document_yields_no_policy_at_all(self, tmp_path) -> None:
        """The property the whole class exists for, stated once as behaviour: a
        refusal means the caller holds *nothing*, not a policy carrying the
        fields that happened to be well-formed."""
        document = timeout_document(wall_s=45.0)
        with pytest.raises(SandboxTimeoutError):
            load_timeout_policy(self._write(tmp_path, document))


class TestTheCompilerIsNotWiderThanTheFile:
    """The committed artifact and the builder's reconstruction read one document.

    A suite that only ever compiled *hand-built* documents could pass while the
    committed file drifted somewhere the shape tests above do not look — an
    extra key, a different marker that still matches, a number that is the same
    to a rounded comparison.  These tests hold the two readers to each other
    over the file itself.
    """

    def test_the_committed_file_and_its_reconstruction_compile_alike(self) -> None:
        """``committed_timeout_document`` is shaped after the file rather than
        read from it, so comparing the two compiled objects is a real check: it
        fails if the file gains a field or changes its budget."""
        from_file = committed_timeout_policy()
        rebuilt = compile_timeout_policy(committed_timeout_document())
        assert rebuilt.wall_s == from_file.wall_s
        assert rebuilt.kind == from_file.kind

    def test_the_reconstruction_carries_no_field_the_file_does_not(self) -> None:
        """The other half of the same check: a file that grew a key would leave
        the reconstruction *narrower* than the artifact, and only a direct read
        of the file would show it."""
        with COMMITTED_TIMEOUT_POLICY.open("r", encoding="utf-8") as handle:
            on_disk = json.load(handle)
        rebuilt = committed_timeout_document()
        assert {key for key in on_disk if not key.startswith("_")} == {
            key for key in rebuilt if not key.startswith("_")
        }
