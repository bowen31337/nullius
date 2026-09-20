"""Feature 111's alert: the ``unrecoverable_state`` a failed decryption emits.

app_spec.xml, "Null Oracle & Planted Nulls", feature 111: *System resolves
the sidecar decryption key from KMS or sops, which emits an
unrecoverable_state alert when decryption fails.*  docs/nullius-tech-
architecture.md §7's failure table gives the failure its own row and its
verdict::

    | Null sidecar key lost | Decrypt failure | **Unrecoverable.** All FDR
      history becomes uninterpretable. Back up the key to two independent
      stores |

and §15 repeats it as the one entry that is not a repair — *"Null sidecar key
lost → Decrypt failure → Unrecoverable."*  The null labels (feature 109, §7.1's
sealed sidecar) are the only place a node's status is written down, and they
are sealed under a key nothing else holds the plaintext of; when that key is
gone, every score the system has ever produced keeps its number and loses its
meaning at the same instant, silently.

**The failure is called *unrecoverable*, not *urgent*, and the difference
orders every decision here.**  An urgent failure is one an operator fixes by
acting; this one is a state the deployment is *in* — there is no retry that
brings a lost key back, no repair short of restoring from backup (feature 155's
two independent stores), and no amount of waiting that improves it.  So the
work of this module is not to retry, to fall back, or to degrade: it is to
*make the state visible and durable*, because the one thing §7 says cannot be
allowed is that it passes unnoticed.  A process that catches a decryption
failure and carries on computing has produced exactly the FDR this row warns
about — one computed over a world whose nulls have silently become real.

**The emission is a raise, and the raise carries the record.**  The workspace's
two sibling alert features settled this shape and this module follows it
deliberately: :func:`canary.halt_dreaming` writes one row and then raises
:class:`~canary.CanaryDeterminismBrokenError` carrying the halt, and
:mod:`snapshot` raises its corruption error carrying the alert — in both, *the
raise is the emission and the record is the payload*.  §7's row is a state, so
a bare log line is not enough (it scrolls away, and a monitor cannot dispatch
on it), and a bare exception is not enough either (a caller that catches it to
keep reporting would leave nothing behind).  :func:`emit_unrecoverable_state`
therefore builds an :class:`UnrecoverableState` *and* appends it to the journal
when one is configured, and returns the error for the caller to raise; the
journal is written **before** the raise, so a caller that catches the alert
still leaves the state on record.

**The journal is a member-owned table, created idempotently, and optional.**
``CREATE TABLE IF NOT EXISTS`` beside the code that reads it — the stance
:mod:`nulloracle.ksguard` and :mod:`canary._halt` both take, and deliberately
not a migration: a migration is loaded by path by its runner and orders against
every other version file, while this table has exactly one writer and one
reader, both in this module.  A deployment with no ``DATABASE_URL`` composes
no journal and still gets the alert — the record is the durable half, and its
absence must never be the reason an alert goes unraised.

**``UnrecoverableStateError`` is a :class:`~nulloracle.errors.
SidecarDecryptionError`.**  §7 calls this literally *Decrypt failure →
Unrecoverable*, so the alert is a *kind* of decryption failure rather than a
replacement for the refusal that family already states: every existing
``except SidecarDecryptionError`` in the workspace — the target route's, the
selection's, the plan gate's — still catches it, and a caller that wants the
alert specifically catches the subclass.  ``envelope.open_envelope`` raised the
underlying tag failure and it rides along as ``__cause__``, so an operator
reading a traceback sees the original refusal and then the state it puts the
deployment in.  A subclass rather than a fold, because the two facts are
different for the reader: *this file did not authenticate* is a fact about a
file, and *the key is gone and all recorded calibration is uninterpretable* is
a fact about the deployment.

**The alert never carries the reference target.**  :attr:`KeyReference.
scheme_label` already redacts it — a ``kms:`` ARN and a ``sops:`` path are not
secrets, but a ``hex:`` target *is* the key itself — so the record stores the
label and not the target, and the module never composes a message from
``reference.target``.  The alert is a thing that ends up in a log an operator
reads and a table a monitor sweeps; it is the last place in the system the one
secret §1 says *"silently voids every calibration number the system has ever
produced"* should surface.
"""

from __future__ import annotations

import os
import re
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote, urlparse

from .errors import KsGuardError, SidecarDecryptionError, SidecarKeyError
from .keyref import KeyReference

