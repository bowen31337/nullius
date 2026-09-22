"""Feature 208 — the prompt carries no summarized directional guidance.

app_spec.xml, "Hypothesis Authoring Agent", feature 208: *System rejects
injecting summarized directional guidance into the prompt, because prose priors
over-constrain the search space.*  The claims here are about
:mod:`signal_agent._guidance`, and the *shape* claims — the two-declaration
check (role, provenance), the refusal of a flat prompt text rather than a scan
of it, the computed flag, the refusal that names sections and never quotes
prose — are the ones worth reading, because they are what makes the law refuse
something rather than merely describe it.

The prompts are inline rather than in the conftest, the convention
``test_history.py`` states: several assertions are about the *parts* (their
names are the declarations the check reads), so a fixture that rebuilt them per
test would make "the same section" a claim about two constructions rather than
about one mapping.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from signal_agent import (
    INJECTED_GUIDANCE_CODE,
    MAX_LISTED_INJECTIONS,
    NOT_PROMPT_PARTS_CODE,
    UNGUIDED_CODE,
    GuidanceReason,
    GuidanceVerdict,
    InjectedGuidanceError,
    PromptGuidanceGate,
)

#: The sections §14.1's prompt legitimately carries — the replay half this law
#: exists to protect.  A guidance section planted beside them is the headline
#: case: the mistake PRD §C3 says most implementations make is adding one
#: *more* section to a prompt like this, believing it helps.
CONTRACT = "entrypoint signal(ctx, seed); universe closes; replay bit-exact."
HISTORY = "prior proposals, verbatim, in full"
CLAUSE = "do not submit a parameter tweak of a mechanism the campaign holds"
THEMES = "order-flow-imbalance, cross-sectional-momentum, ..."
SCORES = "score.json per node, as recorded"

#: The prose an injected section actually carries.  Deliberately bland: the
#: law's claim is that it never reads this, so the words must be ones a
#: prose scanner would have found suspicious and the role check must not.
DIRECTION = "momentum has been working; prefer continuation over reversal."

#: A clean prompt of the canonical shape: the parts a flattener is about to
#: render, all declared, none of them guidance.
CLEAN = {
    "contract": CONTRACT,
    "themes": THEMES,
    "history": HISTORY,
    "clause": CLAUSE,
    "scores": SCORES,
}


# ── The admitted case ─────────────────────────────────────────────────────────


def test_a_prompt_of_declared_parts_is_admitted(guidance_gate: PromptGuidanceGate) -> None:
    """Every legitimate section present, in the caller's order, unmodified."""
    verdict = guidance_gate.admit(CLEAN)
    assert verdict.admitted
    assert verdict.reason is GuidanceReason.UNGUIDED
    assert [name for name, _ in verdict.sections] == list(CLEAN)
    assert dict(verdict.sections)["history"] is HISTORY


def test_require_returns_the_parts_when_the_prompt_is_unguided(
    guidance_gate: PromptGuidanceGate,
) -> None:
    """``require`` is a read on the admitted path, not only a raise on the refused one."""
    sections = guidance_gate.admit(CLEAN).require()
    assert dict(sections)["contract"] == CONTRACT


def test_the_admitted_parts_are_returned_unmodified(
    guidance_gate: PromptGuidanceGate,
) -> None:
    """The law judges a prompt and never authors one — no re-writing, no re-ordering."""
    verdict = guidance_gate.admit({"history": HISTORY, "scores": [1, 2]})
    assert verdict.sections == (("history", HISTORY), ("scores", [1, 2]))


def test_an_empty_prompt_is_unguided(guidance_gate: PromptGuidanceGate) -> None:
    """A prompt with no parts injects nothing.

    Refusing this would block the first round of every campaign, which is the
    failure mode of reading "no guidance" as "at least one section checked".
    """
    verdict = guidance_gate.admit({})
    assert verdict.admitted
    assert verdict.sections == ()


