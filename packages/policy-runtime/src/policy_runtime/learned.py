"""Feature 231, the deferral check — a policy that builds a learned component is
refused admission, because §11.2 defers that decision to the M1 triage.

app_spec.xml, "Exploration Policy Runtime", feature 231: *System rejects a
policy admission that loads a model checkpoint or calls inference, because a
learned component stays deferred until the triage measurement decides it.*  It
is docs/nullius-tech-architecture.md §11.2 read as an admission gate: *"The
§4.5 overfit signature is a classifier in everything but name, and it is
tempting to build it as one.  Nothing in this architecture does.  The policy
writes thresholds; dreaming revises them.  **That stays true until the M1
triage measures the perturbation-stability AUC**"* — a decision §11.2 records
*"so it is not quietly reopened by whoever next reads §4.5"*.  §12's
determinism table closes the other end from the other side — *"**No inference
in the replay path** | Replay calls no model of any kind"* — and §15 files the
failure the deferral exists to make impossible: *"Learned component reached the
replay path un-materialized | Canary drift; replay score varies with batch
shape or thread count"*, whose recovery (*"revert to stored-float artifacts"*)
is an operator's, not the code's.

**Where this check sits, and what it is not.**  Feature 230 owns the
information barrier's three static checks over a policy's authored source
(absolute score constants, hardcoded node ids, an unreachable ``commit()``);
this module owns a fourth, and it is the sibling of those rather than a new
gate: the refusal is returned by the same :func:`~policy_runtime.screen_policy`,
carried by the same :class:`~policy_runtime.PolicyAdmissionDecision`, raised by
the same :meth:`~policy_runtime.PolicyAdmissionDecision.require`, and reported
under its own :class:`~policy_runtime.AdmissionReason` so the retrying agent is
told *which* decision it ran ahead of.  One gate, one verdict, one exception to
catch — the shape §634's single list of *"static checks before any policy is
admitted"* implies.

**The refusal is of the *call*, not of the model — and that is the canary's
split, kept.**  Feature 146's ``_inference`` module refuses a model inference
call *made from the replay path*; §11.2's deferral is not a prohibition on
models, because the evaluation path is exactly where a learned output *is*
computed and persisted.  This module draws the complementary line: it says
nothing about *where* a call is made, and nothing about which model classes may
exist — it refuses a policy whose **authored source** reaches for one at all.
A policy is the learnable object (§11.2's own thesis, measured); a learned
component underneath it is a decision the system has not made, so a policy
written against one is written against a premise that does not yet hold.

**Why this is a check and not a configuration.**  The house keeps a
deployment's *ceiling* in a committed document — feature 167's
``imports_allowlist.json``, feature 157's ``isolation_policy.json``, feature
241's ``legal_themes.json`` — because a ceiling the code held could not be
widened or narrowed by the deployment that owns it.  This one is deliberately
*not* a document, and the contrast is the point: §11.2's deferral is the
system's own decision, not a deployment's, and it is lifted by *the triage
measurement* and nothing else.  A JSON file would make reopening the question a
configuration edit, which is precisely the *"quietly reopened"* the section
forbids.  Widening it belongs in a commit to this module, in review, with the
AUC in hand — and even then §11.2's four rows (CPU-deterministic, materialized
at evaluation time, Z0-derived and hashed, holdout-disjoint) each have to be
satisfied before a learned component is admitted at all.

**The three shapes a learned component is reached through.**  A policy's source
can build one three ways, and each is detected on its own terms:

* **a model framework is imported** — ``import torch``, ``from sklearn.ensemble
  import ...``.  The enabling condition, and the one shape that is also
  feature 167's business: the sandbox's committed allowlist admits none of
  these terms, so such a submission is refused there too.  Both refusals are
  correct and they are not duplicates — 167 answers *"is this term inside the
  deployment's ceiling?"*, a question a deployment may answer differently
  tomorrow; this answers *"is this the deferral §11.2 recorded?"*, which no
  deployment may answer at all.  A policy that reaches the admission path is
  screened here whether or not it was screened there.
* **a checkpoint is loaded** — ``torch.load("policy.pt")``, ``model.load_state_dict(...)``,
  ``AutoModel.from_pretrained(...)``.  Matched two ways, because either half of
  the phrase can be the whole of the evidence: the *verb* alone names a
  checkpoint load (``from_pretrained``, ``load_state_dict``,
  ``read_checkpoint`` — no legitimate policy calls one), and the *path* alone
  names it whatever the verb is (a string literal ending in a model-artifact
  suffix, handed to a call).  The two compose: ``torch.load(path)`` with the
  path built elsewhere slips past the literal rule and is caught by the import
  rule that let ``torch`` into the source in the first place.
* **inference is called** — ``model.predict(x)``, ``estimator.forward(t)``,
  ``llm.generate(prompt)``.  Matched on the *attribute* name only.  A bare
  ``predict(question)`` is deliberately **not** an inference call: a policy's
  own top-level helper can be named anything, and refusing it would be the
  false positive that refuses a policy for a function name.  The attribute
  shape — an object being asked to infer — is what a learned component is
  called through, and that is what is matched.

**Conservative, like its sibling — no false negatives over false positives.**
The deferral is a hard architectural decision, not a heuristic, so the check
errs toward refusing: a policy that merely hands a modeled path to a call it
never reaches is refused and named.  Two exclusions are deliberate rather than
oversights.  ``.bin`` is **not** among the checkpoint suffixes, because this
system's own ingest writes ``.bin`` snapshots — the suffix alone does not name
a checkpoint here, and a ``.bin`` load is still caught when its verb is a load
verb.  And a bare inference verb is not matched, for the helper reason above.
Both are the same trade 230 records for the bare word ``"root"``: miss the
rarer shape rather than refuse the commoner one — while the two detections that
catch a *load* stay total, because a policy has no legitimate reason to reach
outside its prefix at all.

Honest limits, stated as feature 167's screen states its own: this reads a
policy's *source*, not its behaviour.  A policy that reaches a model by
spelling the loader dynamically — ``getattr(torch, "load")(...)``, a name built
from a string — evades this screen, exactly as it evades the import allowlist.
This is the admission check, the earliest layer; the enforcement behind it is
the same box that backs every other static check in this member.  What holds is
that the answer is *computed* from the source's AST rather than hardcoded to
"yes", and that every offender is named with its line, so the author repairs
them all rather than resubmitting to learn the rest.

Stdlib only (``ast``), and import-cheap: nothing at module scope the factory's
scan pays for, and no import of another workspace member — the deferral is
owned here, in this member's own vocabulary.
"""

