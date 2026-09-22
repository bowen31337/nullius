"""Feature 226, the beta scalar — read once at initialization, fixed for the
whole episode.

app_spec.xml, "Exploration Policy Runtime", feature 226: *System rejects a
reassignment of the beta scalar after initialization, holding it fixed for the
whole episode.*  docs/nullius-tech-architecture.md §609 states the law verbatim
— *"``beta`` is read once in ``__init__``, fixed for the episode, routed through
a single ``_schedule(beta) -> dict`` so every threshold moves together.  Swept on
a grid offline.  This is carried over from the paper unchanged because it is what
makes cross-cycle comparison legible."* — and docs/alpha-engine-prd.md §7.4
carries it as the paper's own discipline.

The invariants these tests pin are the ones the guarantee depends on:

* **the scalar is the number** — :class:`EpisodeBeta` *is* a :class:`float`, not
  a wrapper around one, so the schedule (feature 227), the replay's arithmetic
  and the ``replay_score`` row all read the one value the episode was opened
  with, with no conversion at any seam for a second beta to drift through;
* **every reassignment path is refused** — attribute assignment (the value, an
  underscored spelling, a shadow attribute) and deletion alike raise
  :class:`BetaFixedError`, the class carries ``__slots__ = ()`` and so no
  ``__dict__``, and a caller reaching past the attribute protocol with
  ``object.__setattr__`` finds nothing to rebind: the guarantee is a fact about
  the type, not a promise in a docstring;
* **"after initialization" includes a second initialization** — a caller that
  re-invokes the initializer on a live scalar (``beta.__init__(x)``) cannot move
  it, because the value was bound in ``__new__`` and a second ``__init__``
  reaches no bind; a caller that calls ``__new__`` directly gets a *fresh*
  scalar carrying the new number rather than a mutation of the live one, which
  is the same rule observed from the construction side: a different beta is a
  different episode;
* **the value is read honestly** — a ``float`` and an ``int`` are accepted (a
  grid point is a number), while a ``bool``, text, ``None`` and a non-finite
  number are refused rather than coerced, because coercion is how a mistyped
  configuration becomes a silent episode;
* **the law has two sides and both are pinned** — the *read* (:func:`read_beta`
  refuses a value that is not a finite real number, so the episode is opened on
  a magnitude) and the *guard* (:class:`EpisodeBeta` refuses every path by which
  the scalar could move afterwards, so the magnitude the episode was opened on
  is the magnitude it is scored under).

The headline case is the feature's own sentence: a scalar read at
initialization and reassigned afterwards is refused, in the same words however
the author spelled the reassignment.
"""

from __future__ import annotations

import copy
import pickle

import pytest
from policy_runtime import (
    BetaFixedError,
    EpisodeBeta,
    PolicyRuntimeError,
    read_beta,
)

# ---------------------------------------------------------------------------
# The scalar is the number
# ---------------------------------------------------------------------------


def test_read_beta_returns_the_scalar_the_episode_was_opened_with() -> None:
    # The feature's verb: a runtime reads its episode's beta once and gets the
    # scalar every threshold is then derived from.  It is the number itself, so
    # feature 227's schedule and the replay's own arithmetic read it directly.
    beta = read_beta(0.7)
    assert beta == 0.7
    assert float(beta) == 0.7
    assert beta.value == 0.7


def test_beta_behaves_as_the_float_it_is() -> None:
    # A scalar, not a wrapper: comparisons, arithmetic, hashing and formatting
    # all answer as the float does, so no consumer has to unwrap it — which is
    # the seam a wrapper would put a second beta behind.
    beta = read_beta(0.7)
    assert beta < 0.8
    assert beta * 2 == pytest.approx(1.4)
    assert beta + 0.3 == pytest.approx(1.0)
    assert hash(beta) == hash(0.7)
    assert f"{beta:.1f}" == "0.7"
    assert isinstance(beta, float)


