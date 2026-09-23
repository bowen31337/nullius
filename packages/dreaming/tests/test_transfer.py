"""Feature 282's claim, stated as tests: the family-shaped holdout.

app_spec.xml, "Dreaming Loop & Meta-Selection", feature 282: *System computes
leave-one-family-out transfer by holding an entire theme root out of the pool,
which returns the delta on that held-out theme.*  docs/alpha-engine-prd.md
§4.5 states why the metric exists at all — *"Hold an entire theme root out of
the dreaming pool, then evaluate on worlds from that theme.  It measures
transfer directly, costs almost nothing, and is the only honest way to tell
learned research discipline from memorized family texture."* — and §15 states
why the holdout has to be *family*-shaped: *"shape features do not [transfer]
and two of them invert sign across families."*

So the claims worth pinning are these, and they are what the classes below
are arranged around:

* **the holdout is entire.**  Every world whose root is the family named
  leaves the pool — there is no parameter that could hold half a family out,
  and the test pins that the two halves are exactly the family's worlds and
  everything else, disjoint, in the pool's id order whatever order the
  caller's census was built in;
* **the delta is on the held-out family only.**  The comparison is feature
  281's, restricted to the family's worlds: readings for any other world are
  not evaluated, and the figure agrees with an independently restricted
  :func:`dreaming.paired_ir_difference` to the bit;
* **the floor judges the pool that remains.**  A retained pool below §12.1's
  floor is feature 275's refusal, delegated, in the floor's own word — and a
  pool whose worlds all carry one root (the campaign-diversity failure)
  arrives as that refusal too, not as a second law minted here;
* **the family is the caller's fact, and at the store seam the pool is
  ground truth.**  A census that misses pool worlds, or names worlds the
  store does not hold, is refused with the disagreement named — because
  *"holding an entire theme root out of the pool"* is a claim about the
  pool;
* **the delegated laws stay delegated.**  A world of the family only one arm
  carries, a family too small to spread, a non-finite figure — each is
  refused in feature 281's vocabulary, by feature 281's own law, never
  re-spelled here.
"""

from __future__ import annotations

import sqlite3
import statistics
from contextlib import closing
from pathlib import Path

import pytest
from dreaming import (
    DATABASE_URL_ENV,
    FREEZE_CODE,
    PAIRED_CODE,
    POOL_TOO_THIN_CODE,
    CapRecordError,
    CapRequestError,
    CycleFreeze,
    DreamingError,
    FamilyPartition,
    FreezeRequestError,
    PairedComparisonError,
    PairedDifference,
    PoolFrozenError,
    PoolTooThinError,
    ProportionComparisonError,
    RevisionCeilingError,
    SplitRequestError,
    SplitStoreError,
    TransferRequestError,
    TransferStoreError,
    family_transfer,
    leave_one_family_out,
    paired_ir_difference,
    pool_bootstrap_schema,
    pooled_family_transfer,
    sqlite_path,
)

#: The two families the fixtures plant — §241's default theme set carries both
#: spellings, and a bootstrap world's own root is ``hpo``
#: (:data:`bootstrap._question.BOOTSTRAP_THEME_ROOT`), so ``hpo`` is the root
#: a real census would be asked to hold out first.
HELD_ROOT = "hpo"
RETAINED_ROOT = "mom"

#: §12.1's floor, restated so a test that builds a pool around it reads as
#: the document it is pinning rather than as a bare literal.
FLOOR = 20


def _families(
    *,
    held: int = 4,
    retained: int = FLOOR,
    held_root: str = HELD_ROOT,
    retained_root: str = RETAINED_ROOT,
) -> dict[str, str]:
    """A pool's census: ``held`` worlds of one root, ``retained`` of another.

    The default answers a pool that clears the floor once the family is out
    (``retained`` at exactly 20), so every test below that is *not* about the
    floor starts from a legal pool — and every test that is about it moves one
    world.
    """
    families: dict[str, str] = {}
    for index in range(held):
        families[f"world-{index:03d}"] = held_root
    for index in range(held, held + retained):
        families[f"world-{index:03d}"] = retained_root
    return families


def _arms(
    families: dict[str, str],
    *,
    base: float = 0.10,
    step: float = 0.05,
    gain: float = 0.30,
    wobble: float = 0.02,
) -> tuple[dict[str, float], dict[str, float]]:
    """Both arms' readings over a whole census, differing by more than a trend.

    The two arms share the ``step`` (the world-to-world trend) and differ by
    ``gain`` plus a small per-world ``wobble`` — the wobble is load-bearing:
    two arms differing by a constant are refused by the statistic itself (a
    standard error of exactly zero), so a fixture without it would exercise
    the refusal rather than the comparison.
    """
    candidate: dict[str, float] = {}
    baseline: dict[str, float] = {}
    for index, world in enumerate(sorted(families)):
        baseline[world] = base + step * index
        candidate[world] = base + step * index + gain + wobble * (index % 3)
    return candidate, baseline


