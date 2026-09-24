"""Feature 306's claim, stated as tests: the authorship guard.

app_spec.xml, "Portfolio Book Construction", feature 306: *System keeps book
construction human-authored and version-controlled, which rejects any
agent-authored modification to it.*  docs/alpha-engine-prd.md §C8 closes the
construction's own section with the rule — *"Version-controlled,
human-authored, explicitly outside the search space.  Changing it is a human
decision with a changelog entry, not a discovery"* — and §2.2 NG1 says it
from the other side (*"Not a strategy optimizer"*).  This suite pins the
boundary that rule demands.

So the claims worth pinning are these, and they are what the classes below
are arranged around:

* **the admitted path exists and is exactly one** — a human-authored change
  under a full commit id runs, which is §C8's own description of how the
  construction changes: a human decision, version-controlled;
* **the refusal is over *any* agent-authored modification** — every declared
  agent kind is refused, and nothing outside the one human kind is admitted
  by any route: a near-miss or unknown kind is refused at the ask, so the
  vocabulary fails closed (the prohibition shape, not an allowlist);
* **the version-controlled half is structural** — a change that names no
  commit cannot be stated at all, and neither can one that names a mutable
  pointer, an ambiguous short id or a working-tree marker;
* **the ask settles before the judgment** — a caller that handed a broken
  record is told *what to fix*, never *an agent authored this*, however
  agent-authored the change meant to be;
* **the verdict is over a record the caller already holds** — never a
  database, never a clock, never a filesystem, and the surface is read
  duck-typed so the loader's synthetic-name copies are judged identically;
* **the vocabulary is the guard's own two classes** — the ask
  (:class:`book.BookChangeRequestError`) and the one judgment the sentence
  mints (:class:`book.AgentAuthoredModificationError`), both under the
  member's :class:`book.BookConstructionError`, and a caller must be able to
  catch one without catching the other.
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest
from book import (
    AGENT_AUTHOR_KINDS,
    AGENT_MODIFICATION_CODE,
    AUTHOR_KINDS,
    HUMAN_AUTHOR_KIND,
    REVISION_HEX_LENGTH,
    AgentAuthoredModificationError,
    BookChangeRequestError,
    BookConstructionChange,
    BookConstructionError,
    is_agent_authored,
    rejects_agent_authored_modification,
)

#: The module the code pin at the foot of this file parses — anchored to the
#: file rather than to the process's working directory, so the suite gives
#: the same answer however pytest was invoked.
MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "book" / "_authorship.py"

#: The commit every fixture change arrives under — forty lowercase hex
#: characters, the spelling ``git rev-parse HEAD`` answers in this
#: repository.  Dyadic in the way that matters here: not a number at all,
#: but exact, so the admitted and refused spellings differ by characters a
#: test can name rather than by an epsilon.
COMMIT = "0123456789abcdef0123456789abcdef01234567"

#: The construction asset every fixture change names — the weighting the
#: combiner applies, which is the asset §C8's own chain names first.
SUBJECT = "the information-ratio weighting"

#: The human every admitted fixture change is authored by.  A person's
#: name, spelled as a person spells it — the point of the fixture is that
#: the guard reads the *kind*, never the name.
HUMAN_AUTHOR = "Ada Lovelace"


def _human_change() -> BookConstructionChange:
    """§C8's admitted path as a value: a human decision, under a commit."""
    return BookConstructionChange(SUBJECT, HUMAN_AUTHOR, "human", COMMIT)


def _agent_change(kind: str) -> BookConstructionChange:
    """The search reaching for the construction, as a value."""
    return BookConstructionChange(SUBJECT, "the loop", kind, COMMIT)


