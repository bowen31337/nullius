"""The null-oracle member: §7.1's encrypted sidecar of null assignments.

app_spec.xml, "Null Oracle & Planted Nulls", lands on this workspace member
(``packages/nulloracle``, import name ``nulloracle``).
docs/nullius-tech-architecture.md §7 opens with the reason the component
exists at all — *"The component that makes the whole method work. It is
deliberately small, deliberately isolated, and deliberately boring."* — and
§1 states what is at stake if the isolation fails: the null labels are the
one secret whose leak *"silently voids every calibration number the system
has ever produced, and you would not notice."*

Feature 109 is the foundation the whole category stands on: *System
persists null assignments in an AES-GCM encrypted sidecar file readable by
exactly one service account.*  The features that follow layer onto this
member rather than beside it — feature 110's absence of ``is_null`` from
the tree store (a rule about a *different* component, resting on this one
being the only place the bit lives), feature 111's KMS/sops key resolution
(:mod:`nulloracle.keyref` is the grammar that resolution runs behind),
feature 112's ``POST /target`` and 115's block permutation (which read the
seeds this member stores), 117's ``φ`` and 118-122's campaign assignment
(the writers of the map this member seals), and 123-124's KS guard (which
needs the labels, not merely their count).

**The three halves, and why they are three modules.**  A sidecar entry is a
schema (:mod:`nulloracle.assignment`), a cipher (:mod:`nulloracle.envelope`)
and a file (:mod:`nulloracle.sidecar`), and each is separately arguable.
The schema is §7.1's ``{node_id: {is_null, perm_seed, block_days}}`` and can
be reasoned about — and tested — with no key in hand; the cipher is AES-GCM
in a pinned container and can be tested for tampering with no schema in the
way; the file is permissions and atomic replacement, which is neither of the
other two.  Collapsing them would mean the one thing that cannot be
separated is where a bug hides.

**Why the plaintext schema is what it is.**  ``is_null`` is the bit itself.
``perm_seed`` and ``block_days`` are there because feature 115's block
permutation must be *reproducible* — *"using a stored permutation seed with
a 20 day block length"*, and the load-bearing word is **stored** — so the
parameters that make a null node's series what it is are sealed beside the
bit that says the node is null.  A world whose permutation was re-drawn on
each request would not be a world; §12's determinism contract forbids it
outright.

**Why the labels are never cached in memory.**  :class:`NullSidecar` holds
no memo of the map it just read.  The file is sealed and mode-``0600``
precisely so that *reading it* is the controlled operation; a cache would
move that operation to construction and then hold the plaintext labels for
the process's lifetime, which is a strictly worse place for them to be than
the disk they are encrypted on.

**The ``@register`` decorator lives here, in this ``__init__``, and in no
submodule.**  The factory's scan re-executes a package's ``__init__`` on
every :func:`~app.module_loader.create_app` call, but a submodule already
cached in ``sys.modules`` is not re-executed; a ``@register`` in a submodule
would therefore fire on the first composition of a process and silently drop
out of every later one.  Registration lives on the import path the scan
always runs — the same invariant every other member's registration states.

The public API is small on purpose, and each piece is the seam a later
feature composes rather than a second spelling of something the sidecar
already says:

* :class:`~nulloracle.assignment.NullAssignment` with
  :func:`~nulloracle.assignment.canonical_assignments` — §7.1's schema as a
  value and as canonical bytes: one node's ``is_null``/``perm_seed``/
  ``block_days``, validated at construction and renderable reproducibly.
* :class:`~nulloracle.sidecar.NullSidecar` — the file: :meth:`~nulloracle.
  sidecar.NullSidecar.write` seals a whole map atomically at mode ``0600``,
  :meth:`~nulloracle.sidecar.NullSidecar.open` reads it back or refuses, and
  :meth:`~nulloracle.sidecar.NullSidecar.assignment` answers for one node.
* :class:`~nulloracle.keyref.SidecarKey` with
  :class:`~nulloracle.keyref.KeyReference` and
  :func:`~nulloracle.keyref.ensure_key` — feature 111's seam: the reference
  grammar (``kms:``, ``sops:``, ``hex:``), the account check, and a key
  wrapper that will not leak into a traceback.
* :func:`~nulloracle.envelope.seal` with
  :func:`~nulloracle.envelope.open_envelope` — the AES-GCM container, whose
  layout is pinned in that module so a nonce can never be reused.
* :func:`~nulloracle.assignment.assignments_digest` and
  :func:`~nulloracle.envelope.envelope_digest` — the two key-free
  comparisons: *is this the same sidecar?*, answerable by a process that is
  not allowed to open it.
* The error taxonomy of :mod:`nulloracle.errors`, one base class wide —
  and its central distinction is that an unopenable sidecar raises rather
  than reading as an empty one.
"""

