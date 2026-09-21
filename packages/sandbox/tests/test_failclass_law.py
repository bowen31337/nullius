"""Feature 168: the fail-class law — one of §9.1's four, from every run.

The sentence this file's subject makes checkable: *"System returns a structured
fail class of ok, timeout, error or tripwire_fail from every sandboxed run."*
Three claims, and the tests below take them in that order.

**"returns" — the class is a value, never a raise.**  §5.2's control table records
its kill as an outcome, §8's ledger carries the same four as ``outcome TEXT NOT
NULL``, §6.1 step 11 charges the trial "even if the node fails.  A failed
evaluation still consumed a hypothesis", and :class:`evaluator.SandboxResult`
states that a failed run "is a value, not an exception".  So the sweep below
asserts the *absence* of an exception across the whole vocabulary — the honest
way to test a law whose subject is an outcome — and only the two classification
refusals raise.

**"from every sandboxed run" — totality.**  This is the file's largest claim and
it is checked as a property of the data rather than sampled: every class the box
records is a key of the table, the table's image is exactly §9.1's four, every
one of the four is reachable, and ``require`` returns an object for *all* of them
— ``ok`` included.  That last is the one place this law's verb differs from its
six siblings', and the tests name the difference rather than leaving a reader to
notice it.

**"structured" — the class carries its provenance.**  A translated class keeps
the spelling it came from, the value refuses to be assembled into a
self-contradicting record, and ``row()`` hands out §9.1's own shape.

**The cross-member spellings are pinned as data rather than imported.**  The
member's one-provenance rule — the box untrusted code is put inside must not
depend on the member that drives it — means this module restates §9.1's four, the
runner's six and ``evaluator``'s ``"timeout"``; this suite is what makes the
restatement safe, importing the neighbours in-function so a sibling's absence
degrades one test rather than collection.

**And the refusals are the feature's own edge.**  An unreadable subject is not
``ok`` (the "absence that reads as a result" failure :mod:`sandbox.transfer`
states) and an unknown class is not ``error`` (feature 163's suite names the rule
from the other side: *"a drifted vocabulary must not become a fabricated
outcome"*).  Both raise, both are greppable, and the tests tell them apart by
reason rather than by class alone.
"""

from __future__ import annotations

import pytest
from _documents import (
    ESCAPE_CLASS,
    LEDGER_FIELD,
    NODE_CLASSES,
    RUNNER_CLASSES,
    SEED_NODE_ID,
    TERMINAL_FIELD,
    UNKNOWN_CLASS,
    node_fail_class_record,
    runner_result,
    timeout_run,
    tripwire_outcome,
)
from sandbox import (
    ERROR_FAIL_CLASS,
    FAIL_CLASS_COMPONENT_NAME,
    FAIL_CLASS_REQUIRED_CODE,
    FAIL_CLASS_TABLE,
    FAIL_CLASS_UNKNOWN_CODE,
    NODE_FAIL_CLASSES,
    OK_FAIL_CLASS,
    SANDBOX_ESCAPE_CLASS,
    SANDBOX_RUNNER_CLASSES,
    SOURCE_CLASSES,
    TIMEOUT_FAIL_CLASS,
    TRIPWIRE_FAIL_CLASS,
    FailClass,
    FailClassDecision,
    FailClassReason,
    SandboxFailClass,
    SandboxFailClassError,
    UnclassifiedRunError,
    UnknownFailClassError,
    classify_fail_class,
    classify_run,
    sandbox_fail_class,
)

#: §9.1's column comment, verbatim: ``fail_class TEXT -- ok | timeout | error |
#: tripwire_fail``.  Spelled here rather than read from
#: :data:`sandbox.NODE_FAIL_CLASSES` so a reordering or a dropped class fails
#: here rather than being followed — the discipline the wall-clock suite applies
#: to its own copy.
SECTION_9_1_VOCABULARY: tuple[str, ...] = ("ok", "timeout", "error", "tripwire_fail")

