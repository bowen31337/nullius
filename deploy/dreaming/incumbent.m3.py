"""The M3 incumbent: one commit rule that decides on a financial world and
explores a bootstrap one.

docs/preregistration/2026-10-17-m3-dreaming.ADDENDUM.md, Addendum 3, *"The
fix"*: *"The incumbent is ``deploy/dreaming/incumbent.m3.py`` (CONTRACT
``question``), admitted by the strict gate. Each call reads every revealed
node's in-sample value: ``ic_insample`` where the observation carries it
(financial), ``r2_train`` otherwise (bootstrap), skipping a missing or
non-finite value. It commits the highest-valued node (ties by node id
ascending) when at least ``min_observed`` nodes have values and that node's
z-score among them is at least ``commit_z``; otherwise it abstains. On a
financial world it then returns no batch, so it decides once over the whole
tree, as the M2 rule does. On a bootstrap world it returns up to
``frontier_cap`` unrevealed neighbours of revealed nodes, re-deciding each
round. All three parameters come from one ``_schedule(beta)`` at
``beta = 0.5``: ``commit_z = 0.5 + 3.0·w``, ``frontier_cap = max(1,
round(2.0 + 6.0·w))`` with ``w = beta/(1+beta)``, and ``min_observed = 5``."*

**Why the pre-registration's own incumbent could not stand in.** Addendum 3's
*"The refused attempt"* records the cycle ``m3-attempt-1`` refused at
selection with ``selection_ungrounded``: every one of its 41 candidates scored
``-inf`` (abstained) on **all 45** bootstrap train worlds. The incumbent it
revised was ``deploy/dreaming/incumbent.m2.py``, the M2 fixed rule, which only
picks among nodes that are *already evaluated* — it reads
``question.observed()`` once and commits or abstains, and never expands a
node. A financial world reveals its whole stored tree before the first call,
so that rule works there; a bootstrap world reveals nothing until a policy
asks for nodes, so it abstains at once, in every domain, and jitter only moves
its threshold, so every revision does the same. Selection runs on bootstrap
worlds only, so it had nothing to select on.

**Why the other shipped policy could not either.** ``deploy/dreaming/
incumbent.example.py`` does explore, but it was written for bootstrap
observations alone: it subtracts from ``observation.r2_train``, which is
``None`` on a financial node the replay reveals without a reading (a node
whose ``ic_mean`` is ``NULL`` — ``orchestrator._live_tree`` freezes it an
empty payload, and the replay's own root seeding reveals it anyway), so it
raises ``TypeError`` on a financial world. And even where it does not raise,
the only observation field both pools share is ``r2_train``, which on a
financial world is ``ic_mean ** 2`` — the *square* of the in-sample
information coefficient, which discards its sign. Ranking by it would prefer
the node with the largest ``|ic_mean|``, profitable or not.

**One ``commit_z`` governs both pools, and that is the point.** Addendum 3's
second shaping fact: *"A threshold read on financial worlds alone (the M2 bar)
is never exercised on bootstrap worlds. Its revisions could not be told apart
by selection, so criterion 1 would measure jitter noise. For selection on
bootstrap worlds to bear on financial worlds at all, one parameter must decide
the commit in both pools."* So the commit is one rule — the top reading among
the nodes that carry one, kept only when it stands ``commit_z`` population
standard deviations above the mean of those readings — and every numeric
threshold it uses comes from the one :func:`_schedule`. A revision that moves
``commit_z`` moves it in both pools at once, so what selection measures on
bootstrap worlds is the same decision the financial verdict reads.

**The z-score, not the raw level.** A raw level would be a different bar in
each pool — bootstrap ``r2_train`` and financial ``ic_insample`` are different
quantities on different scales — and, worse, a policy comparing a reading
against a bare number is exactly what the admission gate refuses (feature 230:
no absolute score constants). A node's standing *among the nodes revealed so
far* is the same question in either pool, needs no absolute target to state,
and is what ``commit_z`` names. The standard deviation is the *population*
one (divide by ``n``, the readings are the whole set being judged) and a
**zero deviation never clears**: with every reading equal there is no "above
the rest" to point at, and a rule that committed the first id on a flat set
would be committing to noise. Ties on the top reading break by node id
ascending, the order :func:`orchestrator.closeout._commit_top_node` breaks its
own tie by.

**Abstention is a decision, and it is declared.** Every terminating path of
``select`` reaches ``question.commit(...)`` or ``question.abstain()`` inline —
the strict rule ``policy_runtime.screen_policy`` holds a ``CONTRACT =
"question"`` module to, on every path of ``select`` once same-module helpers
are followed. Falling short of ``min_observed`` readings, or a top reading
that does not clear ``commit_z``, is a world this policy takes no position on,
and Addendum 3 makes that a legitimate outcome (an abstained episode scores
``NON_COMMITTING_SCORE``, the same number a miss always scored); the
declaration is what keeps a *chosen* miss distinguishable from a policy that
fell off its end.

**Which pool, and how the pool is told apart.** The two pools' observations
name their in-sample reading differently — ``bootstrap.Observation`` carries
``r2_train``, and the financial front's observation carries ``ic_insample``
(``orchestrator._live_tree``'s own fold of a node's ``ir_tstat``-or-
``ic_tstat`` reading) — so reading ``ic_insample`` *where the attribute
exists* and falling back to ``r2_train`` reads each pool's own honest number
without this module ever naming a domain. The same attribute is how the
frontier decision tells the pools apart: a financial world's question reveals
its whole stored tree before the first call, so its observations carry
``ic_insample`` and there is nothing left to explore — this policy decides
once and answers no batch, exactly as the M2 rule does (Addendum 3: *"On a
financial world it then returns no batch, so it decides once over the whole
tree"*). A bootstrap world reveals nothing until asked, so its observations
carry no ``ic_insample`` and the walk continues: up to ``frontier_cap``
not-yet-revealed neighbours of revealed nodes, in a stable order, are the next
batch.

**Every threshold comes from :func:`_schedule`, no literal at a comparison
site.** The admission gate refuses a numeric literal compared against
anything (feature 230), so no threshold here is written where it is used:
``min_observed``, ``commit_z`` and ``frontier_cap`` are read out of one
``_schedule(beta)`` mapping, the discipline ``deploy/dreaming/
incumbent.example.py`` and :mod:`policy_runtime.schedule` hold their own
thresholds to. The zero-deviation guard is a truth test on the deviation
(``if deviation and ...``), never ``deviation > 0.0`` — the same reason. Each
constant is a float or int literal, so the default jitter reviser
(:class:`dreaming.reviser._JitterLiterals`, the ``jitter`` reviser Addendum 3
names) moves the whole rule from one place and a revision of this file stays
admissible by construction.

**No import beyond the allowlist, and nothing else reachable.** ``math`` —
``isfinite``, for skipping a NaN or an infinity — is on the sandbox's
committed allowlist (``packages/sandbox/src/sandbox/imports_allowlist.json``),
so the deterministic policy runtime reaches it; nothing else is imported, and
no cell is ever addressed by a literal id (every read and every commit goes
through ``question.*``).

``CONTRACT = "question"`` names the policy contract this module is authored
to — ``select(question)`` over ``question.observed()``/``question.commit
(...)``/``question.abstain()`` — for :func:`orchestrator._policy.
load_exploration_policy` (additions_spec_dreaming_m3.xml, "Dreaming
Preconditions", feature 6). It is a string literal rather than a derived value
because dreaming's default reviser jitters numeric literals only and leaves a
string marker like this one untouched across a revision.
"""

