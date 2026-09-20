"""Feature 111, the alert: the ``unrecoverable_state`` a failed decryption emits.

app_spec.xml, "Null Oracle & Planted Nulls", feature 111: *System resolves the
sidecar decryption key from KMS or sops, which emits an unrecoverable_state
alert when decryption fails.*  ``test_backends.py`` pins the resolution half —
the KMS call and the sops decryption.  This file pins the other half: what the
system does when a decryption fails, which §7's failure table is unusually
direct about::

    | Null sidecar key lost | Decrypt failure | **Unrecoverable.** All FDR
      history becomes uninterpretable. Back up the key to two independent
      stores |

Three claims, in the order the module argues them:

* **the alert is raised, and it carries its record.**  ``unrecoverable_state``
  is the spec's own spelling, it is the whole vocabulary of the alert
  (:data:`ALERT_KIND` is the only kind, and a record carrying another word is
  refused rather than stored), and the exception is a
  ``SidecarDecryptionError`` — §7 reads *Decrypt failure → Unrecoverable*, so
  the alert is a kind of decryption failure and every existing ``except
  SidecarDecryptionError`` still catches it.
* **the state outlives the process that found it.**  The journal appends; it
  never upserts.  The count of rows is the evidence — an operator choosing
  between a restore and a rebuild reads the span between the first row and the
  last — and a state that recurs is *two* observations, not one.  A deployment
  with no ``DATABASE_URL`` composes no journal and still gets the alert: the
  durability of §7's failure must not depend on the health of a database.
* **a malformed secret is not the alert.**  This is the distinction the whole
  feature rests on, and it is drawn in one place — ``guard_decryption``
  converts a ``SidecarDecryptionError`` and deliberately does *not* convert a
  ``SidecarKeyError``.  A mistyped reference has a repair that is not a
  restore, and paging someone about it would be a false alarm of the loudest
  kind.

The key itself is the thing this module must never widen access to: the record
stores the *redacted* scheme label (:meth:`KeyReference.scheme_label`) and the
detail is flattened and truncated, so a secret quoted into a backend's message
or a ``hex:`` reference's target cannot ride along into a log or a table.
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import pytest

from nulloracle import (
    ALERT_KIND,
    DATABASE_URL_ENV,
    KEY_ALERT_TABLE,
    KEY_BACKEND_STAGE,
    SIDECAR_STAGE,
    KeyAlertJournal,
    KeyReference,
    KsGuardError,
    NullAssignment,
    NullSidecar,
    SidecarDecryptionError,
    SidecarKey,
    SidecarKeyError,
    UnrecoverableState,
    UnrecoverableStateError,
    emit_unrecoverable_state,
    guard_decryption,
    load_key_alerts,
    unrecoverable_state_error,
)

HEX_32 = "ab" * 32
OTHER_HEX_32 = "cd" * 32
KMS_REF = "kms:arn:aws:kms:eu-west-1:1234:key/abc"


@pytest.fixture
def journal(tmp_path: Path) -> KeyAlertJournal:
    """A journal over a fresh SQLite file in this test's temporary directory."""
    return KeyAlertJournal(f"sqlite:///{tmp_path}/alerts.db")


@pytest.fixture
def cause() -> SidecarDecryptionError:
    """The refusal a tag failure would raise — what an alert is chained from."""
    return SidecarDecryptionError(
        "the sidecar's authentication tag did not verify"
    )