def test_the_success_sentence_opens_with_its_code(
    guidance_gate: PromptGuidanceGate,
) -> None:
    """An operator greps the admission by the paper's own word for the winner."""
    verdict = guidance_gate.admit(CLEAN)
    assert verdict.detail.startswith(UNGUIDED_CODE)


def test_unguided_agrees_with_admit(guidance_gate: PromptGuidanceGate) -> None:
    """The two methods cannot disagree: one is defined as a read of the other."""
    injected = dict(CLEAN, summary=DIRECTION)
    assert guidance_gate.unguided(CLEAN) is guidance_gate.admit(CLEAN).admitted
    assert guidance_gate.unguided(injected) is guidance_gate.admit(injected).admitted


# ── "declares the guidance role" — the name check ─────────────────────────────


def test_a_section_declaring_a_guidance_role_is_refused(
    guidance_gate: PromptGuidanceGate,
) -> None:
    """The headline case: one more section, added by an implementation that
    believed it was helping."""
    verdict = guidance_gate.admit(dict(CLEAN, summary=DIRECTION))
    assert not verdict.admitted
    assert verdict.reason is GuidanceReason.INJECTED_GUIDANCE
    assert verdict.detail.startswith(INJECTED_GUIDANCE_CODE)
    assert "summary" in verdict.detail


def test_the_role_check_refuses_whatever_the_content(
    guidance_gate: PromptGuidanceGate,
) -> None:
    """The declaration is the subject: a section of score records is still
    guidance once it declares the role."""
    verdict = guidance_gate.admit({"lessons": SCORES})
    assert verdict.reason is GuidanceReason.INJECTED_GUIDANCE


@pytest.mark.parametrize(
    "role",
    [
        "advice",
        "digest",
        "direction",
        "directional",
        "directional_guidance",
        "directions",
        "guidance",
        "guidance_summary",
        "hints",
        "history_digest",
        "history_summary",
        "insights",
        "lessons",
        "lessons_learned",
        "recommendations",
        "summary",
        "summary_of_history",
        "synthesis",
        "takeaways",
        "tips",
        "trends",
        "what_failed",
        "what_worked",
    ],
)
def test_every_guidance_role_is_refused(
    guidance_gate: PromptGuidanceGate, role: str
) -> None:
    """The spelled-out set, so a rename in the module is a failing test."""
    verdict = guidance_gate.admit({role: DIRECTION})
    assert verdict.reason is GuidanceReason.INJECTED_GUIDANCE


@pytest.mark.parametrize(
    ("spelling", "expected"),
    [
        ("Summary", GuidanceReason.INJECTED_GUIDANCE),
        ("LESSONS-LEARNED", GuidanceReason.INJECTED_GUIDANCE),
        ("  history summary  ", GuidanceReason.INJECTED_GUIDANCE),
        ("What Worked", GuidanceReason.INJECTED_GUIDANCE),
        ("prior_insights", GuidanceReason.UNGUIDED),
        ("insights_and_lessons", GuidanceReason.UNGUIDED),
        ("historical_context", GuidanceReason.UNGUIDED),
    ],
)
def test_a_role_is_a_word_not_a_spelling(
    guidance_gate: PromptGuidanceGate, spelling: str, expected: GuidanceReason
) -> None:
    """Normalised before matching, so case, spacing and punctuation are not a
    disguise — and not a loophole either: the match is on the whole normal
    form, so a name that merely *contains* a role's word is not the role.

    ``prior_insights`` and ``insights_and_lessons`` carry the words; neither
    is the declared role, and refusing them would be a substring check
    wearing a normaliser.
    """
    verdict = guidance_gate.admit({spelling: DIRECTION})
    assert verdict.reason is expected


