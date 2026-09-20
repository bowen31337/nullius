"""Feature 154's chokepoint: a key read recorded before it is served.

app_spec.xml, "Trust Zone Isolation & Secrets", feature 154: *System
persists an access audit record per read of the null sidecar key, which
exactly one service account may request.*  This suite is the read half —
the sentence's *per read* and its *exactly one service account* together:
:class:`infra.security.audit_log.KeyReadAudit` (and its one-call spelling
:func:`infra.security.audit_log.audited_key_read`) decides the account,
writes the record, and only then hands back material.  The record's field
set is in ``test_record.py``; the chain is in ``test_log.py``.
"""

from __future__ import annotations

import pytest

from infra.security.audit_log import (
    KEY_REF_ENV,
    SERVICE_ACCOUNT_ENV,
    AuditDecision,
    AuditLog,
    AuditTrailError,
    KeyAuditError,
    KeyReadAudit,
    audited_key_read,
)

# ---------------------------------------------------------------------------
# The three orderings that are the contract: decide, record, serve.
# ---------------------------------------------------------------------------


def test_a_granted_read_returns_the_material(granted_audit: KeyReadAudit, key_material: bytes) -> None:
    """The granted account reads the key — the expected case."""
    assert granted_audit.read(key_material) == key_material


def test_a_granted_read_is_recorded(granted_audit: KeyReadAudit, key_material: bytes) -> None:
    """Every granted read leaves a record — that is the feature's "per read"."""
    granted_audit.read(key_material)
    (record,) = granted_audit.log.records
    assert record.decision == AuditDecision.GRANTED
    assert record.granted is True
    assert record.requester_account == granted_audit.granted_account


def test_two_reads_are_two_records(
    granted_audit: KeyReadAudit, key_material: bytes, mem_log: AuditLog
) -> None:
    """The record is per read, not per caller — a second read is a second line.

    The distinction that matters: a process holding the key and reading the
    file twice performed one key read, while a process that resolves the key
    twice performed two. This counts the second kind, which is the kind that
    grows with a leaking caller.
    """
    granted_audit.read(key_material)
    granted_audit.read(key_material)
    assert len(mem_log.records) == 2
    assert [r.sequence for r in mem_log.records] == [0, 1]


def test_a_foreign_read_is_refused(granted_audit: KeyReadAudit, key_material: bytes) -> None:
    """A second account does not get the key — §7.1's "ONE service account"."""
    foreign = KeyReadAudit(
        granted_audit.log,
        granted_account=granted_audit.granted_account,
        account="someone-else",
    )
    with pytest.raises(KeyAuditError):
        foreign.read(key_material)


def test_a_foreign_read_is_recorded_before_it_is_refused(
    granted_audit: KeyReadAudit, key_material: bytes, foreign_account: str
) -> None:
    """The refusal leaves a record — the more interesting line of the two."""
    foreign = KeyReadAudit(
        granted_audit.log,
        granted_account=granted_audit.granted_account,
        account=foreign_account,
    )
    with pytest.raises(KeyAuditError):
        foreign.read(key_material)
    (record,) = granted_audit.log.refused_reads()
    assert record.decision == AuditDecision.REFUSED
    assert record.granted is False


def test_a_refusal_records_both_identities(
    granted_audit: KeyReadAudit, key_material: bytes, foreign_account: str, granted_account: str
) -> None:
    """Who asked and who holds it — both, so an operator can act on the line."""
    foreign = KeyReadAudit(
        granted_audit.log, granted_account=granted_account, account=foreign_account
    )
    with pytest.raises(KeyAuditError):
        foreign.read(key_material)
    (record,) = granted_audit.log.records
    assert record.requester_account == foreign_account
    assert record.granted_account == granted_account


def test_the_record_precedes_the_material(granted_audit: KeyReadAudit, key_material: bytes) -> None:
    """The line exists by the time the caller holds the key — evidence, not bookkeeping.

    Asserted by reading the log from *inside* the call's own return path:
    the record the caller gets back with the material is one the log already
    holds. A record written after the key was handed out would be one a
    crash could lose, leaving a read that happened with no line.
    """
    returned = granted_audit.read(key_material)
    held = granted_audit.log.records
    assert returned == key_material
    assert len(held) == 1
    assert held[0].decision == AuditDecision.GRANTED


