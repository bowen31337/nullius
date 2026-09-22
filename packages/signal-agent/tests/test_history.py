"""Feature 206 — the history is read in full, or it is not a history.

app_spec.xml, "Hypothesis Authoring Agent", feature 206: *Agent rejects a
truncated history sample, reading every prior proposal in full before
proposing.*  The claims here are about :mod:`signal_agent._history`, and the
*shape* claims — the two-clause split, the recomputed-identity check, the
computed flag, the refusal that names and never quotes — are the ones worth
reading, because they are what makes the law refuse something rather than
merely describe it.

The proposals are inline rather than in the conftest, the convention
``test_authoring.py`` states: several assertions are about the *text* (its hash
is the identity the check recomputes over), so a fixture that rebuilt them per
test would make "the same text" a claim about two constructions rather than
about one string.
"""

from __future__ import annotations

import uuid

import pytest
from signal_agent import (
    COMPLETE_HISTORY_CODE,
    MAX_LISTED_OFFENDERS,
    MISSING_PROPOSAL_CODE,
    NOT_A_HISTORY_CODE,
    SAMPLED_HISTORY_CODE,
    TRUNCATED_HISTORY_CODE,
    HistoryReason,
    ProposalHistory,
    TruncatedHistoryError,
    source_code_hash,
)

#: Two prior proposals, as text.  Deliberately not tiny: the truncation claims
#: below are made by cutting them, and a cut of a three-character string is a
#: claim about an off-by-one rather than about a proposal.
PROPOSAL_A = "def signal(observations):\n    return observations['close']\n"
PROPOSAL_B = "def signal(observations):\n    return -observations['close']\n"

NODE_A = str(uuid.uuid4())
NODE_B = str(uuid.uuid4())


def whole(node_id: str, proposal: str) -> dict:
    """One prior proposal as the tree would hand it over — identity and text.

    The ``code_hash`` is the real one, taken through the member's own
    :func:`source_code_hash`, because the whole point of the check it feeds is
    that the two agree to the byte.
    """
    return {
        "node_id": node_id,
        "proposal": proposal,
        "code_hash": source_code_hash(proposal),
    }


# ── The admitted case ─────────────────────────────────────────────────────────


def test_a_whole_history_is_admitted(history_law: ProposalHistory) -> None:
    """Every prior proposal present, whole, in the caller's order."""
    verdict = history_law.admit(
        [whole(NODE_A, PROPOSAL_A), whole(NODE_B, PROPOSAL_B)],
        prior_nodes=[NODE_A, NODE_B],
    )
    assert verdict.complete
    assert verdict.reason is HistoryReason.COMPLETE
    assert [entry.node_id for entry in verdict.entries] == [NODE_A, NODE_B]
    assert [entry.proposal for entry in verdict.entries] == [PROPOSAL_A, PROPOSAL_B]


def test_the_admitted_history_is_returned_whole(history_law: ProposalHistory) -> None:
    """The text comes back verbatim — not normalised, not stripped, not re-encoded."""
    entries = history_law.admit(
        [whole(NODE_A, PROPOSAL_A)], prior_nodes=[NODE_A]
    ).require()
    assert entries[0].proposal == PROPOSAL_A
    assert entries[0].code_hash == source_code_hash(PROPOSAL_A)


def test_require_returns_the_entries_when_the_history_is_whole(
    history_law: ProposalHistory,
) -> None:
    """``require`` is a read on the admitted path, not only a raise on the refused one."""
    verdict = history_law.admit([whole(NODE_A, PROPOSAL_A)], prior_nodes=[NODE_A])
    assert verdict.require() == verdict.entries


def test_an_empty_history_is_a_history_and_is_whole(
    history_law: ProposalHistory,
) -> None:
    """A campaign's first round has read every prior proposal there is.

    Refusing this would block the first proposal of every campaign, which is
    the failure mode of reading "every" as "at least one".
    """
    verdict = history_law.admit([])
    assert verdict.complete
    assert verdict.entries == ()


def test_the_order_is_the_callers_order(history_law: ProposalHistory) -> None:
    """The law does not sort: a prompt reads the history in an order."""
    verdict = history_law.admit([whole(NODE_B, PROPOSAL_B), whole(NODE_A, PROPOSAL_A)])
    assert [entry.node_id for entry in verdict.entries] == [NODE_B, NODE_A]


