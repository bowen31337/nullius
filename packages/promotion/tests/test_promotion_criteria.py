"""The criteria: the six terms, and the one hash taken over them.

Feature 291's sentence has two halves — *a criteria hash*, and *recorded
before the deciding evaluation runs* — and this file holds the first.  The
second is ``test_promotion_pre_register.py``'s.

**What is asserted here is a *property*, not a value.**  A test that pinned
``criteria_hash`` to a literal hex digest would pin one spelling of one
document and would pass for a hash function that had been changed to
something with the same output by accident; the properties that make the hash
*usable as a check* are the ones that matter, and each one is a test below.
Two criteria that state the same terms must hash identically however they
were spelled or built — that is what makes a stored hash reproducible by a
later reader.  Two criteria that differ in any one term must hash
differently — that is what makes the hash evidence rather than decoration.
And the digest must be the sha256 of the canonical document, because that is
the one claim a reader of the row can independently verify:
``promotion_registry.criteria_hash`` is ``CHAR(64)``, and the reader's own
``hashlib.sha256(...).hexdigest()`` is the check.

**The canonical form is the reason the hash is reproducible, so it is tested
directly.**  A document rendered by another route — a plain dict, a mapping
built in another key order — must hash the same, and the tight separators and
sorted keys are what buy that.  The counterpart tests hold the other
direction: the document carries *every* field, because a hash that omitted a
criterion would not notice when that criterion changed.

**The validators are tested through the public constructor.**  ``theta`` and
the three counts and the two probabilities each have a boundary of their own,
and each boundary is argued in the module rather than asserted here — but the
*behaviour* is asserted, one case per refusal, because the argument is worth
nothing if the code does not make it.  ``bool`` is worth its own cases: it is
an ``int`` subclass in Python, so a validator that forgot the explicit check
would accept ``True`` where ``50`` belongs and persist the thinnest admissible
pool wearing a plausible number.
"""

from __future__ import annotations

import dataclasses as dc
import hashlib
import json
from dataclasses import fields as dc_fields

import pytest
from conftest import DEFAULT_CRITERIA_DOCUMENT
from promotion import CRITERIA_FIELDS, PromotionCriteria, PromotionError, criteria_hash
from promotion.criteria import (
    _validated_count,
    _validated_probability,
    _validated_real,
)


def _criteria(**overrides) -> PromotionCriteria:
    """The default criteria with the named terms overridden."""
    return PromotionCriteria(**{**DEFAULT_CRITERIA_DOCUMENT, **overrides})


# -- The six terms ----------------------------------------------------------------


def test_the_six_terms_are_the_field_set_the_value_carries() -> None:
    # The enumeration is spelled once as a constant and twice as fields, and
    # the two must agree: a constant listing a field the dataclass does not
    # carry would make every document-building loop raise, and a field the
    # constant omits would be a criterion the hash silently does not cover.
    assert set(CRITERIA_FIELDS) == set(DEFAULT_CRITERIA_DOCUMENT)
    assert CRITERIA_FIELDS == tuple(field.name for field in dc_fields(PromotionCriteria))
    # The order is the document's, and the document's is the order the PRD's
    # milestones read the terms in: the advantage, the test, the deployment
    # figure, then the three quantities of evidence.
    assert CRITERIA_FIELDS == (
        "theta",
        "alpha",
        "max_fdr_deploy",
        "min_worlds",
        "min_coverage_strata",
        "min_forward_days",
    )


def test_the_value_is_frozen_and_slots_ed() -> None:
    # Frozen because a criterion the caller could edit between the
    # pre-registration and the decision is precisely what §13 item 7 exists
    # to prevent: the hash would have been taken over values that no longer
    # hold.
    criteria = _criteria()
    with pytest.raises(dc.FrozenInstanceError):
        criteria.theta = 0.9
    assert not hasattr(criteria, "__dict__")


def test_two_criteria_stating_one_registration_compare_equal() -> None:
    # ``0.3`` and ``0.30`` are one bar: the reals canonicalise to the float
    # the column holds, so equality is equality of *values* rather than of how
    # a caller wrote them down — and two equal criteria hash identically,
    # which is what makes a stored digest reproducible by a reader.
    assert _criteria() == _criteria(theta=0.30)
    assert _criteria(theta=3 / 10) == _criteria()
    assert hash(_criteria()) == hash(_criteria(theta=0.3))
    assert criteria_hash(_criteria(theta=0.30)) == criteria_hash(_criteria())


def test_a_fractional_count_is_refused_rather_than_coerced() -> None:
    # The bounds of the canonicalisation, stated as its own test because the
    # temptation is real: ``int(50.0)`` is ``50`` and coercing would make a
    # cross-validated fold count of ``50.5`` silently mean a 50-world pool.
    # A count of worlds is a count, so the fraction is refused where the
    # float bar beside it is canonicalised.
    for field in ("min_worlds", "min_coverage_strata", "min_forward_days"):
        with pytest.raises(PromotionError) as raised:
            _criteria(**{field: 50.0})
        assert field in str(raised.value)


