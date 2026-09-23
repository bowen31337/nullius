"""Feature 280's claim, stated as tests: the meta-level selection bar.

app_spec.xml, "Dreaming Loop & Meta-Selection", feature 280: *System rejects a
winning revision whose advantage falls below the square root of twice the log
of M scaled by score deviation.*  docs/alpha-engine-prd.md §12.1 states the
rule — *"the selected policy's true advantage survives selection noise only
when ``true_advantage > √(2 ln M) · σ_V / √n_worlds``"* — and
docs/nullius-tech-architecture.md §10.3.1 states the stance: *"The orchestrator
enforces this as a hard precondition, not a guideline."*

So the claims worth pinning are these, and they are what the classes below are
arranged around:

* the **arithmetic reproduces the documents** — the strongest claim in the
  file and the reason it is first.  §12.1's *"bar ≈ 2.72"* at ``M = 40``,
  §7.3's whole null max-Sharpe table (2.15 / 3.03 / 3.72 / 4.29 at
  10 / 100 / 1,000 / 10,000 trials), and the section's own worked check —
  a target advantage of 0.3 at ``σ_V = 0.8`` crossing the bar between 52
  and 53 worlds, the *"n > 53 worlds"* that *"independently reproduces the
  ~56"* — are *derived* here, not quoted;
* the **edge is strict** — a winner exactly at the bar has not survived it
  (§12.1's *"only when"*), one float above has, and a negative advantage is
  refused by the bar rather than by a validation, because it falls below
  any bar the arithmetic can state;
* the **verdict is over figures the caller already holds** — the ladder's
  verdict shape, never a count, never a database;
* the **``M`` is read back from feature 277's record** — the refusal's
  ``M`` is the recorded cap, the record in force is the *newest* one naming
  the iteration (a retried cycle is re-decided), and a cycle with no record
  is refused as *"a bar over a number nobody ran"*;
* the **vocabulary is the bar's own three classes** — the ask, the store
  and the verdict, with the cap's request and record refusals *translated*
  at the seam, never propagated, and the one code on the verdict alone.
"""

from __future__ import annotations

import datetime as dt
import math
import sqlite3
from contextlib import closing

import pytest
from dreaming import (
    CAPPED_SWEEP_CAP,
    FULL_DREAMING_CAP,
    SELECTION_BAR_CODE,
    BarRecordError,
    BarRequestError,
    CapRecordError,
    CapRequestError,
    DreamingError,
    FreezeRequestError,
    PairedComparisonError,
    PairedDifference,
    PoolFrozenError,
    PoolTooThinError,
    ProportionComparisonError,
    RevisionCeilingError,
    SelectionBarError,
    SplitRequestError,
    SplitStoreError,
    TransferRequestError,
    TransferStoreError,
    cycle_bar,
    cycle_caps,
    paired_ir_difference,
    power_capacity,
    record_cycle_cap,
    rejects_unbarred_winner,
    selection_bar,
)


def dt_at(hour: int) -> dt.datetime:
    """An aware instant, fixed so a test's stamps are deterministic."""
    return dt.datetime(2026, 3, 1, hour, 0, 0, tzinfo=dt.UTC)


def _offsets(worlds: int) -> list[float]:
    """Symmetric offsets whose **sample** deviation is exactly one.

    ``+a`` and ``−a`` in equal halves — and a lone zero when the count is
    odd — so that ``Σ(x − x̄)² = n − 1`` and the ``n − 1`` denominator of
    the sample deviation cancels it: the deviations the tests build carry
    the mean and the spread they claim *exactly*, which matters because the
    52/53-world boundary the documents state sits 0.0013 wide and a 1%-off
    spread would cross it.
    """
    amplitude = 1.0 if worlds % 2 else math.sqrt((worlds - 1) / worlds)
    half = worlds // 2
    offsets = [amplitude] * half + [-amplitude] * half
    if worlds % 2:
        offsets.append(0.0)
    return offsets


