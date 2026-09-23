"""Feature 275's claim, stated as tests: the ladder floor refusal.

app_spec.xml, "Dreaming Loop & Meta-Selection", feature 275: *System rejects a
dreaming run when the pool holds fewer than 20 worlds, which returns a
``pool_too_thin`` error message.*  docs/alpha-engine-prd.md §12.1 states the
rule as a precondition on a run that has not started — *"below 20 worlds: do
not run dreaming; fixed exploration; accumulate history"* — and this suite pins
the judgment that enforces it.

So the claims worth pinning are these, and they are what the classes below are
arranged around:

* a pool below the floor is refused, and the refusal carries the code
  ``pool_too_thin`` and names both the figure and the floor;
* the floor is a *parameter* — a deployment that sets its own floor is judged
  against it, and the §12.1 default is 20;
* the judgment is over a count the caller already has — it never counts the
  pool itself, so a malformed figure or floor is refused rather than answered;
* the refusal is a **sibling** of feature 270's, not a third face of it — a
  thin pool is not a held pool, and a caller must be able to catch one without
  catching the other.
"""

from __future__ import annotations

import pytest
from dreaming import (
    POOL_TOO_THIN_CODE,
    DreamingError,
    PoolFrozenError,
    PoolTooThinError,
    rejects_thin_pool,
    validated_floor,
)
from dreaming.ladder import LADDER_FLOOR_WORLDS


class TestTheFloor:
    """The refusal itself: a pool below the floor is refused, and by how much."""

    def test_a_pool_below_the_floor_is_refused(self):
        """§12.1's floor: below 20 worlds, do not run dreaming."""
        for worlds in (0, 5, 19):
            with pytest.raises(PoolTooThinError):
                rejects_thin_pool(worlds)

    def test_a_pool_at_or_above_the_floor_is_admitted(self):
        """Meeting the floor is enough — there is no upper edge to a floor.

        The floor is a power precondition, not a band: §12.1's ``< 20`` refuses
        the thin pool, and 20 clears it.  A pool of 20 with the default floor of
        20 returns without raising — the run may begin.
        """
        for worlds in (20, 21, 50, 100):
            rejects_thin_pool(worlds)  # no refusal

    def test_the_default_floor_is_twenty(self):
        """§12.1's number, the floor the refusal judges against by default."""
        assert LADDER_FLOOR_WORLDS == 20
        # The boundary is exact: 19 refuses, 20 admits, on the default floor.
        with pytest.raises(PoolTooThinError):
            rejects_thin_pool(19, gate=LADDER_FLOOR_WORLDS)
        rejects_thin_pool(20, gate=LADDER_FLOOR_WORLDS)  # admitted

    def test_the_floor_is_a_parameter_not_a_constant(self):
        """A deployment that sets its own floor is judged against it.

        The floor is a keyword, defaulting to §12.1's 20 but settable — a
        deployment that raises the floor to 50 (the M3 gate's figure) refuses a
        pool feature 276 would have capped, and admits only what the gate would.
        """
        with pytest.raises(PoolTooThinError):
            rejects_thin_pool(40, gate=50)
        rejects_thin_pool(50, gate=50)  # admitted
        rejects_thin_pool(51, gate=50)  # admitted
        # A lower floor admits a pool the default would refuse.
        rejects_thin_pool(10, gate=5)  # admitted

    def test_the_refusal_is_a_verdict_over_a_count_not_a_count_itself(self):
        """The judgment takes the figure; it never opens a database or counts.

        The figure is the pool's size, which this member already computes — the
        same count a feature-270 hold records as ``world_count`` — passed in
        rather than read, so a verdict is not a count and the count is the
        caller's to supply.  Pinned as a pure function of two integers: no
        connection, no path, no store.
        """
        # A thin pool is refused; a thick one is admitted — both over plain ints.
        with pytest.raises(PoolTooThinError):
            rejects_thin_pool(10, gate=20)
        rejects_thin_pool(30, gate=20)  # admitted


class TestTheRefusalMessage:
    """What a thin-pool refusal says, since the message *is* the repair."""

    def test_the_refusal_opens_with_the_code(self):
        """The prefix is what makes a rejection greppable by its own word."""
        with pytest.raises(PoolTooThinError) as refusal:
            rejects_thin_pool(10, gate=20)

        assert str(refusal.value).startswith(POOL_TOO_THIN_CODE)

    def test_the_message_names_the_figure_and_the_floor(self):
        """Both ends of the judgement, so an operator can see what was measured."""
        with pytest.raises(PoolTooThinError) as refusal:
            rejects_thin_pool(7, gate=20)

        message = str(refusal.value)
        assert "7" in message
        assert "20" in message

    def test_the_message_names_the_governing_document(self):
        """A caller who has never read §12.1 meets this message, so it is legible."""
        with pytest.raises(PoolTooThinError) as refusal:
            rejects_thin_pool(3, gate=20)

        assert "§12.1" in str(refusal.value)

    def test_the_message_states_the_repair(self):
        """A refusal that only said "no" would leave a caller stuck.

        The repair for a thin pool is not to re-send the same run — it is to
        grow the pool, or to run fixed exploration and accumulate history until
        the pool clears the floor.
        """
        with pytest.raises(PoolTooThinError) as refusal:
            rejects_thin_pool(3, gate=20)

        message = str(refusal.value)
        assert "fixed exploration" in message or "accumulate history" in message


