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
from types import SimpleNamespace

import pytest
from dreaming import (
    FREEZE_CODE,
    POOL_TOO_THIN_CODE,
    DreamingError,
    FreezeRequestError,
    PoolFrozenError,
    PoolTooThinError,
    RevisionError,
    RevisionRequestError,
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

    def test_the_member_carries_the_revision_sweep_as_its_own_pair(self):
        """Feature 271's two classes take the ask/verdict split the cap states.

        The M-revision sweep (``dreaming.reviser``) refuses in its own
        vocabulary — :class:`RevisionRequestError` for the **ask's** own facts
        (an incumbent source that is not non-empty text, a count that is not a
        genuine positive integer, a seed that is neither text nor int, a parent
        version that is not None or non-empty text), :class:`RevisionError` for
        the **production** verdict (a revised source that does not parse, or a
        shortfall of distinct candidates after deduplication by ``code_hash``)
        — never feature 270's, and never the cap's or the ceiling's, even
        though all three are about the sweep's size: the ask's fault is *fix
        the call*, the shortfall's repair is *grow the policy's authored
        constants or shrink M*, and a count of 40 is a well-formed ask one rung
        up.  A member that folded the shortfall into the malformed ask would
        make a caller that must react differently to *your arguments were
        wrong* and *this policy cannot fund that many revisions* catch one
        class and re-inspect something it cannot tell apart.
        """
        import dreaming

        for reviser_class in (
            dreaming.RevisionRequestError,
            dreaming.RevisionError,
        ):
            assert issubclass(reviser_class, dreaming.DreamingError)
            # Siblings of every existing class — a caller catches a revision
            # sweep's refusal without catching a hold's, a thin pool's, a
            # cap's, a ceiling's, a split's, a comparison's, a transfer's, a
            # rotation's or a bar's, and vice versa.
            for sibling in (
                FreezeRequestError,
                PoolFrozenError,
                PoolTooThinError,
                dreaming.CapRequestError,
                dreaming.CapRecordError,
                dreaming.RevisionCeilingError,
                dreaming.SplitRequestError,
                dreaming.SplitStoreError,
                dreaming.ProportionComparisonError,
                dreaming.PairedComparisonError,
                dreaming.TransferRequestError,
                dreaming.TransferStoreError,
                dreaming.HoldoutRequestError,
                dreaming.HoldoutRecordError,
                dreaming.BarRequestError,
                dreaming.BarRecordError,
                dreaming.SelectionBarError,
            ):
                assert not issubclass(reviser_class, sibling)
                assert not issubclass(sibling, reviser_class)

        # The ask and the verdict are two classes, not one: a malformed ask is
        # refused before anything is produced, so a well-formed call can still
        # refuse with the verdict.
        assert not issubclass(RevisionRequestError, RevisionError)
        assert not issubclass(RevisionError, RevisionRequestError)

        # No code word, like features 276/278's: feature 271's verb is
        # *produces* and mandates none, so each refusal opens with its subject
        # — the source or count that was wrong, or the shortfall — and neither
        # ever mints the thin pool's or the freeze's word.
        with pytest.raises(RevisionRequestError) as blank_ask:
            dreaming.revise_policy("", 3)
        with pytest.raises(RevisionError) as shortfall:
            dreaming.revise_policy("def p(beta):\n    return beta", 3)

        for refusal in (blank_ask.value, shortfall.value):
            assert POOL_TOO_THIN_CODE not in str(refusal)
            assert FREEZE_CODE not in str(refusal)
        # The ask names what was wrong with the request; the verdict names the
        # shortfall — two subjects, neither a greppable token.
        assert "policy source" in str(blank_ask.value)
        assert "distinct candidate" in str(shortfall.value)

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

    def test_the_member_carries_the_transfer_as_its_own_pair(self):
        """Feature 282's two classes take the ask/store split the cap states.

        The family-shaped holdout (``dreaming.transfer``) refuses in its own
        vocabulary — :class:`TransferRequestError` for the ask's own facts (a
        census that is not a mapping of non-empty ids to non-empty roots, a
        root the pool does not carry, one policy on both arms, no database
        named), :class:`TransferStoreError` for a store that holds no pool or
        no honest census of one — never feature 270's, and never the paired
        comparison's: a world that will not pair is feature 281's fact,
        refused by its own law in its own word, because the delta on a
        held-out theme *is* a paired comparison over that theme's worlds.
        Pinned as a sibling of every existing class so a caller catches a
        transfer's refusal without catching anyone else's.
        """
        import dreaming

        for transfer_class in (
            dreaming.TransferRequestError,
            dreaming.TransferStoreError,
        ):
            assert issubclass(transfer_class, dreaming.DreamingError)
            for sibling in (
                FreezeRequestError,
                PoolFrozenError,
                PoolTooThinError,
                dreaming.CapRequestError,
                dreaming.CapRecordError,
                dreaming.RevisionCeilingError,
                dreaming.SplitRequestError,
                dreaming.SplitStoreError,
                dreaming.ProportionComparisonError,
                dreaming.PairedComparisonError,
            ):
                assert not issubclass(transfer_class, sibling)
                assert not issubclass(sibling, transfer_class)

        # No code word, like features 276/278's and unlike 281's pair:
        # feature 282's verb is "computes" and mandates none, so the refusal
        # opens with its subject — and never mints the thin pool's or the
        # freeze's word, both of which are delegated where they apply.
        with pytest.raises(dreaming.TransferRequestError) as refusal:
            dreaming.leave_one_family_out("hpo", theme="hpo")

        message = str(refusal.value)
        assert POOL_TOO_THIN_CODE not in message
        assert FREEZE_CODE not in message

    def test_the_member_carries_the_rotation_as_its_own_pair(self):
        """Feature 279's two classes take the ask/store split the cap states.

        The holdout's per-cycle rotation and its record
        (``dreaming.rotation``) refuse in their own vocabulary —
        :class:`HoldoutRequestError` for the ask's own facts (an iteration id
        that is not non-empty text, a train fraction outside ``(0, 1)``, a
        naive instant, no database named), :class:`HoldoutRecordError` for a
        store that holds no pool or a row that will not read back — never
        feature 270's and never the split's, even where the rules are the
        member's shared ones (the id rule and the URL translation spelled in
        ``dreaming.cycle``, the fraction rule in ``dreaming.split``, both
        *translated* at the rotation's seam rather than re-raised), and
        never feature 275's: a pool below the ladder floor is the floor's
        refusal, delegated through the split's judgment in the floor's own
        word, because a pool too thin to dream on has no halves to rotate.
        """
        import dreaming

        for rotation_class in (
            dreaming.HoldoutRequestError,
            dreaming.HoldoutRecordError,
        ):
            assert issubclass(rotation_class, dreaming.DreamingError)
            # Siblings of every existing class — a caller catches a
            # rotation's refusal without catching a hold's, a thin pool's,
            # a cap's, a ceiling's, a split's, a comparison's, a transfer's
            # or a bar's, and vice versa.
            for sibling in (
                FreezeRequestError,
                PoolFrozenError,
                PoolTooThinError,
                dreaming.CapRequestError,
                dreaming.CapRecordError,
                dreaming.RevisionCeilingError,
                dreaming.SplitRequestError,
                dreaming.SplitStoreError,
                dreaming.ProportionComparisonError,
                dreaming.PairedComparisonError,
                dreaming.TransferRequestError,
                dreaming.TransferStoreError,
                dreaming.BarRequestError,
                dreaming.BarRecordError,
                dreaming.SelectionBarError,
            ):
                assert not issubclass(rotation_class, sibling)
                assert not issubclass(sibling, rotation_class)

        # No code word, like features 276/278/282's and unlike 281's pair:
        # feature 279's sentence mandates none, so the refusal opens with
        # its subject — and never mints the thin pool's or the freeze's
        # word, both of which are delegated where they apply.
        with pytest.raises(dreaming.HoldoutRequestError) as refusal:
            dreaming.cycle_rotation(None)

        message = str(refusal.value)
        assert POOL_TOO_THIN_CODE not in message
        assert FREEZE_CODE not in message

    def test_the_member_carries_the_selection_bar_as_its_own_three(self):
        """Feature 280's three classes split by repair, and the third is the verdict.

        §12.1's bar refuses a *winner*, so the feature has one more face than
        the ask/store pairs the cap, the split, the comparison and the
        transfer state: :class:`BarRequestError` (re-send the figures),
        :class:`BarRecordError` (record the cycle's cap, or point at the
        store that holds it) and :class:`SelectionBarError` — the figures
        were honest, the record was there, and the answer is *no*: *keep the
        incumbent*, which the paper's ``V^{m★} ≥ V^0`` holds by
        construction.  A caller that caught the verdict as either
        developer face would re-send the same honest figures forever, or
        re-point at a database that was fine.  The one code is on the
        verdict alone — ``advantage_below_bar``, the word an operator
        greps a deployment log for — while the ask and store faces open
        with their subjects, the stance :class:`CapRequestError` states.
        """
        import dreaming

        for bar_class in (
            dreaming.BarRequestError,
            dreaming.BarRecordError,
            dreaming.SelectionBarError,
        ):
            assert issubclass(bar_class, dreaming.DreamingError)
            for sibling in (
                FreezeRequestError,
                PoolFrozenError,
                PoolTooThinError,
                dreaming.CapRequestError,
                dreaming.CapRecordError,
                dreaming.RevisionCeilingError,
                dreaming.SplitRequestError,
                dreaming.SplitStoreError,
                dreaming.ProportionComparisonError,
                dreaming.PairedComparisonError,
                dreaming.TransferRequestError,
                dreaming.TransferStoreError,
            ):
                assert not issubclass(bar_class, sibling)
                assert not issubclass(sibling, bar_class)

        # The code is on the verdict alone, and the cap's refusals are
        # translated at the seam — the caller that asked for a bar never
        # meets the cap's word for an act that recorded nothing.
        assert dreaming.SELECTION_BAR_CODE == "advantage_below_bar"
        with pytest.raises(dreaming.SelectionBarError) as verdict:
            dreaming.rejects_unbarred_winner(0.25, m=40, spread=0.8, worlds=53)
        with pytest.raises(dreaming.BarRequestError) as ask:
            dreaming.rejects_unbarred_winner(0.3, m=0, spread=0.8, worlds=53)

        assert str(verdict.value).startswith(dreaming.SELECTION_BAR_CODE)
        assert not str(ask.value).startswith(dreaming.SELECTION_BAR_CODE)
        for message in (str(verdict.value), str(ask.value)):
            assert POOL_TOO_THIN_CODE not in message
            assert FREEZE_CODE not in message

    def test_the_member_carries_the_incumbent_inclusion_as_its_own_one(self):
        """Feature 273 has one face, not a pair, and that is the sentence's shape.

        *"System includes the incumbent policy in the candidate set, which
        returns a selected policy never worse on the fixed history."*  The
        sentence has no store act — *includes* reads nothing and writes nothing
        — and its second clause is a theorem about feature 274's argmax rather
        than a judgment some module makes, so this feature mints exactly one
        class, :class:`IncumbentRequestError`, the **ask** face, where the cap,
        the split, the transfer, the rotation and the selection each mint a
        pair.  A member that split it in two would be inventing a store face
        for a store the sentence never mentions.

        It is its own class rather than a face of feature 271's
        :class:`RevisionRequestError`, though the rule that a candidate's
        source and identity are non-empty text is the member's one rule: the
        *vocabulary* splits by who was asked, so a caller that included an
        incumbent must not meet the reviser's word for an act that revised
        nothing.  It is not feature 276's
        :class:`RevisionCeilingError` either — this feature refuses no count —
        and never feature 275's or feature 270's word.
        """
        import dreaming

        assert issubclass(dreaming.IncumbentRequestError, dreaming.DreamingError)
        for sibling in (
            FreezeRequestError,
            PoolFrozenError,
            PoolTooThinError,
            dreaming.CapRequestError,
            dreaming.CapRecordError,
            dreaming.RevisionCeilingError,
            dreaming.RevisionRequestError,
            dreaming.RevisionError,
            dreaming.SplitRequestError,
            dreaming.SplitStoreError,
            dreaming.ProportionComparisonError,
            dreaming.PairedComparisonError,
            dreaming.TransferRequestError,
            dreaming.TransferStoreError,
            dreaming.HoldoutRequestError,
            dreaming.HoldoutRecordError,
            dreaming.BarRequestError,
            dreaming.BarRecordError,
            dreaming.SelectionBarError,
            dreaming.SelectionRequestError,
            dreaming.SelectionStoreError,
        ):
            assert not issubclass(dreaming.IncumbentRequestError, sibling)
            assert not issubclass(sibling, dreaming.IncumbentRequestError)

        # No code word, like features 271/276/278/279': feature 273's verb is
        # *includes* and mandates none, so each refusal opens with its subject —
        # the source that was wrong, or the candidate the incumbent collided
        # with — and the message never mints the thin pool's, the freeze's, the
        # sweep's or the selector's word.
        with pytest.raises(dreaming.IncumbentRequestError) as ask:
            dreaming.incumbent_candidate("")
        with pytest.raises(dreaming.IncumbentRequestError) as malformed_set:
            dreaming.include_incumbent("a policy source", "a policy source")

        for refusal in (ask.value, malformed_set.value):
            message = str(refusal)
            assert POOL_TOO_THIN_CODE not in message
            assert FREEZE_CODE not in message
            assert "sweep_malformed" not in message
            assert "selection_malformed" not in message
        assert "policy source" in str(ask.value)
        assert "sequence" in str(malformed_set.value)

        # The collision the sentence's verb turns on: *includes* is not *may
        # include*, and it is refused in this feature's own class rather than
        # silently widening a set that already carries the policy in force.
        entry = dreaming.incumbent_candidate("a policy source")
        with pytest.raises(dreaming.IncumbentRequestError) as collision:
            dreaming.include_incumbent(
                [SimpleNamespace(module_id=entry.module_id, code_hash="f" * 64)],
                "a policy source",
            )

        assert entry.module_id in str(collision.value)


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