class TestTheHoldoutIsEntire:
    """§4.5's *"an entire theme root"* — every world of the family, and only those."""

    def test_the_two_halves_are_the_family_and_everything_else(self):
        """Holding ``hpo`` out removes the ``hpo`` worlds and nothing else.

        The partition's whole claim: the held-out half is exactly the family's
        worlds and the retained half is exactly the rest, so the two halves
        are disjoint and together are the pool the census named.
        """
        families = _families(held=4, retained=20)

        partition = leave_one_family_out(families, theme=HELD_ROOT)

        assert partition.theme == HELD_ROOT
        assert partition.held_out == tuple(f"world-{index:03d}" for index in range(4))
        assert partition.retained == tuple(
            f"world-{index:03d}" for index in range(4, 24)
        )
        assert not (set(partition.held_out) & set(partition.retained))
        assert set(partition.held_out) | set(partition.retained) == set(families)

    def test_the_halves_come_in_the_pools_id_order_whatever_the_census_order(self):
        """The same families answer the same partition in any process.

        The order is the pool's id order — the same total order
        :func:`dreaming.pool_worlds` answers — so a census built in reverse
        (or by two different callers) constructs one partition, not two that
        differ by insertion order.
        """
        families = _families(held=3, retained=20)

        forward = leave_one_family_out(families, theme=HELD_ROOT)
        backward = leave_one_family_out(
            dict(reversed(list(families.items()))), theme=HELD_ROOT
        )

        assert forward == backward
        assert hash(forward) == hash(backward)
        assert forward.held_out == tuple(sorted(forward.held_out))
        assert forward.retained == tuple(sorted(forward.retained))

    def test_a_family_scattered_through_the_id_order_is_held_out_whole(self):
        """Interleaving is not half-holding: root decides, nothing else.

        *Which* worlds leave is decided by nothing but their root — there is
        no positional parameter, no stride, no count.  A family whose worlds
        interleave with the retained family's in id order still leaves
        entirely, which is the *"entire"* of the sentence as a construction
        fact rather than a convention.
        """
        families = {
            f"world-{index:03d}": (
                HELD_ROOT if index % 2 == 0 else RETAINED_ROOT
            )
            for index in range(40)
        }

        partition = leave_one_family_out(families, theme=HELD_ROOT)

        assert partition.held_out == tuple(
            f"world-{index:03d}" for index in range(0, 40, 2)
        )
        assert partition.retained == tuple(
            f"world-{index:03d}" for index in range(1, 40, 2)
        )

    def test_the_partition_carries_the_roots_the_pool_carried(self):
        """``roots`` and its count — the breadth the hold-out was chosen among."""
        families = _families(held=4, retained=20)
        families["world-990"] = "event"

        partition = leave_one_family_out(families, theme=HELD_ROOT)

        assert partition.roots == ("event", HELD_ROOT, RETAINED_ROOT)
        assert partition.family_count == 3
        assert partition.world_count == len(families)

    def test_the_predicates_answer_by_root_and_refuse_strangers(self):
        """``is_held_out`` / ``is_retained``, and the refusal both share.

        A world the partition does not hold is refused by both predicates
        rather than answered ``False``: a world outside the pool is in no
        family this partition knows, and an answer that read as one side
        would let a caller mark a world the hold-out never saw — the split's
        own predicates refuse for the same reason.
        """
        families = _families(held=4, retained=20)
        partition = leave_one_family_out(families, theme=HELD_ROOT)

        assert partition.is_held_out("world-000")
        assert not partition.is_retained("world-000")
        assert partition.is_retained("world-004")
        assert not partition.is_held_out("world-004")

        for stranger in ("world-990", None, 42, ""):
            with pytest.raises(TransferRequestError):
                partition.is_held_out(stranger)
            with pytest.raises(TransferRequestError):
                partition.is_retained(stranger)

    def test_the_record_is_a_value_not_a_view_of_the_census(self):
        """A caller that keeps writing its census cannot move a partition.

        The stance the split's and the comparison's records state: the halves
        are carried as tuples cut at construction, so a later edit to the
        caller's dict is not silently reflected in a partition already read.
        """
        families = _families(held=4, retained=20)
        partition = leave_one_family_out(families, theme=HELD_ROOT)

        families["world-004"] = HELD_ROOT  # mutate the caller's own census
        families["world-991"] = "event"

        assert "world-991" not in partition.retained
        assert partition.is_retained("world-004")
        assert partition.world_count == 24

    def test_the_row_is_a_fresh_dict_per_call(self):
        """A store-shaped mapping, and a new object each time."""
        partition = leave_one_family_out(_families(held=2, retained=20), theme=HELD_ROOT)

        first = partition.row()
        first["theme"] = "tampered"

        assert partition.row()["theme"] == HELD_ROOT
        assert set(partition.row()) == {"theme", "held_out", "retained", "roots"}

    def test_a_partition_whose_halves_overlap_is_refused(self):
        """A world in both halves would be evaluated on and selected over.

        That is the family-shaped leak the partition exists to prevent,
        refused at the one place it could be constructed by hand.
        """
        with pytest.raises(TransferRequestError) as refusal:
            FamilyPartition(
                theme=HELD_ROOT,
                held_out=("world-000",),
                retained=("world-000", "world-001"),
                roots=(HELD_ROOT, RETAINED_ROOT),
            )

        assert "in both" in str(refusal.value)


