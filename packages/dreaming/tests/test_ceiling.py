"""Feature 276's claim, stated as tests: the middle rung's ceiling.

app_spec.xml, "Dreaming Loop & Meta-Selection", feature 276: *System rejects a
revision count above 10 while the pool holds between 20 and 50 worlds, so the
selection bar stays low.*  docs/alpha-engine-prd.md §12.1 states the rule as the
middle row of its ladder — *"20–50: dreaming with ``M`` capped at 8–10 so the
selection bar stays low"* — and this suite pins the judgment that enforces it.

So the claims worth pinning are these, and they are what the classes below are
arranged around:

* the band's ceiling is exact — ``10`` runs, ``11`` does not, and the band's
  edges are ``20`` and ``50`` with one rung on either side;
* the ceiling applies to **one** rung: above the band there is no ceiling at
  all, and below it the refusal is feature 275's, delegated;
* the number a cycle is *entitled to* and the number it is *refused above* are
  one constant — the default judgment never refuses what
  :func:`dreaming.cap.revision_cap` answers, at any pool size, by construction;
* the judgment is over counts the caller already has — it never opens a
  database, and a malformed count or rung is refused rather than answered;
* the refusal is a **sibling** of the member's other four classes — a sweep too
  wide for the thin rung is not a thin pool, not a malformed ask, not a held
  pool and not a malformed cap ask, and a caller must be able to catch one
  without catching the others.
"""

from __future__ import annotations

import pytest
from dreaming import (
    CAPPED_SWEEP_CAP,
    FULL_DREAMING_CAP,
    FULL_DREAMING_WORLDS,
    DreamingError,
    FreezeRequestError,
    PoolFrozenError,
    PoolTooThinError,
    RevisionCeilingError,
    rejects_thin_pool,
    rejects_uncapped_sweep,
    revision_cap,
)
from dreaming.ceiling import _validated_revision_count
from dreaming.ladder import LADDER_FLOOR_WORLDS, POOL_TOO_THIN_CODE