def test_two_spellings_of_one_role_are_one_role(
    guidance_gate: PromptGuidanceGate,
) -> None:
    """The normal forms agree, so the verdicts agree."""
    spaced = guidance_gate.admit({"lessons learned": DIRECTION})
    underscored = guidance_gate.admit({"lessons_learned": DIRECTION})
    assert spaced.reason is underscored.reason is GuidanceReason.INJECTED_GUIDANCE


@pytest.mark.parametrize(
    "near_miss",
    [
        "themes",
        "scores",
        "records",
        "history",
        "proposals",
        "contract",
        "clause",
        "declaration",
        "historical_context",
        "budget",
        "universe",
        "rotation",
        "context",
        "notes",
        "focus",
    ],
)
def test_the_legitimate_sections_are_not_refused(
    guidance_gate: PromptGuidanceGate, near_miss: str
) -> None:
    """The deliberate near-misses: a denylist refuses §C3's one thing, not
    everything §C3 does not name.

    ``themes`` is the §9.3 set, ``scores``/``records`` are §14.1's per-node
    facts, ``history``/``proposals`` are the replay sections feature 206
    owns, and a deployment may add sections this member never imagined
    without asking this law's permission.
    """
    verdict = guidance_gate.admit({near_miss: DIRECTION})
    assert verdict.admitted, verdict.detail


@pytest.mark.parametrize(
    "empty", ["", None, (), [], {}, 0, False],
)
def test_a_guidance_role_with_nothing_in_it_injects_nothing(
    guidance_gate: PromptGuidanceGate, empty: object
) -> None:
    """Truthiness rather than presence: refusing on the field name alone would
    refuse a template's empty placeholder slot."""
    verdict = guidance_gate.admit({"summary": empty})
    assert verdict.admitted
    assert [name for name, _ in verdict.sections] == ["summary"]


# ── "declares itself distilled" — the provenance check ────────────────────────


def test_a_part_declaring_a_history_provenance_is_refused(
    guidance_gate: PromptGuidanceGate,
) -> None:
    """The innocent name is not a licence: §14.1's sentence names the operation
    exactly — compressing complete proposals into prose."""
    verdict = guidance_gate.admit(
        {"context": {"text": DIRECTION, "derived_from": "prior proposals"}}
    )
    assert verdict.reason is GuidanceReason.INJECTED_GUIDANCE
    assert "context" in verdict.detail
    assert "derived_from" in verdict.detail


@pytest.mark.parametrize(
    "key",
    [
        "derived_from",
        "distilled_from",
        "generated_from",
        "summarised_from",
        "summarized_from",
        "synthesised_from",
        "synthesized_from",
    ],
)
def test_every_distilling_declaration_is_refused(
    guidance_gate: PromptGuidanceGate, key: str
) -> None:
    """The spelled-out set, British and American spellings both."""
    verdict = guidance_gate.admit({"context": {key: "the campaign's history"}})
    assert verdict.reason is GuidanceReason.INJECTED_GUIDANCE


@pytest.mark.parametrize(
    "source",
    [
        "prior proposals",
        "the campaign's history",
        "history",
        "the tree",
        "prior scores",
        ["node-1", "node-2"],
    ],
)
def test_a_provenance_naming_the_history_is_refused(
    guidance_gate: PromptGuidanceGate, source: object
) -> None:
    """The words the history is named by, read as whole tokens over the value."""
    verdict = guidance_gate.admit({"context": {"derived_from": source}})
    assert verdict.reason is GuidanceReason.INJECTED_GUIDANCE


@pytest.mark.parametrize(
    "source", ["contract", "manifest", "the declared ABI", "legal themes"],
)
def test_a_provenance_naming_something_else_is_admitted(
    guidance_gate: PromptGuidanceGate, source: str
) -> None:
    """PRD §C3 forbids guidance *from history*; prose derived from the declared
    facts is not a prior about where to look."""
    verdict = guidance_gate.admit({"context": {"derived_from": source}})
    assert verdict.admitted, verdict.detail