def test_beta_carries_no_dict_and_is_not_a_new_spelling_of_a_beta() -> None:
    # The read-only guarantee is only as strong as the object's inability to
    # grow new attributes — the stance contract.MarketWindow takes with its own
    # slots.  No __dict__, so there is nowhere for shadow state to live beside
    # the fixed scalar, and two episodes' scalars are two values rather than one
    # object wearing two numbers.
    beta = read_beta(0.7)
    assert not hasattr(beta, "__dict__")
    assert read_beta(0.7) is not beta
    assert read_beta(0.9) != beta


def test_beta_accepts_an_integer_grid_point() -> None:
    # A sweep grid is a set of numbers, and beta = 1 is a legitimate grid point
    # — the exploit-only end of the sweep.  An int is a real number, so it is
    # read; what is refused is a value that is not a magnitude at all.
    beta = read_beta(1)
    assert beta == 1.0
    assert isinstance(beta, float)


def test_beta_normalises_to_a_float() -> None:
    # The scalar read from an int grid point is the same float the same grid
    # point spelled 1.0 gives, so two episodes opened at one grid point carry
    # one scalar — the legibility docs §609 says the single-scalar discipline
    # exists to protect.
    assert read_beta(1) == read_beta(1.0)
    assert type(read_beta(1)) is type(read_beta(1.0))


# ---------------------------------------------------------------------------
# Every reassignment path is refused
# ---------------------------------------------------------------------------


def test_reassignment_of_the_value_is_refused() -> None:
    # The feature's own sentence: beta is fixed for the episode, so assigning
    # a new value to it after initialization raises.  A different beta is a
    # different episode, not a reassignment of this one.
    beta = read_beta(0.7)
    with pytest.raises(BetaFixedError):
        beta.value = 0.9
    assert beta == 0.7  # the refused write left the scalar where it was


def test_reassignment_of_an_underscored_spelling_is_refused() -> None:
    # The guard is not a name list: an author reaching for the storage behind
    # the property (``_value``) is refused the identical way, so there is no
    # private spelling that moves the scalar.
    beta = read_beta(0.7)
    with pytest.raises(BetaFixedError):
        beta._value = 0.9
    assert beta == 0.7


def test_shadow_attribute_is_refused() -> None:
    # Any attribute at all, because the class declares no slots: an accepted
    # assignment here could only be shadow state beside the fixed scalar, which
    # is the "grow new attributes" path the slots exist to close.
    beta = read_beta(0.7)
    with pytest.raises(BetaFixedError):
        beta.beta = 0.9
    assert beta == 0.7


def test_deletion_is_refused() -> None:
    # The same law from the other side: a scalar with no attributes cannot lose
    # one, and ``del beta.value`` reaching for the fixed value is the
    # reassignment it is not allowed to make.
    beta = read_beta(0.7)
    with pytest.raises(BetaFixedError):
        del beta.value
    assert beta == 0.7


def test_object_setattr_reaches_no_slot_to_rebind() -> None:
    # A caller reaching past the attribute protocol entirely — object.__setattr__
    # — finds no slot to rebind: the value lives in the float's own storage,
    # which is not an attribute, and the class declares none.  The guarantee is
    # therefore a fact about the type rather than a promise in a docstring.
    beta = read_beta(0.7)
    with pytest.raises(AttributeError):
        object.__setattr__(beta, "value", 0.9)
    with pytest.raises(AttributeError):
        object.__setattr__(beta, "shadow", 0.9)
    assert beta == 0.7


def test_a_second_initialization_cannot_move_the_scalar() -> None:
    # "After initialization" includes a caller reaching for the initializer a
    # second time.  The value was bound in the first __new__, and __init__ on a
    # live float reaches no bind at all — so the episode's beta is the one it
    # was opened with, however the caller spells the second attempt.  The
    # boundary contract.MarketWindow draws ("build a new window instead of
    # re-initializing this one") restated for a scalar.
    beta = read_beta(0.7)
    beta.__init__(0.9)  # type: ignore[misc]
    assert beta == 0.7


