"""Feature 273's claim, stated as tests: ``π^0`` back in the candidate set.

app_spec.xml, "Dreaming Loop & Meta-Selection", feature 273: *System includes
the incumbent policy in the candidate set, which returns a selected policy
never worse on the fixed history.*  docs/alpha-engine-prd.md §C5 states the
clause as the qualifier on the whole dreaming loop — *"because the candidate
set includes ``π^0 = π_t``, the selected policy is no worse than the current
one *on the fixed replay history*.  Note the qualifier.  It is a guarantee
about replay score, not about future P&L."* — and three of this feature's
neighbours cite it by number while expressly disclaiming it: feature 272's
docstring (*"putting ``π^0 = π_t`` back into the candidate set so the selection
can never fall below the current policy is feature 273's"*), feature 274's
(*"It is not feature 273 either"*), and feature 280's, whose whole refusal is
grounded on it.

So the claims worth pinning are these, and the classes below are arranged
around them:

* the **value is π^0 as a candidate-shaped entry** — the incumbent's own
  ``source``, its ``code_hash`` and the ``module_id`` the loop knows it by —
  built through the member's **one spelling of a candidate's identity**
  (feature 271's ``_code_hash_of``), and a caller that names no version gets
  the very string feature 271's ``candidate_module`` would have derived for
  that source, so a previous cycle's ``policy_revision.policy_version`` is
  reconstructible from the policy source alone;
* the entry carries **no ``revision_index``** — feature 272's own reader
  admits *"a genuine positive integer or absent"*, and its docstring names
  this feature as the case — so the widened set can be handed to feature 272's
  ``plan_sweep`` without the incumbent being mislabelled as one of the ``M``
  revisions the loop produced;
* the **act of including widens the set** — the incumbent **first**, the
  produced revisions in their own order after it, as a tuple, and without
  mutating the caller's sequence;
* an **empty candidate set is admitted**, and the widened set is then the
  one-member set ``(π^0,)`` — §C5's guarantee at its most literal;
* everything else **refuses rather than silently defaulting**, in this
  feature's own vocabulary and never feature 271's — a malformed source, a
  malformed version, a bare string where a sequence belongs, a candidate whose
  identity cannot be read, and the load-bearing one: an incumbent that is
  **already in the set**, by ``module_id`` or by ``code_hash``, which is the
  case feature 271's deduplication structurally cannot catch;
* both functions are **pure** — no store, no clock, no environment, no
  ``@register`` component — and neither opens a database;
* the sentence's **second clause is a theorem**, not a check this module
  performs: run feature 274's *real* :func:`~dreaming.select.select_argmax`
  over the widened set, over a pool a caller actually holds, and the winner's
  §7 objective is at least the incumbent's — ``V^{m★} ≥ V^0`` by construction,
  and where it is not, feature 274 refuses rather than answering something
  lower.
"""

from __future__ import annotations

import importlib
import random
import sqlite3
from contextlib import closing
from types import SimpleNamespace

import pytest
from dreaming import (
    DreamingError,
    IncumbentCandidate,
    IncumbentRequestError,
    include_incumbent,
    incumbent_candidate,
    sqlite_path,
)

#: The incumbent's policy source — the ``π_t`` of §C5's ``π^0 = π_t``.  A
#: real, parseable policy module rather than an ellipsis, because feature 271's
#: reviser would happily jitter a one-line body and the point of these tests is
#: that the identity is computed from whatever source it is handed.
INCUMBENT_SOURCE = "def policy(beta):\n    return beta * 0.5\n"

#: A revised source — what feature 271 would produce for one revision.  Differs
#: from the incumbent by one numeric literal, the shape ``REVISION_BAND``
#: jitter makes, so the two hash differently by construction.
REVISED_SOURCE = "def policy(beta):\n    return beta * 0.55\n"