#: Feature 168's own sentence, quoted because it is the *last* of the stub's
#: words and the one the whole file leans on.
EVERY_RUN: str = "from every sandboxed run"


class TestTheVocabulary:
    """§9.1's four, and the box's vocabulary that maps onto them."""

    def test_the_four_are_section_9_1s_own_spelling_in_its_order(self) -> None:
        # The column comment's declaration order and exactly four classes: a
        # fifth arriving unnoticed would change what every later "how did the
        # trials end?" query could group.
        assert NODE_FAIL_CLASSES == SECTION_9_1_VOCABULARY
        assert NODE_CLASSES == SECTION_9_1_VOCABULARY
        assert len(NODE_FAIL_CLASSES) == 4

    def test_each_of_the_four_is_also_its_own_named_constant(self) -> None:
        # The values a caller branches on, spelled once each rather than as
        # literals at every site.
        assert OK_FAIL_CLASS == "ok"
        assert TIMEOUT_FAIL_CLASS == "timeout"
        assert ERROR_FAIL_CLASS == "error"
        assert TRIPWIRE_FAIL_CLASS == "tripwire_fail"

    def test_the_runner_classes_are_the_evaluators_six(self) -> None:
        # The box's own vocabulary, restated from SandboxResult's docstring.  The
        # suite that makes the restatement safe is this one — the import is
        # in-function so a missing evaluator degrades this test rather than
        # collection.
        from evaluator._debit import _SANDBOX_FAIL_CLASSES

        assert SANDBOX_RUNNER_CLASSES == RUNNER_CLASSES
        assert tuple(_SANDBOX_FAIL_CLASSES) == SANDBOX_RUNNER_CLASSES

    def test_the_seccomp_verdict_is_spelled_the_specs_way(self) -> None:
        # Feature 161's class, with app_spec.xml's underscore — and *not* one of
        # §9.1's four, which is exactly why translating it is this law's job.
        assert SANDBOX_ESCAPE_CLASS == ESCAPE_CLASS == "sandbox_escape"
        assert SANDBOX_ESCAPE_CLASS not in NODE_FAIL_CLASSES

    def test_the_sources_are_the_tables_keys(self) -> None:
        # The read side: what this deployment's box is known to report.  A
        # caller asking that question reads a value rather than re-deriving it.
        assert SOURCE_CLASSES == tuple(FAIL_CLASS_TABLE)
        for cls in RUNNER_CLASSES + NODE_CLASSES + (ESCAPE_CLASS,):
            assert cls in SOURCE_CLASSES, cls

    def test_the_component_name_is_the_categorys_seventh(self) -> None:
        # The registry replaces a name's earlier registration, so this must be
        # its own name and not any of the other six seats'.
        assert FAIL_CLASS_COMPONENT_NAME == "sandbox-failclass"
        assert FAIL_CLASS_COMPONENT_NAME not in {
            "sandbox",
            "sandbox-imports",
            "sandbox-transfer",
            "sandbox-seed",
            "sandbox-threads",
            "sandbox-timeout",
        }


