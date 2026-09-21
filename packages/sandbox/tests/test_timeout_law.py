"""Feature 163: the wall-clock budget law — the kill and the class it persists.

The step this file's subject makes checkable: *"System persists a timeout fail
class after hard-killing a sandboxed run that exceeded its 30 second wall clock
budget."*  Three claims, and the tests below take them in that order.

**The kill is a value, never a raise, and this is the file's first and largest
claim.**  §5.2's control table is "Timeout | Hard kill, recorded as
``fail_class=timeout``"; §8's ledger carries ``timeout`` among its four
``outcome`` spellings; §6.1 step 11 charges the trial "even if the node fails.
A failed evaluation still consumed a hypothesis"; and :class:`evaluator.SandboxResult`
already returns its kills as values, stating in its own docstring that a failed
run "is a value, not an exception".  So a paraeterised sweep across the whole
duration space asserts the *absence* of an exception — the honest way to test a
law whose subject is an outcome — and only the *unreadable* run raises.

**What this law refuses is the recording, not the run.**  ``elapsed_s`` that is
not a number of seconds, a committed artifact that does not declare §5.2's
thirty: those raise, and they raise a :class:`~sandbox.errors.SandboxTimeoutError`
whose message opens with the greppable ``timeout`` token the way every other
law's refusal in this member does.  A caller that reads the member's other five
laws and expects ``require`` to raise on *the feature's own subject* will be
surprised here, and that surprise is the feature — so the tests name it.

**The cross-member spellings are pinned as data rather than imported.**  The
member's one-provenance rule: the box agent-authored code is put inside must not
acquire a dependency on the member that drives it, so this module restates
``evaluator``'s ``"timeout"``, §9.1's column name and the four-class vocabulary
— and this suite is what makes the restatement safe.  A rename on the other side
of the seam fails here rather than producing a stored class nothing reads.
"""

from __future__ import annotations

import pytest
from _documents import (
    AT_BUDGET_S,
    FLAG_DURATION,
    OVERRUN_S,
    SEED_NODE_ID,
    TEXT_DURATION,
    WALL_S,
    WITHIN_S,
    committed_timeout_document,
    node_fail_class_record,
    timeout_run,
)
from sandbox import (
    DEFAULT_WALL_S,
    NODE_FAIL_CLASSES,
    TIMEOUT_COMPONENT_NAME,
    TIMEOUT_FAIL_CLASS,
    SandboxTimeout,
    SandboxTimeoutError,
    TimeoutDecision,
    TimeoutKill,
    TimeoutPolicy,
    TimeoutReason,
    TimeoutRecord,
    classify_duration,
    committed_timeout_policy,
    compile_timeout_policy,
    exceeded_budget,
    kill_timeout,
    sandbox_timeout,
)

#: The policy every test in this file judges against — compiled from the
#: committed artifact, which is what a deployment actually holds.  A module
#: constant rather than a fixture because it is *immutable*: a compiled policy
#: is a frozen dataclass over one number, so no test can drift it for another.
#: The suite's fresh-object rule (see ``_documents``) exists for *mutable*
#: documents and explicitly does not apply to a frozen value.
POLICY: TimeoutPolicy = committed_timeout_policy()

#: Feature 163's sentence, verbatim — the "30" the law is held to.  Spelled as
#: data rather than read from :data:`sandbox.DEFAULT_WALL_S` so a rename of the
#: number fails here rather than being followed, and so the assertion below
#: reads as the feature's own claim.
SECTION_5_2_BUDGET: float = 30.0

#: §9.1's column comment, verbatim: ``fail_class TEXT -- ok | timeout | error |
#: tripwire_fail``.  Written out so a reordering or a dropped class on the
#: ledger side fails here.
SECTION_9_1_VOCABULARY: tuple[str, ...] = ("ok", "timeout", "error", "tripwire_fail")

#: The token every refusal from this law opens with, so an operator greps one
#: word.  Restated, and asserted to be what the law actually emits.
TIMEOUT_TOKEN: str = "timeout"