def _winning_difference(
    worlds: int, *, mean: float = 0.3, spread: float = 0.8
) -> PairedDifference:
    """A taken comparison whose differences carry an exact mean and spread.

    Built through feature 281's own call — never a hand-assembled record —
    so the figures the bar judges are the figures the paired statistic
    actually answers: §12.1's ``σ_V`` is §11.0's ``σ_diff``, and the
    advantage is the mean paired difference.  The baseline arm reads zero
    on every world, so each world's difference is the candidate's reading.
    """
    candidate = {
        f"world-{index:03d}": mean + spread * offset
        for index, offset in enumerate(_offsets(worlds))
    }
    baseline = {world: 0.0 for world in candidate}
    return paired_ir_difference(candidate, baseline)


class TestTheArithmetic:
    """``selection_bar`` — Appendix B's line, derived rather than quoted."""

    def test_the_bar_at_forty_is_the_sections_own_figure(self):
        """§12.1: *"At ``M = 40`` (bar ≈ 2.72)"* — stated in SE units."""
        assert selection_bar(40, spread=1.0, worlds=1) == pytest.approx(
            2.72, abs=0.005
        )

    def test_the_bar_reproduces_section_7_3s_table(self):
        """§7.3's null max-Sharpe bar — the same statistic one level down.

        The PRD's own table reads 2.15 / 3.03 / 3.72 / 4.29 at
        10 / 100 / 1,000 / 10,000 trials; each is √(2 ln K) to two decimals,
        which is what the bar answers in SE units.
        """
        table = {
            10: 2.15,
            100: 3.03,
            1_000: 3.72,
            10_000: 4.29,
        }
        for trials, expected in table.items():
            assert round(selection_bar(trials, spread=1.0, worlds=1), 2) == (
                expected
            ), f"§7.3's bar at K = {trials}"

    def test_the_documents_own_worked_check_crosses_at_fifty_three(self):
        """§12.1's *"n > 53 worlds"*: 0.3 clears at 53 and not at 52.

        At ``M = 40``, ``σ_V = 0.8`` and a target advantage of 0.3 — the
        three figures the section itself computes with.
        """
        assert selection_bar(40, spread=0.8, worlds=52) > 0.3
        assert selection_bar(40, spread=0.8, worlds=53) < 0.3

        rejects_unbarred_winner(0.3, m=40, spread=0.8, worlds=53)
        with pytest.raises(SelectionBarError):
            rejects_unbarred_winner(0.3, m=40, spread=0.8, worlds=52)

    def test_the_two_derivations_of_the_pool_are_the_same_order(self):
        """§12.1's *"n > 53 … independently reproducing the ~56 from the
        paired-power calculation in §11.0"* — the bar's figure sits inside
        the power figure, both stated at the same 0.3 / 0.8."""
        smallest = next(
            worlds
            for worlds in range(1, 200)
            if selection_bar(40, spread=0.8, worlds=worlds) < 0.3
        )

        assert smallest == 53
        assert power_capacity(0.3, spread=0.8) == 56
        assert smallest <= power_capacity(0.3, spread=0.8)

    def test_one_revision_carries_no_selection_noise(self):
        """``ln 1 = 0``: the expected maximum of one null score is that
        score, and the multiple-testing width begins with the second
        candidate.  The arithmetic's own value, not a refusal."""
        assert selection_bar(1, spread=0.8, worlds=30) == 0.0

    def test_the_bar_grows_with_m(self):
        """Monotone in ``M`` — what makes judging a cycle at its recorded
        *cap* the conservative direction — and the ~1.27 the ceiling's own
        narrative computes between the rungs' caps."""
        at_ten = selection_bar(CAPPED_SWEEP_CAP, spread=0.8, worlds=53)
        at_forty = selection_bar(FULL_DREAMING_CAP, spread=0.8, worlds=53)

        assert at_forty > at_ten
        assert at_forty / at_ten == pytest.approx(1.2657, abs=0.0005)

    def test_the_bar_scales_with_the_deviation_and_the_root_of_the_worlds(self):
        """The formula's own shape: linear in ``σ_V``, inverse-square-root
        in ``n_worlds`` — the standard error of the mean score."""
        baseline = selection_bar(40, spread=0.8, worlds=53)

        assert selection_bar(40, spread=1.6, worlds=53) == pytest.approx(
            2 * baseline
        )
        assert selection_bar(40, spread=0.8, worlds=212) == pytest.approx(
            baseline / 2
        )

    def test_the_judgment_is_pure_over_figures(self, monkeypatch):
        """No database is opened, no row is read: the verdict's shape is the
        ladder's, over figures the caller already holds."""
        monkeypatch.delenv("DATABASE_URL", raising=False)

        rejects_unbarred_winner(0.3, m=40, spread=0.8, worlds=53)
        assert selection_bar(40, spread=0.8, worlds=53) == pytest.approx(
            0.29848, abs=1e-5
        )


