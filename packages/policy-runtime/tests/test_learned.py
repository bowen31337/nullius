"""Feature 231, the deferral check — a policy that reaches for a learned
component is refused admission.

app_spec.xml, "Exploration Policy Runtime", feature 231: *System rejects a
policy admission that loads a model checkpoint or calls inference, because a
learned component stays deferred until the triage measurement decides it.*  It
is docs/nullius-tech-architecture.md §11.2 read as an admission gate — *"The
§4.5 overfit signature is a classifier in everything but name … Nothing in this
architecture does.  The policy writes thresholds; dreaming revises them.  **That
stays true until the M1 triage measures the perturbation-stability AUC**"* — a
decision §11.2 records *"so it is not quietly reopened by whoever next reads
§4.5"*.  §12's determinism table closes the other end (*"No inference in the
replay path | Replay calls no model of any kind"*) and §15 files the failure the
deferral exists to make impossible (*"Learned component reached the replay path
un-materialized | Canary drift; replay score varies with batch shape or thread
count"*).

Feature 231 is the fourth static check on feature 230's gate, not a second gate,
and the invariants these tests pin are the ones the guarantee depends on:

* **the refusal belongs to the existing gate** — it is returned by
  :func:`screen_policy`, carried by :class:`PolicyAdmissionDecision`, raised by
  :meth:`PolicyAdmissionDecision.require`, and reported under its own
  :class:`AdmissionReason`, so a caller has one verdict, one exception to catch,
  and one log line naming *which* decision the policy ran ahead of;
* **the three shapes are each detected on their own terms** — a model-framework
  import (the enabling condition), a checkpoint load (matched by verb *and* by
  a checkpoint path handed to a call), and an inference call (matched on the
  attribute name only);
* **the deferral is named, not the model** — the refusal says the learned
  component is deferred until the M1 triage, so the retrying agent knows to
  write against ``question.*`` rather than to try a different model;
* **the check is conservative where the barrier is** — a policy that hands a
  modeled path to a call is refused and named, while two shapes are deliberately
  left alone: ``.bin`` (this system's own ingest writes it) and a bare helper
  named like an inference verb (``predict(x)`` is as likely a policy's own
  function as an inference call).

The headline case is the feature's own sentence: ``torch.load("policy.pt")``
in a policy's source is refused, naming the checkpoint.
"""

from __future__ import annotations

import ast

import pytest
from policy_runtime import (
    AdmissionReason,
    PolicyAdmissionRefusal,
    PolicyRuntimeError,
    find_learned_component,
    screen_policy,
)

#: A policy body that commits correctly on its one terminating path — so that
#: every source below differs from a clean policy *only* in the learned
#: component it carries, and the reason a test observes is the one this feature
#: owns rather than 230's commit reachability.
_COMMITTING_TAIL = (
    "    (root,) = q.legal_roots()\n"
    "    return q.commit(root)\n"
)


def _policy(*lines: str) -> str:
    """A policy whose body is ``lines`` and whose terminal commits.

    Written once so each test's source reads as the one thing it varies — the
    learned component — rather than as ten lines of boilerplate the reader has
    to check for a stray early return.
    """
    body = "".join(f"    {line}\n" for line in lines)
    return f"def policy(q):\n{body}{_COMMITTING_TAIL}"


# ---------------------------------------------------------------------------
# A checkpoint load — the feature's own sentence
# ---------------------------------------------------------------------------


def test_screen_policy_refuses_a_checkpoint_loaded_from_a_source_literal() -> None:
    # The feature's own sentence: a policy that loads a model checkpoint is
    # refused.  The checkpoint is named by the path literal it hands the loader
    # — ``"policy.pt"`` — which is evidence enough on its own, whatever the verb
    # is called, because a policy has no legitimate reason to name a model
    # artifact.
    source = _policy('model = torch.load("policy.pt")')
    decision = screen_policy(source)
    assert decision.adopted is False
    assert decision.reason is AdmissionReason.LEARNED_COMPONENT
    assert any("policy.pt" in offender for offender in decision.offenders)
    assert AdmissionReason.LEARNED_COMPONENT.value in decision.detail