from __future__ import annotations

import ast

__all__ = ["find_learned_component"]

#: The root modules a learned component is built on.  §11.2 names the model
#: classes a *justified* learned component may use ("hierarchical logistic
#: regression or a gradient-boosted tree") and §12 forbids "GPU inference
#: anywhere in research" — so the frameworks are named here as the enabling
#: condition, not as a judgement about which of them is legal: a policy that
#: imports one has authored a learned component, and the deferral is what
#: decides whether such a thing may exist.  ``pickle`` is present because it is
#: the checkpoint *serialization* — a policy importing it is unpickling a fitted
#: object — and not because it is a framework.
_FRAMEWORKS = frozenset(
    {
        "catboost",
        "coremltools",
        "dill",
        "flax",
        "huggingface_hub",
        "jax",
        "joblib",
        "keras",
        "lightgbm",
        "llama_cpp",
        "mlx",
        "onnx",
        "onnxruntime",
        "openvino",
        "optimum",
        "pickle",
        "safetensors",
        "scikit_learn",
        "sentence_transformers",
        "sklearn",
        "tensorflow",
        "tensorrt",
        "tflite_runtime",
        "torch",
        "transformers",
        "vllm",
        "xgboost",
    }
)

#: The model-artifact formats a checkpoint path is spelled with — the torch,
#: Hugging Face, ONNX, pickle, Keras/TensorFlow, GGUF, CoreML and TorchServe
#: serializations, plus numpy's array formats.  ``.bin`` is deliberately absent:
#: this system's own ingest writes ``.bin`` snapshots, so the suffix alone does
#: not name a checkpoint — a ``.bin`` load is still caught by its load verb.
_CHECKPOINT_SUFFIXES = (
    ".ckpt",
    ".dill",
    ".gguf",
    ".h5",
    ".hdf5",
    ".joblib",
    ".keras",
    ".mar",
    ".mlmodel",
    ".npy",
    ".npz",
    ".onnx",
    ".pb",
    ".pkl",
    ".pickle",
    ".pt",
    ".pth",
    ".safetensors",
    ".sav",
    ".tflite",
)

#: Call names that name a checkpoint load by themselves, whatever their
#: arguments are — no legitimate policy calls one, so the verb is the whole of
#: the evidence.  Matched as an attribute (``model.load_state_dict(...)``) *and*
#: as a bare name (``load_state_dict(...)``), because both spellings are a load:
#: a policy reaches its question through an attribute either way, and a bare
#: ``load_state_dict`` is not an English word a helper would be named by.
_LOAD_CALLS = frozenset(
    {
        "InferenceSession",
        "from_ckpt",
        "from_pretrained",
        "load_checkpoint",
        "load_ckpt",
        "load_model",
        "load_parameters",
        "load_pretrained",
        "load_safetensors",
        "load_state_dict",
        "load_weights",
        "read_checkpoint",
        "read_pickle",
        "restore_checkpoint",
        "unpickle",
    }
)

