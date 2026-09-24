"""Feature 307's claim, stated as tests: the changelog-entry companion.

app_spec.xml, "Portfolio Book Construction", feature 307: *System requires a
changelog entry accompanying every book construction change, which returns a
validation failure when absent.*  docs/alpha-engine-prd.md §C8 closes the
construction's own section with the rule — *"Version-controlled,
human-authored, explicitly outside the search space.  Changing it is a human
decision with a changelog entry, not a discovery"* — and this suite pins the
clause that rule's *"with a changelog entry"* demands.

So the claims worth pinning are these, and they are what the classes below
are arranged around:

* **the admitted path exists and is exactly one** — a well-stated changelog
  entry accompanying a change runs, which is §C8's own description of how the
  construction changes: a human decision, version-controlled, *with a
  changelog entry*;
* **the refusal is over a present change with no entry beside it** — a `None`
  entry, an omitted entry, or an unstatable one are each refused, and the
  refusal names *which change* was unaccompanied;
* **the boundary is presence, not content** — the entry is admitted as present
  when it is a well-stated `ChangelogEntry` and refused as absent when it is
  not there; this package validates no changelog prose;
* **the ask settles before the judgment** — a caller that handed a broken
  entry is told *state the entry*, never *the entry is missing*, however
  absent the entry meant to be; and an absent change is refused as the ask's
  own fact, not judged;
* **the verdict is over two records the caller already holds** — never a
  database, never a clock, never a filesystem, and the surface is read
  duck-typed so the loader's synthetic-name copies are judged identically;
* **the vocabulary is the companion's own two classes** — the ask
  (:class:`book.ChangelogEntryRequestError`) and the one judgment the sentence
  mints (:class:`book.MissingChangelogEntryError`), both under the member's
  :class:`book.BookConstructionError`, and a caller must be able to catch one
  without catching the other.
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest
from book import (
    MISSING_CHANGELOG_ENTRY_CODE,
    BookConstructionChange,
    BookConstructionError,
    ChangelogEntry,
    ChangelogEntryRequestError,
    MissingChangelogEntryError,
    is_missing_changelog_entry,
    requires_changelog_entry,
)

#: The module the code pin at the foot of this file parses — anchored to the
#: file rather than to the process's working directory, so the suite gives
#: the same answer however pytest was invoked.
MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "book" / "_changelog.py"

#: The commit every fixture change arrives under — forty lowercase hex
#: characters, the spelling ``git rev-parse HEAD`` answers in this
#: repository.
COMMIT = "0123456789abcdef0123456789abcdef01234567"

#: The construction asset every fixture change names — the weighting the
#: combiner applies, which is the asset §C8's own chain names first.
SUBJECT = "the information-ratio weighting"

#: The human every fixture change is authored by.
HUMAN_AUTHOR = "Ada Lovelace"

#: The entry's subject — the asset the changelog entry documents.
ENTRY_SUBJECT = "the information-ratio weighting"

#: The entry's body — the prose a human records when they change the
#: construction, the record §C8's *"with a changelog entry"* demands.
ENTRY_BODY = "Changed the information-ratio weighting from equal to IR-proportional."


def _change() -> BookConstructionChange:
    """A change to be accompanied — the guard's own record, reused here."""
    return BookConstructionChange(SUBJECT, HUMAN_AUTHOR, "human", COMMIT)


def _entry() -> ChangelogEntry:
    """§C8's admitted companion as a value: the entry that documents the change."""
    return ChangelogEntry(ENTRY_SUBJECT, ENTRY_BODY)