__all__ = [
    "ALERT_KIND",
    "DATABASE_URL_ENV",
    "KEY_BACKEND_STAGE",
    "KEY_ALERT_TABLE",
    "SIDECAR_STAGE",
    "KeyAlertJournal",
    "UnrecoverableState",
    "UnrecoverableStateError",
    "emit_unrecoverable_state",
    "guard_decryption",
    "load_key_alerts",
    "unrecoverable_state_error",
]

#: The alert's kind — the spec's own spelling, verbatim.  app_spec.xml feature
#: 111: *"which emits an unrecoverable_state alert"*.  Not a free-form message
#: field, and not a paraphrase: the word is what an operator greps for, what a
#: monitor dispatches on, and what §7's failure table means by *Unrecoverable*.
#: The sibling alerts spell theirs the same way (:data:`canary.DETERMINISM_
#: BROKEN`, ``snapshot``'s corruption kind), because an alert a reader cannot
#: find by the name the spec gave it is an alert the spec did not get.
ALERT_KIND = "unrecoverable_state"

#: The stage that failed: the key's own backend, before any sidecar was read.
#:
#: The KMS call or the ``sops`` decryption is where feature 111's resolution
#: happens, and it is where the failure is *known* to be about the key rather
#: than about a file: nothing has been opened yet.  Distinguished from
#: :data:`SIDECAR_STAGE` because the two send an operator to different places —
#: here to the KMS grant and the wrapped data key, there to the file on disk and
#: the key it was sealed under.
KEY_BACKEND_STAGE = "key_backend"

#: The stage that failed: the sidecar's own authentication, after a key was
#: resolved.  GCM's tag did not verify, which §7's row reads as *Decrypt
#: failure* — the file was altered, or the key resolved to is not the one it
#: was sealed under.
SIDECAR_STAGE = "sidecar"

#: The environment variable naming the relational store the journal writes to.
#:
#: The one spelling every store in this workspace already uses (the guard's, the
#: fraction's, the verdict's, the canary's halt store), restated here rather than
#: imported so this module states its own contract and imports no sibling's.
DATABASE_URL_ENV = "DATABASE_URL"

#: This feature's provenance table — one row per unrecoverable state observed.
#:
#: Member-owned and created idempotently, like :data:`nulloracle.ksguard.
#: KS_GUARD_TABLE` and ``canary._halt``'s ``canary_dream_halt``: exactly one
#: writer and one reader, both in this module, so it needs no migration and
#: orders against no other version file.
KEY_ALERT_TABLE = "nulloracle_sidecar_key_alert"

#: ``nulloracle_sidecar_key_alert``'s DDL.  One row per detection, appended —
#: never refreshed.  A state that recurs (a process that restarts and fails to
#: decrypt again) is *two* observations of one state, and collapsing them to a
#: primary key would destroy the only evidence of how long the deployment has
#: been in it: an operator deciding between restoring a backup and rebuilding
#: the pool reads the span between the first row and the last.  The sibling
#: halt store keys its rows because a halt is idempotent by design; an alert is
#: not, and the difference is deliberate.
#:
#: `reference` carries the *redacted* label (:meth:`KeyReference.scheme_label`)
#: and never the target — a `hex:` target is the key.  `detail` is the failing
#: call's own message, scrubbed of any secret the backend might have quoted.
_KEY_ALERT_SCHEMA = f"""
-- Feature 111: an unrecoverable_state, persisted as the state the deployment
-- is in.  One row per detection, appended, because the span between the first
-- row and the last is how long the deployment has been in this state -- the
-- datum an operator choosing between a restore and a rebuild reads.
--
-- `stage` is 'key_backend' (the KMS call or sops decryption failed) or
-- 'sidecar' (a key resolved and GCM's tag did not verify); `reference` is the
-- redacted scheme label, never the target.
CREATE TABLE IF NOT EXISTS {KEY_ALERT_TABLE} (
    alert_kind  TEXT NOT NULL,  -- 'unrecoverable_state', the spec's spelling
    stage       TEXT NOT NULL,  -- 'key_backend' or 'sidecar'
    reference   TEXT,           -- the redacted scheme label, e.g. 'kms:<redacted>'
    detail      TEXT NOT NULL,  -- the failing call's message, secret-scrubbed
    detected_at TEXT NOT NULL   -- when the state was observed (ISO-8601 UTC)
);
"""