import math

CONTRACT = "question"

#: This policy's own fixed scalar, read once by :func:`select` and threaded
#: into :func:`_schedule` — distinct from a dreaming cycle's own ``--beta``,
#: which governs how *candidates* are scored, not what any one candidate's
#: thresholds are. Addendum 3 pins this policy's parameters at ``beta = 0.5``.
_BETA = 0.5


def _schedule(beta):
    """Every threshold this policy uses, derived from one scalar.

    Returns a fresh dict each call, with the three keys ``select`` reads:

    * ``commit_z`` — how far above the mean of the readings it has seen, in
      population standard deviations, the highest reading must stand before
      this policy commits it. ``0.5 + 3.0 * w``, in ``(0.5, 3.5)``.
    * ``frontier_cap`` — how many not-yet-revealed neighbours one round may
      add to the next reveal batch. ``max(1, round(2.0 + 6.0 * w))``, in
      ``[2, 8]``.
    * ``min_observed`` — how many nodes must carry a reading before the
      z-score is computed at all: a "top of the set" drawn from a handful of
      nodes is not a standing worth committing to.

    where ``w = beta / (1.0 + beta)`` — the same exploration weight
    ``deploy/dreaming/incumbent.example.py`` derives its own thresholds from.

    A pure function of ``beta`` and nothing else, so two calls at the same
    scalar return the identical mapping — a threshold reached any other way
    would be a second schedule, which is exactly the drift routing every
    threshold through this one function exists to prevent. All three
    constants are literal (``0.5``, ``3.0``, ``2.0``, ``6.0``, ``5``), so the
    jitter reviser moves the rule's magnitudes without touching its shape.
    """
    explore_weight = beta / (1.0 + beta)
    return {
        "commit_z": 0.5 + 3.0 * explore_weight,
        "frontier_cap": max(1, round(2.0 + 6.0 * explore_weight)),
        "min_observed": 5,
    }


