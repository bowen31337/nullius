"""Feature 209's law: the flawed mechanism, the located bug, the retry decision.

app_spec.xml, "Hypothesis Authoring Agent", feature 209: *Agent distinguishes a
flawed core mechanism from a sound idea undermined by a located bug, which
returns a retry decision for only the second case.*  Four contracts, all held
from the side this member owns:

* **the distinction** — a defect resolves in the proposal's own source or it
  does not, and ``locate_defect`` answers the first as a
  :class:`~signal_agent.LocatedDefect` and the second as ``None``.  The
  position must be one the parse tree *occupies* and the symbol is *derived*
  from the tree, so a caller cannot assert a location it did not find;

* **the retry for only the second case** — ``retry`` is computed from the
  reason, ``True`` for exactly one of the three, and the two refusals have
  different repairs.  This is feature 209's second clause and the reason the
  law returns a value rather than raising: a driver deciding *whether* to spend
  a trial charge must be able to branch without an exception in the way;

* **located in code rather than guessed from the write-up** — the clause that
  makes the feature more than a taxonomy, and here it is a *provable* property
  rather than a promise: no complaint, however well argued, moves ``retry``
  from ``False`` to ``True``.  The suite tests it by holding the source fixed
  and varying only the prose, and then by holding the prose fixed and varying
  only the source;

* **the error vocabulary** — the member gains exactly one class for feature 209
  and it is the *refusal*, and it is a **sibling** of
  :class:`~signal_agent.errors.AgentSourceError` rather than a subclass, so a
  caller's pre-existing ``except AgentSourceError:`` handler — whose repair is
  *re-prompt the agent* — cannot catch "the mechanism is flawed" and spend
  budget on the branch the diagnosis just closed.  That asymmetry is asserted
  here against the three refusals that *do* subclass, because it is the one
  inheritance decision in the member that could be "tidied" into being wrong.

The proposals every claim is made about live at module scope rather than in
fixtures: they are *text*, and several assertions are about the text itself
(``source_line`` is the proposal verbatim; the source is returned unmodified),
so a fixture that rebuilt them per test would make "the same source" a claim
about two constructions rather than about one string.  The same reasoning puts
``test_themes.py``'s slugs and ``test_anti_convergence.py``'s pair at module
scope there.
"""

from __future__ import annotations

import pytest
import signal_agent as member
from signal_agent import (
    SIGNAL_SOURCE_FILENAME,
    DiagnosisReason,
    DiagnosisVerdict,
    FlawedMechanismError,
    LocatedDefect,
    MechanismDiagnosis,
    first_defect,
    locate_defect,
    mechanism_diagnosis,
)

#: A conforming proposal, and the parse tree it has: ``signal`` is defined at
#: line 1, its body at line 2, and ``rolling_mean`` is called on line 2.
_SOUND = (
    "def signal(ctx, seed):\n"
    "    return ctx.close.rolling_mean(20)\n"
)

#: The same proposal with a helper, so a position inside it resolves to a
#: symbol that is not ``signal`` — the claim the derived symbol exists for.
_WITH_HELPER = (
    "def _mean(window):\n"
    "    return window.close.rolling_mean(20)\n"
    "\n"
    "\n"
    "def signal(ctx, seed):\n"
    "    return _mean(ctx)\n"
)

#: A proposal that does not parse: the colon after the parameter list is
#: missing, so the parser stops on line 1.
_BROKEN = (
    "def signal(ctx, seed)\n"
    "    return ctx.close.rolling_mean(20)\n"
)

#: A proposal whose *last* line does not parse, so the parser's own position is
#: not line 1 — which is what makes "the parser's answer is the anchor" a claim
#: about the parser rather than about the common case.
_BROKEN_LATE = (
    "def signal(ctx, seed):\n"
    "    value = ctx.close.rolling_mean(20)\n"
    "    return value if value > 0 else\n"
)

