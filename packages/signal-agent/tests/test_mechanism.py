"""Feature 211's suite: the stated mechanism, persisted and never scored.

app_spec.xml, "Hypothesis Authoring Agent", feature 211: *System persists a
stated mechanism string used for deduplication and human review, never as a
scored input.*

The sentence is four claims and this file takes them one at a time, because they
fail in four different ways and a suite that tested "the feature" would let
three of them be true while the fourth was not:

* **the stated mechanism string** — the agent's own rationale, stored *verbatim*
  while compared canonically.  Tested from both sides: the column keeps exactly
  what the agent wrote, and two spellings of one claim compare equal.
* **persists** — the write, and every way it can be honest or dishonest about
  what the row holds.  The four states a row can be in, each answered
  differently.
* **used for deduplication and human review** — the two readers.  The dedup
  *report* (which excludes nothing and names every holder) and the review read
  (which answers what has been claimed, and deliberately claims no review
  workflow).
* **never as a scored input** — the barrier.  Structurally: no numeric surface
  on the record, the digest is a ``str`` and not a magnitude, the verdict has one
  value, and the exception bridge refuses unconditionally.

The last of the four is the one that would be silently lost, because it is the
only one that is a *prohibition* rather than a capability: nothing about the
system would break if a caller scored a mechanism, and every other test in this
file would still pass.  So it gets the most direct treatment — the absences are
pinned as absences, and the reason they are pinned is stated beside each one.

**The fixtures bring a real schema.**  ``mechanism_database`` runs ``0118`` and
``0117`` by file path — see ``conftest.py`` — so every claim about the column
is a claim about the column the migration creates rather than about one this
suite invented.  Nothing here hand-writes ``CREATE TABLE node``.
"""

from __future__ import annotations

import sqlite3

import pytest
import signal_agent as member
from conftest import plant_node, sqlite_path_of
from signal_agent import (
    NEVER_SCORED_CODE,
    NOT_A_STATEMENT_CODE,
    STATED_MECHANISM_CODE,
    MechanismColumnError,
    MechanismConflictError,
    MechanismNodeNotRecordedError,
    MechanismNotScoredError,
    MechanismReason,
    MechanismRecord,
    MechanismScoredInput,
    MechanismStatementError,
    MechanismStore,
    MechanismStoreUnavailableError,
    StatedMechanism,
    canonical_mechanism,
    mechanism_digest,
    stated_mechanism,
)

#: A rationale of the shape the authoring side actually produces: a sentence
#: naming an economic mechanism, not a label.  Spelled once at module scope
#: because several claims are *about the text itself* — it is stored verbatim,
#: its canonical form is a comparison key — and a fixture that rebuilt it per
#: test would make "the same mechanism" a claim about two constructions rather
#: than about one string.
_MOMENTUM = (
    "Cross-sectional momentum decays after liquidity shocks; buy the "
    "laggards once the spread normalises."
)

#: A second, genuinely different mechanism.  The dedup read is only worth
#: testing against a mechanism it should *not* match, or "it found the one
#: node in the tree" would pass on a read that returned every row.
_REVERSION = "Overnight mean reversion in the front month after a limit move."


# ── The first claim: the stated mechanism string ──────────────────────────────


def test_the_column_is_kept_verbatim_while_the_comparison_is_canonical(
    mechanism_store: MechanismStore,
    mechanism_database: str,
) -> None:
    # The feature's central restraint, and both halves are asserted together
    # because either alone would be satisfied by the wrong implementation.
    # ``canonical_mechanism`` exists for the *dedup comparison*; the column
    # keeps what the agent wrote.  A store that canonicalised on the way in
    # would pass the second half of this test and fail the first — and it would
    # be rewriting the agent's claim rather than recording it, which is the one
    # thing §9.1's "human review" clause cannot tolerate.
    written = "  Cross-Sectional   Momentum\nDecays after liquidity shocks.  "
    node = plant_node(mechanism_database)
    recorded = mechanism_store.persist(node, written)

    assert recorded.statement == written, "the column keeps the agent's text"
    assert recorded.digest == mechanism_digest(written)
    # And the row really holds it — read the column raw, past the store's own
    # reporting, so this is a claim about the database rather than about the
    # value the store handed back.
    with sqlite3.connect(sqlite_path_of(mechanism_database)) as connection:
        (stored,) = connection.execute(
            "SELECT stated_mechanism FROM node WHERE id = ?", (node,)
        ).fetchone()
    assert stored == written


