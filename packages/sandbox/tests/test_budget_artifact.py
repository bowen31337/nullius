"""Feature 162: the committed artifact — the cgroup limits a run is checked against.

The step this file's subject makes checkable: *"exceeding the cgroup limits for
cpu, memory of 2048 MB or a process count of 32"* is only a refusable condition
if the deployment has a written-down statement of what *the limits* are.  The
committed document (:data:`~sandbox.COMMITTED_BUDGET_POLICY`) is that statement
— the three numbers §5.2's control row (``Resources | cgroup v2: cpu.max,
memory.max, pids.max``) is written from before anyone writes a stanza — and the
tests here read it the way an operator or a CI check would: compiled through the
same refusal as any change to it, holding exactly §5.2's ``cpu_s=30``,
``mem_mb=2048`` and ``pids=32``, and refusing to drift on disk exactly as it
refuses in memory, *whole document refused rather than the offending value
quietly applied*.

**Why this control ships a committed artifact.**  Features 165, 166 and 168
state their reason for having none — a value a run is handed, a format, a
vocabulary, none of them things a deployment could set differently.  This
feature's subject is three numbers a *kernel* is written from, which is the
strongest case for an artifact in the category: nothing about a cgroup limit is
auditable after the fact unless the number is in a file, and every stored breach
beside it dates a rejection to a budget.

**The one thing this artifact carries that is not a limit, and why.**  The file
also publishes ``runner_mem_mb``: the host runner's portable ``RLIMIT_AS``
fallback, which is *larger* than the cgroup's ``memory.max`` because jemalloc's
address-space *reservation* for the interpreter and polars exceeds two gigabytes
even at a modest resident set.  The two numbers are different facts about
different mechanisms, and the tests below pin both — a document that published
either in the other's place would be a reviewer reading a cgroup limit out of an
``RLIMIT_AS`` default, which is the drift this file's whole ``_comment`` block
argues against.

**What the artifact deliberately does not carry.**  ``wall_s`` is the same
``Limits(...)`` call's first field and belongs to feature 163's wall-clock law,
which ships its own artifact; ``network`` and ``filesystem`` are structural
denials inside feature 157's isolation.  The tests below pin those absences,
because the temptation to add "one more limit" to a file that already holds
three is exactly how one law's artifact becomes another law's second source of
truth.
"""

from __future__ import annotations

import json

import pytest
from _documents import (
    AT_CPU_S,
    AT_MEM_MB,
    AT_PIDS,
    CPU_S,
    MEASURED_FIELDS,
    MEM_MB,
    OVER_CPU_S,
    OVER_MEM_MB,
    OVER_PIDS,
    PIDS,
    RUNNER_MEM_DRIFT_MB,
    RUNNER_MEM_MB,
    WITHIN_CPU_S,
    WITHIN_MEM_MB,
    WITHIN_PIDS,
    budget_document,
    budget_run,
    committed_budget_document,
)
from sandbox import (
    BUDGET_POLICY_KIND,
    COMMITTED_BUDGET_POLICY,
    DEFAULT_CPU_S,
    DEFAULT_MEM_MB,
    DEFAULT_PIDS,
    CgroupBudgetDocumentError,
    SandboxBudgetError,
    check_cgroup_budget,
    classify_amount,
    classify_count,
    classify_seconds,
    committed_budget_policy,
    compile_budget_policy,
    load_budget_policy,
)

#: §5.2's call site, verbatim for the three fields this artifact owns.  Written
#: as data rather than read from :data:`sandbox.DEFAULT_CPU_S` &c. for the reason
#: the other suites give: a test that read the constants would follow a rename of
#: the numbers rather than catch one.
SECTION_5_2_CPU_S: float = 30.0
SECTION_5_2_MEM_MB: int = 2048
SECTION_5_2_PIDS: int = 32