class TestTheKillIsAValue:
    """The feature's headline, as the absence of an exception."""

    def test_a_run_over_budget_is_killed_rather_than_raised(self) -> None:
        # §5.2's row read literally: the run is hard-killed *and recorded*, so
        # the law hands back the record.  A raise here would be a second,
        # disagreeing spelling of a fact the runner already decided.
        decision = kill_timeout(timeout_run(elapsed_s=OVERRUN_S), POLICY)
        assert decision.killed is True
        assert decision.refused is False
        assert decision.reason is TimeoutReason.EXCEEDED_BUDGET
        assert isinstance(decision.kill, TimeoutKill)

    def test_the_kill_names_section_eights_class(self) -> None:
        # The class the feature persists, spelled as §9.1 writes it in the
        # column comment and §8 in the ledger's — restated in the law, pinned
        # here, and the two must agree.
        decision = kill_timeout(timeout_run(elapsed_s=OVERRUN_S), POLICY)
        assert decision.kill.fail_class == TIMEOUT_FAIL_CLASS
        assert decision.kill.fail_class == "timeout"

    def test_the_kill_carries_the_durations_that_earned_it(self) -> None:
        # A bare "timeout" says a run died at the wall; *by how much* is what
        # tells an operator whether the budget is wrong or the signal is.  The
        # subtraction is exact because both values were classified first.
        decision = kill_timeout(timeout_run(elapsed_s=OVERRUN_S), POLICY)
        kill = decision.kill
        assert kill.elapsed_s == OVERRUN_S
        assert kill.budget_s == SECTION_5_2_BUDGET
        assert kill.overrun_s == pytest.approx(OVERRUN_S - SECTION_5_2_BUDGET)
        assert kill.overrun_s > 0

    def test_the_kill_carries_the_node_and_component_when_it_has_them(self) -> None:
        # The two identifiers an operator correlates on.  Carried through from
        # the subject rather than dropped, because a kill report that could not
        # name the node is one nobody can act on.
        decision = kill_timeout(
            timeout_run(elapsed_s=OVERRUN_S, node_id="n-7", component="signal-sandbox"),
            POLICY,
        )
        assert decision.kill.node_id == "n-7"
        assert decision.kill.component == "signal-sandbox"

    def test_every_duration_space_answers_without_raising(self) -> None:
        # The sweep, and the honest way to assert a law whose subject is an
        # outcome: across inside, at, just past and far past the budget, and
        # across a run that carries no budget of its own, the law *returns*.
        # A single raise anywhere in here would mean one hung signal could take
        # down an evaluator over thousands of unattended candidates.
        for elapsed in (0.0, WITHIN_S, AT_BUDGET_S, WALL_S + 0.001, OVERRUN_S, 1e9):
            for budget in (None, WALL_S):
                run = timeout_run(
                    elapsed_s=elapsed,
                    **({} if budget is None else {"budget_s": budget}),
                )
                decision = kill_timeout(run, POLICY)
                assert isinstance(decision, TimeoutDecision)
                assert isinstance(decision.detail, str) and decision.detail

    def test_require_returns_the_kill_rather_than_raising_it(self) -> None:
        # The launcher verb, and the one place this member's shape differs.
        # A caller puts ``require`` on the line after the spawn; here it hands
        # back the kill to persist instead of refusing the dispatch.
        decision = kill_timeout(timeout_run(elapsed_s=OVERRUN_S), POLICY)
        kill = decision.require()
        assert isinstance(kill, TimeoutKill)
        assert kill.fail_class == TIMEOUT_FAIL_CLASS

    def test_require_returns_none_for_a_run_inside_its_budget(self) -> None:
        # The commonest answer, and it is neither a kill nor a refusal: §6.1
        # step 2 dispatches thousands of runs for every one that hangs, and
        # ``None`` is how this law says "nothing to persist".
        decision = kill_timeout(timeout_run(elapsed_s=WITHIN_S), POLICY)
        assert decision.require() is None
        assert decision.killed is False
        assert decision.refused is False
        assert decision.reason is TimeoutReason.WITHIN_BUDGET

    def test_the_kill_row_is_shaped_for_the_store(self) -> None:
        # §9.1's own column name, so a caller writes the outcome without
        # assembling the same keys itself.  A fresh dict per call — a shared
        # one would let a caller's edit leak into the next kill's row.
        decision = kill_timeout(
            timeout_run(elapsed_s=OVERRUN_S, node_id="n-7"), POLICY
        )
        row = decision.kill.row()
        assert row["fail_class"] == "timeout"
        assert row["elapsed_s"] == OVERRUN_S
        assert row["budget_s"] == SECTION_5_2_BUDGET
        assert row["node_id"] == "n-7"
        assert decision.kill.row() is not row

    def test_a_kill_with_no_node_carries_no_node_key(self) -> None:
        # "no node" is an absence, and an absent key is how the store reads it —
        # writing ``node_id: ""`` would be a node the tree cannot look up.
        row = kill_timeout(timeout_run(elapsed_s=OVERRUN_S), POLICY).kill.row()
        assert "node_id" not in row


class TestTheBoundary:
    """*Exceeded* read strictly — the one judgement that could have gone twice."""

    def test_a_run_at_exactly_its_budget_was_not_killed(self) -> None:
        # The feature's verb is *exceeded*, and a run that took exactly its
        # budget did not exceed it.  A law killing at the instant the budget was
        # still satisfied would be sharper than §5.2's row, and the difference
        # is one whole class of runs.
        decision = kill_timeout(timeout_run(elapsed_s=AT_BUDGET_S), POLICY)
        assert decision.killed is False
        assert decision.reason is TimeoutReason.WITHIN_BUDGET
        assert decision.require() is None

    def test_a_run_a_hair_over_its_budget_was_killed(self) -> None:
        # The other side of the same boundary, so the test above proves a strict
        # comparison rather than an off-by-a-whole-budget one.
        decision = kill_timeout(
            timeout_run(elapsed_s=WALL_S + 0.001), POLICY
        )
        assert decision.killed is True

    def test_exceeded_budget_is_strict_on_both_sides(self) -> None:
        # The named function that owns the interpretation, exercised directly:
        # a reader asking *when exactly do we kill?* should be able to read the
        # answer rather than infer it from a comparison buried in the gate.
        assert exceeded_budget(OVERRUN_S, WALL_S) is True
        assert exceeded_budget(AT_BUDGET_S, WALL_S) is False
        assert exceeded_budget(WITHIN_S, WALL_S) is False
        assert exceeded_budget(0.0, WALL_S) is False

    def test_exceeded_budget_never_raises_on_an_unreadable_duration(self) -> None:
        # A comparison between two values that are not numbers of seconds has no
        # defensible answer.  ``False`` rather than a raise, so a caller using
        # this directly is never surprised; the run that must *hear* about its
        # unreadable duration goes through ``check``.
        for bad in (TEXT_DURATION, FLAG_DURATION, None, -1.0, object()):
            assert exceeded_budget(bad, WALL_S) is False
            assert exceeded_budget(OVERRUN_S, bad) is False