def test_two_spellings_of_one_claim_are_one_mechanism() -> None:
    # §9.1 annotates the column ``-- dedup ...``, and deduplication over free
    # text is only meaningful if formatting does not decide the answer.  The
    # three normalizations are asserted one at a time, and the fourth thing —
    # what is deliberately *not* normalized — right after.
    assert canonical_mechanism("Momentum decays") == canonical_mechanism(
        "  momentum   decays  "
    )
    assert canonical_mechanism("MOMENTUM DECAYS") == canonical_mechanism(
        "momentum decays"
    )
    assert canonical_mechanism("momentum\tdecays") == canonical_mechanism(
        "momentum\ndecays"
    )
    assert mechanism_digest("Momentum  decays") == mechanism_digest(
        " momentum decays "
    )


def test_no_semantic_equivalence_is_invented() -> None:
    # The restraint, pinned as a *refusal to merge* rather than as a comment.
    # Each pair below is one a stemming, a stop-word list or a synonym map would
    # fold together — and folding them would hide a hypothesis from the human
    # review the same sentence asks for.  The asymmetry decides it: a miss costs
    # a reviewer one extra line, a false merge hides a hypothesis.
    assert mechanism_digest("momentum, decayed") != mechanism_digest(
        "momentum decays"
    )
    assert mechanism_digest("the momentum factor") != mechanism_digest(
        "momentum factor"
    )
    assert mechanism_digest("momentum reversal") != mechanism_digest("reversal")


def test_a_non_string_is_refused_before_anything_is_derived() -> None:
    for value in (b"momentum", 7, 3.5, ["momentum"], {"a": 1}, object()):
        with pytest.raises(MechanismStatementError) as refusal:
            canonical_mechanism(value)
        assert "must be text" in str(refusal.value)
    # And the digest refuses by the same path rather than hashing a repr: a
    # digest of ``repr(value)`` would make two different objects with equal
    # reprs one mechanism.
    with pytest.raises(MechanismStatementError):
        mechanism_digest(7)


def test_the_record_reports_the_words_a_review_line_can_emit() -> None:
    node_id = "0" * 8 + "-0000-0000-0000-" + "0" * 12
    long_enough = " ".join(f"w{index}" for index in range(100))
    record = MechanismRecord(
        node_id=node_id,
        reason=MechanismReason.STATED,
        detail="d",
        statement=long_enough,
    )
    # Bounded, so a pathological submission cannot make a review queue's line
    # unbounded — the column still keeps everything, which is the point of the
    # bound being on the *summary*.
    assert len(record.words) == member.CANONICAL_MECHANISM_MAX_WORDS
    assert record.statement == long_enough
    assert record.words[0] == "w0"


# ── The second claim: persists ────────────────────────────────────────────────


def test_persist_writes_the_row_that_held_nothing(
    mechanism_store: MechanismStore, mechanism_database: str
) -> None:
    node = plant_node(mechanism_database)
    recorded = mechanism_store.persist(node, _MOMENTUM)
    assert recorded.recorded is True
    assert recorded.reason is MechanismReason.STATED
    assert recorded.stated is True
    assert recorded.statement == _MOMENTUM
    assert recorded.detail.startswith(STATED_MECHANISM_CODE)


def test_an_idempotent_retry_writes_nothing_and_says_so(
    mechanism_store: MechanismStore, mechanism_database: str
) -> None:
    # §14 demands retry-safe writes of the workers this runs on.  The retry is
    # recognized by *canonical* equality, so a re-statement in different
    # formatting is the same mechanism — and the record reports the row's
    # spelling rather than the caller's, because the row's is what a reviewer
    # will read.  A record that reported the caller's would be reporting a value
    # that is nowhere in the tree.
    node = plant_node(mechanism_database)
    first = mechanism_store.persist(node, _MOMENTUM)
    retry = mechanism_store.persist(node, f"  {_MOMENTUM.upper()}  ")

    assert first.recorded is True
    assert retry.recorded is False, "a retry must not claim to have written"
    assert retry.statement == _MOMENTUM, "the row's spelling, not the caller's"
    assert retry.reason is MechanismReason.STATED
    # And the row is unchanged, raw.
    with sqlite3.connect(sqlite_path_of(mechanism_database)) as connection:
        (stored,) = connection.execute(
            "SELECT stated_mechanism FROM node WHERE id = ?", (node,)
        ).fetchone()
    assert stored == _MOMENTUM