from __future__ import annotations

from typing import Optional

from app.module_loader import register

from .assignment import (
    DEFAULT_BLOCK_DAYS,
    NullAssignment,
    assignments_digest,
    canonical_assignments,
    decode_assignments,
    encode_assignments,
    normalize_node_id,
)
from .envelope import (
    FORMAT_VERSION,
    MAGIC,
    NONCE_BYTES,
    TAG_BYTES,
    envelope_digest,
    open_envelope,
    require_cryptography,
    seal,
)
from .errors import (
    NullOracleError,
    SidecarAccessError,
    SidecarDecryptionError,
    SidecarError,
    SidecarKeyError,
    SidecarStoreError,
)
from .keyref import (
    KEY_REF_ENV,
    SERVICE_ACCOUNT_ENV,
    SIDECAR_KEY_BYTES,
    EnsureKeyResult,
    KeyReference,
    SidecarKey,
    ensure_key,
    resolve_key,
    service_account,
)
from .sidecar import (
    SIDECAR_DIRECTORY,
    SIDECAR_FILENAME,
    SIDECAR_FILE_MODE,
    SIDECAR_PATH_ENV,
    NullSidecar,
)

__all__ = [
    "COMPONENT_NAME",
    "DEFAULT_BLOCK_DAYS",
    "FORMAT_VERSION",
    "KEY_REF_ENV",
    "MAGIC",
    "NONCE_BYTES",
    "SIDECAR_DIRECTORY",
    "SIDECAR_FILENAME",
    "SIDECAR_FILE_MODE",
    "SIDECAR_KEY_BYTES",
    "SIDECAR_PATH_ENV",
    "SERVICE_ACCOUNT_ENV",
    "TAG_BYTES",
    "EnsureKeyResult",
    "KeyReference",
    "NullAssignment",
    "NullOracleError",
    "NullSidecar",
    "SidecarAccessError",
    "SidecarDecryptionError",
    "SidecarError",
    "SidecarKey",
    "SidecarKeyError",
    "SidecarStoreError",
    "assignments_digest",
    "build_null_sidecar",
    "canonical_assignments",
    "decode_assignments",
    "encode_assignments",
    "ensure_key",
    "envelope_digest",
    "normalize_node_id",
    "open_envelope",
    "require_cryptography",
    "resolve_key",
    "seal",
    "service_account",
]

__version__ = "0.1.0"

#: The component name this member registers under — the key a composed
#: :class:`~app.module_loader.Application` carries the sidecar at, and the
#: name the seat in the app namespace (``src/app/modules/nulloracle``) asks
#: for.  Spelled once here so the member, the factory's registry and the
#: seat cannot drift apart.
COMPONENT_NAME = "nulloracle"


@register(COMPONENT_NAME)
def build_null_sidecar() -> Optional[NullSidecar]:
    """Component builder: §7.1's sidecar, bound to the environment.

    Takes no arguments — that is the factory's registration protocol — and
    resolves its path and its key from the environment at build time, so a
    composed application carries a sidecar for the deployment the process is
    actually running in (``NULL_SIDECAR_PATH`` or ``LAKE_ROOT`` for the
    location, ``NULL_SIDECAR_KEY_REF`` for the key, and
    ``NULL_SIDECAR_SERVICE_ACCOUNT`` for the one account it is granted to).

    Construction performs no I/O: the directory is created and the file
    written only on a :meth:`~nulloracle.sidecar.NullSidecar.write`, and the
    key is not read from disk or a KMS here beyond what the reference itself
    resolves.  So composing the application never touches the sidecar, which
    is what keeps the factory's scan cheap and unprivileged.

    Returns ``None`` when nothing names a usable location and key — the
    same degrade-don't-break stance the ledger member's store takes toward
    an absent ``DATABASE_URL``: an unconfigured sidecar is a discoverable
    state, and the composed application simply carries no ``"nulloracle"``
    component.  A deployment whose scorer must run §7.4's detectability
    guard is the caller that must not find itself in that state.

    Deliberately never raises, including for a ``kms:`` or ``sops:``
    reference this member does not speak.  The factory builds every
    registered component on every :func:`~app.module_loader.create_app`
    call, so a builder that raised would take composition down for every
    unrelated feature in the workspace; a process that *requires* a sidecar
    asks :func:`~nulloracle.keyref.ensure_key` directly at its own startup,
    where a named :class:`~nulloracle.errors.SidecarKeyError` is the right
    answer.
    """
    return NullSidecar.resolve()