class TestTheAdmittedPath:
    """A change with its entry beside it runs — the one path there is."""

    def test_a_change_with_its_entry_runs(self):
        """§C8's own sentence for how the construction changes, accompanied.

        *"Changing it is a human decision with a changelog entry"* — the
        change that names a human author and the entry that documents it are
        the change the sentence describes, and the verdict returns None for
        them: the companion keeps the construction accompanied, it does not
        make changing it impossible.
        """
        assert requires_changelog_entry(_change(), _entry()) is None

    def test_the_predicate_reads_the_same_fact(self):
        """``is_missing_changelog_entry`` is the judgment's read-only spelling.

        The two cannot disagree because they settle the ask and the presence
        once — and a caller that only wants to know (a report, an audit line)
        gets the fact without the refusal.
        """
        assert is_missing_changelog_entry(_change(), _entry()) is False

    def test_the_record_is_frozen(self):
        """A caller who could rewrite an entry in memory would need no agent —
        the record is the document, and it does not move.

        The same reason :class:`book.BookConstructionChange` is frozen: a
        caller who could edit the subject or the body after the fact could
        rewrite what the change was documented to say without the human
        decision §C8 demands.
        """
        entry = _entry()
        with pytest.raises(dataclasses.FrozenInstanceError):
            entry.body = "rewritten"  # type: ignore[misc]

    def test_the_free_strings_strip(self):
        """Subject and body are free strings (one spelling worth storing).

        So a padded subject is the same subject — two records over the same
        padded and stripped fields are one entry — and the entry's equality
        reads one spelling of the name.
        """
        padded = ChangelogEntry(f"  {ENTRY_SUBJECT} ", f" {ENTRY_BODY} ")
        assert padded == _entry()
        assert padded.subject == ENTRY_SUBJECT
        assert padded.body == ENTRY_BODY

    def test_two_verdicts_over_the_same_pair_agree(self):
        """Deterministic: the companion holds no state and reads no clock."""
        change, entry = _change(), _entry()
        assert requires_changelog_entry(change, entry) is None
        assert requires_changelog_entry(change, entry) is None
        assert is_missing_changelog_entry(change, entry) is False


class TestTheBoundaryIsPresence:
    """Admitted as present when well-stated; refused as absent when not there."""

    def test_a_none_entry_is_absent(self):
        """The sentence's *absent*, plainly: no entry handed, the change
        unaccompanied."""
        assert is_missing_changelog_entry(_change(), None) is True
        with pytest.raises(MissingChangelogEntryError):
            requires_changelog_entry(_change(), None)

    def test_an_omitted_field_is_absent_not_broken(self):
        """The sentinel discipline: an entry that *omits* its body is absent
        (it could not be stated), distinct from one that carries a blank body
        (stated, and stated badly — the ask's own fact)."""
        namespace = {"subject": ENTRY_SUBJECT}
        omitted = type("EntryNoBody", (), namespace)()
        assert is_missing_changelog_entry(_change(), omitted) is True
        with pytest.raises(MissingChangelogEntryError):
            requires_changelog_entry(_change(), omitted)

    def test_a_present_but_broken_entry_is_the_ask_not_the_judgment(self):
        """A blank body is a stated-but-bad entry — refused at the ask, never
        judged missing, so a caller can tell *state the entry* from *the entry
        is missing*."""
        with pytest.raises(ChangelogEntryRequestError):
            ChangelogEntry(ENTRY_SUBJECT, "   ")
        with pytest.raises(ChangelogEntryRequestError):
            requires_changelog_entry(_change(), ChangelogEntry("  ", ENTRY_BODY))


class TestTheRefusal:
    """``requires_changelog_entry`` — feature 307's own sentence."""

    def test_the_refusal_opens_with_its_greppable_code(self):
        """The code is the first token of every judgment message."""
        assert MISSING_CHANGELOG_ENTRY_CODE == "missing_changelog_entry"
        with pytest.raises(MissingChangelogEntryError) as caught:
            requires_changelog_entry(_change(), None)
        assert str(caught.value).split(":")[0] == MISSING_CHANGELOG_ENTRY_CODE

    def test_the_refusal_names_the_change(self):
        """The refusal says *which change* was unaccompanied — the subject,
        the author, the kind and the revision it claimed to arrive under."""
        with pytest.raises(MissingChangelogEntryError) as caught:
            requires_changelog_entry(_change(), None)
        message = str(caught.value)
        assert SUBJECT in message
        assert HUMAN_AUTHOR in message
        assert "human" in message
        assert COMMIT in message

    def test_the_refusal_cites_the_documents_rule(self):
        """The verdict cites §C8's line, not a paraphrase of it."""
        with pytest.raises(MissingChangelogEntryError) as caught:
            requires_changelog_entry(_change(), None)
        message = str(caught.value)
        assert "changelog entry" in message
        assert "not a discovery" in message

    def test_the_refusal_states_the_one_repair(self):
        """*A human accompanies the change with the entry it requires* — and
        there is no fabrication repair.

        The message must not offer to invent the human's own document (that
        would be this module writing the changelog), and must not offer to
        proceed: the repair is the sentence's own, a person deciding, under
        version control, with the entry that documents it.
        """
        with pytest.raises(MissingChangelogEntryError) as caught:
            requires_changelog_entry(_change(), None)
        message = str(caught.value)
        assert "accompanies" in message
        assert "a human" in message.lower()

    def test_the_verdict_forms_no_value(self):
        """A refused change leaves nothing behind — it raises, and the
        admitted path answers None."""
        assert requires_changelog_entry(_change(), _entry()) is None
        with pytest.raises(MissingChangelogEntryError):
            requires_changelog_entry(_change(), None)