class TestTheTableIsTheFeature:
    """Totality, checked as a property of the data rather than sampled."""

    def test_every_class_the_box_reports_is_a_key(self) -> None:
        # The "every sandboxed run" half: no class the runner records and no
        # seccomp verdict can arrive without a mapping to answer it.
        for cls in RUNNER_CLASSES:
            assert cls in FAIL_CLASS_TABLE, cls
        assert ESCAPE_CLASS in FAIL_CLASS_TABLE
        for cls in NODE_CLASSES:
            assert cls in FAIL_CLASS_TABLE, cls

    def test_the_tables_image_is_exactly_section_9_1s_four(self) -> None:
        # The other direction: nothing translated can come out as a class the
        # column does not have.  A fifth value in the image would be a stored
        # outcome §8's ledger cannot group.
        assert set(FAIL_CLASS_TABLE.values()) == set(SECTION_9_1_VOCABULARY)

    def test_every_one_of_the_four_is_reachable(self) -> None:
        # Totality has a second half a one-directional check would miss: a
        # vocabulary three of whose four values could never come back would pass
        # "every source maps into the four" and still fail the feature's
        # sentence.
        reachable = set(FAIL_CLASS_TABLE.values())
        for cls in SECTION_9_1_VOCABULARY:
            assert cls in reachable, cls

    def test_the_four_pass_through_untouched(self) -> None:
        # A table that renamed one of §9.1's own four would be a law disagreeing
        # with the column it exists to fill — and `timeout` renaming would be a
        # second spelling of feature 163's class.
        for cls in SECTION_9_1_VOCABULARY:
            assert FAIL_CLASS_TABLE[cls] == cls
            assert classify_fail_class(cls) == cls

    def test_the_runner_classes_collapse_where_section_eight_says(self) -> None:
        # `timeout` is §8's own word and stays; the other five are "failed any
        # other way".  The finer vocabulary is the runner's to keep — §9.1's
        # column has four values and *why it crashed* belongs in the row's
        # detail.
        assert FAIL_CLASS_TABLE["timeout"] == TIMEOUT_FAIL_CLASS
        for cls in ("oom", "crash", "violation", "payload", "empty"):
            assert FAIL_CLASS_TABLE[cls] == ERROR_FAIL_CLASS, cls

    def test_the_seccomp_verdict_is_translated_not_refused(self) -> None:
        # Feature 161's handoff.  Feature 163's suite names this law as the owner
        # of the translation — "re-labelling it is feature 168's job" — because
        # 161's verdict is a genuine seccomp finding and *not* one of §9.1's four.
        assert FAIL_CLASS_TABLE[ESCAPE_CLASS] == ERROR_FAIL_CLASS

    def test_the_table_cannot_be_widened_by_a_caller(self) -> None:
        # Read-only: a caller writing into the mapping it was handed would be a
        # fifth class arriving without a test noticing.
        with pytest.raises(TypeError):
            FAIL_CLASS_TABLE["new_class"] = ERROR_FAIL_CLASS  # type: ignore[index]


class TestTheClassifier:
    """One place a class is read, so nothing can disagree about what one is."""

    def test_a_known_class_becomes_its_section_9_1_spelling(self) -> None:
        assert classify_fail_class("oom") == ERROR_FAIL_CLASS
        assert classify_fail_class("ok") == OK_FAIL_CLASS
        assert classify_fail_class(ESCAPE_CLASS) == ERROR_FAIL_CLASS

    def test_the_match_is_exact_rather_than_forgiving(self) -> None:
        # Stripping or case-folding here would make this law the place a
        # malformed writer's drift became invisible: the class would be recorded
        # right and the writer would go on writing wrong.
        assert classify_fail_class(UNKNOWN_CLASS) is None
        assert classify_fail_class("timeout ") is None
        assert classify_fail_class("TIMEOUT") is None

    def test_a_value_that_is_not_a_class_is_none(self) -> None:
        # `None` for everything unplaceable, because the *caller* decides which
        # refusal that earns — an unreadable subject and a drifted vocabulary
        # have different repairs.
        for value in (None, 7, True, b"crash", "", [], {}):
            assert classify_fail_class(value) is None, value