#: The columns of :data:`KEY_ALERT_TABLE`, in the order the insert names them
#: and the order the read-back unpacks them.  Spelled once so the write and the
#: read cannot drift apart on a column order — the failure a positional
#: ``SELECT *`` invites.  The sibling stores spell theirs the same way.
_COLUMNS = "alert_kind, stage, reference, detail, detected_at"


def _isoformat_now() -> str:
    """The current instant as ISO-8601 UTC text, second resolution.

    Microseconds are dropped rather than rounded, the same spelling
    :func:`canary._halt._utc_now` and :func:`ledger.record.utc_now` use,
    restated here rather than imported so this module states its own contract:
    dropping keeps a stamp never *after* the instant it names, so two alerts an
    instant apart still order correctly in the journal.
    """
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


#: How long a failure's own message may be before it is truncated on its way
#: into a record.  Long enough to name the call that failed and quote a backend
#: error verbatim, short enough that a secret pasted into a message cannot ride
#: along whole.
#:
#: The bound is on the *hex* the message could carry, not on the text: a
#: 32-byte key is 64 characters, so a limit comfortably above 64 would let a
#: key that appeared at the *end* of a long message survive the cut untouched.
#: See :data:`_HEX_RUN` for the check that closes the remaining gap.
_DETAIL_LIMIT = 200

#: A run of hex characters long enough to be key material — 64 is one AES-256
#: key spelled out, and 32 is its shortest unambiguous prefix (the member's
#: whole key vocabulary is hex and base64, and a 32-character hex run is not a
#: thing a backend error message says for any other reason).
_HEX_RUN = re.compile(r"\b[0-9a-fA-F]{32,}\b")


def _scrubbed(failure: Any) -> str:
    """A failure's message, flattened and redacted for the detail column.

    The detail is read by an operator and swept by a monitor, and the message it
    comes from is composed by code this module does not own — a ``sops``
    invocation's stderr, a KMS SDK's ``ClientError`` string.  A message that
    quoted the plaintext it failed to use would be the one leak §1 says the
    system would never notice, so the message is not trusted:

    * newlines are collapsed, so one alert is one row in a log;
    * any hex run long enough to be key material is replaced by a placeholder —
      because truncating alone does not make a message safe, and the arithmetic
      is unforgiving: a 32-byte key is 64 characters, so a key quoted at the end
      of a 60-character message survives a 200-character cut completely intact.
      Measured, not assumed: a bare ``f"key {key} was rejected"`` is 81
      characters and used to pass through verbatim;
    * the remainder is truncated, so a message that is *mostly* secret cannot
      leave a long fragment of one behind.

    The hex rule is deliberately the *only* content rule.  A general secret
    scrubber would be a second, disagreeing implementation of a policy the
    member already enforces structurally — the reference *target* is never read
    on any path that reaches here, so the one string guaranteed to be key
    material is already absent — while the hex run is the one shape a backend's
    own error text can carry a key in, and it is cheap to look for.  This is the
    belt to that braces, not the braces.
    """
    text = " ".join(str(failure).split())
    text = _HEX_RUN.sub("<redacted>", text)
    if len(text) > _DETAIL_LIMIT:
        text = text[: _DETAIL_LIMIT - 1] + "…"
    return text or type(failure).__name__


