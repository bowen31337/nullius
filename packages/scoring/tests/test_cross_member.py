"""The cross-member seam this feature closes — pinned against the real
census, not a stand-in.

The workspace contract is that **no member imports another**.  It is met
with the same remedy everywhere a spelling has to be shared: the spelling
is *restated* in the member that needs it, and a suite like this one is
what keeps the restatement honest (``packages/regime/tests/
test_cross_member.py`` states the discipline for that member's own two
seams; the in-function import that costs one test when a sibling is absent
rather than the collection of the whole suite is that file's remedy too).

Feature 264 is the seam where the two members' halves of prd §7.2 finally
meet, and it is worth stating exactly which side owns what, because the
split is not obvious:

* **the regime member** (feature 290, :func:`regime.census.assign_strata`)
  owns *which stratum a world is in*.  It walks the pool, asks a causal
  rolling-window labeler for each world's closing label, checks the answer
  against the label space, and answers one ``world_id``/``stratum`` row
  per world — a :class:`~regime.StratumAssignment`.
* **this member** (feature 264, :func:`scoring.regime_strata`) owns *the
  join that turns those rows plus a set of scores into the strata feature
  263 blends over*, and the refusal of every ask whose arithmetic would
  average across regimes instead.

Neither imports the other.  So what this file pins, from the data side, is
that the **real** census output satisfies the surface
:func:`scoring.regime_strata` duck-reads: that a real
:class:`~regime.StratumAssignment` carries the two attributes the join
needs and needs nothing else, that the strata the census assigns come out
as the index's keys with the right worlds in each, and — decisively — that
the pipeline runs end to end from raw regime rows to a blended scalar,
which is the number feature 274's argmax will rank on.

Why the imports are inside the tests: a module-scope ``import regime``
would make this member's suite fail to collect wherever the sibling member
is absent, which is the outcome the contract's remedy exists to avoid.  In
a function, the absence costs one test, and that test says what is
missing.  The path insert is the same bootstrap every member suite
performs for *itself*, applied to a sibling, because the member suites are
not installed into each other's environments.
"""

from __future__ import annotations

import random
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from conftest import StandInScore  # type: ignore[import-not-found] - suite-local
from scoring import PLAIN_MEAN_CODE, RegimeIndexError, regime_aggregate, regime_strata

REPO_ROOT = Path(__file__).resolve().parents[3]
REGIME_SRC = REPO_ROOT / "packages" / "regime" / "src"
FEATURE_STORE_SRC = REPO_ROOT / "packages" / "feature-store" / "src"

#: The three names the regime member's ledger counts and feature 58's
#: labeler carves for — restated here, never imported, and passed to the
#: census rather than read off it.  The count is what the two members
#: agree on (``packages/regime/tests/test_cross_member.py`` pins that);
#: the names are the ledger's vocabulary and this suite spells them so the
#: declaration a deployment would make is exercised for real.
DEFAULT_STRATA = ("high-volatility trend", "low-volatility chop", "crash")


def _census():
    """The regime member's census module, imported in-function.

    ``importorskip`` rather than a bare import: a workspace without the
    sibling should lose this test and nothing else.
    """
    if str(REGIME_SRC) not in sys.path:
        sys.path.insert(0, str(REGIME_SRC))
    regime = pytest.importorskip(
        "regime", reason="the regime member is not in this workspace"
    )
    return pytest.importorskip(
        f"{regime.__name__}.census",
        reason="the census module is not where its member keeps it",
    )


def _labeler():
    """Feature 58's labeler — the *real* one the census duck-reads."""
    if str(FEATURE_STORE_SRC) not in sys.path:
        sys.path.insert(0, str(FEATURE_STORE_SRC))
    feature_store = pytest.importorskip(
        "feature_store", reason="the feature-store member is not in this workspace"
    )
    return pytest.importorskip(
        f"{feature_store.__name__}.regime_labeler",
        reason="the labeler module is not where its member keeps it",
    )