class TestEveryRunGetsAClass:
    """The feature's largest claim, as the absence of an exception."""

    def test_every_source_classifies_without_raising(self) -> None:
        # The sweep across the whole vocabulary.  A law that raised for any of
        # these would turn one hung or crashed signal into a crashed evaluator
        # over thousands of unattended candidates.
        for source in SOURCE_CLASSES:
            decision = classify_run(source)
            assert decision.classified is True, source
            assert decision.refused is False, source
            assert decision.fail_class.fail_class in SECTION_9_1_VOCABULARY, source

    def test_require_returns_an_object_for_every_source_including_ok(self) -> None:
        # The one place this law's verb shape differs from its six siblings':
        # «ok» is one of the four the sentence names, so there is no
        # nothing-to-return case and `require` never yields None.  This *is*
        # "from every sandboxed run", made operational.
        for source in SOURCE_CLASSES:
            value = classify_run(source).require()
            assert isinstance(value, FailClass), source
            assert value.fail_class in SECTION_9_1_VOCABULARY, source

    def test_the_runner_result_classifies_by_its_own_field(self) -> None:
        # The object the box actually hands back — the path an assembled system
        # takes, rather than a bare class string.
        for fail_class, expected in (
            ("crash", ERROR_FAIL_CLASS),
            ("timeout", TIMEOUT_FAIL_CLASS),
            ("oom", ERROR_FAIL_CLASS),
            ("empty", ERROR_FAIL_CLASS),
        ):
            decision = classify_run(runner_result(fail_class=fail_class))
            assert decision.fail_class.fail_class == expected, fail_class
            # The result names no node — see the cross-member test below.
            assert decision.fail_class.node_id == ""

    def test_a_scored_run_is_ok(self) -> None:
        # SandboxResult's own declared success: no class *and* no problem.  The
        # rule is restated here as data and pinned against the evaluator below.
        decision = classify_run(runner_result(fail_class=None))
        assert decision.classified is True
        assert decision.fail_class.fail_class == OK_FAIL_CLASS
        assert decision.fail_class.ok is True
        assert decision.fail_class.translated is False

    def test_a_refused_contract_is_an_error(self) -> None:
        # Problems and no class: the signal ran and returned something the
        # contract rejected — §8's "failed any other way", not a resource
        # failure and not `ok`.
        decision = classify_run(runner_result(fail_class=None, problems=["wrong length"]))
        assert decision.fail_class.fail_class == ERROR_FAIL_CLASS
        assert decision.fail_class.ok is False
        assert "contract" in decision.fail_class.detail

    def test_a_class_beside_problems_still_governs(self) -> None:
        # A result carrying both is not "problems without a class": the recorded
        # class is the run's own statement about how it ended.
        decision = classify_run(
            runner_result(fail_class="timeout", problems=["wrong length"])
        )
        assert decision.fail_class.fail_class == TIMEOUT_FAIL_CLASS

    def test_feature_163s_kill_classifies_through_the_same_reader(self) -> None:
        # Feature 163 hands off: its kill carries `fail_class` and this law reads
        # it without a second reader — one fact, one translation.
        from sandbox import committed_timeout_policy, kill_timeout

        kill = kill_timeout(timeout_run(elapsed_s=90.0), committed_timeout_policy()).kill
        decision = classify_run(kill)
        assert decision.fail_class.fail_class == TIMEOUT_FAIL_CLASS
        assert decision.fail_class.translated is False

    def test_a_tripwire_verdict_classifies_by_its_outcome(self) -> None:
        # Step 10's answer, arriving under `outcome` rather than §9.1's
        # `fail_class` — the second of the three spellings the one reader reads.
        failed = classify_run(tripwire_outcome(rejected=True))
        assert failed.fail_class.fail_class == TRIPWIRE_FAIL_CLASS
        clean = classify_run(tripwire_outcome(rejected=False))
        assert clean.fail_class.fail_class == OK_FAIL_CLASS

    def test_every_class_field_spelling_is_read(self) -> None:
        # §9.1's column, §8's ledger and the store rows' `terminal_class`: three
        # names for one fact, and a reader that dropped one of them would fail
        # silently on whichever row shape happened to use it.
        for field in ("fail_class", LEDGER_FIELD, TERMINAL_FIELD):
            record = node_fail_class_record(fail_class="tripwire_fail", field=field)
            decision = classify_run(record)
            assert decision.fail_class.fail_class == TRIPWIRE_FAIL_CLASS, field

    def test_a_null_class_beside_a_real_one_still_decides(self) -> None:
        # The "a real class beside a null one still decides" rule feature 163
        # states for its own comparison: a null sibling must not mask the real
        # class into an unreadable subject.
        record = {
            "node_id": SEED_NODE_ID,
            "fail_class": None,
            LEDGER_FIELD: TRIPWIRE_FAIL_CLASS,
        }
        assert classify_run(record).fail_class.fail_class == TRIPWIRE_FAIL_CLASS

    def test_an_unevaluated_row_is_not_read_as_ok(self) -> None:
        # §9.1's column is nullable, so a row straight from a driver carries the
        # *key* with a null value.  A null class with no `problems` field says
        # nothing about how the run ended, and reading it as a scored run would
        # be a failed node counted as a successful one.
        record = {"node_id": SEED_NODE_ID, "fail_class": None}
        decision = classify_run(record)
        assert decision.refused is True
        assert decision.reason is FailClassReason.UNREADABLE_SUBJECT