#: The failure sentences a deployment would have in hand: what the contract
#: validator reports for a signature it refuses, what a sandbox run reports for
#: a return of the wrong shape, and one that reads like a *very* good argument
#: for retrying.  None of them names a position in the source, and that is the
#: point — the third exists to show that argument quality buys nothing.
_COMPLAINTS = [
    "signal source does not compile: expected ':'",
    "signal returned a Series of 12 values for a universe of 20",
    (
        "the mechanism is sound; only the lookback constant is mistyped, "
        "so the branch should be retried with 60 in place of 20"
    ),
]


@pytest.fixture
def law() -> MechanismDiagnosis:
    """Feature 209's law, built directly rather than reached off a composed app.

    A test of the *law* should not depend on the factory having scanned
    anything; the component tests reach the composed one separately, which is
    the discipline ``test_authoring.py`` states for feature 205's law.  This one
    reads no committed artifact and no environment, so building it here is the
    whole of its construction.
    """
    return mechanism_diagnosis()


# -- The distinction: a position in the code, or nothing -----------------------


def test_a_line_the_parse_tree_occupies_resolves() -> None:
    # The distinguishing act.  Line 2 is where the body begins, so it is a place
    # a defect can be located in code.
    defect = locate_defect(_SOUND, 2)
    assert isinstance(defect, LocatedDefect)
    assert defect.line == 2
    # The proposal's own text, verbatim — this is what a retry prompt quotes,
    # and a verbatim copy is asserted against the source rather than trusted.
    assert defect.source_line == _SOUND.splitlines()[1]
    # The symbol is derived from the tree, not accepted from a caller.
    assert defect.symbol == "signal"


def test_the_symbol_is_derived_from_the_tree_not_taken_from_the_caller() -> None:
    # Line 2 sits inside ``_mean``, so that is what the defect names — even
    # though a caller asking about a signal would much rather it said
    # ``signal``.  A law that let the caller assert the symbol would produce a
    # located bug located in the wrong function, which is §C3's guess arriving
    # one level down.
    assert locate_defect(_WITH_HELPER, 2).symbol == "_mean"  # type: ignore[union-attr]
    assert locate_defect(_WITH_HELPER, 6).symbol == "signal"


def test_a_position_in_no_definition_names_the_module() -> None:
    # A module-level failure has no enclosing function, and the answer says so
    # rather than inventing a name — the same symbol the parser's own defects
    # carry, so the two paths spell it once.
    source = "LOOKBACK = 20\n\n\ndef signal(ctx, seed):\n    return LOOKBACK\n"
    assert locate_defect(source, 1).symbol == member.MODULE_SYMBOL  # type: ignore[union-attr]


def test_a_line_no_node_begins_on_does_not_resolve() -> None:
    # A blank line, a comment, and a line past the end.  A function *spans* its
    # blank lines, so a claim that the defect is "in the function" is not a
    # claim that there is code at that line — and the feature's whole subject is
    # a location *in code*.
    source = (
        "def signal(ctx, seed):\n"
        "\n"
        "    # a comment about the lookback\n"
        "    return ctx.close.rolling_mean(20)\n"
    )
    assert locate_defect(source, 2) is None  # the blank line
    assert locate_defect(source, 3) is None  # the comment
    assert locate_defect(source, 4) is not None  # the return
    assert locate_defect(source, 99) is None  # past the end


def test_a_position_that_is_not_an_integer_does_not_resolve() -> None:
    # A position parsed out of prose is exactly the guess §C3 names, so the
    # floats, the strings and the None are all refused rather than coerced.
    for claimed in ("2", "line 2", 2.0, None, [2], {"line": 2}):
        assert locate_defect(_SOUND, claimed) is None, claimed


