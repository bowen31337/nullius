"""§7.1's schema, as a value: one node's null assignment.

app_spec.xml feature 109 persists *"null assignments"*; the architecture
fixes what one is (§7.1's ``{node_id: {is_null: bool, perm_seed: int,
block_days: int}}``).  This file pins the schema half of the feature, which
is deliberately testable with no key and no file: the shape of an
assignment, the refusals that keep a malformed one out of the sealed bytes,
and the canonical spelling that makes two sidecars from the same
assignments the same bytes.

The refusals are the load-bearing part.  Everything this file refuses would,
if it were instead coerced, produce a sidecar that opens *successfully* to
a world nobody designed — a real node wearing a null's parameters, a
permutation that cannot be reproduced, a node keyed under an id that joins
to nothing.  Those failures are silent by construction (the whole point of
§7.1 is that nobody can see the labels to notice), so the only place they
can be caught is here, at the write.
"""

from __future__ import annotations

import json
import uuid

import pytest

from nulloracle import (
    DEFAULT_BLOCK_DAYS,
    NullAssignment,
    SidecarError,
    assignments_digest,
    canonical_assignments,
    decode_assignments,
    encode_assignments,
    normalize_node_id,
)


def assignment(node_id: str, **overrides) -> NullAssignment:
    """An assignment for ``node_id``, with the defaults the tests vary."""
    fields = {"is_null": True, "perm_seed": 11}
    fields.update(overrides)
    return NullAssignment(node_id=node_id, **fields)


class TestTheBitIsAGenuineBool:
    # The one bit the entire system is forbidden from writing anywhere else
    # (§7.1: "There is no is_null column anywhere in the tree store"), and
    # the one that decides whether a node reports a real target or a
    # permuted one (§7.2).  A coercion here plants the wrong world silently.

    @pytest.mark.parametrize("value", [True, False])
    def test_a_genuine_bool_is_accepted(self, node_id: str, value: bool) -> None:
        assert assignment(node_id, is_null=value).is_null is value

    @pytest.mark.parametrize(
        "value",
        ["false", "true", "", 0, 1, 0.0, 1.0, None, [], {}, b"false"],
    )
    def test_anything_else_is_refused(self, node_id: str, value: object) -> None:
        # The string "false" is the one that matters most: it arrives from a
        # YAML document or a JSON body, it is truthy, and it means the exact
        # opposite of False.
        with pytest.raises(SidecarError, match="genuine bool"):
            assignment(node_id, is_null=value)

    def test_the_refusal_names_the_offending_type(self, node_id: str) -> None:
        with pytest.raises(SidecarError) as raised:
            assignment(node_id, is_null="false")
        assert "str" in str(raised.value)
        assert "'false'" in str(raised.value)


class TestThePermutationParameters:
    # Feature 115 reproduces a null node's block permutation from the stored
    # seed and the stored block length.  The word doing the work there is
    # "stored": a seed that cannot be re-read is a world no replay rebuilds.

    def test_the_default_block_length_is_the_twenty_days_of_the_doc(
        self, node_id: str
    ) -> None:
        # §7.2 spells it inline (block=20d) and feature 115 states it
        # ("a 20 day block length").
        assert assignment(node_id).block_days == DEFAULT_BLOCK_DAYS == 20

    def test_a_seed_of_zero_is_a_legitimate_seed(self, node_id: str) -> None:
        # Zero is a value a generator can return. Refusing it would make the
        # seed space look smaller than it is.
        assert assignment(node_id, perm_seed=0).perm_seed == 0

    @pytest.mark.parametrize("value", [-1, 1.5, "7", None, True, False])
    def test_a_seed_that_is_not_a_non_negative_int_is_refused(
        self, node_id: str, value: object
    ) -> None:
        # True/False are excluded deliberately even though bool subclasses
        # int: True is not a seed anyone meant to write.
        with pytest.raises(SidecarError, match="perm_seed"):
            assignment(node_id, perm_seed=value)

    @pytest.mark.parametrize("value", [0, -1, 2.5, "20", None, True])
    def test_a_block_length_that_is_not_positive_is_refused(
        self, node_id: str, value: object
    ) -> None:
        # Zero is the interesting refusal: a zero-day block permutation
        # permutes nothing, so the assignment would be a *real* node wearing
        # a null's parameters.
        with pytest.raises(SidecarError, match="block_days"):
            assignment(node_id, block_days=value)

    def test_a_block_length_other_than_the_default_is_stored_as_given(
        self, node_id: str
    ) -> None:
        # §7.4's detectability guard treats the block length as the knob an
        # operator investigates — "alert(nulls may be detectable —
        # investigate block length)" — so a non-default must survive rather
        # than being normalized back to 20.
        assert assignment(node_id, block_days=5).block_days == 5