def test_the_success_sentence_opens_with_its_code(history_law: ProposalHistory) -> None:
    """An operator greps the admission by the feature's own word."""
    verdict = history_law.admit([whole(NODE_A, PROPOSAL_A)])
    assert verdict.detail.startswith(COMPLETE_HISTORY_CODE)


# ── "in full" — the per-entry clause ──────────────────────────────────────────


def test_a_cut_proposal_is_refused_by_recomputed_identity(
    history_law: ProposalHistory,
) -> None:
    """The load-bearing check: the text does not hash to the identity it claims.

    Nothing declares the cut — the entry carries the digest §9.1 recorded for
    the *whole* proposal, and the carried text is less than that.  A law that
    only read declarations would admit this.
    """
    verdict = history_law.admit(
        [whole(NODE_A, PROPOSAL_A[:20]) | {"code_hash": source_code_hash(PROPOSAL_A)}],
        prior_nodes=[NODE_A],
    )
    assert not verdict.complete
    assert verdict.reason is HistoryReason.TRUNCATED
    assert NODE_A in verdict.detail


def test_a_declared_truncation_is_refused(history_law: ProposalHistory) -> None:
    """A loader that admits the cut is refused too — the declaration is not a licence."""
    verdict = history_law.admit([{"node_id": NODE_A, "proposal": PROPOSAL_A, "truncated": True}])
    assert verdict.reason is HistoryReason.TRUNCATED
    assert verdict.detail.startswith(TRUNCATED_HISTORY_CODE)


@pytest.mark.parametrize(
    "key", ["cut", "cut_off", "elided", "incomplete", "partial", "truncated"]
)
def test_every_truncation_declaration_is_honoured(
    history_law: ProposalHistory, key: str
) -> None:
    """The spelled-out set, so a rename in the module is a failing test."""
    verdict = history_law.admit([{"node_id": NODE_A, "proposal": PROPOSAL_A, key: True}])
    assert verdict.reason is HistoryReason.TRUNCATED


def test_a_whole_flag_set_false_is_a_truncation(history_law: ProposalHistory) -> None:
    """``full: False`` is an explicit admission the read was partial."""
    verdict = history_law.admit([{"node_id": NODE_A, "proposal": PROPOSAL_A, "full": False}])
    assert verdict.reason is HistoryReason.TRUNCATED


def test_a_whole_flag_left_unset_is_not_a_truncation(
    history_law: ProposalHistory,
) -> None:
    """``full: None`` is a record that never filled the field in, not a cut read.

    Reading "unset" as "cut" would refuse every record type that carries the
    flag as optional, and the digest and the declared length still govern it.
    """
    verdict = history_law.admit([{"node_id": NODE_A, "proposal": PROPOSAL_A, "full": None}])
    assert verdict.complete


def test_a_declared_length_the_text_cannot_account_for_is_a_truncation(
    history_law: ProposalHistory,
) -> None:
    """The weaker fallback, for a record that carries no digest.

    Weaker by construction — it is the caller's own arithmetic about its own
    read — and it is why the digest is checked first.
    """
    verdict = history_law.admit(
        [{"node_id": NODE_A, "proposal": PROPOSAL_A[:10], "total_chars": len(PROPOSAL_A)}]
    )
    assert verdict.reason is HistoryReason.TRUNCATED


def test_a_declared_length_that_matches_is_not_a_truncation(
    history_law: ProposalHistory,
) -> None:
    """The fallback refuses a *gap*, not the presence of the field."""
    verdict = history_law.admit(
        [{"node_id": NODE_A, "proposal": PROPOSAL_A, "total": len(PROPOSAL_A)}]
    )
    assert verdict.complete


def test_a_declared_total_of_zero_is_not_believed(history_law: ProposalHistory) -> None:
    """``total: 0`` is not a length, and believing it would admit an empty read."""
    verdict = history_law.admit([{"node_id": NODE_A, "proposal": PROPOSAL_A, "total": 0}])
    assert verdict.complete


def test_a_boolean_total_is_not_believed(history_law: ProposalHistory) -> None:
    """``True`` is an ``int`` in Python; reading it as ``1`` manufactures a cut.

    The same affinity trap ``locate_defect`` guards at the diagnosis seam.
    """
    verdict = history_law.admit([{"node_id": NODE_A, "proposal": PROPOSAL_A, "total": True}])
    assert verdict.complete


