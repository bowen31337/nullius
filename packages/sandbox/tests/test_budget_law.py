"""Feature 162: the cgroup-limits law — the rejection and the readings behind it.

The step this file's subject makes checkable: *"System rejects a sandboxed run
exceeding the cgroup limits for cpu, memory of 2048 MB or a process count of
32."*  Four claims, and the tests below take them in that order.

**The subject is a measurement of the machine, not a property of the code.**
Every other law in this category reads something a caller *declares* — which
isolation, which imports, which pins, which seed, which wall clock — while this
one reads what the box *consumed*: §5.2's control row is ``Resources | cgroup
v2: cpu.max, memory.max, pids.max``, and a cgroup counter is the only thing that
can answer it.  So nothing in this module opens a cgroup, reads a counter or
starts a probe: the three readings arrive on the run, exactly as feature 163's
elapsed time does, which is what lets this suite assert the law's behaviour
without depending on the machine that started pytest having a cgroup v2
hierarchy at all.

**The rejection is a value at the gate and a raise at the launcher.**  The
pipeline dispatches thousands of unattended candidates (§6.1 step 2), so
:func:`check_cgroup_budget` *answers* every run with a decision carrying the
per-limit overruns — a breach must reach an operator as a fact about a run, not
as a crashed evaluator.  A launcher on the last line after the spawn calls
:meth:`BudgetDecision.require`, which raises
:class:`~sandbox.errors.CgroupBudgetExceeded`.  A parameterised sweep across the
whole measurement space asserts the *absence* of an exception — the honest way
to test a law whose gate answers rather than raises — and the tests that expect a
raise call ``require`` by name.

**Why a breach raises here when feature 163's kill deliberately does not.**  The
two features split §5.2's one ``Limits(...)`` clause and they split the outcome
the same way: dying at the wall clock is an ordinary fate of a bad candidate
(recorded as ``fail_class=timeout``), while a run that held the core past its
budget, allocated past ``memory.max`` or forked past ``pids.max`` is a violation
of the *box* — §3's zone map makes the cgroup limits a property of Z1 — which is
something an operator has to look at.  A caller who reads feature 163's
three-outcome ``require`` and expects the same shape here will be surprised, and
that surprise is the feature, so the tests name it.

**The cross-member spellings are pinned as data rather than imported.**  The
member's one-provenance rule: the box agent-authored code is put inside must not
acquire a dependency on the member that drives it, so this module restates
``evaluator._sandbox``'s three defaults and feature 168's runner vocabulary —
and this suite is what makes each restatement safe.  A rename on the other side
of the seam fails here rather than producing a cgroup written from a number
nothing reads.
"""

from __future__ import annotations

import pytest
from _documents import (
    AT_CPU_S,
    AT_MEM_MB,
    AT_PIDS,
    BYTES_MEASUREMENT,
    CPU_FAIL_CLASS,
    FLAG_MEASUREMENT,
    FRACTIONAL_MEM_MB,
    MEASURED_FIELDS,
    MEMORY_FAIL_CLASS,
    NEGATIVE_PIDS,
    OVER_CPU_S,
    OVER_MEM_MB,
    OVER_PIDS,
    PIDS_FAIL_CLASS,
    TEXT_MEASUREMENT,
    WITHIN_CPU_S,
    WITHIN_MEM_MB,
    WITHIN_PIDS,
    budget_document,
    budget_run,
    committed_budget_document,
)
from sandbox import (
    BUDGET_COMPONENT_NAME,
    CGROUP_BUDGET_CODE,
    CGROUP_LIMITS_REQUIRED_CODE,
    DEFAULT_CPU_S,
    DEFAULT_MEM_MB,
    DEFAULT_PIDS,
    RUNNER_MEM_MB,
    BudgetBreach,
    BudgetOverrun,
    BudgetReason,
    BudgetRun,
    CgroupBudgetDocumentError,
    CgroupBudgetExceeded,
    CgroupLimit,
    CgroupPolicy,
    SandboxBudget,
    SandboxBudgetError,
    check_cgroup_budget,
    classify_amount,
    classify_count,
    classify_seconds,
    committed_budget_policy,
    compile_budget_policy,
    over_limits,
    sandbox_budget,
)
from sandbox import (
    MEASURED_FIELDS as LAW_MEASURED_FIELDS,
)
from sandbox import (
    MEMORY_FAIL_CLASS as LAW_MEMORY_FAIL_CLASS,
)

#: The policy every test in this file judges against — compiled from the
#: committed artifact, which is what a deployment actually holds.  A module
#: constant rather than a fixture because it is *immutable*: a compiled policy is
#: a tuple of frozen limits, so no test can drift it for another.  The suite's
#: fresh-object rule (see ``_documents``) exists for *mutable* documents and
#: explicitly does not apply to a frozen value.
POLICY: CgroupPolicy = committed_budget_policy()

#: Feature 162's sentence, verbatim — the three numbers the law is held to.
#: Spelled as data rather than read from :data:`sandbox.DEFAULT_CPU_S` &c. so a
#: rename of the numbers fails here rather than being followed, and so the
#: assertions below read as the feature's own claim.
SECTION_5_2_CPU_S: float = 30.0
SECTION_5_2_MEM_MB: int = 2048
SECTION_5_2_PIDS: int = 32


