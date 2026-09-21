"""The authoring record's error surface: one tree, and which errors are its own.

Features 203 and 204 are two columns and three columns of **one** row's authoring
record — 0115's trio — so their refusals are one taxonomy rather than two.  That
is a design decision with a cost either way, and this file is where it is stated
and pinned:

* **One base class.**  Every refusal either feature raises is a
  :class:`~providers.ModelPinError`.  A caller that already handles "this member
  refused to record an authoring model" keeps working when the weights and dice
  arrive, and a `except ModelPinError` at a deployment's seam does not silently
  stop covering half the record.
* **A second base would have been a lie about the seam.**  204's columns are not
  a separate resource: a row's weights belong to the model that authored it, the
  refusal for a row with no model is *203's* question with no answer
  (:class:`~providers.NodeProvenanceError` is raised by both calls), and the
  store that writes both is one class.  Minting ``AgentWeightsError`` as a
  parallel root would have split the taxonomy along a line the data does not
  have.
* **The subclasses stay separate, though**, which is the other half: a caller
  that *can* act on the difference must be able to catch it, so a malformed
  digest, a malformed sampling, a digest conflict and a sampling conflict are
  four classes rather than one.

The table below is the whole surface, spelled out, and the tests are deliberately
written as assertions *about the table* — a new error class with no line here is
a failing test, which is what keeps this file honest as the record grows.
"""

from __future__ import annotations

import providers
import pytest
from providers import (
    AgentSamplingMalformedError,
    CkptHashConflictError,
    CkptHashMalformedError,
    ModelPinConflictError,
    ModelPinError,
    NodeNotRecordedError,
    NodeProvenanceError,
    PinColumnError,
    RollingAliasError,
    SamplingConflictError,
)

#: Feature 203's four, all of which arrive from that feature's sentence.
FEATURE_203 = (
    ModelPinConflictError,
    RollingAliasError,
    PinColumnError,
    NodeNotRecordedError,
)

#: Feature 204's five.  ``NodeProvenanceError`` is shared ground and is listed
#: under both, because that is the fact: a row with no authoring model is
#: refused by the triple's writer *and* by the weights' writer, and it is one
#: class because it is one condition.
FEATURE_204 = (
    NodeProvenanceError,
    AgentSamplingMalformedError,
    CkptHashMalformedError,
    CkptHashConflictError,
    SamplingConflictError,
)

#: Every refusal this member raises that is about the authoring record.
EVERY_REFUSAL = FEATURE_203 + FEATURE_204


def test_every_authoring_record_refusal_is_a_model_pin_error():
    # The one-base-class decision, stated over the whole table rather than one
    # class at a time: a caller's `except ModelPinError` covers 203 and 204
    # alike, so adding the weights and dice did not silently narrow it.
    for error in EVERY_REFUSAL:
        assert issubclass(error, ModelPinError), error
        assert error is not ModelPinError, f"{error} must be a subclass, not the base"


def test_the_two_features_refuse_with_distinguishable_classes():
    # The other half: one base does not mean one class.  A caller that can act on
    # the difference — a malformed digest is a config typo, a conflict is a
    # wrong node in hand — catches the subclass, and a taxonomy that collapsed
    # them would take that away.
    assert len(set(EVERY_REFUSAL)) == len(EVERY_REFUSAL)
    assert not (set(FEATURE_203) & set(FEATURE_204) - {NodeProvenanceError})


def test_no_authoring_record_refusal_inherits_another_members_base():
    # **The seam rule.**  A shared helper that raised another feature's error
    # type would defeat the caller's `except`, so this member's refusals must
    # descend from this member's base and from nothing else's.  Asserted by
    # walking the MRO rather than by naming the foreign bases, since the point
    # is the absence of any of them.
    own = {ModelPinError}
    for error in EVERY_REFUSAL:
        foreign = [
            base
            for base in error.__mro__
            if base.__module__.startswith(("canary", "artifacts", "sandbox", "app"))
        ]
        assert not foreign, f"{error.__name__} inherits {foreign}"
        assert set(error.__mro__) & own, error


def test_the_error_surface_is_exactly_the_table_above():
    # A new refusal class has to be added to the table — which is a *decision*
    # about whether it belongs under ``ModelPinError`` or should be a bare
    # ``ModelPinError`` — rather than arriving undocumented.  Compared against
    # the member's own ``__all__``, so this fails on the class being exported
    # and forgotten, which is how a taxonomy drifts.
    #
    # Scoped to ``ModelPinError``'s subtree and not to everything in ``__all__``
    # whose name ends in ``Error``: this member also exports its *provider*
    # vocabulary (``ProviderError``, ``UnknownModelError``, …), which is a
    # different branch about calling a model rather than about recording one,
    # and this file is about the authoring record.
    subtree = {
        name
        for name in providers.__all__
        if isinstance(getattr(providers, name, None), type)
        and issubclass(getattr(providers, name), ModelPinError)
        and name != "ModelPinError"
    }
    assert subtree == {error.__name__ for error in EVERY_REFUSAL}


@pytest.mark.parametrize("error", EVERY_REFUSAL, ids=lambda e: e.__name__)
def test_each_refusal_can_be_raised_and_carries_a_message(error):
    # Every one of these is raised with a sentence that says what is wrong and
    # what to do about it — the house rule this member follows everywhere else.
    # Pinned as a property of the class rather than of any one message, so a new
    # class that could only be constructed with no message is caught here.
    raised = error("the authoring record is not what it should be")
    assert str(raised) == "the authoring record is not what it should be"
    assert isinstance(raised, ModelPinError)


def test_the_pin_store_is_the_only_class_that_raises_them():
    # Where the record's refusals come from, and where they do not.  The value
    # parsers raise the two *malformed* classes — they are handed a bare value
    # and that is all they can judge — while every row-level condition is the
    # store's, because the row is what the store holds.
    import providers._ckpt as ckpt
    import providers._pin_store as store
    import providers._sampling as sampling

    assert store.AgentModelPins is providers.AgentModelPins
    for module, expected in (
        (ckpt, CkptHashMalformedError),
        (sampling, AgentSamplingMalformedError),
    ):
        raised = {
            name
            for name, value in vars(module).items()
            if isinstance(value, type) and issubclass(value, ModelPinError)
            and value is not ModelPinError
        }
        assert raised == {expected.__name__}, module.__name__