#: The inference verbs a learned component is *called* through.  Matched as an
#: attribute name only (``model.predict(...)``): a bare ``predict(x)`` is as
#: likely a policy's own helper as an inference call, and refusing a policy for
#: naming a helper is the false positive the attribute-only rule avoids.
#: ``score``, ``fit`` and ``train`` are deliberately absent — they are ordinary
#: English in this system's own vocabulary (§14's reporting, the scoring path),
#: so matching them would refuse policies that never touch a model.
_INFERENCE_CALLS = frozenset(
    {
        "classify",
        "decision_function",
        "embed",
        "embedding",
        "forward",
        "generate",
        "infer",
        "infer_batch",
        "inference",
        "predict",
        "predict_log_proba",
        "predict_proba",
    }
)


def _import_roots(node: ast.Import | ast.ImportFrom) -> list[str]:
    """The root module names an import statement names.

    ``import a.b`` and ``from a.b import c`` both name the root ``a`` — the
    framework is imported by whichever spelling reaches it.  A relative import
    (``from . import sibling``) has no module to name, and a policy that writes
    one is refused by feature 167's screen (a submitted policy is one module,
    not a package with siblings), so it contributes nothing here.
    """
    if isinstance(node, ast.Import):
        return [alias.name.split(".", 1)[0] for alias in node.names]
    if node.level:
        return []
    module = node.module or ""
    return [module.split(".", 1)[0]] if module else []


def _callee_name(node: ast.Call) -> tuple[str | None, bool]:
    """The called name and whether it was reached as an attribute.

    ``question.commit(x)`` is an attribute call named ``commit``;
    ``load_model(x)`` is a bare call named ``load_model``.  Anything else — a
    call through a subscript, a lambda or a call result — names nothing, and
    names nothing here deliberately: a callee whose own name is computed is not
    a name this screen can honestly match on.
    """
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr, True
    if isinstance(func, ast.Name):
        return func.id, False
    return None, False


def _is_checkpoint_path(value: object) -> bool:
    """Whether a string literal names a model checkpoint by its suffix.

    The leaf of the path — everything after the last ``/`` — must end in one of
    :data:`_CHECKPOINT_SUFFIXES`.  The leaf rather than the whole string, so a
    directory that merely contains a dot (``"runs/v1.2/policy.pt"``) is judged
    on the file it names, and case-insensitively, because a checkpoint written
    by an operator reads ``.PT`` as often as ``.pt``.
    """
    if not isinstance(value, str) or not value:
        return False
    leaf = value.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return leaf.endswith(_CHECKPOINT_SUFFIXES)


def _call_arguments(node: ast.Call) -> list[ast.AST]:
    """Every argument a call is handed — positional and keyword alike.

    Both, because a checkpoint is loaded by the path it names however the call
    spells it: ``load("m.pt")``, ``load(path="m.pt")``, and
    ``from_pretrained(ckpt="m.pt")`` are one load written three ways.
    """
    arguments = [arg for arg in node.args if not isinstance(arg, ast.Starred)]
    arguments.extend(keyword.value for keyword in node.keywords)
    return arguments


def find_learned_component(tree: ast.AST) -> list[str]:
    """Every way ``tree`` reaches for a learned component, by line.

    The detector behind feature 231's refusal, kept a function over an AST so
    the check is a pure read of the source: the three shapes above, each named
    where it was found and each carrying the line it sits on, sorted by line so
    the offenders read down the policy the way its author will.  An empty list
    is the honest "no learned component here" — the caller
    (:func:`policy_runtime.screen_policy`) decides what that admits, so this
    function answers only *what was found*, never *what it means*.

    The whole tree is walked, nested scopes included, and that is the contrast
    with feature 230's commit matcher rather than an oversight: a
    ``def load_weights(...)`` never *runs* when the enclosing statement does, so
    230 does not count it as a commit — but a ``model.predict(...)`` inside a
    nested helper runs exactly when the helper is called, so the deferral is
    broken by it just the same.  Where a call sits in the source is not a fact
    that excuses it; that it is there at all is the fact this check reads.
    """
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for root in _import_roots(node):
                if root in _FRAMEWORKS:
                    offenders.append(
                        f"line {node.lineno}: a model-framework import — {root!r}"
                    )
        elif isinstance(node, ast.Call):
            name, is_attribute = _callee_name(node)
            if name in _LOAD_CALLS:
                offenders.append(
                    f"line {node.lineno}: a checkpoint load — {name}(...)"
                )
            elif is_attribute and name in _INFERENCE_CALLS:
                offenders.append(
                    f"line {node.lineno}: an inference call — {name}(...)"
                )
            for argument in _call_arguments(node):
                if isinstance(argument, ast.Constant) and _is_checkpoint_path(
                    argument.value
                ):
                    offenders.append(
                        f"line {node.lineno}: a checkpoint path "
                        f"{argument.value!r} handed to {name or 'a call'}(...)"
                    )
    offenders.sort(key=lambda offender: int(offender.split(" ", 2)[1].rstrip(":")))
    return offenders