class TestTheCeiling:
    """The refusal itself: the band's cap, at the band's edges."""

    def test_a_sweep_above_the_band_cap_is_refused(self):
        """Feature 276's own sentence: above 10, while the pool is in the band."""
        for pool in (20, 21, 30, 49):
            for count in (11, 12, 40, 100):
                with pytest.raises(RevisionCeilingError):
                    rejects_uncapped_sweep(count, pool)

    def test_a_sweep_at_the_band_cap_is_admitted(self):
        """The edge is inclusive on the admitted side: 10 runs, 11 does not.

        §12.1's band is *"``M`` capped at 8–10"* and feature 276's sentence
        fixes the ceiling at its top — so the cap itself is admitted and
        exactly one more revision is refused.
        """
        for pool in (20, 30, 49):
            rejects_uncapped_sweep(CAPPED_SWEEP_CAP, pool)  # admitted
            with pytest.raises(RevisionCeilingError):
                rejects_uncapped_sweep(CAPPED_SWEEP_CAP + 1, pool)

    def test_the_bands_lower_edge_is_the_floor(self):
        """20 is the band's first pool; below it the ladder speaks, not this.

        The floor is a *lower* edge and itself admits: a pool of exactly 20 may
        dream, under the ceiling — which is the whole of feature 276's *"while
        the pool holds between 20 and 50 worlds"*.
        """
        rejects_uncapped_sweep(CAPPED_SWEEP_CAP, LADDER_FLOOR_WORLDS)  # admitted
        with pytest.raises(RevisionCeilingError):
            rejects_uncapped_sweep(CAPPED_SWEEP_CAP + 1, LADDER_FLOOR_WORLDS)

    def test_the_bands_upper_edge_is_the_full_dreaming_raise(self):
        """49 is capped, 50 is not — feature 277's boundary, one rung up.

        A pool of 49 refuses the same 40 revisions a pool of 50 admits, which
        is the whole content of the ladder's two middle-and-top rungs.
        """
        for pool in (49, 48, 20):
            with pytest.raises(RevisionCeilingError):
                rejects_uncapped_sweep(FULL_DREAMING_CAP, pool)

        for pool in (50, 51, 100, 1000):
            rejects_uncapped_sweep(FULL_DREAMING_CAP, pool)  # admitted

    def test_there_is_no_ceiling_above_the_band(self):
        """The ceiling is the *middle* rung's rule and does not follow a cycle up.

        Refusing a wide sweep here would leave the top rung refusing the very
        figure §12.1's own bar calculation is written at — *"At ``M = 40`` (bar
        ≈ 2.72) … this gives ``n > 53`` worlds"* — so above the band this
        judgment admits whatever feature 277's schedule answers.
        """
        for pool in (50, 60, 500):
            for count in (1, 10, 40, 41, 1000):
                rejects_uncapped_sweep(count, pool)  # no refusal, ever

    def test_the_ceiling_is_feature_277s_figure_consumed_not_respelled(self):
        """One ladder, one spelling per rung: the band's cap is the schedule's.

        The 10 a cycle is *entitled to* on the thin rung (``revision_cap``)
        and the 10 it is *refused above* (this judgment's default ceiling) are
        the same object, so the two cannot drift apart.
        """
        assert CAPPED_SWEEP_CAP == 10
        assert FULL_DREAMING_WORLDS == 50
        assert LADDER_FLOOR_WORLDS == 20
        # The band's cap is literally the module constant feature 277 states.
        import dreaming.cap as cap_module
        import dreaming.ceiling as ceiling_module

        assert ceiling_module.CAPPED_SWEEP_CAP is cap_module.CAPPED_SWEEP_CAP
        assert (
            ceiling_module.FULL_DREAMING_WORLDS is cap_module.FULL_DREAMING_WORLDS
        )

    def test_the_default_judgment_never_refuses_what_the_schedule_answers(self):
        """The agreement law, over every rung — the reason the 10 is consumed.

        For every pool size from the floor to well past the raise,
        ``revision_cap`` answers a figure this judgment admits.  If the two
        features ever respelled their own 10, this is the test that would fail
        at the moment they disagreed.
        """
        for pool in range(LADDER_FLOOR_WORLDS, 200):
            rejects_uncapped_sweep(revision_cap(pool), pool)  # admitted

    def test_the_default_judgment_refuses_exactly_one_more_than_the_schedule(self):
        """The other half of the agreement: the ceiling is where the cap plus one lands.

        Below the band the schedule's answer plus one is refused; above it
        there is no such edge, because the raise has fired.
        """
        for pool in range(LADDER_FLOOR_WORLDS, FULL_DREAMING_WORLDS):
            with pytest.raises(RevisionCeilingError):
                rejects_uncapped_sweep(revision_cap(pool) + 1, pool)

        for pool in (50, 51, 120):
            rejects_uncapped_sweep(revision_cap(pool) + 1, pool)  # admitted

    def test_zero_revisions_is_admitted(self):
        """*Do not run any revision* is the caller's own business.

        The ceiling bounds a sweep that happens; it never requires one, so a
        zero-revision sweep is admitted on every rung rather than refused as a
        malformed count.
        """
        for pool in (20, 30, 49, 50, 200):
            rejects_uncapped_sweep(0, pool)  # admitted

    def test_the_refusal_names_both_figures_and_the_band(self):
        """A refusal that only said "no" would leave a caller stuck.

        The message states the figure it refused, the ceiling it was measured
        against, the pool's size, the band's two edges, §12.1 and Appendix B's
        bar — so a caller who has never read the section meets the rule's
        reason exactly where the rule stops them.
        """
        with pytest.raises(RevisionCeilingError) as refusal:
            rejects_uncapped_sweep(25, 30)

        message = str(refusal.value)
        assert "25" in message and "10" in message and "30" in message
        assert "20" in message and "50" in message
        assert "§12.1" in message
        assert "sqrt(2 ln M)" in message
        assert "n > 53" in message

    def test_the_refusal_states_the_repair(self):
        """The message *is* the repair instruction, as every refusal in this member is."""
        with pytest.raises(RevisionCeilingError) as refusal:
            rejects_uncapped_sweep(40, 30)

        message = str(refusal.value)
        assert "Lower M to the band's cap" in message
        assert "grow the pool" in message