class TestTheAdmittedPath:
    """A human decision under version control runs — the one path there is."""

    def test_a_human_authored_version_controlled_change_runs(self):
        """§C8's own sentence for how the construction changes, admitted.

        *"Changing it is a human decision with a changelog entry"* — the
        change record that states a human author and names its commit is
        the change the sentence describes, and the verdict returns None
        for it: the guard keeps the construction human-authored, it does
        not make changing it impossible.
        """
        assert rejects_agent_authored_modification(_human_change()) is None

    def test_the_predicate_reads_the_same_fact(self):
        """``is_agent_authored`` is the judgment's read-only spelling.

        The two cannot disagree because they spell the comparison once —
        and a caller that only wants to know (a report, an audit line)
        gets the fact without the refusal.
        """
        assert is_agent_authored(_human_change()) is False

    def test_the_record_is_frozen(self):
        """A caller who could re-author a change in memory would need no
        agent — the record is the decision, and it does not move.

        The same reason :class:`book.PromotedSignal` is frozen: a caller
        who could edit the author or the commit after the fact could
        re-author the construction's history without the human decision
        §C8 demands.
        """
        change = _human_change()
        with pytest.raises(dataclasses.FrozenInstanceError):
            change.author_kind = "discovery"  # type: ignore[misc]

    def test_the_free_names_strip_and_the_laws_spell_exactly(self):
        """Subject and author are names (one spelling worth storing);
        kind and revision are laws (one spelling, period).

        So a padded subject is the same subject — two records over the
        same padded and stripped fields are one change — while the kind
        and the revision are never folded, case-insensitively or
        otherwise: the vocabulary and the commit id are exact spellings,
        and the tests below refuse their near-misses.
        """
        padded = BookConstructionChange(
            f"  {SUBJECT} ", f" {HUMAN_AUTHOR} ", "human", COMMIT
        )
        assert padded == _human_change()
        assert padded.subject == SUBJECT
        assert padded.author == HUMAN_AUTHOR

    def test_two_verdicts_over_the_same_change_agree(self):
        """Deterministic: the guard holds no state and reads no clock."""
        change = _agent_change("dreaming")
        with pytest.raises(AgentAuthoredModificationError) as first:
            rejects_agent_authored_modification(change)
        with pytest.raises(AgentAuthoredModificationError) as second:
            rejects_agent_authored_modification(change)
        assert str(first.value) == str(second.value)


class TestTheVocabulary:
    """One admitted kind, five declared agents, and nothing else.

    The vocabulary is a prohibition rather than an allowlist (features
    246/247's shape for their wall): the boundary is the human kind, and
    everything that is not it is agent-authored — declared or not.
    """

    def test_the_one_admitted_kind_is_human(self):
        """§C8's word, spelled once: *"human-authored"*."""
        assert HUMAN_AUTHOR_KIND == "human"

    def test_the_agent_kinds_are_the_systems_own_authors(self):
        """Each name greppable to where the system itself mints it.

        ``agent`` is policy-runtime's phrase for the authoring process,
        ``discovery`` is §C8's (*"not a discovery"*), ``dreaming`` is the
        reviser that lawfully revises policy source, ``optimizer`` is
        NG1's (*"Not a strategy optimizer"*), ``worker`` is the batch
        pool.  Pinned exactly, because the vocabulary is closed.
        """
        assert AGENT_AUTHOR_KINDS == frozenset(
            {"agent", "discovery", "dreaming", "optimizer", "worker"}
        )

    def test_the_vocabulary_is_the_union_and_human_is_not_an_agent(self):
        """The declared whole, and the two halves disjoint."""
        assert AUTHOR_KINDS == frozenset({HUMAN_AUTHOR_KIND}) | AGENT_AUTHOR_KINDS
        assert HUMAN_AUTHOR_KIND not in AGENT_AUTHOR_KINDS
        assert len(AUTHOR_KINDS) == len(AGENT_AUTHOR_KINDS) + 1

    @pytest.mark.parametrize("kind", sorted(AGENT_AUTHOR_KINDS))
    def test_every_declared_agent_kind_is_refused(self, kind):
        """The sentence's *any*: all five land on the refused side.

        The refusal is the sentence's own outcome for an automated author,
        whatever it promises — the loop that found something, the reviser
        that improved something, the pool that wrote something down.
        """
        with pytest.raises(AgentAuthoredModificationError) as caught:
            rejects_agent_authored_modification(_agent_change(kind))
        assert str(caught.value).startswith(AGENT_MODIFICATION_CODE)
        assert kind in str(caught.value)

    @pytest.mark.parametrize("kind", sorted(AGENT_AUTHOR_KINDS))
    def test_the_predicate_agrees_for_every_agent_kind(self, kind):
        """The read-only spelling answers True for each of them."""
        assert is_agent_authored(_agent_change(kind)) is True

    @pytest.mark.parametrize(
        "kind",
        ["Human", "HUMAN", "human ", "humna", "ci-bot", "operator", "machine"],
    )
    def test_a_near_miss_or_unknown_kind_is_refused_at_the_ask(self, kind):
        """Feature 241's stance: a near-miss is refused, not mapped.

        The ask refuses the spelling so a caller that misnames its author
        is told *what to fix* — and the fail-closed property holds by
        construction: nothing outside ``"human"`` is admitted by any
        route, so an unknown kind is no gap in the guard, only a gap in
        the caller's spelling of it.
        """
        with pytest.raises(BookChangeRequestError):
            BookConstructionChange(SUBJECT, HUMAN_AUTHOR, kind, COMMIT)
        with pytest.raises(BookChangeRequestError):
            rejects_agent_authored_modification(
                _StandInChange(SUBJECT, HUMAN_AUTHOR, kind, COMMIT)
            )
        with pytest.raises(BookChangeRequestError):
            is_agent_authored(_StandInChange(SUBJECT, HUMAN_AUTHOR, kind, COMMIT))