class TestTheRaisedFailure:
    """A raised exception is ``error`` — including a raised ``TimeoutError``."""

    def test_a_raised_exception_is_an_error(self) -> None:
        for raised in (RuntimeError("boom"), ValueError("bad"), OSError("io")):
            decision = classify_run(raised)
            assert decision.fail_class.fail_class == ERROR_FAIL_CLASS, raised
            assert type(raised).__name__ in decision.fail_class.detail

    def test_a_raised_timeout_is_an_error_and_not_a_timeout(self) -> None:
        # The sharpest judgement in the law, and it is the evaluator's own: "the
        # sandbox records its kills as values, never exceptions, so a timeout
        # that arrives raised is a host-side failure wearing a familiar name."
        # Reading it as a wall-clock kill would count a bug among the trials that
        # ran out of time.
        for raised in (TimeoutError("wall"), TimeoutError(), ):
            decision = classify_run(raised)
            assert decision.fail_class.fail_class == ERROR_FAIL_CLASS
            assert decision.fail_class.fail_class != TIMEOUT_FAIL_CLASS

    def test_the_evaluators_classifier_agrees(self) -> None:
        # The restatement made safe: evaluator.failure_outcome draws the same
        # line from the other side of the seam.
        from evaluator import failure_outcome

        assert failure_outcome(TimeoutError("wall")) == ERROR_FAIL_CLASS
        assert failure_outcome("timeout") == TIMEOUT_FAIL_CLASS
        assert failure_outcome("oom") == ERROR_FAIL_CLASS

    def test_the_classifications_agree_class_for_class(self) -> None:
        # Every class the runner records, classified by both laws, must land on
        # the same one of §8's four — a disagreement here is a stored outcome
        # that depends on which side of the pipeline read it.
        from evaluator import failure_outcome

        for cls in RUNNER_CLASSES:
            ours = classify_run(cls).fail_class.fail_class
            assert ours == failure_outcome(cls), cls