def _candidate(
    module_id: str, *, code_hash: str | None = None, parent: str | None = "pi-0"
):
    """One candidate module — the value feature 271 produces, duck-typed.

    A :class:`types.SimpleNamespace` carrying ``module_id``, ``code_hash``,
    ``parent_version`` and ``revision_index`` — the four fields a candidate
    is read for — so a test names one without importing feature 271's class,
    the way the inclusion reads one: by the attributes it needs, never by
    ``isinstance``.  The ``code_hash`` defaults to 64 of the id's own first
    letter, the shape a real sha256 takes, so a test that wants to *collide*
    hashes must say so explicitly.  The default is applied only to a *non-empty*
    id, because a test that hands in a blank one is asserting the inclusion's
    refusal of it and must not have that refusal pre-empted by a fixture fault.
    """
    return SimpleNamespace(
        module_id=module_id,
        code_hash=code_hash if code_hash is not None else (module_id[:1] * 64),
        parent_version=parent,
        revision_index=1,
    )


def _objective(score: float, *, world_count: int = 10):
    """One aggregated objective — feature 263's value, duck-typed.

    Carries ``score`` and ``world_count``, the two figures feature 274's argmax
    ranks by, so a verdict test over the widened set needs no real §7 blend
    behind it.
    """
    return SimpleNamespace(score=score, world_count=world_count)


#: ``0109``'s ``policy_revision`` DDL, spelled once.  The same stand-in
#: ``test_select.py`` uses, because this suite needs the same one table and
#: a second copy of it in the member would be a second thing to keep in sync.
_REVISION_DDL = (
    "CREATE TABLE policy_revision ("
    "id TEXT PRIMARY KEY, "
    "policy_version TEXT NOT NULL UNIQUE, "
    "parent_version TEXT, "
    "code_hash CHAR(64) NOT NULL, "
    "aggregate_score REAL, "
    "selected BOOLEAN NOT NULL DEFAULT FALSE)"
)


def _revision_table(url: str) -> None:
    """Give the pool the ``policy_revision`` table feature 274 writes into.

    Feature 274 is the table's sole writer, so this suite creates it here and
    reads it from the other side — the shape ``test_select.py`` uses for its
    own write, spelled here because the theorem test below runs feature 274's
    real commit over the widened set this feature answers.
    """
    with closing(sqlite3.connect(sqlite_path(url))) as connection, connection:
        connection.execute(_REVISION_DDL)


def _write_scores(
    url: str, *, policy_version: str, beta: float, readings: dict[str, float]
) -> None:
    """Write one policy's score rows into the pool, through ``0109``'s columns.

    The rows are written the way the owner declares them — ``0109``'s eight
    columns for ``replay_score`` — so every read below goes through the same
    table a deployment's replay loop fills, rather than through a narrower
    fixture shape.
    """
    with closing(sqlite3.connect(sqlite_path(url))) as connection, connection:
        for world_id, score in readings.items():
            connection.execute(
                "INSERT INTO replay_score (id, policy_version, world_id, beta, "
                "score, committed_pick, is_holdout, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"score-{policy_version}-{world_id}",
                    policy_version,
                    world_id,
                    beta,
                    score,
                    None,
                    0,
                    "2026-01-01T00:00:00Z",
                ),
            )


