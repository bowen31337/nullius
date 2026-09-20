"""No inference in the replay path — the inference refusal.

app_spec.xml feature 146 (this category's, in "Determinism Guarantees &
Nightly Canary", depending on feature 140): *"System rejects a model
inference call made from the replay path, because replay reads materialized
values rather than computing them."* It is §12's closing table row —
"**No inference in the replay path** | Replay calls no model of any kind.
Learned outputs, if ever adopted, are materialized at evaluation time and
read back as stored floats — §11.2" — the row the prerequisites state as a
flat prohibition ("replay invokes no model inference of any kind") and
§11.2's materialization row states from the other side: *"its outputs are
computed **once at evaluation time** and persisted to the artifact store.
Replay reads stored floats and calls no inference."*  §15 files the failure
this feature exists to make impossible — "Learned component reached the
replay path un-materialized | Canary drift; replay score varies with batch
shape or thread count" — and its recovery ("revert to stored-float
artifacts, §11.2") is the operator's, not the code's.

Where features 135-140 are assertions over declarations a deployment
already wrote — image references, device strings — this one refuses a
*call at runtime*, which is a different shape of assertion and gets a
different shape of module: not a parser over strings but a mark set where
the replay path begins and a seam the call goes through.  Four decisions
carry the feature, and each is a reading of one word in it.

**The refusal is of the call, not of the model.**  The feature's word is
*call*: what is rejected is "a model inference call made from the replay
path", not a model.  §11.2 defers learned components, but deferral is not
prohibition from the whole system — the evaluation path is exactly where a
learned output is "computed once at evaluation time and persisted", so a
model called there is the contract *working*, not breaking.  Nothing here
inspects a model, names model classes, or refuses a checkpoint: the seam
is the call, and the one fact the refusal needs is where the call was made
from.  Which models may exist at all is the admission checks' question (a
later member's, app_spec.xml feature 231) — and a refusal that tried to
answer it here would be the canary deciding policy admission, the same
coupling this package refuses everywhere else.

**The replay path is a dynamic extent, marked where it begins.**  "Made
from the replay path" is a fact about where the call sits at runtime, and
the replay is a separate deployment (§13) whose code is not this package's
to gate line by line.  So the path is *marked*: :func:`replaying` is the
context manager that spans the replay's dynamic extent, and feature 142's
:func:`~canary.replay_pair` enters it around its whole computation, so
every replay is guarded by construction — no nightly runner can forget
the guard, and the composed spelling (:meth:`~canary.CanaryReplay.pair`)
inherits it because it delegates.  The mark is a
:class:`contextvars.ContextVar` rather than a module flag, and the choice
is the same one §12's "single-threaded numerics" row pins from the other
direction: one replay is one context, the mark cannot leak into a thread
the replay did not spawn, and a task the extent *does* ask to run carries
the mark with it — the honest reading of "from the replay path" for
anything running on the replay's behalf.  The guard is an assertion
channel, not a data flow: it reads no value into the score and
contributes none to it, so a replay run under it computes exactly the
score its frozen bytes sum to — what the guard changes is what the replay
*refuses*, not what it computes.

**The call is refused before it is made — the model never runs.**
:func:`model_inference` checks the mark first and raises
:class:`~canary.CanaryInferenceError` without calling the model.  The
order is the feature: a learned output computed inside the replay would
already be the drift the refusal exists to prevent — the score would
carry a value no frozen pair contributed, and §15's "replay score varies
with batch shape or thread count" is the symptom of exactly that value —
so a refusal that ran the call and then raised would have spent the thing
it was refusing to spend.  The refusal names the model and states the
repair, because §15's recovery is an operator's decision and an operator
reads the message.

**Off the replay path, the seam delegates — and that is what makes it a
seam.**  A refusal that only refused would guard nothing, because no
caller would route through it.  :func:`model_inference` is the one
spelling of "call a model" that carries the determinism contract with it:
a caller on the evaluation path gets the model's own result back, the
arguments and keyword arguments passed through untouched, because the
evaluation path is where §11.2 computes learned outputs once and persists
them.  The delegation is deliberately *thin* — no caching, no counting,
no retries, no validation of the model — because anything more would make
the canary own inference rather than refuse it, and the artifact store
§11.2 names is the owner of materialization, not this member.

What this module deliberately does **not** do is admit, materialize, or
record.  It does not admit models — §11.2's four admission rows are the
M1 triage's, and a registry here would be a second place the "deferred,
with conditions" decision could be quietly reopened.  It does not
materialize anything — computing a learned output once and persisting it
is the evaluation path's verb and the artifact store's table, and a
canary that wrote model outputs would be the auditor editing the evidence
it audits.  It does not record or count the calls it refuses — the
refusal is the feature, raised where the caller is, and the clean-path
evidence is the replay's own result, whose score is a function of frozen
bytes no model contributed to.  Stdlib only — ``contextlib`` and
``contextvars`` beside the typing that names them — so importing this
member on every factory scan (and on the replay path §1 keeps away from
anything that could perturb it) still costs composition nothing.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from ._errors import CanaryInferenceError

__all__ = [
    "ModelInference",
    "is_replaying",
    "model_inference",
    "replaying",
]

#: The mark that says "this dynamic extent is the replay path".  A
#: :class:`~contextvars.ContextVar` rather than a module-level flag, because a
#: module flag is process-global state one replay's failure could leave set for
#: every later caller, while a context value is scoped exactly to the extent
#: that set it: set on entry, restored on exit however the extent ends, and
#: invisible to a thread the replay did not spawn.  The default — ``False`` —
#: is the honest starting state: code is on the replay path only while a
#: replay is running, and everything else is the evaluation path or neither,
#: where a model call is §11.2's to judge, not this module's.
_REPLAYING: ContextVar[bool] = ContextVar("nullius_canary_replaying", default=False)


def is_replaying() -> bool:
    """Whether this dynamic extent is the replay path.

    ``True`` inside :func:`replaying` — and therefore inside feature 142's
    :func:`~canary.replay_pair`, which runs its whole computation there — and
    ``False`` everywhere else, including the extent a replay spawns work into.
    The predicate the seam refuses on, kept public because it is also the
    audit's read: a nightly report can state *that the replay path was entered*
    without having to attempt an inference call to prove it.
    """
    return _REPLAYING.get()


@contextmanager
def replaying() -> Iterator[None]:
    """Mark the replay path's dynamic extent — the guard's entry.

    Sets the context mark :func:`is_replaying` reads for the duration of the
    ``with`` block, and restores the previous state on exit however the block
    ends — normally, by exception, or by nested extent — so a replay that
    raised still leaves the path marked exactly as it found it.  Restoring
    rather than clearing is what makes nesting honest: an extent entered from
    inside another one unwinds to *still replaying*, because both extents are
    the replay path.

    The load-bearing caller is feature 142's :func:`~canary.replay_pair`,
    which enters this around its whole computation so every replay is guarded
    by construction — but the context is public, because "the replay path" is
    a deployment shape (§13), not one function: a nightly runner that reads a
    pair back and hands it to the replay marks the same extent, and anything
    it runs on the replay's behalf is then inside the same refusal.
    """
    token = _REPLAYING.set(True)
    try:
        yield
    finally:
        _REPLAYING.reset(token)


def _model_name(model: Any) -> str:
    """The model's own name — what the refusal calls it.

    A function or class names itself; an instance names its type.  One
    spelling, stated once, so the refusal's message points at the thing the
    operator must materialize rather than at an opaque ``repr`` the operator
    cannot grep for.
    """
    name = getattr(model, "__name__", None)
    if isinstance(name, str) and name.strip():
        return name
    return type(model).__name__


def model_inference(model: Any, /, *args: Any, **kwargs: Any) -> Any:
    """Call a model through the determinism contract's one seam.

    Feature 146's sentence, executed: if the call arrives from inside the
    replay path — :func:`is_replaying` is ``True`` — it is rejected with
    :class:`~canary.CanaryInferenceError` *before the model runs*, naming the
    model and stating §11.2's repair (materialize the output where it is
    evaluated, read back the stored floats).  Otherwise the model is called
    with the arguments exactly as handed in and its result returned exactly as
    it came back — the evaluation path's ordinary business, and the reason a
    caller routes through this seam rather than around it: the call carries
    the contract with it, so the one place a learned component may reach for
    a model is the one place that refuses to do so on the replay's behalf.

    The model is positional-only so a caller's ``args`` cannot collide with
    the seam's own spelling, and nothing about the model is validated or
    inspected — a non-callable off the replay path fails with the call's own
    ``TypeError``, and on the replay path the refusal fires first, because
    the feature rejects the *call*, whatever the model turns out to be.
    """
    if is_replaying():
        raise CanaryInferenceError(
            f"a model inference call ({_model_name(model)}) was made from the "
            "replay path: the replay reads materialized values rather than "
            "computing them — replay calls no model of any kind (architecture "
            "§12, 'No inference in the replay path'), so a learned output the "
            "replay needs is one that was computed once at evaluation time and "
            "read back as stored floats (architecture §11.2). Materialize the "
            "output where it is evaluated and replay the stored floats"
        )
    return model(*args, **kwargs)


class ModelInference:
    """Feature 146's refusal, as the value a composed application carries.

    A stateless facade over the three spellings above, so a caller holding
    the composed canary component can reach the refusal without importing
    this member's submodules by name — the same role
    :class:`~canary.CanaryReplay` plays for the nightly replay and
    :class:`~canary.BitReproducibility` plays for the byte comparison.  The
    class carries no state: ``__slots__`` is empty and it defines no
    ``__init__``, which is the honest shape for a guard that is a fact about
    where a call sits, not a thing a deployment configures.  There is no
    model registry, no allowlist and no toggle here — the refusal is not a
    setting that could be turned off, it is the replay path's definition —
    so two callers can never observe each other through this value, and
    there is nothing a deployment could misset.

    The delegation is deliberately *thin* — each method is one call to the
    function that owns the behaviour — because a second implementation of
    the refusal is exactly what this package's one-provenance rule forbids.
    What this class adds is discoverability (the factory's scan composes
    it, through :attr:`canary.CanaryService.inference`) and one
    duck-checkable seam for the app seat and the features that follow, not
    enforcement logic.
    """

    __slots__ = ()

    def call(self, model: Any, /, *args: Any, **kwargs: Any) -> Any:
        """Call a model — refused when made from the replay path.

        Feature 146's whole sentence, through the composed component: same
        refusal (raised before the model runs, naming it, stating §11.2's
        repair), same delegation (arguments and result untouched) as
        :func:`model_inference` — a caller reaching the seam through the
        composed application and one importing the member agree by
        construction.
        """
        return model_inference(model, *args, **kwargs)

    def replaying(self) -> Iterator[None]:
        """The context manager marking the replay path — the guard's entry.

        The composed spelling of :func:`replaying`, for a nightly runner that
        holds the service and wants a replay-shaped extent it runs itself
        (reading a pair back, preparing the comparison) under the same refusal
        the replay proper runs under.
        """
        return replaying()

    def is_replaying(self) -> bool:
        """Whether this dynamic extent is the replay path — the predicate."""
        return is_replaying()