def test_the_document_is_a_fresh_mapping_of_the_six_terms() -> None:
    criteria = _criteria()
    document = criteria.document()
    assert document == DEFAULT_CRITERIA_DOCUMENT
    # A fresh mapping per call, so a caller cannot reach through the return
    # value into a later hash.
    document["theta"] = 99.0
    assert criteria.document()["theta"] == 0.3
    assert document is not criteria.document()


# -- The canonical form -----------------------------------------------------------


def test_the_canonical_form_sorts_keys_and_drops_whitespace() -> None:
    # Both choices are load-bearing and both are asserted as *text*, because
    # that is what the hash is taken over: reformatting the document — pretty
    # printing it into a log line — must not change its hash.
    canonical = _criteria().canonical()
    assert canonical == json.dumps(
        DEFAULT_CRITERIA_DOCUMENT, sort_keys=True, separators=(",", ":")
    )
    assert " " not in canonical
    assert canonical.startswith('{"alpha"')


def test_a_document_built_in_another_key_order_hashes_the_same() -> None:
    # The property the sorted keys buy, asserted through the thing a reader
    # actually does: rebuild the document from the stored row and check the
    # digest.  A key order the canonical form did not fix would make that
    # reader's check fail for a reason nobody decided.
    shuffled = dict(reversed(list(DEFAULT_CRITERIA_DOCUMENT.items())))
    assert list(shuffled) != list(DEFAULT_CRITERIA_DOCUMENT)
    canonical = json.dumps(shuffled, sort_keys=True, separators=(",", ":"))
    assert canonical == _criteria().canonical()


def test_the_hash_is_sha256_of_the_canonical_document() -> None:
    # The one claim a reader of the row can independently verify, and the
    # reason the column is CHAR(64).  Asserted by recomputing it here the way
    # the reader would, rather than by pinning a literal.
    criteria = _criteria()
    expected = hashlib.sha256(criteria.canonical().encode("utf-8")).hexdigest()
    assert criteria_hash(criteria) == expected
    assert criteria.digest == expected
    assert len(expected) == 64
    assert all(character in "0123456789abcdef" for character in expected)


def test_the_digest_is_hex_so_the_char_64_column_holds_it() -> None:
    digest = _criteria().digest
    assert digest == digest.lower()
    assert len(digest) == 64
    assert bytes.fromhex(digest)


@pytest.mark.parametrize(
    "changed",
    [
        {"theta": 0.31},
        {"alpha": 0.06},
        {"max_fdr_deploy": 0.24},
        {"min_worlds": 51},
        {"min_coverage_strata": 4},
        {"min_forward_days": 91},
    ],
)
def test_every_one_of_the_six_terms_moves_the_hash(changed: dict) -> None:
    # One case per term, deliberately — a hash that covered five of the six
    # would pass a test that varied one of the five.  This is the property
    # that makes the digest *evidence*: §13 item 7 fixes the criteria, and a
    # digest that did not notice a changed criterion would fix nothing.
    assert criteria_hash(_criteria(**changed)) != criteria_hash(_criteria())


def test_the_document_omits_no_term_at_a_default() -> None:
    # The counterpart of the test above from the other side: the document
    # carries every one of the six at its registered value, so a deployment
    # that leaves a term at the spec's own figure still hashes it.  A hash
    # that skipped defaults would call a deployment that configured the term
    # differently... identical.
    assert set(_criteria().document()) == set(CRITERIA_FIELDS)
    assert len(_criteria().canonical().split(",")) == len(CRITERIA_FIELDS)


# -- The hash's refusals ----------------------------------------------------------


@pytest.mark.parametrize("carrier", [None, 42, "theta=0.3", object()])
def test_a_carrier_with_no_canonical_document_is_refused(carrier: object) -> None:
    # A hash of *something else* recorded as a promotion's criteria is
    # exactly the row §13 item 7 exists to make impossible.
    with pytest.raises(PromotionError) as raised:
        criteria_hash(carrier)
    assert "canonical" in str(raised.value)


def test_a_canonical_that_is_not_text_is_refused() -> None:
    # Duck-typed rather than isinstance-checked, so a carrier of the right
    # *shape* is accepted — and a carrier of that shape returning something
    # that is not text has no one spelling to encode, which is a refusal
    # rather than a guess at ``str(...)``.
    class NotText:
        def canonical(self) -> bytes:
            return b'{"theta":0.3}'

    with pytest.raises(PromotionError) as raised:
        criteria_hash(NotText())
    assert "canonical" in str(raised.value)