def test_screen_policy_refuses_a_checkpoint_load_named_by_its_verb() -> None:
    # The other half of the phrase: a load verb names a checkpoint load by
    # itself, whatever its argument is.  ``load_state_dict`` is not an English
    # word a policy's own helper would be named by, and no legitimate policy
    # calls one — so the policy is refused for the verb alone, even though the
    # path it loads is built elsewhere and never appears as a literal.
    source = _policy("state = torch.load_state_dict(blob)")
    decision = screen_policy(source)
    assert decision.adopted is False
    assert decision.reason is AdmissionReason.LEARNED_COMPONENT
    assert any("load_state_dict" in offender for offender in decision.offenders)


def test_screen_policy_refuses_a_hugging_face_checkpoint_load() -> None:
    # ``from_pretrained`` is the Hugging Face spelling of a checkpoint load, and
    # §11.2's deferral is about the learned component rather than about which
    # framework ships it — so the refusal does not depend on a framework import
    # being present in the same source.  A policy that calls it is refused.
    source = _policy("clf = AutoModel.from_pretrained(ckpt)")
    decision = screen_policy(source)
    assert decision.adopted is False
    assert decision.reason is AdmissionReason.LEARNED_COMPONENT
    assert any("from_pretrained" in offender for offender in decision.offenders)


def test_screen_policy_refuses_a_checkpoint_path_handed_to_a_plain_load() -> None:
    # A checkpoint path is a checkpoint path whatever the call is named: a
    # builtin-looking ``load(...)`` handed a ``.safetensors`` file is a
    # checkpoint load, and the policy is refused naming the file.  This is the
    # conservative direction — the path is the evidence, and the offender names
    # it so the author knows which literal to drop.  (A path held in a variable
    # is not a literal this screen can read; the import rule that let the
    # framework into the source is what catches that half.)
    source = _policy('weights = load(path="head.safetensors")')
    decision = screen_policy(source)
    assert decision.adopted is False
    assert decision.reason is AdmissionReason.LEARNED_COMPONENT
    assert any("head.safetensors" in offender for offender in decision.offenders)


def test_screen_policy_refuses_every_checkpoint_naming_each() -> None:
    # A policy that reaches for two checkpoints names both, so the author
    # repairs them all rather than resubmitting to learn the rest — the same
    # "name every offender" stance sandbox.screen_module and feature 230 take.
    source = _policy(
        'a = torch.load("policy.pt")',
        'b = load_weights("head.pkl")',
    )
    decision = screen_policy(source)
    assert decision.reason is AdmissionReason.LEARNED_COMPONENT
    assert any("policy.pt" in offender for offender in decision.offenders)
    assert any("head.pkl" in offender for offender in decision.offenders)


# ---------------------------------------------------------------------------
# An inference call — the policy asking a model
# ---------------------------------------------------------------------------


def test_screen_policy_refuses_a_predict_call() -> None:
    # A learned component is *called* through an attribute — an object being
    # asked to infer — and ``model.predict(...)`` is that shape.  The policy is
    # refused with the inference call named, so the author knows the call is the
    # problem rather than the object.
    source = _policy("best = model.predict(frontier)")
    decision = screen_policy(source)
    assert decision.adopted is False
    assert decision.reason is AdmissionReason.LEARNED_COMPONENT
    assert any("predict" in offender for offender in decision.offenders)


def test_screen_policy_refuses_a_forward_call() -> None:
    # ``forward`` is the other spelling of the same act — a tensor handed to a
    # network — and it is matched on the attribute name alone, so a policy that
    # runs a model forward is refused whether or not it imported a framework in
    # this source.
    source = _policy("logits = net.forward(features)")
    decision = screen_policy(source)
    assert decision.adopted is False
    assert decision.reason is AdmissionReason.LEARNED_COMPONENT
    assert any("forward" in offender for offender in decision.offenders)


def test_screen_policy_refuses_a_generate_call() -> None:
    # The language-model spelling: ``llm.generate(prompt)`` is inference, and
    # §12 forbids "a model of any kind" in the searched path.  The refusal names
    # the call, not the object, so a policy author is told which act to remove.
    source = _policy("answer = llm.generate(prompt)")
    decision = screen_policy(source)
    assert decision.adopted is False
    assert decision.reason is AdmissionReason.LEARNED_COMPONENT
    assert any("generate" in offender for offender in decision.offenders)


