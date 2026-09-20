"""Feature 154's record: one line, chained, and unable to hold a secret.

app_spec.xml, "Trust Zone Isolation & Secrets", feature 154: *System
persists an access audit record per read of the null sidecar key, which
exactly one service account may request.*  This suite is the record half
(:class:`infra.security.audit_log.AuditRecord` and
:func:`infra.security.audit_log.describe_reference`): the field set, the
canonical rendering the chain digest is taken over, and the redaction that
keeps a ``hex:`` reference's target — which *is* the key — out of the log.
The append-only log is in ``test_log.py``; the read chokepoint is in
``test_read.py``.
"""

from __future__ import annotations

import json

import pytest

from infra.security.audit_log import (
    GENESIS,
    AuditDecision,
    AuditRecord,
    AuditTrailError,
    describe_reference,
)


def _record(**overrides) -> AuditRecord:
    """A well-formed granted record, with fields overridable per test."""
    fields = {
        "sequence": 0,
        "previous_digest": GENESIS,
        "requester_account": "svc",
        "granted_account": "svc",
        "decision": AuditDecision.GRANTED,
        "reference_label": "kms:<redacted>",
        "reason": "the account the key is granted to read it",
        "timestamp": 1_700_000_000.0,
    }
    fields.update(overrides)
    return AuditRecord(**fields)


# -- the field set -------------------------------------------------------------


def test_a_granted_record_says_so() -> None:
    """``granted`` is the decision, not a separate flag that could disagree."""
    assert _record().granted is True
    assert _record(decision=AuditDecision.REFUSED).granted is False


def test_the_decision_vocabulary_is_closed() -> None:
    """A third outcome is refused — a read that neither happened nor was refused."""
    with pytest.raises(AuditTrailError):
        _record(decision="maybe")


def test_the_decision_vocabulary_is_two() -> None:
    """The vocabulary names both outcomes, so nothing enumerates it by hand."""
    assert AuditDecision.ALL == (AuditDecision.GRANTED, AuditDecision.REFUSED)


def test_a_negative_sequence_is_refused() -> None:
    """The chain position is a non-negative integer — a record knows where it sits."""
    with pytest.raises(AuditTrailError):
        _record(sequence=-1)


def test_a_bool_sequence_is_refused() -> None:
    """``True`` is not position 1: a truth value where a count belongs is a bug."""
    with pytest.raises(AuditTrailError):
        _record(sequence=True)


def test_a_non_integer_sequence_is_refused() -> None:
    """A string position cannot be walked, so it is refused rather than coerced."""
    with pytest.raises(AuditTrailError):
        _record(sequence="0")


def test_a_short_predecessor_link_is_refused() -> None:
    """A predecessor link is a 64-character digest, or it is not a link."""
    with pytest.raises(AuditTrailError):
        _record(previous_digest="abc")


def test_a_missing_predecessor_link_is_refused() -> None:
    """``None`` is not ``GENESIS``: the first record's link is spelled, not omitted."""
    with pytest.raises(AuditTrailError):
        _record(previous_digest=None)


# -- the rendering the chain is taken over -------------------------------------


def test_the_rendering_is_canonical() -> None:
    """The same fields serialise to the same bytes — sorted, unspaced, flat."""
    record = _record()
    rendered = record.to_json()
    assert rendered == json.dumps(json.loads(rendered), sort_keys=True, separators=(",", ":"))
    assert json.loads(rendered)["decision"] == AuditDecision.GRANTED


def test_the_rendering_is_a_flat_object_of_scalars() -> None:
    """Every field is a string, number or null — nothing nested, nothing free-form."""
    fields = json.loads(_record().to_json())
    assert set(fields) == {
        "decision",
        "granted_account",
        "previous_digest",
        "reason",
        "reference_label",
        "requester_account",
        "sequence",
        "timestamp",
        "version",
    }
    for value in fields.values():
        assert value is None or isinstance(value, (str, int, float))


