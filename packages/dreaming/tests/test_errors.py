"""The member's error vocabulary, and the line it deliberately does not cross.

This workspace splits error vocabularies by *the repair the caller must make*,
one base class per member and a greppable code prefix per failure.  Feature
270's sentence has two faces, and this suite pins them as two classes:

* :class:`~dreaming.errors.FreezeRequestError` — a malformed **ask**.  The
  iteration id names nothing, the instant is naive, the URL is a scheme this
  member cannot speak or an in-memory database.  Refused before anything is
  read or written, and deliberately **not** a `PoolFrozenError`: the repair is
  to fix the call, not to stop writing.
* :class:`~dreaming.errors.PoolFrozenError` — the **rule** broken.  A writer
  was refused, a second iteration tried to hold a held pool, or the pool was
  found changed when the freeze was checked.  The repair is the same for all
  three: *stop writing, or close the iteration.*

And it pins the one code this member carries as a **second sentence**, not a
third face of feature 270: ``pool_too_thin``, which is docs/alpha-engine-prd.md
§12.1's ladder floor — a precondition on a run that has not started, which is
feature 275's own sentence and its own class, :class:`PoolTooThinError`, a
sibling of feature 270's two classes under the one ``DreamingError`` base.  A
member that folded it into feature 270's ``PoolFrozenError`` would make a caller
that must react differently to *the pool is held* and *the pool is too thin to
dream on* catch one class and re-inspect something it cannot tell apart.
"""

from __future__ import annotations

import datetime as dt

import pytest
from dreaming import (
    FREEZE_CODE,
    POOL_TOO_THIN_CODE,
    DreamingError,
    FreezeRequestError,
    PoolFrozenError,
    PoolTooThinError,
)
from dreaming.cycle import validated_iteration_id


class TestTheVocabulary:
    """Two classes, one base, and the relationships between them."""

    def test_both_faces_share_one_base(self):
        """One member, one base — the workspace's per-member rule."""
        assert issubclass(FreezeRequestError, DreamingError)
        assert issubclass(PoolFrozenError, DreamingError)
        assert issubclass(DreamingError, Exception)

    def test_the_two_faces_are_siblings(self):
        """A malformed ask is not the rule being broken, and must not be caught as one.

        Load-bearing for callers: a `except FreezeRequestError` that also
        swallowed a pool-frozen refusal would let a cycle treat *"stop writing,
        the pool is held"* as *"your arguments were wrong"*, which is the
        failure this workspace names for a vocabulary that swallows a
        neighbouring error.
        """
        assert not issubclass(FreezeRequestError, PoolFrozenError)
        assert not issubclass(PoolFrozenError, FreezeRequestError)

    def test_every_refusal_opens_with_the_code(self, freeze):
        """The prefix is what makes a rejection greppable by its own word."""
        with pytest.raises(PoolFrozenError) as refusal:
            freeze.release("freeze-nothing")

        assert str(refusal.value).startswith(FREEZE_CODE)

    def test_the_code_is_feature_270s_word(self):
        """``pool_frozen`` and not the ladder's ``pool_too_thin``."""
        assert FREEZE_CODE == "pool_frozen"
        assert "too_thin" not in FREEZE_CODE

    def test_the_member_carries_the_ladder_floor_as_a_sibling(self):
        """Feature 275's ``pool_too_thin`` is its own class beside feature 270's.

        §12.1's floor — *"below 20 worlds: do not run dreaming"* — is a
        precondition on a run that has not started, which is feature 275's own
        sentence.  It lives in this member as its own code (``pool_too_thin``)
        and its own class (:class:`PoolTooThinError`), a sibling of feature
        270's two classes under the one ``DreamingError`` base — not a third
        face of :class:`PoolFrozenError`.  Pinned because the tempting edit is
        to fold it into feature 270's refusal, where a pool's size is already
        being read: the two sentences have different repairs, so they must be
        two classes a caller can tell apart.
        """
        import dreaming

        assert dreaming.POOL_TOO_THIN_CODE == "pool_too_thin"
        assert "POOL_TOO_THIN_CODE" in dir(dreaming)
        assert issubclass(PoolTooThinError, dreaming.errors.PoolTooThinError)
        assert issubclass(PoolTooThinError, DreamingError)
        # A sibling, not a face of feature 270's refusal — the two have
        # different repairs, so a caller must be able to catch one without
        # catching the other.
        assert not issubclass(PoolTooThinError, PoolFrozenError)
        assert not issubclass(PoolFrozenError, PoolTooThinError)
        assert POOL_TOO_THIN_CODE != FREEZE_CODE


class TestTheMessages:
    """What a refusal says, since the message *is* the repair instruction."""

    def test_a_writer_is_told_what_to_do(self, freeze):
        """A refusal that only said "no" would leave a caller stuck."""
        freeze.open("cycle-1", opened_at=dt_now())

        with pytest.raises(PoolFrozenError) as refusal:
            freeze.guard(
                "DELETE FROM bootstrap_world WHERE world_id = 'world-aaa'"
            )

        message = str(refusal.value)
        assert "Close the iteration" in message
        assert "CycleFreeze.release" in message

    def test_the_guard_refusal_names_the_governing_documents(self, freeze):
        """The rule's provenance is in the refusal, not only in the docstring.

        A caller who has never read §C5 is exactly the caller who meets this
        message, so the message is where the rule's reason has to be legible —
        §C5's first clause and §12.1's *fixed history*.
        """
        freeze.open("cycle-1", opened_at=dt_now())

        with pytest.raises(PoolFrozenError) as refusal:
            freeze.guard(
                "DELETE FROM replay_score WHERE id = 'score-world-aaa-0.0'"
            )

        message = str(refusal.value)
        assert "§C5" in message
        assert "fixed history" in message

    def test_a_second_hold_names_both_cycles(self, freeze):
        """The operator has to be able to tell which cycle to wait for."""
        freeze.open("cycle-1", opened_at=dt_now())

        with pytest.raises(PoolFrozenError) as refusal:
            freeze.open("cycle-2", opened_at=dt_now())

        message = str(refusal.value)
        assert "'cycle-1'" in message
        assert "'cycle-2'" in message
        assert "one dreaming cycle at a time" in message

    def test_a_malformed_ask_says_what_was_wrong_with_it(self):
        """The ask's own fault, named as the ask's own fault."""
        with pytest.raises(FreezeRequestError) as refusal:
            validated_iteration_id(None)

        message = str(refusal.value)
        assert "non-empty string" in message
        assert FREEZE_CODE not in message


def dt_now() -> dt.datetime:
    """An aware instant, fixed so a test's stamps are deterministic.

    Spelled as a function rather than a module constant so a test that reads it
    cannot accidentally share a mutable — there is nothing mutable here, but
    the habit is what keeps a suite from growing one.
    """
    return dt.datetime(2026, 3, 1, 12, 0, 0, tzinfo=dt.UTC)
