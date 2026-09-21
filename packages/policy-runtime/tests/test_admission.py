"""Feature 230, the admission gate — a policy is admitted only if static checks
find none of the three barrier-breaking anti-patterns.

app_spec.xml, "Exploration Policy Runtime", feature 230: *System rejects a
policy admission when static checks detect absolute score constants, hardcoded
node ids or an unreachable commit path.*  docs/nullius-tech-architecture.md §634
names the checks verbatim — "no absolute score constants, no hardcoded node ids,
… ``commit()`` reachable on every terminating path" — and they are the paper's
hard constraints restated as an admission gate: prefix-only, no absolute score
targets, and ``commit()`` mandatory (a policy that terminates without committing
scores ``-inf``; docs §436, §438).

Feature 230 is the *read side* of that enforcement, and the invariants these
tests pin are the ones the guarantee depends on:

* **the gate returns a verdict, never raises** — :func:`screen_policy` answers
  admitted or refused, why, in what words, naming every offender, and only
  :meth:`PolicyAdmissionDecision.require` raises, on the caller's last line
  before it admits a policy — the gate shape :func:`plan_grid` (feature 229) and
  :func:`sandbox.screen_module` (feature 167) take;
* **the three checks are each their own reason, split by repair** — a policy
  that carries an absolute score constant and one that hardcodes a node id are
  two different prompts to the retrying agent, so they are two reasons, and the
  reason's value token leads every refusal's detail, so it is greppable in an
  admission log;
* **no false negatives over false positives** — the information barrier is a
  hard rule, so a policy that compares an *observed* metric to an absolute
  number is refused, not rationalised away: proving the other side "is not a
  score" is the false negative that lets an absolute target through;
* **the node-id detector is address-shaped, not a dictionary** — it matches the
  indexed-address shape (lowercase, segment-joined, with a letter and a digit)
  and excludes a UUID, so a theme root, a calibration status, prose, or a world
  id a policy legitimately carries is never mistaken for a hardcoded node id;
* **commit reachability is intra-procedural and inline** — every terminating
  path (``return``, ``raise``, or falling off the end) of a function that
  contains a ``commit()`` must be preceded by a ``commit()``; a ``while True``
  that returns its commit from inside the loop (the canonical policy shape, docs
  §476) is admitted because an infinite loop never falls off the end.

The headline case is the barrier's whole point: a policy that carries an
absolute score constant is refused — it is reading past the prefix the barrier
promises it.
"""

from __future__ import annotations

import pytest
from policy_runtime import (
    AdmissionReason,
    PolicyAdmissionRefusal,
    PolicyRuntimeError,
    screen_policy,
)

# ---------------------------------------------------------------------------
# The canonical clean policy — the shape a policy is written in
# ---------------------------------------------------------------------------


#: The canonical policy, written once against ``question.*`` and nothing else —
#: a greedy walk that probes the frontier, moves to the best observed reading,
#: and commits at its terminal.  No absolute score constant, no hardcoded node
#: id, and ``commit()`` reached on its one terminating path.  This is the
#: policy the identical-interface tests run unmodified across both pools
#: (cf. ``test_symreg_question._greedy_walk``), and the thing the gate admits.
CANONICAL_POLICY = """
def policy(question):
    (root,) = question.legal_roots()
    question.probe_batch([root])
    current = root
    while True:
        frontier = list(question.legal_actions(current))
        question.probe_batch(frontier)
        observed = question.observed()
        if not frontier:
            return question.commit(current)
        best = max(frontier, key=lambda cell: observed[cell].r2_insample)
        if observed[best].r2_insample <= observed[current].r2_insample:
            return question.commit(current)
        current = best
"""


def test_screen_policy_admits_the_canonical_policy() -> None:
    # The canonical policy carries no absolute score constant, no hardcoded node
    # id, and no terminating path that fails to reach commit(): every check in
    # feature 230 is satisfied, so it is admitted with CLEAN.
    decision = screen_policy(CANONICAL_POLICY)
    assert decision.adopted is True
    assert decision.reason is AdmissionReason.CLEAN
    assert decision.offenders == ()


def test_screen_policy_require_returns_the_source_unchanged_on_admission() -> None:
    # On an admission, require() returns the admitted source unchanged — adoption
    # is a judgement, never an edit, so the bytes a later stage hashes are
    # exactly these.  A caller can write ``source = law.screen_policy(source).
    # require()`` and have feature 230 enforced there.
    decision = screen_policy(CANONICAL_POLICY)
    assert decision.require() == CANONICAL_POLICY