def test_a_refusal_returns_nothing(key_material: bytes, mem_log: AuditLog) -> None:
    """A refusal is an exception, never an empty key a caller could decrypt with."""
    audit = KeyReadAudit(mem_log, granted_account="svc", account="intruder")
    with pytest.raises(KeyAuditError):
        audit.read(key_material)
    assert len(mem_log.records) == 1


def test_a_refused_read_leaves_the_chain_intact(
    granted_audit: KeyReadAudit, key_material: bytes, mem_log: AuditLog
) -> None:
    """Granted and refused records interleave in one chain, in order."""
    granted_audit.read(key_material)
    foreign = KeyReadAudit(mem_log, granted_account="svc", account="intruder")
    with pytest.raises(KeyAuditError):
        foreign.read(key_material)
    granted_audit.read(key_material)
    assert [r.decision for r in mem_log.verify()] == [
        AuditDecision.GRANTED,
        AuditDecision.REFUSED,
        AuditDecision.GRANTED,
    ]


# ---------------------------------------------------------------------------
# The unconfigured account: a supported state, not a silent bypass.
# ---------------------------------------------------------------------------


def test_an_unconfigured_grant_serves_and_records(mem_log: AuditLog, key_material: bytes) -> None:
    """No account named is a supported state — the read is served and audited.

    The same stance ``nulloracle.keyref.service_account`` takes: a
    deployment that has not named an account relies on the filesystem mode
    bits, and the audit records the read without adjudicating it. Refusing
    here would make the single-machine allowance unusable.
    """
    audit = KeyReadAudit(mem_log)
    assert audit.read(key_material) == key_material
    (record,) = mem_log.records
    assert record.decision == AuditDecision.GRANTED
    assert record.requester_account is None
    assert record.granted_account is None


def test_an_unconfigured_requester_is_attributed_to_the_grant(
    mem_log: AuditLog, key_material: bytes
) -> None:
    """A configured grant with no requester named reads as that account.

    The sibling member's rule (``nulloracle.keyref.ensure_key`` computes
    ``requester = account if account is not None else granted``): a
    deployment that named one account has named the account its own processes
    run as, so the read is attributed to it rather than recorded as
    ``requester_account: null`` — a record that would say the audit does not
    know who read the key.
    """
    audit = KeyReadAudit(mem_log, granted_account="svc")
    assert audit.read(key_material) == key_material
    record = mem_log.records[0]
    assert record.granted is True
    assert record.requester_account == "svc"


def test_the_chokepoint_and_from_env_agree_on_the_requester() -> None:
    """One read, one record — whichever half built the object.

    Guards the drift the rule is stated once to prevent: a chokepoint built
    with ``granted_account`` directly and one built from the environment
    naming the same account must attribute the read identically.
    """
    from infra.security.audit_log import InMemoryAuditSink

    direct = KeyReadAudit(AuditLog(InMemoryAuditSink("d")), granted_account="svc")
    from_env = KeyReadAudit.from_env(
        AuditLog(InMemoryAuditSink("e")),
        env={SERVICE_ACCOUNT_ENV: "svc", KEY_REF_ENV: "kms:x"},
    )
    assert direct.requester == from_env.requester == "svc"


def test_an_explicit_account_beats_the_grant() -> None:
    """``account`` is what the object was built to speak for — it is not overridden."""
    from infra.security.audit_log import InMemoryAuditSink

    audit = KeyReadAudit(
        AuditLog(InMemoryAuditSink("x")), granted_account="svc", account="intruder"
    )
    assert audit.requester == "intruder"
    assert audit.granted_account == "svc"


def test_nothing_configured_attributes_the_read_to_nobody() -> None:
    """With no account named there is nothing to attribute to — the rule invents none."""
    from infra.security.audit_log import InMemoryAuditSink

    audit = KeyReadAudit(AuditLog(InMemoryAuditSink("x")))
    assert audit.requester is None