def test_a_second_construction_through_new_still_answers_the_original() -> None:
    # The other spelling of a second initialization: a caller calling __new__
    # directly on the instance's type and getting a *fresh* scalar back.  It is
    # a different scalar (a new object, correctly carrying the new number)
    # rather than a mutation of the live one — the same "a different beta is a
    # different episode" rule, observed from the construction side.
    beta = read_beta(0.7)
    other = EpisodeBeta.__new__(EpisodeBeta, 0.9)  # type: ignore[misc]
    assert other == 0.9
    assert beta == 0.7


def test_reassignment_is_refused_from_inside_a_policy_style_closure() -> None:
    # The refusal is unconditional and does not depend on who is asking: a
    # function holding the scalar as its own local — the shape an episode's step
    # function has — is refused in exactly the same words.  No frame is
    # privileged, which is what makes this a law rather than a convention.
    beta = read_beta(0.7)

    def step() -> None:
        beta.value = 0.1  # type: ignore[misc]

    with pytest.raises(BetaFixedError):
        step()
    assert beta == 0.7


def test_the_refusal_names_the_law_and_the_repair() -> None:
    # The refusal is an actionable sentence, not a bare TypeError: it names the
    # scalar, the feature and the reason — read once, every threshold derived
    # from it, a different beta is a different episode — so an author who
    # reassigned it reads what to do instead of what they broke.
    beta = read_beta(0.7)
    with pytest.raises(BetaFixedError) as raised:
        beta.value = 0.9
    message = str(raised.value)
    assert "fixed for the whole episode" in message
    assert "226" in message


def test_the_refusal_is_a_policy_runtime_error() -> None:
    # One base class for the read-side path: a caller catching
    # PolicyRuntimeError catches a moved scalar too, while a caller that catches
    # PolicyAdmissionRefusal — the gate's refusal, repaired by resubmitting a
    # policy — does not, because these are two different contracts in two
    # different places.
    beta = read_beta(0.7)
    with pytest.raises(PolicyRuntimeError):
        beta.value = 0.9
    assert issubclass(BetaFixedError, PolicyRuntimeError)


# ---------------------------------------------------------------------------
# The value is read honestly
# ---------------------------------------------------------------------------


def test_a_bool_is_refused_rather_than_read_as_one() -> None:
    # True is an int — the affinity trap the workspace's SQLite layer guards —
    # and beta = True is a flag that happens to have the value one, not a grid
    # point.  Refused by name, so a mistyped config surfaces at initialization
    # rather than becoming a silent exploit-only episode.
    with pytest.raises(BetaFixedError) as raised:
        read_beta(True)
    assert "bool" in str(raised.value)


def test_text_is_refused_rather_than_coerced() -> None:
    # A beta that arrives as "0.7" is not a number, and coercion is how a
    # mistyped configuration becomes a silent episode.  The safe direction is
    # to refuse and name what arrived.
    for value in ("0.7", b"0.7"):
        with pytest.raises(BetaFixedError):
            read_beta(value)


def test_none_and_objects_are_refused() -> None:
    # Nothing about an absent or unstructured value names a magnitude, so there
    # is no threshold to derive and nothing to fix the episode to.
    for value in (None, object(), [0.7], {"beta": 0.7}):
        with pytest.raises(BetaFixedError):
            read_beta(value)


def test_a_non_finite_beta_is_refused() -> None:
    # A NaN beta compares false against everything, so no threshold derived from
    # it is a threshold; an infinite beta is a magnitude no sweep grid yields
    # and no threshold survives.  Finiteness is the one numerical property the
    # law checks — no *band* is imposed, because which finite values a grid
    # tries is the deployment's business, not this law's.
    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(BetaFixedError):
            read_beta(value)