class TestTheCeilingParameters:
    """The band's edges and its cap are the ladder's facts, and settable."""

    def test_the_ceiling_is_a_parameter(self):
        """A deployment sizing its own band ceiling is judged against it.

        The default is feature 277's figure, but the ceiling is a keyword for
        the same reason the floor is: the ladder's numbers are §12.1's defaults
        rather than the only coherent ones.
        """
        rejects_uncapped_sweep(12, 30, ceiling=12)  # admitted at its own edge
        with pytest.raises(RevisionCeilingError):
            rejects_uncapped_sweep(13, 30, ceiling=12)

    def test_a_zero_ceiling_refuses_every_nonzero_sweep_on_the_band(self):
        """A coherent deployment choice: no sweep at all on the thin rung.

        That is the floor's own advice (*fixed exploration*) applied one rung
        up, and it is admitted rather than refused as a malformed ceiling.
        """
        rejects_uncapped_sweep(0, 30, ceiling=0)  # admitted
        with pytest.raises(RevisionCeilingError):
            rejects_uncapped_sweep(1, 30, ceiling=0)

    def test_the_upper_edge_is_a_parameter(self):
        """A deployment that raises the band's edge is judged against it.

        A band that runs to 60 keeps the ceiling shut on 50–59 and lets a cycle
        run feature 277's raised cap at 60 — the raise's edge is the ladder's
        fact, not this module's.
        """
        with pytest.raises(RevisionCeilingError):
            rejects_uncapped_sweep(FULL_DREAMING_CAP, 50, full_dreaming=60)

        rejects_uncapped_sweep(FULL_DREAMING_CAP, 60, full_dreaming=60)  # admitted

    def test_the_floor_passes_through_to_the_ladder(self):
        """One spelling of the band's lower edge: the floor is the floor's own keyword.

        Raised to 30, the judgment refuses a pool of 29 in the ladder's own
        word and admits 30 under the ceiling.
        """
        with pytest.raises(PoolTooThinError):
            rejects_uncapped_sweep(5, 29, floor=30)

        rejects_uncapped_sweep(5, 30, floor=30)  # admitted
        with pytest.raises(RevisionCeilingError):
            rejects_uncapped_sweep(11, 30, floor=30)

    def test_the_judgment_is_pure_over_counts(self):
        """A verdict is not a count: ints in, nothing out, no store attached.

        Verified by denial as well as by signature — the module imports nothing
        that could open a database, which is what keeps this a judgment rather
        than a query.
        """
        rejects_uncapped_sweep(10, 30)  # admitted
        with pytest.raises(RevisionCeilingError):
            rejects_uncapped_sweep(11, 30)
        with pytest.raises(PoolTooThinError):
            rejects_uncapped_sweep(1, 3)

        import dreaming.ceiling as ceiling_module

        source = ceiling_module.__doc__ or ""
        assert "opens no database" in source or "never opens a database" in source
        for forbidden in ("sqlite3", "sqlite_path", "connect"):
            assert forbidden not in dir(ceiling_module)