def test_a_lone_truncated_entry_is_refused_even_with_no_declared_priors(
    history_law: ProposalHistory,
) -> None:
    """Check 2 does not depend on the caller having declared anything.

    ``prior_nodes`` is optional, so a caller that omits it must still be
    protected from a cut read — otherwise the law's strongest check would be
    reachable only through the weakest one.
    """
    verdict = history_law.admit([{"node_id": NODE_A, "proposal": PROPOSAL_A, "truncated": True}])
    assert verdict.reason is HistoryReason.TRUNCATED


# ── "not a sample" — the set clause ───────────────────────────────────────────


@pytest.mark.parametrize(
    "key",
    [
        "dropped",
        "excluded",
        "first_n",
        "head",
        "last_n",
        "limit",
        "omitted",
        "recent",
        "recent_only",
        "sample",
        "sampled",
        "sampled_from",
        "slice",
        "summary",
        "summary_of",
        "tail",
        "trimmed",
    ],
)
def test_every_sampling_declaration_is_refused(history_law: ProposalHistory, key: str) -> None:
    """The spelled-out set: a loader that took a rule-selected subset says so."""
    verdict = history_law.admit([{"node_id": NODE_A, "proposal": PROPOSAL_A, key: "recent"}])
    assert verdict.reason is HistoryReason.SAMPLED
    assert verdict.detail.startswith(SAMPLED_HISTORY_CODE)


def test_a_summary_of_a_proposal_is_a_sample_not_a_truncation(
    history_law: ProposalHistory,
) -> None:
    """§14.1:773's boundary: compressing one proposal into prose *is* sampling it.

    The repair is "fetch the proposal", not "finish the read" — which is why
    the two are separate reasons.
    """
    verdict = history_law.admit(
        [{"node_id": NODE_A, "proposal": "a summary of the proposal", "summary_of": NODE_A}]
    )
    assert verdict.reason is HistoryReason.SAMPLED


def test_an_empty_sampling_declaration_is_not_a_loss(
    history_law: ProposalHistory,
) -> None:
    """``dropped: []`` describes an operation the loader did not perform.

    Truthiness rather than presence for the declarations: refusing on the field
    *name* would refuse a record for its schema.
    """
    verdict = history_law.admit([{"node_id": NODE_A, "proposal": PROPOSAL_A, "dropped": []}])
    assert verdict.complete


def test_sampled_is_preferred_to_truncated_when_both_are_declared(
    history_law: ProposalHistory,
) -> None:
    """A loader that took the last N *and* cut them is describing a subset.

    The subset is the repair a reader acts on without re-reading anything.
    """
    verdict = history_law.admit(
        [
            {
                "node_id": NODE_A,
                "proposal": PROPOSAL_A,
                "last_n": 3,
                "truncated": True,
            }
        ]
    )
    assert verdict.reason is HistoryReason.SAMPLED


def test_a_declared_prior_that_no_entry_covers_is_refused(
    history_law: ProposalHistory,
) -> None:
    """The set check: the round said two proposals, one was handed over."""
    verdict = history_law.admit(
        [whole(NODE_A, PROPOSAL_A)], prior_nodes=[NODE_A, NODE_B]
    )
    assert verdict.reason is HistoryReason.MISSING
    assert verdict.detail.startswith(MISSING_PROPOSAL_CODE)
    assert NODE_B in verdict.detail


def test_the_hole_is_named_and_the_covered_node_is_not(
    history_law: ProposalHistory,
) -> None:
    """The sentence is a repair, so it names the missing node specifically."""
    verdict = history_law.admit(
        [whole(NODE_A, PROPOSAL_A)], prior_nodes=[NODE_A, NODE_B]
    )
    assert NODE_B in verdict.offenders
    assert NODE_A not in verdict.offenders


def test_a_declared_prior_is_matched_by_canonical_identity(
    history_law: ProposalHistory,
) -> None:
    """Two spellings of one node are one node — braces, case, ``urn:uuid:``.

    Otherwise a caller whose tree spelled the id differently from its own query
    would be refused for a hole that is not there.
    """
    verdict = history_law.admit(
        [whole(NODE_A, PROPOSAL_A)], prior_nodes=[NODE_A.upper().replace("-", "")]
    )
    assert verdict.complete