def test_a_boolean_is_not_a_line_number() -> None:
    # ``bool`` is an ``int`` subclass, so ``True`` would otherwise resolve as
    # line 1 — the affinity trap this workspace's SQLite layer guards and
    # feature 210 guards for its own reason, guarded here because a boolean is
    # not a position and a law that read one would hand a caller a defect it
    # never located.
    assert locate_defect(_SOUND, True) is None
    assert locate_defect(_SOUND, False) is None


def test_a_proposal_that_is_not_source_has_no_position() -> None:
    for not_source in (None, 42, ["def signal"], ""):
        assert locate_defect(not_source, 1) is None, not_source


def test_a_reported_problem_rides_along_and_is_not_the_anchor() -> None:
    # The complaint is carried for the retry prompt and is *not* what resolves:
    # the same line resolves with and without one.
    problem = "zero division in the rolling mean"
    defect = locate_defect(_SOUND, 2, 5, problem)
    assert defect.problem == problem and defect.column == 5
    assert locate_defect(_SOUND, 2) is not None


def test_an_impossible_column_is_normalised_rather_than_refused() -> None:
    # The parser's own offset is occasionally past the end of its line, and a
    # law that refused the parser's answer would refuse the one position that is
    # authoritative by construction.  The line is what is verified.
    for column in (0, -3, "x", None, True):
        defect = locate_defect(_SOUND, 2, column)
        assert defect is not None and defect.column == 1, column


# -- The parser's own position: the one location that is derived --------------


def test_a_source_that_does_not_parse_hands_over_the_parsers_own_position() -> None:
    defect = first_defect(_BROKEN)
    assert isinstance(defect, LocatedDefect)
    assert defect.line == 1
    # The parser's own message, not a sentence written here.
    assert defect.problem
    assert "syntax" in defect.problem.lower() or ":" in defect.problem


def test_the_parsers_position_is_the_parsers_and_not_the_first_line() -> None:
    # ``_BROKEN_LATE`` parses fine for two lines and stops on the third, so an
    # implementation that answered "line 1" would pass the test above and fail
    # this one.  That is the whole reason this second fixture exists.
    defect = first_defect(_BROKEN_LATE)
    assert defect is not None and defect.line == 3


def test_a_source_that_parses_has_no_defect_at_all() -> None:
    # The feature's most important default: the code is what the agent meant to
    # write, so the failure came from elsewhere and there is no bug in the
    # source to point a targeted change at.  What that leaves is the mechanism.
    assert first_defect(_SOUND) is None
    assert first_defect(_WITH_HELPER) is None
    assert first_defect("") is None
    assert first_defect(None) is None


def test_the_parser_path_never_raises_and_always_answers_in_range() -> None:
    # A parser whose line is one past the end of a truncated source is the case
    # this clamps, and it must answer rather than raise: the caller here is a
    # driver that already has a failure and is asking where it is.
    truncated = "def signal(ctx, seed):\n    return ("
    defect = first_defect(truncated)
    assert defect is not None
    assert 1 <= defect.line <= len(truncated.splitlines())
    assert defect.source_line == truncated.splitlines()[defect.line - 1]


# -- The retry decision, computed from the reason -----------------------------


def test_retry_is_true_for_exactly_one_of_the_three_reasons() -> None:
    # Feature 209's second clause, as a property of the vocabulary rather than
    # of any one call: ``retry`` is computed from the reason, so the two cannot
    # disagree, and the split is one-of-three.
    reasons = list(DiagnosisReason)
    assert [r for r in reasons if r is DiagnosisReason.RETRYABLE] == [
        DiagnosisReason.RETRYABLE
    ]
    for reason in reasons:
        verdict = DiagnosisVerdict(reason=reason, detail="x")
        assert verdict.retry is (reason is DiagnosisReason.RETRYABLE), reason


