"""M3b incumbent: a scale-free commit rule with two tunable knobs, written against the ``question.*`` contract.

docs/preregistration/2026-10-24-m3b-dreaming-commit-rule.md and its Addendum 1. The
registered idea is unchanged: the fixed rule commits the most in-sample-fitted member
of a family of near-identical constructs, and this incumbent gives the reviser two
knobs that can move the commit away from that member, a ``depth_penalty`` per level
of refinement and a ``ceiling`` above which readings tie. Addendum 1 records why the
first form (an absolute bar of 2.0 on ``ic_insample``, the M2 rule) could not be
selected: a dreaming cycle selects on the bootstrap pool, whose readings are
r-squared values on another scale, so an absolute bar abstains on every bootstrap
world and every candidate ties at 0.0. This form is therefore scale-free, as the M3
incumbent was: readings are standardised within the world and the knobs act on the
z-score.

* ``commit_z`` -- the z-score (population standard deviation above the world's mean
  reading) a node must clear to be eligible. The M2 bar's analogue.
* ``depth_penalty`` -- subtracted from the ranking z per level of refinement depth
  (eligibility is unaffected), so a root outranks a deep refinement unless the
  refinement's standing is higher by more than the penalty.
* ``ceiling`` -- a z above the ceiling counts as the ceiling for ranking, so the band
  between ``commit_z`` and ``ceiling`` is where the rule prefers to commit; ties break
  by depth ascending, then node id ascending.
* ``min_observed`` -- how many readings a world must carry before a z-score means
  anything; below it the policy abstains (and, on a bootstrap world, keeps revealing).
* ``frontier_cap`` -- how many not-yet-revealed neighbours one round may add, on a
  bootstrap world; a financial world reveals its whole tree up front and the walk ends
  after one call.

The reading is ``ic_insample`` where the observation carries it (a financial world,
where it is the post-cost IR t-statistic) and ``r2_train`` otherwise (a bootstrap
world). Every number lives in ``_schedule``'s literals so the default reviser's jitter
reaches them and nothing else; comparisons are against the schedule's values and
attributes are read as attributes, which is what the admission gate requires.
"""

import math

CONTRACT = "question"

_BETA = 0.5


def _schedule(beta):
    """Every threshold this policy uses, derived from ``beta``; a fresh dict per call."""
    explore_weight = beta / (1.0 + beta)
    return {
        "commit_z": 0.5 + 1.5 * explore_weight,
        "depth_penalty": 0.25 + 0.0 * explore_weight,
        "ceiling": 2.5 + 0.0 * explore_weight,
        "min_observed": 5,
        "frontier_cap": max(1, round(2.0 + 6.0 * explore_weight)),
    }


def _reading(observation):
    """The node's in-sample reading, or ``None`` when it carries none that is finite."""
    try:
        value = observation.ic_insample
    except AttributeError:
        value = None
    if value is None:
        try:
            value = observation.r2_train
        except AttributeError:
            value = None
    if value is None or not math.isfinite(value):
        return None
    return value


def _depth_of(question, node_id):
    """The node's refinement depth from the question's own structural view, 0 when unknown."""
    try:
        meta = question.meta(node_id)
    except Exception:  # noqa: BLE001 - a question without meta answers depth 0
        return 0
    depth = getattr(meta, "depth", None)
    return depth if isinstance(depth, int) else 0


def select(question):
    """Commit the best eligible node by banded, depth-penalised standing, or abstain; then say whether the walk continues."""
    schedule = _schedule(_BETA)
    commit_z = schedule["commit_z"]
    depth_penalty = schedule["depth_penalty"]
    ceiling = schedule["ceiling"]
    min_observed = schedule["min_observed"]
    frontier_cap = schedule["frontier_cap"]
    observed = question.observed()
    values = {}
    for node_id, observation in observed.items():
        value = _reading(observation)
        if value is not None:
            values[node_id] = value
    best_id = None
    best_key = None
    if len(values) >= min_observed:
        mean = sum(values.values()) / len(values)
        squared = sum((value - mean) * (value - mean) for value in values.values())
        deviation = math.sqrt(squared / len(values))
        if deviation:
            for node_id, value in values.items():
                standing = (value - mean) / deviation
                if standing < commit_z:
                    continue
                depth = _depth_of(question, node_id)
                banded = standing if standing < ceiling else ceiling
                ranking = banded - depth_penalty * depth
                key = (-ranking, depth, node_id)
                if best_key is None or key < best_key:
                    best_id = node_id
                    best_key = key
    if best_id is not None:
        question.commit(best_id)
    else:
        question.abstain()
    for observation in observed.values():
        if hasattr(observation, "ic_insample"):
            return ()
    if not observed:
        return list(question.legal_roots())
    frontier = []
    for node_id in observed:
        for action in question.legal_actions(node_id):
            if action not in observed and action not in frontier:
                frontier.append(action)
    return frontier[:frontier_cap]