class TestTheCeilingInputs:
    """A malformed count or rung is refused, not answered — the ask's fault."""

    def test_a_bool_revision_count_is_refused_where_a_count_belongs(self):
        """``True`` is ``1`` in Python, so a flag where a count belongs would
        name a sweep of one revision — refused as a malformed ask."""
        with pytest.raises(RevisionCeilingError):
            rejects_uncapped_sweep(True, 30)

    def test_a_float_revision_count_is_refused(self):
        with pytest.raises(RevisionCeilingError):
            rejects_uncapped_sweep(10.5, 30)

    def test_a_non_numeric_revision_count_is_refused(self):
        with pytest.raises(RevisionCeilingError):
            rejects_uncapped_sweep("ten", 30)

    def test_a_negative_revision_count_is_refused(self):
        with pytest.raises(RevisionCeilingError):
            rejects_uncapped_sweep(-1, 30)

    def test_a_malformed_world_count_is_refused_in_this_modules_vocabulary(self):
        """A pool size that is not a count is a *malformed ask*, not a thin pool.

        The two repairs are different — re-send it against grow the pool — so a
        value that cannot name a pool is refused as the ask's own fault rather
        than answered with the ladder's ``pool_too_thin`` word.
        """
        for bad in (True, 29.5, "thirty", None):
            with pytest.raises(RevisionCeilingError) as refusal:
                rejects_uncapped_sweep(5, bad)

            assert not isinstance(refusal.value, PoolTooThinError)

    def test_a_negative_world_count_is_refused(self):
        with pytest.raises(RevisionCeilingError):
            rejects_uncapped_sweep(5, -1)

    def test_a_malformed_floor_is_refused_in_the_ladders_vocabulary(self):
        """The floor is feature 275's fact, so its malformed shape is refused
        by the ladder's own validation, in the ladder's own class."""
        with pytest.raises(PoolTooThinError):
            rejects_uncapped_sweep(5, 30, floor="20")

    def test_a_malformed_boundary_is_refused(self):
        with pytest.raises(RevisionCeilingError):
            rejects_uncapped_sweep(5, 30, full_dreaming="50")

    def test_a_bool_boundary_is_refused(self):
        with pytest.raises(RevisionCeilingError):
            rejects_uncapped_sweep(5, 30, full_dreaming=True)

    def test_a_negative_boundary_is_refused(self):
        with pytest.raises(RevisionCeilingError):
            rejects_uncapped_sweep(5, 30, full_dreaming=-5)

    def test_a_malformed_ceiling_is_refused(self):
        for bad in (True, 10.5, "ten", -1):
            with pytest.raises(RevisionCeilingError):
                rejects_uncapped_sweep(5, 30, ceiling=bad)

    def test_a_boundary_below_the_floor_erases_the_band(self):
        """An edge under the floor leaves no band between them, and every
        admissible pool would escape the ceiling §12.1 keeps shut — refused,
        naming both edges."""
        with pytest.raises(RevisionCeilingError) as refusal:
            rejects_uncapped_sweep(40, 25, floor=30, full_dreaming=10)

        message = str(refusal.value)
        assert "10" in message and "30" in message

    def test_a_boundary_at_the_floor_is_a_degenerate_but_coherent_band(self):
        """Floor and edge equal means every admissible pool is above the band
        — no band is erased, and the ceiling simply never applies."""
        rejects_uncapped_sweep(1000, 20, floor=20, full_dreaming=20)  # admitted

    def test_the_revision_count_validation_is_the_ceiling_s_own(self):
        """The count rule is spelled here so a caller meets *this* feature's class.

        A caller of the ceiling that handed in a malformed count must not meet
        feature 277's request class for a judgment feature 277 never made — the
        seam discipline the workspace states for error vocabularies, applied
        inside the member.
        """
        with pytest.raises(RevisionCeilingError) as refusal:
            _validated_revision_count(None)

        assert not isinstance(refusal.value, FreezeRequestError)