def test_a_located_bug_is_retried_and_carries_the_defect(law: MechanismDiagnosis) -> None:
    verdict = law.diagnose(_BROKEN, _COMPLAINTS)
    assert verdict.retry is True
    assert verdict.reason is DiagnosisReason.RETRYABLE
    assert isinstance(verdict.defect, LocatedDefect)
    assert verdict.detail.startswith("located_bug")
    # The complaints are carried verbatim for the retry prompt, and the detail
    # names the location the prompt must quote.
    assert verdict.complaints == tuple(_COMPLAINTS)
    assert f"{SIGNAL_SOURCE_FILENAME}:{verdict.defect.line}" in verdict.detail


def test_a_flawed_mechanism_is_not_retried_and_names_the_complaints(
    law: MechanismDiagnosis,
) -> None:
    verdict = law.diagnose(_SOUND, _COMPLAINTS)
    assert verdict.retry is False
    assert verdict.reason is DiagnosisReason.FLAWED_MECHANISM
    assert verdict.defect is None
    assert verdict.detail.startswith("flawed_mechanism")
    # "not worth retrying" is not actionable; the reported failures are.
    for complaint in _COMPLAINTS:
        assert complaint in verdict.detail
    assert "not worth retrying" in verdict.detail


def test_a_branch_that_did_not_fail_gets_its_own_refusal(
    law: MechanismDiagnosis,
) -> None:
    # Its own reason rather than a spelling of the flawed-mechanism case: a
    # driver asking whether to retry something that never failed has a bug at
    # the call site, and an operator looking for a mechanism to abandon would be
    # looking in the wrong place.
    verdict = law.diagnose(_SOUND)
    assert verdict.retry is False
    assert verdict.reason is DiagnosisReason.NOT_A_DIAGNOSIS
    assert verdict.complaints == ()
    assert verdict.detail.startswith("not_a_diagnosis")
    assert verdict.detail != law.diagnose(_SOUND, _COMPLAINTS).detail


def test_something_that_is_not_a_proposal_gets_the_same_callsite_refusal(
    law: MechanismDiagnosis,
) -> None:
    for not_source in (None, 42, "", "   ", {"code": "..."}):
        verdict = law.diagnose(not_source, _COMPLAINTS)
        assert verdict.reason is DiagnosisReason.NOT_A_DIAGNOSIS, not_source
        assert verdict.retry is False
        assert verdict.detail.startswith("not_a_diagnosis")


def test_the_reason_is_the_token_its_own_detail_opens_with(
    law: MechanismDiagnosis,
) -> None:
    # The audit vocabulary's one structural promise: a log line is greppable
    # without a lookup table.  For the two refusals the value *is* the code; for
    # the admission the two deliberately differ, the same asymmetry feature
    # 210's ``NOVEL`` has against ``NOVEL_CODE``.
    assert law.diagnose(_SOUND, _COMPLAINTS).reason == "flawed_mechanism"
    assert law.diagnose(_SOUND).reason == "not_a_diagnosis"
    assert law.diagnose(_BROKEN).reason == "retryable"
    assert law.diagnose(_BROKEN).reason.value != member.LOCATED_BUG_CODE
    assert law.diagnose(_BROKEN).detail.startswith(member.LOCATED_BUG_CODE)


# -- The write-up cannot buy a retry ------------------------------------------


def test_holding_the_source_fixed_and_varying_only_the_prose_never_flips_retry(
    law: MechanismDiagnosis,
) -> None:
    # Feature 209's third clause, tested as the property it is: the *same*
    # source, judged against a growing body of argument, must not move.  The
    # last complaint is an explicit plea to retry, and it buys nothing — which
    # is the whole difference between this feature and a model's opinion.
    assert law.retry(_SOUND) is False
    assert law.retry(_SOUND, []) is False
    assert law.retry(_SOUND, [_COMPLAINTS[0]]) is False
    assert law.retry(_SOUND, _COMPLAINTS) is False
    assert law.retry(_SOUND, _COMPLAINTS[-1]) is False
    assert law.retry(_SOUND, ["line 2: zero division in the rolling mean"]) is False


