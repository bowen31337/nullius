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

    def test_the_member_carries_the_revision_cap_as_its_own_pair(self):
        """Feature 277's two classes take the ask/store split for the cap.

        The revision cap's schedule and record (``dreaming.cap``) refuse in
        their own vocabulary — :class:`CapRequestError` for the ask's own
        facts, :class:`CapRecordError` for the store's — never in feature
        270's, even where the rules are the member's shared ones (the
        iteration-id rule, the URL translation, the stamp format), which are
        translated at the cap's seam rather than re-raised as the freeze's.
        """
        import dreaming

        for cap_class in (dreaming.CapRequestError, dreaming.CapRecordError):
            assert issubclass(cap_class, dreaming.DreamingError)
            # Siblings of all three existing classes — a caller catches a
            # cap's refusal without catching a hold's, a thin pool's, or a
            # malformed freeze ask's, and vice versa.
            for sibling in (
                FreezeRequestError,
                PoolFrozenError,
                PoolTooThinError,
            ):
                assert not issubclass(cap_class, sibling)
                assert not issubclass(sibling, cap_class)

    def test_the_member_carries_the_middle_rung_ceiling_as_its_own_class(self):
        """Feature 276's ceiling is a fifth sentence, and its own class.

        §12.1's ladder has three rungs and this member now carries all three:
        the floor refuses a run below 20 worlds (feature 275's
        ``pool_too_thin``), the schedule *answers* the cap a cycle runs under
        (feature 277's ``dreaming.cap``), and the ceiling *refuses* a sweep
        wider than the thin rung funds (:class:`RevisionCeilingError`).  The
        ceiling's repair — *lower ``M`` to the band's cap, or grow the pool
        until the raise applies* — is neither the floor's (*grow the pool
        before dreaming at all*) nor the cap's (*re-consider the ask*), so a
        caller that must react differently to the three must be able to catch
        them apart.  Pinned because the tempting edit is to fold it into
        feature 275's thin-pool refusal, where a pool's size is already being
        read: this pool *may* dream, just not that widely.
        """
        import dreaming

        ceiling_class = dreaming.RevisionCeilingError
        assert issubclass(ceiling_class, dreaming.DreamingError)
        for sibling in (
            FreezeRequestError,
            PoolFrozenError,
            PoolTooThinError,
            dreaming.CapRequestError,
            dreaming.CapRecordError,
        ):
            assert not issubclass(ceiling_class, sibling)
            assert not issubclass(sibling, ceiling_class)

        # No code word: feature 276's sentence mandates none, so the refusal
        # opens with its subject rather than a token — unlike feature 275's.
        with pytest.raises(ceiling_class) as refusal:
            dreaming.rejects_uncapped_sweep(11, 30)

        message = str(refusal.value)
        assert POOL_TOO_THIN_CODE not in message
        assert FREEZE_CODE not in message

    def test_the_member_carries_the_split_as_its_own_pair(self):
        """Feature 278's two classes take the ask/store split the cap states.

        The pool's 70/30 split (``dreaming.split``) refuses in its own
        vocabulary — :class:`SplitRequestError` for the ask's own facts
        (world ids, rotation, fraction, the URL), :class:`SplitStoreError`
        for a database that holds no pool to split — never in feature 270's,
        even where the rule is the member's shared one (the URL translation,
        translated at the split's seam rather than re-raised as the freeze's),
        and never feature 275's: a pool below the ladder floor is the floor's
        refusal, delegated, in the floor's own word.
        """
        import dreaming

        for split_class in (dreaming.SplitRequestError, dreaming.SplitStoreError):
            assert issubclass(split_class, dreaming.DreamingError)
            # Siblings of every existing class — a caller catches a split's
            # refusal without catching a hold's, a thin pool's, a cap's, a
            # ceiling's or a malformed freeze ask's, and vice versa.
            for sibling in (
                FreezeRequestError,
                PoolFrozenError,
                PoolTooThinError,
                dreaming.CapRequestError,
                dreaming.CapRecordError,
                dreaming.RevisionCeilingError,
            ):
                assert not issubclass(split_class, sibling)
                assert not issubclass(sibling, split_class)

        # No code word: feature 278's sentence mandates none, so the refusal
        # opens with its subject rather than a token — and the one refusal
        # this vocabulary never mints is the thin pool's.
        with pytest.raises(dreaming.SplitRequestError) as refusal:
            dreaming.split_pool("world-aaa")

        message = str(refusal.value)
        assert POOL_TOO_THIN_CODE not in message
        assert FREEZE_CODE not in message

    def test_the_member_carries_the_comparison_as_its_own_pair(self):
        """Feature 281's two classes split by *what is wrong*, not by where it was noticed.

        §11.0's sentence replaces one statistic with another, so it has two
        ways to be met and two repairs:

        * :class:`ProportionComparisonError` — the **question** is the wrong
          one.  The proportion test is power-poor at this pool's scale and the
          paired continuous statistic is not.  Repair: *ask for the paired
          statistic*;
        * :class:`PairedComparisonError` — the question is right and the
          **evidence** will not pair.  A world carries one arm and not the
          other, or too few worlds carry both.  Repair: *compare the arms over
          the worlds that carry both*.

        Neither is feature 275's ``pool_too_thin``, and that is the line worth
        pinning hardest: the floor's repair is *grow the pool*, and a caller
        that caught them together would go looking for more worlds when the
        problem was its statistic — or, in the other direction, be told to
        switch statistics while holding 40 worlds, which funds neither test.
        Pinned because the tempting edit is to reach for the class that already
        exists and whose name is about a pool being the wrong size.
        """
        import dreaming

        for paired_class in (
            dreaming.ProportionComparisonError,
            dreaming.PairedComparisonError,
        ):
            assert issubclass(paired_class, dreaming.DreamingError)
            # Siblings of every existing class — a caller catches a
            # comparison's refusal without catching a hold's, a thin pool's, a
            # cap's, a ceiling's, a malformed freeze ask's or a split's.
            for sibling in (
                FreezeRequestError,
                PoolFrozenError,
                PoolTooThinError,
                dreaming.CapRequestError,
                dreaming.CapRecordError,
                dreaming.RevisionCeilingError,
                dreaming.SplitRequestError,
                dreaming.SplitStoreError,
            ):
                assert not issubclass(paired_class, sibling)
                assert not issubclass(sibling, paired_class)

        # A code word each, unlike features 276/278's: these refusals are the
        # two faces of one document section, so an operator grepping a log
        # needs to land on the right face.
        with pytest.raises(dreaming.ProportionComparisonError) as proportion:
            dreaming.rejects_proportion_comparison(
                0.30,
                arm_size=100,
                rate_delta=0.09,
                delta=0.3,
                spread=0.8,
            )
        with pytest.raises(dreaming.PairedComparisonError) as paired:
            dreaming.paired_ir_difference({"w-a": 0.5}, {"w-a": 0.1})

        assert str(proportion.value).startswith(dreaming.PROPORTION_CODE)
        assert str(paired.value).startswith(dreaming.PAIRED_CODE)
        assert dreaming.PROPORTION_CODE != dreaming.PAIRED_CODE

        # ...and neither refusal ever mints the vocabulary this member already
        # has for a pool that is the wrong size.
        for refusal in (proportion.value, paired.value):
            assert POOL_TOO_THIN_CODE not in str(refusal)
            assert FREEZE_CODE not in str(refusal)


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