@dataclasses.dataclass(frozen=True)
class _StandInChange:
    """A stand-in for a book construction change.

    The verdict reads the ``subject`` / ``author`` / ``author_kind`` /
    ``revision`` surface duck-typed — the loader imports members under
    synthetic names and re-executes them, so a record this process
    composed may be a second class object — and this is the shape that
    proves it: exactly those four attributes, nothing else, so a test
    judging one of these exercises the seam the verdict actually depends
    on, not the member's own class.
    """

    subject: object
    author: object
    author_kind: object
    revision: object


def _partial_change(absent: str) -> object:
    """A stand-in carrying the surface *minus* one attribute.

    For the sentinel discipline: an attribute the record omits entirely
    is an unstatable ask, distinct from one present-and-``None``, and this
    builds the omission the verdict's ``_MISSING`` read must catch.
    """
    namespace = {
        "subject": SUBJECT,
        "author": HUMAN_AUTHOR,
        "author_kind": "human",
        "revision": COMMIT,
    }
    namespace.pop(absent)
    return type("PartialChange", (), namespace)()


class TestTheVersionControlledHalf:
    """A change that names no commit cannot be stated — §C8's other word.

    *"Version-controlled"* is the half of the sentence the record makes
    structural: the revision is the full commit id, and every other
    spelling names no version-controlled state at all.
    """

    def test_the_commit_is_forty_lowercase_hex(self):
        """One spelling, pinned: what ``git rev-parse HEAD`` answers here."""
        assert REVISION_HEX_LENGTH == 40
        assert len(COMMIT) == REVISION_HEX_LENGTH

    @pytest.mark.parametrize(
        "revision",
        [
            None,
            "",
            "   ",
            "HEAD",
            "main",
            "feat/book-construction",
            "v1.2.3",
            "dirty",
            "working-tree",
            "uncommitted",
            COMMIT[:39],  # one short — an ambiguous id
            COMMIT + "0",  # one long
            COMMIT.upper(),  # a near-miss of the one spelling
            "z" * REVISION_HEX_LENGTH,  # not hexadecimal
            "0123456789abcdef",  # a short id a small repository would accept
            12345,  # not a string at all
        ],
    )
    def test_no_other_spelling_names_a_version_controlled_state(self, revision):
        """Mutable pointers, ambiguous ids, working-tree markers: refused.

        A branch, a tag or HEAD can be moved to different bytes while
        keeping its name (the canary lockfile refuses the same spellings
        for the same reason); a short id is a promise nothing keeps once
        the repository grows; and an absent revision is a working-tree
        edit — the un-version-controlled thing the sentence exists to
        refuse.
        """
        with pytest.raises(BookChangeRequestError):
            BookConstructionChange(SUBJECT, HUMAN_AUTHOR, "human", revision)

    def test_an_absent_revision_cannot_even_be_omitted(self):
        """The field is required — a change without a commit is not a
        change this vocabulary can state, and the dataclass says so before
        any validator runs."""
        with pytest.raises(TypeError):
            BookConstructionChange(SUBJECT, HUMAN_AUTHOR, "human")

    def test_a_well_stated_revision_is_admitted_for_a_human(self):
        """And the admitted path carries it — the record states the commit
        it runs under, which is what makes the change version-controlled
        rather than merely authored."""
        change = _human_change()
        assert change.revision == COMMIT
        assert rejects_agent_authored_modification(change) is None