class TestTheFloorJudgesTheRetainedPool:
    """The ladder's own judgment over the pool that *remains* — delegated."""

    def test_a_retained_pool_below_the_floor_is_the_ladders_refusal(self):
        """Nineteen worlds left: feature 275's word, naming the retained figure.

        A transfer figure computed over a selection that could never have run
        (§12.1: *"below 20 worlds: do not run dreaming"*) would be a number
        about nothing, so the retained half is judged by the ladder's own
        refusal — the identical delegation the cap, the ceiling and the split
        perform.
        """
        families = _families(held=5, retained=19)

        with pytest.raises(PoolTooThinError) as refusal:
            leave_one_family_out(families, theme=HELD_ROOT)

        message = str(refusal.value)
        assert message.startswith(POOL_TOO_THIN_CODE)
        assert "19 world(s)" in message

    def test_the_floor_judges_the_retained_half_not_the_held_out_one(self):
        """A family may be huge; the pool that must clear the floor is the rest.

        The selection runs over the retained half, so that is the half whose
        size grounds the figure.  Thirty worlds held out and twenty retained
        is admitted — the family's size is the metric's *evidence*, not the
        run's precondition.
        """
        partition = leave_one_family_out(_families(held=30, retained=20), theme=HELD_ROOT)

        assert len(partition.held_out) == 30
        assert len(partition.retained) == 20

    def test_a_pool_of_one_family_is_refused_by_the_delegated_floor(self):
        """The campaign-diversity failure arrives as the floor's, not a new law.

        A pool whose worlds all carry one root has an empty retained half —
        §11.1's ``plan_grid`` constraint exists to keep this pool from being
        built, and when it is built anyway, the honest refusal is the ladder's
        (nothing remains to dream on), refused in the ladder's own word rather
        than a second campaign law minted here.
        """
        families = _families(held=24, retained=0)

        with pytest.raises(PoolTooThinError) as refusal:
            leave_one_family_out(families, theme=HELD_ROOT)

        assert "0 world(s)" in str(refusal.value)

    def test_the_floor_passes_through_as_the_ladders_gate(self):
        """A deployment's own floor is the ladder's keyword, not a second one.

        Pinned so the two spellings of the bottom rung cannot disagree: the
        same pool is refused at the default floor and admitted at a lower one,
        with the figure named in both directions.
        """
        families = _families(held=15, retained=5)

        with pytest.raises(PoolTooThinError):
            leave_one_family_out(families, theme=HELD_ROOT)
        assert leave_one_family_out(families, theme=HELD_ROOT, floor=5).world_count == 20

    @pytest.mark.parametrize("floor", [True, "20", -1, 20.0])
    def test_a_floor_that_is_not_a_world_count_is_the_ladders_refusal(
        self, floor
    ):
        """Refused by the ladder's own validator, in the ladder's vocabulary."""
        with pytest.raises(PoolTooThinError) as refusal:
            leave_one_family_out(_families(held=4, retained=20), theme=HELD_ROOT, floor=floor)

        assert str(refusal.value).startswith(POOL_TOO_THIN_CODE)

    def test_the_transfer_call_refuses_the_thin_retained_pool_too(self):
        """Both spellings refuse in the same order — thin pool before pairing.

        A pool whose retained half is too thin *and* whose arms fail to pair
        is refused for the floor: the selection the figure presumes would
        itself be refused, so the pairing question never becomes the message
        a caller reads.
        """
        families = _families(held=5, retained=19)
        candidate, baseline = _arms(families)
        del baseline["world-000"]  # an unpaired world, waiting behind the floor

        with pytest.raises(PoolTooThinError):
            family_transfer(
                candidate, baseline, themes=families, theme=HELD_ROOT
            )


class TestTheDeltaIsOnTheHeldOutFamilyOnly:
    """§11.1's ``lofo_delta_ir`` — the paired delta over the family's worlds alone."""

    def test_the_delta_is_the_mean_paired_difference_over_the_family(self):
        """The metric's own arithmetic, computed independently of the module.

        §11's table states the metric as *"ΔIR on a held-out theme root"*:
        the candidate arm's mean reading minus the baseline arm's, over the
        held-out family's worlds, world by world.  The expected figure is
        recomputed here from the fixture's own numbers, so the agreement is
        about the *restriction and the statistic*, not about the module
        agreeing with itself.
        """
        families = _families(held=4, retained=20)
        candidate, baseline = _arms(families)

        transfer = family_transfer(candidate, baseline, themes=families, theme=HELD_ROOT)

        held = [world for world, root in families.items() if root == HELD_ROOT]
        differences = [candidate[world] - baseline[world] for world in held]
        assert transfer.delta_ir == pytest.approx(statistics.fmean(differences))
        assert transfer.held_out == tuple(sorted(held))
        assert transfer.retained_worlds == 20

    def test_readings_for_other_families_are_not_evaluated(self):
        """That is the hold-out itself, not a drop.

        Arms carrying the whole pool are restricted to the family's worlds
        before anything is differenced, so a reading on a retained world
        cannot move the figure — pinned hardest by *changing* the retained
        readings and watching the figure hold still.
        """
        families = _families(held=4, retained=20)
        candidate, baseline = _arms(families)

        transfer = family_transfer(candidate, baseline, themes=families, theme=HELD_ROOT)
        moved_candidate = dict(candidate)
        moved_baseline = dict(baseline)
        for world, root in families.items():
            if root == RETAINED_ROOT:
                moved_candidate[world] += 5.0
                moved_baseline[world] -= 5.0

        moved = family_transfer(
            moved_candidate, moved_baseline, themes=families, theme=HELD_ROOT
        )

        assert moved == transfer
        assert transfer.difference.paired_worlds == 4
        assert dict(transfer.difference.differences).keys() == {
            world for world, root in families.items() if root == HELD_ROOT
        }

    def test_the_delta_agrees_with_an_independently_restricted_comparison(self):
        """One arithmetic: the feature's figure *is* feature 281's, restricted.

        Restricting both arms by hand and handing them to
        :func:`dreaming.paired_ir_difference` must answer the same
        :class:`~dreaming.paired.PairedDifference` the transfer carries —
        not a respelling of it — because the delta on a held-out theme is a
        paired comparison over that theme's worlds and this module mints no
        second statistic.
        """
        families = _families(held=4, retained=20)
        candidate, baseline = _arms(families)
        held = frozenset(
            world for world, root in families.items() if root == HELD_ROOT
        )

        transfer = family_transfer(candidate, baseline, themes=families, theme=HELD_ROOT)
        restricted = paired_ir_difference(
            {world: figure for world, figure in candidate.items() if world in held},
            {world: figure for world, figure in baseline.items() if world in held},
        )

        assert transfer.difference == restricted
        assert transfer.delta_ir == restricted.mean_difference
        assert isinstance(transfer.difference, PairedDifference)

    def test_the_metric_reads_strictly_positive(self):
        """§11's target and §12's M3 exit: *"ΔIR on a held-out theme root > 0"*.

        Both edges strict — a delta of exactly zero is not transfer, and a
        negative one is a finding (the family read *worse* under the
        candidate), carried by the sign rather than squared away.
        """
        better = family_transfer(
            *_arms(_families(held=4, retained=20)), themes=_families(held=4, retained=20), theme=HELD_ROOT
        )
        worse = family_transfer(
            *_reversed_arms(_families(held=4, retained=20)),
            themes=_families(held=4, retained=20),
            theme=HELD_ROOT,
        )
        flat = family_transfer(
            *_flat_arms(), themes=_flat_families(), theme=HELD_ROOT
        )

        assert better.delta_ir > 0.0 and better.transfers is True
        assert worse.delta_ir < 0.0 and worse.transfers is False
        assert flat.delta_ir == pytest.approx(0.0) and flat.transfers is False

    def test_the_record_carries_the_evidence_and_the_pool_it_left(self):
        """The family, its worlds, the retained count, and the whole comparison.

        An operator reading a transfer figure can see *which* family it was
        held out on and over *how many* worlds, not only that a delta came
        out — and the row carries the comparison's own row, evidence included.
        """
        families = _families(held=4, retained=20)
        candidate, baseline = _arms(families)

        transfer = family_transfer(candidate, baseline, themes=families, theme=HELD_ROOT)

        assert transfer.theme == HELD_ROOT
        assert transfer.retained_worlds == 20
        first = transfer.row()
        first["difference"]["mean_difference"] = "tampered"
        assert transfer.row()["difference"]["mean_difference"] != "tampered"
        assert set(transfer.row()) == {
            "theme",
            "held_out",
            "retained_worlds",
            "difference",
        }

    def test_the_record_is_a_value_not_a_view_of_the_arms(self):
        """A caller that keeps writing its arms cannot move a figure already read."""
        families = _families(held=4, retained=20)
        candidate, baseline = _arms(families)

        transfer = family_transfer(candidate, baseline, themes=families, theme=HELD_ROOT)
        candidate["world-000"] = 99.0
        baseline["world-001"] = -99.0

        assert transfer.delta_ir == pytest.approx(
            statistics.fmean(
                [
                    candidate0 - baseline0
                    for candidate0, baseline0 in _arm_pairs(families)
                ]
            )
        )

    def test_the_record_compares_and_hashes_by_value(self):
        """Two transfers of the same census and arms are one transfer."""
        families = _families(held=4, retained=20)
        candidate, baseline = _arms(families)

        first = family_transfer(candidate, baseline, themes=families, theme=HELD_ROOT)
        second = family_transfer(
            dict(candidate), dict(baseline), themes=dict(families), theme=HELD_ROOT
        )

        assert first == second
        assert hash(first) == hash(second)
        assert first != object()

    def test_the_census_order_does_not_move_the_figure(self):
        """Pairing is by world id — the same census in any order, one figure."""
        families = _families(held=4, retained=20)
        candidate, baseline = _arms(families)

        forward = family_transfer(candidate, baseline, themes=families, theme=HELD_ROOT)
        reordered = family_transfer(
            candidate,
            baseline,
            themes=dict(reversed(list(families.items()))),
            theme=HELD_ROOT,
        )

        assert forward == reordered