@dataclass(frozen=True)
class UnrecoverableState:
    """Feature 111's ``unrecoverable_state``: the record, and the state it names.

    Built by :func:`emit_unrecoverable_state` and carried on
    :attr:`UnrecoverableStateError.alert` when the alert is raised, so the
    exception is the emission and this is the payload — the shape
    :class:`canary.halt.DreamHalt` and ``snapshot``'s ``CorruptionAlert`` both
    take, and the reason a caller can catch the alert and still have something
    to log, dispatch on, or reconcile against the journal.

    Every field is a fact an operator acts on, and none of them is the key:
    :attr:`stage` says *which* half of resolution failed (the backend or the
    file), :attr:`reference` says *which* reference was being resolved — as a
    redacted label — and :attr:`detail` carries the failing call's own message.
    """

    #: The alert's kind.  Always :data:`ALERT_KIND`; carried on the record so a
    #: reader dispatching on the kind reads it from the thing rather than from
    #: its position in a tuple.
    alert_kind: str
    #: Which half failed: :data:`KEY_BACKEND_STAGE` or :data:`SIDECAR_STAGE`.
    stage: str
    #: The failing call's message, already scrubbed by :func:`_scrubbed`.
    detail: str
    #: The redacted scheme label of the reference being resolved, or ``None``
    #: when no reference was involved (a caller sealing or opening with material
    #: it already held).  Never the target — see the module docstring.
    reference: Optional[str] = None
    #: When the state was observed (ISO-8601 UTC).  The datum a monitor orders
    #: alerts by and an operator measures the outage against.
    detected_at: str = ""

    def __post_init__(self) -> None:
        if self.alert_kind != ALERT_KIND:
            raise KsGuardError(
                f"an unrecoverable state's alert_kind is the spec's "
                f"{ALERT_KIND!r}, got {self.alert_kind!r}; feature 111's alert "
                "has exactly one kind, and a record carrying another word "
                "would be a row no reader of unrecoverable_state could find"
            )
        if self.stage not in (KEY_BACKEND_STAGE, SIDECAR_STAGE):
            raise KsGuardError(
                f"an unrecoverable state's stage is "
                f"{KEY_BACKEND_STAGE!r} or {SIDECAR_STAGE!r}, got "
                f"{self.stage!r}; the stage is what tells an operator whether "
                "to look at the KMS grant or at the file on disk, and a third "
                "value would be a place to look that does not exist"
            )
        if not self.detail:
            raise KsGuardError(
                "an unrecoverable state carries the failing call's message; an "
                "empty detail leaves an operator with the kind and no cause, "
                "which is the state §7 says must not pass unnoticed"
            )

    def summary(self) -> str:
        """Render the state as the line an operator or a monitor reads.

        The kind, the stage, the redacted reference and the cause — in that
        order, because that is the order the questions get asked: *what
        happened*, *where*, *to which key*, *why*.  Deterministic for a given
        record, so two renderings of one state are byte-identical and a test or
        a diff can compare them.
        """
        reference = self.reference or "no key reference"
        return (
            f"{self.alert_kind}: the sidecar key could not be resolved "
            f"({self.stage}, {reference}) — {self.detail}"
        )

    def as_row(self) -> tuple[str, str, Optional[str], str, str]:
        """This record as the tuple :data:`KEY_ALERT_TABLE` stores it.

        The one place the column order is applied, so the insert and any future
        writer cannot disagree with :data:`_COLUMNS`.
        """
        return (
            self.alert_kind,
            self.stage,
            self.reference,
            self.detail,
            self.detected_at,
        )


class UnrecoverableStateError(SidecarDecryptionError):
    """§7's *Unrecoverable* failure, made catchable by type — the alert itself.

    app_spec.xml feature 111: *"which emits an unrecoverable_state alert when
    decryption fails."*  This is that alert.  :func:`emit_unrecoverable_state`
    appends the record to the journal and returns this error for the caller to
    raise; :func:`guard_decryption` raises it on the caller's behalf.

    A :class:`~nulloracle.errors.SidecarDecryptionError` subclass, because §7's
    row is literally *Decrypt failure → Unrecoverable*: the alert is a kind of
    decryption failure, and every existing ``except SidecarDecryptionError`` in
    the workspace keeps catching it.  A caller that wants the state
    specifically — a monitor paging on it, a startup check that refuses to run —
    catches this class and gets :attr:`alert` as well.

    The underlying refusal, when there was one, is ``__cause__``: an operator
    reading the traceback sees the tag failure and then the state it puts the
    deployment in.
    """

    #: The structured record of the state.  Present on every error this module
    #: raises; ``None`` only on a hand-built error with no record behind it.
    alert: Optional[UnrecoverableState]

    #: The failure the journal raised while trying to persist this state, or
    #: ``None`` when the write succeeded (or no journal was configured).
    #:
    #: Carried rather than raised — see
    #: :func:`emit_unrecoverable_state` — because the alert outranks the store.
    #: A caller that *needs* the state to be durable (a startup check deciding
    #: whether to refuse to run, an operator tool reconciling against the
    #: journal) reads this and can require it to be ``None``; a caller that
    #: merely has to know the key is gone reads the alert, exactly as it would
    #: with no journal configured at all.
    persistence_failure: Optional[Exception]

    def __init__(
        self,
        message: str,
        alert: Optional[UnrecoverableState] = None,
        persistence_failure: Optional[Exception] = None,
    ) -> None:
        super().__init__(message)
        self.alert = alert
        self.persistence_failure = persistence_failure