class TestTheFloorIsStillTheFloors:
    """Below the band, the refusal is feature 275's — delegated, in its own word."""

    def test_a_thin_pool_is_refused_in_the_ladders_own_word(self):
        """A pool that may not dream at all needs no cap on its sweep.

        The refusal is the one §12.1's floor already mints — it opens with
        ``pool_too_thin`` and names §12.1 — rather than a second spelling of it
        from this rung, which is what ``depends_on="275"`` means in code.
        """
        for pool in (0, 5, 19):
            with pytest.raises(PoolTooThinError) as refusal:
                rejects_uncapped_sweep(5, pool)

            assert str(refusal.value).startswith(POOL_TOO_THIN_CODE)
            assert "§12.1" in str(refusal.value)

    def test_the_thin_refusal_wins_over_the_ceiling(self):
        """Order matters: a thin pool with a wide sweep meets the floor's word.

        Both facts are true of the call below — the pool is thin *and* the
        sweep is wide — and the floor's refusal is the one that names the
        binding constraint, because no cap can make a run that may not begin
        admissible.
        """
        with pytest.raises(PoolTooThinError):
            rejects_uncapped_sweep(1000, 5)

    def test_the_delegation_is_to_the_floors_own_function(self):
        """The ceiling does not respell the thin judgment — it calls it."""
        import dreaming.ceiling as ceiling_module

        assert ceiling_module.rejects_thin_pool is rejects_thin_pool


class TestTheVocabulary:
    """The ceiling's class: a sibling under the base, borrowing nothing."""

    def test_the_class_shares_the_members_base(self):
        assert issubclass(RevisionCeilingError, DreamingError)
        assert issubclass(DreamingError, Exception)

    def test_the_class_borrows_none_of_the_members_other_four(self):
        """A caller must be able to catch a ceiling refusal without catching a
        thin pool's, a hold's, a malformed freeze ask's or a malformed cap
        ask's — and vice versa, since each names a different repair."""
        for sibling in (
            FreezeRequestError,
            PoolFrozenError,
            PoolTooThinError,
        ):
            assert not issubclass(RevisionCeilingError, sibling)
            assert not issubclass(sibling, RevisionCeilingError)

    def test_the_class_is_a_sibling_of_both_cap_classes(self):
        """Feature 277's pair stays beside this one, on both sides.

        A well-formed count of 40 is refused here and *answered* one rung up, so
        nothing about it is a malformed ask — the two vocabularies must not
        swallow one another.
        """
        import dreaming

        for cap_class in (dreaming.CapRequestError, dreaming.CapRecordError):
            assert not issubclass(RevisionCeilingError, cap_class)
            assert not issubclass(cap_class, RevisionCeilingError)

    def test_the_class_carries_no_code_word(self):
        """Feature 276's sentence mandates no code, and the refusal opens with
        its subject instead — unlike feature 275's ``pool_too_thin``."""
        with pytest.raises(RevisionCeilingError) as refusal:
            rejects_uncapped_sweep(11, 30)

        message = str(refusal.value)
        assert POOL_TOO_THIN_CODE not in message
        assert "pool_frozen" not in message

    def test_the_thin_refusal_a_caller_meets_is_still_the_ladders(self):
        """The one thin-pool refusal this member mints is feature 275's,
        delegated — so ``PoolTooThinError`` is not re-spelled at this rung."""
        import dreaming

        assert dreaming.PoolTooThinError is PoolTooThinError
        with pytest.raises(PoolTooThinError):
            dreaming.rejects_uncapped_sweep(5, 5)

    def test_the_band_edges_are_spelled_nowhere_in_this_module(self):
        """A ladder is one thing spelled once: this module owns no ladder figure.

        The 20 comes from feature 275's :data:`LADDER_FLOOR_WORLDS`, the 50 and
        the 10 from feature 277's :data:`FULL_DREAMING_WORLDS` and
        :data:`CAPPED_SWEEP_CAP` — imported, not restated — so there is no
        third spelling of any rung that could drift.
        """
        import inspect

        import dreaming.ceiling as ceiling_module

        source = inspect.getsource(ceiling_module)
        body = source.split('"""', 2)[2]  # the module docstring is not code
        for figure in ("20", "50"):
            assert f"= {figure}\n" not in body, figure