class TestTheStructure:
    """The feature's second word: the class carries what produced it."""

    def test_a_translated_class_keeps_its_source(self) -> None:
        # A bare "error" says a run failed; *as what* is what tells an operator
        # whether the box crashed, exhausted memory or escaped a seccomp filter —
        # and the finer class is exactly what §9.1's column has no room for.
        decision = classify_run("oom")
        assert decision.fail_class.fail_class == ERROR_FAIL_CLASS
        assert decision.fail_class.source == "oom"
        assert decision.fail_class.translated is True

    def test_a_pass_through_claims_no_provenance(self) -> None:
        # Nothing was decided for §9.1's own four, and claiming a translation
        # would be inventing one.
        decision = classify_run("timeout")
        assert decision.fail_class.source is None
        assert decision.fail_class.translated is False

    def test_the_value_carries_the_node_and_the_component(self) -> None:
        decision = classify_run(
            runner_result(fail_class="crash"), node_id="n-42", component="signal-sandbox"
        )
        assert decision.fail_class.node_id == "n-42"
        assert decision.fail_class.component == "signal-sandbox"

    def test_the_row_is_section_9_1s_shape_and_is_fresh_per_call(self) -> None:
        # The shape a caller writes down, and a fresh dict each time: the suite's
        # fresh-object rule, so one test's drift cannot become another's premise.
        # The node is supplied by the *caller* — SandboxResult names no node, so
        # the dispatcher that knows which one it ran is the one that says.
        value = classify_run("crash", node_id=SEED_NODE_ID).fail_class
        row = value.row()
        assert row["fail_class"] == ERROR_FAIL_CLASS
        assert row["source"] == "crash"
        assert row["node_id"] == SEED_NODE_ID
        assert value.row() is not row
        assert value.row() == row

    def test_a_pass_through_row_omits_the_source(self) -> None:
        # §9.1's column is the class; the provenance is extra, and a caller
        # writing this mapping into a row should not have to decide whether a
        # null column is the store's shape or this law's.
        row = classify_run("ok").fail_class.row()
        assert "source" not in row
        assert row["fail_class"] == OK_FAIL_CLASS

    def test_reclassifying_the_laws_own_value_is_idempotent(self) -> None:
        # A caller that classifies twice gets the same class — the word *and* the
        # provenance, which a naive re-read of `.fail_class` would lose.
        first = classify_run("sandbox_escape").fail_class
        again = classify_run(first).fail_class
        assert again.fail_class == first.fail_class
        assert again.source == first.source

    def test_the_value_refuses_a_word_outside_the_four(self) -> None:
        with pytest.raises(SandboxFailClassError):
            FailClass("boom")

    def test_the_value_refuses_a_source_it_does_not_know(self) -> None:
        with pytest.raises(SandboxFailClassError):
            FailClass(ERROR_FAIL_CLASS, source="not_a_class")

    def test_the_value_refuses_a_record_that_contradicts_itself(self) -> None:
        # `FailClass("error", source="timeout")` is a record claiming a host-side
        # error and a wall-clock kill at once: a reader of §8's column would have
        # no way to tell which the run actually was.
        with pytest.raises(SandboxFailClassError) as raised:
            FailClass(ERROR_FAIL_CLASS, source=TIMEOUT_FAIL_CLASS)
        assert "timeout" in str(raised.value)

    def test_the_value_accepts_a_source_that_agrees(self) -> None:
        value = FailClass(ERROR_FAIL_CLASS, source="crash")
        assert value.source == "crash"
        assert value.translated is True