def _is_state(value: Any) -> bool:
    """Whether ``value`` is an :class:`UnrecoverableState`, structurally.

    Duck-checked rather than ``isinstance``-guarded, deliberately — the same
    distinction, for the same reason, that :func:`nulloracle.assignment.
    _is_assignment` draws.  The factory's scan imports this member under a
    synthetic module name (``app.module_loader._import_package``), so a package
    that a suite also imported canonically as ``nulloracle`` exists in the
    process twice with two distinct class objects.  An ``isinstance`` here would
    refuse the very records the *scanned* component's own
    :func:`emit_unrecoverable_state` builds: a deployment that composed its
    journal through the app namespace and emitted through it would be told its
    own alert was not an alert.

    Measured, not reasoned about: the strict check passed every test in this
    member's own suite and failed eleven integration tests the moment the
    composed and directly-imported worlds met.  The check below is the three
    fields a row needs plus the rendering method the write calls — the whole
    contract this store requires of a value, which is that it can name its kind,
    its stage, its cause and render itself for the insert.
    """
    return all(
        hasattr(value, field)
        for field in ("alert_kind", "stage", "detail", "as_row")
    )


def _label_of(reference: Optional[KeyReference | str]) -> Optional[str]:
    """The log-safe label of a reference, whatever spelling the caller used.

    The whole of this feature's redaction, in one place.  A caller may hand over
    a :class:`~nulloracle.keyref.KeyReference` or a string, and the string may be
    either an already-redacted label (``kms:<redacted>``) or — the mistake this
    function exists to absorb — the *raw* reference text, which for ``hex:``
    carries the key itself.

    Normalising through :meth:`KeyReference.parse` is what makes both spellings
    safe: a raw ``kms:arn:…`` and a label ``kms:<redacted>`` are the same
    scheme with different targets, and ``parse`` then ``scheme_label`` maps the
    first onto the second while leaving the second unchanged (``<redacted>`` is
    a legal target, so the label round-trips to itself).

    A string that is *not* a reference at all — a caller's own tag, a
    free-form note — is stored verbatim, because there is no scheme to redact
    and refusing it would turn a logging convenience into a source of
    exceptions inside an alert path.  That is the only branch where the text is
    not inspected, and it cannot leak a key: a key is always reached through a
    scheme, and every scheme is parsed.
    """
    if reference is None or isinstance(reference, KeyReference):
        return reference.scheme_label if reference is not None else None
    try:
        return KeyReference.parse(reference).scheme_label
    except SidecarKeyError:
        return reference


def emit_unrecoverable_state(
    stage: str,
    *,
    reference: Optional[KeyReference | str] = None,
    detail: Any = None,
    journal: Optional["KeyAlertJournal"] = None,
    detected_at: Optional[str] = None,
) -> UnrecoverableStateError:
    """Record the state, then return the alert the caller raises.

    The whole emission in one function: build the record, append it to
    ``journal`` when one is configured, and hand back the error.  Returning
    rather than raising is deliberate — the caller is holding the failure that
    *caused* this one, and it is the caller that can chain it (``raise alert
    from cause``), which keeps this module from having to guess at an exception
    context.

    The journal write happens **before** the return, so a caller that catches
    the alert to keep reporting still leaves the state on record — the order
    :func:`canary.halt_dreaming` takes and for the same reason.

    **A journal that cannot be written does not replace the alert.**  The
    failure to persist is recorded on the alert's own
    :attr:`UnrecoverableStateError.persistence_failure` and the alert is
    returned as it would have been with no journal at all.  This is the one
    place the module's "the journal is not a gate" promise has to be enforced
    rather than merely stated, and it is worth being concrete about the state
    it prevents: a deployment whose ``DATABASE_URL`` is a scheme this store
    cannot speak composes a journal (the URL is only inspected on first use),
    so *every* emission would raise the storage error instead of §7's alert —
    and a caller catching ``UnrecoverableStateError`` would catch nothing,
    while the one fact §7 says must not pass unnoticed passed unnoticed.  A
    broken database is also exactly the circumstance in which an operator most
    needs to be told the key is gone.

    An earlier version re-raised the storage error from here, and its
    docstring claimed the caller "sees both facts" — it did not: the alert was
    gone and the ``KsGuardError`` was all that arrived.  The record is what
    carries both facts now, and ``persistence_failure`` is how a caller that
    needs the write to have succeeded can tell.

    ``reference`` accepts a :class:`~nulloracle.keyref.KeyReference`, an
    already-redacted label, or a raw reference string.  All three are stored as
    a label — see :func:`_label_of` — because the promise this module makes is
    that the alert never carries a target, and a promise that holds only when
    the caller remembered to redact is not a promise.  Passing the raw string
    used to write the key into the record verbatim; a test with a ``hex:``
    reference caught it, and normalising here rather than documenting a rule is
    what makes it unrepresentable.
    """
    record = UnrecoverableState(
        alert_kind=ALERT_KIND,
        stage=stage,
        detail=_scrubbed(
            detail if detail is not None else f"the {stage} stage reported no cause"
        ),
        reference=_label_of(reference),
        detected_at=detected_at if detected_at is not None else _isoformat_now(),
    )
    failure: Optional[Exception] = None
    if journal is not None:
        try:
            journal.record(record)
        except Exception as exc:  # noqa: BLE001 - the alert outranks the store
            # Caught rather than propagated, and deliberately broad: the
            # question here is not *what* went wrong with the store — a bad
            # scheme, a full disk, a locked file, a missing directory — it is
            # that a decryption failure must reach the caller as the alert
            # regardless.  Narrowing this would let an unforeseen storage
            # fault swallow §7's failure, which is the failure mode the whole
            # feature exists to prevent.
            failure = exc
    return unrecoverable_state_error(record, persistence_failure=failure)