class TestTheFeatureSentence:
    """The four claims, as the numbers and words the feature states them in."""

    def test_the_three_limits_are_the_sentences_three(self) -> None:
        """*"the cgroup limits for cpu, memory of 2048 MB or a process count of
        32"* — each number spelled the way the sentence spells it."""
        assert DEFAULT_CPU_S == SECTION_5_2_CPU_S
        assert DEFAULT_MEM_MB == SECTION_5_2_MEM_MB
        assert DEFAULT_PIDS == SECTION_5_2_PIDS

    def test_the_three_fields_are_named_once_and_in_the_call_sites_order(self) -> None:
        """§5.2's call site writes ``cpu_s``, ``mem_mb``, ``pids`` in that order
        and so does every sweep in this law: a fourth field arriving without a
        unit or a classifier fails the compile rather than being ignored."""
        assert LAW_MEASURED_FIELDS == MEASURED_FIELDS == ("cpu_s", "mem_mb", "pids")

    def test_the_component_name_is_the_categorys_eighth(self) -> None:
        """Its own name, beside the seven already registered: the factory's
        registry replaces a name's earlier registration, so a second
        ``@register("sandbox")`` would silently delete feature 157's isolation
        law rather than widening it."""
        assert BUDGET_COMPONENT_NAME == "sandbox-budget"

    def test_the_codes_are_greppable(self) -> None:
        """One spelling per refusal, so an operator grepping a log finds the
        rejection by the feature's own words — the discipline every other law in
        this member follows."""
        assert CGROUP_BUDGET_CODE == "cgroup_budget_exceeded"
        assert CGROUP_LIMITS_REQUIRED_CODE == "cgroup_limits_required"

    def test_the_error_vocabulary_is_the_members_own(self) -> None:
        """One base per member, and this law's split follows every other's: the
        *run* refusal and the *document* refusal are siblings rather than one
        subclass of the other, because the repairs are on opposite sides of the
        seam."""
        from sandbox import SandboxError

        assert issubclass(CgroupBudgetExceeded, SandboxBudgetError)
        assert issubclass(CgroupBudgetDocumentError, SandboxBudgetError)
        assert issubclass(SandboxBudgetError, SandboxError)
        assert not issubclass(CgroupBudgetDocumentError, CgroupBudgetExceeded)


class TestTheGatesSubject:
    """What the law will and will not read a measurement off.

    The gate answers a *subject* rather than a typed argument, because the
    caller's own record type may describe a run this law should still be able to
    judge — the tolerance feature 163's and feature 164's gates extend to their
    own subjects, one law over.
    """

    def test_a_run_is_the_subject(self) -> None:
        """The value the law ships: three measurements and an identity."""
        run = budget_run(cpu_s=WITHIN_CPU_S)
        assert isinstance(run, BudgetRun)
        assert run.cpu_s == WITHIN_CPU_S
        assert run.measured("mem_mb") == WITHIN_MEM_MB

    def test_a_run_carrying_no_cpu_time_is_unreadable(self) -> None:
        """The one reading every run has: a cpu *duration* is always reported — a
        run that used no cpu used ``0.0`` seconds and there is nothing absent
        about it — so a subject carrying none is not a run this law can judge,
        and it is refused rather than rejected on a limit it cannot be measured
        against."""
        decision = check_cgroup_budget(object(), POLICY)
        assert decision.reason is BudgetReason.UNREADABLE_SUBJECT
        assert decision.refused is True
        assert decision.over_limits is False
        assert decision.breach is None
        assert str(decision.detail).startswith(CGROUP_LIMITS_REQUIRED_CODE)

    def test_a_bare_object_carrying_the_three_fields_is_readable(self) -> None:
        """Duck-typed on purpose: a caller's own record type is judged without
        being re-described, which is what lets a campaign driver hand its own run
        object to the gate."""

        class Own:
            cpu_s = OVER_CPU_S
            mem_mb = WITHIN_MEM_MB
            pids = WITHIN_PIDS
            node_id = "node-7"
            component = "own-signal"

        decision = check_cgroup_budget(Own(), POLICY)
        assert decision.reason is BudgetReason.OVER_LIMITS
        assert decision.breach is not None
        assert decision.breach.fields == ("cpu_s",)
        assert decision.breach.node_id == "node-7"
        assert decision.breach.component == "own-signal"

    def test_a_subject_with_a_non_string_identity_still_yields_a_sentence(self) -> None:
        """The identity is read while *building* a refusal, so a subject carrying
        a non-string one is reported as carrying none rather than crashing the
        sentence that was about to describe it."""

        class Odd:
            cpu_s = OVER_MEM_MB
            mem_mb = OVER_MEM_MB
            pids = WITHIN_PIDS
            node_id = 162
            component = object()

        decision = check_cgroup_budget(Odd(), POLICY)
        assert decision.over_limits is True
        assert decision.breach is not None
        assert decision.breach.node_id == ""
        assert decision.breach.component == ""

    def test_nothing_in_the_law_opens_a_cgroup(self) -> None:
        """The whole point of the subject arriving as an argument, asserted as
        behaviour: a run judged over the *committed* policy in a bare test
        process — no ``DATABASE_URL``, no lake, and quite possibly no cgroup v2
        mounts — reaches an answer rather than an ``OSError``.  A law that
        probed the hierarchy itself would make this suite's verdict depend on the
        machine that started pytest."""
        assert check_cgroup_budget(budget_run(cpu_s=1.0), POLICY).admitted is True


