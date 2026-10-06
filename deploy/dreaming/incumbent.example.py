"""A starting incumbent exploration policy for ``./run.sh dream``.

Feature 11 of ``additions_spec_operator_surfaces.xml`` added
``orchestrator.dream``'s ``--incumbent PATH`` flag, but the repository
shipped no file an operator could point it at -- the only admissible source
lived inside a test fixture. This module is that starting incumbent::

    ./run.sh dream --incumbent deploy/dreaming/incumbent.example.py

It is a *starting* incumbent, not a tuned one: a dreaming cycle revises it
``M`` times, scores every revision (and this module itself) against the
stored bootstrap pool, and the winner -- which may not be this file at all
-- is what an operator carries into the next cycle's own ``--incumbent``,
typically via ``--write-selected``.

**The contract is the admission gate's, not a convention** -- the same one
``packages/orchestrator/tests/test_dream_cli.py``'s own ``INCUMBENT_SOURCE``
fixture satisfies, because ``policy_runtime.screen_policy`` enforces it on
every incumbent, example or not:

* ``commit()`` is reached on every terminating path -- a policy that falls
  off without one scores ``-inf`` (feature 230);
* no string literal here is shaped like a hardcoded node id -- every cell is
  addressed through ``question.*``, never by a literal address (feature
  230);
* no comparison anywhere in this file tests an observed score against a
  bare number -- the "how far from target" distance below compares two
  *expressions* (a squared distance against the running best), never a
  score against a numeric literal (feature 230);
* every threshold this policy uses is read out of one ``_schedule(beta)``
  mapping -- the same "route every threshold through one derivation" rule
  ``policy_runtime.schedule`` enforces for an episode's own thresholds (docs
  section 609) -- rather than scattered as separate magic numbers, so a
  later revision of this file, or a dreaming cycle's own jitter, moves its
  numbers from one place;
* it imports nothing. Only the deterministic allowlist
  (``packages/sandbox/src/sandbox/imports_allowlist.json``) is reachable
  from inside the exploration-policy runtime guard, and this policy needs
  none of it.

**The walk.** The first call sees nothing observed yet, so it commits the
world's sole legal root as a placeholder pick and reveals it. Every later
call scores each observed cell by its squared distance from the schedule's
``target_score`` and commits whichever cell is closest, then widens the
frontier to every not-yet-observed neighbour of an observed cell, capped at
the schedule's own ``frontier_cap`` so a wide lattice is not revealed in one
round. Committing on every call -- not only the last -- means a replay that
stops the loop early (the round cap, or an empty frontier) always has a
committed pick to score.
"""

#: This policy's own fixed scalar, read once by ``select`` and threaded into
#: ``_schedule`` -- distinct from a dreaming cycle's own ``--beta``, which
#: governs how *candidates* are scored, not what any one candidate's
#: thresholds are. A policy is free to read a beta of its own; this one
#: simply does not vary it.
_BETA = 0.5


def _schedule(beta):
    """Every threshold this policy uses, derived from one scalar.

    Returns a fresh dict each call, with the two keys ``select`` reads:

    * ``target_score`` -- the held-out R-squared this policy steers its pick
      toward. Rises with ``beta``, in (0.2, 0.5).
    * ``frontier_cap`` -- how many not-yet-observed neighbours one round may
      add to the next reveal batch. Rises with ``beta``, in (2, 8).

    A pure function of ``beta`` and nothing else, so two calls at the same
    scalar return the identical mapping -- a threshold reached any other way
    would be a second schedule, which is exactly the drift routing every
    threshold through this one function exists to prevent.
    """
    explore_weight = beta / (1.0 + beta)
    return {
        "target_score": 0.2 + 0.3 * explore_weight,
        "frontier_cap": 2.0 + 6.0 * explore_weight,
    }


def select(question):
    schedule = _schedule(_BETA)
    target = schedule["target_score"]
    cap = max(1, round(schedule["frontier_cap"]))

    roots = question.legal_roots()
    observed = question.observed()
    if not observed:
        fallback = None
        for root in roots:
            fallback = root
            break
        question.commit(fallback)
        return list(roots)

    best = None
    best_distance = None
    for node_id, observation in observed.items():
        diff = observation.r2_train - target
        distance = diff * diff
        if best_distance is None or distance < best_distance:
            best = node_id
            best_distance = distance
    question.commit(best)

    frontier = []
    for node_id in observed:
        for action in question.legal_actions(node_id):
            if action not in observed and action not in frontier:
                frontier.append(action)
    return frontier[:cap]