def test_an_empty_provenance_declares_nothing(guidance_gate: PromptGuidanceGate) -> None:
    """``derived_from: ""`` names no source, and refusing it would refuse a
    record for its schema."""
    verdict = guidance_gate.admit({"context": {"derived_from": ""}})
    assert verdict.admitted


def test_prose_itself_is_never_the_subject(guidance_gate: PromptGuidanceGate) -> None:
    """The load-bearing negative: a section of plain prose under an innocent
    name is admitted no matter what the prose says.

    A scan of this text for guidance words would have refused it — and §C3
    requires the *proposals themselves* in full, which carry their own
    summaries, their own directions, their own advice.
    """
    verdict = guidance_gate.admit({"context": DIRECTION})
    assert verdict.admitted


def test_a_sequence_entrys_provenance_is_read_like_a_mappings(
    guidance_gate: PromptGuidanceGate,
) -> None:
    """The duck-typed seam: an entry that names itself and declares a source is
    judged exactly as the equivalent mapping's value is."""
    verdict = guidance_gate.admit(
        [{"name": "context", "text": DIRECTION, "derived_from": "prior proposals"}]
    )
    assert verdict.reason is GuidanceReason.INJECTED_GUIDANCE


# ── The object shapes ──────────────────────────────────────────────────────────


def test_an_object_prompt_is_read_by_its_attributes(
    guidance_gate: PromptGuidanceGate,
) -> None:
    """The typed driver's shape: a dataclass or namespace, judged the same."""
    prompt = SimpleNamespace(contract=CONTRACT, history=HISTORY)
    verdict = guidance_gate.admit(prompt)
    assert verdict.admitted
    assert dict(verdict.sections) == {"contract": CONTRACT, "history": HISTORY}


def test_an_object_prompt_with_a_guidance_attribute_is_refused(
    guidance_gate: PromptGuidanceGate,
) -> None:
    """Recognition is not an admission: the attribute is a declared part, and
    its declaration is guidance."""
    verdict = guidance_gate.admit(SimpleNamespace(history=HISTORY, insights=DIRECTION))
    assert verdict.reason is GuidanceReason.INJECTED_GUIDANCE


def test_a_slots_object_is_read_through_its_slots(
    guidance_gate: PromptGuidanceGate,
) -> None:
    """``vars()`` cannot reach a slots instance; a workspace that hand-writes
    ``__slots__`` on its own values must not become unscreenable by that."""
    class Slotted:
        """The hand-written-slots shape feature 223's prefix view set."""

        __slots__ = ("contract", "lessons")

        def __init__(self, contract: str, lessons: str) -> None:
            self.contract = contract
            self.lessons = lessons

    assert guidance_gate.admit(Slotted(CONTRACT, DIRECTION)).reason is (
        GuidanceReason.INJECTED_GUIDANCE
    )
    assert guidance_gate.admit(Slotted(CONTRACT, "")).admitted


def test_an_object_with_no_state_names_no_parts(
    guidance_gate: PromptGuidanceGate,
) -> None:
    """``object()`` has nothing to screen and nothing to flatten; the caller is
    told to hand parts rather than handed a vacuous admission."""
    verdict = guidance_gate.admit(object())
    assert verdict.reason is GuidanceReason.NOT_PROMPT_PARTS


# ── The sequence-of-named-entries shape ────────────────────────────────────────


def test_a_sequence_of_named_entries_is_read(
    guidance_gate: PromptGuidanceGate,
) -> None:
    """The list-of-records shape: each entry names itself, in the caller's order."""
    verdict = guidance_gate.admit(
        [
            {"name": "contract", "text": CONTRACT},
            {"name": "history", "text": HISTORY},
        ]
    )
    assert verdict.admitted
    assert [name for name, _ in verdict.sections] == ["contract", "history"]