def test_a_different_mechanism_on_one_node_is_refused(
    mechanism_store: MechanismStore, mechanism_database: str
) -> None:
    # A node's stated mechanism is history: it is what a reviewer read and what
    # the dedup pass compared against when the node's scores were recorded.
    # Replacing it would leave every stored comparison referring to a claim the
    # row no longer makes.  Both statements are named.
    node = plant_node(mechanism_database)
    mechanism_store.persist(node, _MOMENTUM)
    with pytest.raises(MechanismConflictError) as refusal:
        mechanism_store.persist(node, _REVERSION)
    message = str(refusal.value)
    assert _MOMENTUM in message and _REVERSION in message
    # And the row still holds the first.
    assert mechanism_store.load(node).statement == _MOMENTUM  # type: ignore[union-attr]


def test_a_row_holding_a_mechanism_cannot_be_cleared(
    mechanism_store: MechanismStore, mechanism_database: str
) -> None:
    # ``persist(node, None)`` writes the unstated NULL, but only onto a row that
    # holds nothing.  The nullability exists so an agent that states no
    # mechanism is recorded honestly, not so one that stated a mechanism can
    # have it erased — and the erase is reachable by accident (a caller that
    # lost a value on the way here) rather than by decision, which is why it is
    # refused rather than quietly recorded.
    node = plant_node(mechanism_database)
    mechanism_store.persist(node, _MOMENTUM)
    for clearing in (None, "", "   ", "\n\t"):
        with pytest.raises(MechanismStatementError) as refusal:
            mechanism_store.persist(node, clearing)
        assert "states nothing" in str(refusal.value)
    assert mechanism_store.load(node).statement == _MOMENTUM  # type: ignore[union-attr]


def test_a_node_that_states_no_mechanism_is_recorded_as_a_null(
    mechanism_store: MechanismStore, mechanism_database: str
) -> None:
    # The nullable column's whole purpose.  ``None`` and blank text are the same
    # proposal-level fact — the agent stated nothing — so both land as the same
    # NULL, and the record reports that positively rather than as a failure.
    # 0117's own words: an agent that states no mechanism has left nothing to
    # review, and a NULL records that rather than fabricating a rationale.
    stated_node = plant_node(mechanism_database)
    blank_node = plant_node(mechanism_database)

    for node, offered in ((stated_node, None), (blank_node, "   \n ")):
        recorded = mechanism_store.persist(node, offered)
        # ``recorded`` is **False**: a NULL and an offer of nothing are the same
        # state, and the column is already in it, so this call changed nothing.
        # ``False`` rather than ``True`` is the honest answer to *did this call
        # write?*, and it is what keeps a caller from reporting a change that
        # did not happen.
        assert recorded.recorded is False
        assert recorded.reason is MechanismReason.NOT_A_STATEMENT
        assert recorded.stated is False
        assert recorded.statement is None
        assert recorded.digest is None
        assert recorded.words == ()
        assert recorded.detail.startswith(NOT_A_STATEMENT_CODE)
        # And the row really holds a NULL rather than an empty string, which is
        # the difference between "states nothing" and "states whitespace".
        with sqlite3.connect(sqlite_path_of(mechanism_database)) as connection:
            (stored,) = connection.execute(
                "SELECT stated_mechanism FROM node WHERE id = ?", (node,)
            ).fetchone()
        assert stored is None


def test_the_unstated_write_is_idempotent_and_re_reads_as_unstated(
    mechanism_store: MechanismStore, mechanism_database: str
) -> None:
    # The unstated state round-trips: whatever wrote the NULL, a reader sees
    # "this row records no mechanism" rather than "the read failed" or "no such
    # node".  Three-way distinction, which is the only thing that makes the
    # NULL usable.
    node = plant_node(mechanism_database)
    assert mechanism_store.load(node) is None, "a fresh row states nothing"
    first = mechanism_store.persist(node, None)
    assert first.recorded is False, "the NULL was already the row's state"
    assert mechanism_store.load(node) is None
    # And a second unstated write answers identically, for the same reason: the
    # NULL is already the fact, and there is nothing for a second call to
    # change.  Nothing distinguishes a fresh row from one an earlier call
    # reported as unstated, and nothing should.
    again = mechanism_store.persist(node, None)
    assert again.recorded is False
    assert again.reason is MechanismReason.NOT_A_STATEMENT
    assert again.detail == first.detail