class TestTheNodeIdentity:
    def test_a_uuid_object_is_normalized_to_canonical_text(self) -> None:
        raw = uuid.uuid4()
        assert assignment(raw).node_id == str(raw)

    def test_an_uppercase_string_normalizes_to_lowercase(self) -> None:
        raw = uuid.uuid4()
        assert normalize_node_id(str(raw).upper()) == str(raw)
        # ...because the two spellings are the same node, and a map that
        # held both would be a map with a phantom entry.
        assert assignment(str(raw).upper()).node_id == assignment(str(raw)).node_id

    def test_surrounding_whitespace_is_tolerated(self, node_id: str) -> None:
        assert assignment(f"  {node_id}\n").node_id == node_id

    @pytest.mark.parametrize(
        "value", ["", "   ", "not-a-uuid", "1234", None, 7, [], uuid.uuid4().hex[:-1]]
    )
    def test_a_non_uuid_is_refused(self, value: object) -> None:
        with pytest.raises(SidecarError, match="not a UUID"):
            normalize_node_id(value)

    def test_a_bare_hex_uuid_without_hyphens_is_accepted(self) -> None:
        # uuid.UUID parses the hyphenless form, so it is the same node and is
        # normalized rather than refused.
        raw = uuid.uuid4()
        assert normalize_node_id(raw.hex) == str(raw)


class TestTheCanonicalSpelling:
    # The sealed bytes.  Two sidecars written from the same assignments must
    # be byte-identical, or a replays' determinism claim (§12) is empty and
    # assignments_digest answers "different" for the same world.

    def test_the_spelling_is_compact_and_key_sorted(self, node_id: str) -> None:
        text = canonical_assignments({node_id: assignment(node_id)})
        assert " " not in text
        assert text == json.dumps(json.loads(text), sort_keys=True, separators=(",", ":"))
        # The field names are §7.1's own, not a private shorthand: the
        # sidecar is read by an operator's audit script and by feature 111's
        # backend alike.
        assert set(json.loads(text)[node_id]) == {"is_null", "perm_seed", "block_days"}

    def test_insertion_order_does_not_change_the_bytes(
        self, node_ids: "callable"
    ) -> None:
        first, second, third = node_ids(3)
        forward = [assignment(first), assignment(second), assignment(third)]
        shuffled = [assignment(third), assignment(first), assignment(second)]
        assert canonical_assignments(forward) == canonical_assignments(shuffled)
        assert assignments_digest(forward) == assignments_digest(shuffled)

    def test_a_mapping_and_an_iterable_of_the_same_assignments_agree(
        self, node_ids: "callable"
    ) -> None:
        # The two are the same set written two ways; a caller holding a list
        # should not have to build a dict to be understood.
        first, second = node_ids(2)
        values = [assignment(first), assignment(second)]
        assert canonical_assignments(values) == canonical_assignments(
            {value.node_id: value for value in values}
        )

    def test_the_digest_is_sixty_four_lowercase_hex(self, node_id: str) -> None:
        digest = assignments_digest([assignment(node_id)])
        assert len(digest) == 64
        assert digest == digest.lower()
        assert set(digest) <= set("0123456789abcdef")

    def test_two_different_worlds_have_two_different_digests(
        self, node_id: str
    ) -> None:
        # The comparison this digest exists to support, and the one an audit
        # without the key can make.
        real = assignments_digest([assignment(node_id, is_null=False)])
        null = assignments_digest([assignment(node_id, is_null=True)])
        assert real != null

    def test_a_mapping_whose_key_disagrees_with_its_value_is_refused(
        self, node_ids: "callable"
    ) -> None:
        # The key is the schema's identity, so a map that says a node is
        # keyed by one id while the value names another resolves no node at
        # all — refused rather than silently reconciled to either.
        first, second = node_ids(2)
        with pytest.raises(SidecarError, match="resolves no node"):
            canonical_assignments({first: assignment(second)})

    def test_a_non_assignment_value_is_refused(self, node_id: str) -> None:
        with pytest.raises(SidecarError, match="not a NullAssignment"):
            canonical_assignments({node_id: {"is_null": True}})