#: The fields of the *same* ``Limits(...)`` call that are deliberately not in
#: this file — feature 163's and feature 157's subjects.  Named here so their
#: absence is a pinned fact rather than a coincidence.
FEATURE_163_FIELDS: tuple[str, ...] = ("wall_s",)
FEATURE_157_FIELDS: tuple[str, ...] = ("network", "filesystem")


class TestTheArtifact:
    """The document on disk, as facts rather than prose."""

    def test_the_artifact_exists_beside_the_module(self) -> None:
        """The committed budget ships with the law that checks against it, so a
        checkout cannot hold one without the other."""
        assert COMMITTED_BUDGET_POLICY.exists()

    def test_the_artifact_declares_its_kind(self) -> None:
        """It says what it is — the marker the compile holds it to, so a stray
        JSON file carrying a ``mem_mb`` key cannot be read as this policy."""
        with COMMITTED_BUDGET_POLICY.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
        assert document["policy"] == BUDGET_POLICY_KIND

    def test_the_artifact_declares_section_5_2s_three_limits(self) -> None:
        """The numbers the feature's own sentence names, read off the file rather
        than the compiled object, so the two readers are checked against each
        other across the seam the builder actually takes."""
        with COMMITTED_BUDGET_POLICY.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
        assert document["cpu_s"] == SECTION_5_2_CPU_S
        assert document["mem_mb"] == SECTION_5_2_MEM_MB
        assert document["pids"] == SECTION_5_2_PIDS

    def test_the_artifact_holds_those_three_and_not_a_fourth_limit(self) -> None:
        """The limits are pinned by *name* rather than by membership: a
        per-component table would be a knob nobody turns — §5.2 passes one
        ``Limits(...)`` to every box — so a fourth measured field arriving
        unnoticed fails here."""
        with COMMITTED_BUDGET_POLICY.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
        limits = [key for key in document if key in MEASURED_FIELDS]
        assert limits == list(MEASURED_FIELDS)

    def test_the_artifact_publishes_the_runners_address_space_fallback(self) -> None:
        """``runner_mem_mb`` is not a limit — it is what the host runner falls
        back to when a real cgroup is unavailable — and it is published *beside*
        the cgroup limit precisely so the two cannot be mistaken for each other.
        A document that dropped it would leave the next reviewer reconciling the
        two numbers from scratch."""
        with COMMITTED_BUDGET_POLICY.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
        assert document["runner_mem_mb"] == RUNNER_MEM_MB
        assert document["runner_mem_mb"] > document["mem_mb"]

    def test_the_artifacts_two_memory_numbers_differ_by_the_stated_drift(self) -> None:
        """The difference is the whole point of publishing both, so it is
        pinned as the value an operator sizing a budget would subtract rather
        than left as whatever two numbers happen to sit in the file."""
        with COMMITTED_BUDGET_POLICY.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
        assert document["runner_mem_mb"] - document["mem_mb"] == RUNNER_MEM_DRIFT_MB

    def test_the_artifact_leaves_the_wall_clock_to_feature_163(self) -> None:
        """``wall_s`` is the same call's first field and it belongs to feature
        163's wall-clock law, which ships its own artifact and pins this
        absence from its side too.  A file that grew it would be a second source
        of truth for another law's subject."""
        with COMMITTED_BUDGET_POLICY.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
        for field in FEATURE_163_FIELDS:
            assert field not in document, field

    def test_the_artifact_leaves_the_structural_denials_to_feature_157(self) -> None:
        """``network`` and ``filesystem`` are not budgets of a *count* at all —
        they are denials the isolation law owns — so a cgroup policy that grew
        one would be a limit no ``cgroup v2`` control can be written from."""
        with COMMITTED_BUDGET_POLICY.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
        for field in FEATURE_157_FIELDS:
            assert field not in document, field

    def test_the_artifact_carries_its_provenance(self) -> None:
        """Every committed document in this member has to be reviewable by a
        reader who has not read app_spec.xml: the ``_comment`` block is that
        reader's entry point, and a file stripped of it would leave "why 2048"
        answerable only by the person who wrote it."""
        with COMMITTED_BUDGET_POLICY.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
        comment = document["_comment"]
        assert isinstance(comment, list) and comment
        joined = "\n".join(comment)
        # The three citations the argument rests on, each named in the file:
        # §5.2's call site, the control table's own row, and the zone map the
        # limits serve.  A comment that lost one would leave the numbers
        # unexplained for the reader it exists for.
        assert "162" in joined
        assert "mem_mb=2048" in joined
        assert "cgroup v2" in joined

    def test_the_artifact_explains_why_the_two_memory_numbers_differ(self) -> None:
        """The one place a reader is most likely to conclude the file is
        inconsistent, so the file has to answer it: the ``RLIMIT_AS`` fallback
        is larger because of jemalloc's address-space reservation, and a comment
        that dropped that sentence would leave two numbers that *look* like a
        typo."""
        with COMMITTED_BUDGET_POLICY.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
        joined = "\n".join(document["_comment"])
        assert "runner_mem_mb" in joined
        assert "RLIMIT_AS" in joined