def test_a_non_statement_ask_is_refused_without_touching_the_database(
    mechanism_store: MechanismStore, mechanism_database: str
) -> None:
    node = plant_node(mechanism_database)
    for value in (7, 3.5, ["momentum"], {"mechanism": "x"}, object()):
        with pytest.raises(MechanismStatementError) as refusal:
            mechanism_store.persist(node, value)
        assert "caller's wiring" in str(refusal.value)
    # Nothing was written, and the refusal happened before the database was
    # reached — the row is still unstated.
    assert mechanism_store.load(node) is None


def test_a_node_the_tree_does_not_hold_is_refused_on_both_paths(
    mechanism_store: MechanismStore,
) -> None:
    # A stated mechanism is a *column on a node*.  Persisting one for an id the
    # tree does not hold would mean writing a row, and the node table is the
    # discovery tree's rather than this member's.  Both the write path and the
    # read path refuse by name, with different wording — a caller reading a log
    # needs to know which it was about to do.
    absent = "11111111-2222-3333-4444-555555555555"
    with pytest.raises(MechanismNodeNotRecordedError) as write_refusal:
        mechanism_store.persist(absent, _MOMENTUM)
    assert "would mean writing a *row*" in str(write_refusal.value)

    with pytest.raises(MechanismNodeNotRecordedError) as read_refusal:
        mechanism_store.load(absent)
    assert "load() reads one node's stated mechanism" in str(read_refusal.value)


def test_a_missing_column_is_refused_by_naming_the_revision(
    unstated_database: str,
) -> None:
    # The store probes the table rather than letting SQLite raise "no such
    # column": a mechanism has a documented prerequisite and the refusal should
    # say which.  Both depths of the same gap are one class, so an operator
    # reading it knows the repair either way.
    store = MechanismStore(unstated_database)
    # No ``plant_node``: the tree this fixture builds stops at ``0118``, so it
    # has the five structural columns and none of the identity triple — which is
    # the state under test, and a planted row would need the very columns whose
    # absence is the point.
    node = "99999999-aaaa-bbbb-cccc-dddddddddddd"
    with pytest.raises(MechanismColumnError) as refusal:
        store.persist(node, _MOMENTUM)
    assert member.MECHANISM_POLICY_REVISION in str(refusal.value)
    assert member.MECHANISM_COLUMN in str(refusal.value)


def test_a_database_with_no_node_table_is_refused_by_the_same_class(
    mechanism_database_url: str,
) -> None:
    # The other depth of the same fact: the file exists and has never been
    # migrated at all.  Same class, same revision named — a missing table and a
    # missing column are one deployment problem seen at two depths, and both
    # repairs are the same chain of migrations.
    store = MechanismStore(mechanism_database_url)
    with pytest.raises(MechanismColumnError) as refusal:
        store.stated()
    assert "no node table" in str(refusal.value)
    assert member.MECHANISM_POLICY_REVISION in str(refusal.value)


def test_a_malformed_node_id_is_refused_as_the_callers_addressing_value(
    mechanism_store: MechanismStore,
) -> None:
    # The id is the *caller's* value, not a fact about a database, so no
    # deployment class would be an honest report and none is used.  Both a
    # non-UUID string and a non-string are refused.
    for value in ("not-a-uuid", "", "   ", 7, None, object()):
        with pytest.raises(MechanismStatementError) as refusal:
            mechanism_store.persist(value, _MOMENTUM)
        assert "is not a UUID" in str(refusal.value)
    # A ``uuid.UUID`` and its text are the same node, normalized so a mixed-case
    # key cannot make one node look like two.
    import uuid

    identifier = uuid.uuid4()
    for spelling in (identifier, str(identifier), str(identifier).upper()):
        assert member._mechanism._validated_node_id(spelling) == str(identifier)


# ── The third claim: deduplication and human review ───────────────────────────


def test_duplicates_names_every_holder_including_a_different_code_hash(
    mechanism_store: MechanismStore, mechanism_database: str
) -> None:
    # The reason this read exists at all.  Architecture §14.1's root failure
    # mode is the agent reformulating one hypothesis in different code: a code
    # hash — feature 179's key — is structurally blind to that, because the
    # source really is different.  The claim is not.  So two nodes with
    # *different* code hashes and one stated mechanism are exactly what this
    # reports, and the code hashes here differ to make that the test.
    first = plant_node(mechanism_database, code_hash="a" * 64)
    second = plant_node(mechanism_database, code_hash="b" * 64)
    other = plant_node(mechanism_database)
    shouted = f"  {_MOMENTUM.upper()}  "
    mechanism_store.persist(first, _MOMENTUM)
    mechanism_store.persist(second, shouted)
    mechanism_store.persist(other, _REVERSION)

    found = mechanism_store.duplicates(_MOMENTUM)
    assert [record.node_id for record in found] == sorted([first, second])
    assert other not in [record.node_id for record in found]
    # Every record carries the *row's* verbatim spelling, so a reviewer
    # comparing them reads what the agents actually wrote — including the
    # leading and trailing spaces one of them wrote — rather than a
    # canonicalized form that is nowhere in the tree.
    assert {record.statement for record in found} == {_MOMENTUM, shouted}