def test_a_name_that_is_not_a_uuid_is_kept_as_written(
    history_law: ProposalHistory,
) -> None:
    """A history from before ids were UUIDs is still a history."""
    verdict = history_law.admit(
        [{"node_id": "node-7", "proposal": PROPOSAL_A}], prior_nodes=["node-7"]
    )
    assert verdict.complete


# ── The silent drop ───────────────────────────────────────────────────────────


def test_a_named_entry_with_no_text_and_no_declaration_is_refused(
    history_law: ProposalHistory,
) -> None:
    """The loophole this law exists to close.

    "I have this node's identity and none of its proposal" has no admitted
    reading — an entry with an id and no text is a proposal that was dropped,
    and calling it an empty proposal would let a loader drop every proposal it
    did not want the agent to see.
    """
    verdict = history_law.admit([{"node_id": NODE_A}], prior_nodes=[NODE_A])
    assert verdict.reason is HistoryReason.MISSING
    assert NODE_A in verdict.detail


def test_the_silent_drop_is_found_without_any_declared_priors(
    history_law: ProposalHistory,
) -> None:
    """Check 2 again, on the drop path: an id with no text is not a history."""
    verdict = history_law.admit([{"node_id": NODE_A}])
    assert verdict.reason is HistoryReason.MISSING


def test_an_unreadable_entry_is_refused_rather_than_admitted(
    history_law: ProposalHistory,
) -> None:
    """A number in the sequence is not a prior proposal.

    Refused, never skipped: a law that silently ignored what it could not read
    would admit a history missing exactly the entries it failed on.
    """
    verdict = history_law.admit([42], prior_nodes=[])
    assert verdict.reason is HistoryReason.MISSING
    assert "prior-0" in verdict.detail


def test_an_unreadable_entry_that_named_itself_is_named_in_the_sentence(
    history_law: ProposalHistory,
) -> None:
    """A named entry the law could not read names the node, not a position.

    "We have n1's identity and none of its proposal" is fixed by fetching n1,
    and a sentence that said ``prior-0`` would send its reader elsewhere.
    """
    verdict = history_law.admit([{"node_id": NODE_A, "full": None, "recent": 0}])
    assert NODE_A in verdict.detail or verdict.reason is HistoryReason.MISSING


# ── "not a history at all" ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "not_a_history",
    ["a prior proposal", b"bytes", None, 7, {"node_id": NODE_A, "proposal": PROPOSAL_A}],
)
def test_something_that_is_not_a_history_is_refused(
    history_law: ProposalHistory, not_a_history: object
) -> None:
    """A bare string and a lone mapping are **one** entry, not a history.

    Reading either as a one-proposal history that happens to be complete would
    admit precisely the truncated sample §14.1's *"not a sample"* names — the
    caller handed a proposal where a sequence of proposals belongs.
    """
    verdict = history_law.admit(not_a_history)
    assert verdict.reason is HistoryReason.NOT_A_HISTORY
    assert verdict.detail.startswith(NOT_A_HISTORY_CODE)
    assert not verdict.complete


def test_the_not_a_history_sentence_names_the_type_received(
    history_law: ProposalHistory,
) -> None:
    """The caller's wiring is what is wrong, so the sentence says what arrived."""
    verdict = history_law.admit("a prior proposal")
    assert "str" in verdict.detail


# ── The shape of the refusal ──────────────────────────────────────────────────


def test_a_refusal_carries_no_entries(history_law: ProposalHistory) -> None:
    """The prefix a law read before it found the hole *is* a sample.

    Returning it would let a caller propose from exactly the history this
    feature exists to refuse.
    """
    verdict = history_law.admit(
        [whole(NODE_A, PROPOSAL_A), {"node_id": NODE_B, "proposal": PROPOSAL_B, "truncated": True}]
    )
    assert not verdict.complete
    assert verdict.entries == ()


def test_the_refusal_reason_is_the_first_offence_in_the_callers_order(
    history_law: ProposalHistory,
) -> None:
    """A reader of the history hits the first hole first.

    The sampled entry is second, the truncated one first — so the truncated
    reason is the one reported, and the sentence still names both.
    """
    verdict = history_law.admit(
        [
            {"node_id": NODE_A, "proposal": PROPOSAL_A, "truncated": True},
            {"node_id": NODE_B, "proposal": PROPOSAL_B, "sampled_from": "recent"},
        ]
    )
    assert verdict.reason is HistoryReason.TRUNCATED
    assert NODE_A in verdict.detail
    assert NODE_B in verdict.detail