class TestTheRefusals:
    """What this law refuses: the recording, never the kill."""

    def test_an_absent_elapsed_time_is_refused_by_name(self) -> None:
        # The run whose duration nobody measured.  Its own reason, because the
        # repair differs from the unreadable-subject one: the caller has the
        # right *object* and the wrong *measurement*.
        decision = kill_timeout(timeout_run(elapsed_s=None), POLICY)
        assert decision.refused is True
        assert decision.killed is False
        assert decision.reason is TimeoutReason.MALFORMED_DURATION

    def test_a_text_duration_is_refused_rather_than_parsed(self) -> None:
        # §5.2 passes ``wall_s=30`` — a number — and the watchdog compares a
        # number.  A ``"47.5s"`` this law silently parsed would be this member
        # inventing a grammar no runner reads, so it is refused instead.
        decision = kill_timeout(timeout_run(elapsed_s=TEXT_DURATION), POLICY)
        assert decision.refused is True
        assert decision.reason is TimeoutReason.MALFORMED_DURATION

    def test_a_flag_is_refused_though_python_makes_it_an_int(self) -> None:
        # ``True`` is an ``int`` in Python and is not a duration.  Accepting it
        # would make a boolean and a budget indistinguishable — the exclusion
        # the seed and thread laws state for their own quantities.
        assert classify_duration(FLAG_DURATION) is None
        decision = kill_timeout(timeout_run(elapsed_s=FLAG_DURATION), POLICY)
        assert decision.refused is True

    def test_a_negative_duration_is_refused(self) -> None:
        # A clock that went backwards rather than a run that finished early.
        assert classify_duration(-0.5) is None
        decision = kill_timeout(timeout_run(elapsed_s=-0.5), POLICY)
        assert decision.refused is True

    def test_a_non_finite_duration_is_refused(self) -> None:
        # ``NaN`` compares false against every bound, so a budget admitted as
        # ``NaN`` would be one no run could ever exceed — a watchdog that never
        # fires while every line of the configuration says it will.
        for bad in (float("nan"), float("inf"), float("-inf")):
            assert classify_duration(bad) is None
            assert kill_timeout(timeout_run(elapsed_s=bad), POLICY).refused is True

    def test_an_unreadable_subject_is_refused_distinctly(self) -> None:
        # An object carrying no elapsed time at all is a different failure from
        # one carrying a bad one, and the reason says which: the repair is at
        # the caller's own record type rather than at whatever produced a
        # number.
        decision = kill_timeout(object(), POLICY)
        assert decision.refused is True
        assert decision.reason is TimeoutReason.UNREADABLE_SUBJECT

    def test_an_unreadable_subject_is_not_a_kill(self) -> None:
        # The distinction the whole decision object is built on: a refusal is
        # ``killed=False`` and so is a clean run, so a caller reading ``not
        # killed`` as "the run was fine" would treat an unreadable subject as a
        # clean one — the "absence that reads as a result" failure.
        decision = kill_timeout(object(), POLICY)
        assert decision.killed is False
        assert decision.refused is True
        assert decision.kill is None

    def test_require_raises_on_a_refusal_by_class_name_and_token(self) -> None:
        # The bridge to an exception, for the caller that must not proceed.  The
        # message opens with the greppable token so an operator greps one word
        # across every law in this member.
        decision = kill_timeout(timeout_run(elapsed_s=TEXT_DURATION), POLICY)
        with pytest.raises(SandboxTimeoutError) as raised:
            decision.require()
        assert str(raised.value).startswith(TIMEOUT_TOKEN)

    def test_require_does_not_raise_for_a_kill(self) -> None:
        # The property a reader of the other five laws will find surprising, so
        # it is asserted rather than implied: this law's headline outcome is not
        # an exception.  A caller that wants it raised re-raises on ``not None``.
        decision = kill_timeout(timeout_run(elapsed_s=OVERRUN_S), POLICY)
        try:
            decision.require()
        except Exception as exc:  # pragma: no cover - the failure this asserts
            raise AssertionError(
                f"a timeout was raised rather than recorded: {exc!r}. §5.2's "
                f"table records the class; the kill is an outcome (feature 163)."
            ) from exc


class TestTheDurations:
    """What a number of seconds is — one classifier, two seams."""

    def test_a_genuine_number_is_admitted_in_both_writings(self) -> None:
        # ``30`` and ``30.0`` are the same measurement written two ways, and
        # refusing one while admitting the other would be a law about typography
        # rather than about a budget.
        assert classify_duration(30) == 30.0
        assert classify_duration(30.0) == 30.0
        assert classify_duration(0) == 0.0
        assert isinstance(classify_duration(30), float)

    def test_everything_unplaceable_is_none(self) -> None:
        # The classifier's whole answer space: ``None`` for anything that is not
        # a duration, and the *gate* decides which refusal that earns — because
        # a budget and an elapsed time are refused with different sentences and
        # different repairs.
        for bad in (
            None,
            TEXT_DURATION,
            b"30",
            FLAG_DURATION,
            False,
            -1.0,
            float("nan"),
            object(),
            [30],
            {"wall_s": 30},
        ):
            assert classify_duration(bad) is None, bad

    def test_the_policy_and_the_run_are_read_by_one_classifier(self) -> None:
        # The member's one-provenance rule applied to the one quantity this law
        # owns: a document and a run cannot disagree about what a number of
        # seconds is, because both go through this function.  Asserted by
        # behaviour rather than by inspection — the same value is refused on
        # both sides.
        assert classify_duration(FLAG_DURATION) is None
        assert kill_timeout(timeout_run(elapsed_s=FLAG_DURATION), POLICY).refused
        assert kill_timeout(timeout_run(elapsed_s=WITHIN_S, budget_s=FLAG_DURATION), POLICY).killed is False