def test_duplicates_is_a_report_and_not_a_gate(
    mechanism_store: MechanismStore, mechanism_database: str
) -> None:
    # It refuses nothing.  The only thing that changes the answer is the
    # caller's own ``exclude`` — a caller saying "I know about this one" — which
    # is a *parameter* rather than this method deciding what counts.  Feature
    # 179's CodeHashIndex is the check that refuses a duplicate before a trial
    # is charged, on a different key; this deliberately does not extend it.
    first = plant_node(mechanism_database)
    second = plant_node(mechanism_database)
    mechanism_store.persist(first, _MOMENTUM)
    mechanism_store.persist(second, _MOMENTUM)

    assert len(mechanism_store.duplicates(_MOMENTUM)) == 2
    remaining = mechanism_store.duplicates(_MOMENTUM, exclude=first)
    assert [record.node_id for record in remaining] == [second]
    # And duplicates on a mechanism nothing states is empty, not an error: a
    # proposal that resembles nothing is the ordinary case.
    assert mechanism_store.duplicates(_REVERSION) == ()


def test_duplicates_refuses_a_statement_that_canonicalises_to_nothing(
    mechanism_store: MechanismStore, mechanism_database: str
) -> None:
    # An empty canonical form names no mechanism to compare, and a read that
    # accepted one would match every other blank — answering "all of them" about
    # a proposal that stated nothing.  So it is refused rather than compared.
    node = plant_node(mechanism_database)
    mechanism_store.persist(node, _MOMENTUM)
    # ``duplicates`` takes a mechanism to *match*, not a mechanism to record, so
    # a blank is refused by :func:`mechanism_digest` rather than folded to the
    # unstated state the write path folds it to.  The two seams treat the same
    # input differently on purpose — see the store's docstrings — and this is
    # the assertion that pins which one refuses.
    for blank in ("", "   ", "\n\t", None):
        with pytest.raises(MechanismStatementError) as refusal:
            mechanism_store.duplicates(blank)
        assert "names no mechanism to match" in str(refusal.value)
    # The digest itself would happily hash the empty canonical form — that is
    # why the read refuses *before* taking one — so the two are asserted apart:
    # the primitive hashes, the seam refuses.
    assert mechanism_digest("") == mechanism_digest("   ")
    # And the write path folds the same input the other way, because a NULL is
    # the honest record of an agent that stated nothing.  The two seams treat a
    # blank differently on purpose.
    node = plant_node(mechanism_database)
    assert mechanism_store.persist(node, "").reason is MechanismReason.NOT_A_STATEMENT


def test_the_review_read_answers_what_has_been_claimed(
    mechanism_store: MechanismStore, mechanism_database: str
) -> None:
    # §9.1's second reader.  It needs something the dedup read cannot give it:
    # the whole set, not a match — a caller with a mechanism in hand is not a
    # reviewer working a queue.  It is deliberately *not* called ``unreviewed``:
    # this member owns no review workflow, there is no ``reviewed_at`` column on
    # ``node`` and no queue state in either spec document, and naming it
    # ``unreviewed`` would claim a state machine that does not exist.
    stated = [plant_node(mechanism_database) for _ in range(3)]
    for index, node in enumerate(stated):
        mechanism_store.persist(node, f"{_MOMENTUM} Variant {index}.")
    blank = plant_node(mechanism_database)
    mechanism_store.persist(blank, None)

    review = mechanism_store.stated()
    assert [record.node_id for record in review] == sorted(stated)
    assert blank not in [record.node_id for record in review], (
        "a NULL is the positive fact that there is nothing to review"
    )
    assert all(record.stated and record.statement for record in review)
    assert not hasattr(mechanism_store, "unreviewed"), (
        "no review-workflow state machine is claimed by this member"
    )