def test_screen_policy_does_not_flag_a_bare_helper_named_like_inference() -> None:
    # A bare ``predict(x)`` is as likely a policy's own top-level function as an
    # inference call, and refusing a policy for naming a helper would be the
    # false positive that has nothing to do with the deferral.  The attribute
    # shape is what a learned component is called through, so the bare call is
    # left alone and the policy is admitted.
    source = (
        "def predict(cell):\n"
        "    return cell\n"
        "def policy(q):\n"
        + _COMMITTING_TAIL
    )
    decision = screen_policy(source)
    assert decision.reason is AdmissionReason.CLEAN
    assert decision.adopted is True


# ---------------------------------------------------------------------------
# A model-framework import — the enabling condition
# ---------------------------------------------------------------------------


def test_screen_policy_refuses_a_model_framework_import() -> None:
    # The enabling condition: a policy that imports a model framework has
    # authored a learned component, whether or not it gets as far as calling it.
    # The refusal names the framework, so the author removes the import rather
    # than hunting for the call that broke it.
    source = f"import torch\n{_policy()}"
    decision = screen_policy(source)
    assert decision.adopted is False
    assert decision.reason is AdmissionReason.LEARNED_COMPONENT
    assert any("torch" in offender for offender in decision.offenders)


def test_screen_policy_refuses_a_from_import_of_a_model_framework() -> None:
    # ``from sklearn.ensemble import ...`` is the other spelling of the same
    # import, and the detector reads the *root* module name — the framework is
    # imported by whichever form reaches it.  A framework reached through a
    # submodule is still a framework.
    source = f"from sklearn.ensemble import GradientBoostingClassifier\n{_policy()}"
    decision = screen_policy(source)
    assert decision.adopted is False
    assert decision.reason is AdmissionReason.LEARNED_COMPONENT
    assert any("sklearn" in offender for offender in decision.offenders)


def test_screen_policy_refuses_a_pickle_import() -> None:
    # ``pickle`` is not a framework but the checkpoint *serialization*: a policy
    # importing it is unpickling a fitted object, and an unpickled model is the
    # learned component §11.2 defers however it was written to disk.
    source = f"import pickle\n{_policy()}"
    decision = screen_policy(source)
    assert decision.adopted is False
    assert decision.reason is AdmissionReason.LEARNED_COMPONENT


def test_screen_policy_does_not_flag_an_ordinary_stdlib_import() -> None:
    # An ordinary deterministic import is not a model framework — ``math`` is
    # feature 167's committed allowlist's own working set — so a policy that
    # imports it is admitted.  The detector is a named set of frameworks, not
    # "any import at all": feature 167 owns the ceiling, this owns the deferral.
    source = f"import math\n{_policy()}"
    decision = screen_policy(source)
    assert decision.reason is AdmissionReason.CLEAN
    assert decision.adopted is True


# ---------------------------------------------------------------------------
# The boundary the check deliberately does not cross
# ---------------------------------------------------------------------------


def test_screen_policy_does_not_flag_a_bin_path() -> None:
    # ``.bin`` is deliberately *not* a checkpoint suffix here, because this
    # system's own ingest writes ``.bin`` snapshots — the suffix alone does not
    # name a checkpoint, and flagging it would refuse policies that never touch
    # a model.  The trade is 230's own (miss the rarer shape rather than refuse
    # the commoner one): a ``.bin`` *load* is still caught by its load verb.
    source = _policy('bar = read_snapshot("bars.bin")')
    decision = screen_policy(source)
    assert decision.reason is AdmissionReason.CLEAN
    assert decision.adopted is True


def test_screen_policy_still_refuses_a_load_verb_on_a_bin_path() -> None:
    # The other half of that trade, pinned: the suffix exclusion is about the
    # *path alone* being weak evidence, not about ``.bin`` being safe.  A load
    # verb is strong evidence on its own, so a ``.bin`` file loaded by a
    # checkpoint verb is still refused.
    source = _policy('state = load_state_dict("weights.bin")')
    decision = screen_policy(source)
    assert decision.adopted is False
    assert decision.reason is AdmissionReason.LEARNED_COMPONENT


# ---------------------------------------------------------------------------
# The check's place on the gate — order, verdict, and require()
# ---------------------------------------------------------------------------