class TestTheVerdict:
    """``rejects_agent_authored_modification`` — feature 306's own sentence."""

    def test_the_refusal_opens_with_its_greppable_code(self):
        """The code is the first token of every judgment message."""
        assert AGENT_MODIFICATION_CODE == "agent_authored_modification"
        with pytest.raises(AgentAuthoredModificationError) as caught:
            rejects_agent_authored_modification(_agent_change("discovery"))
        assert str(caught.value).split(":")[0] == AGENT_MODIFICATION_CODE

    def test_the_refusal_names_the_change(self):
        """The refusal is actionable without a stack trace: the subject
        (what the search reached for), the author, the kind and the
        revision it claimed to arrive under."""
        with pytest.raises(AgentAuthoredModificationError) as caught:
            rejects_agent_authored_modification(_agent_change("discovery"))
        message = str(caught.value)
        assert SUBJECT in message
        assert "the loop" in message
        assert "discovery" in message
        assert COMMIT in message

    def test_the_refusal_cites_the_documents_rule(self):
        """The verdict cites §C8's line and NG1's non-goal, not a
        paraphrase of them."""
        with pytest.raises(AgentAuthoredModificationError) as caught:
            rejects_agent_authored_modification(_agent_change("dreaming"))
        message = str(caught.value)
        assert "outside the search space" in message
        assert "a human decision" in message
        assert "not a discovery" in message
        assert "Not a strategy optimizer" in message

    def test_the_refusal_routes_the_agent_to_its_own_path(self):
        """The search's business is signals — the message says where a
        finding the search believes in *does* go: through the promotion
        path, as a promoted signal, where the weighting decides what it
        is worth.  Never as an edit to the construction that weights it,
        because a search allowed to improve its own weighting function
        has stopped being measured by it.
        """
        with pytest.raises(AgentAuthoredModificationError) as caught:
            rejects_agent_authored_modification(_agent_change("agent"))
        message = str(caught.value)
        assert "promotion path" in message
        assert "promoted signal" in message

    def test_the_refusal_states_the_one_repair(self):
        """*A human makes this change* — and there is no other.

        The message must not offer relabelling (``re-state the
        author_kind`` would be an instruction to talk the guard out of
        its own boundary) and must not offer to proceed: the repair is
        the sentence's own, a person deciding, under version control.
        """
        with pytest.raises(AgentAuthoredModificationError) as caught:
            rejects_agent_authored_modification(_agent_change("worker"))
        message = str(caught.value)
        assert "a human makes this change" in message
        assert "re-state" not in message
        assert "relabel" not in message

    def test_the_verdict_forms_no_value(self):
        """A refused change leaves nothing behind — it raises, and the
        admitted path answers None."""
        assert rejects_agent_authored_modification(_human_change()) is None
        with pytest.raises(AgentAuthoredModificationError):
            rejects_agent_authored_modification(_agent_change("optimizer"))