@pytest.mark.parametrize("field", ["name", "role", "section", "title"])
def test_every_name_field_declares_the_entry(
    guidance_gate: PromptGuidanceGate, field: str
) -> None:
    """The one place a section's identity lives, spelled by any of its fields."""
    verdict = guidance_gate.admit([{field: "summary", "text": DIRECTION}])
    assert verdict.reason is GuidanceReason.INJECTED_GUIDANCE


def test_the_first_name_field_wins(guidance_gate: PromptGuidanceGate) -> None:
    """Two fields naming one entry cannot produce two verdicts."""
    verdict = guidance_gate.admit(
        [{"name": "context", "title": "summary", "text": DIRECTION}]
    )
    assert verdict.admitted
    assert verdict.sections[0][0] == "context"


def test_a_sequence_entry_that_names_nothing_is_not_screenable(
    guidance_gate: PromptGuidanceGate,
) -> None:
    """A part with no declaration cannot declare a role, and reading it anyway
    would be the vacuous green this member refuses everywhere."""
    verdict = guidance_gate.admit([{"text": DIRECTION}])
    assert verdict.reason is GuidanceReason.NOT_PROMPT_PARTS


def test_an_empty_sequence_is_unguided(guidance_gate: PromptGuidanceGate) -> None:
    """The empty-prompt case again, on the sequence shape."""
    assert guidance_gate.admit([]).admitted


# ── "not prompt parts at all" ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "not_parts", ["a rendered prompt", b"bytes", None, 7],
)
def test_something_that_is_not_parts_is_refused(
    guidance_gate: PromptGuidanceGate, not_parts: object
) -> None:
    """A flat prompt text is the *rendered* prompt, and the law refuses it
    rather than scanning it.

    Reading a rendered string as "one section, unnamed, admitted" would be the
    silent green tick: a law that cannot read the declared structure certifies
    nothing.
    """
    verdict = guidance_gate.admit(not_parts)
    assert verdict.reason is GuidanceReason.NOT_PROMPT_PARTS
    assert verdict.detail.startswith(NOT_PROMPT_PARTS_CODE)
    assert not verdict.admitted


def test_the_not_prompt_parts_sentence_names_the_type_received(
    guidance_gate: PromptGuidanceGate,
) -> None:
    """The caller's wiring is what is wrong, so the sentence says what arrived."""
    verdict = guidance_gate.admit("a rendered prompt")
    assert "str" in verdict.detail
    verdict = guidance_gate.admit(None)
    assert "NoneType" in verdict.detail


def test_the_not_prompt_parts_sentence_names_the_three_shapes(
    guidance_gate: PromptGuidanceGate,
) -> None:
    """A refusal is a repair: the three screenable shapes are the repair here."""
    verdict = guidance_gate.admit(7)
    for shape in ("mapping", "object", "sequence"):
        assert shape in verdict.detail


def test_a_sequence_of_prose_entries_is_not_parts(
    guidance_gate: PromptGuidanceGate,
) -> None:
    """``["contract text", "history text"]`` is a rendered prompt in pieces —
    entries that name themselves nothing."""
    verdict = guidance_gate.admit([CONTRACT, HISTORY])
    assert verdict.reason is GuidanceReason.NOT_PROMPT_PARTS


# ── The shape of the refusal ──────────────────────────────────────────────────


def test_a_refusal_carries_no_sections(guidance_gate: PromptGuidanceGate) -> None:
    """The prefix a law read before it found the injection *is* a prompt this
    feature refused.

    Returning it would let a caller ship exactly the prompt this feature
    exists to stop.
    """
    verdict = guidance_gate.admit({"contract": CONTRACT, "summary": DIRECTION})
    assert not verdict.admitted
    assert verdict.sections == ()


def test_the_refusal_names_the_section_and_the_declaration(
    guidance_gate: PromptGuidanceGate,
) -> None:
    """A refusal that named nothing would not be a repair; one that said only
    "guidance" would not say which half of the declaration matched."""
    verdict = guidance_gate.admit({"context": {"derived_from": "prior proposals"}})
    assert "context" in verdict.detail
    assert "distilled" in verdict.detail