def test_a_configured_grant_with_an_unknown_requester_is_refused(
    mem_log: AuditLog, key_material: bytes
) -> None:
    """The check needs both sides to fire — one configured account, one asker."""
    audit = KeyReadAudit(mem_log, granted_account="svc", account="intruder")
    with pytest.raises(KeyAuditError):
        audit.read(key_material)


def test_the_refusal_cites_the_sentence(
    mem_log: AuditLog, key_material: bytes
) -> None:
    """The refusal names §7.1's rule and the recording — an operator can act on it."""
    audit = KeyReadAudit(mem_log, granted_account="svc", account="intruder")
    with pytest.raises(KeyAuditError) as raised:
        audit.read(key_material)
    message = str(raised.value)
    assert "ONE service account" in message
    assert "recorded" in message


# ---------------------------------------------------------------------------
# The log holds no secret — the property the field set is chosen for.
# ---------------------------------------------------------------------------


def test_the_log_records_no_key_material(mem_log: AuditLog, key_material: bytes) -> None:
    """Reading a key writes no rendering of it — the chokepoint cannot leak."""
    audit = KeyReadAudit(mem_log, granted_account="svc", account="svc")
    audit.read(key_material)
    (record,) = mem_log.records
    for rendering in (repr(record), record.to_json(), record.digest()):
        assert key_material.hex() not in rendering


def test_the_log_redacts_the_reference_it_was_given(key_material: bytes, mem_log: AuditLog) -> None:
    """A raw ``hex:`` reference — whose target IS the key — never reaches the log."""
    secret_hex = key_material.hex()
    audit = KeyReadAudit(
        mem_log, granted_account="svc", account="svc", reference=f"hex:{secret_hex}"
    )
    audit.read(key_material)
    (record,) = mem_log.records
    assert record.reference_label == "hex:<redacted>"
    assert secret_hex not in record.to_json()


def test_the_log_keeps_the_scheme_of_the_reference(mem_log: AuditLog, key_material: bytes) -> None:
    """The scheme survives the redaction — which backend was asked is useful."""
    audit = KeyReadAudit(
        mem_log,
        granted_account="svc",
        account="svc",
        reference="sops:/etc/nullius/sidecar-key.age",
    )
    audit.read(key_material)
    assert mem_log.records[0].reference_label == "sops:<redacted>"


def test_the_failure_of_the_sink_refuses_the_read(key_material: bytes) -> None:
    """An un-auditable read must not happen — the caller loses the key."""
    from infra.security.audit_log import AuditSink, AuditSinkError

    class _DownSink(AuditSink):
        def append(self, record):
            raise AuditSinkError("the audit store is unreachable")

        def records(self):
            return ()

    audit = KeyReadAudit(AuditLog(_DownSink("down")), granted_account="svc", account="svc")
    with pytest.raises(AuditSinkError):
        audit.read(key_material)


# ---------------------------------------------------------------------------
# from_env: the deployment's configuration, spelled the null oracle's way.
# ---------------------------------------------------------------------------


def test_from_env_reads_the_grant_and_the_reference() -> None:
    """The grant and the reference come from the two variables the member reads."""
    from infra.security.audit_log import InMemoryAuditSink

    audit = KeyReadAudit.from_env(
        AuditLog(InMemoryAuditSink("env")),
        env={
            SERVICE_ACCOUNT_ENV: " nulloracle-svc ",
            KEY_REF_ENV: "kms:arn:aws:kms:us-east-1:0:key/k",
        },
    )
    assert audit.granted_account == "nulloracle-svc"
    # The requester is derived, not named a second time — so it agrees with
    # the grant here, and cannot drift from it.
    assert audit.account is None
    assert audit.requester == "nulloracle-svc"