class TestTheComparison:
    """The strict boundary, and the three limits judged independently."""

    def test_a_run_inside_every_limit_is_admitted(self) -> None:
        """The common case: §6.1 step 2 dispatches thousands of these for every
        one that breaches."""
        decision = check_cgroup_budget(
            budget_run(cpu_s=WITHIN_CPU_S, mem_mb=WITHIN_MEM_MB, pids=WITHIN_PIDS),
            POLICY,
        )
        assert decision.reason is BudgetReason.WITHIN_LIMITS
        assert decision.admitted is True
        assert decision.over_limits is False
        assert decision.refused is False
        assert decision.breach is None

    def test_exceeding_is_strict_at_every_limit(self) -> None:
        """The feature's own word, and the one judgement in this law that could
        reasonably have gone the other way: a run that consumed *exactly* a limit
        did not exceed it.  All three fields are at their limit at once, so a
        comparison that rounded one of them up would fail here."""
        at_the_line = budget_run(cpu_s=AT_CPU_S, mem_mb=AT_MEM_MB, pids=AT_PIDS)
        assert check_cgroup_budget(at_the_line, POLICY).over_limits is False

    def test_one_second_past_the_cpu_budget_is_exceeding(self) -> None:
        """The other side of the same boundary, one unit over: a comparison that
        were tolerant by any amount would let this run through."""
        over = budget_run(cpu_s=AT_CPU_S + 1.0, mem_mb=AT_MEM_MB, pids=AT_PIDS)
        assert check_cgroup_budget(over, POLICY).over_limits is True

    def test_one_megabyte_past_the_memory_limit_is_exceeding(self) -> None:
        """Memory's own boundary, one megabyte over — the smallest drift an
        operator could make and still have made one."""
        over = budget_run(cpu_s=AT_CPU_S, mem_mb=AT_MEM_MB + 1, pids=AT_PIDS)
        assert check_cgroup_budget(over, POLICY).over_limits is True

    def test_one_process_past_the_count_is_exceeding(self) -> None:
        """The process table's own boundary: §5.2's limit is 32 and its own
        sentence says so, so the thirty-third process is where the box is no
        longer confined."""
        over = budget_run(cpu_s=AT_CPU_S, mem_mb=AT_MEM_MB, pids=AT_PIDS + 1)
        assert check_cgroup_budget(over, POLICY).over_limits is True

    @pytest.mark.parametrize("field", MEASURED_FIELDS)
    def test_each_limit_is_judged_on_its_own(self, field: str) -> None:
        """Three independent comparisons, one at a time: a gate that combined
        them — summed a ratio, took a maximum — would admit a run that
        catastrophically broke one limit while staying modest on the other two,
        which is exactly the exponential-forking case ``pids.max`` exists for."""
        measurements = {
            "cpu_s": WITHIN_CPU_S,
            "mem_mb": WITHIN_MEM_MB,
            "pids": WITHIN_PIDS,
        }
        breach = {"cpu_s": OVER_CPU_S, "mem_mb": OVER_MEM_MB, "pids": OVER_PIDS}[field]
        decision = check_cgroup_budget(
            budget_run(**{**measurements, field: breach}), POLICY
        )
        assert decision.over_limits is True
        assert decision.breach is not None
        assert decision.breach.fields == (field,)

    @pytest.mark.parametrize(
        "measurements",
        [
            {"cpu_s": WITHIN_CPU_S, "mem_mb": WITHIN_MEM_MB, "pids": WITHIN_PIDS},
            {"cpu_s": AT_CPU_S, "mem_mb": AT_MEM_MB, "pids": AT_PIDS},
            {"cpu_s": 0.0, "mem_mb": 0, "pids": 0},
            {"cpu_s": 1e-9, "mem_mb": 1, "pids": 1},
        ],
        ids=["inside", "at-the-line", "zero", "barely-started"],
    )
    def test_no_exception_is_raised_across_the_measurement_space(
        self, measurements: dict
    ) -> None:
        """The gate *answers*, and the absence of an exception is the assertion —
        the honest way to test a law that must not turn one breach into a crashed
        evaluation over thousands of unattended candidates.  A zero measurement
        is in this sweep on purpose: "used no cpu, allocated nothing, forked
        nothing" is inside every positive limit, not a malformed reading."""
        decision = check_cgroup_budget(budget_run(**measurements), POLICY)
        assert decision.admitted is True

    def test_a_run_breaking_two_limits_reports_both(self) -> None:
        """A breach is *plural*: a signal that allocated past ``memory.max`` and
        forked past ``pids.max`` broke two limits, and a record carrying only the
        first would leave an operator repairing the memory and re-running into
        the process table."""
        decision = check_cgroup_budget(
            budget_run(cpu_s=WITHIN_CPU_S, mem_mb=OVER_MEM_MB, pids=OVER_PIDS),
            POLICY,
        )
        assert decision.breach is not None
        assert decision.breach.fields == ("mem_mb", "pids")
        assert decision.breach.exceeded_memory is True
        assert decision.breach.exceeded_pids is True
        assert decision.breach.exceeded_cpu is False

    def test_a_run_breaking_every_limit_reports_all_three_in_policy_order(self) -> None:
        """The order is the *document's*, so two deployments' breach records can
        be compared field by field and a refusal lists the limits in the order a
        reviewer reads the artifact."""
        decision = check_cgroup_budget(
            budget_run(cpu_s=OVER_CPU_S, mem_mb=OVER_MEM_MB, pids=OVER_PIDS), POLICY
        )
        assert decision.breach is not None
        assert decision.breach.fields == MEASURED_FIELDS