def test_every_offending_section_is_named(guidance_gate: PromptGuidanceGate) -> None:
    """Two injections under different declarations: one refusal, both named."""
    verdict = guidance_gate.admit(
        {
            "contract": CONTRACT,
            "summary": DIRECTION,
            "context": {"derived_from": "the tree"},
        }
    )
    assert verdict.reason is GuidanceReason.INJECTED_GUIDANCE
    assert "summary" in verdict.detail
    assert "context" in verdict.detail


def test_the_sentence_names_every_offence_bounded(
    guidance_gate: PromptGuidanceGate,
) -> None:
    """Bounded and counted: a template that grew twelve guidance sections is a
    message nobody reads.

    Twelve distinct roles from the vocabulary, each its own section — the
    match is on the whole normal form, so numbered near-misses would not be
    offences at all.
    """
    roles = [
        "advice",
        "digest",
        "direction",
        "directional",
        "directional_guidance",
        "directions",
        "guidance",
        "guidance_summary",
        "hints",
        "history_digest",
        "history_summary",
        "insights",
    ]
    assert len(roles) == MAX_LISTED_INJECTIONS + 4
    verdict = guidance_gate.admit(
        [{"name": name, "text": DIRECTION} for name in roles]
    )
    assert "and 4 more" in verdict.detail
    assert len(verdict.offenders) == MAX_LISTED_INJECTIONS + 4


def test_the_offenders_are_deduplicated_and_sorted(
    guidance_gate: PromptGuidanceGate,
) -> None:
    """The count is of distinct sections: an inflated number is a misleading one.

    A sequence may name the same role twice, which is the one shape a mapping
    cannot produce — and the count an operator reads is the count of distinct
    sections to delete.
    """
    verdict = guidance_gate.admit(
        [
            {"name": "trends", "text": DIRECTION},
            {"name": "advice", "text": DIRECTION},
            {"name": "trends", "text": DIRECTION},
        ]
    )
    assert list(verdict.offenders) == ["advice", "trends"]


def test_a_refusal_never_quotes_the_prose(guidance_gate: PromptGuidanceGate) -> None:
    """The prose of an injected section is the thing to delete, not the thing to
    re-print in a log line where a reader might mistake it for content the
    system endorses."""
    verdict = guidance_gate.admit({"summary": DIRECTION})
    assert DIRECTION not in verdict.detail
    cut = guidance_gate.admit({"context": {"derived_from": "prior proposals"}})
    assert "prior proposals" in cut.detail  # the *declaration* is quoted…
    assert DIRECTION not in cut.detail  # …the prose never is


def test_the_refusal_carries_the_papers_finding(
    guidance_gate: PromptGuidanceGate,
) -> None:
    """The *because* is the feature's own sentence, and the refusal carries it
    rather than a bare "not allowed"."""
    verdict = guidance_gate.admit({"summary": DIRECTION})
    assert "Figure 5" in verdict.detail
    assert "underperformed" in verdict.detail


# ── The value shapes ──────────────────────────────────────────────────────────


def test_every_code_is_its_own_reasons_value() -> None:
    """Branching on the value and grepping for it are the same string."""
    assert GuidanceReason.INJECTED_GUIDANCE == INJECTED_GUIDANCE_CODE
    assert GuidanceReason.NOT_PROMPT_PARTS == NOT_PROMPT_PARTS_CODE


def test_unguided_is_the_one_reason_whose_detail_opens_differently() -> None:
    """The documented asymmetry: an admission is not a code an operator greps for.

    ``HistoryReason.COMPLETE`` and ``AntiConvergenceReason.NOVEL`` have the
    same one.
    """
    assert GuidanceReason.UNGUIDED == "unguided"
    assert UNGUIDED_CODE != GuidanceReason.UNGUIDED