class TestTheVerdict:
    """``rejects_unbarred_winner`` — §12.1's inequality, as a refusal."""

    def test_a_winner_above_the_bar_proceeds(self):
        """Returns without raising — the caller persists the winner."""
        assert rejects_unbarred_winner(0.4, m=40, spread=0.8, worlds=53) is None

    def test_a_winner_below_the_bar_is_refused_with_the_code(self):
        with pytest.raises(SelectionBarError) as refusal:
            rejects_unbarred_winner(0.25, m=40, spread=0.8, worlds=53)

        assert str(refusal.value).startswith(SELECTION_BAR_CODE)

    def test_the_refusal_states_both_ends_of_the_judgement(self):
        """The advantage, the bar, the three figures behind it, the section,
        and the repair — an operator reading the log sees what the winner
        earned and what surviving selection noise costs."""
        with pytest.raises(SelectionBarError) as refusal:
            rejects_unbarred_winner(0.25, m=40, spread=0.8, worlds=53)

        message = str(refusal.value)
        assert "0.25" in message
        assert "M = 40" in message
        assert "0.8" in message
        assert "53" in message
        assert "sqrt(2 ln M) . sigma_V / sqrt(n_worlds)" in message
        assert "§12.1" in message
        assert "incumbent" in message

    def test_the_edge_is_strict(self):
        """§12.1's *"only when"*: an advantage exactly at the bar has not
        exceeded it — the edge ``PairedDifference.clears`` states for the
        gate's own criterion — and one float above has."""
        bar = selection_bar(40, spread=0.8, worlds=53)

        with pytest.raises(SelectionBarError):
            rejects_unbarred_winner(bar, m=40, spread=0.8, worlds=53)
        rejects_unbarred_winner(
            math.nextafter(bar, math.inf), m=40, spread=0.8, worlds=53
        )

    def test_a_negative_advantage_is_refused_by_the_bar(self):
        """Not by a validation: it falls below any bar the arithmetic can
        state, and the refusal that names it is a verdict."""
        with pytest.raises(SelectionBarError) as refusal:
            rejects_unbarred_winner(-0.4, m=40, spread=0.8, worlds=53)

        assert str(refusal.value).startswith(SELECTION_BAR_CODE)

    def test_a_wider_sweep_widens_the_bar_the_winner_must_clear(self):
        """§12.1's warning as arithmetic: the same advantage is admitted at
        the middle rung's cap and refused at the raised one."""
        rejects_unbarred_winner(0.28, m=CAPPED_SWEEP_CAP, spread=0.8, worlds=53)
        with pytest.raises(SelectionBarError):
            rejects_unbarred_winner(0.28, m=FULL_DREAMING_CAP, spread=0.8, worlds=53)