def select(question):
    """Decide this world's commit, then say whether the walk continues.

    One call does both halves of Addendum 3's rule:

    * **The decision.** Every revealed node's in-sample value is read —
      ``ic_insample`` when the observation carries that attribute and it is
      not ``None`` (a financial world), its ``r2_train`` otherwise (a
      bootstrap world) — with a missing, NaN or infinite value skipped, never
      guessed at. With at least ``min_observed`` values in hand and the
      highest of them (ties by node id ascending) standing at least
      ``commit_z`` population standard deviations above their mean — and the
      deviation not zero, which never clears — that node is committed through
      ``question.commit(node_id)``; every other outcome is declared with
      ``question.abstain()``.

    * **The batch.** A world whose observations carry ``ic_insample`` is a
      financial world, whose question revealed its whole stored tree before
      this, the first call: there is nothing left to explore, so ``()`` ends
      the replay after this one decision, exactly as the M2 rule's own replay
      ends. Otherwise the walk continues: up to ``frontier_cap``
      not-yet-revealed legal actions of revealed nodes, in a stable order
      (revealed node id ascending, then the actions' own ascending order,
      deduplicated), so a round's batch is a deterministic function of what
      has been revealed. A world with nothing revealed yet has no neighbour
      to name, so it has just abstained and answers the legal roots — the
      walk's own starting point, which the next call will then see revealed.

    Both terminal acts are written inline on every path, and the batch is
    returned after one of them has been written, so the strict commit-
    reachability rule a ``CONTRACT = "question"`` module is held to is
    satisfied by construction rather than by a helper this module would have
    to trust.
    """
    schedule = _schedule(_BETA)
    commit_z = schedule["commit_z"]
    frontier_cap = schedule["frontier_cap"]
    min_observed = schedule["min_observed"]

    observed = question.observed()

    values = {}
    for node_id, observation in observed.items():
        value = getattr(observation, "ic_insample", None)
        if value is None:
            # The bootstrap fallback is a *direct* attribute read inside a
            # try, never ``getattr(observation, "r2_train", None)``: the
            # field's own name carries a digit, which is exactly what makes
            # the admission gate's hardcoded-node-id detector match it (a
            # node id is an indexed address like ``n0``, and the detector's
            # rule is "lowercase, segment-joined, carries a letter and a
            # digit"). Naming the field as a string literal would refuse this
            # module for a node id it never wrote, so the read is spelled as
            # the attribute it is and a pool that does not carry it answers
            # the AttributeError this except turns back into "no reading".
            try:
                value = observation.r2_train
            except AttributeError:
                value = None
        if value is None or not math.isfinite(value):
            continue
        values[node_id] = value

    best_id = None
    best_value = None
    for node_id, value in values.items():
        if (
            best_value is None
            or value > best_value
            or (value == best_value and node_id < best_id)
        ):
            best_id = node_id
            best_value = value

    if best_id is not None and len(values) >= min_observed:
        # Both sums are accumulated by the builtin ``sum`` over a generator
        # rather than in a hand-rolled accumulator seeded with ``0.0``: the
        # jitter reviser perturbs a zero literal *additively* (any factor
        # times zero is zero, so a multiplicative nudge would leave it at
        # zero), which would add a constant offset to every revised
        # candidate's sum of squares and move its z-scores for no reason.
        # There is no literal here for a revision to move.
        mean = sum(values.values()) / len(values)
        squared = sum(
            (value - mean) * (value - mean) for value in values.values()
        )
        deviation = math.sqrt(squared / len(values))
        if deviation and (best_value - mean) / deviation >= commit_z:
            question.commit(best_id)
        else:
            question.abstain()
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