class TestTheUnknownFamily:
    """A root the pool does not carry — refused as the ask's own fault."""

    def test_a_root_the_pool_does_not_carry_is_refused_with_the_carried_ones(self):
        """The refusal states the roots the pool *does* carry.

        An operator holding a stale census sees the drift rather than a
        refusal about statistics: the message names the root asked out and
        the families the pool actually holds.
        """
        with pytest.raises(TransferRequestError) as refusal:
            leave_one_family_out(_families(held=4, retained=20), theme="volatility")

        message = str(refusal.value)
        assert "'volatility'" in message
        assert f"{HELD_ROOT!r}" in message and f"{RETAINED_ROOT!r}" in message
        assert "not one the pool carries" in message

    @pytest.mark.parametrize("theme", ["", "   ", None, 42, b"hpo"])
    def test_a_theme_that_names_no_root_is_refused(self, theme):
        """Holding a family out starts by naming the family."""
        with pytest.raises(TransferRequestError) as refusal:
            leave_one_family_out(_families(held=4, retained=20), theme=theme)

        assert "non-empty" in str(refusal.value)

    def test_the_transfer_call_refuses_the_unknown_root_before_the_floor(self):
        """Ask facts first: an unknown root is refused even over a thin pool."""
        families = _families(held=5, retained=19)  # thin once held out

        with pytest.raises(TransferRequestError):
            family_transfer(
                *_arms(families), themes=families, theme="volatility"
            )


class TestTheAsksOwnFacts:
    """A malformed ask is refused as the ask's own fault, before any judgement."""

    @pytest.mark.parametrize(
        "themes",
        [
            "hpo",
            b"hpo",
            ["hpo"] * 24,
            42,
            None,
        ],
    )
    def test_a_census_that_is_not_a_mapping_is_refused(self, themes):
        """One refusal for the seam's whole shape, and the dangerous case named.

        A bare string is refused explicitly because Python would iterate its
        *characters* — a pool handed as one world's id would silently become
        as many one-character worlds as it has letters, and nothing in the
        partition would look wrong.
        """
        with pytest.raises(TransferRequestError) as refusal:
            leave_one_family_out(themes, theme=HELD_ROOT)

        assert "mapping" in str(refusal.value)

    @pytest.mark.parametrize(
        "entry",
        [
            {"": RETAINED_ROOT},
            {42: RETAINED_ROOT},
            {"world-990": " "},
            {"world-990": 7},
        ],
    )
    def test_a_census_keyed_by_no_world_or_rooted_in_no_theme_is_refused(
        self, entry
    ):
        """A world is named by non-empty text; so is the root it carries.

        A blank key would leave a world in no family, and a non-text root is
        no theme the world belongs to — both invisible to the very claim
        *"held out of the pool"* the partition exists to make true.
        """
        families = _families(held=4, retained=20)
        families.update(entry)

        with pytest.raises(TransferRequestError) as refusal:
            leave_one_family_out(families, theme=HELD_ROOT)

        assert "non-empty" in str(refusal.value)

    @pytest.mark.parametrize("arm", ["0.1", b"0.1", ["0.1"], 42, None])
    def test_an_arm_that_is_not_world_keyed_readings_is_refused(self, arm):
        """Shape only — the figures themselves are feature 281's to judge."""
        families = _families(held=4, retained=20)

        with pytest.raises(TransferRequestError) as refusal:
            family_transfer(arm, {}, themes=families, theme=HELD_ROOT)

        assert "readings" in str(refusal.value)

    def test_the_arm_shape_is_refused_before_the_floor(self):
        """The ask's own facts, refused before any judgement runs."""
        families = _families(held=5, retained=19)  # thin once held out

        with pytest.raises(TransferRequestError):
            family_transfer("readings", {}, themes=families, theme=HELD_ROOT)


