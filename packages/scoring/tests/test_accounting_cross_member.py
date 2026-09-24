"""The cross-member seam feature 269 restates — the §7.2 Type-D boundary
and the oracle's own resolution record, pinned against the real null
oracle, not a stand-in.

The workspace contract is that **no member imports another**, and the
error accounting meets it the way every shared spelling is met: the
boundary (``depth >= flip_depth``) is restated in this member's own
vocabulary — never imported — and the explored seam is duck-typed by the
three facts it reads (``node_id``, ``depth``, ``flip_depth``), which are
the shape the oracle's own :class:`~nulloracle.TypeDResolution` carries.
A suite like this one is what keeps both restatements honest
(``packages/scoring/tests/test_scorer_cross_member.py`` states the
discipline for feature 265's sidecar seam; the in-function import that
costs one test when a sibling is absent rather than the collection of
the whole suite is that file's remedy too, and this one's).

What this file pins, from the oracle's side:

* **the boundary, spelling for spelling** — :func:`account_errors`'s
  count agrees with the oracle's own ``past_the_flip`` over the whole
  grid of depths and flips, §7.2's *"at or beyond it the permuted ones"*
  inclusive — the node at the flip counted, the node below it not, a
  root never;
* **the supports** — the flips and depths the oracle's own predicate
  refuses are the ones this seam refuses, so the two spellings cannot
  drift apart in what they will even read;
* **the resolution record satisfies the seam** — a real
  ``TypeDResolution``, constructed by the oracle's own validated
  constructor, is a legal explored node with no adapter: the accounting
  reads its three facts and never its branch or its series, and the
  count over a below/at/beyond triple is 2 exactly;
* **the two halves compose** — real resolutions in the explored
  collection beside feature 265's real process over the stand-in
  sidecar, one ask answering both metrics.

Why the imports are inside the tests: a module-scope ``import
nulloracle`` would make this member's suite fail to collect wherever the
sibling member is absent, which is the outcome the contract's remedy
exists to avoid.  In a function, the absence costs one test, and that
test says what is missing.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest
from conftest import (  # type: ignore[import-not-found] - suite-local
    AT_FLIP,
    BELOW_ONE,
    BEYOND_FLIP,
    FLIP_DEPTH,
    StandInSidecar,
)
from scoring import ErrorAccountingError, NullPickScorer, account_errors

REPO_ROOT = Path(__file__).resolve().parents[3]
NULLORACLE_SRC = REPO_ROOT / "packages" / "nulloracle" / "src"

#: The grid the boundary is pinned over: every depth 0 through 6 against
#: every flip 1 through 5 — 35 cells, spanning §7.2's whole boundary
#: (a root at depth 0 never past a drawn flip, the node at the flip
#: past, the nodes below it not) and the geometric's realistic draws.
_GRID_DEPTHS = range(7)
_GRID_FLIPS = range(1, 6)


def _nulloracle():
    """The null oracle member, imported in-function.

    ``importorskip`` rather than a bare import: a workspace without the
    sibling should lose this suite's tests and nothing else.
    """
    if str(NULLORACLE_SRC) not in sys.path:
        sys.path.insert(0, str(NULLORACLE_SRC))
    return pytest.importorskip(
        "nulloracle", reason="the null oracle member is not in this workspace"
    )


def _grid_node(depth: int, flip: int):
    """One grid cell as a narrow three-fact node, deterministically named.

    ``uuid5`` so the names are stable across runs — a pinned seam should
    not answer to a different campaign every time it is asked.
    """
    return type(
        "Cell",
        (),
        {
            "node_id": str(
                uuid.uuid5(uuid.NAMESPACE_URL, f"feature-269/grid/{depth}/{flip}")
            ),
            "depth": depth,
            "flip_depth": flip,
        },
    )()


def test_the_boundary_agrees_with_the_oracle_s_own_predicate(
    sidecar_labels: dict[str, bool], committed_picks
) -> None:
    # The restatement is checked against the law it restates, over the
    # whole grid: one ask carrying all 35 cells, whose Type-B count must
    # equal the number of cells the oracle's own predicate calls past the
    # flip — inclusive at the flip, exclusive below it, and a root (depth
    # 0) never past a drawn flip, which is how "every root stays real"
    # reads from the accounting's side.
    nulloracle = _nulloracle()
    cells = [(d, f) for d in _GRID_DEPTHS for f in _GRID_FLIPS]
    verdicts = [nulloracle.past_the_flip(d, f) for d, f in cells]
    accounting = account_errors(
        committed_picks,
        explored=[_grid_node(d, f) for d, f in cells],
        scorer=NullPickScorer(StandInSidecar(sidecar_labels)),
    )
    assert accounting.depth_past_flip_errors == sum(verdicts)
    # And the two boundary sentences the grid spans, one node at a time:
    # the node at exactly the flip is the first null node of the branch,
    # the node one below it the last real one.
    at = account_errors(
        committed_picks,
        explored=[_grid_node(FLIP_DEPTH, FLIP_DEPTH)],
        scorer=NullPickScorer(StandInSidecar(sidecar_labels)),
    )
    below = account_errors(
        committed_picks,
        explored=[_grid_node(FLIP_DEPTH - 1, FLIP_DEPTH)],
        scorer=NullPickScorer(StandInSidecar(sidecar_labels)),
    )
    assert at.depth_past_flip_errors == 1
    assert below.depth_past_flip_errors == 0


def test_the_seam_refuses_what_the_oracle_s_predicate_refuses(
    sidecar_labels: dict[str, bool], committed_picks
) -> None:
    # Two spellings of one boundary must also be two spellings of one
    # *support*: the oracle's own predicate refuses a depth that is not
    # a non-negative integer and a flip that is not an integer >= 1, and
    # the accounting's seam refuses the same values — so a corrupted 0
    # in the join cannot quietly cross every root here any more than it
    # can there.  The vocabularies differ (KsGuardError against
    # ErrorAccountingError, each member its own); the refusals agree.
    nulloracle = _nulloracle()
    for bad_depth in (-1, 2.5, True):
        node = _grid_node(1, 3)
        node.depth = bad_depth
        with pytest.raises(nulloracle.KsGuardError):
            nulloracle.past_the_flip(bad_depth, 3)
        with pytest.raises(ErrorAccountingError):
            account_errors(
                committed_picks,
                explored=[node],
                scorer=NullPickScorer(StandInSidecar(sidecar_labels)),
            )
    for bad_flip in (0, -2, True):
        node = _grid_node(1, 3)
        node.flip_depth = bad_flip
        with pytest.raises(nulloracle.KsGuardError):
            nulloracle.past_the_flip(1, bad_flip)
        with pytest.raises(ErrorAccountingError):
            account_errors(
                committed_picks,
                explored=[node],
                scorer=NullPickScorer(StandInSidecar(sidecar_labels)),
            )


def test_the_real_resolution_record_satisfies_the_seam(
    sidecar_labels: dict[str, bool], committed_picks
) -> None:
    # The oracle-side record of a resolved Type-D request — constructed
    # by the oracle's own validated constructor, carrying five fields —
    # is a legal explored node with no adapter: the seam reads its three
    # facts and never its branch bit or its served series.  The count
    # over a below/at/beyond triple is 2 exactly, and each record's own
    # ``real`` bit is the complement of this seam's verdict, which is
    # §7.2's one boundary seen from its two sides.
    nulloracle = _nulloracle()
    series = (0.010, -0.020, 0.005)
    below = nulloracle.TypeDResolution(
        node_id=BELOW_ONE, depth=1, flip_depth=FLIP_DEPTH, real=True, targets=series
    )
    at = nulloracle.TypeDResolution(
        node_id=AT_FLIP,
        depth=FLIP_DEPTH,
        flip_depth=FLIP_DEPTH,
        real=False,
        targets=series,
    )
    beyond = nulloracle.TypeDResolution(
        node_id=BEYOND_FLIP, depth=5, flip_depth=FLIP_DEPTH, real=False, targets=series
    )
    assert below.real is True and at.real is False and beyond.real is False
    accounting = account_errors(
        committed_picks,
        explored=[below, at, beyond],
        scorer=NullPickScorer(StandInSidecar(sidecar_labels)),
    )
    assert accounting.depth_past_flip_errors == 2
    # The coherence the oracle's constructor enforces is the complement
    # of the verdict this seam counts on — one boundary, two members.
    for record, past in ((below, False), (at, True), (beyond, True)):
        assert record.real != past


def test_the_two_halves_compose_over_the_real_shapes(
    sidecar_labels: dict[str, bool], committed_picks
) -> None:
    # End to end, one ask, both metrics: real Type-D resolution records
    # in the explored collection beside the real scorer process over the
    # stand-in sidecar — Type-A's rate answered inside the process from
    # the labels only it reads (0.5 exactly), Type-B's count answered
    # from the depths the oracle already joined (2 exactly), and the
    # sidecar's read log holds the four picks and never an explored
    # node: the barrier's two grants, held by one composition.
    nulloracle = _nulloracle()
    series = (0.010, -0.020, 0.005)
    sidecar = StandInSidecar(sidecar_labels)
    accounting = account_errors(
        committed_picks,
        explored=[
            nulloracle.TypeDResolution(
                node_id=BELOW_ONE, depth=2, flip_depth=FLIP_DEPTH,
                real=True, targets=series,
            ),
            nulloracle.TypeDResolution(
                node_id=AT_FLIP, depth=FLIP_DEPTH, flip_depth=FLIP_DEPTH,
                real=False, targets=series,
            ),
            nulloracle.TypeDResolution(
                node_id=BEYOND_FLIP, depth=FLIP_DEPTH + 1, flip_depth=FLIP_DEPTH,
                real=False, targets=series,
            ),
        ],
        scorer=NullPickScorer(sidecar),
    )
    assert accounting.commitment_error_rate == 0.5
    assert accounting.depth_past_flip_errors == 2
    assert sorted(sidecar.reads) == sorted(sidecar_labels)