@dataclass
class _PanelWorld:
    """A stored world as the census reads it — ``world_id`` and
    ``regime_rows``, the two attributes feature 290's seam documents.

    The same shape ``packages/regime/tests/test_cross_member.py`` states
    for its own drive of the seam: four features wide per dated row, so
    the stand-in exercises the real labeler at its real width without
    pretending to be a price panel.
    """

    world_id: str
    regime_rows: tuple[tuple[float, ...], ...]


def _vol_rows(seed: int, n: int, scale: float) -> tuple[tuple[float, ...], ...]:
    """``n`` dated four-feature rows at a volatility ``scale``.

    Deterministic (a seeded generator, never the module RNG — the
    discipline the labeler's own ``KMEANS_SEED`` states), so the same
    world rides the seam to the same stratum in any order of tests.
    """
    rng = random.Random(seed)
    return tuple(
        tuple(scale * (0.5 + rng.random()) for _ in range(4)) for _ in range(n)
    )


class TestTheIndexRidesTheRealCensus:
    """Feature 264's seam, driven by the census it was written for."""

    def test_the_census_answers_rows_this_index_can_read(self) -> None:
        # The duck-read contract, pinned by name against the real value:
        # the census answers StratumAssignment rows, and this member's
        # join reads exactly ``world_id`` and ``stratum`` off them.  A
        # value that stopped carrying either would be refused by the
        # index, so this is the agreement the whole seam hangs off — and
        # the assertion is on the *real* class the census builds, not on
        # a stand-in this suite made up.
        census = _census()
        labeler = _labeler().RegimeLabeler(k=3, window=10)
        worlds = [
            _PanelWorld("w-calm", _vol_rows(0x101, 40, 0.2)),
            _PanelWorld("w-chop", _vol_rows(0x202, 40, 1.0)),
        ]
        assigned = census.assign_strata(worlds, labeler, strata=DEFAULT_STRATA)
        assert assigned, "the census answered nothing to read"
        for row in assigned:
            assert isinstance(row.world_id, str) and row.world_id.strip()
            assert isinstance(row.stratum, str) and row.stratum.strip()

    def test_the_real_census_rows_index_into_the_strata_it_named(self) -> None:
        # End to end over the member boundary: worlds in, strata out of
        # the real census, scores joined onto them, and each world landing
        # in exactly the regime the census assigned it — the index's keys
        # are the census's own names, and no world is dropped or invented.
        census = _census()
        labeler = _labeler().RegimeLabeler(k=3, window=10)
        worlds = [
            _PanelWorld("w-calm", _vol_rows(0x101, 40, 0.2)),
            _PanelWorld("w-chop", _vol_rows(0x202, 40, 1.0)),
            _PanelWorld("w-crash", _vol_rows(0x303, 40, 4.0)),
        ]
        assigned = census.assign_strata(worlds, labeler, strata=DEFAULT_STRATA)
        scores = [
            StandInScore(row.world_id, 0.75 - 0.25 * index)
            for index, row in enumerate(assigned)
        ]
        index = regime_strata(assigned, scores)
        # Every census row is placed, in the stratum the census named.
        placed = {world.world_id: name for name, group in index.items() for world in group}
        assert placed == {row.world_id: row.stratum for row in assigned}
        assert sum(len(group) for group in index.values()) == len(worlds)

    def test_the_pipeline_blends_a_real_census_output(self) -> None:
        # The composed verb at the seam: raw regime rows in, one blended
        # scalar out — the number docs §10.3's ``V^m`` names and feature
        # 274's argmax will rank candidates on, built here from a real
        # labeler's real strata rather than from hand-grouped fixtures.
        # The checks that matter are the shape ones (every world counted,
        # every stratum the census named, a convex answer), because *which*
        # stratum a seeded k-means puts a world in is the labeler's
        # business and not this feature's.
        #
        # ``strata`` is deliberately left undeclared here.  Three worlds
        # against a k=3 labeler is a *thin* pool, and a thin pool need not
        # land a world in every cluster: the census may name two strata out
        # of three, and declaring the third would earn the §C7 refusal
        # below — correctly, which is exactly why this test does not
        # declare it.  The declaration's own behaviour is pinned by
        # :func:`test_a_declaration_the_census_cannot_fill_is_this_members_refusal`
        # rather than being smuggled into a test about the blend.
        census = _census()
        labeler = _labeler().RegimeLabeler(k=3, window=10)
        worlds = [
            _PanelWorld("w-calm", _vol_rows(0x101, 40, 0.2)),
            _PanelWorld("w-chop", _vol_rows(0x202, 40, 1.0)),
            _PanelWorld("w-crash", _vol_rows(0x303, 40, 4.0)),
        ]
        assigned = census.assign_strata(worlds, labeler, strata=DEFAULT_STRATA)
        scores = [
            StandInScore(row.world_id, 0.75 - 0.25 * index)
            for index, row in enumerate(assigned)
        ]
        blended = regime_aggregate(assigned, scores, lam=0.5)
        assert blended.world_count == len(worlds)
        assert set(blended.stratum_means) <= set(DEFAULT_STRATA)
        assert set(blended.stratum_means) == {row.stratum for row in assigned}
        assert blended.stratum_minimum <= blended.score <= blended.stratum_mean

    def test_a_declaration_the_census_cannot_fill_is_this_members_refusal(
        self,
    ) -> None:
        # The §C7 face, driven with a real census: declare a regime the
        # pool does not cover and the index refuses in **this** member's
        # vocabulary, opening with ``plain_mean`` — never in the census's.
        # That is the two-vocabulary law the regime member's own errors
        # module states from its side, held here from the other: the
        # labels are the census's, the declaration is the caller's, and
        # the refusal of the subset-mean is this feature's to make.
        census = _census()
        labeler = _labeler().RegimeLabeler(k=3, window=10)
        worlds = [_PanelWorld("w-calm", _vol_rows(0x101, 40, 0.2))]
        assigned = census.assign_strata(worlds, labeler, strata=DEFAULT_STRATA)
        scores = [StandInScore(row.world_id, 0.75) for row in assigned]
        covered = {row.stratum for row in assigned}
        missing = [name for name in DEFAULT_STRATA if name not in covered]
        if not missing:  # pragma: no cover - depends on the labeler's clustering
            pytest.skip("one world can cover every stratum only if k-means says so")
        with pytest.raises(RegimeIndexError, match=PLAIN_MEAN_CODE) as refusal:
            regime_strata(assigned, scores, strata=DEFAULT_STRATA)
        assert missing[0] in str(refusal.value)
        # …and the same rows index cleanly with no declaration, which is
        # what makes the refusal the *declaration's* and not the data's.
        assert set(regime_strata(assigned, scores)) == covered

    def test_the_same_labels_and_scores_answer_the_same_index_twice(self) -> None:
        # §12's reproducibility across the member boundary: the census's
        # seeded k-means is the only arithmetic in the labelling path and
        # this member adds none of its own, so the same worlds answer the
        # same strata and the same blend in either order of calls.
        census = _census()
        labeler = _labeler().RegimeLabeler(k=3, window=10)
        worlds = [
            _PanelWorld("w-calm", _vol_rows(0x101, 40, 0.2)),
            _PanelWorld("w-chop", _vol_rows(0x202, 40, 1.0)),
            _PanelWorld("w-crash", _vol_rows(0x303, 40, 4.0)),
        ]
        assigned = census.assign_strata(worlds, labeler, strata=DEFAULT_STRATA)
        scores = [
            StandInScore(row.world_id, 0.5 + 0.25 * index)
            for index, row in enumerate(assigned)
        ]
        first = regime_aggregate(assigned, scores, lam=0.5)
        second = regime_aggregate(list(reversed(assigned)), list(reversed(scores)), lam=0.5)
        assert first == second