class TestTheAskIsRefusedBeforeAnythingIsJudged:
    """The ask's own facts — :class:`book.BookChangeRequestError`, no code."""

    @pytest.mark.parametrize("subject", ["", "   ", None, 7, b"the weighting"])
    def test_a_malformed_subject_is_refused(self, subject):
        """A change that names no subject guards nothing."""
        with pytest.raises(BookChangeRequestError):
            BookConstructionChange(subject, HUMAN_AUTHOR, "human", COMMIT)

    @pytest.mark.parametrize("author", ["", "   ", None, 7])
    def test_a_malformed_author_is_refused(self, author):
        """Authorship is the whole fact judged; a change that states none
        cannot be judged human- or agent-authored."""
        with pytest.raises(BookChangeRequestError):
            BookConstructionChange(SUBJECT, author, "human", COMMIT)

    def test_a_non_string_kind_is_refused(self):
        """The vocabulary is spelled, not flagged."""
        with pytest.raises(BookChangeRequestError):
            BookConstructionChange(SUBJECT, HUMAN_AUTHOR, True, COMMIT)

    def test_the_ask_carries_no_code_word(self):
        """A malformed change names its subject in its first words, not a
        token — the one code on this feature's path is the *judgment*'s,
        and a developer's token on a fact the caller can simply fix would
        be the wrong word for the wrong reader."""
        with pytest.raises(BookChangeRequestError) as caught:
            BookConstructionChange(SUBJECT, HUMAN_AUTHOR, "human", "HEAD")
        assert not str(caught.value).startswith(AGENT_MODIFICATION_CODE)

    def test_the_ask_settles_before_the_judgment_can_fire(self):
        """Even an agent-authored change meets the ask's class first.

        The ordering every verdict in this workspace states: an
        agent-authored change whose revision is a mutable pointer is told
        *name the commit*, not *an agent authored this* — the caller is
        told what to fix rather than told the boundary fired, on the
        strength of a record that could not have been stated at all.
        """
        agent_broken = _StandInChange(SUBJECT, "the loop", "dreaming", "main")
        with pytest.raises(BookChangeRequestError):
            rejects_agent_authored_modification(agent_broken)
        with pytest.raises(BookChangeRequestError):
            is_agent_authored(agent_broken)

    def test_the_verdict_reads_the_surface_duck_typed(self):
        """A stand-in carrying the four attributes is judged identically.

        The loader imports members under synthetic names and re-executes
        them, so a record this process composed may be a second class
        object — the verdict reads the surface, never the type, and this
        is the seam that keeps the composed and canonical copies under
        one law.
        """
        stand_in = _StandInChange(SUBJECT, HUMAN_AUTHOR, "human", COMMIT)
        assert rejects_agent_authored_modification(stand_in) is None
        assert is_agent_authored(stand_in) is False
        agent_stand_in = _StandInChange(SUBJECT, "the loop", "dreaming", COMMIT)
        with pytest.raises(AgentAuthoredModificationError):
            rejects_agent_authored_modification(agent_stand_in)
        assert is_agent_authored(agent_stand_in) is True

    def test_an_absent_attribute_is_not_a_present_none(self):
        """The sentinel discipline: a record that omits a field is
        unstatable, not one that declared it ``None`` — and each of the
        four absences is refused as the ask's own fact."""
        for absent in ("subject", "author", "author_kind", "revision"):
            with pytest.raises(BookChangeRequestError):
                rejects_agent_authored_modification(_partial_change(absent))
            with pytest.raises(BookChangeRequestError):
                is_agent_authored(_partial_change(absent))


class TestTheVocabularyOfErrors:
    """The guard's two classes, and how they sit under the member's base."""

    def test_both_faces_are_book_construction_errors(self):
        """A caller that refuses book work wholesale writes one ``except``."""
        assert issubclass(BookChangeRequestError, BookConstructionError)
        assert issubclass(AgentAuthoredModificationError, BookConstructionError)

    def test_the_ask_is_not_the_judgment(self):
        """But a caller that must react differently can tell them apart.

        An agent-authored change is refusable though perfectly well
        stated, and a mis-stated change is refusable though a human wrote
        it, so the two facts are genuinely different: catching one must
        not catch the other, or a caller would re-inspect something it
        cannot tell apart.
        """
        assert not issubclass(AgentAuthoredModificationError, BookChangeRequestError)
        assert not issubclass(BookChangeRequestError, AgentAuthoredModificationError)
        with pytest.raises(BookChangeRequestError):
            BookConstructionChange(SUBJECT, HUMAN_AUTHOR, "human", "HEAD")
        try:
            rejects_agent_authored_modification(_agent_change("agent"))
        except BookChangeRequestError:  # pragma: no cover - the branch under test
            pytest.fail("the judgment was caught as a malformed ask")
        except AgentAuthoredModificationError:
            pass

    def test_the_combiner_can_raise_a_bare_base_error(self):
        """The base is still catchable on its own — the two faces are
        additions.  Feature 301's ``combine`` raises the *base* class
        directly, so the hierarchy the guard added has to leave that
        reachable: nothing about 306 narrows 301's or 308's surface."""
        from book import combine

        with pytest.raises(BookConstructionError):
            combine([])