class TestTheCommittedBudget:
    """What the compiled artifact holds, and §5.2's stake in it."""

    def test_the_committed_budget_compiles_from_disk(self) -> None:
        """The loader's whole job, proven: read the committed file, refuse
        nothing about it, hand back a policy."""
        assert committed_budget_policy().kind == BUDGET_POLICY_KIND

    def test_the_committed_budget_is_section_5_2s_three_limits(self) -> None:
        """The feature's claim, read off the compiled object: this deployment
        confines untrusted code to §5.2's cpu, memory and process count."""
        policy = committed_budget_policy()
        assert policy.value("cpu_s") == SECTION_5_2_CPU_S == DEFAULT_CPU_S
        assert policy.value("mem_mb") == SECTION_5_2_MEM_MB == DEFAULT_MEM_MB
        assert policy.value("pids") == SECTION_5_2_PIDS == DEFAULT_PIDS

    def test_the_compiled_policy_holds_the_limits_in_the_artifacts_order(self) -> None:
        """The order is the document's, so two deployments' budget records can
        be compared field by field — and so a breach sentence lists the limits
        in the order a reviewer reads the file."""
        assert committed_budget_policy().fields() == MEASURED_FIELDS

    def test_the_compiled_policy_does_not_hold_the_runners_fallback_as_a_limit(
        self,
    ) -> None:
        """``runner_mem_mb`` is published in the file and is *not* a limit: it
        is what the host falls back to, not what a run is measured against.  A
        policy that carried it would reject every run the fallback permitted at
        2 GiB and none of the ones the cgroup permitted at 4 — a breach for
        every ordinary run."""
        policy = committed_budget_policy()
        assert policy.limit("runner_mem_mb") is None
        assert policy.value("runner_mem_mb") is None
        assert "runner_mem_mb" not in policy.fields()

    def test_the_committed_budget_exactly_covers_the_run_that_fits(self) -> None:
        """A budget is a claim in both directions: a run comfortably inside it
        is admitted (or the limits are too tight to be limits), and one past
        them is rejected (or the file is decoration).  Both through the
        committed policy, which is the object a dispatch actually consults."""
        policy = committed_budget_policy()
        inside = budget_run(cpu_s=WITHIN_CPU_S, mem_mb=WITHIN_MEM_MB, pids=WITHIN_PIDS)
        assert check_cgroup_budget(inside, policy).over_limits is False
        past = budget_run(cpu_s=OVER_CPU_S, mem_mb=OVER_MEM_MB, pids=OVER_PIDS)
        assert check_cgroup_budget(past, policy).over_limits is True

    def test_the_committed_budget_does_not_reject_at_its_exact_boundary(self) -> None:
        """*Exceeding* is strict, read through the committed artifact rather than
        through a hand-built policy: the boundary behaviour is the same on the
        path a deployment takes as it is in the law's own tests.  Every field is
        *at* its limit here, which is the reading that could reasonably have gone
        the other way."""
        at_the_line = budget_run(cpu_s=AT_CPU_S, mem_mb=AT_MEM_MB, pids=AT_PIDS)
        decision = check_cgroup_budget(at_the_line, committed_budget_policy())
        assert decision.over_limits is False
        assert decision.admitted is True

    def test_the_loader_and_the_committed_shortcut_agree(self) -> None:
        """``committed_budget_policy`` is not privileged: it goes through the
        same read-and-compile as any other path, so a drift in the file is
        refused on both."""
        assert (
            load_budget_policy(COMMITTED_BUDGET_POLICY).described()
            == committed_budget_policy().described()
        )

    def test_the_compiled_limits_are_numbers_a_cgroup_can_be_written_from(self) -> None:
        """The compiled values are what ``cpu.max``, ``memory.max`` and
        ``pids.max`` are written from, and the classifiers are what made them
        so — the document's ``30`` and the compiled ``30.0`` are the same
        measurement and only the second is comparable."""
        policy = committed_budget_policy()
        cpu = policy.limit("cpu_s")
        mem = policy.limit("mem_mb")
        pids = policy.limit("pids")
        assert cpu is not None and mem is not None and pids is not None
        assert cpu.value == classify_seconds(CPU_S)
        assert mem.value == classify_count(MEM_MB)
        assert pids.value == classify_count(PIDS)
        assert cpu.is_duration is True
        assert mem.is_duration is False

    def test_the_runners_fallback_is_the_number_the_compiler_checks(self) -> None:
        """The law's ``RUNNER_MEM_MB`` is the value the compiler holds the file's
        ``runner_mem_mb`` to, restated here as data for the reason every other
        restatement in this suite exists: the member imports no other workspace
        member, so the number the artifact publishes and the number the compiler
        compares against it are pinned equal here rather than shared by import.
        The drift is derived from the pair rather than written down a third
        time, so a test that means "the fallback is twice the limit" states the
        arithmetic the deployment's comment argues."""
        assert RUNNER_MEM_MB == RUNNER_MEM_DRIFT_MB + MEM_MB
        with COMMITTED_BUDGET_POLICY.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
        assert document["runner_mem_mb"] == RUNNER_MEM_MB