class TestTheDelegatedLaws:
    """Everything about the readings stays feature 281's — never re-spelled."""

    def test_a_family_world_only_one_arm_carries_is_refused_by_the_pairing(self):
        """The unpaired case, inside the family — feature 281's word.

        Dropping the world would silently convert the comparison into the
        unpaired one §11.0 rejects; the refusal comes from the pairing's own
        law, in the pairing's own vocabulary, because this module mints no
        second pairing rule.
        """
        families = _families(held=4, retained=20)
        candidate, baseline = _arms(families)
        del baseline["world-002"]

        with pytest.raises(PairedComparisonError) as refusal:
            family_transfer(candidate, baseline, themes=families, theme=HELD_ROOT)

        message = str(refusal.value)
        assert message.startswith(PAIRED_CODE)
        assert "world-002" in message
        assert "carry both" in message

    def test_a_family_of_one_world_is_refused_for_having_no_spread(self):
        """One difference has no deviation — the statistic's own refusal."""
        families = _families(held=1, retained=20)
        candidate, baseline = _arms(families)

        with pytest.raises(PairedComparisonError) as refusal:
            family_transfer(candidate, baseline, themes=families, theme=HELD_ROOT)

        assert "at least two worlds" in str(refusal.value)

    def test_a_non_finite_reading_on_a_family_world_is_the_statistics_refusal(self):
        """A NaN compares false against everything; the figure law names it."""
        families = _families(held=4, retained=20)
        candidate, baseline = _arms(families)
        candidate["world-001"] = float("nan")

        with pytest.raises(PairedComparisonError) as refusal:
            family_transfer(candidate, baseline, themes=families, theme=HELD_ROOT)

        assert str(refusal.value).startswith(PAIRED_CODE)

    def test_a_family_world_neither_arm_carries_is_not_in_the_comparison(self):
        """The overlap law, operating: the statistic runs on the shared worlds.

        Deliberately *not* a second refusal spelled here — which worlds ground
        the comparison is feature 281's law, and the record states the truth
        in its own ``paired_worlds`` figure, which is what a caller auditing
        the figure reads.
        """
        families = _families(held=4, retained=20)
        candidate, baseline = _arms(families)
        del candidate["world-003"]
        del baseline["world-003"]

        transfer = family_transfer(candidate, baseline, themes=families, theme=HELD_ROOT)

        assert transfer.difference.paired_worlds == 3
        assert len(transfer.held_out) == 4  # the family is still the family

    def test_the_capacity_keywords_pass_straight_through(self):
        """``spread``/``delta``/``power`` are the paired statistic's own.

        Pinned in both directions: a supplied spread sizes the power check
        without replacing the measured one (the record carries what these
        worlds produced), and a spread that cannot size a comparison is
        refused in the comparison's vocabulary — never a second capacity
        arithmetic minted here that could disagree with feature 281's.
        """
        families = _families(held=4, retained=20)
        candidate, baseline = _arms(families)

        transfer = family_transfer(
            candidate,
            baseline,
            themes=families,
            theme=HELD_ROOT,
            spread=0.8,
            delta=0.3,
        )

        differences = [
            candidate[world] - baseline[world]
            for world, root in families.items()
            if root == HELD_ROOT
        ]
        assert transfer.difference.spread == pytest.approx(statistics.stdev(differences))
        assert transfer.difference.spread != 0.8

        for bad in (0.0, -1.0, float("nan")):
            with pytest.raises(PairedComparisonError):
                family_transfer(
                    candidate, baseline, themes=families, theme=HELD_ROOT, spread=bad
                )


