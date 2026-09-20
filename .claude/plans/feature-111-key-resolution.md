# Feature 111 — resolve the sidecar key from KMS or sops, alert `unrecoverable_state` on decryption failure

## What already exists (and must not be disturbed)

`packages/nulloracle/src/nulloracle/keyref.py` landed with feature 109's work and owns
only the **grammar**: `KeyReference` parses `kms:` / `sops:` / `hex:`, `resolve_key`
deliberately refuses `kms:`/`sops:` by name, and `ensure_key(material=…)` is the seam a
backend-speaking caller uses. Its docstrings state the division explicitly: *"Feature 111
owns the backends; this module owns the grammar they are resolved behind"*, and its
refusal message tells the caller to **"resolve the material in that backend and pass it
as `ensure_key(material=…)`"**.

So feature 111 is the missing half: the backends themselves, and the alert. `keyref.py`
is **not edited** — its pinned tests (`test_a_backend_reference_is_refused_by_name`,
`test_a_backend_reference_is_refused_with_the_seam_named`) stay true, because the new
entry point consumes `ensure_key` rather than changing it.

## Design decisions

**The backends speak through injectable seams, not raw SDK calls.** `boto3` is not
installed and `sops` is not on `PATH` (verified). Both are deferred, like
`envelope.require_cryptography`. `KmsBackend` takes a *client* (anything with
`decrypt(CiphertextBlob=…) -> {"Plaintext": bytes}`) and `SopsBackend` takes a *runner*
(anything shaped like `subprocess.run`). Tests inject fakes, so the suite is honest
without a network or the binary; a deployment lets the backends build their own.

**The KMS target names the key; the encrypted data key lives in a blob the deployment
points at.** `kms:<arn-or-id>` is the `KeyId` for a `Decrypt` call; the ciphertext it
decrypts is the deployment's wrapped data key at `NULL_SIDECAR_KMS_BLOB`. Minting a key
per call (`GenerateDataKey`) would defeat the feature — a fresh key per resolution makes
every previously sealed sidecar unopenable.

**`sops:<path>` decrypts the document and reads the key out of it.** `sops --decrypt
<path>`, and the plaintext (stripped) is 64 hex chars or base64 of 32 bytes; anything
else is refused by name. One accepted shape, stated, rather than a guessing parser.

**Composition stays I/O-free — the builders never emit.** `build_null_sidecar` and the
new journal builder keep the factory's contract: never raise, never touch the network.
A `kms:`-referenced deployment still composes no sidecar (the existing
`test_a_backend_reference_does_not_take_composition_down` keeps passing), and the
feature-111 entry point is called explicitly at startup — which is exactly what
`build_null_sidecar`'s docstring already instructs a caller to do. An alert raised
during composition would take down every unrelated member, the opposite of the intent.

**Emission = a typed raise, plus a durable row.** The workspace's two other alert
features (`canary._halt`'s `determinism_broken`, `snapshot`'s corruption alert) both do
this: build a *record*, persist it, then raise a typed error carrying it, so catching the
alert to keep reporting still leaves the fact on record. §7's row — *"Null sidecar key
lost | Decrypt failure | Unrecoverable. All FDR history becomes uninterpretable"* — is the
one failure that must survive the process that noticed it.

**`UnrecoverableStateError` subclasses `SidecarDecryptionError`.** §7 calls this literally
*Decrypt failure → Unrecoverable*, so the alert is a *kind* of decryption failure, not a
replacement: every existing `except SidecarDecryptionError` still catches it. The original
exception rides along as `__cause__`.

**Alert vs. configuration mistake is the member's existing distinction.** A backend whose
*decryption call fails* (API error, non-zero `sops` exit, timeout, missing binary) or a
sidecar whose **tag fails** is the alert: the key is gone and no repair short of restore
helps. A *malformed secret* (a sops plaintext that is not key material, a short blob) stays
`SidecarKeyError` — a configuration mistake with a different repair. This is the same
"no sidecar configured / the sidecar is broken" split the whole taxonomy rests on.

**The alert never carries the reference target.** `KeyReference.scheme_label` already
redacts it (`hex:<redacted>`), because a `hex:` target *is* the key. The record stores the
label, never the target, and a test pins that the target never appears in a message.

## Files

### New — mechanism
- **`packages/nulloracle/src/nulloracle/backends.py`**
  - `KMS_SCHEME`/`SOPS_SCHEME`, `KMS_BLOB_ENV = "NULL_SIDECAR_KMS_BLOB"`,
    `SOPS_TIMEOUT_SECONDS`
  - `KeyBackend` (`Protocol`): `scheme`, `resolve(reference) -> bytes`
  - `KmsBackend(client=None, *, blob_path/…, env=None)`, `boto3_kms_client()`,
    `require_boto3()` (deferred import naming the fix)
  - `SopsBackend(runner=None, *, env=None)`, `require_sops()`
  - `default_backends(env=None) -> dict[str, KeyBackend]`
  - `resolve_material(reference, *, backends=None, env=None) -> bytes` — dispatch
    (`hex:` inline via `keyref`, `kms:`/`sops:` through the backend)
  - `resolve_sidecar_key(env=None, *, backends=None, account=None, journal=None)
    -> EnsureKeyResult` — **the feature's entry point**: parse → backend material →
    `ensure_key(material=…)`; a backend decryption failure emits the alert and raises