def test_the_sentence_names_every_offence_bounded(
    history_law: ProposalHistory,
) -> None:
    """Bounded and counted: a thousand dropped proposals is a message nobody reads."""
    offenders = [f"node-{n}" for n in range(MAX_LISTED_OFFENDERS + 4)]
    verdict = history_law.admit(
        [{"node_id": name, "proposal": PROPOSAL_A, "truncated": True} for name in offenders]
    )
    assert "and 4 more" in verdict.detail
    assert len(verdict.offenders) == MAX_LISTED_OFFENDERS + 4


def test_the_listed_offenders_are_deduplicated_and_sorted(
    history_law: ProposalHistory,
) -> None:
    """The count is of distinct offences: an inflated number is a misleading one."""
    verdict = history_law.admit(
        [
            {"node_id": NODE_B, "proposal": PROPOSAL_B, "truncated": True},
            {"node_id": NODE_A, "proposal": PROPOSAL_A, "truncated": True},
            {"node_id": NODE_B, "proposal": PROPOSAL_B, "truncated": True},
        ]
    )
    assert list(verdict.offenders) == sorted({NODE_A, NODE_B})


def test_a_refusal_never_quotes_the_proposal_text(history_law: ProposalHistory) -> None:
    """The text of a proposal belongs in §9.2's artifact directory, not a log line."""
    verdict = history_law.admit(
        [{"node_id": NODE_A, "proposal": PROPOSAL_A, "truncated": True}]
    )
    assert PROPOSAL_A not in verdict.detail


def test_the_offending_entries_are_named(history_law: ProposalHistory) -> None:
    """A refusal that named nothing would not be a repair."""
    verdict = history_law.admit(
        [{"node_id": NODE_A, "proposal": PROPOSAL_A, "truncated": True}]
    )
    assert NODE_A in verdict.offenders


# ── The value shapes ──────────────────────────────────────────────────────────


def test_every_code_is_its_own_reasons_value() -> None:
    """Branching on the value and grepping for it are the same string."""
    assert HistoryReason.TRUNCATED == TRUNCATED_HISTORY_CODE
    assert HistoryReason.SAMPLED == SAMPLED_HISTORY_CODE
    assert HistoryReason.MISSING == MISSING_PROPOSAL_CODE
    assert HistoryReason.NOT_A_HISTORY == NOT_A_HISTORY_CODE


def test_complete_is_the_one_reason_whose_detail_opens_differently() -> None:
    """The documented asymmetry: an admission is not a code an operator greps for.

    ``AntiConvergenceReason.NOVEL`` has the same one, against ``NOVEL_CODE``.
    """
    assert HistoryReason.COMPLETE == "complete"
    assert COMPLETE_HISTORY_CODE != HistoryReason.COMPLETE


def test_complete_is_computed_from_the_reason_and_not_passed_in() -> None:
    """A verdict cannot disagree with its own reason."""
    from signal_agent import HistoryVerdict

    assert HistoryVerdict(HistoryReason.COMPLETE, "x").complete is True
    assert HistoryVerdict(HistoryReason.TRUNCATED, "x").complete is False
    assert HistoryVerdict(HistoryReason.TRUNCATED, "x").entries == ()


def test_complete_agrees_with_admit(history_law: ProposalHistory) -> None:
    """The two methods cannot disagree: one is defined as a read of the other."""
    whole_history = [whole(NODE_A, PROPOSAL_A)]
    cut = [{"node_id": NODE_A, "proposal": PROPOSAL_A, "truncated": True}]
    assert history_law.complete(whole_history) is history_law.admit(whole_history).complete
    assert history_law.complete(cut) is history_law.admit(cut).complete


def test_a_bare_string_of_declared_priors_is_one_node(history_law: ProposalHistory) -> None:
    """Documented at ``_held_digests``: a bare string is one thing, not characters.

    Getting this wrong would refuse a one-node history for missing ``n``,
    ``o``, ``d``, ``e``.
    """
    verdict = history_law.admit([whole(NODE_A, PROPOSAL_A)], prior_nodes=NODE_A)
    assert verdict.complete


def test_a_prior_proposal_is_named_positionally_when_it_names_nothing(
    history_law: ProposalHistory,
) -> None:
    """A bare string entry has no id to be named by, so it is ``prior-<n>``."""
    verdict = history_law.admit(["a proposal with no identity at all"])
    assert verdict.complete
    assert verdict.entries[0].node_id == "prior-0"


