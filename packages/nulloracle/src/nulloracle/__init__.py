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

**Feature 123 is where the labels are finally *used*, and it is the one
place they may be.**  §7.4 states the test — *"a job holding the sidecar key
runs a two-sample KS test on in-sample score distributions, null nodes vs.
real nodes"* — and §4.2 states the rule it is the single exception to:
``is_null`` is visible to exactly one component, and the guard is the job
that component runs.  So feature 123 arrives as two modules split the way
the sidecar's three are: :mod:`nulloracle.ks` is the test (the statistic
and its p-value, validated, stdlib-only and carrying no node id) and
:mod:`nulloracle.ksguard` is the store that writes the number against its
campaign.

**Feature 124 is the decision the test does not make.**  §7.4's ``p < 0.05``
comparison and the ``VOID`` it sets are feature 124's, and they arrive as
:mod:`nulloracle.verdict` — the module that reads the p-value feature 123
persisted, compares it to :data:`VOID_THRESHOLD`, and sets
``calibration_status = VOID`` when it falls below.  The split is the same
discipline feature 123 observes: this feature measures, the next one
decides, and the threshold that separates "calibrated" from "void" is a
constant of the verdict module because the verdict module is the one place
the verdict is pronounced.  The verdict is a fact about a campaign, so it is
written to the campaign row the guard already writes to; the alert and the
dreaming-halt and pool-exclusion that §7.4's rule also names are
*consequences* of the status being ``VOID``, enforced where the pool and
promotion read the status (features 876/1056), not here.

**Feature 121 is where the flip depth is finally *used*.**  §7.2 states the
rule in one line — *"below ``flip_depth`` the real targets are returned, at or
beyond it the permuted ones"* — and :mod:`nulloracle.resolution` is that rule
with a store behind it: :func:`~nulloracle.resolution.past_the_flip` is the
boundary itself, and :class:`~nulloracle.resolution.TypeDOracle` reads the
node's stored depth and its branch's stored flip (feature 119's, inherited
down the ancestor chain), requires the campaign to be the Type-D regime, and
serves the caller's real targets below the flip and the caller's permutation
at or beyond it.  The permutation arrives as a seam — §7.2's
``block_permute`` is feature 115's — because the *which branch* decision is
feature 121's and the *permutation* is not; what the oracle refuses to do is
serve the permuted branch without one.

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
* :func:`~nulloracle.ks.ks_two_sample` with :mod:`nulloracle.ksguard` —
  feature 123's detectability test and the store that persists its p-value
  against the campaign, and :func:`~nulloracle.verdict.void_if_detectable`
  with :mod:`nulloracle.verdict` — feature 124's verdict, which reads that
  stored p-value, compares it to :data:`VOID_THRESHOLD`, and sets the
  campaign's ``calibration_status`` to ``VOID``.  The test measures, the
  verdict decides, and the verdict pronounces on the number the guard
  persisted rather than on one a caller hands in.
* The error taxonomy of :mod:`nulloracle.errors`, one base class wide —
  and its central distinction is that an unopenable sidecar raises rather
  than reading as an empty one.