class TestTheAsk:
    """The ask's own facts, refused before anything is computed."""

    @pytest.mark.parametrize(
        "advantage",
        ["0.3", None, True, float("nan"), float("inf")],
    )
    def test_an_advantage_that_is_not_a_finite_real_is_refused(self, advantage):
        with pytest.raises(BarRequestError) as refusal:
            rejects_unbarred_winner(advantage, m=40, spread=0.8, worlds=53)

        assert "advantage" in str(refusal.value)
        assert SELECTION_BAR_CODE not in str(refusal.value)

    @pytest.mark.parametrize("m", [0, -3, True, 4.5, "40"])
    def test_a_revision_count_that_is_not_one_or_more_whole_is_refused(self, m):
        with pytest.raises(BarRequestError) as refusal:
            rejects_unbarred_winner(0.3, m=m, spread=0.8, worlds=53)

        assert "revision count" in str(refusal.value)

    @pytest.mark.parametrize(
        "spread",
        [0.0, -0.8, True, "0.8", float("nan")],
    )
    def test_a_deviation_that_is_not_strictly_positive_is_refused(self, spread):
        with pytest.raises(BarRequestError) as refusal:
            rejects_unbarred_winner(0.3, m=40, spread=spread, worlds=53)

        assert "score deviation" in str(refusal.value)

    @pytest.mark.parametrize("worlds", [0, -1, True, 2.5, "53"])
    def test_a_world_count_that_is_not_one_or_more_whole_is_refused(self, worlds):
        with pytest.raises(BarRequestError) as refusal:
            rejects_unbarred_winner(0.3, m=40, spread=0.8, worlds=worlds)

        assert "world count" in str(refusal.value)

    def test_the_figures_are_refused_in_signature_order(self):
        """The ask's own facts first, each naming *its* subject: a caller
        that hands two malformed figures is told about the first."""
        with pytest.raises(BarRequestError) as refusal:
            rejects_unbarred_winner(float("nan"), m=0, spread=0.0, worlds=0)

        assert "advantage" in str(refusal.value)

    def test_the_arithmetic_refuses_its_figures_the_same_way(self):
        """``selection_bar`` validates what it computes over — the one
        spelling of the validators, shared by every entry point."""
        with pytest.raises(BarRequestError):
            selection_bar(0, spread=0.8, worlds=53)
        with pytest.raises(BarRequestError):
            selection_bar(40, spread=0.8, worlds=0)