class TestTheBudgetIsThePolicys:
    """The run's own ``budget_s`` is a record, never a leash.

    This is the one seam in feature 163 that could be turned against itself.
    §5.2's ``Limits(wall_s=30)`` is a *declaration* the deployment makes, and a
    run judged by the budget *it* declared could widen its own bound —
    ``budget_s=1e9`` would put the watchdog's hard kill out of reach while every
    line of the configuration still read as enforced.  The tests below hold the
    verdict to the compiled policy and the run's number to a record that is
    *reported* rather than obeyed.
    """

    def test_a_run_declaring_a_huge_budget_is_still_killed(self) -> None:
        # The attack, stated as behaviour: a run that says it was dispatched
        # under an effectively infinite budget, and outran the real one, is
        # killed anyway.  A gate that compared against this number would return
        # ``within-budget`` and no stored ``fail_class`` would ever exist.
        decision = kill_timeout(
            timeout_run(elapsed_s=OVERRUN_S, budget_s=1e9), POLICY
        )
        assert decision.killed is True
        assert decision.kill.budget_s == SECTION_5_2_BUDGET
        assert decision.reason is TimeoutReason.EXCEEDED_BUDGET

    def test_a_run_declaring_a_tiny_budget_is_not_killed_by_it(self) -> None:
        # The other direction, and it matters too: a run that finished in 3s
        # while claiming a 1s budget was *not* hard-killed by the watchdog, and
        # the law does not invent a kill the runner never made.  A fabricated
        # timeout is as wrong as a missing one — it is a stored class naming a
        # kill nobody performed.
        decision = kill_timeout(timeout_run(elapsed_s=WITHIN_S, budget_s=1.0), POLICY)
        assert decision.killed is False
        assert decision.reason is TimeoutReason.WITHIN_BUDGET

    def test_the_disagreement_is_reported_in_the_kills_sentence(self) -> None:
        # The number is not obeyed, and it is not *silently* ignored either:
        # a dispatch whose record disagrees with the committed budget is one
        # that did not go through this law, which is an audit finding and has to
        # survive into the operator-facing sentence.  The drifted number used
        # here is a plausible one a deployment would reach for — double the
        # committed budget — so the sentence names what the dispatch believed
        # rather than an absurdity no reader would write.
        decision = kill_timeout(
            timeout_run(elapsed_s=OVERRUN_S, budget_s=2 * SECTION_5_2_BUDGET), POLICY
        )
        assert "60s budget" in decision.kill.detail
        assert "did not go through" in decision.kill.detail
        # ...and the *verdict* is still the committed number's, which is the
        # point: the sentence reports the record, it does not adopt it.
        assert decision.kill.budget_s == SECTION_5_2_BUDGET

    def test_the_disagreement_is_reported_on_the_within_budget_side_too(self) -> None:
        # A run inside the committed budget that claims a *wider* one is still a
        # dispatch that bypassed the law, so the note is not a kill-only
        # decoration — it rides the sentence either way.
        decision = kill_timeout(timeout_run(elapsed_s=WITHIN_S, budget_s=1e9), POLICY)
        assert decision.killed is False
        assert "did not go through" in decision.detail

    def test_an_agreeing_budget_says_nothing_extra(self) -> None:
        # The ordinary case — a runner recording the committed number — must not
        # produce a note, or the sentence would carry noise on every dispatch
        # and the signal would be lost.
        decision = kill_timeout(
            timeout_run(elapsed_s=OVERRUN_S, budget_s=SECTION_5_2_BUDGET), POLICY
        )
        assert "did not go through" not in decision.kill.detail

    def test_a_run_carrying_no_budget_says_nothing_extra(self) -> None:
        # No record is not a disagreement.  The module's own ``TimeoutRun``
        # default is the committed number, so this is exercised with a stand-in
        # that carries only the duration.
        class Bare:
            elapsed_s = OVERRUN_S
            node_id = ""
            component = ""

        decision = kill_timeout(Bare(), POLICY)
        assert decision.killed is True
        assert "did not go through" not in decision.kill.detail

    def test_a_hand_built_policy_kills_at_its_own_number(self) -> None:
        # The other half of "the policy decides": a policy carrying a budget
        # other than the committed one kills at *that* number and says so, which
        # is the audit finding the docstring promises.  The compiler refuses
        # such a policy from a document — this asserts the gate itself obeys
        # whatever declaration it was handed, rather than re-reading a constant.
        strict = TimeoutPolicy(wall_s=1.0)
        decision = kill_timeout(timeout_run(elapsed_s=WITHIN_S), strict)
        assert decision.killed is True
        assert decision.kill.budget_s == 1.0