def test_screen_policy_admits_a_ternary_commit_on_both_branches() -> None:
    # A policy that commits on both branches of a ternary commits on every
    # terminating path, so it is admitted — the commit is performed in the
    # terminating statement itself.
    source = 'def policy(q):\n    return q.commit("a") if q.legal_roots() else q.commit("b")\n'
    decision = screen_policy(source)
    assert decision.adopted is True
    assert decision.reason is AdmissionReason.CLEAN


def test_screen_policy_admits_a_policy_with_a_non_committing_helper() -> None:
    # A helper function that performs no commit is not held to the reachability
    # standard — its committing happens elsewhere — so a policy that commits in
    # its own body and delegates a pure computation to a helper is admitted.
    source = (
        "def _score(cell):\n"
        "    return cell\n"
        "def policy(q):\n"
        "    return q.commit(_score('a'))\n"
    )
    decision = screen_policy(source)
    assert decision.adopted is True
    assert decision.reason is AdmissionReason.CLEAN


# ---------------------------------------------------------------------------
# Absolute score constants — the barrier's headline
# ---------------------------------------------------------------------------


def test_screen_policy_refuses_an_absolute_score_constant() -> None:
    # The headline case the barrier exists for: a policy that compares an
    # observed metric to an absolute number carries an absolute score target, so
    # it is refused with ABSOLUTE_SCORE, naming the literal.  No attempt is made
    # to prove the other side "is not a score" — that is the false negative that
    # lets an absolute target through.
    source = (
        'def policy(q):\n'
        '    (root,) = q.legal_roots()\n'
        '    if q.observed()[root].r2_insample >= 0.8:\n'
        '        return q.commit(root)\n'
        '    return q.commit(root)\n'
    )
    decision = screen_policy(source)
    assert decision.adopted is False
    assert decision.reason is AdmissionReason.ABSOLUTE_SCORE
    assert any("0.8" in offender for offender in decision.offenders)
    assert AdmissionReason.ABSOLUTE_SCORE.value in decision.detail


def test_screen_policy_refuses_an_absolute_score_on_the_left_operand() -> None:
    # An absolute score constant is a numeric literal used as a comparison operand
    # — the barrier is about *comparing to* an absolute score, and a numeric
    # literal that is not part of a comparison (a loop bound like ``range(8)``, an
    # array index) is not a score target and is not flagged.  The literal may sit
    # on either side of the operator; here it is the left operand, and the policy
    # is refused naming the literal.
    source = (
        "def policy(q):\n"
        "    (root,) = q.legal_roots()\n"
        "    if 0.5 > q.observed()[root].r2_insample:\n"
        "        return q.commit(root)\n"
        "    return q.commit(root)\n"
    )
    decision = screen_policy(source)
    assert decision.adopted is False
    assert decision.reason is AdmissionReason.ABSOLUTE_SCORE
    assert any("0.5" in offender for offender in decision.offenders)


def test_screen_policy_does_not_flag_a_numeric_loop_bound_as_a_score() -> None:
    # A numeric literal that is not part of a comparison is not an absolute score
    # target — ``range(8)`` is a loop bound, not a score — so a policy that uses
    # one is admitted.  This is the boundary the comparison-only rule draws: it
    # refuses a comparison to an absolute number, and leaves a bare count alone.
    source = (
        "def policy(q):\n"
        "    (root,) = q.legal_roots()\n"
        "    for _ in range(8):\n"
        "        frontier = list(q.legal_actions(root))\n"
        "        q.probe_batch(frontier)\n"
        "    return q.commit(root)\n"
    )
    decision = screen_policy(source)
    assert decision.reason is not AdmissionReason.ABSOLUTE_SCORE
    assert decision.adopted is True


def test_screen_policy_refuses_every_absolute_score_constant_naming_each() -> None:
    # A policy that carries two absolute score constants names both, so the
    # author repairs them all rather than resubmitting to learn the rest — the
    # same "name every offender" stance sandbox.screen_module takes.
    source = (
        "def policy(q):\n"
        "    (root,) = q.legal_roots()\n"
        "    if q.observed()[root].r2_insample > 0.3 and q.budget_remaining() < 5:\n"
        "        return q.commit(root)\n"
        "    return q.commit(root)\n"
    )
    decision = screen_policy(source)
    assert decision.adopted is False
    assert decision.reason is AdmissionReason.ABSOLUTE_SCORE
    assert any("0.3" in offender for offender in decision.offenders)
    assert any("5" in offender for offender in decision.offenders)


