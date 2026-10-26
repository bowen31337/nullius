"""M3b incumbent: the M2 fixed commit rule with two tunable knobs, written against the ``question.*`` contract.

docs/preregistration/2026-10-24-m3b-dreaming-commit-rule.md. The M2 fixed rule
(deploy/dreaming/incumbent.m2.py) commits the evaluated node with the highest
``ic_insample`` (the post-cost IR t-statistic, ``ic_tstat`` where a tree carries no
``ir_tstat``) among the nodes that clear a bar of 2.0, ties by node id. Four archive
series on the wide perpetual universe found that the node this rule commits is the
most in-sample-fitted member of a family of near-identical constructs, and that its
out-of-sample book is no better than its siblings'. This incumbent keeps the bar and
adds two knobs the jitter reviser can move:

* ``depth_penalty`` -- each level of refinement depth subtracts this much from a
  node's ranking value (not from its eligibility), so a root that clears the bar
  outranks a depth-3 refinement of the same idea unless the refinement's reading is
  higher by more than the penalty. Depth is read from ``question.meta(node_id)``.
* ``ceiling`` -- a reading above the ceiling counts as the ceiling for ranking, so
  two nodes both above it tie on value and the tie breaks by depth then node id.
  The bar and the ceiling together define the band the rule prefers to commit in.

Eligibility is unchanged from M2: ``ic_insample`` at or above the bar, and a
positive ``r2_insample`` (the IC's sign). Abstention is unchanged: no eligible node,
``question.abstain()``. One call, empty batch: a financial world's question reveals
every evaluated node up front.

Every number lives in ``_schedule``'s literals so the default reviser's jitter
reaches them and nothing else; comparisons are against the schedule's values, never
against literals, which is what the admission gate requires.
"""

CONTRACT = "question"

_BETA = 0.5


def _schedule(beta):
    """The three readings this policy uses, derived from ``beta``.

    ``bar`` is the M2 discovery bar; ``depth_penalty`` and ``ceiling`` are the
    two knobs. ``beta`` enters with a zero coefficient as in the M2 incumbent,
    so the schedule is a function of it in shape and fixed in value.
    """
    bar = 2.0
    depth_penalty = 0.25
    ceiling = 4.0
    sign_floor = 0.0
    return {
        "bar": bar + 0.0 * beta,
        "depth_penalty": depth_penalty + 0.0 * beta,
        "ceiling": ceiling + 0.0 * beta,
        "sign_floor": sign_floor + 0.0 * beta,
    }


def _depth_of(question, node_id):
    """The node's refinement depth from the question's own structural view, 0 when unknown."""
    try:
        meta = question.meta(node_id)
    except Exception:  # noqa: BLE001 - a question without meta answers depth 0
        return 0
    depth = getattr(meta, "depth", None)
    return depth if isinstance(depth, int) else 0


def select(question):
    """Commit the best eligible node by banded, depth-penalised reading, or abstain."""
    schedule = _schedule(_BETA)
    bar = schedule["bar"]
    depth_penalty = schedule["depth_penalty"]
    ceiling = schedule["ceiling"]
    sign_floor = schedule["sign_floor"]
    best_id = None
    best_key = None
    for node_id, observation in question.observed().items():
        value = observation.ic_insample
        if value is None or value < bar:
            continue
        sign = getattr(observation, "r2_insample", None)
        if sign is not None and sign <= sign_floor:
            continue
        depth = _depth_of(question, node_id)
        banded = value if value < ceiling else ceiling
        ranking = banded - depth_penalty * depth
        key = (-ranking, depth, node_id)
        if best_key is None or key < best_key:
            best_id = node_id
            best_key = key
    if best_id is not None:
        question.commit(best_id)
    else:
        question.abstain()
    return ()