class TestTheRefusalsAreToldApart:
    """Two refusals, two repairs, two greppable codes."""

    def test_a_bare_object_is_unreadable(self) -> None:
        decision = classify_run(object())
        assert decision.refused is True
        assert decision.reason is FailClassReason.UNREADABLE_SUBJECT
        assert decision.classified is False
        assert decision.fail_class is None

    def test_a_null_class_with_no_problems_is_unreadable(self) -> None:
        # The distinction the whole reader turns on: `None` under the column is
        # "nothing written yet", not "errored".
        decision = classify_run({"node_id": SEED_NODE_ID, "fail_class": None})
        assert decision.reason is FailClassReason.UNREADABLE_SUBJECT

    def test_an_unknown_class_is_its_own_reason(self) -> None:
        # Kept apart from the last one because the repair is on the *other* side
        # of the seam — the box wrote a spelling this law has never seen.
        decision = classify_run(UNKNOWN_CLASS)
        assert decision.refused is True
        assert decision.reason is FailClassReason.UNKNOWN_CLASS
        assert UNKNOWN_CLASS in decision.detail

    def test_the_two_refusals_carry_different_greppable_codes(self) -> None:
        assert classify_run(object()).detail.startswith(FAIL_CLASS_REQUIRED_CODE)
        assert classify_run(UNKNOWN_CLASS).detail.startswith(FAIL_CLASS_UNKNOWN_CODE)
        assert FAIL_CLASS_REQUIRED_CODE == "fail_class_required"
        assert FAIL_CLASS_UNKNOWN_CODE == "fail_class_unknown"

    def test_the_two_refusals_raise_different_errors(self) -> None:
        # Both are SandboxFailClassError, so a caller with one `except` catches
        # the feature — and the two subclasses are siblings rather than one under
        # the other, because the repairs are on opposite sides of the seam.
        with pytest.raises(UnclassifiedRunError):
            classify_run(object()).require()
        with pytest.raises(UnknownFailClassError):
            classify_run(UNKNOWN_CLASS).require()
        assert issubclass(UnclassifiedRunError, SandboxFailClassError)
        assert issubclass(UnknownFailClassError, SandboxFailClassError)
        assert not issubclass(UnknownFailClassError, UnclassifiedRunError)

    def test_an_unknown_class_is_not_folded_into_error(self) -> None:
        # Feature 163's suite states the rule from the other side: "a drifted
        # vocabulary must not become a fabricated outcome."  Folding a misspelt
        # `TimeOut` into `error` would read every wall-clock kill as a generic
        # crash and send an operator after a fault that is not there.
        assert classify_fail_class(UNKNOWN_CLASS) is None
        assert classify_run(UNKNOWN_CLASS).fail_class is None

    def test_an_unreadable_subject_is_not_read_as_ok(self) -> None:
        # The "absence that reads as a result" failure this member's transfer law
        # states: neither `ok` nor `error` may be fabricated from silence.
        decision = classify_run(object())
        assert decision.fail_class is None
        assert not hasattr(decision, "fail_class") or decision.fail_class is None

    def test_the_refusal_sentence_names_what_it_looked_for(self) -> None:
        # An operator repairing a writer needs to know which column is missing.
        detail = classify_run(object()).detail
        for field in ("fail_class", LEDGER_FIELD, TERMINAL_FIELD):
            assert field in detail, field


class TestTheFacade:
    """The composed value: thin delegation, and nothing held at all."""

    def test_the_component_carries_no_state(self) -> None:
        # The first law in this member that can say this: every sibling holds
        # something — a mechanism, an allowlist, a format, a salt, caps, a budget
        # — and this one's subject is a vocabulary and a mapping, neither of
        # which is a deployment's to set.
        law = sandbox_fail_class()
        assert isinstance(law, SandboxFailClass)
        assert SandboxFailClass.__slots__ == ()

    def test_the_read_side_answers_both_questions(self) -> None:
        # `classes()` is what gets stored; `sources()` is what gets accepted.  A
        # deployment checks the two against what its runner actually writes.
        law = sandbox_fail_class()
        assert law.classes() == SECTION_9_1_VOCABULARY
        assert set(law.sources()) >= set(RUNNER_CLASSES)

    def test_the_facade_verbs_are_one_call_into_the_module(self) -> None:
        # Thin delegation, asserted by agreement: a second implementation of the
        # table or the reader would be a second thing to keep in sync.
        law = sandbox_fail_class()
        run = runner_result(fail_class="oom")
        assert law.check(run).fail_class.fail_class == classify_run(run).fail_class.fail_class
        assert law.require(run).source == classify_run(run).fail_class.source

    def test_the_facade_returns_a_class_for_ok_too(self) -> None:
        # The difference from all six siblings, through the component rather than
        # a module function: a composition carrying a stub whose `require` passed
        # None through for `ok` would pass every wiring test and fail here.
        law = sandbox_fail_class()
        value = law.require(runner_result(fail_class=None))
        assert isinstance(value, FailClass)
        assert value.ok is True

    def test_the_component_is_fresh_per_call_and_holds_nothing(self) -> None:
        first = sandbox_fail_class()
        second = sandbox_fail_class()
        assert first is not second
        assert first.classes() == second.classes()

    def test_a_classified_decision_with_no_class_refuses_rather_than_returning_none(
        self,
    ) -> None:
        # The invariant that makes "returns a class for every run" true rather
        # than usually true: *classified* and *a class is carried* are the same
        # fact, and a decision assembled by hand that broke it would hand a
        # caller a bare ``None`` from a verb whose whole contract is that it
        # cannot.  Checked rather than asserted, because ``python -O`` strips an
        # ``assert``.
        hand_built = FailClassDecision(
            reason=FailClassReason.CLASSIFIED, detail="by hand"
        )
        with pytest.raises(SandboxFailClassError) as raised:
            hand_built.require()
        assert str(raised.value).startswith(FAIL_CLASS_REQUIRED_CODE)

    def test_the_decision_reports_classified_and_refused_for_themselves(self) -> None:
        # A caller that read a bare falsy as "the run was fine" would treat an
        # unreadable subject as a clean run.
        classified = classify_run("crash")
        refused = classify_run(object())
        assert isinstance(classified, FailClassDecision)
        assert (classified.classified, classified.refused) == (True, False)
        assert (refused.classified, refused.refused) == (False, True)