class TestTheVocabulary:
    """The floor's class: a sibling of feature 270's, under the one base."""

    def test_the_floor_error_is_a_dreaming_error(self):
        """One member, one base — a caller catches every failure with one except."""
        assert issubclass(PoolTooThinError, DreamingError)

    def test_the_floor_error_is_a_sibling_not_a_face_of_feature_270(self):
        """A thin pool is not a held pool, and must not be caught as one.

        Load-bearing for callers: a ``except PoolFrozenError`` that also
        swallowed a thin-pool refusal would let a cycle treat *"the pool is too
        thin to dream on"* as *"the pool is held by a cycle"*, and wait for a
        cycle that does not exist.
        """
        assert not issubclass(PoolTooThinError, PoolFrozenError)
        assert not issubclass(PoolFrozenError, PoolTooThinError)

    def test_the_code_is_feature_275s_word(self):
        """``pool_too_thin`` and not feature 270's ``pool_frozen``."""
        assert POOL_TOO_THIN_CODE == "pool_too_thin"
        assert POOL_TOO_THIN_CODE != "pool_frozen"


class TestTheInputs:
    """A malformed figure or floor is refused, not answered — a verdict is not a count."""

    def test_a_negative_figure_is_refused(self):
        """A pool holds zero worlds or more; a negative figure names no pool."""
        with pytest.raises(PoolTooThinError) as refusal:
            rejects_thin_pool(-1, gate=20)

        assert str(refusal.value).startswith(POOL_TOO_THIN_CODE)

    def test_a_negative_floor_is_refused(self):
        """A floor is a world count; a negative floor would admit every run."""
        with pytest.raises(PoolTooThinError) as refusal:
            rejects_thin_pool(10, gate=-5)

        assert str(refusal.value).startswith(POOL_TOO_THIN_CODE)

    def test_a_bool_figure_is_refused_where_a_count_belongs(self):
        """``True`` is ``1`` in Python, so a flag where a figure belongs is refused.

        A bool where the pool's size belongs would name a pool of one world,
        which is below any floor — but it would be refused for the wrong reason,
        so it is refused as a malformed figure rather than answered as a thin
        pool.
        """
        with pytest.raises(PoolTooThinError):
            rejects_thin_pool(True, gate=20)

    def test_a_bool_floor_is_refused_where_a_count_belongs(self):
        """A flag where the floor belongs would name the thinnest admissible pool."""
        with pytest.raises(PoolTooThinError):
            rejects_thin_pool(10, gate=True)

    def test_a_float_figure_is_refused(self):
        """A world count is a whole number; a fraction names no pool."""
        with pytest.raises(PoolTooThinError):
            rejects_thin_pool(19.5, gate=20)

    def test_a_non_numeric_figure_is_refused(self):
        """A figure that is not a number names no pool this judgment can measure."""
        with pytest.raises(PoolTooThinError):
            rejects_thin_pool("twenty", gate=20)

    def test_a_non_numeric_floor_is_refused(self):
        """A floor that is not a number cannot measure a pool."""
        with pytest.raises(PoolTooThinError):
            rejects_thin_pool(10, gate="20")

    def test_a_malformed_input_answers_no_verdict(self):
        """A run whose inputs are wrong is never silently admitted or blocked.

        The refusal is raised rather than answered, so a caller cannot read a
        malformed figure as *the pool is thin* or as *the pool is fine* — the
        inputs must be corrected first, which is the ask's own fault named in
        the ask's own vocabulary.
        """
        with pytest.raises(PoolTooThinError):
            rejects_thin_pool(None, gate=20)


class TestTheFloorValidation:
    """The one spelling of what the floor must be, shared by the judgment."""

    def test_a_valid_floor_passes_through(self):
        """A non-negative whole number is the floor it names."""
        assert validated_floor(20) == 20
        assert validated_floor(0) == 0
        assert validated_floor(50) == 50

    def test_a_negative_floor_is_refused(self):
        """A floor is a world count; a negative floor admits every run."""
        with pytest.raises(PoolTooThinError):
            validated_floor(-1)

    def test_a_bool_floor_is_refused(self):
        """``True`` is ``1`` in Python; a flag is not a floor."""
        with pytest.raises(PoolTooThinError):
            validated_floor(True)

    def test_a_float_floor_is_refused(self):
        """A floor is a whole number; a fraction names no floor."""
        with pytest.raises(PoolTooThinError):
            validated_floor(20.0)

    def test_a_non_numeric_floor_is_refused(self):
        """A floor that is not a number cannot measure a pool."""
        with pytest.raises(PoolTooThinError):
            validated_floor("20")