class TestIncumbentCandidate:
    """``π^0`` as an entry — the value half, and it is pure."""

    def test_the_entry_carries_the_incumbents_own_source(self):
        """The source is the only thing feature 272's replay reads — unchanged."""
        entry = incumbent_candidate(INCUMBENT_SOURCE)

        assert entry.source == INCUMBENT_SOURCE

    def test_the_code_hash_is_the_members_one_spelling(self):
        """The hash is feature 271's, imported and not respelled.

        Feature 271's ``_code_hash_of`` is the one spelling of a candidate's
        identity — its docstring calls it *"shared by candidate_module and
        revise_policy's deduplication so the two cannot disagree on what makes
        two revisions the same candidate"* — so this asserts the agreement
        against the owner's own function rather than against a re-derived
        ``hashlib`` figure, which is the whole point of importing it.
        """
        reviser = importlib.import_module("dreaming.reviser")

        entry = incumbent_candidate(INCUMBENT_SOURCE)

        assert entry.code_hash == reviser._code_hash_of(INCUMBENT_SOURCE)

    def test_the_default_version_is_the_one_feature_271_would_have_derived(self):
        """The restatement is pinned against its owner, not trusted.

        A candidate's ``module_id`` is a function of its source, so an
        incumbent whose caller names no version is given the very string the
        loop would have written for it when it *was* a candidate — which is
        what makes a previous cycle's ``policy_revision.policy_version``
        reconstructible from the policy source alone.  A second derivation that
        drifted here would address a policy the pool's rows are not keyed by,
        and nothing else in this member's behaviour would notice.
        """
        reviser = importlib.import_module("dreaming.reviser")

        entry = incumbent_candidate(INCUMBENT_SOURCE)
        produced = reviser.candidate_module(INCUMBENT_SOURCE)

        assert entry.module_id == produced.module_id
        assert entry.code_hash == produced.code_hash

    def test_a_named_version_is_honoured_verbatim(self):
        """A deployment that addresses its policies another way is obeyed."""
        entry = incumbent_candidate(INCUMBENT_SOURCE, version="pi-7")

        assert entry.module_id == "pi-7"

    def test_the_two_derivations_disagree_for_different_sources(self):
        """Stated so the agreement above is not vacuous: two sources, two ids."""
        first = incumbent_candidate(INCUMBENT_SOURCE)
        second = incumbent_candidate(REVISED_SOURCE)

        assert first.module_id != second.module_id
        assert first.code_hash != second.code_hash

    def test_the_parent_defaults_to_none(self):
        """The ordinary case: this iteration's lineage begins at the incumbent.

        The ``M`` revisions feature 271 produces carry the *incumbent's*
        version as their ``parent_version``, so an incumbent descending from a
        further policy is the exception rather than the rule.
        """
        assert incumbent_candidate(INCUMBENT_SOURCE).parent_version is None

    def test_a_named_parent_is_carried(self):
        """A deployment that records a longer lineage is obeyed."""
        entry = incumbent_candidate(INCUMBENT_SOURCE, parent_version="pi-6")

        assert entry.parent_version == "pi-6"

    def test_the_entry_is_frozen(self):
        """The ``__slots__`` entry a caller holds, so nothing can be added to move it.

        The stance feature 271's own ``CandidateModule`` states for itself
        (*"a caller cannot add an attribute to move a candidate"*): a
        ``__slots__`` entry takes no new attribute, so two callers holding one
        entry hold one value.
        """
        entry = incumbent_candidate(INCUMBENT_SOURCE)

        with pytest.raises(AttributeError):
            entry.spurious = "other"  # type: ignore[attr-defined]

    def test_the_entry_carries_four_fields_and_no_revision_index(self):
        """The absence of a fifth field is deliberate, not an omission."""
        assert IncumbentCandidate.__slots__ == (
            "code_hash",
            "module_id",
            "parent_version",
            "source",
        )
        assert not hasattr(incumbent_candidate(INCUMBENT_SOURCE), "revision_index")

    def test_two_entries_for_one_incumbent_are_one_value(self):
        """Equality and hash are the four fields, so a set of them is a set."""
        first = incumbent_candidate(INCUMBENT_SOURCE, version="pi-0")
        second = incumbent_candidate(INCUMBENT_SOURCE, version="pi-0")

        assert first == second
        assert hash(first) == hash(second)

    def test_a_blank_source_is_refused(self):
        """An incumbent that carries no policy puts none back in the set."""
        with pytest.raises(IncumbentRequestError) as caught:
            incumbent_candidate("   ")

        assert "policy source" in str(caught.value)

    def test_a_non_text_source_is_refused_before_the_hash(self):
        """A value with no ``.encode()`` is the ask's fault, not an ``AttributeError``."""
        with pytest.raises(IncumbentRequestError) as caught:
            incumbent_candidate(0.5)

        assert "float" in str(caught.value)

    def test_a_blank_version_is_refused(self):
        """A version that cannot be named addresses no policy."""
        with pytest.raises(IncumbentRequestError) as caught:
            incumbent_candidate(INCUMBENT_SOURCE, version="")

        assert "version" in str(caught.value)

    def test_a_blank_parent_is_refused(self):
        """A parent that cannot be named places the lineage nowhere."""
        with pytest.raises(IncumbentRequestError) as caught:
            incumbent_candidate(INCUMBENT_SOURCE, parent_version=" ")

        assert "parent" in str(caught.value)

    def test_the_refusal_is_a_dreaming_error_and_not_the_revisers(self):
        """The ask/store split holds: the inclusion is this feature's word.

        A caller that included an incumbent must not meet feature 271's
        ``RevisionRequestError`` for an act that revised nothing — the *rule*
        that a source is non-empty text is the member's one rule, and the
        *vocabulary* splits by who was asked.
        """
        errors = importlib.import_module("dreaming.errors")

        with pytest.raises(DreamingError) as caught:
            incumbent_candidate("")

        assert isinstance(caught.value, IncumbentRequestError)
        assert not isinstance(caught.value, errors.RevisionRequestError)

    def test_the_refusal_is_neither_the_freezes_nor_the_floors_word(self):
        """Not ``pool_frozen``, not ``pool_too_thin`` — a caller acts on the right fact."""
        import dreaming

        with pytest.raises(IncumbentRequestError) as caught:
            incumbent_candidate("")

        message = str(caught.value)
        assert dreaming.FREEZE_CODE not in message
        assert dreaming.POOL_TOO_THIN_CODE not in message