def test_an_integer_too_large_for_a_float_is_refused_in_the_members_own_error() -> None:
    # A magnitude beyond floating point derives no threshold, so it is refused —
    # and refused as a BetaFixedError, not as the OverflowError ``float()``
    # raises internally.  Letting the conversion's own exception escape would
    # hand a caller catching PolicyRuntimeError an exception it does not catch,
    # which is the error-vocabulary leak a member seam must not have.
    with pytest.raises(BetaFixedError):
        read_beta(10**400)


def test_the_refusal_for_an_unconvertible_value_is_a_policy_runtime_error() -> None:
    # The same guarantee from the caller's side: the one base class catches it.
    # This is the case that would have leaked OverflowError out of the member.
    with pytest.raises(PolicyRuntimeError):
        read_beta(10**400)


def test_other_real_number_types_are_read() -> None:
    # The rule is "a real number", spelled the way Python spells it — so a real
    # number that is neither a float nor an int is read too, rather than refused
    # for its spelling.  A Fraction is a real number on the line the scalar
    # lives on.
    from fractions import Fraction

    assert read_beta(Fraction(1, 2)) == 0.5
    assert read_beta(Fraction(3, 2)) == 1.5


def test_a_decimal_is_refused_rather_than_read_at_another_precision() -> None:
    # A Decimal is a *decimal* number while the scalar's arithmetic is binary
    # floating point, so accepting one would mean the episode ran at a precision
    # the configuration did not name — the silent-episode failure in a different
    # costume.  Refused, and a complex is not on the real line at all.
    from decimal import Decimal

    for value in (Decimal("0.7"), 1 + 0j):
        with pytest.raises(BetaFixedError):
            read_beta(value)


def test_a_zero_or_negative_beta_is_read_not_refused() -> None:
    # The law deliberately imposes no band.  Which finite betas a sweep grid
    # tries, and which one a cycle defaults to, is the deployment's and the
    # dreaming loop's business (docs §7.4: "swept on a grid during offline
    # evaluation; default chosen per cycle"), and refusing a value no document
    # forbids would be inventing a contract — the safe direction for a law is to
    # refuse only what is not a magnitude at all.
    for value in (0.0, -1.5, 1e-9, 1e9):
        assert read_beta(value) == value


def test_reading_refuses_before_any_scalar_exists() -> None:
    # A refused read constructs nothing: there is no half-built scalar to leak
    # out of the failing call and, in particular, no scalar a caller could hold
    # that carries a value the law never accepted.
    with pytest.raises(BetaFixedError):
        read_beta("0.7")
    assert read_beta(0.7) == 0.7  # the same call site still reads a good value


# ---------------------------------------------------------------------------
# The scalar survives the round trips a value type is expected to
# ---------------------------------------------------------------------------


def test_copy_and_pickle_answer_the_same_fixed_scalar() -> None:
    # An episode's beta crosses the seams a value type crosses — a copy into a
    # replay worker, a pickle to a cached episode — and each round trip must
    # give back the same scalar, equally fixed.  A rebuilt scalar that had
    # quietly become mutable would be the law defeated by serialization.
    beta = read_beta(0.7)
    for rebuilt in (copy.copy(beta), copy.deepcopy(beta), pickle.loads(pickle.dumps(beta))):
        assert rebuilt == 0.7
        assert isinstance(rebuilt, EpisodeBeta)
        with pytest.raises(BetaFixedError):
            rebuilt.value = 0.9


def test_beta_is_usable_as_a_mapping_key_and_a_json_field() -> None:
    # The two places the scalar is read by something other than Python: a
    # sweep's result table keyed by the grid point, and the replay_score row
    # that records which scalar a score was earned under (feature 106's
    # ``beta REAL NOT NULL``).  Both see the plain number.
    import json

    beta = read_beta(0.7)
    assert json.dumps({"beta": beta}) == '{"beta": 0.7}'
    assert {beta: "scored"}[0.7] == "scored"  # hashes as the float it is