def test_a_complaint_naming_a_line_is_still_not_a_location(
    law: MechanismDiagnosis,
) -> None:
    # The near-miss the clause is really about: a write-up that *does* name a
    # position, in prose.  It is refused unless the caller passes the position
    # as the position — which is the difference between reading the code and
    # reading about the code.
    prose = "the failure is at line 1, in the signature"
    assert law.retry(_SOUND, [prose]) is False
    assert law.retry(_SOUND, [prose], line=1) is True


def test_holding_the_prose_fixed_and_varying_only_the_source_flips_retry(
    law: MechanismDiagnosis,
) -> None:
    # The other half, and without it the test above passes vacuously: the same
    # complaints *do* admit a retry when the code explains them.  So the
    # asymmetry is source-driven rather than complaint-driven in both
    # directions.
    complaints = _COMPLAINTS
    assert law.retry(_SOUND, complaints) is False
    assert law.retry(_BROKEN, complaints) is True


def test_the_write_up_can_separate_the_two_refusals_from_each_other(
    law: MechanismDiagnosis,
) -> None:
    # The precise scope of "the complaints cannot move the verdict": they move
    # it *between the refusals* — a branch that failed versus one that did not —
    # and never onto the retry path.  Stated as its own test because a suite
    # that only asserted the second half would leave the first looking like an
    # accident.
    assert law.diagnose(_SOUND).reason is DiagnosisReason.NOT_A_DIAGNOSIS
    assert law.diagnose(_SOUND, _COMPLAINTS).reason is (
        DiagnosisReason.FLAWED_MECHANISM
    )


def test_a_located_position_admits_a_retry_even_with_no_complaint_at_all(
    law: MechanismDiagnosis,
) -> None:
    # The converse asymmetry: the *evidence* is sufficient on its own.  A defect
    # the caller located in the code admits the retry without any prose, because
    # what feature 209 requires is the location rather than a report.
    assert law.retry(_SOUND, [], line=2) is True


def test_the_flawed_mechanism_path_is_reachable_only_for_parsing_source(
    law: MechanismDiagnosis,
) -> None:
    # The refusal's meaning depends on where it is reached from, so the reach is
    # pinned: this reason is returned *only* for source that parses (a source
    # that does not parse is a located retry) and *only* when a complaint was
    # reported (otherwise there was no failure to diagnose).  Both neighbours
    # are asserted in the same test, because the claim is about the boundary
    # rather than about the middle.
    assert law.diagnose(_SOUND, _COMPLAINTS).reason is (
        DiagnosisReason.FLAWED_MECHANISM
    )
    assert law.diagnose(_BROKEN, _COMPLAINTS).reason is DiagnosisReason.RETRYABLE
    assert law.diagnose(_SOUND).reason is DiagnosisReason.NOT_A_DIAGNOSIS
    # And the sentence must not claim the source is what its author meant to
    # write — that is false for a proposal which parses but declares the wrong
    # entrypoint, and a driver reading it would go looking for a bug the law
    # never ruled out.
    detail = law.diagnose(_SOUND, _COMPLAINTS).detail
    assert "meant to write" not in detail
    assert "the source parses" in detail


def test_the_flawed_mechanism_sentence_does_not_overclaim_about_the_source(
    law: MechanismDiagnosis,
) -> None:
    # The edge case the sentence above guards against, spelled as its own test
    # so a rewording that reintroduced the overclaim fails here rather than
    # silently in a log line: a proposal can parse perfectly, be refused by
    # feature 205's conformance check, and carry a *deliberate* defect.  The law
    # has not established that the source is blameless — only that no position
    # in it was located — and the two are different statements.
    wrong_entrypoint = "def sig(ctx, seed):\n    return 1\n"
    assert first_defect(wrong_entrypoint) is None  # it parses
    refusal = law.diagnose(wrong_entrypoint, ["no 'signal' entrypoint found"])
    assert refusal.reason is DiagnosisReason.FLAWED_MECHANISM
    assert "no position in the proposal's own source was established" in (
        refusal.detail
    )
    # And the same proposal with the position supplied is a retry — which is
    # what makes the paragraph above a *prompt* rather than a dead end.
    assert law.diagnose(
        wrong_entrypoint, ["no 'signal' entrypoint found"], line=1
    ).retry is True