def test_admitted_is_computed_from_the_reason_and_not_passed_in() -> None:
    """A verdict cannot disagree with its own reason."""
    assert GuidanceVerdict(GuidanceReason.UNGUIDED, "x").admitted is True
    assert GuidanceVerdict(GuidanceReason.INJECTED_GUIDANCE, "x").admitted is False
    assert GuidanceVerdict(GuidanceReason.INJECTED_GUIDANCE, "x").sections == ()
    assert GuidanceVerdict(GuidanceReason.NOT_PROMPT_PARTS, "x").sections == ()


def test_the_verdict_has_no_writable_state_beyond_its_fields() -> None:
    """The slots are the verdict's whole shape, and the caller cannot add to it."""
    assert set(GuidanceVerdict.__slots__) == {
        "admitted",
        "detail",
        "offenders",
        "reason",
        "sections",
    }


# ── ``require`` and the error ─────────────────────────────────────────────────


def test_require_raises_on_the_refused_path(guidance_gate: PromptGuidanceGate) -> None:
    """The one place this law raises."""
    verdict = guidance_gate.admit({"summary": DIRECTION})
    with pytest.raises(InjectedGuidanceError) as raised:
        verdict.require()
    assert raised.value.args[0] == verdict.detail


def test_the_gates_require_agrees_with_the_verdicts(
    guidance_gate: PromptGuidanceGate,
) -> None:
    """The caller's verb: the same raise, on the last line before the ship."""
    with pytest.raises(InjectedGuidanceError):
        guidance_gate.require({"summary": DIRECTION})
    assert guidance_gate.require(CLEAN) == guidance_gate.admit(CLEAN).sections


def test_the_error_is_not_reachable_through_the_source_contract() -> None:
    """The asymmetry: a caller's ``except AgentSourceError`` must not catch it.

    That handler repairs by re-prompting the agent, and re-prompting with the
    same prompt buys another over-constrained search from the same
    over-constrained prompt.
    """
    from signal_agent import (
        AgentSourceError,
        AntiConvergenceClauseError,
        FlawedMechanismError,
        TruncatedHistoryError,
    )

    assert issubclass(InjectedGuidanceError, Exception)
    assert not issubclass(InjectedGuidanceError, AgentSourceError)
    assert not issubclass(InjectedGuidanceError, FlawedMechanismError)
    assert not issubclass(InjectedGuidanceError, TruncatedHistoryError)
    assert not issubclass(InjectedGuidanceError, AntiConvergenceClauseError)


def test_the_error_is_in_the_members_vocabulary() -> None:
    """Catchable as the member's own base, like every other refusal here."""
    from signal_agent import SignalAgentError

    assert issubclass(InjectedGuidanceError, SignalAgentError)


def test_the_error_message_opens_with_the_reasons_code(
    guidance_gate: PromptGuidanceGate,
) -> None:
    """A campaign log and an operator's grep say the same thing."""
    with pytest.raises(InjectedGuidanceError) as raised:
        guidance_gate.admit({"summary": DIRECTION}).require()
    assert str(raised.value).startswith(INJECTED_GUIDANCE_CODE)
    with pytest.raises(InjectedGuidanceError) as flat:
        guidance_gate.admit(None).require()
    assert str(flat.value).startswith(NOT_PROMPT_PARTS_CODE)


@pytest.mark.parametrize(
    ("prompt", "code"),
    [
        ({"summary": DIRECTION}, INJECTED_GUIDANCE_CODE),
        ({"context": {"derived_from": "the tree"}}, INJECTED_GUIDANCE_CODE),
        ("a rendered prompt", NOT_PROMPT_PARTS_CODE),
        (None, NOT_PROMPT_PARTS_CODE),
        ([{"text": DIRECTION}], NOT_PROMPT_PARTS_CODE),
    ],
)
def test_each_reason_opens_its_own_sentence(
    guidance_gate: PromptGuidanceGate, prompt: object, code: str
) -> None:
    """Three reasons, three headlines — a refusal never opens with another's."""
    verdict = guidance_gate.admit(prompt)
    assert verdict.detail.startswith(code)