class TestTheArtifactIsRefusedWhole:
    """A drifted document is refused, and the *whole* of it is.

    Every test below compiles through :func:`load_budget_policy` from a file
    written to ``tmp_path`` — the path an operator's edit actually takes —
    rather than by calling the compiler directly, so the disk seam is exercised
    as well as the law.  The property under test throughout is that a refusal
    never half-applies: a policy that dropped the offending limit and compiled
    the rest would be a deployment whose file and whose cgroups disagree, which
    is untrusted code running at a number nobody wrote down arriving by another
    route.
    """

    def _write(self, tmp_path, document) -> object:
        path = tmp_path / "budget.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def test_a_cpu_budget_other_than_the_committed_one_is_refused(
        self, tmp_path
    ) -> None:
        """The headline drift: someone raises the cpu budget so a slow signal
        stops being rejected.  §5.2 fixes the number and the feature's sentence
        names it, so the file is refused rather than the new number quietly
        applied."""
        document = committed_budget_document()
        document["cpu_s"] = 120
        with pytest.raises(SandboxBudgetError) as raised:
            load_budget_policy(self._write(tmp_path, document))
        assert str(raised.value).startswith("cgroup_limits_required")
        assert "120" in str(raised.value)

    def test_a_memory_limit_other_than_the_committed_one_is_refused(
        self, tmp_path
    ) -> None:
        """The field the feature's sentence spells out loudest — "memory of 2048
        MB" — and the one an operator is most tempted to raise, since a signal
        that allocates a wide frame will be OOM-killed by it."""
        document = committed_budget_document()
        document["mem_mb"] = 8192
        with pytest.raises(SandboxBudgetError) as raised:
            load_budget_policy(self._write(tmp_path, document))
        assert "8192" in str(raised.value)

    def test_a_process_count_other_than_the_committed_one_is_refused(
        self, tmp_path
    ) -> None:
        """The third limit, and the one whose drift is quietest: a run that forks
        past §5.2's 32 does not fail loudly, it just makes the box's host slower
        for everything else on it."""
        document = committed_budget_document()
        document["pids"] = 256
        with pytest.raises(SandboxBudgetError):
            load_budget_policy(self._write(tmp_path, document))

    def test_a_limit_lowered_below_the_committed_one_is_refused_too(
        self, tmp_path
    ) -> None:
        """The other direction, and it is not the harmless one: a box tighter
        than §5.2's rejects candidates that would have finished, so every stored
        breach beside it is a rejection the deployment did not mean to make."""
        document = committed_budget_document()
        document["mem_mb"] = 256
        with pytest.raises(SandboxBudgetError):
            load_budget_policy(self._write(tmp_path, document))

    def test_a_limit_one_thousandth_off_is_refused(self, tmp_path) -> None:
        """The comparison is exact rather than approximate, so a drift that looks
        like floating-point noise at a glance fails here: "thirty" is a number in
        a file, not a tolerance."""
        document = committed_budget_document()
        document["cpu_s"] = SECTION_5_2_CPU_S + 0.001
        with pytest.raises(SandboxBudgetError):
            load_budget_policy(self._write(tmp_path, document))

    def test_a_drifted_runner_fallback_is_refused_too(self, tmp_path) -> None:
        """The field that is *not* a limit is still held to its own committed
        value, and this is why: a document that published the cgroup limit in
        the fallback's place would be a reviewer reading ``RLIMIT_AS`` out of
        ``memory.max`` — the exact confusion the two numbers are published
        together to prevent."""
        document = committed_budget_document()
        document["runner_mem_mb"] = MEM_MB
        with pytest.raises(SandboxBudgetError) as raised:
            load_budget_policy(self._write(tmp_path, document))
        assert "runner_mem_mb" in str(raised.value)

    def test_a_text_limit_is_refused_rather_than_parsed(self, tmp_path) -> None:
        """``"2048"`` reads naturally to a human and is not this document's
        grammar.  §5.2 passes numbers and the kernel is written from numbers; a
        parser here would be this member inventing a grammar no runtime reads."""
        document = committed_budget_document()
        document["mem_mb"] = "2048"
        with pytest.raises(CgroupBudgetDocumentError) as raised:
            load_budget_policy(self._write(tmp_path, document))
        assert "2048" in str(raised.value)

    def test_a_flag_limit_is_refused(self, tmp_path) -> None:
        """``true`` is an ``int`` to Python and is not a limit.  A budget
        admitted as a flag would be one no run could ever exceed — a cgroup that
        never fires while the file says it will."""
        document = committed_budget_document()
        document["mem_mb"] = True
        with pytest.raises(CgroupBudgetDocumentError):
            load_budget_policy(self._write(tmp_path, document))

    def test_a_fractional_process_count_is_refused(self, tmp_path) -> None:
        """No cgroup counter reports a fractional count, and truncating one here
        would be this law computing a number no kernel produced."""
        document = committed_budget_document()
        document["pids"] = 32.5
        with pytest.raises(CgroupBudgetDocumentError):
            load_budget_policy(self._write(tmp_path, document))

    def test_a_negative_limit_is_refused(self, tmp_path) -> None:
        """``-1`` is not a budget under any reading: a negative ``cpu.max``
        rejects every run at the instant it starts, and a negative ``pids.max``
        is a box that cannot fork at all — a deployment that refuses its own
        workload."""
        document = committed_budget_document()
        document["pids"] = -1
        with pytest.raises(CgroupBudgetDocumentError):
            load_budget_policy(self._write(tmp_path, document))

    def test_a_zero_limit_is_refused_as_a_value_not_as_a_shape(self, tmp_path) -> None:
        """``0`` is representable and meaningful — a ``memory.max`` of zero
        admits no allocation at all — so the classifier *admits* it and the
        refusal here is the value comparison rather than the shape check.  The
        distinction matters to a reader: zero is not a typo the classifier
        caught, it is a budget that is not §5.2's."""
        document = committed_budget_document()
        document["pids"] = 0
        with pytest.raises(SandboxBudgetError) as raised:
            load_budget_policy(self._write(tmp_path, document))
        assert str(raised.value).startswith("cgroup_limits_required")
        assert classify_count(0) == 0

    def test_an_absent_limit_is_refused_rather_than_defaulted(self, tmp_path) -> None:
        """The one inference the compiler must not make: reading a missing
        ``mem_mb`` as the default would be turning silence into the strongest
        promise the document makes.  'Unspecified' and 'confined to 2048 MB by
        law' are different promises and only the second is this feature's."""
        document = budget_document(omit=("mem_mb",))
        with pytest.raises(CgroupBudgetDocumentError) as raised:
            load_budget_policy(self._write(tmp_path, document))
        assert "mem_mb" in str(raised.value)

    def test_every_measured_field_is_refused_when_absent(self, tmp_path) -> None:
        """All three, one at a time, because a compiler that defaulted one field
        and refused the other two would pass a test that only checked one."""
        for field in MEASURED_FIELDS:
            document = budget_document(omit=(field,))
            with pytest.raises(CgroupBudgetDocumentError) as raised:
                load_budget_policy(self._write(tmp_path, document))
            assert field in str(raised.value), field

    def test_an_absent_runner_fallback_is_refused_rather_than_defaulted(
        self, tmp_path
    ) -> None:
        """The same reading for the published field: this deployment states its
        fallback beside its limit so the two cannot be confused, and a document
        that dropped one would leave the next reader inferring it."""
        document = budget_document(omit=("runner_mem_mb",))
        with pytest.raises(CgroupBudgetDocumentError) as raised:
            load_budget_policy(self._write(tmp_path, document))
        assert "runner_mem_mb" in str(raised.value)

    def test_a_foreign_marker_is_refused(self, tmp_path) -> None:
        """The document must say what it is.  A stray JSON file with a ``mem_mb``
        key — an unrelated deployment's config — is not this policy."""
        document = committed_budget_document()
        document["policy"] = "some-other-policy"
        with pytest.raises(CgroupBudgetDocumentError) as raised:
            load_budget_policy(self._write(tmp_path, document))
        assert BUDGET_POLICY_KIND in str(raised.value)

    def test_the_wall_clock_artifacts_marker_is_not_read_as_this_one(
        self, tmp_path
    ) -> None:
        """Feature 163's committed file is a real document this member ships, and
        it is *not* this policy despite being JSON beside it.  A compiler that
        matched markers loosely would read the wall-clock budget as a cgroup
        budget and find three limits missing."""
        document = committed_budget_document()
        document["policy"] = "sandbox-timeout"
        with pytest.raises(CgroupBudgetDocumentError):
            load_budget_policy(self._write(tmp_path, document))

    def test_a_marker_that_is_not_a_string_is_refused(self, tmp_path) -> None:
        """An unnamed policy holds nothing to any limit — 'unnamed' is not
        'cpu_s = 30' — so the marker is refused as a shape rather than compared
        as a string."""
        document = committed_budget_document()
        document["policy"] = 162
        with pytest.raises(CgroupBudgetDocumentError):
            load_budget_policy(self._write(tmp_path, document))

    def test_a_blank_marker_is_refused(self, tmp_path) -> None:
        """``"  "`` is present and says nothing, so it is refused on the same
        grounds a missing one is."""
        document = committed_budget_document()
        document["policy"] = "  "
        with pytest.raises(CgroupBudgetDocumentError):
            load_budget_policy(self._write(tmp_path, document))

    def test_a_document_that_is_not_a_mapping_is_refused(self, tmp_path) -> None:
        """A list or a string at the top level is a different document that
        happens to be JSON, and a compiler that guessed at its meaning would be
        writing policy rather than reading it."""
        path = tmp_path / "budget.json"
        path.write_text(json.dumps([2048]), encoding="utf-8")
        with pytest.raises(CgroupBudgetDocumentError):
            load_budget_policy(path)

    def test_an_unreadable_file_is_refused(self, tmp_path) -> None:
        """A budget that cannot be read is not one that confines nothing
        gracefully — it is one whose deployment has no resource law at all, so
        the caller is stopped rather than handed an empty policy."""
        with pytest.raises(CgroupBudgetDocumentError) as raised:
            load_budget_policy(tmp_path / "not-there.json")
        assert "could not read" in str(raised.value)

    def test_a_file_of_invalid_json_is_refused(self, tmp_path) -> None:
        """A truncated or hand-edited file reaches the same refusal as a
        well-formed drift: nothing is compiled from a document that cannot be
        parsed, rather than a partially-read one whose file and cgroups
        disagree."""
        path = tmp_path / "broken.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(CgroupBudgetDocumentError) as raised:
            load_budget_policy(path)
        assert "JSON" in str(raised.value)

    def test_a_drifted_document_yields_no_policy_at_all(self, tmp_path) -> None:
        """The property the whole class exists for, stated once as behaviour: a
        refusal means the caller holds *nothing*, not a policy carrying the
        fields that happened to be well-formed."""
        document = budget_document(cpu_s=90.0)
        with pytest.raises(SandboxBudgetError):
            load_budget_policy(self._write(tmp_path, document))

    def test_a_drifted_document_is_refused_in_memory_exactly_as_on_disk(self) -> None:
        """The disk seam is not the law: the same document refused by
        :func:`load_budget_policy` is refused by
        :func:`compile_budget_policy`, so an operator debugging a deployment does
        not have to wonder which of the two readers disagreed."""
        document = budget_document(pids=99)
        with pytest.raises(SandboxBudgetError):
            compile_budget_policy(document)