class TestTheCrossMemberSpellings:
    """The restatements, held to the neighbours by import — one place each."""

    def test_the_four_are_the_ledgers_four(self) -> None:
        from ledger import OUTCOMES

        assert tuple(OUTCOMES) == SECTION_9_1_VOCABULARY
        assert NODE_FAIL_CLASSES == tuple(OUTCOMES)

    def test_the_four_are_the_evaluators_trial_outcomes(self) -> None:
        from evaluator import TRIAL_OUTCOMES

        assert tuple(TRIAL_OUTCOMES) == SECTION_9_1_VOCABULARY

    def test_the_tripwire_verdicts_two_are_inside_the_four(self) -> None:
        # Step 10 states only two of the four — `ok` and `tripwire_fail` — and
        # both must be values this law can carry, or a quarantined subtree would
        # have no class to record.
        from tripwires.time_shuffle import TRIPWIRE_OUTCOMES

        assert set(TRIPWIRE_OUTCOMES) <= set(NODE_FAIL_CLASSES)
        assert TRIPWIRE_FAIL_CLASS in TRIPWIRE_OUTCOMES

    def test_the_evaluators_result_fields_are_the_ones_we_read(self) -> None:
        # The reader keys on field *names*, so a rename on the evaluator's side
        # would leave this law reading silence — and silence is refused, not
        # guessed — but the failure would surface at the pipeline rather than
        # here.  This is where it surfaces.
        #
        # `fail_class` and `problems` are read; `detail` is what the law's own
        # sentence quotes back; and `seed` is deliberately *not* read — a seed is
        # not a class, feature 165 owns it, and a reader that swept every field
        # would find one there.
        from evaluator import SandboxResult

        fields = set(SandboxResult.__dataclass_fields__)
        assert fields == {
            "scores",
            "problems",
            "fail_class",
            "detail",
            "seed",
            "contract_version",
        }
        for field in ("fail_class", "problems", "detail"):
            assert field in fields, field

    def test_the_result_names_no_node_and_that_is_the_callers_to_supply(self) -> None:
        # The finding this suite made: `SandboxResult` is the outcome of one
        # signal execution and carries no node identity — the dispatcher that ran
        # it knows which node it belonged to.  So the law's node comes from the
        # *caller*, which is what `classify_run`'s own parameter is for, and a
        # reader that looked for one on the result would find silence.
        from evaluator import SandboxResult

        assert "node_id" not in SandboxResult.__dataclass_fields__
        assert "component" not in SandboxResult.__dataclass_fields__
        decision = classify_run(runner_result(fail_class="crash"), node_id=SEED_NODE_ID)
        assert decision.fail_class.node_id == SEED_NODE_ID

    def test_every_class_the_evaluator_records_is_in_the_table(self) -> None:
        # Both laws are total over the same vocabulary; if the evaluator grew a
        # seventh sandbox class, this law's table would be incomplete and this is
        # where that shows — at the suite rather than at the first node that
        # crashed in the new way.
        from evaluator._debit import _SANDBOX_FAIL_CLASSES

        for cls in _SANDBOX_FAIL_CLASSES:
            assert cls in FAIL_CLASS_TABLE, cls