def _write_sidecar(path: Path, key_hex: str, node_id: str) -> None:
    """Seal one assignment into a sidecar at ``path`` under ``key_hex``.

    Permissions are set explicitly rather than left to the umask: §7.1's file
    is gated on *both* the file's mode and its directory's, and a sidecar the
    gate refuses would raise ``SidecarAccessError`` — a different failure from
    the one under test, reached before the cipher is ever consulted.  Getting
    this wrong is the trap this workspace has hit before: a hand-made sidecar
    with default modes raises an *access* error, and a test asserting on the
    decryption error then fails for a reason that has nothing to do with keys.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    sidecar = NullSidecar(path, SidecarKey.from_hex(key_hex))
    sidecar.write([NullAssignment(node_id=node_id, is_null=True, perm_seed=11)])
    path.chmod(0o600)


# -- The alert's vocabulary --------------------------------------------------


class TestTheAlertKindIsTheSpecsOwnWord:
    def test_the_kind_is_unrecoverable_state(self) -> None:
        # app_spec.xml feature 111: *"which emits an unrecoverable_state
        # alert"*.  Not a paraphrase: the word is what an operator greps for
        # and what a monitor dispatches on, so the spec's spelling is the
        # contract.
        assert ALERT_KIND == "unrecoverable_state"

    def test_the_two_stages_name_where_the_failure_is(self) -> None:
        # The stage sends an operator somewhere: the KMS grant or the wrapped
        # data key in the first case, the file on disk in the second.  Two
        # values, because those are the two places feature 111 can fail.
        assert KEY_BACKEND_STAGE == "key_backend"
        assert SIDECAR_STAGE == "sidecar"

    def test_the_table_is_member_owned_and_named_for_this_feature(self) -> None:
        assert KEY_ALERT_TABLE == "nulloracle_sidecar_key_alert"

    def test_the_database_variable_is_the_one_variable_every_store_reads(self) -> None:
        assert DATABASE_URL_ENV == "DATABASE_URL"

    @pytest.mark.parametrize(
        "overrides",
        [
            {"alert_kind": "unrecoverable"},
            {"alert_kind": "URGENT"},
            {"stage": "kms"},
            {"stage": "sops"},
            {"detail": ""},
        ],
    )
    def test_a_record_outside_the_vocabulary_is_refused(self, overrides) -> None:
        # Refused at construction, not at write: a row a reader of
        # unrecoverable_state cannot find is worse than no row, because it
        # looks like coverage.
        fields = {
            "alert_kind": ALERT_KIND,
            "stage": SIDECAR_STAGE,
            "detail": "the tag did not verify",
        }
        fields.update(overrides)
        with pytest.raises(KsGuardError):
            UnrecoverableState(**fields)

    def test_a_refusal_names_the_expected_word(self) -> None:
        with pytest.raises(KsGuardError, match=ALERT_KIND):
            UnrecoverableState(
                alert_kind="urgent", stage=SIDECAR_STAGE, detail="cause"
            )


# -- The record --------------------------------------------------------------


class TestTheRecord:
    def test_a_record_round_trips_through_its_row(self) -> None:
        state = UnrecoverableState(
            alert_kind=ALERT_KIND,
            stage=KEY_BACKEND_STAGE,
            detail="AccessDeniedException",
            reference="kms:<redacted>",
            detected_at="2026-01-01T00:00:00+00:00",
        )
        assert state.as_row() == (
            ALERT_KIND,
            KEY_BACKEND_STAGE,
            "kms:<redacted>",
            "AccessDeniedException",
            "2026-01-01T00:00:00+00:00",
        )

    def test_the_record_is_frozen(self) -> None:
        # A record a reader could mutate in place is a record two readers can
        # disagree about — and this one is both logged and persisted.
        state = UnrecoverableState(
            alert_kind=ALERT_KIND, stage=SIDECAR_STAGE, detail="cause"
        )
        with pytest.raises(Exception):
            state.detail = "something else"  # type: ignore[misc]

    def test_the_summary_is_deterministic(self, cause) -> None:
        # Two renderings of one state are byte-identical, so a test, a diff or
        # a monitor's dedup can compare them.
        alert = emit_unrecoverable_state(SIDECAR_STAGE, detail=cause)
        assert alert.alert.summary() == alert.alert.summary()

    def test_the_summary_names_the_kind_the_stage_and_the_cause(self, cause) -> None:
        alert = emit_unrecoverable_state(
            KEY_BACKEND_STAGE, reference=KMS_REF, detail=cause
        )
        summary = alert.alert.summary()
        assert ALERT_KIND in summary
        assert KEY_BACKEND_STAGE in summary
        assert "tag did not verify" in summary

    def test_a_reference_less_state_says_so_rather_than_rendering_none(self) -> None:
        # A caller sealing with material it already held has no reference to
        # name; "None" in an operator's log line would read as a key named
        # None.
        state = UnrecoverableState(
            alert_kind=ALERT_KIND, stage=SIDECAR_STAGE, detail="cause"
        )
        assert state.reference is None
        assert "None" not in state.summary()


# -- The emission ------------------------------------------------------------


class TestTheEmission:
    def test_it_returns_the_error_it_built(self, cause) -> None:
        alert = emit_unrecoverable_state(SIDECAR_STAGE, detail=cause)
        assert isinstance(alert, UnrecoverableStateError)

    def test_the_error_carries_the_record(self, cause) -> None:
        alert = emit_unrecoverable_state(SIDECAR_STAGE, detail=cause)
        assert isinstance(alert.alert, UnrecoverableState)
        assert alert.alert.alert_kind == ALERT_KIND

    def test_a_key_reference_is_stored_as_its_redacted_label(self) -> None:
        alert = emit_unrecoverable_state(
            KEY_BACKEND_STAGE, reference=KeyReference.parse(KMS_REF)
        )
        assert alert.alert.reference == "kms:<redacted>"

    def test_an_already_redacted_label_is_stored_verbatim(self) -> None:
        alert = emit_unrecoverable_state(
            KEY_BACKEND_STAGE, reference="sops:<redacted>"
        )
        assert alert.alert.reference == "sops:<redacted>"

    @pytest.mark.parametrize(
        "raw", [KMS_REF, "sops:/z0/null/key.enc.yaml", f"hex:{HEX_32}"]
    )
    def test_a_raw_reference_string_is_redacted_too_not_just_a_parsed_one(
        self, raw: str
    ) -> None:
        # The footgun this closes: a caller holding the reference as *text*
        # (which is what `NULL_SIDECAR_KEY_REF` is) passing it straight
        # through.  Stored verbatim, a `hex:` target puts the key in the
        # journal and in every log line — and the promise this module makes to
        # the rest of the system is that the alert never carries a target.  A
        # promise that holds only when the caller remembered to redact first
        # is not a promise, so the normalisation lives in the emission.
        alert = emit_unrecoverable_state(KEY_BACKEND_STAGE, reference=raw)
        assert alert.alert.reference == f"{raw.split(':')[0]}:<redacted>"
        assert raw.split(":", 1)[1] not in alert.alert.reference

    def test_a_raw_hex_reference_never_reaches_the_record_as_a_key(self) -> None:
        alert = emit_unrecoverable_state(
            SIDECAR_STAGE, reference=f"hex:{HEX_32}"
        )
        assert HEX_32 not in repr(alert.alert)
        assert HEX_32 not in str(alert)

    def test_a_string_that_is_not_a_reference_is_stored_as_given(self) -> None:
        # A caller's own tag or note.  Stored verbatim rather than refused:
        # there is no scheme to redact, and raising here would turn a logging
        # convenience into a source of exceptions inside an alert path.
        alert = emit_unrecoverable_state(SIDECAR_STAGE, reference="startup-check")
        assert alert.alert.reference == "startup-check"

    def test_a_raw_string_is_normalised_the_same_way_a_parsed_one_is(self) -> None:
        # Both spellings converge on one label, so two callers reporting the
        # same failure write byte-identical rows and a monitor's dedup works.
        parsed = emit_unrecoverable_state(
            KEY_BACKEND_STAGE, reference=KeyReference.parse(KMS_REF)
        )
        text = emit_unrecoverable_state(KEY_BACKEND_STAGE, reference=KMS_REF)
        assert parsed.alert.reference == text.alert.reference == "kms:<redacted>"

    def test_a_hex_reference_never_puts_the_key_on_the_record(self) -> None:
        # The sharp case: for `hex:` the target *is* the key, so the label is
        # the difference between a record and a leak.
        alert = emit_unrecoverable_state(
            SIDECAR_STAGE, reference=KeyReference.parse(f"hex:{HEX_32}")
        )
        assert alert.alert.reference == "hex:<redacted>"
        assert HEX_32 not in repr(alert.alert)
        assert HEX_32 not in str(alert)

    def test_the_error_message_states_the_consequence_and_the_repair(
        self, cause
    ) -> None:
        # The operator reading it is deciding between a restore and a rebuild;
        # §7 and §15 both answer *restore from backup*, and the message says
        # so rather than leaving them to look it up.
        message = str(emit_unrecoverable_state(SIDECAR_STAGE, detail=cause))
        assert "unrecoverable" in message
        assert "uninterpretable" in message
        assert "backup" in message

    def test_a_missing_detail_still_produces_a_cause(self) -> None:
        # An emission that names no cause would be the state §7 says must not
        # pass unnoticed, with nothing to act on.
        alert = emit_unrecoverable_state(KEY_BACKEND_STAGE)
        assert alert.alert.detail
        assert KEY_BACKEND_STAGE in alert.alert.detail

    def test_the_emission_works_with_no_journal_at_all(self, cause) -> None:
        # The alert's durability must never depend on a database being
        # present: a deployment with no relational store still gets paged.
        alert = emit_unrecoverable_state(SIDECAR_STAGE, detail=cause, journal=None)
        assert isinstance(alert, UnrecoverableStateError)

    def test_a_broken_journal_does_not_replace_the_alert(self, cause) -> None:
        # The central claim of the module's "the journal is not a gate"
        # promise, and the state it prevents: a deployment whose DATABASE_URL
        # is a scheme this store cannot speak composes a journal (the URL is
        # only inspected on first use), so *every* emission would raise the
        # storage error instead of §7's alert — a caller catching
        # `UnrecoverableStateError` would catch nothing, and the one fact §7
        # says must not pass unnoticed would pass unnoticed.
        #
        # Measured, not reasoned about: an earlier version re-raised the
        # storage error here while its docstring claimed the caller "sees both
        # facts".  It did not — the alert was gone.
        broken = KeyAlertJournal("postgresql://db.internal/nullius")
        alert = emit_unrecoverable_state(
            KEY_BACKEND_STAGE, detail=cause, journal=broken
        )
        assert isinstance(alert, UnrecoverableStateError)
        assert alert.alert.alert_kind == ALERT_KIND

    def test_a_broken_journal_is_reported_on_the_alert(self, cause) -> None:
        # "Does not replace" is not "is swallowed": a caller that needs the
        # state to be durable can tell, and an operator reading one page is
        # told not to go looking for a row that is not there.
        broken = KeyAlertJournal("postgresql://db.internal/nullius")
        alert = emit_unrecoverable_state(
            KEY_BACKEND_STAGE, detail=cause, journal=broken
        )
        assert alert.persistence_failure is not None
        assert "could NOT be written" in str(alert)
        assert "sqlite" in str(alert.persistence_failure)

    def test_a_working_journal_reports_no_persistence_failure(
        self, journal: KeyAlertJournal, cause
    ) -> None:
        alert = emit_unrecoverable_state(
            KEY_BACKEND_STAGE, detail=cause, journal=journal
        )
        assert alert.persistence_failure is None

    def test_no_journal_is_not_a_persistence_failure(self, cause) -> None:
        # Absent is not broken: a deployment keeping no relational store is a
        # supported configuration, and reporting it as a write failure would
        # make every alert in such a deployment look degraded.
        alert = emit_unrecoverable_state(KEY_BACKEND_STAGE, detail=cause)
        assert alert.persistence_failure is None

    def test_the_persistence_failure_does_not_leak_a_secret(self, cause) -> None:
        # The failure's message is composed by code this module does not own
        # and is folded into the alert's own text, so it is scrubbed the same
        # way a backend's message is.
        broken = KeyAlertJournal("postgresql://host/db")
        alert = emit_unrecoverable_state(
            KEY_BACKEND_STAGE, detail=RuntimeError(f"key {HEX_32} rejected"),
            journal=broken,
        )
        assert HEX_32 not in str(alert)

    def test_a_configured_journal_is_written_before_the_error_returns(
        self, journal: KeyAlertJournal, cause
    ) -> None:
        # Written before the return, so a caller that catches the alert to
        # keep reporting still leaves the state on record.
        emit_unrecoverable_state(SIDECAR_STAGE, detail=cause, journal=journal)
        assert len(journal.alerts()) == 1

    def test_the_journal_write_is_what_the_caller_raises(
        self, journal: KeyAlertJournal, cause
    ) -> None:
        alert = emit_unrecoverable_state(SIDECAR_STAGE, detail=cause, journal=journal)
        (record,) = journal.alerts()
        assert record == alert.alert

    def test_a_detected_at_may_be_supplied_for_a_deterministic_stamp(
        self, journal: KeyAlertJournal, cause
    ) -> None:
        # Pinned so a caller replaying a known observation (a reconciliation
        # script, a test) can stamp it exactly rather than approximately.
        emit_unrecoverable_state(
            SIDECAR_STAGE,
            detail=cause,
            journal=journal,
            detected_at="2026-01-01T00:00:00+00:00",
        )
        (record,) = journal.alerts()
        assert record.detected_at == "2026-01-01T00:00:00+00:00"

    def test_the_default_stamp_is_iso_utc(self, cause) -> None:
        stamp = emit_unrecoverable_state(SIDECAR_STAGE, detail=cause).alert.detected_at
        assert stamp.endswith("+00:00")
        assert "T" in stamp

    def test_it_refuses_to_build_an_alert_from_something_else(self) -> None:
        # `unrecoverable_state_error` composes its message from the record's
        # own fields; handed anything else it is an emission with no record
        # behind it.
        with pytest.raises(KsGuardError, match="UnrecoverableState"):
            unrecoverable_state_error("the key is gone")  # type: ignore[arg-type]

    def test_the_built_error_is_a_decryption_error(self, cause) -> None:
        # §7's row is literally *Decrypt failure → Unrecoverable*: the alert
        # is a kind of decryption failure, and every existing
        # `except SidecarDecryptionError` in the workspace keeps catching it.
        assert isinstance(
            emit_unrecoverable_state(SIDECAR_STAGE, detail=cause),
            SidecarDecryptionError,
        )

    def test_a_hand_built_error_may_carry_no_record(self) -> None:
        # `alert` is Optional because the subclass is constructible directly;
        # every error *this module* raises carries one.
        assert UnrecoverableStateError("the key is gone").alert is None


class TestTheDetailIsScrubbed:
    """The detail is composed by code this module does not own."""

    def test_newlines_are_collapsed(self) -> None:
        # One alert is one row in a log; a multi-line stderr pasted verbatim
        # would be a log entry an operator's grep cannot find the end of.
        alert = emit_unrecoverable_state(
            KEY_BACKEND_STAGE, detail=RuntimeError("first\nsecond\n\tthird")
        )
        assert "\n" not in alert.alert.detail
        assert "first second third" in alert.alert.detail

    def test_a_very_long_message_is_truncated(self) -> None:
        # A secret pasted into a backend's message must not ride along whole.
        alert = emit_unrecoverable_state(
            KEY_BACKEND_STAGE, detail=RuntimeError(HEX_32 * 20)
        )
        assert len(alert.alert.detail) <= 200

    def test_a_quoted_secret_does_not_survive_the_truncation(self) -> None:
        alert = emit_unrecoverable_state(
            KEY_BACKEND_STAGE,
            detail=RuntimeError(f"key {HEX_32} was rejected by the KMS"),
        )
        assert HEX_32 not in alert.alert.detail

    def test_a_secret_in_a_short_message_is_redacted_not_merely_cut(self) -> None:
        # The case truncation alone does *not* cover, and the reason the hex
        # rule exists: this message is 81 characters — well under the limit —
        # so a length bound would pass it through verbatim with the key intact.
        # A limit protects against a huge message; it does nothing about a
        # small one that is mostly secret.
        message = f"key {HEX_32} was rejected"
        assert len(message) < 200  # the bound would not have fired
        alert = emit_unrecoverable_state(
            KEY_BACKEND_STAGE, detail=RuntimeError(message)
        )
        assert HEX_32 not in alert.alert.detail
        assert "<redacted>" in alert.alert.detail

    @pytest.mark.parametrize("length", [32, 48, 64, 128])
    def test_a_hex_run_of_any_key_like_length_is_redacted(self, length: int) -> None:
        # 64 characters is one key; 128 is two.  A run shorter than 32 is not
        # key material and is left alone, which is what keeps the rule from
        # eating ordinary words.
        run = "ab" * (length // 2)
        alert = emit_unrecoverable_state(
            KEY_BACKEND_STAGE, detail=RuntimeError(f"rejected: {run}")
        )
        assert run not in alert.alert.detail

    def test_a_short_hex_fragment_is_left_alone(self) -> None:
        # The rule is bounded below on purpose: an error code, a short digest
        # prefix or a UUID fragment is not a key, and redacting it would cost
        # an operator the one detail that identified the failure.
        alert = emit_unrecoverable_state(
            KEY_BACKEND_STAGE, detail=RuntimeError("throttled after 4 attempts")
        )
        assert "throttled after 4 attempts" in alert.alert.detail

    def test_a_base64_secret_is_caught_by_the_truncation(self) -> None:
        # The hex rule does not see base64 — a 44-character base64 key is
        # indistinguishable from a word — so base64's protection is the
        # truncation plus the structural guarantee that the reference target
        # never reaches this function.  Pinned so the *coverage* is honest:
        # this test documents which of the two rules is doing the work.
        import base64

        encoded = base64.b64encode(bytes.fromhex(HEX_32)).decode()
        alert = emit_unrecoverable_state(
            KEY_BACKEND_STAGE, detail=RuntimeError(f"key {encoded} " + "x" * 300)
        )
        assert len(alert.alert.detail) <= 200

    def test_a_detail_carrying_no_text_falls_back_to_the_type(self) -> None:
        # An exception whose str() is empty still has a name, and the name is
        # more use to an operator than an empty cell.
        alert = emit_unrecoverable_state(KEY_BACKEND_STAGE, detail=RuntimeError())
        assert alert.alert.detail == "RuntimeError"

    def test_a_non_exception_detail_is_rendered_rather_than_refused(self) -> None:
        # The callers are backend adapters, and a raised value in Python need
        # not be an Exception; refusing would turn a decryption failure into
        # a type error.
        alert = emit_unrecoverable_state(KEY_BACKEND_STAGE, detail="sops: not found")
        assert "sops: not found" in alert.alert.detail


# -- The guard ---------------------------------------------------------------


class TestGuardDecryptionTurnsARefusalIntoTheAlert:
    """*which emits an unrecoverable_state alert when decryption fails.*"""

    def test_a_decryption_failure_inside_is_converted(self, cause) -> None:
        with pytest.raises(UnrecoverableStateError) as raised:
            with guard_decryption():
                raise cause
        assert raised.value.alert.stage == SIDECAR_STAGE

    def test_the_original_refusal_rides_along_as_the_cause(self, cause) -> None:
        # Nothing about *why* the tag failed is lost: an operator reading the
        # traceback sees the refusal and then the state it puts the
        # deployment in.
        with pytest.raises(UnrecoverableStateError) as raised:
            with guard_decryption():
                raise cause
        assert raised.value.__cause__ is cause

    def test_a_clean_block_is_left_alone(self) -> None:
        with guard_decryption():
            value = 1 + 1
        assert value == 2

    def test_an_unrelated_error_is_left_alone(self) -> None:
        # The guard is about decryption, not a blanket catch: a ValueError
        # from a caller's own arithmetic is the caller's to handle.
        with pytest.raises(ValueError):
            with guard_decryption():
                raise ValueError("not a decryption failure")

    def test_a_malformed_secret_is_not_converted(self) -> None:
        # The feature's central distinction.  A `SidecarKeyError` is a
        # *configuration* mistake — a mistyped reference, a short secret —
        # with a repair that is not a restore; converting it would page
        # someone about a lost key when the fix is to correct a variable.
        with pytest.raises(SidecarKeyError) as raised:
            with guard_decryption():
                raise SidecarKeyError("the sidecar key is 2 bytes")
        assert not isinstance(raised.value, UnrecoverableStateError)

    def test_a_malformed_secret_leaves_no_row_behind(self, journal) -> None:
        # The line drawn in the journal, not just in the exception type.
        with pytest.raises(SidecarKeyError):
            with guard_decryption(journal=journal):
                raise SidecarKeyError("the sidecar key is 2 bytes")
        assert journal.alerts() == ()

    def test_a_clean_block_writes_nothing(self, journal) -> None:
        with guard_decryption(journal=journal):
            pass
        assert journal.alerts() == ()

    def test_the_guard_still_raises_the_alert_over_a_broken_journal(
        self, cause
    ) -> None:
        # The guard is the path most callers take, so the "not a gate"
        # promise has to hold here too: a decryption failure routed through a
        # broken journal must still arrive as §7's alert.
        broken = KeyAlertJournal("postgresql://host/db")
        with pytest.raises(UnrecoverableStateError) as raised:
            with guard_decryption(journal=broken):
                raise cause
        assert raised.value.persistence_failure is not None
        assert raised.value.__cause__ is cause

    def test_a_conversion_persists_the_state(self, journal, cause) -> None:
        with pytest.raises(UnrecoverableStateError):
            with guard_decryption(reference=KMS_REF, journal=journal):
                raise cause
        (record,) = journal.alerts()
        assert record.stage == SIDECAR_STAGE
        assert record.alert_kind == ALERT_KIND

    def test_the_guard_records_the_reference_it_was_given(self, journal, cause) -> None:
        with pytest.raises(UnrecoverableStateError):
            with guard_decryption(journal=journal, reference=f"hex:{HEX_32}"):
                raise cause
        (record,) = journal.alerts()
        assert record.reference == "hex:<redacted>"
        assert HEX_32 not in repr(record)

    def test_a_nested_guard_does_not_record_the_same_observation_twice(
        self, journal, cause
    ) -> None:
        # A caller nesting this around a call that already emitted must not
        # append a second row for one observation: the count of rows is the
        # evidence of how long the deployment has been in the state, and
        # inflating it would make the span between first and last a lie.
        with pytest.raises(UnrecoverableStateError) as raised:
            with guard_decryption(journal=journal):
                with guard_decryption(journal=journal):
                    raise cause
        assert len(journal.alerts()) == 1
        assert raised.value.__cause__ is cause

    def test_an_alert_raised_inside_is_not_re_wrapped(self) -> None:
        # Re-wrapping would replace the original `__cause__` — the actual
        # decryption failure — with the alert that already named it.
        original = emit_unrecoverable_state(SIDECAR_STAGE, detail="the tag")
        with pytest.raises(UnrecoverableStateError) as raised:
            with guard_decryption():
                raise original
        assert raised.value is original

    def test_a_detected_at_can_be_pinned_for_a_deterministic_row(
        self, journal, cause
    ) -> None:
        with pytest.raises(UnrecoverableStateError):
            with guard_decryption(
                journal=journal, detected_at="2026-02-02T00:00:00+00:00"
            ):
                raise cause
        (record,) = journal.alerts()
        assert record.detected_at == "2026-02-02T00:00:00+00:00"


class TestTheGuardOverARealSidecar:
    """The emission wired to the thing it is about: a real sealed file."""

    def test_a_tampered_sidecar_open_emits_the_alert(self, tmp_path, journal) -> None:
        # The end-to-end shape of §7's row: a real sidecar, opened with the
        # wrong key, through the guard.  `open_envelope` raises its own tag
        # failure — which the caller reads as *this file did not
        # authenticate* — and the guard adds the fact about the deployment.
        path = tmp_path / "z0" / "null" / "sidecar.enc"
        _write_sidecar(path, HEX_32, str(uuid.uuid4()))
        wrong_key = NullSidecar(path, SidecarKey.from_hex(OTHER_HEX_32))
        with pytest.raises(UnrecoverableStateError) as raised:
            with guard_decryption(journal=journal):
                wrong_key.open()
        assert raised.value.__cause__ is not None
        assert isinstance(raised.value.__cause__, SidecarDecryptionError)
        assert raised.value.alert.stage == SIDECAR_STAGE

    def test_the_tampered_open_leaves_exactly_one_row(self, tmp_path, journal) -> None:
        path = tmp_path / "z0" / "null" / "sidecar.enc"
        _write_sidecar(path, HEX_32, str(uuid.uuid4()))
        with pytest.raises(UnrecoverableStateError):
            with guard_decryption(journal=journal):
                NullSidecar(path, SidecarKey.from_hex(OTHER_HEX_32)).open()
        assert len(journal.alerts()) == 1

    def test_a_clean_open_emits_nothing(self, tmp_path, journal) -> None:
        # The guard must be invisible on the happy path — a sidecar that
        # opens is not an alert, and a guard that recorded on every open
        # would fill the journal with noise an operator learns to ignore.
        path = tmp_path / "z0" / "null" / "sidecar.enc"
        node = str(uuid.uuid4())
        _write_sidecar(path, HEX_32, node)
        with guard_decryption(journal=journal):
            labels = NullSidecar(path, SidecarKey.from_hex(HEX_32)).open()
        assert labels[node].is_null is True
        assert journal.alerts() == ()

    def test_a_file_that_cannot_be_read_is_not_converted(self, tmp_path) -> None:
        # An unreadable sidecar is an access failure, not a decryption one:
        # §7.1's owner-only gate refused the read before any cipher ran, and
        # the repair is a permission fix rather than a restore.
        path = tmp_path / "z0" / "null" / "sidecar.enc"
        _write_sidecar(path, HEX_32, str(uuid.uuid4()))
        path.chmod(0o644)
        with pytest.raises(Exception) as raised:
            with guard_decryption():
                NullSidecar(path, SidecarKey.from_hex(HEX_32)).open()
        assert not isinstance(raised.value, UnrecoverableStateError)


# -- The journal -------------------------------------------------------------


class TestTheJournalIsAppended:
    def test_a_record_round_trips(self, journal) -> None:
        state = UnrecoverableState(
            alert_kind=ALERT_KIND,
            stage=KEY_BACKEND_STAGE,
            detail="AccessDeniedException",
            reference="kms:<redacted>",
            detected_at="2026-01-01T00:00:00+00:00",
        )
        journal.record(state)
        assert journal.alerts() == (state,)

    def test_recording_returns_the_record_unchanged(self, journal) -> None:
        # So the write composes into `emit_unrecoverable_state` without that
        # function needing to know anything about this store.
        state = UnrecoverableState(
            alert_kind=ALERT_KIND, stage=SIDECAR_STAGE, detail="cause"
        )
        assert journal.record(state) is state

    def test_the_same_state_recorded_twice_is_two_rows(self, journal) -> None:
        # Appended, never upserted.  A state that recurs — a process that
        # restarts and fails to decrypt again — is *two* observations of one
        # state, and the span between the first and the last is how long the
        # deployment has been in it.
        state = UnrecoverableState(
            alert_kind=ALERT_KIND,
            stage=SIDECAR_STAGE,
            detail="cause",
            detected_at="2026-01-01T00:00:00+00:00",
        )
        journal.record(state)
        journal.record(state)
        assert len(journal.alerts()) == 2

    def test_alerts_come_back_oldest_first(self, journal) -> None:
        for stamp in ("2026-01-03", "2026-01-01", "2026-01-02"):
            journal.record(
                UnrecoverableState(
                    alert_kind=ALERT_KIND,
                    stage=SIDECAR_STAGE,
                    detail=stamp,
                    detected_at=f"{stamp}T00:00:00+00:00",
                )
            )
        assert [r.detail for r in journal.alerts()] == [
            "2026-01-01",
            "2026-01-02",
            "2026-01-03",
        ]

    def test_two_alerts_in_the_same_second_keep_their_order(self, journal) -> None:
        # `detected_at` is second-resolution, so two alerts an instant apart
        # share a stamp; rowid is the tie-break, the same one the halt store
        # uses, and it is what an operator reconstructing an outage reads.
        for detail in ("first", "second", "third"):
            journal.record(
                UnrecoverableState(
                    alert_kind=ALERT_KIND,
                    stage=SIDECAR_STAGE,
                    detail=detail,
                    detected_at="2026-01-01T00:00:00+00:00",
                )
            )
        assert [r.detail for r in journal.alerts()] == ["first", "second", "third"]

    def test_latest_is_the_most_recent_state(self, journal) -> None:
        for detail in ("older", "newer"):
            journal.record(
                UnrecoverableState(
                    alert_kind=ALERT_KIND,
                    stage=SIDECAR_STAGE,
                    detail=detail,
                    detected_at=(
                        f"2026-01-0{1 if detail == 'older' else 2}T00:00:00+00:00"
                    ),
                )
            )
        assert journal.latest().detail == "newer"

    def test_latest_on_an_empty_journal_is_none(self, journal) -> None:
        # The question a startup check asks.  `None` means no alert has ever
        # been recorded — deliberately not the same fact as *healthy*, which
        # is why `resolve` answers `None` too and the two are kept apart.
        assert journal.latest() is None

    def test_alerts_on_an_empty_journal_is_empty(self, journal) -> None:
        assert journal.alerts() == ()

    def test_the_table_is_created_on_first_use(self, tmp_path) -> None:
        path = tmp_path / "nested" / "deeper" / "alerts.db"
        journal = KeyAlertJournal(f"sqlite:///{path}")
        assert journal.alerts() == ()
        assert path.exists()

    def test_creating_the_table_twice_is_a_no_op(self, journal) -> None:
        # `CREATE TABLE IF NOT EXISTS`: a fresh database and an existing one
        # take the same path, which is why this store needs no migration.
        for _ in range(3):
            journal.record(
                UnrecoverableState(
                    alert_kind=ALERT_KIND, stage=SIDECAR_STAGE, detail="cause"
                )
            )
        assert len(journal.alerts()) == 3

    def test_a_reopened_journal_keeps_the_rows(self, tmp_path) -> None:
        # The whole point of a journal: the state outlives the process that
        # found it.
        url = f"sqlite:///{tmp_path}/alerts.db"
        KeyAlertJournal(url).record(
            UnrecoverableState(
                alert_kind=ALERT_KIND, stage=SIDECAR_STAGE, detail="cause"
            )
        )
        assert len(KeyAlertJournal(url).alerts()) == 1

    def test_the_row_lands_in_the_named_table_with_the_named_columns(
        self, journal, cause
    ) -> None:
        emit_unrecoverable_state(
            SIDECAR_STAGE, reference=KMS_REF, detail=cause, journal=journal
        )
        connection = sqlite3.connect(journal.path)
        try:
            row = connection.execute(
                f"SELECT alert_kind, stage, reference, detail, detected_at "
                f"FROM {KEY_ALERT_TABLE}"
            ).fetchone()
        finally:
            connection.close()
        assert row[0] == ALERT_KIND
        assert row[1] == SIDECAR_STAGE
        assert row[2] == "kms:<redacted>"
        assert row[4].endswith("+00:00")

    def test_the_journal_refuses_a_record_of_anything_else(self, journal) -> None:
        # Duck-typed rather than `isinstance`-guarded, so that the composed and
        # canonically-imported module worlds agree (see
        # `test_key_alert_component.py::test_the_composed_journal_accepts_a_
        # directly_imported_record`) — but "duck-typed" is not "unchecked".  A
        # dict cannot name its kind, its stage, its cause and render itself,
        # and is refused.
        with pytest.raises(KsGuardError, match="UnrecoverableState"):
            journal.record({"alert_kind": ALERT_KIND})  # type: ignore[arg-type]

    def test_a_foreign_looking_record_that_satisfies_the_contract_is_accepted(
        self, journal
    ) -> None:
        # The other edge of the same rule, pinned so the check cannot quietly
        # become an `isinstance` again: a *structurally* valid record from
        # another module world is a record this store must keep.  The alias
        # split is the real case; a stand-in class is how a unit test states it
        # without a second import of the whole package.
        class _Record:
            alert_kind = ALERT_KIND
            stage = SIDECAR_STAGE
            detail = "the sidecar's tag did not verify"
            reference = "kms:<redacted>"
            detected_at = "2026-01-01T00:00:00+00:00"

            def as_row(self):
                return (
                    self.alert_kind,
                    self.stage,
                    self.reference,
                    self.detail,
                    self.detected_at,
                )

        journal.record(_Record())
        (record,) = journal.alerts()
        assert record.stage == SIDECAR_STAGE
        assert record.detail == "the sidecar's tag did not verify"


class TestTheJournalIsOptional:
    """A missing journal must never be the reason an alert goes unraised."""

    def test_resolve_is_none_without_a_database_url(self) -> None:
        assert KeyAlertJournal.resolve({}) is None

    @pytest.mark.parametrize("blank", ["", "   ", "\t"])
    def test_a_blank_database_url_counts_as_unset(self, blank: str) -> None:
        # The shape an unexpanded template leaves behind.
        assert KeyAlertJournal.resolve({DATABASE_URL_ENV: blank}) is None

    def test_resolve_returns_a_journal_when_one_is_named(self, tmp_path) -> None:
        url = f"sqlite:///{tmp_path}/alerts.db"
        journal = KeyAlertJournal.resolve({DATABASE_URL_ENV: url})
        assert journal is not None
        assert journal.database_url == url

    def test_resolve_does_not_touch_the_disk(self, tmp_path) -> None:
        # Composing the application resolves this store, and composition must
        # not open a database: the file is absent until the first read or
        # write.
        path = tmp_path / "never" / "alerts.db"
        KeyAlertJournal.resolve({DATABASE_URL_ENV: f"sqlite:///{path}"})
        assert not path.exists()

    def test_a_blank_database_url_is_refused_by_the_constructor(self) -> None:
        with pytest.raises(KsGuardError, match=DATABASE_URL_ENV):
            KeyAlertJournal("   ")

    def test_load_key_alerts_reads_a_named_journal(self, tmp_path) -> None:
        url = f"sqlite:///{tmp_path}/alerts.db"
        KeyAlertJournal(url).record(
            UnrecoverableState(
                alert_kind=ALERT_KIND, stage=SIDECAR_STAGE, detail="cause"
            )
        )
        assert len(load_key_alerts(url)) == 1

    def test_load_key_alerts_reads_the_environment(self, tmp_path) -> None:
        url = f"sqlite:///{tmp_path}/alerts.db"
        KeyAlertJournal(url).record(
            UnrecoverableState(
                alert_kind=ALERT_KIND, stage=SIDECAR_STAGE, detail="cause"
            )
        )
        assert len(load_key_alerts(env={DATABASE_URL_ENV: url})) == 1

    def test_load_key_alerts_raises_when_nothing_is_configured(self) -> None:
        # A caller that explicitly asked for the journal has asked a question
        # whose honest answer is "there is none" — unlike `resolve`, which is
        # asking whether one exists.
        with pytest.raises(KsGuardError, match=DATABASE_URL_ENV):
            load_key_alerts(env={})

    def test_the_error_names_the_variable_to_set(self) -> None:
        with pytest.raises(KsGuardError) as raised:
            load_key_alerts(env={})
        assert DATABASE_URL_ENV in str(raised.value)


class TestTheJournalRefusesAStoreItCannotHonour:
    def test_a_non_sqlite_scheme_is_refused_loudly(self) -> None:
        # Silently accepting a Postgres DSN and writing to a file named after
        # it would be a journal an operator never finds.
        journal = KeyAlertJournal("postgresql://host/db")
        with pytest.raises(KsGuardError, match="sqlite"):
            journal.alerts()

    @pytest.mark.parametrize("url", ["sqlite://", "sqlite:///:memory:"])
    def test_an_in_memory_database_is_refused(self, url: str) -> None:
        # An in-memory journal dies with the connection that opened it, and
        # §7's unrecoverable state is precisely the fact that must outlive the
        # process that discovered it.
        #
        # `sqlite:///:memory:` is the spelling every document in this workspace
        # uses, and it is the one that *looks* right while being wrong: the
        # third slash is the URL/path separator, so reading the parsed path
        # literally sends this to a file named `:memory:` — a journal that
        # appears configured and that no operator would ever find.  Pinned with
        # the documented spelling precisely because that is the one a reader
        # would reach for.
        journal = KeyAlertJournal(url)
        with pytest.raises(KsGuardError, match="in-memory"):
            journal.alerts()

    def test_an_in_memory_url_creates_no_file_named_memory(
        self, tmp_path, monkeypatch
    ) -> None:
        # The consequence of the bug above, asserted directly: the store must
        # not silently materialise a file literally called `:memory:` in the
        # process's working directory.
        monkeypatch.chdir(tmp_path)
        with pytest.raises(KsGuardError):
            KeyAlertJournal("sqlite:///:memory:").alerts()
        assert not (tmp_path / ":memory:").exists()

    def test_an_absolute_path_survives_the_separator_rule(self, tmp_path) -> None:
        # The other half of the same rule: `sqlite:////abs/path.db` carries two
        # leading slashes after the separator, and exactly one is dropped — so
        # the path stays absolute.  The root suite's DATABASE_URL is spelled
        # this way, which is why the rule matters beyond this file's tests.
        path = tmp_path / "alerts.db"
        journal = KeyAlertJournal(f"sqlite:///{path}")
        assert journal.path == path
        journal.record(
            UnrecoverableState(
                alert_kind=ALERT_KIND, stage=SIDECAR_STAGE, detail="cause"
            )
        )
        assert path.exists()

    def test_a_relative_path_is_taken_as_relative(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        journal = KeyAlertJournal("sqlite:///relative.db")
        assert journal.path == Path("relative.db")

    def test_a_host_carrying_sqlite_url_is_refused(self) -> None:
        # `sqlite://host/path` addresses a file, but reads like a URL that
        # points somewhere a host's name suggests.  Refused rather than
        # silently treated as a path.
        with pytest.raises(KsGuardError, match="host"):
            KeyAlertJournal("sqlite://example.com/var/lib/alerts.db").alerts()

    def test_the_refusal_names_the_variable(self) -> None:
        with pytest.raises(KsGuardError) as raised:
            KeyAlertJournal("mysql://host/db").alerts()
        assert DATABASE_URL_ENV in str(raised.value)