def test_screen_policy_refuses_a_boolean_flag_but_not_as_a_score() -> None:
    # A boolean literal is not a numeric score constant — ``bool`` is an ``int``
    # subclass, and an ``is_null = True`` flag is not an absolute score, the same
    # affinity trap the workspace's SQLite layer guards — so a policy that binds
    # a boolean is not refused as an absolute score.  (It is admitted here, the
    # barrier being about scores, not flags.)
    source = (
        "def policy(q):\n"
        "    flag = True\n"
        "    (root,) = q.legal_roots()\n"
        "    return q.commit(root)\n"
    )
    decision = screen_policy(source)
    assert decision.reason is not AdmissionReason.ABSOLUTE_SCORE


# ---------------------------------------------------------------------------
# Hardcoded node ids — reading past the prefix
# ---------------------------------------------------------------------------


def test_screen_policy_refuses_a_hardcoded_node_id() -> None:
    # A node id is the one address a node is revealed or committed on, and a
    # policy that names one by a literal (``"n0"`` — the planted tree's spelling)
    # is reading past the prefix the barrier promises it, so it is refused with
    # HARDCODED_NODE_ID, naming the literal.
    source = (
        "def policy(q):\n"
        '    return q.commit("n0")\n'
    )
    decision = screen_policy(source)
    assert decision.adopted is False
    assert decision.reason is AdmissionReason.HARDCODED_NODE_ID
    assert any("n0" in offender for offender in decision.offenders)
    assert AdmissionReason.HARDCODED_NODE_ID.value in decision.detail


def test_screen_policy_refuses_a_lattice_shaped_node_id() -> None:
    # The bootstrap lattice spells a node id as ``d+9.i+0.s+0.a+0`` — segments
    # joined by ``.`` and ``+`` — and the detector matches that shape, so a
    # policy that hardcodes one is refused, naming the literal.
    source = (
        "def policy(q):\n"
        '    return q.commit("d+9.i+0.s+0.a+0")\n'
    )
    decision = screen_policy(source)
    assert decision.adopted is False
    assert decision.reason is AdmissionReason.HARDCODED_NODE_ID
    assert any("d+9.i+0.s+0.a+0" in offender for offender in decision.offenders)


def test_screen_policy_does_not_flag_a_uuid_as_a_node_id() -> None:
    # A world or campaign id a policy legitimately carries is a UUID, which
    # matches the address shape and carries digits — so it is excluded on its
    # own pattern, and a policy that carries one is not mistaken for a hardcoded
    # node id.  The policy is admitted.
    source = (
        "def policy(q):\n"
        '    world_id = "550e8400-e29b-41d4-a716-446655440000"\n'
        "    (root,) = q.legal_roots()\n"
        "    return q.commit(root)\n"
    )
    decision = screen_policy(source)
    assert decision.adopted is True
    assert decision.reason is AdmissionReason.CLEAN


def test_screen_policy_does_not_flag_a_theme_root_or_status_as_a_node_id() -> None:
    # A theme root (``"momentum"``, ``"value"``) is a bare word — no digit — and a
    # calibration status (``"VOID"``) is uppercase, so neither matches the
    # indexed-address shape (which requires a letter *and* a digit, lowercase),
    # and a policy that names one is not refused as hardcoding a node id.
    source = (
        "def policy(q):\n"
        '    theme = "momentum"\n'
        '    status = "VOID"\n'
        "    (root,) = q.legal_roots()\n"
        "    return q.commit(root)\n"
    )
    decision = screen_policy(source)
    assert decision.reason is not AdmissionReason.HARDCODED_NODE_ID
    assert decision.adopted is True


def test_screen_policy_does_not_flag_a_bare_word_root_as_a_node_id() -> None:
    # A bare word like ``"root"`` is as likely an English word as an address, and
    # the detector requires a digit (node ids are indexed), so it is not flagged
    # — the safe direction is to miss the rare bare-word root rather than to
    # flag legitimate vocabulary.  The policy is admitted.
    source = (
        "def policy(q):\n"
        '    (root,) = q.legal_roots()\n'
        '    start = "root"\n'
        "    return q.commit(root)\n"
    )
    decision = screen_policy(source)
    assert decision.adopted is True
    assert decision.reason is AdmissionReason.CLEAN