def test_the_digest_covers_every_field() -> None:
    """Editing any one field changes the digest — which is what the chain is."""
    base = _record()
    for field, other in (
        ("requester_account", "someone"),
        ("granted_account", "someone"),
        ("decision", AuditDecision.REFUSED),
        ("reference_label", "hex:<redacted>"),
        ("reason", "another reason"),
        ("sequence", 7),
        ("previous_digest", "f" * 64),
        ("timestamp", 1_700_000_001.0),
    ):
        assert _record(**{field: other}).digest() != base.digest(), field


def test_the_digest_is_stable() -> None:
    """Two records with the same fields digest the same — the chain re-derives."""
    assert _record().digest() == _record().digest()
    assert len(_record().digest()) == 64


def test_the_version_is_carried_and_hashed() -> None:
    """A record declares its format, and a bumped version breaks the digest."""
    assert json.loads(_record().to_json())["version"] == 1
    assert _record(version=2).digest() != _record().digest()


# -- the field set cannot carry the key ----------------------------------------


def test_the_repr_names_the_decision_and_the_accounts() -> None:
    """A record's repr renders its fields — and the fields hold nothing secret."""
    text = repr(_record(requester_account="svc", decision=AuditDecision.REFUSED))
    assert "AuditRecord" in text
    assert "refused" in text
    assert "svc" in text


def test_the_repr_carries_no_key_material(key_material: bytes, hex_reference: str) -> None:
    """No rendering of a record contains the key — the field set cannot express it."""
    record = _record(reference_label=describe_reference(hex_reference))
    for rendering in (repr(record), record.to_json(), record.digest()):
        assert key_material.hex() not in rendering
    assert key_material.hex().encode() not in repr(record).encode()


def test_the_record_has_no_field_that_can_hold_a_reference_target(hex_reference: str) -> None:
    """The record's fields are identities, decisions and labels — never a target."""
    fields = json.loads(_record(reference_label=describe_reference(hex_reference)).to_json())
    assert "test-key-id" not in json.dumps(fields)
    assert "target" not in fields
    assert "key" not in fields
    assert "material" not in fields


# -- the redaction -------------------------------------------------------------


def test_a_kms_reference_keeps_its_scheme_and_loses_its_target(kms_reference: str) -> None:
    """``kms:<arn>`` logs as ``kms:<redacted>`` — the form, not the key id."""
    assert describe_reference(kms_reference) == "kms:<redacted>"
    assert "test-key-id" not in describe_reference(kms_reference)


def test_a_hex_reference_never_logs_its_target(hex_reference: str, key_material: bytes) -> None:
    """A ``hex:`` target *is* the key, so the label redacts it."""
    label = describe_reference(hex_reference)
    assert label == "hex:<redacted>"
    assert key_material.hex() not in label


def test_a_bare_string_is_redacted_whole() -> None:
    """A reference with no scheme is redacted entirely — nothing to keep."""
    assert describe_reference("/etc/nullius/sidecar-key") == "<redacted>"


@pytest.mark.parametrize(
    "value",
    [None, "", "   ", "kms:x", "sops:/a.age", "hex:00ff", "/a/path", "<redacted>", "<none>"],
)
def test_the_redaction_is_total(value) -> None:
    """Every shape reduces without raising — a log line is never a crash."""
    assert isinstance(describe_reference(value), str)


@pytest.mark.parametrize(
    "value",
    [None, "", "kms:x", "sops:/a.age", "hex:00ff", "/a/path", "<redacted>", "<none>"],
)
def test_the_redaction_is_idempotent(value) -> None:
    """Reducing an already-reduced label is that label — one parameter suffices."""
    once = describe_reference(value)
    assert describe_reference(once) == once


def test_a_non_string_is_redacted_rather_than_crashed() -> None:
    """A caller that hands a bytes reference gets a marker, not a TypeError."""
    assert describe_reference(b"hex:00") == "<redacted>"