class TestTheStoreSeam:
    """``pooled_family_transfer`` — the transfer read from the pool's own rows."""

    def test_the_arms_are_read_from_replay_score_and_restricted_to_the_family(
        self, pool, monkeypatch
    ):
        """§11.1's call over the store: two named arms, one held-out root.

        The figure agrees with the arithmetic computed independently from the
        rows this test wrote, over exactly the family's worlds — the read is
        the same one feature 281's store seam makes, restricted by the census
        handed in.
        """
        families = _families(held=4, retained=20)
        candidate, baseline = _arms(families)
        _write_arm(pool, "pi-0", baseline)
        _write_arm(pool, "pi-1", candidate)
        monkeypatch.setenv(DATABASE_URL_ENV, pool)

        transfer = pooled_family_transfer(
            "pi-1", "pi-0", themes=families, theme=HELD_ROOT
        )

        held = [world for world, root in families.items() if root == HELD_ROOT]
        differences = [candidate[world] - baseline[world] for world in held]
        assert transfer.delta_ir == pytest.approx(statistics.fmean(differences))
        assert transfer.held_out == tuple(sorted(held))
        assert transfer.retained_worlds == 20
        assert transfer.difference.paired_worlds == 4

    def test_the_transfer_writes_nothing(self, pool, monkeypatch):
        """Feature 270 holds the pool fixed; a transfer that wrote would be the mutation.

        Asserted by counting rows before and after over a pool that already
        has rows, so an insert of any kind would show.
        """
        families = _families(held=4, retained=20)
        candidate, baseline = _arms(families)
        _write_arm(pool, "pi-0", baseline)
        _write_arm(pool, "pi-1", candidate)
        monkeypatch.setenv(DATABASE_URL_ENV, pool)
        before = _pool_rows(pool)

        pooled_family_transfer("pi-1", "pi-0", themes=families, theme=HELD_ROOT)

        assert _pool_rows(pool) == before == 48

    def test_the_transfer_runs_over_a_held_pool(self, pool, monkeypatch):
        """A transfer is a *read*, so feature 270's hold does not refuse it.

        §C5 holds the pool fixed for the whole outer iteration and the
        standing metric is what the iteration computes during it.  The hold is
        verified after the read, and a write is still refused, so the read was
        not permitted by the guards having been taken down.
        """
        families = _families(held=4, retained=20)
        candidate, baseline = _arms(families)
        _write_arm(pool, "pi-0", baseline)
        _write_arm(pool, "pi-1", candidate)
        monkeypatch.setenv(DATABASE_URL_ENV, pool)

        freeze = CycleFreeze(pool)
        hold = freeze.open("cycle-1")

        transfer = pooled_family_transfer(
            "pi-1", "pi-0", themes=families, theme=HELD_ROOT
        )

        assert transfer.delta_ir == pytest.approx(
            statistics.fmean(
                [
                    candidate[world] - baseline[world]
                    for world, root in families.items()
                    if root == HELD_ROOT
                ]
            )
        )
        assert freeze.held()
        assert freeze.verify(hold)
        with pytest.raises(PoolFrozenError):
            freeze.guard(
                "INSERT INTO replay_score (id, policy_version, world_id, beta, "
                "score, is_holdout) VALUES ('x', 'pi-2', 'w-a', 0.0, 0.0, 0)"
            )

    def test_the_env_mapping_names_the_database(self, pool):
        """``env`` is honoured the way the split's and the comparison's seams honour it.

        A caller that holds its own view of the deployment's variables — a
        request, a job spec — names the database through it, without
        monkeypatching the process.
        """
        families = _families(held=4, retained=20)
        candidate, baseline = _arms(families)
        _write_arm(pool, "pi-0", baseline)
        _write_arm(pool, "pi-1", candidate)

        transfer = pooled_family_transfer(
            "pi-1",
            "pi-0",
            themes=families,
            theme=HELD_ROOT,
            env={DATABASE_URL_ENV: pool},
        )

        assert transfer.difference.paired_worlds == 4

    def test_no_database_named_is_refused(self, monkeypatch):
        """An act that means to read the pool and resolves nothing is refused by name.

        Not answered with ``None``: a delta reported over no database would be
        a figure on worlds that were never read, and it would look exactly
        like one that had been.
        """
        monkeypatch.delenv(DATABASE_URL_ENV, raising=False)

        with pytest.raises(TransferRequestError) as refusal:
            pooled_family_transfer(
                "pi-1",
                "pi-0",
                themes=_families(held=4, retained=20),
                theme=HELD_ROOT,
                env={},
            )

        assert DATABASE_URL_ENV in str(refusal.value)

    def test_a_url_the_member_cannot_speak_is_refused_in_this_modules_vocabulary(
        self, pool, monkeypatch
    ):
        """Translated at the seam — never feature 270's ``FreezeRequestError``.

        The seam discipline the whole workspace states for error
        vocabularies: a caller taking a transfer must not meet *your hold was
        malformed* about an act that held nothing.  Pinned by asserting the
        class, since the message quotes the freeze's refusal on purpose.
        """
        monkeypatch.setenv(DATABASE_URL_ENV, pool)

        with pytest.raises(TransferRequestError) as refusal:
            pooled_family_transfer(
                "pi-1",
                "pi-0",
                themes=_families(held=4, retained=20),
                theme=HELD_ROOT,
                database_url="postgresql://h/db",
            )

        assert not isinstance(refusal.value, FreezeRequestError)

    def test_a_database_with_no_pool_is_refused(self, database_url, monkeypatch):
        """No pool tables means no pool to hold a family out of.

        Translated from the membership read's own refusal into this module's
        store class — never re-raised as the split's, because a caller taking
        a transfer must not meet a split's vocabulary for it.
        """
        monkeypatch.setenv(DATABASE_URL_ENV, database_url)

        with pytest.raises(TransferStoreError) as refusal:
            pooled_family_transfer(
                "pi-1",
                "pi-0",
                themes=_families(held=4, retained=20),
                theme=HELD_ROOT,
            )

        message = str(refusal.value)
        assert "no pool" in message
        assert not isinstance(refusal.value, SplitStoreError)

    def test_a_census_that_misses_pool_worlds_is_refused(self, pool, monkeypatch):
        """Worlds in no family are invisible to the partition — refused, named.

        A census that misses pool worlds would leave them free to sit under a
        selection that believed their family was gone, which is the
        family-shaped leak this seam exists to prevent.
        """
        families = _families(held=4, retained=20)
        candidate, baseline = _arms(families)
        _write_arm(pool, "pi-0", baseline)
        _write_arm(pool, "pi-1", candidate)
        monkeypatch.setenv(DATABASE_URL_ENV, pool)
        short = dict(families)
        del short["world-010"]

        with pytest.raises(TransferStoreError) as refusal:
            pooled_family_transfer("pi-1", "pi-0", themes=short, theme=HELD_ROOT)

        assert "does not name" in str(refusal.value)
        assert "'world-010'" in str(refusal.value)

    def test_a_census_that_names_phantom_worlds_is_refused(self, pool, monkeypatch):
        """Worlds the store does not hold ground no figure — refused, named."""
        families = _families(held=4, retained=20)
        candidate, baseline = _arms(families)
        _write_arm(pool, "pi-0", baseline)
        _write_arm(pool, "pi-1", candidate)
        monkeypatch.setenv(DATABASE_URL_ENV, pool)
        padded = dict(families)
        padded["world-990"] = RETAINED_ROOT

        with pytest.raises(TransferStoreError) as refusal:
            pooled_family_transfer("pi-1", "pi-0", themes=padded, theme=HELD_ROOT)

        message = str(refusal.value)
        assert "does not hold" in message
        assert "'world-990'" in message

    def test_the_census_is_checked_before_the_arms_are_read(self, pool, monkeypatch):
        """The disagreement is the store's fact, so it is the refusal that lands.

        A pool whose census is stale *and* whose arms fail to pair is refused
        for the census: the caller's repair is to re-read the pool's families,
        and being told about a pairing failure instead would send it to the
        statistic with a census that is still wrong.
        """
        families = _families(held=4, retained=20)
        candidate, baseline = _arms(families)
        del baseline["world-002"]  # an unpaired family world, waiting behind
        _write_arm(pool, "pi-0", baseline)
        _write_arm(pool, "pi-1", candidate)
        monkeypatch.setenv(DATABASE_URL_ENV, pool)
        short = dict(families)
        del short["world-010"]

        with pytest.raises(TransferStoreError) as refusal:
            pooled_family_transfer("pi-1", "pi-0", themes=short, theme=HELD_ROOT)

        assert "does not name" in str(refusal.value)

    def test_the_census_must_cover_the_whole_union_not_just_the_score_worlds(
        self, scores, monkeypatch
    ):
        """The membership law here is the split's: both halves of the pool.

        ``pool_worlds`` unions ``bootstrap_world`` with ``replay_score``'s
        distinct worlds, so a census naming only the worlds the arms were
        replayed against misses every authored-but-unreplayed world — and is
        refused.  Pinned over the ``scores`` fixture, whose three
        ``bootstrap_world`` rows are exactly such worlds.  The short census
        still carries the held-out root (the ask's own facts are checked
        before the store), so the refusal that lands is the store's.
        """
        url, _ = scores
        financial = {
            f"world-fin-{index:02d}": RETAINED_ROOT for index in range(21)
        }
        authored = {
            "world-aaa": HELD_ROOT,
            "world-bbb": HELD_ROOT,
            "world-ccc": HELD_ROOT,
        }
        _write_arm(url, "pi-0", {world: 0.1 + 0.01 * i for i, world in enumerate(financial)})
        _write_arm(url, "pi-1", {world: 0.4 + 0.01 * i for i, world in enumerate(financial)})
        _write_arm(url, "pi-0", {"world-aaa": 0.1, "world-bbb": 0.2, "world-ccc": 0.3})
        _write_arm(url, "pi-1", {"world-aaa": 0.4, "world-bbb": 0.55, "world-ccc": 0.6})
        monkeypatch.setenv(DATABASE_URL_ENV, url)

        with pytest.raises(TransferStoreError) as refusal:
            pooled_family_transfer(
                "pi-1", "pi-0", themes={**financial, "world-aaa": HELD_ROOT}, theme=HELD_ROOT
            )

        assert "'world-bbb'" in str(refusal.value)

        transfer = pooled_family_transfer(
            "pi-1",
            "pi-0",
            themes={**financial, **authored},
            theme=HELD_ROOT,
        )

        # The authored worlds are the held-out family, and the fixture's own
        # pi-0 rows are overridden by the later-id rows this test wrote.
        assert transfer.held_out == ("world-aaa", "world-bbb", "world-ccc")
        assert transfer.retained_worlds == 21
        assert transfer.delta_ir == pytest.approx((0.30 + 0.35 + 0.30) / 3)

    def test_a_policy_transferred_against_itself_is_refused(self, pool, monkeypatch):
        """Every difference exactly zero — refused before any database is opened."""
        monkeypatch.setenv(DATABASE_URL_ENV, pool)

        with pytest.raises(TransferRequestError) as refusal:
            pooled_family_transfer(
                "pi-0",
                "pi-0",
                themes=_families(held=4, retained=20),
                theme=HELD_ROOT,
                env={},
            )

        assert "on both sides" in str(refusal.value)

    @pytest.mark.parametrize("version", ["", "   ", None, 42, b"pi-0"])
    def test_a_malformed_policy_version_is_refused(self, pool, monkeypatch, version):
        """An arm named by nothing names no arm to transfer against."""
        monkeypatch.setenv(DATABASE_URL_ENV, pool)

        with pytest.raises(TransferRequestError):
            pooled_family_transfer(
                version,
                "pi-0",
                themes=_families(held=4, retained=20),
                theme=HELD_ROOT,
                env={},
            )

    def test_a_family_world_only_one_arm_was_replayed_against_is_refused(
        self, pool, monkeypatch
    ):
        """The delegated pairing law, reached through the store.

        The state a partially-replayed pool is in, refused by the statistic
        that knows what pairing means — in its own word, exactly as the pure
        seam refuses it.
        """
        families = _families(held=4, retained=20)
        candidate, baseline = _arms(families)
        del baseline["world-002"]
        _write_arm(pool, "pi-0", baseline)
        _write_arm(pool, "pi-1", candidate)
        monkeypatch.setenv(DATABASE_URL_ENV, pool)

        with pytest.raises(PairedComparisonError) as refusal:
            pooled_family_transfer("pi-1", "pi-0", themes=families, theme=HELD_ROOT)

        assert str(refusal.value).startswith(PAIRED_CODE)
        assert "world-002" in str(refusal.value)