class TestAKillIsNeverFabricated:
    """A kill means a run died at the wall — the object refuses to say otherwise.

    ``TimeoutKill`` is exported and its ``row()`` is what a caller writes to
    §9.1, so a hand-assembled or store-rebuilt kill is a path that reaches the
    database.  These tests pin that the one fact a timeout record carries —
    *this run was hard-killed, and by how much* — cannot be asserted falsely.
    """

    def test_a_kill_for_a_run_inside_its_budget_is_refused(self) -> None:
        # The fabricated-outcome case: ``fail_class=timeout`` for a run that
        # finished early, with a negative overrun beside it.  A fabricated
        # timeout is as wrong as a missing one — it names a kill nobody made.
        with pytest.raises(SandboxTimeoutError) as raised:
            TimeoutKill(elapsed_s=WITHIN_S, budget_s=SECTION_5_2_BUDGET, detail="x")
        assert str(raised.value).startswith(TIMEOUT_TOKEN)

    def test_a_kill_at_exactly_the_budget_is_refused(self) -> None:
        # The boundary, on the object rather than the gate: *exceeded* is
        # strict, so a run that took exactly its budget was not hard-killed and
        # cannot be recorded as though it were.
        with pytest.raises(SandboxTimeoutError):
            TimeoutKill(elapsed_s=AT_BUDGET_S, budget_s=SECTION_5_2_BUDGET, detail="x")

    def test_a_kill_built_from_a_non_duration_is_refused(self) -> None:
        # A store row is rebuilt into a kill on the read path, so the durations
        # arrive from outside the law and have to be checked here — the same
        # classifier the compiler and the gate use.
        for bad in (TEXT_DURATION, FLAG_DURATION, None, -1.0):
            with pytest.raises(SandboxTimeoutError):
                TimeoutKill(elapsed_s=bad, budget_s=SECTION_5_2_BUDGET, detail="x")
            with pytest.raises(SandboxTimeoutError):
                TimeoutKill(elapsed_s=OVERRUN_S, budget_s=bad, detail="x")

    def test_a_genuine_kill_still_constructs_and_reads_back(self) -> None:
        # The invariant must not make the legitimate path unreachable.
        kill = TimeoutKill(
            elapsed_s=OVERRUN_S, budget_s=SECTION_5_2_BUDGET, detail="x"
        )
        assert kill.overrun_s > 0
        assert kill.fail_class == TIMEOUT_FAIL_CLASS
        assert kill.row()["fail_class"] == "timeout"

    def test_every_kill_the_gate_builds_satisfies_the_invariant(self) -> None:
        # The two seams cannot disagree: whatever the gate decides is a kill, it
        # hands the constructor a pair that exceeds — so a future edit to the
        # comparison would fail here rather than at the first dispatch.
        for elapsed in (WALL_S + 0.001, OVERRUN_S, 1e9):
            kill = kill_timeout(timeout_run(elapsed_s=elapsed), POLICY).kill
            assert kill.overrun_s > 0, elapsed


class TestThePolicyHoldsADuration:
    """A hand-assembled policy is a supported path, so it is checked too.

    :class:`TimeoutPolicy` is exported and its fields are public, and the class
    docstring contemplates a hand-built one — the gate kills at whatever it was
    handed and reports the number, which is the audit finding.  That path must
    fail the same *way* as the compiler does when it is handed junk: this
    member's greppable refusal, not a bare ``ValueError`` raised from inside a
    refusal sentence by an ``f"{...:g}"`` on a string.
    """

    def test_a_policy_built_from_a_text_budget_is_refused(self) -> None:
        with pytest.raises(SandboxTimeoutError) as raised:
            TimeoutPolicy(wall_s="thirty")
        assert str(raised.value).startswith(TIMEOUT_TOKEN)

    def test_every_junk_budget_is_refused_by_the_same_classifier(self) -> None:
        # One classifier, three seams — the compiler, the gate and now the
        # constructor all read a duration through ``classify_duration``, so a
        # value refused in one place cannot be admitted in another.
        for bad in ("30", None, FLAG_DURATION, -1.0, float("nan"), object()):
            assert classify_duration(bad) is None, bad
            with pytest.raises(SandboxTimeoutError):
                TimeoutPolicy(wall_s=bad)

    def test_a_policy_carrying_another_number_is_still_constructible(self) -> None:
        # The *value* is not pinned here — only the shape.  A policy carrying a
        # different budget is a legitimate hand-assembled object, and holding it
        # to the committed thirty is the compiler's job rather than the
        # constructor's; refusing it here would make the documented audit-
        # finding path unreachable.
        assert TimeoutPolicy(wall_s=1.0).wall_s == 1.0
        assert TimeoutPolicy(wall_s=DEFAULT_WALL_S).wall_s == DEFAULT_WALL_S

    def test_a_compiled_policy_never_hits_the_constructor_refusal(self) -> None:
        # The invariant's only purpose is the hand-built path; every documented
        # path was already refused earlier and by name, so composition cannot
        # trip on this.
        assert compile_timeout_policy(committed_timeout_document()).wall_s == (
            DEFAULT_WALL_S
        )