class TestTheStoreSeam:
    """``cycle_bar`` — ``M`` read back from feature 277's own record."""

    def test_the_bar_is_read_back_from_the_cycles_record(self, pool):
        """The recorded cap sets the bar: a 52-world pool records 40, and
        the winner is judged at 40 — the refusal's ``M`` is the store's
        figure, never a number the caller handed in (the seam takes no
        ``m``; there is nothing to hand)."""
        record_cycle_cap("cycle-1", 52, database_url=pool, recorded_at=dt_at(10))
        difference = _winning_difference(52)

        assert difference.paired_worlds == 52
        assert difference.mean_difference == pytest.approx(0.3)
        assert difference.spread == pytest.approx(0.8)

        with pytest.raises(SelectionBarError) as refusal:
            cycle_bar("cycle-1", difference, database_url=pool)

        message = str(refusal.value)
        assert message.startswith(SELECTION_BAR_CODE)
        assert "M = 40" in message

    def test_a_clearing_winner_is_answered_with_the_bar_it_cleared(self, pool):
        """The seam answers the bar, so the caller that persists the winner
        can carry what it cleared — the same figure ``selection_bar``
        answers over the same figures."""
        record_cycle_cap("cycle-1", 53, database_url=pool, recorded_at=dt_at(10))
        difference = _winning_difference(53, mean=0.5)

        bar = cycle_bar("cycle-1", difference, database_url=pool)

        assert bar == pytest.approx(
            selection_bar(40, spread=difference.spread, worlds=53)
        )
        assert bar < 0.5

    def test_the_middle_rungs_cap_narrows_the_bar(self, pool):
        """A 30-world pool records 10 — feature 277's own schedule — and
        the winner is judged at the rung it actually ran on."""
        record_cycle_cap("cycle-1", 30, database_url=pool, recorded_at=dt_at(10))
        difference = _winning_difference(30, mean=0.4)

        bar = cycle_bar("cycle-1", difference, database_url=pool)

        assert bar == pytest.approx(
            selection_bar(10, spread=difference.spread, worlds=30)
        )
        with pytest.raises(SelectionBarError) as refusal:
            cycle_bar("cycle-1", _winning_difference(30, mean=0.2), database_url=pool)

        assert "M = 10" in str(refusal.value)

    def test_the_sections_own_figures_survive_the_whole_loop(self, pool):
        """The §12.1 sentence end to end: a comparison whose mean is 0.3
        and whose spread measures 0.8 over its own worlds, judged at the
        recorded 40 — admitted at 53 worlds, refused at 52, exactly as the
        section's own arithmetic says."""
        record_cycle_cap("cycle-53", 53, database_url=pool, recorded_at=dt_at(10))
        record_cycle_cap("cycle-52", 52, database_url=pool, recorded_at=dt_at(10))

        assert cycle_bar(
            "cycle-53", _winning_difference(53), database_url=pool
        ) == pytest.approx(selection_bar(40, spread=0.8, worlds=53))
        with pytest.raises(SelectionBarError):
            cycle_bar("cycle-52", _winning_difference(52), database_url=pool)

    def test_the_record_in_force_is_the_newest_one(self, pool):
        """A retried cycle is re-decided — feature 277's own law, one row
        per occurrence — so the bar judges at the *last* cap recorded for
        the iteration: the decision that was in force when the sweep ran.

        Same store, same figures, both orders: a re-decision that raises
        the cap widens the bar under a winner that had cleared; one that
        lowers it narrows the bar under a winner that had been refused.
        """
        # An advantage that clears the middle rung's bar and not the raised
        # one, over the same 53 worlds.
        difference = _winning_difference(53, mean=0.27)
        at_ten = selection_bar(10, spread=difference.spread, worlds=53)
        at_forty = selection_bar(40, spread=difference.spread, worlds=53)
        assert at_ten < 0.27 < at_forty

        record_cycle_cap("cycle-1", 30, database_url=pool, recorded_at=dt_at(10))
        record_cycle_cap("cycle-1", 53, database_url=pool, recorded_at=dt_at(11))
        with pytest.raises(SelectionBarError):
            cycle_bar("cycle-1", difference, database_url=pool)

    def test_a_re_decision_that_lowers_the_cap_narrows_the_bar(self, pool):
        record_cycle_cap("cycle-1", 53, database_url=pool, recorded_at=dt_at(10))
        record_cycle_cap("cycle-1", 30, database_url=pool, recorded_at=dt_at(11))
        difference = _winning_difference(53, mean=0.27)

        bar = cycle_bar("cycle-1", difference, database_url=pool)

        assert bar == pytest.approx(
            selection_bar(10, spread=difference.spread, worlds=53)
        )

    def test_a_cycle_with_no_record_is_a_bar_over_a_number_nobody_ran(self, pool):
        """The refusal feature 277 persisted the cap for: an ``M`` nobody
        recorded judges nothing."""
        record_cycle_cap("cycle-1", 53, database_url=pool, recorded_at=dt_at(10))

        with pytest.raises(BarRecordError) as refusal:
            cycle_bar("cycle-2", _winning_difference(53), database_url=pool)

        message = str(refusal.value)
        assert "'cycle-2'" in message
        assert "nobody recorded" in message
        assert "record_cycle_cap" in message

    def test_no_database_named_is_refused_in_the_bars_own_word(self, monkeypatch):
        """Translated at the seam: the caller asked for a bar and must not
        be told the cap could not be *recorded* — the refusal opens with
        the bar's own subject, and the cap's word for its own act appears
        only as the attributed quote of the seam that raised it."""
        monkeypatch.delenv("DATABASE_URL", raising=False)

        with pytest.raises(BarRequestError) as refusal:
            cycle_bar("cycle-1", _winning_difference(53))

        message = str(refusal.value)
        assert message.startswith("judging a cycle's winner")
        assert "See the refusal the record's own seam raised" in message
        assert not isinstance(refusal.value, CapRequestError)
        assert isinstance(refusal.value.__cause__, CapRequestError)

    def test_a_database_without_a_pool_is_refused_in_the_bars_own_word(
        self, tmp_path
    ):
        """A store without the pool holds no dreaming cycles and so no caps
        to read — the cap's record refusal, translated, not propagated."""
        bare = tmp_path / "bare.db"
        with closing(sqlite3.connect(bare)):
            pass

        with pytest.raises(BarRecordError) as refusal:
            cycle_bar(
                "cycle-1",
                _winning_difference(53),
                database_url=f"sqlite:///{bare}",
            )

        assert isinstance(refusal.value.__cause__, CapRecordError)

    def test_the_figures_are_validated_before_the_store_is_read(
        self, monkeypatch
    ):
        """A record is a value any caller can construct: a hand-built
        comparison carrying a non-finite advantage is refused as the ask's
        own fact — before the database is asked for anything."""
        monkeypatch.delenv("DATABASE_URL", raising=False)
        broken = PairedDifference(
            paired_worlds=2,
            candidate_mean=1.0,
            baseline_mean=0.0,
            mean_difference=float("nan"),
            spread=0.8,
            standard_error=0.4,
            t_statistic=2.5,
            p_value=0.01,
            differences=(("w-1", float("nan")), ("w-2", float("nan"))),
        )

        with pytest.raises(BarRequestError) as refusal:
            cycle_bar("cycle-1", broken)

        assert "advantage" in str(refusal.value)

    def test_a_comparison_that_is_not_one_is_refused(self, pool):
        """The advantage, the deviation and the world count are three
        figures one comparison carries — loose figures could come from
        three different measurements."""
        with pytest.raises(BarRequestError) as refusal:
            cycle_bar("cycle-1", {"world-1": 0.3}, database_url=pool)

        assert "PairedDifference" in str(refusal.value)
        assert "rejects_unbarred_winner" in str(refusal.value)

    def test_a_blank_iteration_is_refused_before_the_store(self, pool):
        with pytest.raises(BarRequestError) as refusal:
            cycle_bar("  ", _winning_difference(53), database_url=pool)

        assert "non-empty string" in str(refusal.value)

    def test_the_seam_writes_nothing(self, pool):
        """Reads ``cycle_cap``, writes no row: an admitted and a refused
        judgment leave the history exactly as the record left it."""
        record_cycle_cap("cycle-1", 53, database_url=pool, recorded_at=dt_at(10))
        history_before = cycle_caps(database_url=pool)
        assert len(history_before) == 1

        cycle_bar("cycle-1", _winning_difference(53, mean=0.5), database_url=pool)
        with pytest.raises(SelectionBarError):
            cycle_bar("cycle-1", _winning_difference(53, mean=0.1), database_url=pool)

        assert cycle_caps(database_url=pool) == history_before