def test_both_reads_are_ordered_so_a_review_pass_is_reproducible(
    mechanism_store: MechanismStore, mechanism_database: str
) -> None:
    # A review queue that reshuffled between reads would be one a reviewer could
    # not work through, and a dedup report that reordered would make two runs
    # look like two findings.
    nodes = [plant_node(mechanism_database) for _ in range(4)]
    for node in nodes:
        mechanism_store.persist(node, _MOMENTUM)
    first_pass = [record.node_id for record in mechanism_store.duplicates(_MOMENTUM)]
    second_pass = [record.node_id for record in mechanism_store.duplicates(_MOMENTUM)]
    assert first_pass == second_pass == sorted(nodes)
    assert [record.node_id for record in mechanism_store.stated()] == sorted(nodes)


def test_the_record_compares_mechanisms_without_reaching_the_store() -> None:
    # A caller comparing two proposals in hand should not have to open a
    # database to ask the dedup question — and two nodes that both state
    # *nothing* are not two occurrences of one mechanism.
    node = "22222222-3333-4444-5555-666666666666"
    other = "77777777-8888-9999-aaaa-bbbbbbbbbbbb"
    held = MechanismRecord(
        node_id=node,
        reason=MechanismReason.STATED,
        detail="d",
        statement=_MOMENTUM,
    )
    assert held.same_mechanism(f"  {_MOMENTUM.upper()}  ")
    assert held.same_mechanism(
        MechanismRecord(
            node_id=other,
            reason=MechanismReason.STATED,
            detail="d",
            statement=_MOMENTUM,
        )
    )
    assert not held.same_mechanism(_REVERSION)
    assert not held.same_mechanism(7)

    quiet = MechanismRecord(
        node_id=node, reason=MechanismReason.NOT_A_STATEMENT, detail="d"
    )
    assert not quiet.same_mechanism(quiet)
    assert not quiet.same_mechanism("")


# ── The fourth claim: never as a scored input ─────────────────────────────────


def test_the_barrier_refuses_a_mechanism_however_well_formed() -> None:
    # The clause is *"never"*, so there is no well-formed value that passes.  A
    # method that could return ``scored=True`` for some statement would be a
    # method whose contract allowed the thing the feature forbids — so the
    # verdict has one value and this asserts it for the shapes a caller might
    # hope were special.
    law = StatedMechanism()
    for offered in (
        _MOMENTUM,
        f"  {_MOMENTUM.upper()}  ",
        "",
        None,
        MechanismRecord(
            node_id="33333333-4444-5555-6666-777777777777",
            reason=MechanismReason.STATED,
            detail="d",
            statement=_MOMENTUM,
        ),
    ):
        verdict = law.scored_input(offered)
        assert isinstance(verdict, MechanismScoredInput)
        assert verdict.scored is False
        assert NEVER_SCORED_CODE in verdict.detail


def test_the_barrier_names_what_a_score_actually_measures() -> None:
    # The refusal has to be actionable, not just negative: a caller looking for
    # a number should be told where the number lives.  Every figure this system
    # reports is a measurement of the *source*, and a score conditioned on the
    # rationale would make agent_model_id stratification, the M3 paired
    # comparison and the deflation term functions of what a model said about
    # itself.  That is the sentence the refusal carries.
    detail = StatedMechanism().scored_input(_MOMENTUM).detail
    assert "§9.1" in detail
    assert "never" in detail and "scored" in detail
    assert "source" in detail
    assert "agent_model_id" in detail and "stratification" in detail
    # It names what it was handed by *length* rather than by quoting it: a
    # rationale can be a paragraph, and an operator-facing message that embedded
    # one would be unreadable in a log.
    assert f"{len(_MOMENTUM)}-character" in detail
    assert _MOMENTUM not in detail


def test_the_barrier_bridge_raises_unconditionally() -> None:
    # The exception bridge for a caller on its last line before a scorer.  There
    # is no passing state, so there is no return value — and the class is
    # deliberately not under AgentSourceError or MechanismStatementError: no
    # agent action repairs this and no re-prompt changes it, so a caller
    # catching the proposal-level vocabulary must not catch it by accident.
    law = StatedMechanism()
    for offered in (_MOMENTUM, "", None, 7):
        with pytest.raises(MechanismNotScoredError) as refusal:
            law.require_scored_input(offered)
        assert NEVER_SCORED_CODE in str(refusal.value)
    assert not issubclass(MechanismNotScoredError, member.AgentSourceError)
    assert not issubclass(MechanismNotScoredError, MechanismStatementError)
    assert issubclass(MechanismNotScoredError, member.SignalAgentError)