class TestTheTwoRefusalsAreToldApart:
    """An unreadable *subject* and an unreadable *duration* are different facts.

    ``TimeoutReason`` carries both because the repairs differ: the first is
    "you handed this law the wrong object", the second is "whatever produced
    this number is what to look at".  The distinction is easy to lose by keying
    the branch on the subject's *type* rather than on what was found — which
    would silently diagnose every duck-typed subject's malformed duration as an
    unreadable object.
    """

    def test_a_duck_typed_subject_with_a_bad_duration_is_malformed(self) -> None:
        # The regression this class exists for: an object that *does* carry an
        # ``elapsed_s`` — so it is a run this law can read — carrying a value
        # that is not a number of seconds.  The verdict must be the duration
        # refusal, not the subject one.
        class Row:
            elapsed_s = TEXT_DURATION
            node_id = "n-1"
            component = "signal-sandbox"

        decision = kill_timeout(Row(), POLICY)
        assert decision.reason is TimeoutReason.MALFORMED_DURATION
        assert decision.refused is True

    def test_a_duck_typed_subject_with_a_good_duration_is_judged(self) -> None:
        # The same shape, well-formed: the law reads a caller's own record type
        # rather than requiring its own — which is the whole reason the two
        # branches cannot be keyed on ``isinstance``.
        class Row:
            elapsed_s = OVERRUN_S
            node_id = "n-1"
            component = "signal-sandbox"

        decision = kill_timeout(Row(), POLICY)
        assert decision.killed is True
        assert decision.kill.node_id == "n-1"
        assert decision.kill.component == "signal-sandbox"

    def test_a_subject_with_no_elapsed_time_at_all_is_unreadable(self) -> None:
        # The other branch, kept distinct: *nothing* to read is a different
        # failure from a bad reading, and the object here does not have the
        # attribute at all.
        class NotARun:
            node_id = "n-1"

        decision = kill_timeout(NotARun(), POLICY)
        assert decision.reason is TimeoutReason.UNREADABLE_SUBJECT
        assert decision.refused is True

    def test_the_two_refusals_produce_different_sentences(self) -> None:
        # An operator's only interface is the message, so the two must not read
        # the same: one names the elapsed time it could not use, the other says
        # no elapsed time was there.
        class Bad:
            elapsed_s = TEXT_DURATION

        class Absent:
            pass

        malformed = kill_timeout(Bad(), POLICY).detail
        unreadable = kill_timeout(Absent(), POLICY).detail
        assert malformed != unreadable
        assert TEXT_DURATION in malformed
        assert "no elapsed time at all" in unreadable

    def test_both_refusals_raise_the_same_error_through_require(self) -> None:
        # Two reasons, one exception: a caller that only wants to be stopped
        # catches one class, and the *reason* is what distinguishes the repair.
        # Feature 157's restraint, applied here — an error per reason would let
        # a caller catch the spellings it thought of.
        for subject in (timeout_run(elapsed_s=TEXT_DURATION), object()):
            with pytest.raises(SandboxTimeoutError):
                kill_timeout(subject, POLICY).require()


class TestTheCrossMemberSpellings:
    """The restatements this member makes, pinned so a rename cannot slip past."""

    def test_the_budget_is_section_5_2s_thirty_seconds(self) -> None:
        # The feature's own sentence names it, and this is where the number is
        # held to the sentence rather than to itself.
        assert DEFAULT_WALL_S == SECTION_5_2_BUDGET
        assert POLICY.wall_s == SECTION_5_2_BUDGET
        assert sandbox_timeout().wall_s == SECTION_5_2_BUDGET

    def test_the_budget_survives_the_millisecond_conversion(self) -> None:
        # A caller sizing a watchdog reads the budget in the unit its timeout
        # parameter takes; the conversion is exact because it is a
        # multiplication, not a rounding.
        assert POLICY.milliseconds == 30_000.0

    def test_the_fail_class_is_the_ledgers_spelling(self) -> None:
        # §8's ledger and §9.1's node column and ``evaluator``'s SandboxResult
        # all spell this class the same way.  Restated here as data, and this is
        # the assertion that keeps the restatement honest.
        assert TIMEOUT_FAIL_CLASS == "timeout"
        assert "timeout" in SECTION_9_1_VOCABULARY
        assert NODE_FAIL_CLASSES == SECTION_9_1_VOCABULARY

    def test_the_vocabulary_is_section_9_1s_four_in_its_order(self) -> None:
        # The column comment's declaration order, and exactly four classes: the
        # law reads this vocabulary to refuse writing over a *different* class,
        # so a fifth arriving unnoticed would change what it can protect.
        assert NODE_FAIL_CLASSES == ("ok", "timeout", "error", "tripwire_fail")

    def test_the_component_name_is_the_categorys_sixth(self) -> None:
        # The registry replaces a name's earlier registration, so this must be
        # its own name and not any of the other seats'.
        assert TIMEOUT_COMPONENT_NAME == "sandbox-timeout"
        assert TIMEOUT_COMPONENT_NAME not in {
            "sandbox",
            "sandbox-imports",
            "sandbox-transfer",
            "sandbox-seed",
            "sandbox-threads",
            "sandbox-failclass",
            "sandbox-budget",
            "sandbox-syscalls",
        }