class TestTheVocabulary:
    """Three classes, one base, and the lines they deliberately do not cross."""

    def test_the_three_faces_share_one_base(self):
        for bar_class in (BarRequestError, BarRecordError, SelectionBarError):
            assert issubclass(bar_class, DreamingError)
            assert issubclass(bar_class, Exception)

    @pytest.mark.parametrize(
        "bar_class",
        [BarRequestError, BarRecordError, SelectionBarError],
    )
    def test_the_three_faces_are_siblings_of_every_existing_class(self, bar_class):
        """A caller catches a bar's refusal without catching a hold's, a
        thin pool's, a cap's, a split's, a comparison's or a transfer's —
        and vice versa: the repairs all differ."""
        for sibling in (
            FreezeRequestError,
            PoolFrozenError,
            PoolTooThinError,
            CapRequestError,
            CapRecordError,
            RevisionCeilingError,
            SplitRequestError,
            SplitStoreError,
            ProportionComparisonError,
            PairedComparisonError,
            TransferRequestError,
            TransferStoreError,
        ):
            assert not issubclass(bar_class, sibling), bar_class
            assert not issubclass(sibling, bar_class), sibling

    def test_the_code_is_on_the_verdict_alone(self):
        """``advantage_below_bar`` opens the verdict — the one refusal an
        operator greps a deployment log for — while the ask and store faces
        open with their subjects, the stance the cap's pair states."""
        assert SELECTION_BAR_CODE == "advantage_below_bar"

        with pytest.raises(SelectionBarError) as verdict:
            rejects_unbarred_winner(0.25, m=40, spread=0.8, worlds=53)
        with pytest.raises(BarRequestError) as ask:
            rejects_unbarred_winner(float("nan"), m=40, spread=0.8, worlds=53)

        assert str(verdict.value).startswith(SELECTION_BAR_CODE)
        assert not str(ask.value).startswith(SELECTION_BAR_CODE)

    def test_the_verdict_is_not_the_comparisons_or_the_ceilings(self):
        """The comparison grounded fine (the subject is the noise of
        winning, not the pairing of worlds); the sweep was legal (the
        ceiling refuses it before it runs, the bar refuses the winner
        after).  A caller that must react differently to the three cannot
        catch one class and tell them apart."""
        assert not issubclass(SelectionBarError, PairedComparisonError)
        assert not issubclass(SelectionBarError, RevisionCeilingError)
        assert not issubclass(SelectionBarError, BarRequestError)
        assert not issubclass(SelectionBarError, BarRecordError)