class TestIncludeIncumbent:
    """The act of including — the widened set, and the refusals that keep it honest."""

    def test_the_incumbent_comes_first(self):
        """``π^0`` is the set's opening member by the numbering §C5 gives it."""
        produced = [_candidate("cand-a"), _candidate("cand-b")]

        widened = include_incumbent(produced, INCUMBENT_SOURCE)

        assert widened[0].module_id == incumbent_candidate(INCUMBENT_SOURCE).module_id
        assert widened[0].code_hash == incumbent_candidate(INCUMBENT_SOURCE).code_hash

    def test_the_produced_revisions_follow_in_their_own_order(self):
        """The loop's revisions are not re-ordered by having the incumbent prepended."""
        produced = [_candidate("cand-b"), _candidate("cand-a"), _candidate("cand-c")]

        widened = include_incumbent(produced, INCUMBENT_SOURCE)

        assert [getattr(one, "module_id", None) for one in widened[1:]] == [
            "cand-b",
            "cand-a",
            "cand-c",
        ]

    def test_the_set_is_exactly_one_larger(self):
        """The sentence's verb is *includes*: one entry added, none removed."""
        produced = [_candidate("cand-a"), _candidate("cand-b")]

        widened = include_incumbent(produced, INCUMBENT_SOURCE)

        assert len(widened) == len(produced) + 1

    def test_the_answer_is_a_tuple(self):
        """A value a caller can hold and compare, not a generator paying twice."""
        widened = include_incumbent([_candidate("cand-a")], INCUMBENT_SOURCE)

        assert isinstance(widened, tuple)
        assert widened is not include_incumbent(
            [_candidate("cand-a")], INCUMBENT_SOURCE
        )

    def test_an_empty_candidate_set_is_admitted(self):
        """§C5's guarantee at its most literal: the selected policy *is* the incumbent.

        Feature 271 refuses a production shortfall, so an empty set reaching
        here is a caller's own construction rather than a policy that could not
        fund ``M`` — and the whole of this feature is *adding one*.  This is the
        admission feature 276's ceiling states for a zero revision count, one
        step earlier in the same loop.
        """
        widened = include_incumbent((), INCUMBENT_SOURCE)

        assert len(widened) == 1
        assert widened[0].source == INCUMBENT_SOURCE

    def test_the_callers_sequence_is_not_consumed(self):
        """The produced ``M`` is read, never consumed in place."""
        produced = [_candidate("cand-a"), _candidate("cand-b")]

        include_incumbent(produced, INCUMBENT_SOURCE)

        assert [one.module_id for one in produced] == ["cand-a", "cand-b"]

    def test_a_named_version_travels_into_the_set(self):
        """A deployment that addresses the incumbent by its own name is obeyed."""
        widened = include_incumbent(
            [_candidate("cand-a")], INCUMBENT_SOURCE, version="pi-7"
        )

        assert widened[0].module_id == "pi-7"

    def test_the_entry_is_readable_the_way_feature_272_reads_one(self):
        """The widened set crosses into feature 272's plan without a fabricated index.

        Feature 272's ``_candidate_of`` reads ``module_id``, ``code_hash`` and
        an **optional** ``revision_index``, and its docstring names this feature
        as the reason the index is optional — *"273's incumbent — put back into
        the candidate set by a sibling feature — may well arrive as a different
        class carrying the same facts."*  This runs the owner's own reader over
        the entry the widened set carries, so the claim is pinned against the
        consumer rather than inferred from the entry's shape.
        """
        sweep = importlib.import_module("dreaming.sweep")

        widened = include_incumbent([_candidate("cand-a")], INCUMBENT_SOURCE)

        module_id, code_hash, index = sweep._candidate_of(widened[0])
        assert module_id == widened[0].module_id
        assert code_hash == widened[0].code_hash
        assert index is None

    def test_the_whole_widened_set_plans_a_sweep(self):
        """Every member of the widened set is sweepable — the whole point of the shape."""
        sweep = importlib.import_module("dreaming.sweep")

        widened = include_incumbent(
            [_candidate("cand-a", code_hash="a" * 64)], INCUMBENT_SOURCE
        )

        pairs = sweep.plan_sweep(widened, ("world-1", "world-2"))

        assert len(pairs) == 2 * 2
        assert {pair.module_id for pair in pairs} == {
            widened[0].module_id,
            "cand-a",
        }

    # -- the load-bearing refusals ---------------------------------------------

    def test_an_incumbent_already_in_the_set_is_refused(self):
        """*Includes* is not *may include* — running the act twice does not enlarge anything.

        A loop that ran this feature twice has not widened its tournament, and
        the enlarged set would give §C5's argmax two entrants under one version
        — a tournament that looks larger and selects nothing new.
        """
        incumbent = incumbent_candidate(INCUMBENT_SOURCE, version="pi-0")

        with pytest.raises(IncumbentRequestError) as caught:
            include_incumbent([_candidate("pi-0")], INCUMBENT_SOURCE, version="pi-0")

        assert "already" in str(caught.value)
        assert incumbent.module_id in str(caught.value)

    def test_an_incumbent_reproduced_verbatim_is_refused_by_its_hash(self):
        """The case feature 271's deduplication structurally cannot catch.

        Feature 271 deduplicates the revisions against *each other*; it never
        compares them to the incumbent they descend from, so a production that
        returned a byte-identical source is caught here or nowhere.  Without
        this refusal the widened set would hold two entrants that are one
        policy, and feature 274's argmax over them would be a guaranteed tie.
        """
        with pytest.raises(IncumbentRequestError) as caught:
            include_incumbent(
                [
                    _candidate(
                        "cand-verbatim",
                        code_hash=incumbent_candidate(INCUMBENT_SOURCE).code_hash,
                    )
                ],
                INCUMBENT_SOURCE,
            )

        assert "cand-verbatim" in str(caught.value)

    def test_the_two_collisions_are_refused_separately(self):
        """Different identities, different repairs — so the message says which gave it away.

        A *version* collision is a loop that ran the inclusion twice; a *hash*
        collision is a production that did not revise anything.  Both are this
        class, and the message distinguishes them.
        """
        entry = incumbent_candidate(INCUMBENT_SOURCE)

        with pytest.raises(IncumbentRequestError) as by_id:
            include_incumbent(
                [_candidate(entry.module_id, code_hash="f" * 64)], INCUMBENT_SOURCE
            )
        with pytest.raises(IncumbentRequestError) as by_hash:
            include_incumbent(
                [_candidate("cand-other", code_hash=entry.code_hash)], INCUMBENT_SOURCE
            )

        assert "already one of its members" in str(by_id.value)
        assert "byte-identical" in str(by_hash.value)

    def test_a_bare_source_is_refused_where_a_sequence_belongs(self):
        """A nine-character world would silently become nine one-character candidates."""
        with pytest.raises(IncumbentRequestError) as caught:
            include_incumbent(REVISED_SOURCE, INCUMBENT_SOURCE)

        assert "sequence" in str(caught.value)

    def test_a_non_sequence_is_refused(self):
        """A candidate module stands for one revision, not a tournament."""
        with pytest.raises(IncumbentRequestError) as caught:
            include_incumbent(_candidate("cand-a"), INCUMBENT_SOURCE)

        assert "sequence" in str(caught.value)

    def test_a_candidate_with_no_module_id_is_refused(self):
        """A candidate that cannot be named is one the inclusion cannot be told apart from."""
        with pytest.raises(IncumbentRequestError) as caught:
            include_incumbent([_candidate("")], INCUMBENT_SOURCE)

        assert "module_id" in str(caught.value)

    def test_a_candidate_with_no_code_hash_is_refused(self):
        """A candidate whose identity cannot be read cannot be checked against the incumbent."""
        with pytest.raises(IncumbentRequestError) as caught:
            include_incumbent([_candidate("cand-a", code_hash="   ")], INCUMBENT_SOURCE)

        assert "code_hash" in str(caught.value)

    def test_a_malformed_source_is_refused_before_any_candidate_is_read(self):
        """The ask's own fact is refused whether or not the set is well formed."""
        with pytest.raises(IncumbentRequestError):
            include_incumbent([_candidate("cand-a")], "")

    def test_a_malformed_candidate_is_refused_before_a_collision_is_looked_for(self):
        """An unreadable set is a malformed ask, not a silent non-collision."""
        with pytest.raises(IncumbentRequestError) as caught:
            include_incumbent([_candidate("")], INCUMBENT_SOURCE, version="pi-0")

        assert "module_id" in str(caught.value)

    def test_the_set_is_read_before_the_entry_is_built(self):
        """The member's order: the tournament is validated, then the entrant.

        Both faults are present at once — a malformed set *and* a malformed
        source — and the set wins, because the set is the tournament every
        other figure is read against.  That is the order
        :func:`dreaming.sweep.plan_sweep` and
        :func:`dreaming.select.commit_selection` also take, and pinning it here
        keeps the docstring's stated order a checkable claim rather than prose.
        """
        with pytest.raises(IncumbentRequestError) as caught:
            include_incumbent("not a sequence", "")

        assert "sequence" in str(caught.value)

    def test_the_refusal_is_a_dreaming_error(self):
        """A caller catching ``DreamingError`` catches the inclusion's refusal."""
        with pytest.raises(DreamingError):
            include_incumbent(REVISED_SOURCE, INCUMBENT_SOURCE)

    def test_the_refusal_is_neither_the_freezes_nor_the_floors_word(self):
        """The inclusion's refusals are its own — no borrowed vocabulary."""
        import dreaming

        with pytest.raises(IncumbentRequestError) as caught:
            include_incumbent(REVISED_SOURCE, INCUMBENT_SOURCE)

        message = str(caught.value)
        assert dreaming.FREEZE_CODE not in message
        assert dreaming.POOL_TOO_THIN_CODE not in message
        assert "sweep_malformed" not in message
        assert "selection_malformed" not in message

    def test_an_empty_set_is_not_the_freezes_or_the_floors_refusal(self):
        """The admission is silent: no class is raised for a set that holds the incumbent alone."""
        assert include_incumbent((), INCUMBENT_SOURCE)