# ---------------------------------------------------------------------------
# Unreachable commit — commit() is mandatory
# ---------------------------------------------------------------------------


def test_screen_policy_refuses_an_early_return_before_any_commit() -> None:
    # A policy with a ``return`` reachable before any ``commit()`` has a
    # terminating path that never commits — a policy that can score on a pick it
    # never made — so it is refused with UNREACHABLE_COMMIT, naming the path.
    source = (
        "def policy(q):\n"
        "    if True:\n"
        "        return None\n"
        '    return q.commit("a")\n'
    )
    decision = screen_policy(source)
    assert decision.adopted is False
    assert decision.reason is AdmissionReason.UNREACHABLE_COMMIT
    assert AdmissionReason.UNREACHABLE_COMMIT.value in decision.detail


def test_screen_policy_refuses_a_raise_before_any_commit() -> None:
    # A ``raise`` is a terminating path too — a policy that raises before it
    # commits terminates without committing — so it is refused, naming the path.
    source = (
        "def policy(q):\n"
        "    if True:\n"
        '        raise ValueError("no pick")\n'
        '    return q.commit("a")\n'
    )
    decision = screen_policy(source)
    assert decision.adopted is False
    assert decision.reason is AdmissionReason.UNREACHABLE_COMMIT


def test_screen_policy_refuses_a_source_with_no_commit_at_all() -> None:
    # commit() is mandatory, so a policy that contains no commit() call at all
    # can never commit — it is refused, naming that the source contains no
    # commit().
    source = "def policy(q):\n    (root,) = q.legal_roots()\n    return None\n"
    decision = screen_policy(source)
    assert decision.adopted is False
    assert decision.reason is AdmissionReason.UNREACHABLE_COMMIT
    assert any("no commit()" in offender for offender in decision.offenders)


def test_screen_policy_refuses_a_function_that_falls_off_without_commit() -> None:
    # A function whose body can fall off the end without reaching a commit() —
    # an implicit ``return None`` — has a terminating path that never commits,
    # so it is refused, naming that it can finish without committing.
    source = (
        "def policy(q):\n"
        "    if True:\n"
        '        return q.commit("a")\n'
        "    x = 1\n"
    )
    decision = screen_policy(source)
    assert decision.adopted is False
    assert decision.reason is AdmissionReason.UNREACHABLE_COMMIT
    assert any("fall off" in offender for offender in decision.offenders)


def test_screen_policy_admits_a_while_true_that_commits_from_inside() -> None:
    # The canonical policy is an unbounded walk — ``while True:`` with no break,
    # returning its commit from inside the loop (docs §476).  An infinite loop
    # never falls off the end, so the post-loop path is not reachable, and the
    # policy commits on its one terminating path — it is admitted, not refused as
    # "falling off without a commit".
    source = (
        "def policy(q):\n"
        "    current = 'root'\n"
        "    while True:\n"
        "        frontier = list(q.legal_actions(current))\n"
        "        q.probe_batch(frontier)\n"
        "        observed = q.observed()\n"
        "        best = max(frontier, key=lambda c: observed[c].r2_insample)\n"
        "        if best == current:\n"
        "            return q.commit(current)\n"
        "        current = best\n"
    )
    decision = screen_policy(source)
    assert decision.adopted is True
    assert decision.reason is AdmissionReason.CLEAN


def test_screen_policy_refuses_a_while_true_that_breaks_to_a_no_commit_path() -> None:
    # A ``while True`` that can ``break`` is not truly infinite — the break exits
    # to whatever follows — so a policy that breaks out of the loop and then
    # falls off without committing is refused; the break makes the post-loop path
    # reachable, and that path never commits.
    source = (
        "def policy(q):\n"
        "    while True:\n"
        "        if True:\n"
        "            break\n"
        '        return q.commit("a")\n'
        "    x = 1\n"
    )
    decision = screen_policy(source)
    assert decision.adopted is False
    assert decision.reason is AdmissionReason.UNREACHABLE_COMMIT


# ---------------------------------------------------------------------------
# Readability — a screen cannot admit what it cannot read
# ---------------------------------------------------------------------------