class TestTheVocabulary:
    """Feature 282's two classes, and the line between them and their neighbours."""

    def test_both_classes_share_the_member_base(self):
        """One member, one base — the workspace's per-member rule."""
        for refusal in (TransferRequestError, TransferStoreError):
            assert issubclass(refusal, DreamingError)
        assert issubclass(DreamingError, Exception)

    def test_the_two_classes_are_siblings(self):
        """*Your census was wrong* is not *your store holds nothing*.

        The repairs differ — re-consider the ask, against point at the
        database the replay pool lives in — so a caller that must react
        differently must be able to catch them apart.
        """
        assert not issubclass(TransferRequestError, TransferStoreError)
        assert not issubclass(TransferStoreError, TransferRequestError)

    def test_the_classes_are_siblings_of_every_existing_class(self):
        """A caller catches a transfer's refusal without catching anyone else's."""
        for refusal in (TransferRequestError, TransferStoreError):
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
            ):
                assert not issubclass(refusal, sibling), sibling
                assert not issubclass(sibling, refusal), sibling

    def test_no_refusal_mints_a_code_word_this_member_already_carries(self):
        """Feature 282's verb is *computes*, so the refusal opens with its subject.

        The one vocabulary this module never borrows is the thin pool's and
        the freeze's: the floor is delegated in the floor's own word, and a
        transfer never held anything.
        """
        with pytest.raises(TransferRequestError) as refusal:
            leave_one_family_out("hpo", theme=HELD_ROOT)

        message = str(refusal.value)
        assert POOL_TOO_THIN_CODE not in message
        assert FREEZE_CODE not in message
        assert not message.startswith(POOL_TOO_THIN_CODE)

    def test_the_module_is_reachable_from_the_member(self):
        """The feature's surface is the member's, as the ladder's other rungs are."""
        import dreaming

        for name in (
            "FamilyPartition",
            "FamilyTransfer",
            "TransferRequestError",
            "TransferStoreError",
            "family_transfer",
            "leave_one_family_out",
            "pooled_family_transfer",
        ):
            assert name in dreaming.__all__, name
            assert hasattr(dreaming, name), name

    def test_the_module_is_stdlib_only_and_imports_no_member(self):
        """The transfer is stdlib-only, and the member imports no sibling.

        The factory's scan imports this package to fire its ``@register``, so
        a module-scope third-party import would make composition pay for a
        feature it is not using — the restraint every rung of this member's
        ladder states for its own module.
        """
        import sys

        import dreaming.transfer as module

        source = Path(module.__file__).read_text()
        for forbidden in (
            "import numpy",
            "import scipy",
            "import pandas",
            "from bootstrap",
            "from app",
        ):
            assert forbidden not in source, forbidden
        assert sys.modules["dreaming.transfer"] is module