def test_a_wrong_position_hint_cannot_suppress_the_parsers_own_defect(
    law: MechanismDiagnosis,
) -> None:
    # ``line`` is a claim that is *tried*, not a claim that is *trusted*: the
    # parser is asked on the retry path either way, so a caller cannot reduce
    # this law's answer by passing a worse hint than the parser would have made.
    # ``_BROKEN`` does not parse, and a hint at a line no node begins on must
    # not turn that into a refusal — the wrong hint moves *where* the defect is
    # reported, and never whether there is one.
    parsed = law.diagnose(_BROKEN, _COMPLAINTS)
    hinted = law.diagnose(_BROKEN, _COMPLAINTS, line=99)
    assert parsed.retry is hinted.retry is True
    assert parsed.defect is not None and hinted.defect is not None
    # The hint that *does* resolve wins over the parser's, which is the point of
    # passing one at all.
    decent = law.diagnose(_BROKEN, _COMPLAINTS, line=2)
    assert decent.retry is True
    assert decent.defect.line == 2  # type: ignore[union-attr]
    assert decent.defect is not parsed.defect


def test_a_wrong_position_hint_is_discarded_rather_than_reported(
    law: MechanismDiagnosis,
) -> None:
    # The other side of the same coin, and the reason a caller that must be told
    # its claim was bad asks ``locate`` rather than ``diagnose``: the verdict has
    # one answer, and a hint is graded on the resolution of the *source* rather
    # than on the caller's claim about it.
    assert law.locate(_BROKEN, 99) is None  # the claim, graded on its own
    assert law.diagnose(_BROKEN, _COMPLAINTS, line=99).reason is (
        DiagnosisReason.RETRYABLE
    )


# -- The read side, and the exception on the last line ------------------------


def test_the_locate_verb_is_the_same_predicate_the_verdict_runs(
    law: MechanismDiagnosis,
) -> None:
    # The read side must not be a second implementation: a caller asking
    # "would this position count?" and a caller asking for a verdict cannot get
    # two answers.
    assert law.locate(_SOUND, 2) is not None
    assert law.retry(_SOUND, [], line=2) is True
    assert law.locate(_SOUND, 99) is None
    assert law.retry(_SOUND, [], line=99) is False


def test_require_returns_the_located_defect_whose_text_is_the_proposal(
    law: MechanismDiagnosis,
) -> None:
    # The bridge.  What a caller gets on the last line before it writes a retry
    # prompt is the *code*, so there is no write-up in the value it was handed
    # and a prompt built from it cannot be a guess.
    defect = law.require(_BROKEN, _COMPLAINTS)
    assert isinstance(defect, LocatedDefect)
    assert defect.source_line in _BROKEN
    assert defect.source_line == _BROKEN.splitlines()[defect.line - 1]
    assert defect.filename == SIGNAL_SOURCE_FILENAME
    assert f"{SIGNAL_SOURCE_FILENAME}:{defect.line}" in defect.render()


def test_require_raises_the_refusal_for_both_refusals(
    law: MechanismDiagnosis,
) -> None:
    # One class for both, because a caller on its last line wants the exception
    # either way; the *reason* is what separates them to a caller branching on
    # the returned value — the shape feature 212's ``require`` takes.
    for source, complaints in ((_SOUND, _COMPLAINTS), (_SOUND, ())):
        with pytest.raises(FlawedMechanismError) as refusal:
            law.require(source, complaints)
        assert isinstance(refusal.value, member.SignalAgentError)
    # And the retrying path returns rather than raising, which is the only
    # reason the loop above is not the whole method's behaviour.
    assert isinstance(law.require(_BROKEN), LocatedDefect)