class TestTheMalformedMeasurement:
    """A reading that is not a quantity is refused, never counted as inside.

    The sharpest judgement in this law, and it is the same one feature 163 makes
    about an unmeasurable elapsed time: *"'unmeasured' is not 'under the limit'"*.
    A run admitted on silence is one whose breach would never be recorded, which
    is the failure this whole feature exists to prevent.
    """

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("cpu_s", TEXT_MEASUREMENT),
            ("cpu_s", FLAG_MEASUREMENT),
            ("cpu_s", -1.0),
            ("mem_mb", TEXT_MEASUREMENT),
            ("mem_mb", BYTES_MEASUREMENT),
            ("mem_mb", FRACTIONAL_MEM_MB),
            ("mem_mb", -1),
            ("pids", FLAG_MEASUREMENT),
            ("pids", NEGATIVE_PIDS),
            ("pids", FRACTIONAL_MEM_MB),
        ],
        ids=[
            "cpu-text",
            "cpu-flag",
            "cpu-negative",
            "mem-text",
            "mem-bytes",
            "mem-fractional",
            "mem-negative",
            "pids-flag",
            "pids-negative",
            "pids-fractional",
        ],
    )
    def test_an_unusable_reading_is_refused_rather_than_admitted(
        self, field: str, value: object
    ) -> None:
        """Each malformed reading on its own axis, and each refused *rather than*
        rejected: the distinction matters because the repair is different — the
        caller has the right object and an unusable reading, so the operator
        looks at whatever published the counter rather than at the gate."""
        measurements = {
            "cpu_s": WITHIN_CPU_S,
            "mem_mb": WITHIN_MEM_MB,
            "pids": WITHIN_PIDS,
        }
        decision = check_cgroup_budget(
            budget_run(**{**measurements, field: value}), POLICY
        )
        assert decision.reason is BudgetReason.UNMEASURED
        assert decision.refused is True
        assert decision.over_limits is False
        assert decision.admitted is False
        assert field in str(decision.detail)

    def test_an_absent_reading_is_refused_rather_than_read_as_zero(self) -> None:
        """The one shape difference between this law's subject and feature 163's,
        and it is forced by the subject: a duration is always reported while a
        *peak* is only knowable if the runtime published one.  An unreadable
        ``memory.peak`` — an older kernel, a hierarchy mounted without the
        controller — is silence, and silence is not a comfortable zero."""
        decision = check_cgroup_budget(
            budget_run(cpu_s=WITHIN_CPU_S, mem_mb=None, pids=WITHIN_PIDS), POLICY
        )
        assert decision.reason is BudgetReason.UNMEASURED
        assert "mem_mb" in str(decision.detail)
        assert "unmeasured" in str(decision.detail).lower()

    @pytest.mark.parametrize("field", MEASURED_FIELDS)
    def test_every_measured_field_is_refused_when_absent(self, field: str) -> None:
        """All three, one at a time — a gate that refused one field's absence and
        read the other two as zero would pass a test that only checked one.

        The *reason* differs for ``cpu_s``, and that difference is the law rather
        than an inconsistency: a cpu duration is the one reading every run
        carries — a run that used no cpu used ``0.0`` seconds and there is
        nothing absent about it — so an object carrying none is not a run at all
        and earns ``UNREADABLE_SUBJECT``, while an absent memory peak or process
        count is a real run whose *counter* was never readable and earns
        ``UNMEASURED``.  Both are refusals; only the second is a run this law has
        the right subject for."""
        measurements = {
            "cpu_s": WITHIN_CPU_S,
            "mem_mb": WITHIN_MEM_MB,
            "pids": WITHIN_PIDS,
        }
        decision = check_cgroup_budget(
            budget_run(**{**measurements, field: None}), POLICY
        )
        expected = (
            BudgetReason.UNREADABLE_SUBJECT
            if field == "cpu_s"
            else BudgetReason.UNMEASURED
        )
        assert decision.reason is expected, field
        assert decision.refused is True
        assert decision.breach is None

    def test_an_unmeasured_run_is_not_a_breach(self) -> None:
        """The distinction the two refusal reasons exist for: a run nobody could
        measure must not be published as one that outran a limit, or the
        operator's first question — *which limit?* — would have no answer."""
        decision = check_cgroup_budget(budget_run(mem_mb=None), POLICY)
        assert decision.breach is None
        assert decision.over_limits is False
        assert decision.refused is True

    def test_the_unreadable_subject_is_told_apart_from_the_unusable_reading(
        self,
    ) -> None:
        """Two reasons, not one, because the repairs are on opposite sides of the
        seam: the first is a caller that handed over the wrong *object*, the
        second a caller whose run has a bad *reading*."""
        assert (
            check_cgroup_budget(object(), POLICY).reason
            is BudgetReason.UNREADABLE_SUBJECT
        )
        assert (
            check_cgroup_budget(budget_run(mem_mb="2048"), POLICY).reason
            is BudgetReason.UNMEASURED
        )

    def test_the_run_is_not_rejected_on_a_limit_it_cannot_be_measured_against(
        self,
    ) -> None:
        """The refusal's whole stance, asserted on a run that *is* past a limit
        on one axis and unmeasurable on another: the law reports the refusal
        rather than the breach, because a rejection it could not substantiate is
        worse than one it never made."""
        decision = check_cgroup_budget(
            budget_run(cpu_s=OVER_CPU_S, mem_mb=None, pids=OVER_PIDS), POLICY
        )
        assert decision.reason is BudgetReason.UNMEASURED
        assert decision.breach is None