class TestTheAskIsRefusedBeforeAnythingIsJudged:
    """The ask's own facts — :class:`book.ChangelogEntryRequestError`, no code."""

    @pytest.mark.parametrize("subject", ["", "   ", None, 7, b"the weighting"])
    def test_a_malformed_entry_subject_is_refused(self, subject):
        """An entry that names no subject documents nothing."""
        with pytest.raises(ChangelogEntryRequestError):
            ChangelogEntry(subject, ENTRY_BODY)

    @pytest.mark.parametrize("body", ["", "   ", None, 7])
    def test_a_malformed_entry_body_is_refused(self, body):
        """An entry that records nothing is not a changelog entry."""
        with pytest.raises(ChangelogEntryRequestError):
            ChangelogEntry(ENTRY_SUBJECT, body)

    def test_the_ask_carries_no_code_word(self):
        """A malformed entry names its subject in its first words, not a
        token — the one code on this feature's path is the *judgment*'s, and
        a developer's token on a fact the caller can simply state would be the
        wrong word for the wrong reader."""
        with pytest.raises(ChangelogEntryRequestError) as caught:
            ChangelogEntry(ENTRY_SUBJECT, "")
        assert not str(caught.value).startswith(MISSING_CHANGELOG_ENTRY_CODE)

    def test_an_absent_change_is_refused_as_the_ask_not_judged(self):
        """A companion cannot say which change is unaccompanied when no change
        was handed — the change is the ask's own fact, refused before any
        presence is judged, however present the entry meant to be."""
        with pytest.raises(ChangelogEntryRequestError):
            requires_changelog_entry(None, _entry())
        with pytest.raises(ChangelogEntryRequestError):
            is_missing_changelog_entry(None, _entry())

    def test_the_ask_settles_before_the_judgment_can_fire(self):
        """Even a change whose entry is absent meets a well-stated ask first.

        The ordering every verdict in this workspace states: a change with a
        present, well-stated entry runs; a change with a broken entry is told
        *state the entry*, not judged — the caller is told what to fix rather
        than told the boundary fired, on the strength of a record that could
        not have been stated at all."""
        change = _change()
        # A well-stated entry accompanies the change: admitted.
        assert requires_changelog_entry(change, _entry()) is None
        # A broken entry, even for a change that is present: the ask.
        with pytest.raises(ChangelogEntryRequestError):
            requires_changelog_entry(change, ChangelogEntry(ENTRY_SUBJECT, "  "))

    def test_the_verdict_reads_the_surface_duck_typed(self):
        """A stand-in carrying the entry's two attributes is judged
        identically.

        The loader imports members under synthetic names and re-executes
        them, so a record this process composed may be a second class object —
        the verdict reads the surface, never the type, and this is the seam
        that keeps the composed and canonical copies under one law.
        """
        stand_in = _StandInEntry(ENTRY_SUBJECT, ENTRY_BODY)
        assert is_missing_changelog_entry(_change(), stand_in) is False
        assert requires_changelog_entry(_change(), stand_in) is None
        # An entry stand-in with no body attribute is absent.
        no_body = type("NoBody", (), {"subject": ENTRY_SUBJECT})()
        assert is_missing_changelog_entry(_change(), no_body) is True