def test_a_pair_is_read_positionally(history_law: ProposalHistory) -> None:
    """``(node_id, proposal)`` — the shape a caller with no record type reaches for."""
    verdict = history_law.admit([(NODE_A, PROPOSAL_A)], prior_nodes=[NODE_A])
    assert verdict.complete
    assert verdict.entries[0].proposal == PROPOSAL_A


def test_a_triple_carries_the_identity_too(history_law: ProposalHistory) -> None:
    """``(node_id, proposal, code_hash)`` — and the digest is checked like any other."""
    verdict = history_law.admit(
        [(NODE_A, PROPOSAL_A[:8], source_code_hash(PROPOSAL_A))], prior_nodes=[NODE_A]
    )
    assert verdict.reason is HistoryReason.TRUNCATED


def test_a_record_types_declarations_are_read_as_a_mappings_are(
    history_law: ProposalHistory,
) -> None:
    """The duck-typed seam: a caller's own record type must be judged the same.

    The law reads fields by name from a mapping key *or* an attribute, so a
    loader that hands over ``Record(node_id=..., truncated=True)`` must be
    refused exactly as the equivalent dict is.  Reading only mappings would
    make the whole judgment depend on which shape the caller's loader produced
    — and the loader most likely to hand over a typed record is the one that
    truncates.
    """

    class Record:
        """A record type with the fields this law knows, and no others."""

        def __init__(self, node_id, proposal="", code_hash="", **extra) -> None:
            self.node_id = node_id
            self.proposal = proposal
            self.code_hash = code_hash
            for name, value in extra.items():
                setattr(self, name, value)

    assert history_law.admit([Record(NODE_A, PROPOSAL_A)]).complete
    assert (
        history_law.admit([Record(NODE_A, PROPOSAL_A, truncated=True)]).reason
        is HistoryReason.TRUNCATED
    )
    assert (
        history_law.admit([Record(NODE_A, PROPOSAL_A, sampled_from="recent")]).reason
        is HistoryReason.SAMPLED
    )
    assert (
        history_law.admit([Record(NODE_A, PROPOSAL_A, full=False)]).reason
        is HistoryReason.TRUNCATED
    )
    assert (
        history_law.admit([Record(NODE_A, PROPOSAL_A, total_chars=99)]).reason
        is HistoryReason.TRUNCATED
    )
    assert history_law.admit([Record(NODE_A)]).reason is HistoryReason.MISSING


def test_a_record_type_carrying_only_identity_is_still_read(
    history_law: ProposalHistory,
) -> None:
    """Recognition is *any* known field, not all of them.

    A record type that declares ``node_id`` and nothing else is a proposal
    whose text this law cannot find — which is the silent drop, named.  If
    recognition demanded every field, this entry would be an *unreadable* one
    and the sentence would name ``prior-0`` instead of the node the caller
    itself wrote down.
    """

    class IdentityOnly:
        def __init__(self, node_id) -> None:
            self.node_id = node_id

    verdict = history_law.admit([IdentityOnly(NODE_A)])
    assert verdict.reason is HistoryReason.MISSING
    assert NODE_A in verdict.detail


def test_the_declaration_sets_are_read_in_a_stable_order(
    history_law: ProposalHistory,
) -> None:
    """An entry carrying both a sampling and a truncation key is decided the same way twice.

    The sets are iterated sorted rather than in set order, so two runs over the
    same history produce the same sentence — a refusal an operator diffs
    between rounds must not move because a hash seed did.
    """
    entry = {
        "node_id": NODE_A,
        "proposal": PROPOSAL_A,
        "last_n": 3,
        "truncated": True,
    }
    reasons = {history_law.admit([entry]).reason for _ in range(20)}
    assert reasons == {HistoryReason.SAMPLED}


def test_a_bare_string_entry_is_one_entry_not_characters(
    history_law: ProposalHistory,
) -> None:
    """The same documented ambiguity as ``prior_nodes``, on the entry side."""
    verdict = history_law.admit(["abc"])
    assert len(verdict.entries) == 1
    assert verdict.entries[0].proposal == "abc"


# ── ``require`` and the error ─────────────────────────────────────────────────