"""

from __future__ import annotations

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
    KsGuardError,
    KsTestError,
    NullOracleError,
    SidecarAccessError,
    SidecarDecryptionError,
    SidecarError,
    SidecarKeyError,
    SidecarStoreError,
)
from .flipdepth import (
    FLIP_DEPTH_COLUMN,
    NODE_TABLE,
    P_MAX,
    P_MIN,
    FlipDepth,
    flip_depth,
    node_as_seed,
    persist_flip_depth,
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

# Feature 123's two halves: the test (:mod:`nulloracle.ks`) and the store
# that writes its answer against the campaign (:mod:`nulloracle.ksguard`).
# Imported at module scope, unlike the `cryptography` the envelope defers:
# both are stdlib-only, so the factory's scan — which imports this package
# to fire its `@register` — pays nothing for them.
from .ks import (
    KS_ASYMPTOTIC,
    KS_ASYMPTOTIC_FLOOR,
    KS_EXACT,
    KS_EXACT_CELLS,
    KS_MIN_SAMPLE,
    KS_SERIES_TERMS,
    KolmogorovSmirnov,
    ks_pvalue,
    ks_two_sample,
    two_sample_statistic,
)
from .ksguard import (
    CAMPAIGN_TABLE,
    DATABASE_URL_ENV,
    KS_GUARD_TABLE,
    KsGuard,
    KsGuardRecord,
    guard_record_from_row,
    load_ks_guard,
    persist_ks_pvalue,
)
from .phi import (
    NULL_FRACTION_COLUMN,
    PHI_CEILING,
    PHI_FLOOR,
    WORKSPACE_COUNT_COLUMN,
    PlantedNullFraction,
    null_fraction,
    persist_null_fraction,
)
from .resolution import (
    TYPE_D_CAMPAIGN_TYPE,
    TypeDOracle,
    TypeDResolution,
    past_the_flip,
    resolve_type_d,
)
from .sidecar import (
    SIDECAR_DIRECTORY,
    SIDECAR_FILE_MODE,
    SIDECAR_FILENAME,
    SIDECAR_PATH_ENV,
    NullSidecar,
)
from .verdict import (
    CALIBRATION_STATUS_OK,
    CALIBRATION_STATUS_VOID,
    VOID_THRESHOLD,
    CampaignVerdict,
    Verdict,
    load_verdict,
    void_if_detectable,
)

__all__ = [
    "CALIBRATION_STATUS_OK",
    "CALIBRATION_STATUS_VOID",
    "CAMPAIGN_TABLE",
    "COMPONENT_NAME",
    "DATABASE_URL_ENV",
    "DEFAULT_BLOCK_DAYS",
    "FLIP_DEPTH_COLUMN",
    "FLIP_DEPTH_COMPONENT_NAME",
    "FORMAT_VERSION",
    "FRACTION_COMPONENT_NAME",
    "KEY_REF_ENV",
    "KS_ASYMPTOTIC",
    "KS_ASYMPTOTIC_FLOOR",
    "KS_EXACT",
    "KS_EXACT_CELLS",
    "KS_GUARD_COMPONENT_NAME",
    "KS_GUARD_TABLE",
    "KS_MIN_SAMPLE",
    "KS_SERIES_TERMS",
    "MAGIC",
    "NODE_TABLE",
    "NONCE_BYTES",
    "NULL_FRACTION_COLUMN",
    "PHI_CEILING",
    "PHI_FLOOR",
    "P_MAX",
    "P_MIN",
    "RESOLUTION_COMPONENT_NAME",
    "SERVICE_ACCOUNT_ENV",
    "SIDECAR_DIRECTORY",
    "SIDECAR_FILENAME",
    "SIDECAR_FILE_MODE",
    "SIDECAR_KEY_BYTES",
    "SIDECAR_PATH_ENV",
    "TAG_BYTES",
    "TYPE_D_CAMPAIGN_TYPE",
    "VERDICT_COMPONENT_NAME",
    "VOID_THRESHOLD",
    "WORKSPACE_COUNT_COLUMN",
    "EnsureKeyResult",
    "FlipDepth",
    "KeyReference",
    "KolmogorovSmirnov",
    "KsGuard",
    "KsGuardError",
    "KsGuardRecord",
    "KsTestError",
    "NullAssignment",
    "NullOracleError",
    "NullSidecar",
    "PlantedNullFraction",
    "SidecarAccessError",
    "SidecarDecryptionError",
    "SidecarError",
    "SidecarKey",
    "SidecarKeyError",
    "SidecarStoreError",
    "TypeDOracle",
    "TypeDResolution",
    "Verdict",
    "assignments_digest",
    "build_flip_depth",
    "build_null_sidecar",
    "build_type_d_resolution",
    "build_verdict",
    "canonical_assignments",
    "decode_assignments",
    "encode_assignments",
    "ensure_key",
    "envelope_digest",
    "flip_depth",
    "guard_record_from_row",
    "ks_pvalue",
    "ks_two_sample",
    "load_ks_guard",
    "load_verdict",
    "node_as_seed",
    "normalize_node_id",
    "null_fraction",
    "open_envelope",
    "past_the_flip",
    "persist_flip_depth",
    "persist_ks_pvalue",
    "persist_null_fraction",
    "require_cryptography",
    "resolve_key",
    "resolve_type_d",
    "seal",
    "service_account",
    "two_sample_statistic",
    "void_if_detectable",
]

__version__ = "0.1.0"

#: The component name this member registers under — the key a composed
#: :class:`~app.module_loader.Application` carries the sidecar at, and the
#: name the seat in the app namespace (``src/app/modules/nulloracle``) asks
#: for.  Spelled once here so the member, the factory's registry and the
#: seat cannot drift apart.
COMPONENT_NAME = "nulloracle"

#: The component name feature 123's guard journal registers under — the key a
#: composed :class:`~app.module_loader.Application` carries the journal at.
#: A second name rather than a second component under :data:`COMPONENT_NAME`
#: because the two are different things on different lifecycles: the sidecar
#: is §7.1's sealed file, the guard is feature 123's store, and a deployment
#: can legitimately have one without the other.  The ledger member registers
#: three names the same way.
KS_GUARD_COMPONENT_NAME = "nulloracle-ks-guard"

#: The component name feature 124's verdict store registers under — the key a
#: composed :class:`~app.module_loader.Application` carries it at.  A third
#: name rather than a second/third component under :data:`COMPONENT_NAME`
#: because the sidecar, the guard journal and the verdict are three different
#: things on three different lifecycles, and a deployment can legitimately
#: have one without the others.  The ledger member registers three names the
#: same way.
VERDICT_COMPONENT_NAME = "nulloracle-ks-verdict"

#: The component name feature 117's fraction store registers under — the key a
#: composed :class:`~app.module_loader.Application` carries it at.  A fourth
#: name rather than a second component under :data:`COMPONENT_NAME` because
#: the sidecar, the guard journal, the verdict and the fraction are four
#: different things on four different lifecycles, and a deployment can
#: legitimately have one without the others.  The ledger member registers
#: several names the same way.
FRACTION_COMPONENT_NAME = "nulloracle-null-fraction"

#: The component name feature 119's flip-depth store registers under — the key
#: a composed :class:`~app.module_loader.Application` carries it at.  A fifth
#: name rather than a second component under :data:`COMPONENT_NAME` because the
#: sidecar, the guard journal, the verdict, the fraction and the flip depth are
#: five different things on five different lifecycles, and a deployment can
#: legitimately have one without the others.  The ledger member registers
#: several names the same way.
FLIP_DEPTH_COMPONENT_NAME = "nulloracle-null-flip-depth"

#: The component name feature 121's Type-D resolution registers under — the
#: key a composed :class:`~app.module_loader.Application` carries it at.  A
#: sixth name rather than a sixth component under :data:`COMPONENT_NAME`
#: because the sidecar, the guard journal, the verdict, the fraction, the flip
#: depth and the resolution are six different things on six different
#: lifecycles, and a deployment can legitimately have any without the others.
#: The ``type-d-`` prefix sorts after both the ``ks-*`` and the ``null-*``
#: families in the name-sorted ``app.order``, so feature 123's
#: guard-immediately-after-sidecar adjacency is untouched.
RESOLUTION_COMPONENT_NAME = "nulloracle-type-d-resolution"


@register(FRACTION_COMPONENT_NAME)
def build_null_fraction() -> PlantedNullFraction | None:
    """Component builder: §4.1.1's fraction store, bound to the environment.

    Feature 117's *store* half as a component, so the campaign planner that
    fixes a campaign's planted-null fraction can ask the composed application
    for the fraction store the deployment configured rather than reading
    ``DATABASE_URL`` itself — the same seam the guard's, the verdict's and the
    ledger's stores expose.

    Takes no arguments — that is the factory's registration protocol — and
    resolves its path from the environment at build time, so a composed
    application carries a fraction store for the deployment the process is
    actually running in.

    Returns ``None`` when nothing names a relational store, the
    degrade-don't-break stance every store in this workspace takes toward an
    absent ``DATABASE_URL``: an unconfigured fraction is a discoverable state,
    and a deployment whose campaign planner must fix §4.1.1's fraction is the
    caller that must not find itself in it.

    Like :func:`build_null_sidecar`, this never raises, including for a URL
    whose scheme this store cannot speak.  The factory builds every registered
    component on every :func:`~app.module_loader.create_app` call, so a builder
    that raised would take composition down for every unrelated feature; a
    process that *requires* a fraction store asks
    :meth:`~nulloracle.phi.PlantedNullFraction.resolve` or calls the store
    directly, where a named :class:`~nulloracle.errors.KsGuardError` is the
    right answer.  Construction performs no I/O — the path is resolved on first
    use — so composing the application never opens a database.
    """
    return PlantedNullFraction.resolve()


@register(FLIP_DEPTH_COMPONENT_NAME)
def build_flip_depth() -> FlipDepth | None:
    """Component builder: §7.3's Type-D flip-depth store, bound to the environment.

    Feature 119's *store* half as a component, so the campaign job that draws a
    Type-D branch's flip depth can ask the composed application for the store
    the deployment configured rather than reading ``DATABASE_URL`` itself — the
    same seam the fraction's, the guard's and the verdict's stores expose.

    Returns ``None`` when nothing names a relational store, the
    degrade-don't-break stance every store in this workspace takes toward an
    absent ``DATABASE_URL``: an unconfigured flip depth is a discoverable state,
    and a deployment whose campaign loop must draw §7.3's flip depths is the
    caller that must not find itself in it.

    Like :func:`build_null_fraction`, this never raises, including for a URL
    whose scheme this store cannot speak.  The factory builds every registered
    component on every :func:`~app.module_loader.create_app` call, so a builder
    that raised would take composition down for every unrelated feature; a
    process that *requires* a flip-depth store asks
    :meth:`~nulloracle.flipdepth.FlipDepth.resolve` or calls the store directly,
    where a named :class:`~nulloracle.errors.KsGuardError` is the right answer.
    Construction performs no I/O — the path is resolved on first use — so
    composing the application never opens a database.
    """
    return FlipDepth.resolve()


@register(RESOLUTION_COMPONENT_NAME)
def build_type_d_resolution() -> TypeDOracle | None:
    """Component builder: §7.2's Type-D flip resolution, bound to the environment.

    Feature 121's resolution half as a component, so the endpoint that serves
    §7.2's ``POST /target`` requests can ask the composed application for the
    Type-D oracle the deployment configured rather than reading
    ``DATABASE_URL`` itself — the same seam the fraction's, the flip depth's,
    the verdict's and the guard's stores expose.

    Returns ``None`` when nothing names a relational store, the
    degrade-don't-break stance every store in this workspace takes toward an
    absent ``DATABASE_URL``: an unconfigured resolution is a discoverable
    state, and a deployment whose endpoint must resolve Type-D requests is the
    caller that must not find itself in it.

    Like :func:`build_flip_depth`, this never raises, including for a URL
    whose scheme this store cannot speak.  The factory builds every registered
    component on every :func:`~app.module_loader.create_app` call, so a builder
    that raised would take composition down for every unrelated feature; a
    process that *requires* the resolution asks
    :meth:`nulloracle.resolution.TypeDOracle.resolve` or calls the oracle
    directly, where a named :class:`~nulloracle.errors.KsGuardError` is the
    right answer.  Construction performs no I/O — the path is resolved on
    first use — so composing the application never opens a database.
    """
    return TypeDOracle.resolve()


@register(VERDICT_COMPONENT_NAME)
def build_verdict() -> CampaignVerdict | None:
    """Component builder: §7.4's verdict store, bound to the environment.

    Feature 124's *decision* half as a component, so the campaign job that
    judges a completed campaign can ask the composed application for the
    verdict store the deployment configured rather than reading
    ``DATABASE_URL`` itself — the same seam the guard's and the ledger's store
    expose.

    Returns ``None`` when nothing names a relational store, the
    degrade-don't-break stance every store in this workspace takes toward an
    absent ``DATABASE_URL``: an unconfigured verdict is a discoverable state,
    and a deployment whose campaign loop must pronounce §7.4's verdict is the
    caller that must not find itself in it.

    Like :func:`build_null_sidecar` and :func:`build_ks_guard`, this never
    raises, including for a URL whose scheme this store cannot speak.  The
    factory builds every registered component on every
    :func:`~app.module_loader.create_app` call, so a builder that raised would
    take composition down for every unrelated feature; a process that *requires*
    a verdict asks :meth:`~nulloracle.verdict.CampaignVerdict.resolve` or calls
    the store directly, where a named :class:`~nulloracle.errors.KsGuardError`
    is the right answer.  Construction performs no I/O — the path is resolved
    on first use — so composing the application never opens a database.
    """
    return CampaignVerdict.resolve()


@register(KS_GUARD_COMPONENT_NAME)
def build_ks_guard() -> KsGuard | None:
    """Component builder: §7.4's guard journal, bound to the environment.

    Feature 123's *store* half as a component, so the campaign job that runs
    the guard over a completed campaign can ask the composed application for
    the journal the deployment configured rather than reading
    ``DATABASE_URL`` itself — the same seam the ledger member's store and
    the evaluator's own expose.

    Returns ``None`` when nothing names a relational store, the
    degrade-don't-break stance every store in this workspace takes toward an
    absent ``DATABASE_URL``: an unconfigured guard is a discoverable state,
    and a deployment whose campaign loop must run §7.4's guard is the caller
    that must not find itself in it.

    Like :func:`build_null_sidecar`, this never raises, including for a URL
    whose scheme this store cannot speak.  The factory builds every
    registered component on every :func:`~app.module_loader.create_app`
    call, so a builder that raised would take composition down for every
    unrelated feature; a process that *requires* a guard asks
    :meth:`~nulloracle.ksguard.KsGuard.resolve` or calls the store directly,
    where a named :class:`~nulloracle.errors.KsGuardError` is the right
    answer.  Construction performs no I/O — the path is resolved on first
    use — so composing the application never opens a database.
    """
    return KsGuard.resolve()


@register(COMPONENT_NAME)
def build_null_sidecar() -> NullSidecar | None:
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