class TestTheVocabularyOfErrors:
    """The companion's two classes, and how they sit under the member's base."""

    def test_both_faces_are_book_construction_errors(self):
        """A caller that refuses book work wholesale writes one ``except``."""
        assert issubclass(ChangelogEntryRequestError, BookConstructionError)
        assert issubclass(MissingChangelogEntryError, BookConstructionError)

    def test_the_ask_is_not_the_judgment(self):
        """But a caller that must react differently can tell them apart.

        An absent entry is refusable though the entry field was perfectly well
        formed (it was simply not handed), and a mis-stated entry is refusable
        though an entry was handed, so the two facts are genuinely different:
        catching one must not catch the other, or a caller would re-inspect
        something it cannot tell apart."""
        assert not issubclass(
            MissingChangelogEntryError, ChangelogEntryRequestError
        )
        assert not issubclass(
            ChangelogEntryRequestError, MissingChangelogEntryError
        )
        with pytest.raises(ChangelogEntryRequestError):
            ChangelogEntry(ENTRY_SUBJECT, "")
        try:
            requires_changelog_entry(_change(), None)
        except ChangelogEntryRequestError:  # pragma: no cover - the ask under test
            pytest.fail("the judgment was caught as a malformed ask")
        except MissingChangelogEntryError:
            pass

    def test_the_combiner_can_raise_a_bare_base_error(self):
        """The base is still catchable on its own — the two faces are
        additions.  Feature 301's ``combine`` raises the *base* class
        directly, so the hierarchy the companion added has to leave that
        reachable: nothing about 307 narrows 301's, 306's or 308's surface."""
        from book import combine

        with pytest.raises(BookConstructionError):
            combine([])


class TestTheLayering:
    """The companion costs composition nothing, and it looks nothing up."""

    def test_the_module_is_stdlib_only(self):
        """The factory's scan imports this package; the companion must cost it
        zero.  Parsed rather than trusted: an ``import numpy`` added to
        :mod:`book._changelog` would be invisible to every behavioural test
        here and would put a third-party wheel on the path of the factory's
        scan — the one bill this member's layering note promises not to pay."""
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
        already excludes absolute ones by name; this pins the *relative* half
        so a future edit cannot reach out to another member for the vocabulary
        it restates here."""
        tree = ast.parse(MODULE_PATH.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level:
                assert node.module in {"errors"}, node.module

    def test_the_module_opens_no_store_reads_no_environment_and_consults_no_clock(self):
        """A verdict is not a measurement, and neither is it a read.

        The module must not grow a database dependency, an environment
        variable, a clock or a filesystem: its whole subject is two records
        the caller already holds — and a version that opened a store would be
        answering a question about the deployment from inside a judgment."""
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

    def test_no_verb_takes_a_content_parameter(self):
        """The boundary is presence, not content — pinned at the signature.
        Checked through the function objects rather than the source text, so a
        renamed keyword still fails the test: neither spelling of the companion
        accepts a content parameter of any spelling, which is what makes the
        boundary the document's rule rather than a deployment's preference."""
        import inspect

        for call in (is_missing_changelog_entry, requires_changelog_entry):
            parameters = set(inspect.signature(call).parameters)
            assert parameters == {"change", "entry"}, parameters

    def test_the_judgment_needs_no_database(self, monkeypatch):
        """Exercised in a process with no ``DATABASE_URL`` at all.

        The behavioural half of the claim above: the verdict runs with the
        deployment's database variable deleted, so a version that had grown a
        store dependency would fail here rather than in production."""
        monkeypatch.delenv("DATABASE_URL", raising=False)
        assert requires_changelog_entry(_change(), _entry()) is None
        with pytest.raises(MissingChangelogEntryError):
            requires_changelog_entry(_change(), None)

    def test_the_companion_is_deterministic(self):
        """Two records over the same fields are one change and one entry, and
        the predicate and the verdict answer them identically every time."""
        first_change, second_change = _change(), _change()
        first_entry, second_entry = _entry(), _entry()
        assert first_change == second_change
        assert first_entry == second_entry
        assert (
            is_missing_changelog_entry(first_change, first_entry)
            == is_missing_changelog_entry(second_change, second_entry)
            is False
        )
        assert requires_changelog_entry(first_change, first_entry) is None
        assert requires_changelog_entry(second_change, second_entry) is None


@dataclasses.dataclass(frozen=True)
class _StandInEntry:
    """A stand-in for a changelog entry.

    The verdict reads the ``subject`` / ``body`` surface duck-typed — the
    loader imports members under synthetic names and re-executes them, so a
    record this process composed may be a second class object — and this is
    the shape that proves it: exactly those two attributes, nothing else, so a
    test judging one of these exercises the seam the verdict actually depends
    on, not the member's own class.
    """

    subject: object
    body: object