### New — the alert
- **`packages/nulloracle/src/nulloracle/keyalert.py`**
  - `UNRECOVERABLE_STATE = "unrecoverable_state"` (the spec's spelling, verbatim)
  - stages: `KEY_BACKEND_STAGE = "key_backend"`, `SIDECAR_STAGE = "sidecar"`
  - `UnrecoverableState` (frozen dataclass): `alert_kind`, `stage`, `reference`
    (the redacted label), `detail`, `detected_at`; `summary()`
  - `unrecoverable_state_error(state) -> UnrecoverableStateError` — the one spelling of
    the emission, message composed from the record (`canary.determinism_broken_error`)
  - `UnrecoverableStateError(SidecarDecryptionError)` carrying `.alert`
  - `emit_unrecoverable_state(stage, *, reference=None, detail=None, journal=None,
    detected_at=None)` — build record, persist if a journal is given, return the error
    for the caller to raise
  - `guard_decryption(reference=None, journal=None)` — context manager: a
    `SidecarDecryptionError` inside it is persisted and re-raised as the alert with
    `__cause__` set; the seam that makes "the sidecar will not open" a §7 alert
  - `KeyAlertJournal` — `DATABASE_URL`-backed SQLite store, `CREATE TABLE IF NOT EXISTS
    nulloracle_sidecar_key_alert` (idempotent, member-owned, no migration), `record()`,
    `alerts()`, `latest()`; `resolve(env=None)` → `None` when unconfigured
  - `load_key_alerts(...)`

### New — the seat
- **`src/app/modules/nulloracle/keyalert.py`** — `COMPONENT_NAME =
  "nulloracle-sidecar-key-alert"`, `key_alert_component(app=None)`, `__all__` of exactly
  those two (the seat convention; `test_*_component.py` pins the set)

### Edited — `packages/nulloracle/src/nulloracle/__init__.py`
- import the new names; add them to the alphabetical `__all__`
- add `KEY_ALERT_COMPONENT_NAME`; `@register(KEY_ALERT_COMPONENT_NAME)` on
  `build_key_alert_journal()` — zero-arg, never raises, returns `None` when unconfigured
- extend the module docstring's public-API bullets with feature 111's backends + alert

**Name is load-bearing.** `app.order` is name-sorted and
`order.index("nulloracle") + 1 == order.index("nulloracle-ks-guard")` is asserted in two
tests. `nulloracle-key-…` would sort **before** `nulloracle-ks-guard` and break it;
`nulloracle-sidecar-key-alert` sorts after `nulloracle-plan-gate` and before
`nulloracle-target-route`. Verified against the live `app.order`.

### Not touched
`keyref.py`, `sidecar.py`, `envelope.py`, `errors.py` (all landed and pinned), plus every
shared path (`module_loader.py`, `settings.py`, `middleware.py`, migrations, other members).

## Tests

- **`packages/nulloracle/tests/test_backends.py`** — `kms:` through a fake client;
  `sops:` through a fake runner; the KMS blob path; base64 and hex plaintexts; failures
  (KMS `ClientError`, non-zero exit, timeout, missing binary) each emit
  `unrecoverable_state` and raise with `__cause__`; a malformed secret is
  `SidecarKeyError` and **not** an alert; the redacted label never leaks the target;
  `resolve_sidecar_key` returns an `EnsureKeyResult` with `created is False`; `hex:`
  still resolves with no backend at all; `keyref.ensure_key` still refuses `kms:`.
- **`packages/nulloracle/tests/test_keyalert.py`** — the kind is the spec's spelling;
  the record round-trips; the journal writes/reads rows, creates its table idempotently,
  and degrades to `None` without `DATABASE_URL`; `guard_decryption` converts a tampered
  sidecar open into the alert, persists, and leaves a clean open alone; emission works
  with no journal at all; a missing binary does not leak a secret into `detail`.
- **`packages/nulloracle/tests/test_key_alert_component.py`** — scan finds the name; the
  builder takes no arguments and never raises; `None` without `DATABASE_URL`; survives a
  *second* `create_app()`; the guard stays adjacent to the sidecar; the seat's `__all__`.
- **`tests/nulloracle/test_key_resolution.py`** — assembled-system integration (the
  acceptance gate collects only `tests/`, per this repo's convention): a sidecar sealed
  under key A, a `sops:` reference resolving to key B, and the composed journal recording
  one `unrecoverable_state` row while `UnrecoverableStateError` propagates.

## Verification

```
UV_CACHE_DIR=$PWD/.claw-forge/tmp/uv-cache uv run --no-sync pytest tests/nulloracle packages/nulloracle/tests -q
UV_CACHE_DIR=$PWD/.claw-forge/tmp/uv-cache uv run --no-sync ruff check <new files>
```
Both suites, because the gate grades `tests/` only. Ruff is scoped to the files I touch —
the repo baseline is red (163 pre-existing errors, mypy absent).