@contextmanager
def guard_decryption(
    reference: Optional[KeyReference | str] = None,
    *,
    journal: Optional["KeyAlertJournal"] = None,
    detected_at: Optional[str] = None,
) -> Iterator[None]:
    """Turn a :class:`SidecarDecryptionError` raised inside into the alert.

    The seam that makes *"the sidecar will not open"* a §7 alert rather than a
    refusal a caller might read as a transient.  ``open_envelope``'s tag failure
    is already the right refusal — the file is not served, the plaintext never
    leaves — and what it does not say is what it means: the deployment is in a
    state it cannot leave.  Everything below the tag failure is left exactly as
    it is; everything above it, from here out, is the alert.

    The original refusal rides along as ``__cause__``, so nothing about *why* the
    tag failed is lost — and a caller that wants the pre-111 behaviour catches
    :class:`~nulloracle.errors.SidecarDecryptionError` and gets the original,
    because :class:`UnrecoverableStateError` is one.

    A :class:`~nulloracle.errors.SidecarKeyError` raised inside is **not**
    converted, and that is the feature's central distinction rather than an
    omission: a *malformed reference* or a *malformed secret* is a configuration
    mistake an operator fixes by correcting it, which is a different failure with
    a different repair.  §7's row is about the key being *gone*.
    """
    try:
        yield
    except SidecarDecryptionError as cause:
        if isinstance(cause, UnrecoverableStateError):
            # Already the alert — a double guard (a caller nesting this around
            # a call that already emitted) must not append a second row for one
            # observation, or the span between first and last would be a lie.
            raise
        alert = emit_unrecoverable_state(
            SIDECAR_STAGE,
            reference=reference,
            detail=cause,
            journal=journal,
            detected_at=detected_at,
        )
        raise alert from cause


def unrecoverable_state_error(
    state: UnrecoverableState,
    *,
    persistence_failure: Optional[Exception] = None,
) -> UnrecoverableStateError:
    """Build the alert from its record — the one spelling of the emission.

    The record's own :meth:`UnrecoverableState.summary` plus §7's consequence,
    so the page an operator reads and the row the journal holds say the same
    thing — the same reason :func:`canary.determinism_broken_error` and
    ``snapshot.corruption_error`` exist rather than every caller composing its
    own message.  The consequence is stated because the operator reading it is
    deciding what to do at three in the morning, and §7's answer is not a retry:
    the key comes back from a backup (feature 155's two independent stores) or
    the FDR history stays uninterpretable.

    ``persistence_failure`` names the journal's failure when the state could
    not be written down.  It is folded into the message as well as carried on
    the error, because an operator reading a single page needs to know that
    this alert is *not* in the journal — otherwise they will go looking for a
    row that is not there and conclude the alert never fired.
    """
    if not _is_state(state):
        raise KsGuardError(
            f"unrecoverable_state_error takes an UnrecoverableState — the "
            f"record of the state — got {state!r}; the alert's message is "
            "composed from the record's own fields, and an error built from "
            "anything else would be an emission with no record behind it"
        )
    message = (
        f"{state.summary()}; §7 calls this unrecoverable — all FDR history "
        "becomes uninterpretable, so restore the key from one of its two "
        "independent backups rather than retrying the read"
    )
    if persistence_failure is not None:
        message += (
            f". The state could NOT be written to the alert journal "
            f"({_scrubbed(persistence_failure)}), so this alert is the only "
            "record of it"
        )
    return UnrecoverableStateError(message, state, persistence_failure)