def test_the_exception_carries_the_verdicts_own_sentence(
    law: MechanismDiagnosis,
) -> None:
    # So the retry prompt and the log line say the same thing.
    verdict = law.diagnose(_SOUND, _COMPLAINTS)
    with pytest.raises(FlawedMechanismError) as refusal:
        law.require(_SOUND, _COMPLAINTS)
    assert str(refusal.value) == verdict.detail


def test_a_retrying_require_never_raises(law: MechanismDiagnosis) -> None:
    # The one path that does not raise at all, and that is feature 209's second
    # clause: the decision is the law's returned value.
    defect = law.require(_BROKEN, _COMPLAINTS)
    assert defect.symbol == member.MODULE_SYMBOL


# -- The error vocabulary, and the inheritance that is load-bearing -----------


def test_the_refusal_is_a_sibling_of_the_source_contract_not_a_subclass() -> None:
    # The sharpest inheritance decision in this member.  The three refusals that
    # *do* subclass AgentSourceError each assert the same repair — re-prompt the
    # agent — so a caller written before them must not lose them.  This refusal
    # asserts the opposite repair, so a handler whose body is "re-prompt" must
    # not catch it: that would spend a trial charge on the branch the diagnosis
    # just closed, which is the one thing feature 209 exists to prevent.
    assert issubclass(FlawedMechanismError, member.SignalAgentError)
    assert not issubclass(FlawedMechanismError, member.AgentSourceError)


def test_the_three_repair_the_agent_refusals_still_subclass_the_source_contract() -> None:
    # The other half, asserted beside it so the asymmetry is held as a
    # *relationship* rather than as one fact about one class: a later "tidy-up"
    # that moved this refusal under the base would break the first test, and one
    # that moved the other three out would break this one.
    for repair_the_agent in (
        member.IllegalThemeError,
        member.DeadTerritoryError,
        member.AntiConvergenceError,
    ):
        assert issubclass(repair_the_agent, member.AgentSourceError), (
            repair_the_agent
        )
    # The negative is asserted by *catching*, not by ``issubclass``, because the
    # claim is about a caller's handler rather than about the type algebra: the
    # clause below is the handler written before feature 209 existed, and it
    # must run past this refusal and leave the caller to see it.
    caught = False
    try:
        raise FlawedMechanismError("must not be caught by that clause")
    except member.AgentSourceError:  # pragma: no cover - the failure being tested
        caught = True
    except FlawedMechanismError:
        pass
    assert caught is False


def test_the_vocabulary_has_no_retry_class() -> None:
    # ``errors.py`` recorded this before feature 209 existed and it is still
    # true: the retrying half of the decision is a *value*, returned, and an
    # error type whose only raiser is a caller that had already been told to
    # retry is a shape there is nothing to reason about.  Asserted over the
    # member's whole export surface rather than by reading the module, so a
    # class added under any name is caught.
    exported = [
        name
        for name in member.__all__
        if name.endswith("Error") and "Retry" in name
    ]
    assert exported == []


# -- The law carries nothing --------------------------------------------------


def test_the_law_holds_no_state_between_calls(law: MechanismDiagnosis) -> None:
    # A component shared across a campaign that held a proposal or a verdict
    # would let two branches' diagnoses be read through each other.  Held to
    # behaviour by interleaving two branches and showing each answer is the one
    # it would have been alone.
    first = law.diagnose(_BROKEN, _COMPLAINTS)
    second = law.diagnose(_SOUND, _COMPLAINTS)
    assert first.retry is True and second.retry is False
    assert law.diagnose(_BROKEN, _COMPLAINTS).detail == first.detail
    assert law.diagnose(_SOUND, _COMPLAINTS).detail == second.detail