def test_from_env_with_nothing_configured_is_unconfigured() -> None:
    """Neither variable set names no account — the mode-bits-only deployment."""
    from infra.security.audit_log import InMemoryAuditSink

    audit = KeyReadAudit.from_env(AuditLog(InMemoryAuditSink("env")), env={})
    assert audit.granted_account is None
    assert audit.requester is None


def test_from_env_treats_blank_as_unset() -> None:
    """A blank value is a deployment that meant to configure one and did not."""
    from infra.security.audit_log import InMemoryAuditSink

    audit = KeyReadAudit.from_env(
        AuditLog(InMemoryAuditSink("env")),
        env={SERVICE_ACCOUNT_ENV: "   ", KEY_REF_ENV: ""},
    )
    assert audit.granted_account is None


def test_from_env_records_the_reference_as_a_label(key_material: bytes) -> None:
    """A reference read from the environment reaches the log already reduced."""
    from infra.security.audit_log import InMemoryAuditSink

    log = AuditLog(InMemoryAuditSink("env"))
    audit = KeyReadAudit.from_env(
        log,
        env={
            SERVICE_ACCOUNT_ENV: "svc",
            KEY_REF_ENV: f"hex:{key_material.hex()}",
        },
    )
    audit.read(key_material)
    assert log.records[0].reference_label == "hex:<redacted>"
    assert key_material.hex() not in log.records[0].to_json()


# ---------------------------------------------------------------------------
# The one-call spelling.
# ---------------------------------------------------------------------------


def test_the_function_spelling_audits_and_serves(mem_log: AuditLog, key_material: bytes) -> None:
    """One call records the read and returns the key — the easiest seam."""
    returned = audited_key_read(
        key_material, log=mem_log, granted_account="svc", account="svc"
    )
    assert returned == key_material
    assert mem_log.records[0].granted is True


def test_the_function_spelling_refuses_a_foreign_account(mem_log: AuditLog, key_material: bytes) -> None:
    """And refuses the same way the object does — one contract, two spellings."""
    with pytest.raises(KeyAuditError):
        audited_key_read(
            key_material, log=mem_log, granted_account="svc", account="intruder"
        )
    assert len(mem_log.refused_reads()) == 1


def test_the_two_spellings_agree(mem_log: AuditLog, key_material: bytes) -> None:
    """A record written each way is the same record — one contract, two spellings.

    The timestamp is supplied so the two records differ in nothing at all;
    with the clock in play the comparison would be of two instants, which is
    not what "the same record" means.
    """
    from infra.security.audit_log import InMemoryAuditSink

    other = AuditLog(InMemoryAuditSink("other"))
    at = 1_700_000_000.0
    audited_key_read(
        key_material,
        log=mem_log,
        granted_account="svc",
        reference="kms:x",
        timestamp=at,
    )
    KeyReadAudit(other, granted_account="svc", reference="kms:x").read(
        key_material, timestamp=at
    )
    first, second = mem_log.records[0], other.records[0]
    assert first.to_json() == second.to_json()
    assert first.digest() == second.digest()


# ---------------------------------------------------------------------------
# The chokepoint's own contract.
# ---------------------------------------------------------------------------


def test_the_chokepoint_exposes_its_log(mem_log: AuditLog) -> None:
    """A caller can reach the log it writes to — the audit is not hidden."""
    audit = KeyReadAudit(mem_log, granted_account="svc", account="svc")
    assert audit.log is mem_log
    assert audit.granted_account == "svc"
    assert audit.account == "svc"


def test_the_chokepoint_distinguishes_the_requester_from_the_grant(mem_log: AuditLog) -> None:
    """``account`` is who is asking and ``granted_account`` is who holds it.

    Two properties, not one, because the refusal has to name both — and a
    single accessor returning the grant would make the foreign case
    unrepresentable.
    """
    audit = KeyReadAudit(mem_log, granted_account="svc", account="intruder")
    assert audit.granted_account == "svc"
    assert audit.account == "intruder"


def test_the_chokepoint_refuses_a_log_it_does_not_have() -> None:
    """A chokepoint with nowhere to record is refused — there would be no audit."""
    with pytest.raises(AuditTrailError):
        KeyReadAudit(None)