def _reversed_arms(
    families: dict[str, str],
) -> tuple[dict[str, float], dict[str, float]]:
    """The fixture's arms with the gain subtracted — a family that reads worse."""
    candidate, baseline = _arms(families)
    return baseline, candidate


def _flat_families() -> dict[str, str]:
    """A census whose held-out family reads exactly level between the arms."""
    return _families(held=4, retained=20)


def _flat_arms() -> tuple[dict[str, float], dict[str, float]]:
    """Arms whose held-out family differences average zero — the flat case.

    §11's bar is strict (``> 0``), so a delta of exactly zero must read as
    *no transfer*, and this is the fixture that makes the boundary testable:
    differences of ``+0.1, −0.1, +0.3, −0.3`` over the family's worlds.  The
    retained worlds carry readings too — deliberately identical between the
    arms, so the test also shows they cannot move a figure they are not in.
    """
    families = _flat_families()
    retained = sorted(
        world for world, root in families.items() if root == RETAINED_ROOT
    )
    level = {world: 0.2 + 0.01 * index for index, world in enumerate(retained)}
    candidate = {
        "world-000": 0.5,
        "world-001": 0.3,
        "world-002": 0.7,
        "world-003": 0.1,
        **level,
    }
    baseline = {"world-000": 0.4, "world-001": 0.4, "world-002": 0.4, "world-003": 0.4, **level}
    return candidate, baseline


def _arm_pairs(families: dict[str, str]) -> list[tuple[float, float]]:
    """The held-out family's per-world (candidate, baseline) pairs, sorted."""
    candidate, baseline = _arms(families)
    held = sorted(
        world for world, root in families.items() if root == HELD_ROOT
    )
    return [(candidate[world], baseline[world]) for world in held]


def _write_arm(
    url: str,
    policy_version: str,
    readings: dict[str, float],
    *,
    order: int = 0,
    prefix: str = "z",
) -> None:
    """Write one arm's score rows into a pool, through ``0109``'s columns.

    The rows are written the way the owner declares them — the eight columns
    :data:`dreaming.REPLAY_SCORE_COLUMNS` restates.  ``order`` is a
    zero-padded infix on the score id and ``prefix`` sorts it past any rows a
    fixture wrote before: ``0109``'s id is a UUID in production, so id order
    and write order are unrelated, and a test that must override a fixture's
    reading does it by sorting after it, not by writing later.
    """
    with closing(sqlite3.connect(sqlite_path(url))) as connection, connection:
        for world_id, score in readings.items():
            connection.execute(
                "INSERT INTO replay_score (id, policy_version, world_id, beta, "
                "score, committed_pick, is_holdout, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"{prefix}{order:04d}-score-{policy_version}-{world_id}",
                    policy_version,
                    world_id,
                    0.0,
                    score,
                    None,
                    0,
                    "2026-01-01T00:00:00Z",
                ),
            )


def _pool_rows(url: str) -> int:
    """How many rows the pool's score table holds — the write-detection probe."""
    with closing(sqlite3.connect(sqlite_path(url))) as connection:
        return connection.execute("SELECT COUNT(*) FROM replay_score").fetchone()[0]


def test_the_pool_fixture_exists(pool):
    """The pool this suite transfers over is a real one.

    A guard against the whole store class silently skipping: the same guard
    ``test_paired.py`` states for its own seam, restated here because this
    file's store class leans on the same fixture.
    """
    assert sqlite_path(pool).exists()
    assert pool_bootstrap_schema().count("CREATE TABLE") == 2
    assert _pool_rows(pool) == 0