def test_the_hash_duck_reads_the_canonical_seam() -> None:
    # The factory imports every member under a synthetic module name, so the
    # *composed* criteria value is structurally a PromotionCriteria but never
    # the same class object a direct import yields — an isinstance check here
    # would refuse the very value composition produced.  A plain carrier with
    # the one method is therefore accepted, which is the property asserted.
    class Carrier:
        def canonical(self) -> str:
            return _criteria().canonical()

    assert criteria_hash(Carrier()) == _criteria().digest


# -- The validators ---------------------------------------------------------------


@pytest.mark.parametrize("value", ["0.3", None, [0.3], {"theta": 0.3}, complex(0.3)])
def test_a_threshold_that_is_not_a_number_is_refused(value: object) -> None:
    with pytest.raises(PromotionError) as raised:
        _validated_real(value, "theta")
    assert "theta" in str(raised.value)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_a_threshold_that_is_not_finite_is_refused(value: float) -> None:
    # NaN compares false against everything, so a criterion holding one can
    # never be met *or* missed — a pre-registered criterion no evaluation can
    # decide is a promotion that can neither stand nor be refused.
    with pytest.raises(PromotionError) as raised:
        _validated_real(value, "theta")
    assert "finite" in str(raised.value)


def test_a_boolean_threshold_is_refused() -> None:
    # ``True`` is ``1`` in Python.  A flag where a threshold belongs would
    # persist as a plausible number rather than an error.
    with pytest.raises(PromotionError) as raised:
        _validated_real(True, "theta")
    assert "bool" in str(raised.value)
    with pytest.raises(PromotionError):
        _validated_count(True, "min_worlds")


def test_a_low_or_negative_advantage_bar_is_a_criterion_not_a_malformation() -> None:
    # The one term with no interval and no floor, deliberately: prd §12's M3
    # exit is ``> 0.3`` and §11.0's whole argument is that a bar too *low* is
    # the meta-overfitting failure — which is a judgement about evidence, and
    # belongs to the evaluation that has an M and a σ to compare the bar
    # against, not to the surface that writes the criteria down.  A negative
    # θ is also how a deployment says *must not be worse*.
    assert _criteria(theta=-0.5).theta == -0.5
    assert _criteria(theta=0.0).theta == 0.0
    assert _criteria(theta=2.0).theta == 2.0


@pytest.mark.parametrize("field", ["alpha", "max_fdr_deploy"])
@pytest.mark.parametrize("value", [-0.01, 1.01, 2.0, -1.0])
def test_a_probability_outside_the_unit_interval_is_refused(
    field: str, value: float
) -> None:
    # Above 1 α is not a level at all and a ceiling refuses nothing; below 0
    # a ceiling refuses everything.  Either way the promotion could not be
    # decided, which makes it a criterion no evaluation could fail.
    with pytest.raises(PromotionError) as raised:
        _validated_probability(value, field)
    assert field in str(raised.value)
    assert "[0, 1]" in str(raised.value)


@pytest.mark.parametrize("field", ["alpha", "max_fdr_deploy"])
@pytest.mark.parametrize("value", [0.0, 1.0, 0.05])
def test_both_ends_of_the_probability_interval_are_honoured(
    field: str, value: float
) -> None:
    # ``0.0`` and ``1.0`` are probabilities.  Whether such a bar is *wise* is
    # the deciding evaluation's question, not the pre-registration's — and a
    # validator that refused the ends would be overruling a decision the
    # deployment is entitled to make.
    assert _validated_probability(value, field) == value
    assert _criteria(**{field: value}).document()[field] == value


@pytest.mark.parametrize("field", ["min_worlds", "min_coverage_strata", "min_forward_days"])
def test_a_negative_count_is_refused(field: str) -> None:
    with pytest.raises(PromotionError) as raised:
        _validated_count(-1, field)
    assert field in str(raised.value)


@pytest.mark.parametrize("value", [50.0, "50", None, [50]])
def test_a_count_that_is_not_an_integer_is_refused(value: object) -> None:
    with pytest.raises(PromotionError):
        _validated_count(value, "min_worlds")


def test_zero_counts_are_counts() -> None:
    # A deployment that requires no evidence of one kind has made a decision;
    # it is not malformed.  (It is also not *wise* — prd §11.0's whole
    # argument is that a thin pool is where dreaming overfits — but the
    # wisdom of a bar is the evaluation's question.)
    assert _validated_count(0, "min_worlds") == 0
    assert _criteria(min_worlds=0, min_coverage_strata=0, min_forward_days=0).digest


def test_the_refusal_message_names_the_feature_and_the_term() -> None:
    # The message is the whole of what an operator sees, and the two facts it
    # must carry are *which term* and *which feature decided this*.
    with pytest.raises(PromotionError) as raised:
        _criteria(max_fdr_deploy=1.5)
    message = str(raised.value)
    assert "max_fdr_deploy" in message
    assert "feature 291" in message