def test_the_verdicts_own_require_refuses_too() -> None:
    # The returned verdict's bridge, asserted separately from the law's: a
    # caller that got the value rather than the exception must not be able to
    # get an admitted result out of it either.
    verdict = StatedMechanism().scored_input(_MOMENTUM)
    with pytest.raises(MechanismNotScoredError) as refusal:
        verdict.require()
    assert refusal.value.args[0] == verdict.detail


def test_the_record_carries_no_numeric_surface() -> None:
    # The barrier, made structural.  This is the claim that would be silently
    # lost: nothing breaks if a caller scores a mechanism, so the prohibition is
    # enforced by there being nothing to coerce.  The absence of each dunder is
    # pinned *as an absence*, because the failure this guards against is a later
    # edit adding one — a record that supported ``float()`` would be a record a
    # careless line could average.
    node = "44444444-5555-6666-7777-888888888888"
    record = MechanismRecord(
        node_id=node,
        reason=MechanismReason.STATED,
        detail="d",
        statement=_MOMENTUM,
    )
    for dunder in ("__float__", "__int__", "__index__", "__complex__", "__trunc__"):
        assert not hasattr(record, dunder), dunder
        assert dunder not in MechanismRecord.__slots__
        assert dunder not in MechanismScoredInput.__slots__
    for coercion in (float, int, complex, round, abs):
        with pytest.raises(TypeError):
            coercion(record)  # type: ignore[arg-type]
    # Ordering is not supported *by value*: ``__lt__`` is inherited from
    # ``object`` and falls back to identity, so two equal-valued records do not
    # sort — which is the honest answer, since there is no magnitude here to
    # order them by.  Asserted by behaviour rather than by attribute presence,
    # because ``hasattr`` is true of every object.
    twin = MechanismRecord(
        node_id=node,
        reason=MechanismReason.STATED,
        detail="d",
        statement=_MOMENTUM,
    )
    assert twin is not record
    with pytest.raises(TypeError):
        sorted([record, twin])


def test_the_dedup_key_is_a_key_and_not_a_magnitude() -> None:
    # The one derived value on the record, and it is a ``str`` — so it is not
    # orderable into a ranking even by accident.  A numeric digest would be the
    # first step toward a scored one, which is the whole shape of the failure
    # the feature's last clause exists to prevent.
    digest = mechanism_digest(_MOMENTUM)
    assert isinstance(digest, str)
    assert len(digest) == 64 and digest == digest.lower()
    assert all(character in "0123456789abcdef" for character in digest)
    assert mechanism_digest(_MOMENTUM) == digest, "stable across calls"
    assert not isinstance(digest, (int, float, bool))


def test_the_reason_vocabulary_has_one_token_per_repair() -> None:
    # Three reasons, not four.  An empty value and an absent one are the same
    # proposal-level fact with the same repair — which is none — so there is
    # deliberately no "blank statement" token: two tokens for one state would
    # invite a reader to think the difference mattered.  The values are the
    # greppable codes, and no two are equal (an aliased ``enum`` member would
    # make two names one state).
    assert [reason.value for reason in MechanismReason] == [
        "stated",
        NOT_A_STATEMENT_CODE,
        member.MECHANISM_CONFLICT_CODE,
    ]
    assert len({reason.value for reason in MechanismReason}) == 3
    assert not hasattr(MechanismReason, "BLANK_STATEMENT")


def test_the_conflict_refusal_is_a_statement_error_and_a_greppable_word(
    mechanism_store: MechanismStore, mechanism_database: str
) -> None:
    # The conflict's class choice is the *opposite* of the deployment classes':
    # the subject is still the statement being persisted, so a caller catching
    # the statement contract must not lose the refusal through a clause that no
    # longer matches.  It is its own class because the *repair* differs — the
    # caller must stop trying to re-state history, which no re-prompt changes —
    # and its code says so.
    assert issubclass(MechanismConflictError, MechanismStatementError)
    assert member.MECHANISM_CONFLICT_CODE in MechanismReason.CONFLICT.value

    node = plant_node(mechanism_database)
    mechanism_store.persist(node, _MOMENTUM)
    with pytest.raises(MechanismStatementError):
        mechanism_store.persist(node, _REVERSION)