class TestTheLayering:
    """The guard costs composition nothing, and it looks nothing up."""

    def test_the_module_is_stdlib_only(self):
        """The factory's scan imports this package; the guard must cost it
        zero.  Parsed rather than trusted: an ``import numpy`` added to
        :mod:`book._authorship` would be invisible to every behavioural
        test here and would put a third-party wheel on the path of the
        factory's scan — the one bill this member's layering note promises
        not to pay.
        """
        tree = ast.parse(MODULE_PATH.read_text())
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported.add(node.module.split(".")[0])
        assert imported <= {"dataclasses", "typing", "__future__"}, imported

    def test_the_module_imports_no_other_workspace_member(self):
        """A member never imports a member — the workspace's own contract.

        Only relative imports are admissible, and the parsed check above
        already excludes absolute ones by name; this pins the *relative*
        half so a future edit cannot reach out to ``dreaming`` or
        ``canary`` for the vocabulary it restates here.
        """
        tree = ast.parse(MODULE_PATH.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level:
                assert node.module in {"errors"}, node.module

    def test_the_module_opens_no_store_reads_no_environment_and_consults_no_clock(self):
        """A verdict is not a measurement, and neither is it a read.

        The module must not grow a database dependency, an environment
        variable, a clock or a filesystem: its whole subject is a record
        the caller already holds, the commit it names *being* its
        timestamp — and a version that opened a store would be answering
        a question about the deployment from inside a judgment.
        """
        source = MODULE_PATH.read_text()
        for forbidden in (
            "sqlite3",
            "os.environ",
            "getenv",
            "datetime",
            "time.",
            "subprocess",
            "pathlib",
        ):
            assert forbidden not in source, forbidden

    def test_no_verb_takes_an_admitted_kinds_parameter(self):
        """The admitted set is a constant, not a knob — pinned at the
        signature.  Checked through the function objects rather than the
        source text, so a renamed keyword still fails the test: neither
        spelling of the guard accepts an ``admitted_kinds=``, ``allow=``
        or any other parameter a deployment could widen the boundary
        through, which is what makes the guard the document's rule rather
        than a deployment's preference.
        """
        import inspect

        for call in (is_agent_authored, rejects_agent_authored_modification):
            parameters = set(inspect.signature(call).parameters)
            assert parameters == {"change"}, parameters
        assert isinstance(AUTHOR_KINDS, frozenset)
        assert isinstance(AGENT_AUTHOR_KINDS, frozenset)

    def test_the_judgment_needs_no_database(self, monkeypatch):
        """Exercised in a process with no ``DATABASE_URL`` at all.

        The behavioural half of the claim above: the verdict runs with
        the deployment's database variable deleted, so a version that had
        grown a store dependency would fail here rather than in
        production.
        """
        monkeypatch.delenv("DATABASE_URL", raising=False)
        assert rejects_agent_authored_modification(_human_change()) is None
        with pytest.raises(AgentAuthoredModificationError):
            rejects_agent_authored_modification(_agent_change("discovery"))

    def test_the_guard_is_deterministic(self):
        """Two records over the same fields are one change, and the
        predicate and the verdict answer it identically every time."""
        first = BookConstructionChange(SUBJECT, HUMAN_AUTHOR, "human", COMMIT)
        second = BookConstructionChange(SUBJECT, HUMAN_AUTHOR, "human", COMMIT)
        assert first == second
        assert is_agent_authored(first) == is_agent_authored(second) is False
        assert rejects_agent_authored_modification(first) is None
        assert rejects_agent_authored_modification(second) is None