class KeyAlertJournal:
    """The ``unrecoverable_state`` journal: one appended row per detection.

    ``DATABASE_URL``-backed SQLite, resolved lazily on first use so that
    composing the application never opens a database — the same stance every
    store in this workspace takes, and the reason
    :func:`nulloracle.build_key_alert_journal` can be a component builder
    without touching the disk.

    Deliberately **not** a gate.  A journal that could refuse to record, or that
    a caller had to hold in order to get an alert, would make the durability of
    §7's failure depend on the health of a database — and the alert has to
    survive exactly the processes that are already unhealthy.  Every emission
    path works with ``journal=None``; this store is where the state is *kept*,
    not where it is *decided*.
    """

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise KsGuardError(
                f"{DATABASE_URL_ENV} must be a non-empty database URL"
            )
        self._database_url = database_url.strip()
        self._path: Optional[Path] = None

    @classmethod
    def resolve(
        cls, env: Optional[Mapping[str, str]] = None
    ) -> Optional["KeyAlertJournal"]:
        """The journal ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset — the rule every
        store here applies, and the shape an unexpanded template leaves behind.
        Absent is not an error: it is a deployment keeping no relational store,
        which composes no alert journal, and the alert itself still emits.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The database URL this journal writes to."""
        return self._database_url

    @property
    def path(self) -> Path:
        """The SQLite file backing this journal, resolved on first use."""
        if self._path is None:
            self._path = _sqlite_path(self._database_url)
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """Open the database, ensuring this feature's table exists.

        ``CREATE TABLE IF NOT EXISTS`` — the contract every store in this
        workspace states: a fresh database and an existing one take the same
        path, so no migration step is needed here and running a migration over
        a database this store created would change nothing.  The caller owns the
        connection; use it as a context manager to commit.
        """
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        with connection:
            connection.executescript(_KEY_ALERT_SCHEMA)
        return connection

    # -- Writing ------------------------------------------------------------

    def record(self, state: UnrecoverableState) -> UnrecoverableState:
        """Append ``state`` to the journal, returning it unchanged.

        Returns the record rather than a row id so the write composes into
        :func:`emit_unrecoverable_state` without that function needing to know
        anything about this store.  Appended, never upserted: see
        :data:`_KEY_ALERT_SCHEMA` for why the count of rows is evidence.
        """
        if not _is_state(state):
            raise KsGuardError(
                f"the journal records UnrecoverableState values, got "
                f"{type(state).__name__}; a row written from anything else "
                "would be an alert no reader of unrecoverable_state could "
                "reconstruct"
            )
        connection = self._connect()
        try:
            with connection:
                connection.execute(
                    f"INSERT INTO {KEY_ALERT_TABLE} ({_COLUMNS}) "
                    "VALUES (?, ?, ?, ?, ?)",
                    state.as_row(),
                )
        finally:
            connection.close()
        return state

    # -- Reading ------------------------------------------------------------

    def alerts(self) -> tuple[UnrecoverableState, ...]:
        """Every recorded state, oldest first.

        Ordered by ``detected_at`` and then by rowid, so two alerts stamped in
        the same second still come back in the order they were observed — the
        tie the halt store breaks the same way, and the one that matters when an
        operator is reconstructing an outage from the rows.
        """
        connection = self._connect()
        try:
            rows = connection.execute(
                f"SELECT {_COLUMNS} FROM {KEY_ALERT_TABLE} "
                "ORDER BY detected_at, rowid"
            ).fetchall()
        finally:
            connection.close()
        return tuple(_state_from_row(row) for row in rows)

    def latest(self) -> Optional[UnrecoverableState]:
        """The most recent state on record, or ``None`` when there is none.

        The question a startup check asks — *is this deployment already in the
        unrecoverable state?* — answerable without sweeping the whole journal.
        ``None`` means no alert has ever been recorded, which is not the same
        fact as *the deployment is healthy*: a deployment with no journal
        configured answers ``None`` too, and the member's error taxonomy is
        built around keeping those apart.
        """
        connection = self._connect()
        try:
            row = connection.execute(
                f"SELECT {_COLUMNS} FROM {KEY_ALERT_TABLE} "
                "ORDER BY detected_at DESC, rowid DESC LIMIT 1"
            ).fetchone()
        finally:
            connection.close()
        return _state_from_row(row) if row is not None else None