def test_the_law_instance_declares_no_slots() -> None:
    # Nothing to hold, so nothing to go stale: the law is a facade over module
    # functions and has no attributes at all — the shape feature 205's
    # ``SignalContract`` takes.
    assert MechanismDiagnosis.__slots__ == ()
    assert not any(
        name in MechanismDiagnosis.__dict__
        for name in ("_cache", "_defect", "_proposal")
    )


def test_a_single_complaint_string_is_read_as_one_complaint(
    law: MechanismDiagnosis,
) -> None:
    # The one inference this module makes about its caller's data, spelled out
    # in ``_reported``: a caller quoting one validator sentence — the common
    # case — must not be read as twenty complaints, or the count in a refusal's
    # detail would be nonsense.
    verdict = law.diagnose(_SOUND, _COMPLAINTS[1])
    assert verdict.complaints == (_COMPLAINTS[1],)
    assert "1 complaint(s)" in verdict.detail


def test_a_long_complaint_list_is_bounded_in_the_refusals_detail(
    law: MechanismDiagnosis,
) -> None:
    # The refusal names what was reported, but a bounded number of times: a
    # validator returns one problem per failing property, and a paragraph that
    # quoted all of them would be one nobody reads.  Every complaint is still
    # *carried* — the bound is on the sentence, not on the value.
    many = [f"problem {index}" for index in range(member.MAX_LISTED_COMPLAINTS + 3)]
    verdict = law.diagnose(_SOUND, many)
    assert verdict.complaints == tuple(many)
    assert f"{len(many)} complaint(s)" in verdict.detail
    assert "3 more" in verdict.detail
    assert many[-1] not in verdict.detail


def test_the_source_is_judged_and_never_modified(law: MechanismDiagnosis) -> None:
    # A gate that edited a proposal "into a located bug" would be authoring it,
    # the stance features 210's and 212's ``admit`` take toward their inputs.
    # Held by value on the proposal the law returns a defect for.
    source = list(_BROKEN)
    defect = law.require(_BROKEN, _COMPLAINTS)
    assert defect.source_line == _BROKEN.splitlines()[defect.line - 1]
    assert "".join(source) == _BROKEN


# -- The code anchor is shared with the members that read the same source -----


def test_the_source_filename_is_the_one_the_contract_member_compiles_under() -> None:
    # A located bug is a place in the source the *sandbox actually executes*, so
    # the anchor a retry prompt quotes must be the one every other reader of a
    # proposal uses.  Asserted through the contract member's own refusal rather
    # than against a second copy of the literal: a compile of a source that does
    # not parse names this filename, so the two spellings are held to one string
    # by a test that lives in neither module.
    import contract

    problems = contract.validate_signal_signature(_BROKEN)
    assert problems, "a source that does not parse must be refused"
    assert any(SIGNAL_SOURCE_FILENAME in problem for problem in problems), problems


def test_the_module_symbol_is_the_one_pythons_own_defects_carry() -> None:
    # ``<module>`` rather than a name the agent wrote, so a log line cannot
    # mistake it for a symbol in the proposal.
    assert member.MODULE_SYMBOL == "<module>"
    assert locate_defect(_BROKEN, 1).symbol == member.MODULE_SYMBOL  # type: ignore[union-attr]
    assert first_defect(_BROKEN).symbol == member.MODULE_SYMBOL  # type: ignore[union-attr]


def test_the_verdict_repr_names_the_reason_and_the_location(
    law: MechanismDiagnosis,
) -> None:
    # A debugging aid, asserted because a repr that lied about the location
    # would be the first thing a reader trusts and the last thing they check.
    retrying = repr(law.diagnose(_BROKEN, _COMPLAINTS))
    assert "reason='retryable'" in retrying
    assert "retry=True" in retrying
    assert "1:22" in retrying  # the location, so a reader sees where
    assert "retry=False" in repr(law.diagnose(_SOUND, _COMPLAINTS))
    assert "LocatedDefect(" in repr(law.require(_BROKEN))