# ── The law's own shape ───────────────────────────────────────────────────────


def test_the_law_is_stateless() -> None:
    """No per-run state to keep in step with the prompt — the gates' own shape."""
    assert PromptGuidanceGate.__slots__ == ()


def test_admit_never_raises(guidance_gate: PromptGuidanceGate) -> None:
    """A caller measuring its assemblies cannot do that through a raise."""
    for value in (None, 7, "flat", b"b", {}, [], object(), [42], {"summary": ""}):
        assert isinstance(guidance_gate.admit(value).admitted, bool)


def test_the_verdict_constructor_refuses_nothing() -> None:
    """Unguidedness is ``admit``'s judgment, not the value's.

    A caller holding a refusal is the caller that most needs one, and it
    cannot be told about an object it was never allowed to build.
    """
    assert GuidanceVerdict(GuidanceReason.NOT_PROMPT_PARTS, "x").detail == "x"


def test_the_declaration_sets_are_read_in_a_stable_order(
    guidance_gate: PromptGuidanceGate,
) -> None:
    """A record carrying two provenance declarations is decided the same way
    twice, and a refusal an operator diffs between rounds must not move
    because a hash seed did."""
    part = {"summarised_from": "history", "synthesized_from": "the tree"}
    reasons = {guidance_gate.admit({"context": dict(part)}).detail for _ in range(20)}
    assert len(reasons) == 1


# ── The boundaries ────────────────────────────────────────────────────────────


def test_the_boundary_with_feature_206_a_history_section_is_not_re_judged(
    guidance_gate: PromptGuidanceGate,
) -> None:
    """206 owns the history's *contents*; this law only reads the prompt's
    parts.

    A ``summary_of`` declaration on an entry *inside* a history section is
    feature 206's sampled-history refusal, not this law's — so a prompt whose
    history section carries such entries is admitted here and refused by the
    history law, each on its own subject.
    """
    verdict = guidance_gate.admit(
        {
            "history": [
                {"node_id": "n1", "proposal": "def signal(ctx, seed): ..."},
                {"node_id": "n2", "proposal": "a summary", "summary_of": "n2"},
            ]
        }
    )
    assert verdict.admitted
    assert verdict.reason is GuidanceReason.UNGUIDED


def test_the_boundary_with_feature_210_the_committed_clause_is_admitted(
    guidance_gate: PromptGuidanceGate,
) -> None:
    """The one prose this member compiles is a *negative constraint* — it names
    no direction to search in.

    §C3 demands exactly one thing the prompt must carry and one class of thing
    it must not, and a prompt carrying the clause, the contract and the whole
    history is admitted here while feature 210 *requires* the clause there.
    """
    from signal_agent import anti_convergence_gate

    clause = anti_convergence_gate().text()
    prompt = {"contract": CONTRACT, "history": HISTORY, "clause": clause}
    verdict = guidance_gate.admit(prompt)
    assert verdict.admitted
    assert anti_convergence_gate().carries(clause) is True


def test_the_two_prompt_side_laws_pull_in_opposite_directions(
    guidance_gate: PromptGuidanceGate,
) -> None:
    """210 refuses the prompt *missing* the clause; 208 refuses the prompt
    *carrying* distilled prose.  A caller holding both answers can tell which
    half of its assembler to fix."""
    from signal_agent import AntiConvergenceClauseError, anti_convergence_gate

    gate = anti_convergence_gate()
    with pytest.raises(AntiConvergenceClauseError):
        gate.require_in(CONTRACT)
    with pytest.raises(InjectedGuidanceError):
        guidance_gate.require({"contract": CONTRACT, "summary": DIRECTION})