def load_key_alerts(
    database_url: Optional[str] = None,
    *,
    env: Optional[Mapping[str, str]] = None,
) -> tuple[UnrecoverableState, ...]:
    """Read the journal at ``database_url`` (or ``DATABASE_URL``).

    The free-function spelling the member's other stores offer beside their
    classes (``load_ks_guard``, ``load_verdict``), for a monitor or an operator
    script that wants the rows without building a store.  An unconfigured
    environment raises :class:`~nulloracle.errors.KsGuardError` naming the
    variable, because a caller that explicitly asked for the journal has asked a
    question whose honest answer is "there is none" — the same distinction
    :meth:`~nulloracle.keyref.KeyReference.from_env` draws.
    """
    source = os.environ if env is None else env
    raw = (
        database_url.strip()
        if isinstance(database_url, str) and database_url.strip()
        else source.get(DATABASE_URL_ENV, "").strip()
    )
    if not raw:
        raise KsGuardError(
            f"no alert journal is configured: pass a database URL or set "
            f"{DATABASE_URL_ENV}; §7's unrecoverable state is recorded in a "
            "relational store, and without one there is nothing to read"
        )
    return KeyAlertJournal(raw).alerts()


def _state_from_row(row: Any) -> UnrecoverableState:
    """Rebuild a record from a journal row.

    The counterpart of :meth:`UnrecoverableState.as_row`, and the only place
    :data:`_COLUMNS` is unpacked — so a column added to the DDL and forgotten
    here is a test failure rather than a silently mis-assigned field.
    """
    return UnrecoverableState(
        alert_kind=row[0],
        stage=row[1],
        reference=row[2],
        detail=row[3],
        detected_at=row[4],
    )


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into a filesystem path.

    The SQLAlchemy convention the workspace's ``DATABASE_URL`` already uses,
    restated here rather than imported so each store states its own contract.
    A non-SQLite scheme is refused loudly — the Postgres store arrives with the
    migration member — and a pathless (in-memory) URL is refused too: an
    in-memory database dies with the connection that opened it, and §7's
    unrecoverable state is precisely the fact that must outlive the process that
    discovered it.

    SQLAlchemy's spelling is ``sqlite:///relative`` and ``sqlite:////absolute``:
    the third slash separates the URL from the path, so *one* leading slash on
    the parsed path is the separator and must be dropped, while a second is the
    path's own root.  That single rule answers all three spellings —
    ``sqlite:///rel.db`` → ``rel.db``, ``sqlite:////tmp/abs.db`` → ``/tmp/abs.db``,
    ``sqlite:///:memory:`` → ``:memory:`` — and the in-memory check then
    compares against the plain literal.

    Getting this wrong is not a cosmetic matter: reading the parsed path
    literally sends ``sqlite:///:memory:`` to a *file* named ``:memory:``, and
    the journal then looks configured while every row lands somewhere no
    operator will ever look — the silent-loss failure this whole feature exists
    to prevent.  Measured, not reasoned about: this code had exactly that bug
    until a test using the workspace's documented spelling caught it.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise KsGuardError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: this "
            "journal speaks sqlite:/// (the spec's single-machine allowance); "
            f"point {DATABASE_URL_ENV} at a sqlite database"
        )
    if parsed.netloc not in ("", "localhost"):
        raise KsGuardError(
            f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
            f"{parsed.netloc!r}: sqlite addresses a file, and a host here is a "
            "URL an operator believes points somewhere it does not"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path or path == ":memory:":
        raise KsGuardError(
            f"{DATABASE_URL_ENV} names no file ({database_url!r}): an "
            "in-memory journal dies with the connection that opened it, and an "
            "unrecoverable state that vanished with its reporter is exactly "
            "the failure §7 says must not pass unnoticed"
        )
    return Path(path)