def test_require_raises_on_the_refused_path(history_law: ProposalHistory) -> None:
    """The one place this law raises."""
    verdict = history_law.admit([{"node_id": NODE_A, "proposal": PROPOSAL_A, "truncated": True}])
    with pytest.raises(TruncatedHistoryError) as raised:
        verdict.require()
    assert raised.value.args[0] == verdict.detail


def test_the_error_is_not_reachable_through_the_source_contract() -> None:
    """The asymmetry: a caller's ``except AgentSourceError`` must not catch it.

    That handler repairs by re-prompting the agent, and re-prompting against a
    cut history buys another proposal from the same cut history.
    """
    from signal_agent import AgentSourceError, FlawedMechanismError

    assert issubclass(TruncatedHistoryError, Exception)
    assert not issubclass(TruncatedHistoryError, AgentSourceError)
    assert not issubclass(TruncatedHistoryError, FlawedMechanismError)


def test_the_error_is_in_the_members_vocabulary() -> None:
    """Catchable as the member's own base, like every other refusal here."""
    from signal_agent import SignalAgentError

    assert issubclass(TruncatedHistoryError, SignalAgentError)


def test_the_error_message_opens_with_the_reasons_code(
    history_law: ProposalHistory,
) -> None:
    """A campaign log and an operator's grep say the same thing."""
    verdict = history_law.admit([{"node_id": NODE_A, "proposal": PROPOSAL_A, "truncated": True}])
    with pytest.raises(TruncatedHistoryError) as raised:
        verdict.require()
    assert str(raised.value).startswith(TRUNCATED_HISTORY_CODE)


@pytest.mark.parametrize(
    ("history", "prior_nodes", "code"),
    [
        ([{"node_id": NODE_A, "proposal": PROPOSAL_A, "truncated": True}], (), TRUNCATED_HISTORY_CODE),
        ([{"node_id": NODE_A, "proposal": PROPOSAL_A, "sample": "x"}], (), SAMPLED_HISTORY_CODE),
        ([{"node_id": NODE_A}], (), MISSING_PROPOSAL_CODE),
        ("not a history", (), NOT_A_HISTORY_CODE),
    ],
)
def test_each_reason_opens_its_own_sentence(
    history_law: ProposalHistory, history: object, prior_nodes: tuple, code: str
) -> None:
    """Four reasons, four headlines — a refusal never opens with another's."""
    verdict = history_law.admit(history, prior_nodes=prior_nodes)
    assert verdict.detail.startswith(code)


# ── The law's own shape ───────────────────────────────────────────────────────


def test_the_law_is_stateless() -> None:
    """No per-run state to keep in step with the tree — the gates' own shape."""
    assert ProposalHistory.__slots__ == ()


def test_the_law_admit_never_raises(history_law: ProposalHistory) -> None:
    """A caller measuring handed history cannot do that through a raise."""
    for refusal in ("not a history", [{"node_id": NODE_A}], [42], [{"node_id": NODE_A, "proposal": "x", "cut": 1}]):
        assert isinstance(history_law.admit(refusal).complete, bool)


def test_the_history_constructor_refuses_nothing() -> None:
    """Wholeness is ``admit``'s judgment, not the value's.

    An entry handed over cut is a fact to refuse, and a constructor that raised
    on it would make the law's own verdict unreachable for the common case
    where the caller built the value first and asked afterwards.
    """
    from signal_agent import PriorProposal

    assert PriorProposal(NODE_A, "").node_id == NODE_A


def test_a_prior_proposal_compares_by_parts_not_by_class() -> None:
    """The loader imports every member twice, so ``isinstance`` would be false.

    Equality over the parts is the same statement and survives that — the
    discipline every cross-import value in this workspace follows.
    """
    from signal_agent import PriorProposal

    class Impostor:
        """A value built from the other import of the same file."""

        def __init__(self) -> None:
            self.node_id = NODE_A
            self.proposal = PROPOSAL_A
            self.code_hash = source_code_hash(PROPOSAL_A)

    assert PriorProposal(NODE_A, PROPOSAL_A, source_code_hash(PROPOSAL_A)) == Impostor()


def test_a_prior_proposal_does_not_equal_an_unrelated_value() -> None:
    """``NotImplemented`` from the comparison, so ``==`` answers ``False``."""
    from signal_agent import PriorProposal

    assert PriorProposal(NODE_A, PROPOSAL_A) != 7