class TestTheBreach:
    """The record a rejected run earns — the two halves of ``rejects`` as a value."""

    def _breach(self) -> BudgetBreach:
        decision = check_cgroup_budget(
            budget_run(
                cpu_s=WITHIN_CPU_S,
                mem_mb=OVER_MEM_MB,
                pids=OVER_PIDS,
                node_id="node-9",
                component="signal",
            ),
            POLICY,
        )
        assert decision.breach is not None
        return decision.breach

    def test_the_overrun_carries_both_numbers_and_the_excess(self) -> None:
        """The four values an operator sizes a budget from, computed once here
        rather than re-derived by each reader."""
        overrun = BudgetOverrun(
            field="mem_mb", limit=SECTION_5_2_MEM_MB, measured=OVER_MEM_MB, unit="MB"
        )
        assert overrun.excess == OVER_MEM_MB - SECTION_5_2_MEM_MB
        assert f"{SECTION_5_2_MEM_MB}" in overrun.describe()
        assert f"{OVER_MEM_MB}" in overrun.describe()

    def test_the_excess_is_strictly_positive_by_construction(self) -> None:
        """The gate builds an overrun only on a strict ``>``, so a record cannot
        claim a breach that never happened — the invariant feature 163's kill
        states for its own overrun.  A limit and a measurement that *are* equal
        never reach this type."""
        decision = check_cgroup_budget(budget_run(cpu_s=AT_CPU_S), POLICY)
        assert decision.admitted is True

    def test_a_breach_with_no_overrun_is_refused(self) -> None:
        """The one shape this object cannot survive being read back: ``fields``
        would be empty and *"this run was rejected"* would be indistinguishable
        from *"this run was measured and refused for no stated reason"* — a
        fabricated rejection, which is the failure the whole feature exists to
        prevent."""
        with pytest.raises(CgroupBudgetExceeded) as raised:
            BudgetBreach(overruns=(), detail="rejected")
        assert str(raised.value).startswith(CGROUP_BUDGET_CODE)

    def test_the_breach_reports_the_fields_it_broke(self) -> None:
        """The headline, as a tuple in the document's order."""
        assert self._breach().fields == ("mem_mb", "pids")

    def test_the_breach_reports_a_class_the_runner_would_have_recorded(self) -> None:
        """``fail_class`` is the runner's spelling for the *worst* thing that
        happened, in the order a kernel would have acted: cpu exhaustion is
        throttled into a ``timeout``, an allocation past ``memory.max`` is
        OOM-killed, and a ``fork`` past ``pids.max`` fails outright as a
        ``crash``."""
        from sandbox.budget import _breach_fail_class

        cpu_only = BudgetOverrun(
            field="cpu_s", limit=SECTION_5_2_CPU_S, measured=OVER_CPU_S, unit="s"
        )
        mem_only = BudgetOverrun(
            field="mem_mb", limit=SECTION_5_2_MEM_MB, measured=OVER_MEM_MB, unit="MB"
        )
        pids_only = BudgetOverrun(
            field="pids", limit=SECTION_5_2_PIDS, measured=OVER_PIDS, unit="pids"
        )
        assert _breach_fail_class([cpu_only]) == CPU_FAIL_CLASS
        assert _breach_fail_class([mem_only]) == MEMORY_FAIL_CLASS
        assert _breach_fail_class([pids_only]) == PIDS_FAIL_CLASS
        # Cpu wins over memory, memory over pids: the order a kernel acts in.
        assert _breach_fail_class([pids_only, mem_only, cpu_only]) == CPU_FAIL_CLASS
        assert _breach_fail_class([pids_only, mem_only]) == MEMORY_FAIL_CLASS

    def test_the_memory_class_is_the_one_the_law_declares(self) -> None:
        """Restated as data for the member's one-provenance reason, and pinned
        against the runner's own vocabulary in the cross-member test below."""
        assert LAW_MEMORY_FAIL_CLASS == MEMORY_FAIL_CLASS == "oom"

    def test_the_store_rows_are_one_per_broken_limit(self) -> None:
        """A list rather than one mapping, because a breach *is* plural: a store
        that flattened two overruns into one row would lose the second reading."""
        rows = self._breach().rows()
        assert [row["limit_field"] for row in rows] == ["mem_mb", "pids"]
        assert rows[0]["limit_value"] == SECTION_5_2_MEM_MB
        assert rows[0]["measured"] == OVER_MEM_MB
        assert rows[0]["excess"] == OVER_MEM_MB - SECTION_5_2_MEM_MB
        assert rows[0]["unit"] == "MB"

    def test_the_store_rows_carry_the_identity_when_the_run_had_one(self) -> None:
        """The node and component travel with the breach, so *which node was
        rejected?* is answerable from the record rather than from a log line that
        has since rotated."""
        rows = self._breach().rows()
        assert all(row["node_id"] == "node-9" for row in rows)
        assert all(row["component"] == "signal" for row in rows)

    def test_the_summary_row_publishes_the_runners_own_class_name(self) -> None:
        """The counting shape, beside the per-limit one: the runner's class
        travels under the runner's own field name (``fail_class``) because that
        is what the box reported — feature 168 is the law that places it in
        §9.1's column, and a second translation here would be a second spelling
        of its table."""
        row = self._breach().row()
        assert row["fail_class"] == MEMORY_FAIL_CLASS
        assert set(row["over_limits"]) == {"mem_mb", "pids"}
        assert row["measured"]["mem_mb"] == OVER_MEM_MB
        assert row["limits"]["mem_mb"] == SECTION_5_2_MEM_MB

    def test_the_rows_are_fresh_objects_each_call(self) -> None:
        """The copy-then-hand discipline every other law's store shape applies: a
        caller that mutates a row it was handed must not be mutating the breach's
        own state for the next reader."""
        breach = self._breach()
        first = breach.rows()
        first[0]["limit_value"] = 1
        assert breach.rows()[0]["limit_value"] == SECTION_5_2_MEM_MB
        assert breach.row() is not breach.row()

    def test_the_breach_sentence_names_every_reading_and_both_citations(self) -> None:
        """The message an operator ends up reading has to carry the listing —
        every broken limit with both numbers beside it — *and* say which clause
        of §5.2 it comes from, or a rejection arrives with no evidence and no
        rule."""
        detail = self._breach().detail
        assert detail.startswith(CGROUP_BUDGET_CODE)
        assert "mem_mb" in detail and "pids" in detail
        assert str(OVER_MEM_MB) in detail
        assert "cgroup v2" in detail


class TestTheRefusalAtTheLauncher:
    """``require`` — the one place the law raises, and what it distinguishes."""

    def test_an_admitted_run_passes_through(self) -> None:
        """The verb is usable unconditionally as the last line before a fork: a
        run inside every limit is a no-op.  Unlike feature 163's ``require``
        there is *no value* returned for the pass-through — there is no kill to
        hand back, because a confined run leaves no record to persist."""
        decision = check_cgroup_budget(budget_run(cpu_s=WITHIN_CPU_S), POLICY)
        assert decision.require() is None

    def test_a_breach_raises_the_breachs_own_sentence(self) -> None:
        """The message a launcher ends up reading is the *breach's*, not the
        decision's one-line summary: a caller that raises has nothing else to
        print, so the listing of every broken limit with both numbers has to be
        in the exception."""
        decision = check_cgroup_budget(
            budget_run(cpu_s=WITHIN_CPU_S, mem_mb=OVER_MEM_MB, pids=OVER_PIDS), POLICY
        )
        with pytest.raises(CgroupBudgetExceeded) as raised:
            decision.require()
        assert str(raised.value).startswith(CGROUP_BUDGET_CODE)
        assert "mem_mb" in str(raised.value)
        assert "pids" in str(raised.value)
        assert str(OVER_MEM_MB) in str(raised.value)

    def test_an_unmeasured_run_raises_the_refusal(self) -> None:
        """The other half of the feature's two refusals, and the same error type:
        a caller never has to catch two, the division feature 157's decision
        draws for its own pair."""
        decision = check_cgroup_budget(budget_run(mem_mb=None), POLICY)
        with pytest.raises(CgroupBudgetExceeded) as raised:
            decision.require()
        assert str(raised.value).startswith(CGROUP_LIMITS_REQUIRED_CODE)

    def test_the_unreadable_subject_raises_too(self) -> None:
        """A caller that has been handed the wrong object still has to be told,
        and it is told with the same class — the gate's answer and the launcher's
        exception are one vocabulary rather than two."""
        with pytest.raises(CgroupBudgetExceeded):
            check_cgroup_budget(object(), POLICY).require()

    def test_the_refusal_is_catchable_as_the_members_base(self) -> None:
        """One ``except`` for the whole sandbox path: a caller catching the
        member's base does not have to enumerate this law's two spellings."""
        from sandbox import SandboxError

        with pytest.raises(SandboxError):
            check_cgroup_budget(budget_run(cpu_s=OVER_CPU_S), POLICY).require()

    def test_a_rejected_run_is_not_refused(self) -> None:
        """``refused`` means *the law could not judge this run*, which is a
        different fact from *the law judged it and rejected it*.  A caller that
        read a bare falsy as "the run was fine" would treat an unmeasurable run
        as an admitted one — which is why ``refused`` is its own property."""
        rejected = check_cgroup_budget(budget_run(cpu_s=OVER_CPU_S), POLICY)
        assert rejected.refused is False
        assert rejected.admitted is False
        assert rejected.over_limits is True