class TestTheGuaranteeHoldsByConstruction:
    """The sentence's second clause, pinned over feature 274's *real* argmax.

    *"…which returns a selected policy never worse on the fixed history."*
    With ``π^0`` in the set, feature 274's argmax is the maximum over a
    tournament one of whose entrants is the current policy, so the selected
    policy's §7 objective is at least the incumbent's whenever a selection is
    returned at all — that is ``V^{m★} ≥ V^0``, §12.1's own words, and this
    module performs **no check of it**: a check here would be a second spelling
    of the argmax's own law, and a test that can fail is not the construction
    the paper states.  What the classes below pin is therefore the *theorem*
    itself: run feature 274's verdict over the widened set and the inequality
    holds; the one path that could answer lower — a tie on the maximum — is
    feature 274's refusal, which is what the last test makes arrive.
    """

    def test_the_argmax_over_the_widened_set_is_never_below_the_incumbent(self):
        """``V^{m★} ≥ V^0``, over a pool a caller actually holds.

        The evidence is read back through the pool's own ``replay_score``
        table — the read feature 274 takes — and the incumbent's §7 figure is
        compared against the winner's by the figures the pool holds, not by a
        number this test invented.  The revisions beat the incumbent here, so
        the inequality is not satisfied trivially by the incumbent winning.
        """
        select = importlib.import_module("dreaming.select")
        incumbent = incumbent_candidate(INCUMBENT_SOURCE, version="pi-0")
        revisions = [
            _candidate("cand-a", code_hash="a" * 64, parent="pi-0"),
            _candidate("cand-b", code_hash="b" * 64, parent="pi-0"),
        ]

        widened = include_incumbent(revisions, INCUMBENT_SOURCE, version="pi-0")

        assert widened[0].module_id == incumbent.module_id
        # Feature 274's own verdict, over the set this feature answered.
        objectives = {
            "pi-0": _objective(0.20),
            "cand-a": _objective(0.35),
            "cand-b": _objective(0.28),
        }
        winner = select.select_argmax(widened, objectives)

        assert winner.module_id == "cand-a"
        assert objectives[winner.module_id].score >= objectives["pi-0"].score

    def test_the_incumbent_is_the_argmax_when_nothing_beats_it(self):
        """§12.1's *"when nothing clears the bar, the incumbent is the argmax"*.

        The same construction from the other side: the revisions are in the
        set and score lower, and the selected policy *is* the incumbent — which
        is why feature 280 can say a refused winner is not a lost cycle.
        """
        select = importlib.import_module("dreaming.select")

        widened = include_incumbent(
            [_candidate("cand-a", code_hash="a" * 64)],
            INCUMBENT_SOURCE,
            version="pi-0",
        )

        winner = select.select_argmax(
            widened, {"pi-0": _objective(0.30), "cand-a": _objective(0.12)}
        )

        assert winner.module_id == "pi-0"

    def test_the_widened_set_is_what_makes_a_tie_possible_and_refused(self):
        """The one path that could answer lower is feature 274's refusal, not a smaller figure.

        A revision whose objective **equals** the incumbent's is a tie on the
        maximum, and feature 274 refuses it rather than breaking it by order —
        so no path of the loop returns a policy worse than the incumbent, which
        is the guarantee stated positively.  Without the incumbent in the set
        there is no tie, and the argmax would return the revision — the
        comparison feature 273 exists to make impossible on the fixed history.
        """
        select = importlib.import_module("dreaming.select")

        widened = include_incumbent(
            [_candidate("cand-a", code_hash="a" * 64)],
            INCUMBENT_SOURCE,
            version="pi-0",
        )
        tied = {"pi-0": _objective(0.30), "cand-a": _objective(0.30)}

        with pytest.raises(select.SelectionRequestError) as caught:
            select.select_argmax(widened, tied)

        assert "pi-0" in str(caught.value) and "cand-a" in str(caught.value)
        # The same set without the incumbent selects the revision — the state
        # feature 273 removes, stated so the test above is not vacuous.
        assert (
            select.select_argmax(
                [_candidate("cand-a", code_hash="a" * 64)], {"cand-a": _objective(0.30)}
            ).module_id
            == "cand-a"
        )

    def test_no_selection_over_a_widened_set_ever_falls_below_the_incumbent(self):
        """The theorem swept, not sampled: many sets, many figures, no violation.

        The tests above pin the inequality at named figures, which is how one
        shows *why* it holds.  This one is the other half of the evidence — that
        the guarantee is a property of the construction rather than of the
        figures chosen — so it sweeps sets of every size from none to five and
        scores drawn over a range wide enough that the revisions beat the
        incumbent about as often as they lose to it.  A construction that
        merely *tended* to satisfy ``V^{m★} ≥ V^0`` would show a violation here;
        one that satisfies it by construction cannot, at any figure.

        The seed is fixed so a failure is reproducible, and the two outcome
        counters are asserted to be non-zero so the sweep cannot pass by
        vacuously crowning the incumbent every time.  The one refusal feature
        274 is allowed is a tie on the maximum, and a tie is *equal* and never
        lower — the loop's answer is then a refusal rather than a worse policy,
        which is the sentence's guarantee stated positively.
        """
        select = importlib.import_module("dreaming.select")
        rng = random.Random(273)
        incumbent_wins = revision_wins = ties = 0

        for trial in range(200):
            produced = [
                _candidate(
                    f"cand-{trial}-{index}",
                    code_hash=f"{trial:x}{index:x}".ljust(64, "a"),
                )
                for index in range(rng.randint(0, 5))
            ]
            widened = include_incumbent(produced, INCUMBENT_SOURCE)
            incumbent_id = widened[0].module_id
            objectives = {
                one.module_id: _objective(round(rng.uniform(-1.0, 1.0), 4))
                for one in widened
            }
            objectives[incumbent_id] = _objective(round(rng.uniform(-1.0, 1.0), 4))

            try:
                winner = select.select_argmax(widened, objectives)
            except select.SelectionRequestError:
                ties += 1
                continue

            assert objectives[winner.module_id].score >= objectives[incumbent_id].score
            if winner.module_id == incumbent_id:
                incumbent_wins += 1
            else:
                revision_wins += 1

        assert incumbent_wins > 0 and revision_wins > 0
        assert incumbent_wins + revision_wins + ties == 200

    def test_the_committed_winner_is_never_below_the_incumbent(self, pool):
        """The theorem at the store seam, over feature 274's real commit.

        The pool holds readings for the incumbent and for two revisions, the
        widened set is what feature 273 answers, and feature 274's own
        ``commit_selection`` crowns one of them into ``policy_revision``.  The
        row's figure is read back from the table and compared against the
        incumbent's §7 blend, computed here independently from the rows this
        test wrote — so the agreement is about the *loop*, not about this
        feature agreeing with itself.
        """
        select = importlib.import_module("dreaming.select")
        incumbent = incumbent_candidate(INCUMBENT_SOURCE, version="pi-0")
        _revision_table(pool)
        # Both strategies aggravate identically on w1/w2 and the revisions are
        # strictly better on w3, so the incumbent is not the winner by accident.
        _write_scores(
            pool, policy_version="pi-0", beta=0.0, readings={"w1": 0.10, "w2": 0.20}
        )
        _write_scores(
            pool, policy_version="cand-a", beta=0.0, readings={"w1": 0.20, "w2": 0.40}
        )

        widened = include_incumbent(
            [_candidate("cand-a", code_hash="a" * 64, parent="pi-0")],
            INCUMBENT_SOURCE,
            version="pi-0",
        )
        crowned = select.commit_selection(
            widened,
            strata={"s": ("w1", "w2")},
            beta=0.0,
            database_url=pool,
        )

        with closing(sqlite3.connect(sqlite_path(pool))) as connection:
            rows = connection.execute(
                "SELECT policy_version, aggregate_score FROM policy_revision "
                "WHERE selected"
            ).fetchall()

        assert len(rows) == 1
        assert rows[0][0] == crowned.module_id == "cand-a"
        # The incumbent's blend over the same strata, computed from the rows
        # above: mean 0.15, and min_g equals the mean with one stratum.
        incumbent_score = (0.10 + 0.20) / 2
        assert rows[0][1] >= incumbent_score
        assert incumbent.module_id in {one.module_id for one in widened}

    def test_the_incumbent_alone_commits_as_its_own_winner(self, pool):
        """The empty-production case at the store seam: ``π^0`` is crowned.

        §C5's guarantee at its most literal — the selected policy *is* the
        incumbent — and the widened set of one is a set feature 274 can select
        over without a tie.  The row's ``policy_version`` is the version this
        feature derived for the source, so the policy a previous cycle wrote as
        ``policy_revision.policy_version`` is the policy restored here.
        """
        select = importlib.import_module("dreaming.select")
        entry = incumbent_candidate(INCUMBENT_SOURCE, version="pi-0")
        _revision_table(pool)
        _write_scores(
            pool, policy_version="pi-0", beta=0.0, readings={"w1": 0.10, "w2": 0.30}
        )

        widened = include_incumbent((), INCUMBENT_SOURCE, version="pi-0")
        crowned = select.commit_selection(
            widened, strata={"s": ("w1", "w2")}, beta=0.0, database_url=pool
        )

        assert crowned.module_id == entry.module_id
        with closing(sqlite3.connect(sqlite_path(pool))) as connection:
            written = connection.execute(
                "SELECT policy_version, code_hash, parent_version, aggregate_score "
                "FROM policy_revision WHERE selected"
            ).fetchone()

        assert written[0] == entry.module_id
        assert written[1] == entry.code_hash  # read, not recomputed
        assert written[2] is None  # the incumbent's own parent, as feature 273 built it
        assert written[3] == pytest.approx(0.20)