class TestTheRecording:
    """Feature 163's second half: *persists a timeout fail class*."""

    def test_the_class_is_written_onto_a_fresh_node_record(self) -> None:
        # §9.1's column, on the row shape a relational driver hands over.  An
        # unevaluated node names no class, and filling it in is exactly what
        # this verb is for.
        record = node_fail_class_record()
        receipt = sandbox_timeout().record(record)
        assert record["fail_class"] == "timeout"
        assert isinstance(receipt, TimeoutRecord)
        assert receipt.written == TIMEOUT_FAIL_CLASS
        assert receipt.node_id == SEED_NODE_ID

    def test_the_write_reports_what_it_replaced(self) -> None:
        # A *record* holds one terminal class — that is what §9.1's column is —
        # so the receipt is where "this record already said something else"
        # survives.  A first write replaced nothing.
        receipt = sandbox_timeout().record(node_fail_class_record())
        assert receipt.superseded is None
        assert receipt.overwrote is False

    def test_re_persisting_the_same_class_is_idempotent(self) -> None:
        # A retried kill, a re-persisted outcome: not news, and reporting it as
        # a change would make every retry look like a rewritten history.
        record = node_fail_class_record(fail_class="timeout")
        receipt = sandbox_timeout().record(record)
        assert receipt.superseded is None
        assert receipt.overwrote is False
        assert record["fail_class"] == "timeout"

    def test_a_record_naming_a_different_class_is_refused(self) -> None:
        # The one judgement here that could reasonably have gone the other way,
        # and it goes this way for the seed law's reason: the record holds one
        # value and the two statements are about two different failures.  A node
        # quarantined by §17's tripwire that later reads as a timeout is a
        # quarantine erased by a timestamp.
        record = node_fail_class_record(fail_class="tripwire_fail")
        with pytest.raises(SandboxTimeoutError) as raised:
            sandbox_timeout().record(record)
        assert record["fail_class"] == "tripwire_fail"
        assert "tripwire_fail" in str(raised.value)
        assert "timeout" in str(raised.value)

    def test_every_other_terminal_class_is_refused_too(self) -> None:
        # Not just the tripwire: ``ok`` and ``error`` are statements about the
        # same run, and writing over either erases a real outcome.
        for other in ("ok", "error"):
            record = node_fail_class_record(fail_class=other)
            with pytest.raises(SandboxTimeoutError):
                sandbox_timeout().record(record)
            assert record["fail_class"] == other

    def test_a_class_outside_the_vocabulary_is_refused_not_erased(self) -> None:
        # A record carrying something §9.1 does not declare.  Refused by name
        # rather than treated as "no class": a caller told "nothing there" would
        # write ``timeout`` over whatever was, erasing a failure nobody can now
        # name.
        record = node_fail_class_record(fail_class="hang")
        with pytest.raises(SandboxTimeoutError) as raised:
            sandbox_timeout().record(record)
        assert "hang" in str(raised.value)
        assert record["fail_class"] == "hang"

    def test_the_write_reads_the_ledgers_outcome_spelling(self) -> None:
        # §8's ledger names the same fact ``outcome``.  The law reads whichever
        # the record already carries, so it neither adds a second key nor
        # misses a class the ledger already stated.
        record = node_fail_class_record(fail_class="error", field="outcome")
        with pytest.raises(SandboxTimeoutError):
            sandbox_timeout().record(record)
        assert record["outcome"] == "error"
        assert "fail_class" not in record

    def test_the_write_lands_on_the_ledgers_spelling_when_that_is_what_it_has(self) -> None:
        # An ``outcome`` key holding *this* class is idempotent, and the field
        # the law reports is the one it found rather than §9.1's — the record
        # keeps its own shape.
        record = {"node_id": SEED_NODE_ID, "outcome": "timeout"}
        receipt = sandbox_timeout().record(record)
        assert receipt.field == "outcome"
        assert record["outcome"] == "timeout"

    def test_the_write_reaches_an_object_record_as_well(self) -> None:
        # The other shape the repository's records take: the plain objects the
        # stores return carry the class as an attribute.
        class Row:
            def __init__(self) -> None:
                self.node_id = SEED_NODE_ID
                self.fail_class = None

        row = Row()
        receipt = sandbox_timeout().record(row)
        assert row.fail_class == "timeout"
        assert receipt.node_id == SEED_NODE_ID

    def test_a_record_this_law_cannot_write_is_refused(self) -> None:
        # The feature's verb is *persists*.  A record that refuses the write
        # would otherwise report a persistence that never happened — the silent
        # no-op a caller cannot distinguish from success.
        from types import MappingProxyType

        frozen = MappingProxyType({"node_id": SEED_NODE_ID})
        with pytest.raises(SandboxTimeoutError) as raised:
            sandbox_timeout().record(frozen)
        assert TIMEOUT_TOKEN in str(raised.value)

    def test_an_object_that_takes_no_attribute_is_refused(self) -> None:
        # The attribute half of the same refusal: a slots-based or frozen
        # record that cannot carry the class must say so rather than drop it.
        class Sealed:
            __slots__ = ("node_id",)

            def __init__(self) -> None:
                self.node_id = SEED_NODE_ID

        with pytest.raises(SandboxTimeoutError):
            sandbox_timeout().record(Sealed())

    def test_a_null_class_field_is_the_ordinary_unevaluated_node(self) -> None:
        # §9.1's column is declared ``fail_class TEXT,`` — nullable — so a row
        # straight from a driver carries the *key* with a null value on every
        # node that has not been evaluated.  That is the case this verb exists
        # for, so it must be treated as "nothing yet" rather than as a
        # contradiction or an unreadable value.
        record = {"node_id": SEED_NODE_ID, "fail_class": None}
        receipt = sandbox_timeout().record(record)
        assert record["fail_class"] == "timeout"
        assert receipt.written == TIMEOUT_FAIL_CLASS
        assert receipt.overwrote is False

    def test_the_receipt_names_the_field_the_write_touched(self) -> None:
        # The receipt is the audit trail: a caller reading ``field`` must be
        # told where the class *landed*.  A null-valued or absent field is
        # written under the canonical name, so the receipt has to say so —
        # reporting ``None`` would tell an auditor the write went nowhere.
        for record in ({"node_id": SEED_NODE_ID, "fail_class": None}, {}):
            receipt = sandbox_timeout().record(record, node_id=SEED_NODE_ID)
            assert receipt.field == "fail_class", record
            assert record["fail_class"] == "timeout"

    def test_a_null_ledger_field_keeps_the_ledgers_own_spelling(self) -> None:
        # The same, on §8's row shape: the record keeps its own field name
        # rather than gaining §9.1's, and the receipt names that one.
        record = {"node_id": SEED_NODE_ID, "outcome": None}
        receipt = sandbox_timeout().record(record)
        assert record["outcome"] == "timeout"
        assert "fail_class" not in record
        assert receipt.field == "outcome"

    def test_a_real_class_beside_a_null_one_still_decides(self) -> None:
        # A record carrying a null under one spelling and a genuine class under
        # the other is not "no class" — the real one governs, and a null
        # sibling must not mask it into an idempotent overwrite.
        record = {
            "node_id": SEED_NODE_ID,
            "fail_class": None,
            "outcome": "tripwire_fail",
        }
        with pytest.raises(SandboxTimeoutError) as raised:
            sandbox_timeout().record(record)
        assert "tripwire_fail" in str(raised.value)
        assert record["outcome"] == "tripwire_fail"

    def test_a_sandbox_internal_class_is_refused_not_translated(self) -> None:
        # The neighbouring category's vocabulary: feature 161 records
        # ``sandbox_escape`` for a seccomp violation, and the runner has six of
        # its own (``oom``, ``crash``, ``violation``, ``payload``, ``empty``).
        # None is one of §9.1's four terminal classes, so this law refuses to
        # write over one — translating a seccomp verdict into a timeout would
        # erase an escape attempt, and re-labelling it is feature 168's job.
        for other in ("sandbox_escape", "oom", "crash", "violation", "payload", "empty"):
            record = node_fail_class_record(fail_class=other)
            with pytest.raises(SandboxTimeoutError) as raised:
                sandbox_timeout().record(record)
            assert other in str(raised.value), other
            assert record["fail_class"] == other

    def test_the_node_id_can_be_supplied_rather_than_read(self) -> None:
        # A caller that knows the node — a storer mid-write — says so, and the
        # receipt carries the caller's spelling rather than a re-read.
        record: dict[str, object] = {}
        receipt = sandbox_timeout().record(record, node_id="explicit-node")
        assert receipt.node_id == "explicit-node"
        assert record["fail_class"] == "timeout"

    def test_an_unidentified_record_still_produces_a_readable_refusal(self) -> None:
        # ``_record_node_id`` is read while building an error message, so a
        # record naming no id must not raise a second failure inside the first.
        with pytest.raises(SandboxTimeoutError) as raised:
            sandbox_timeout().record({"fail_class": "ok"})
        assert "<unidentified node>" in str(raised.value)

    def test_the_kill_and_the_write_are_the_two_halves_of_one_sentence(self) -> None:
        # End to end, through the composed component: the run overruns, the
        # kill names §8's class, and that class lands on §9.1's row.  This is
        # the feature's sentence executed rather than asserted about.
        law = sandbox_timeout()
        decision = law.check(timeout_run(elapsed_s=OVERRUN_S, node_id=SEED_NODE_ID))
        record = node_fail_class_record()
        law.record(record, node_id=decision.kill.node_id)
        assert record["fail_class"] == decision.kill.fail_class == "timeout"