class TestTheBoolean:
    """``over_limits`` — the headline, and what it deliberately does not say."""

    def test_it_answers_the_arithmetic_question(self) -> None:
        assert over_limits(budget_run(cpu_s=OVER_CPU_S), POLICY) is True
        assert over_limits(budget_run(cpu_s=WITHIN_CPU_S), POLICY) is False

    def test_an_unmeasurable_run_is_false_here_and_the_caller_must_look_deeper(
        self,
    ) -> None:
        """The caveat feature 163's ``killed`` states for its own boolean: a
        caller branching on this alone has asked only the arithmetic question, so
        the caller that *must* hear about an unmeasurable run calls
        :func:`check_cgroup_budget` and reads the reason."""
        assert over_limits(budget_run(mem_mb=None), POLICY) is False
        assert check_cgroup_budget(budget_run(mem_mb=None), POLICY).refused is True
        assert over_limits(object(), POLICY) is False

    def test_it_never_raises(self) -> None:
        """The convenience's contract: it is the one verb that cannot raise, so a
        caller can use it in a comprehension over a batch of runs without a
        try/except — the same stance feature 164's ``check`` takes."""
        for subject in (
            object(),
            budget_run(mem_mb="2048"),
            budget_run(cpu_s=OVER_CPU_S),
        ):
            assert over_limits(subject, POLICY) in (True, False)


class TestThePolicy:
    """The compiled budget — what the deployment confines untrusted code to."""

    def test_the_policy_declares_its_three_limits_in_order(self) -> None:
        assert POLICY.fields() == MEASURED_FIELDS
        assert POLICY.kind == "sandbox-cgroup-limits"

    def test_each_limit_knows_its_unit_and_whether_it_is_a_duration(self) -> None:
        """The unit is what makes a breach sentence readable — ``cpu_s = 30s``
        rather than ``cpu_s = 30`` — and ``is_duration`` is what tells a reader
        that one of the three is measured on a different axis."""
        cpu = POLICY.limit("cpu_s")
        mem = POLICY.limit("mem_mb")
        pids = POLICY.limit("pids")
        assert cpu is not None and mem is not None and pids is not None
        assert (cpu.unit, mem.unit, pids.unit) == ("s", "MB", "pids")
        assert cpu.is_duration is True
        assert mem.is_duration is False and pids.is_duration is False

    def test_the_policy_describes_itself_for_a_runbook(self) -> None:
        """The read side a CI check or a runbook quotes, so a deployment
        describing its own posture transcribes the compiled artifact rather than
        re-typing three numbers beside three unit words."""
        assert POLICY.described() == (
            f"cpu_s = {SECTION_5_2_CPU_S:g}s",
            f"mem_mb = {SECTION_5_2_MEM_MB}MB",
            f"pids = {SECTION_5_2_PIDS}pids",
        )

    def test_an_unlisted_field_is_answered_by_being_outside_the_sweep(self) -> None:
        """``limit`` decides nothing: a field the policy does not carry is
        answered by the *gate* by not being in the set it sweeps.  The published
        runner fallback is the live example — it is in the artifact and is
        deliberately not a limit."""
        assert POLICY.limit("runner_mem_mb") is None
        assert POLICY.value("runner_mem_mb") is None
        assert RUNNER_MEM_MB not in POLICY.fields()

    def test_the_gate_judges_against_the_policys_own_numbers(self) -> None:
        """A hand-assembled policy carrying other limits rejects at *those*
        numbers and says so — the audit finding rather than a bug, and the reason
        the gate compares against the compiled declaration rather than a module
        constant."""
        narrow = CgroupPolicy(
            kind="hand-built",
            limits=(CgroupLimit(field="cpu_s", value=1.0, unit="s"),),
        )
        decision = check_cgroup_budget(budget_run(cpu_s=2.0), narrow)
        assert decision.over_limits is True
        assert decision.breach is not None
        assert decision.breach.overruns[0].limit == 1.0


class TestTheClassifiers:
    """The one reading of "a number of seconds" and "a whole count".

    The document and the run are read by the *same* pair of classifiers, so the
    two seams cannot disagree about what a measurement is — the member's
    one-provenance rule applied to a type check.
    """

    def test_a_seconds_reading_is_a_number(self) -> None:
        assert classify_seconds(SECTION_5_2_CPU_S) == SECTION_5_2_CPU_S
        assert classify_seconds(0) == 0.0
        assert classify_seconds(1e-9) == 1e-9

    @pytest.mark.parametrize(
        "value",
        [None, "30", b"30", True, False, -1, float("nan"), float("inf"), [30], (30,)],
        ids=[
            "none",
            "text",
            "bytes",
            "true",
            "false",
            "negative",
            "nan",
            "infinite",
            "list",
            "tuple",
        ],
    )
    def test_a_non_duration_is_refused(self, value: object) -> None:
        """Every shape a JSON document, an environment variable or a §9.1 column
        could hand one over as, refused by name rather than coerced.  ``NaN`` and
        infinity are in the sweep because they compare *false* against every
        limit: a run carrying one would be admitted by the arithmetic and is the
        quietest possible way to pass a gate that was supposed to confine it."""
        assert classify_seconds(value) is None

    def test_a_whole_count_is_a_whole_count(self) -> None:
        assert classify_count(SECTION_5_2_MEM_MB) == SECTION_5_2_MEM_MB
        assert classify_count(2048.0) == 2048
        assert classify_count(0) == 0

    @pytest.mark.parametrize(
        "value",
        [None, "2048", b"2048", True, False, -1, 2048.5, float("nan"), float("inf")],
        ids=[
            "none",
            "text",
            "bytes",
            "true",
            "false",
            "negative",
            "fractional",
            "nan",
            "infinite",
        ],
    )
    def test_a_non_count_is_refused(self, value: object) -> None:
        """No cgroup counter reports a fractional or infinite count, and a
        ``True`` is an ``int`` in Python and deliberately not a limit: no cgroup
        is written from a flag."""
        assert classify_count(value) is None

    def test_the_document_and_the_run_are_read_by_the_same_pair(self) -> None:
        """One reading, two seams: the classifier the compile reads a document's
        limit with is the one the gate reads a run's measurement with, so a value
        the file could hold and the gate could not produce is impossible."""
        for field in MEASURED_FIELDS:
            assert classify_amount(field, 1) == 1, field
            assert classify_amount(field, "1") is None, field
        assert classify_amount("wall_s", 30) is None

    def test_an_unknown_field_has_no_reading(self) -> None:
        """A field this law does not own — feature 163's wall clock, feature
        157's denials — has no classifier here at all, so the compile cannot
        quietly widen to a fourth limit."""
        assert classify_amount("wall_s", 30) is None
        assert classify_amount("network", False) is None

    def test_the_document_pins_the_two_classifiers_to_the_constants(self) -> None:
        """The compile reads the committed artifact through the *classifiers*;
        the constants are what it compares the result against.  Both are stated
        here so a reader sees the two readers agree on §5.2's numbers."""
        document = committed_budget_document()
        assert classify_seconds(document["cpu_s"]) == DEFAULT_CPU_S
        assert classify_count(document["mem_mb"]) == DEFAULT_MEM_MB
        assert classify_count(document["pids"]) == DEFAULT_PIDS