def test_screen_policy_names_the_unreachable_commit_before_the_learned_component() -> None:
    # The learned-component check runs *last*, because it is the one refusal
    # that is a deferral rather than a broken barrier: a policy whose commit()
    # is unreachable is broken whatever else it carries, so the retrying agent
    # repairs the policy's shape before its premises.  This source carries both,
    # and the reachability is named.
    source = (
        "def policy(q):\n"
        "    if q.legal_roots():\n"
        "        return None\n"
        '    model = torch.load("policy.pt")\n'
        "    return q.commit(None)\n"
    )
    decision = screen_policy(source)
    assert decision.adopted is False
    assert decision.reason is AdmissionReason.UNREACHABLE_COMMIT


def test_screen_policy_returns_a_verdict_for_a_learned_component_never_raises() -> None:
    # The gate returns a verdict, never raises — so a caller auditing a history
    # of policies reads the refusal without a try/except, and only require() on
    # the caller's last line raises.  Feature 231 joins the existing gate rather
    # than introducing a second one, so this property is unchanged by it.
    decision = screen_policy(_policy('model = torch.load("policy.pt")'))
    assert decision.adopted is False  # returned, not raised
    assert decision.offenders != ()


def test_require_raises_policy_admission_refusal_for_a_learned_component() -> None:
    # The bridge: a caller writing ``source = law.screen_policy(source).
    # require()`` gets feature 231 enforced there rather than remembered, and
    # the exception is the same PolicyAdmissionRefusal (a PolicyRuntimeError)
    # every other refusal raises — one gate, one exception to catch.
    decision = screen_policy(_policy("best = model.predict(frontier)"))
    with pytest.raises(PolicyAdmissionRefusal) as raised:
        decision.require()
    assert AdmissionReason.LEARNED_COMPONENT.value in str(raised.value)
    assert isinstance(raised.value, PolicyRuntimeError)


def test_learned_component_reason_value_leads_the_detail() -> None:
    # Each reason's value is the token every refusal's detail opens with, so the
    # reason is greppable in an admission log without a lookup table — and 231's
    # token tells a reader the policy ran ahead of the deferral, not that it
    # broke the information barrier.
    decision = screen_policy(_policy("best = model.predict(frontier)"))
    assert decision.detail.startswith(AdmissionReason.LEARNED_COMPONENT.value + ":")
    # The deferral is *named* as a deferral: the refusal points at the decision
    # that has not been made yet, so the repair is to wait, not to retry.
    assert "deferred" in decision.detail


def test_learned_component_is_not_the_reason_for_an_clean_policy() -> None:
    # adopted is computed from the reason, so a CLEAN policy is admitted and the
    # new reason is never reached for a policy that carries no learned
    # component — the check does not make the gate refuse everything.
    source = (
        "def policy(question):\n"
        "    (root,) = question.legal_roots()\n"
        "    question.probe_batch([root])\n"
        "    while True:\n"
        "        frontier = list(question.legal_actions(root))\n"
        "        if not frontier:\n"
        "            return question.commit(root)\n"
        "        root = frontier[0]\n"
    )
    decision = screen_policy(source)
    assert decision.adopted is True
    assert decision.reason is AdmissionReason.CLEAN
    assert decision.require() == source


# ---------------------------------------------------------------------------
# The detector, read directly — a pure function over an AST
# ---------------------------------------------------------------------------


def test_find_learned_component_answers_by_line_in_source_order() -> None:
    # The detector is exposed as a pure function over an AST, separate from the
    # gate that judges its answer — the same split .planning keeps from the
    # component.  Its offenders read down the policy the way its author will,
    # sorted by line, so a refusal listing them is a reading order rather than
    # an AST traversal order.
    tree = ast.parse(
        "import torch\n"
        "def policy(q):\n"
        '    a = torch.load("m.pt")\n'
        "    b = net.forward(q)\n"
    )
    offenders = find_learned_component(tree)
    lines = [int(offender.split(" ", 2)[1].rstrip(":")) for offender in offenders]
    assert lines == sorted(lines)
    assert len(offenders) == 3


def test_find_learned_component_answers_nothing_for_a_clean_ast() -> None:
    # An empty list is the honest "no learned component here": the detector
    # answers only *what was found*, never *what it means*, and the caller
    # decides what that admits.
    tree = ast.parse(
        "def policy(q):\n"
        "    (root,) = q.legal_roots()\n"
        "    return q.commit(root)\n"
    )
    assert find_learned_component(tree) == []