class TestTheCompilerIsNotWiderThanTheFile:
    """The committed artifact and the builder's reconstruction read one document.

    A suite that only ever compiled *hand-built* documents could pass while the
    committed file drifted somewhere the shape tests above do not look — an extra
    key, a different marker that still matches, a number that is the same to a
    rounded comparison.  These tests hold the two readers to each other over the
    file itself.
    """

    def test_the_files_document_compiles_through_the_law(self) -> None:
        """Read the file raw and compile *that*, rather than asking the module
        for its own compiled shortcut: the two must be the same document."""
        with COMMITTED_BUDGET_POLICY.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
        policy = compile_budget_policy(document)
        assert policy.described() == committed_budget_policy().described()

    def test_the_builder_reconstruction_compiles_to_the_files_policy(self) -> None:
        """The builder's spelling of the artifact is not a second source of
        truth: if it drifted, this compares a reconstruction against the file
        rather than a constant against itself."""
        assert (
            compile_budget_policy(committed_budget_document()).described()
            == committed_budget_policy().described()
        )

    def test_the_file_carries_no_key_the_law_does_not_read(self) -> None:
        """An extra key is how a knob nobody turns gets added: it survives
        review because the compile ignores it, and then a deployment starts
        reading it.  The compile refuses *nothing* on this ground — it is not its
        business — so the pin belongs here, where the file is the subject."""
        with COMMITTED_BUDGET_POLICY.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
        allowed = {"policy", "_comment", *MEASURED_FIELDS, "runner_mem_mb"}
        assert set(document) == allowed

    def test_every_measured_field_is_a_number_the_classifiers_accept(self) -> None:
        """The classifiers the *gate* reads a run's measurements with are the
        ones the compile reads the document with — one reading, two seams.  If
        the file carried a value the gate could not have produced, the two seams
        would have drifted apart."""
        with COMMITTED_BUDGET_POLICY.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
        for field in MEASURED_FIELDS:
            assert classify_amount(field, document[field]) == document[field], field