class TestTheFaçade:
    """The value a composed application carries."""

    def test_the_module_constructor_compiles_the_committed_artifact(self) -> None:
        """Not a component and not registered: a component whose builder *ran*
        the law would have nothing to run it *on*, since the law needs a run's
        measurements to answer for."""
        budget = sandbox_budget()
        assert isinstance(budget, SandboxBudget)
        assert budget.policy.described() == POLICY.described()

    def test_the_read_side_is_the_three_limits(self) -> None:
        """A deployment auditing what untrusted code may consume reads them off
        the component rather than re-deriving them from the file."""
        budget = sandbox_budget()
        assert budget.cpu_s == SECTION_5_2_CPU_S
        assert budget.mem_mb == SECTION_5_2_MEM_MB
        assert budget.pids == SECTION_5_2_PIDS
        assert budget.described() == POLICY.described()
        assert budget.limits() == POLICY.limits()

    def test_the_facade_carries_no_cgroup_and_no_probe(self) -> None:
        """A component shared across runs that opened a hierarchy — or installed
        a probe when it was built — would be reading counters that belong to a
        single run, so two dispatches would share a box and the second would be
        rejected for the first's consumption.  Asserted as behaviour: the facade
        holds exactly one attribute, and it is the policy."""
        budget = sandbox_budget()
        assert SandboxBudget.__slots__ == ("_policy",)
        assert not hasattr(budget, "cpu_stat")
        assert not hasattr(budget, "memory_peak")

    def test_the_facade_verbs_reach_the_one_gate(self) -> None:
        """The delegation is deliberately thin, because a second implementation
        of the comparison or the breach sentence would be a second thing to keep
        in sync."""
        budget = sandbox_budget()
        over = budget_run(cpu_s=OVER_CPU_S)
        assert budget.over_limits(over) is True
        assert budget.check(over).over_limits is True
        assert budget.check(budget_run(cpu_s=WITHIN_CPU_S)).admitted is True
        with pytest.raises(CgroupBudgetExceeded):
            budget.require(over)
        assert budget.require(budget_run(cpu_s=WITHIN_CPU_S)) is None

    def test_the_facade_compiles_nothing_at_call_time(self) -> None:
        """Two instances of the same committed policy describe the same
        deployment: a facade that re-read the file per call would make a drifted
        artifact fail on a dispatch rather than at composition."""
        assert sandbox_budget().described() == sandbox_budget().described()