class TestTheFacade:
    """The composed value: thin delegation, and no state a run could share."""

    def test_the_component_carries_only_the_compiled_policy(self) -> None:
        # No clock, no process, no deadline.  A component held across runs that
        # carried a watchdog would be one measuring a duration that belongs to a
        # single run, so two dispatches would share a deadline and the second
        # would be killed for the first's elapsed time.
        law = sandbox_timeout()
        assert isinstance(law, SandboxTimeout)
        assert SandboxTimeout.__slots__ == ("_policy",)
        assert law.policy is law.policy
        assert isinstance(law.policy, TimeoutPolicy)

    def test_reading_the_budget_does_not_widen_anything(self) -> None:
        # The read side a deployment audits with: the compiled declaration
        # itself, which a caller cites rather than re-deriving.
        assert sandbox_timeout().wall_s == SECTION_5_2_BUDGET
        assert sandbox_timeout().exceeds(OVERRUN_S) is True
        assert sandbox_timeout().exceeds(WITHIN_S) is False

    def test_the_facade_verbs_are_one_call_into_the_module(self) -> None:
        # Thin delegation, asserted by agreement: the component's answer and the
        # module's answer are the same answer, because the component holds no
        # arithmetic of its own — a second spelling would be a second thing to
        # keep in sync.
        law = sandbox_timeout()
        run = timeout_run(elapsed_s=OVERRUN_S, node_id="n-1")
        assert law.check(run).reason is kill_timeout(run, POLICY).reason
        assert law.killed(run) is kill_timeout(run, POLICY).killed
        assert law.require(run).fail_class == kill_timeout(run, POLICY).kill.fail_class

    def test_the_facade_refuses_a_run_it_cannot_read(self) -> None:
        # Through the component rather than a hand-built law, so a composition
        # that carried a stub would fail here rather than at the first dispatch.
        with pytest.raises(SandboxTimeoutError):
            sandbox_timeout().require(object())

    def test_the_component_is_fresh_per_call_and_shares_nothing(self) -> None:
        # Two calls answer the same question because the policy is the same
        # *value*, not because a component is mutated — the facade has no state
        # a caller could drift.
        first = sandbox_timeout()
        second = sandbox_timeout()
        assert first is not second
        assert first.policy == second.policy
        assert first.policy is not second.policy