def test_screen_policy_refuses_a_non_string_source() -> None:
    # A policy that is not source text at all — an int, a mapping — cannot be
    # judged, so it is refused with UNREADABLE_SOURCE, naming the type.  Passing
    # it would be reporting clean over code the gate never checked.
    decision = screen_policy(42)  # type: ignore[arg-type]
    assert decision.adopted is False
    assert decision.reason is AdmissionReason.UNREADABLE_SOURCE
    assert "int" in decision.detail


def test_screen_policy_refuses_a_blank_source() -> None:
    # An empty or whitespace-only string has no entrypoint to be missing, so it
    # is refused with UNREADABLE_SOURCE before any barrier is judged — the same
    # stance signal_agent takes on a blank proposal.
    decision = screen_policy("   ")
    assert decision.adopted is False
    assert decision.reason is AdmissionReason.UNREADABLE_SOURCE


def test_screen_policy_refuses_source_that_does_not_parse() -> None:
    # Source that does not parse has unknowable anti-patterns, and "unknown" is
    # not "clean" — the submission is refused with UNREADABLE_SOURCE, carrying
    # the syntax error, rather than waved through on the half of it that parsed.
    decision = screen_policy("def (")
    assert decision.adopted is False
    assert decision.reason is AdmissionReason.UNREADABLE_SOURCE


# ---------------------------------------------------------------------------
# The order of the checks — the most fundamental problem is named first
# ---------------------------------------------------------------------------


def test_screen_policy_names_the_absolute_score_before_the_node_id() -> None:
    # The checks run in order — readability, absolute score, node id, commit — so
    # a policy that carries both an absolute score constant and a hardcoded node
    # id is refused with the absolute score first, the most fundamental problem
    # named before the more policy-specific one.  The first reason wins, so the
    # refusal is ABSOLUTE_SCORE even though a node id is also present.
    source = (
        "def policy(q):\n"
        "    (root,) = q.legal_roots()\n"
        "    if q.observed()[root].r2_insample >= 0.8:\n"
        '        return q.commit("n0")\n'
        "    return q.commit(root)\n"
    )
    decision = screen_policy(source)
    assert decision.adopted is False
    assert decision.reason is AdmissionReason.ABSOLUTE_SCORE
    # The node id is also present, but the first reason wins, so the offenders
    # name the absolute score, not the node id.
    assert any("0.8" in offender for offender in decision.offenders)


# ---------------------------------------------------------------------------
# The decision and its require() — the bridge that raises on the caller's line
# ---------------------------------------------------------------------------


def test_screen_policy_decision_is_a_value_never_raises() -> None:
    # The gate returns a verdict, never raises — so a caller auditing a history
    # of policies can read the verdict without a try/except, and only require()
    # on the caller's last line raises.
    decision = screen_policy("def policy(q):\n    return None\n")
    assert decision.adopted is False  # returned, not raised


def test_require_raises_naming_the_reason_on_refusal() -> None:
    # On a refusal, require() raises PolicyAdmissionRefusal with the refusal's
    # own sentence — the bridge between the returned verdict and the exception a
    # caller wants on its last line before admitting a policy.
    source = "def policy(q):\n    return None\n"
    decision = screen_policy(source)
    with pytest.raises(PolicyAdmissionRefusal):
        decision.require()


def test_policy_admission_refusal_is_a_policy_runtime_error() -> None:
    # PolicyAdmissionRefusal is a PolicyRuntimeError, so a caller catching the
    # read-side path's one base class catches an admission refusal too — the
    # single-except discipline bootstrap.errors and artifacts._errors state.
    assert issubclass(PolicyAdmissionRefusal, PolicyRuntimeError)


def test_admission_reason_value_leads_the_detail() -> None:
    # Each reason's value is the token every refusal's detail opens with, so the
    # reason is greppable in an admission log without a lookup table.
    source = "def policy(q):\n    return None\n"
    decision = screen_policy(source)
    assert decision.detail.startswith(AdmissionReason.UNREACHABLE_COMMIT.value + ":")


def test_admission_decision_adopted_is_computed_from_reason() -> None:
    # adopted is computed from the reason, never assumed — the same "computed,
    # never assumed" stance PlanGridDecision and sandbox.ModuleDecision take — so
    # a CLEAN reason is the only admitted one.
    assert screen_policy(CANONICAL_POLICY).adopted is True
    decision = screen_policy("def policy(q):\n    return None\n")
    assert decision.adopted is False
    assert decision.reason is not AdmissionReason.CLEAN