class TestTheCrossMemberPins:
    """The restatements made safe, one seam at a time.

    The member's one-provenance rule: the sandbox member imports no other
    workspace member — the box agent-authored code is put inside must not acquire
    a dependency on the member that drives it — so §5.2's three numbers and the
    runner's vocabulary are restated here *as data*.  This class is what makes
    each restatement safe: a rename on the other side of the seam fails here
    rather than producing a ``cpu.max`` written from a number nothing reads.
    """

    def test_the_cpu_budget_is_the_evaluators_own(self) -> None:
        """The import is in-function so a missing evaluator degrades this test
        rather than collection, the discipline every cross-member test in this
        member follows."""
        from evaluator._sandbox import DEFAULT_CPU_S as RUNNER_CPU_S

        assert DEFAULT_CPU_S == RUNNER_CPU_S == SECTION_5_2_CPU_S

    def test_the_pids_limit_is_the_evaluators_own(self) -> None:
        """§5.2's 32, restated on the runner's side too — the number is the same
        on both sides of the seam and a drift in either fails here."""
        from evaluator._sandbox import DEFAULT_PIDS as RUNNER_PIDS

        assert DEFAULT_PIDS == RUNNER_PIDS == SECTION_5_2_PIDS

    def test_the_memory_difference_is_the_evaluators_stated_reason(self) -> None:
        """The one place the two features' numbers *deliberately* disagree, and
        it is the evaluator's own documented judgement: its portable
        ``RLIMIT_AS`` fallback is larger than §5.2's cgroup limit because
        jemalloc's address-space reservation for the interpreter and polars
        exceeds 2 GiB even at a modest resident set.  The law's published
        ``runner_mem_mb`` is that fallback; its enforced limit is §5.2's 2048.

        A rename or a change on either side of this seam fails here — which is
        exactly the pair of numbers an operator is most likely to "reconcile"
        by editing one of them."""
        from evaluator._sandbox import DEFAULT_MEM_MB as RUNNER_MEM_MB_EVALUATOR

        assert RUNNER_MEM_MB == RUNNER_MEM_MB_EVALUATOR != DEFAULT_MEM_MB
        assert DEFAULT_MEM_MB == SECTION_5_2_MEM_MB == 2048
        assert RUNNER_MEM_MB_EVALUATOR == 4096

    def test_the_memory_class_is_one_of_the_runners_six(self) -> None:
        """``oom`` is the runner's spelling, not §9.1's: feature 168 owns the
        four-word column and its table is what places this class under ``error``.
        This law names the class the box *reported* rather than translating it,
        because a second translation would be a second spelling of that table."""
        from sandbox import SANDBOX_RUNNER_CLASSES

        assert MEMORY_FAIL_CLASS in SANDBOX_RUNNER_CLASSES

    def test_the_evaluators_vocabulary_agrees(self) -> None:
        """The same restatement read from the other side: the runner's six
        classes, as the debit module declares them."""
        from evaluator._debit import _SANDBOX_FAIL_CLASSES

        assert MEMORY_FAIL_CLASS in tuple(_SANDBOX_FAIL_CLASSES)

    def test_the_breachs_classes_translate_into_section_9_1s_four(self) -> None:
        """The seam between this law and feature 168, exercised rather than
        assumed: the classes this law reports are ones the vocabulary owner can
        place in §9.1's column, so a breach record is never a class the store
        cannot write."""
        from sandbox import FAIL_CLASS_TABLE

        for runner_class in (
            CPU_FAIL_CLASS,
            MEMORY_FAIL_CLASS,
            PIDS_FAIL_CLASS,
        ):
            assert runner_class in FAIL_CLASS_TABLE, runner_class
            assert FAIL_CLASS_TABLE[runner_class] in (
                "ok",
                "timeout",
                "error",
                "tripwire_fail",
            ), runner_class

    def test_the_cpu_breach_becomes_the_timeout_class_the_runner_records(self) -> None:
        """A cpu budget exhausted is the one breach whose class is also §9.1's
        ``timeout`` — the same word feature 163's wall-clock kill is recorded
        under, because ``cpu.max`` throttling *is* the runner's timeout from the
        box's side.  Named here so the collision is a pinned fact rather than a
        surprise in the store."""
        from evaluator import failure_outcome

        assert CPU_FAIL_CLASS == "timeout"
        assert failure_outcome(CPU_FAIL_CLASS) == "timeout"

    def test_the_memory_breach_becomes_the_error_class(self) -> None:
        """``oom`` is not one of §9.1's four, so ``failure_outcome`` maps it to
        ``error`` — "failed any other way" — which is what feature 168's table
        says too.  The two readings of the same class are pinned equal here."""
        from evaluator import failure_outcome

        assert failure_outcome(MEMORY_FAIL_CLASS) == "error"

    def test_the_runner_defaults_are_the_ones_the_law_compiled(self) -> None:
        """All three at once, against the committed artifact rather than against
        the constants: a deployment whose file drifted would fail here even if
        the constants were edited to match."""
        from evaluator._sandbox import (
            DEFAULT_CPU_S as RUNNER_CPU_S,
        )
        from evaluator._sandbox import (
            DEFAULT_MEM_MB as RUNNER_MEM_MB_EVALUATOR,
        )
        from evaluator._sandbox import (
            DEFAULT_PIDS as RUNNER_PIDS,
        )

        assert POLICY.value("cpu_s") == RUNNER_CPU_S
        assert POLICY.value("pids") == RUNNER_PIDS
        # The memory field is the *cgroup* limit and the runner's default is its
        # RLIMIT_AS fallback, so these two are deliberately different — stated as
        # an inequality so a future edit that "fixed" it fails here.
        assert POLICY.value("mem_mb") != RUNNER_MEM_MB_EVALUATOR
        assert POLICY.value("mem_mb") == SECTION_5_2_MEM_MB


class TestTheCompileRefusesWhatIsNotSection52s:
    """The compile-time half of *rejects*, through the in-memory seam.

    The artifact suite exercises the disk path; these tests hold the compiler
    itself, which is what every other caller — a CI check rebuilding a policy from
    a manifest — actually reaches.
    """

    def test_a_well_formed_document_compiles(self) -> None:
        policy = compile_budget_policy(committed_budget_document())
        assert policy.fields() == MEASURED_FIELDS

    @pytest.mark.parametrize(
        ("field", "value"),
        [("cpu_s", 60), ("mem_mb", 4096), ("pids", 8)],
    )
    def test_any_other_limit_is_refused(self, field: str, value: object) -> None:
        """Each of the three on its own: a compiler that held one field to §5.2
        and took the other two on trust would pass a test that only checked
        one."""
        document = budget_document(**{field: value})
        with pytest.raises(CgroupBudgetExceeded) as raised:
            compile_budget_policy(document)
        assert str(raised.value).startswith(CGROUP_LIMITS_REQUIRED_CODE)
        assert field in str(raised.value)

    def test_the_refusal_does_not_quietly_apply_the_offending_value(self) -> None:
        """The property the whole compile exists for, stated as behaviour: a
        refusal means the caller holds *nothing*, not a policy carrying the two
        limits that happened to be right."""
        with pytest.raises(SandboxBudgetError):
            compile_budget_policy(budget_document(mem_mb=SECTION_5_2_MEM_MB + 1))

    def test_a_missing_marker_is_refused(self) -> None:
        """No marker at all is the same refusal as a foreign one: this compiler
        does not read documents that do not claim to be this policy."""
        document = committed_budget_document()
        del document["policy"]
        with pytest.raises(CgroupBudgetDocumentError):
            compile_budget_policy(document)

    def test_a_malformed_measured_field_is_a_document_refusal_not_a_limit_refusal(
        self,
    ) -> None:
        """The two refusals told apart, which is the split the error classes
        exist for: ``"2048"`` is a *shape* problem about the file, while ``4096``
        is a *value* problem about the deployment, and the repairs are different
        people's."""
        with pytest.raises(CgroupBudgetDocumentError):
            compile_budget_policy(budget_document(mem_mb="2048"))
        with pytest.raises(CgroupBudgetExceeded):
            compile_budget_policy(budget_document(mem_mb=4096))

    def test_the_refusal_names_the_field_and_the_value(self) -> None:
        """A message saying only "budget refused" would hide which of the three a
        drifted configuration got wrong — the same discipline every other law's
        refusal in this member follows."""
        with pytest.raises(CgroupBudgetExceeded) as raised:
            compile_budget_policy(budget_document(pids=999))
        message = str(raised.value)
        assert "pids" in message
        assert "999" in message
        assert "32" in message