def test_the_store_backed_verbs_refuse_when_there_is_no_store() -> None:
    # ``store=None`` is a discoverable composition state, not a broken one: the
    # barrier answers, the four store-backed verbs refuse by name.  And it is
    # **not an empty store** — an empty store answers "no node states a
    # mechanism here" about every id, while this says there is no database to
    # have recorded one in.  The distinction is the one the member's other store
    # builders draw for their own ``None``.
    law = StatedMechanism()
    assert law.store is None
    assert law.scored_input(_MOMENTUM).scored is False, "the barrier still answers"

    calls = (
        lambda: law.persist("55555555-6666-7777-8888-999999999999", _MOMENTUM),
        lambda: law.load("55555555-6666-7777-8888-999999999999"),
        lambda: law.duplicates(_MOMENTUM),
        law.stated,
    )
    for call in calls:
        with pytest.raises(MechanismStoreUnavailableError) as refusal:
            call()
        assert "not an empty store" in str(refusal.value)

    # And the environment is the seam: ``resolve`` answers ``None`` for an unset
    # or blank variable, and a store for a named one.
    assert MechanismStore.resolve({}) is None
    assert MechanismStore.resolve({"DATABASE_URL": "   "}) is None
    assert isinstance(
        MechanismStore.resolve({"DATABASE_URL": "sqlite:///tree.db"}),
        MechanismStore,
    )
    # ``from_env`` is the caller-side twin that refuses by name instead.
    with pytest.raises(MechanismStoreUnavailableError):
        MechanismStore.from_env({})
    # And the module-level convenience never returns ``None``: composing nothing
    # here would make the one guardrail that needs no storage unavailable in
    # exactly the deployment that has the least other protection.
    assert isinstance(stated_mechanism({}), StatedMechanism)
    assert isinstance(stated_mechanism({"DATABASE_URL": "sqlite:///tree.db"}), StatedMechanism)


def test_a_url_this_member_cannot_speak_is_refused_at_first_use() -> None:
    # Construction performs no I/O: a builder that opened a database would be
    # doing composition-time work on the disk, and the factory builds every
    # registered component on every ``create_app()``.  So the translation (and
    # the refusal) happen on first use, which is what makes
    # ``build_stated_mechanism`` safe to run anywhere.
    for url in (
        "postgresql://host/tree",
        "sqlite://memory",
        "sqlite:///:memory:",
        "sqlite://",
        "",
        "   ",
    ):
        store = MechanismStore(url) if url.strip() else None
        if store is None:
            continue
        with pytest.raises(MechanismStoreUnavailableError):
            store.stated()


def test_the_law_and_the_store_agree_through_one_handle(
    mechanism: StatedMechanism, mechanism_database: str
) -> None:
    # The composed shape: one handle carrying the barrier and the store, so a
    # caller holding the composed component asks feature 211's questions without
    # importing the submodule by name.  The store-backed verbs delegate rather
    # than re-implement, so there is no second state machine to keep in step.
    node = plant_node(mechanism_database)
    assert mechanism.store is not None
    recorded = mechanism.persist(node, _MOMENTUM)
    assert recorded.recorded is True
    assert mechanism.load(node).statement == _MOMENTUM  # type: ignore[union-attr]
    assert [record.node_id for record in mechanism.duplicates(_MOMENTUM)] == [node]
    assert [record.node_id for record in mechanism.stated()] == [node]
    with pytest.raises(MechanismNotScoredError):
        mechanism.require_scored_input(recorded)


def test_the_mechanism_column_is_the_one_the_migration_creates(
    mechanism_database: str,
) -> None:
    # The one claim that ties this suite to the schema's owner: the constant the
    # store reads and writes is the column ``0117_identity_trio`` actually adds,
    # and that migration leaves it **nullable** — which is the premise of the
    # unstated branch above.  A suite that spelled its own column name would
    # pass every test in this file against a schema nobody ships.
    from conftest import load_migration

    trio = load_migration("0117_identity_trio")
    with sqlite3.connect(sqlite_path_of(mechanism_database)) as connection:
        columns = {
            str(row[1]): row
            for row in connection.execute("PRAGMA table_info(node)").fetchall()
        }
    assert member.MECHANISM_COLUMN in columns
    assert member.MECHANISM_COLUMN in trio.COLUMNS
    # ``notnull`` is the sixth field of a ``PRAGMA table_info`` row, and this is
    # the reading that makes the unstated write possible at all.
    assert columns[member.MECHANISM_COLUMN][3] == 0
    assert member.MECHANISM_COLUMN not in trio.NOT_NULL_COLUMNS
    # And the two the migration does constrain are not this feature's business.
    assert "stated_mechanism" not in trio.NOT_NULL_COLUMNS