class TestTheRoundTripThroughTheSealedBytes:
    def test_everything_survives_encode_then_decode(self, node_ids: "callable") -> None:
        first, second = node_ids(2)
        original = {
            first: assignment(first, is_null=True, perm_seed=3, block_days=20),
            second: assignment(second, is_null=False, perm_seed=0, block_days=5),
        }
        decoded = decode_assignments(encode_assignments(original))
        assert decoded == original
        # ...and the values are equal as values, not merely as payloads.
        assert decoded[first].is_null is True
        assert decoded[second].is_null is False
        assert decoded[second].block_days == 5

    def test_an_empty_world_round_trips(self) -> None:
        # A campaign that assigned no nulls is a legitimate world, and it
        # must survive as a *statement* rather than as an absence — §7.4's
        # guard runs against whatever was written.
        assert encode_assignments({}) == b"{}"
        assert decode_assignments(b"{}") == {}

    def test_a_payload_that_is_not_utf8_is_refused_as_a_schema_problem(self) -> None:
        # Deliberately SidecarError and not SidecarDecryptionError:
        # authentication is not at issue here, the authenticated bytes are.
        with pytest.raises(SidecarError, match="not UTF-8"):
            decode_assignments(b"\xff\xfe\x00")

    def test_a_payload_that_is_not_json_is_refused_as_a_schema_problem(self) -> None:
        with pytest.raises(SidecarError, match="not JSON"):
            decode_assignments(b"node_id: abc\n")

    def test_a_json_that_is_not_an_object_is_refused(self) -> None:
        with pytest.raises(SidecarError, match="not the object"):
            decode_assignments(b"[1, 2, 3]")

    def test_an_entry_missing_a_field_is_refused_with_the_field_named(
        self, node_id: str
    ) -> None:
        # AES-GCM proves the bytes are the ones sealed; it does not prove
        # they are a schema this build understands.  An older or hand-edited
        # file must say so rather than half-load.
        payload = json.dumps({node_id: {"is_null": True, "perm_seed": 1}}).encode()
        with pytest.raises(SidecarError) as raised:
            decode_assignments(payload)
        assert "'block_days'" in str(raised.value)
        assert node_id in str(raised.value)

    def test_an_entry_that_is_not_a_mapping_is_refused(self, node_id: str) -> None:
        payload = json.dumps({node_id: True}).encode()
        with pytest.raises(SidecarError, match="not the mapping"):
            decode_assignments(payload)

    def test_a_coerced_bool_in_a_stored_payload_is_refused_on_the_way_back_in(
        self, node_id: str
    ) -> None:
        # The refusal is not merely a write-side courtesy: a file someone
        # edited by hand to say "false" is caught at the read too.
        payload = json.dumps(
            {node_id: {"is_null": "false", "perm_seed": 1, "block_days": 20}}
        ).encode()
        with pytest.raises(SidecarError, match="genuine bool"):
            decode_assignments(payload)
