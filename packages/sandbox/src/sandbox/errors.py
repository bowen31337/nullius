"""The sandbox member's error vocabulary.

Every refusal this member raises names a *reason* rather than a bare fact,
because a sandboxed run happens inside the frozen evaluator's pipeline
(docs/nullius-tech-architecture.md §5.2, §6.1 step 2) where a failure travels
out as a trial outcome rather than a traceback an operator reads live: §8's
``ok | timeout | error | tripwire_fail`` is only actionable if the exception
behind the ``error`` says *what about the run* was refused.

The split is by *which contract* was violated, never by which line of code
failed — the discipline :mod:`infra.security.sandbox_egress`'s and
:mod:`tripwires.errors` state for their own trees:

* :class:`SandboxIsolationError` — the isolation contract, and feature 157's
  whole subject.  The run's configuration does not carry gVisor isolation: the
  isolation block is absent, it names a mechanism or runtime that is not
  gVisor's, or a component's compiled policy was not gVisor's to begin with.
  This is the one refusal in the member that exists to keep *agent-authored
  code* from executing outside the isolation §5.2's table requires, so its
  subclass :class:`GVisorIsolationRequired` is what a caller sees when the
  feature fires — and every message it carries begins with the greppable code
  :data:`sandbox.isolation.ISOLATION_REQUIRED_CODE`
  (``gvisor_isolation_required``), so an operator grepping a log for the
  rejection finds it by the feature's own words, the same discipline
  :class:`nulloracle.errors.IsNullColumnError` applies to ``is_null_column``.

* :class:`IsolationDocumentError` — the *document* contract, a sibling of the
  isolation contract rather than a subclass of it.  The isolation declaration
  is not a document this member can read at all: not a mapping, a missing or
  non-string mechanism, a document that does not say what it is.  Kept apart
  from :class:`SandboxIsolationError` for the reason
  :class:`infra.security.sandbox_egress.EgressPolicyDocumentError` is kept
  apart from its own law: *the document could not be read* and *the document
  grants what the law forbids* are different facts about different things, and
  a caller that conflated them would "fix" a well-formed document that had
  already named the wrong runtime, or go looking for a runtime that was never
  named because a key was misspelled.

* :class:`SandboxImportError` — the import-allowlist contract, and feature
  167's whole subject.  A submitted module imports a term the configured
  allowlist does not cover, or the allowlist document itself could not be
  read.  Its subclass :class:`DisallowedImportError` is the refusal itself,
  and every message it carries begins with the greppable code
  :data:`sandbox.imports.DISALLOWED_IMPORT_CODE` (``disallowed_import``) —
  the feature's own sentence, written as a token, the same discipline
  :data:`sandbox.isolation.ISOLATION_REQUIRED_CODE` applies to feature 157's.
  The gate's *returned* refusal carries the same code and the same sentence,
  which is the shape the feature's own sentence asks for: it *returns* a
  ``disallowed_import`` error message.

* :class:`AllowlistDocumentError` — the *document* contract of the import
  law, kept beside :class:`IsolationDocumentError` and apart from
  :class:`DisallowedImportError` for the reason that pair is split: the
  allowlist document is written by trusted code, and one that cannot be read
  — a missing marker, a term that is not a dotted name, one term listed
  twice — is a fact about the *configuration*, not about any module
  submitted against it.

* :class:`SandboxSeedError` — the seed contract, and feature 165's whole
  subject.  A sandboxed invocation that carries no seed, carries one that is
  not a seed, or whose node record disagrees with the seed the invocation
  would carry.  Its subclass :class:`InvocationSeedError` is the refusal of a
  *seedless run* — every message begins with the greppable code
  :data:`sandbox.seed.SEED_REQUIRED_CODE` (``node_seed_required``), the
  discipline :data:`sandbox.isolation.ISOLATION_REQUIRED_CODE` applies to
  feature 157's — and :class:`NodeSeedDocumentError` is the refusal of a
  *stored record that contradicts itself*, whose messages begin with
  :data:`sandbox.seed.SEED_MISMATCH_CODE` (``node_seed_mismatch``).

There is deliberately no error for *"the run was not admitted"* beyond
:class:`GVisorIsolationRequired`.  Feature 157's failure mode is one thing —
a run configuration that is not gVisor's — and splitting it into an error per
spelling (absent block, ``runc``, a micro-VM, an empty string) would let a
caller catch the spellings it happened to think of and miss the one the
deployment actually configured.  The same restraint shapes
:class:`SandboxSeedError`: *"this run carries no seed this law can pass"* is
one fact with several spellings (absent, ``None``, a string, a ``bool``, a
negative integer), and a caller that had to catch each spelling would miss the
one its deployment actually produced.
"""

from __future__ import annotations

__all__ = [
    "AllowlistDocumentError",
    "DisallowedImportError",
    "GVisorIsolationRequired",
    "InvocationSeedError",
    "IsolationDocumentError",
    "NodeSeedDocumentError",
    "SandboxError",
    "SandboxImportError",
    "SandboxIsolationError",
    "SandboxSeedError",
    "SandboxTransferError",
    "ScoreChannelError",
    "WindowTransferError",
]


class SandboxError(Exception):
    """The base of every refusal this member raises.

    One base class so a caller — the pipeline step that executes a signal, a
    campaign driver, a CI check that recompiles the committed isolation
    artifact — can catch every failure of the sandbox path with a single
    ``except``.  The member imports no other workspace member (the sandbox is
    the thing untrusted code is put inside, so its own vocabulary must not
    depend on anything that could be handed to it), and its errors therefore
    share no hierarchy with the evaluator's or the tripwires': a caller
    catching :class:`tripwires.errors.TripwireError` will not accidentally
    swallow a sandbox refusal, and vice versa.
    """


class SandboxIsolationError(SandboxError):
    """The isolation contract: a run was configured without gVisor isolation.

    app_spec.xml, "Untrusted Code Sandbox", feature 157: *System rejects a run
    of agent-authored code configured without gVisor isolation.*  The two
    moments this class covers are the two the feature's own sentence draws
    between — a *configuration* proposed as a document (compile time, fail
    closed, nothing applied) and a *run* offered to the launcher (answer time,
    refused before anything executes).

    Raised rather than returned, for the reason
    :class:`infra.security.loop_credentials.ZoneWritePermissionRejected` is:
    the configuration is written by *trusted* code — an operator, a campaign
    driver, a deployment manifest — not by the untrusted code inside the box,
    so a caller that got the isolation wrong gets an exception it cannot
    ignore.  The alternative shape would be worse than a bug: a launcher that
    answered a bad configuration with a *value* would need a caller to check
    it, and the failure mode this feature exists to prevent is agent-authored
    code running with nothing under it while the pipeline reports an ordinary
    trial outcome.
    """


class GVisorIsolationRequired(SandboxIsolationError):
    """The refusal itself: this run is not configured with gVisor isolation.

    Every message begins with ``gvisor_isolation_required``
    (:data:`sandbox.isolation.ISOLATION_REQUIRED_CODE`), the one spelling a
    log-grepping operator or CI check looks for, and names the offending value
    — the mechanism and runtime that were configured instead, or the key that
    was absent — so the drift is findable rather than merely refused.  The
    spelling is the feature's own subject written as a code: §5.2's table row
    is ``Isolation | gVisor (runsc)``, §18's stack table chose ``gVisor
    runsc`` for the deployment, and a message that said only "isolation
    refused" would hide which of the two a drifted configuration was missing.

    Deliberately not a :class:`PermissionError`, unlike feature 147's zone
    write refusal.  That refusal stands where the operating system would have
    produced an ``EACCES``, so it is *shaped* like a permission error to be
    caught by the same ``except``; this one stands where no kernel is
    consulted at all — the run is refused before a process exists — and
    dressing it as a filesystem accident would send an operator looking for a
    permissions problem in a deployment that has none.
    """


class IsolationDocumentError(SandboxIsolationError):
    """The isolation declaration is not a document this member can read.

    A policy document that does not declare itself (the marker feature 149's
    and 148's committed artifacts carry), an ``isolation`` block that is
    absent, is not a mapping, or whose ``mechanism``/``runtime`` are not
    strings.  Refused, fail closed — the whole document, not the unreadable
    key skipped — because a configuration compiled from a partially-read
    document is one whose file and whose run disagree, and that disagreement
    is where the next drift lives.

    Kept outside the isolation contract proper, and stated here so a caller can
    tell the two apart: this error is about a document *nobody can read*, where
    :class:`GVisorIsolationRequired` is about a document that read perfectly
    well and named the wrong isolation.  The second is the feature working; the
    first is the feature unable to say what it found.
    """


class SandboxImportError(SandboxError):
    """The import-allowlist contract: a submission outside what is configured.

    app_spec.xml, "Untrusted Code Sandbox", feature 167: *System rejects a
    submitted module importing anything outside the configured allowlist,
    which returns a disallowed_import error message.*  The subject has moved
    from feature 157's *run* to the *module a run would execute* — §5.2's
    ``code=node.code``, checked statically at the moment it is offered, before
    anything executes — and from the isolation a box declares to the modules a
    submission may import: §10.2's "any import outside an allowlist" and
    §11.1's "no imports outside the allowlist", the row §12 states from the
    determinism side ("blocked by the import allowlist").

    Raised rather than returned only at the bridge
    (:meth:`sandbox.imports.ModuleDecision.require`) and for the document
    contract below — the gate itself *answers* a submission with a decision,
    for the reason feature 157's gate does: the pipeline offers thousands of
    submissions unattended, and a screen that raised per module would turn one
    bad candidate into a crashed evaluator.
    """


class DisallowedImportError(SandboxImportError):
    """The refusal itself: this module imports outside the configured allowlist.

    Every message begins with ``disallowed_import``
    (:data:`sandbox.imports.DISALLOWED_IMPORT_CODE`), the one spelling the
    feature's own sentence gives the rejection, so a log-grepping operator or
    CI check finds it by the feature's words.  The message the gate *returns*
    carries the same code and the same sentence — the sentence says the system
    "returns" it — and this class is that message in the exception shape a
    launcher that must not proceed asks for with ``require()``.

    The refusal names every offending term with its line, never only the
    first: the reader of the refusal is the author of the submission (the
    loop, or the operator debugging it), and a screen that reported one
    offender at a time would be resubmitted to learn the rest — the same
    discipline :mod:`canary._allowlist` states for its own collective
    refusal, stated here rather than shared by import because the sandbox is
    the box untrusted code is put inside and its vocabulary must not depend
    on anything that could be handed to it.
    """


class AllowlistDocumentError(SandboxImportError):
    """The configured allowlist is not a document this member can read.

    A document that does not declare itself (the marker feature 157's
    committed policy and feature 149's committed egress artifact carry), an
    ``allow`` list that is not a list, a term that is not a dotted Python
    name (a leading dot, a star, an empty segment), or one term listed twice.
    Refused, fail closed — the whole document, not the unreadable term
    skipped — because an allowlist compiled from a partially-read document is
    one whose file and whose ceiling disagree, and that disagreement is where
    the next drift lives.

    The counterpart of :class:`IsolationDocumentError`, and kept apart from
    :class:`DisallowedImportError` for the reason that pair is split: the
    allowlist is written by *trusted* code, and its refusals are facts about
    a deployment's configuration; the submissions screened against it are
    untrusted, and their refusals are the feature working.
    """


class SandboxTransferError(SandboxError):
    """The payload-channel contract: what crosses the channel did not.

    app_spec.xml, "Untrusted Code Sandbox", feature 166: *System transfers the
    materialized window as Arrow IPC, which returns the resulting score vector
    over the same channel.*  The subject is the *channel* — §5.2's payload
    channel, the one path into and out of a box that has no mounts
    (``Filesystem | No mounts. Data arrives over IPC only.``) — and this class
    is its refusals.

    **Why the transfer has refusals at all, when the box holds the bytes.**
    The sandbox never reads a window or a score off disk; it reads them off a
    buffer that arrived over the channel.  So a transfer can fail in ways no
    computation can: bytes that are not a window payload, a payload whose
    frames cannot be read, a score vector that is not a score vector, a channel
    that was already spent.  Each of those is a fact about *the bytes that
    crossed* rather than about the signal, and a caller that caught them as
    :class:`SandboxIsolationError` would go looking for a misconfigured box
    when the fault is in what it sent.

    **Raised rather than returned, unlike the two laws' gates.**  Features
    157's and 167's refusals are *answers* — a run and a submission are offered
    unattended, thousands of them, so their gates return decisions and the
    pipeline reads a value rather than surviving a traceback.  A transfer is
    not offered in that sense: it is one dispatch by trusted host code
    (§5.2's own call site), and there is exactly one sensible response to "the
    bytes you sent are not a window" — do not run, fix the dispatch.  So the
    channel raises, and the *score* half of feature 166 is where a per-run
    failure stays a value: see :meth:`sandbox.transfer.ScoreVector.require`.
    """


class WindowTransferError(SandboxTransferError):
    """The bytes that arrived are not a materialized window.

    The inbound half of :class:`SandboxTransferError`.  A payload that is
    empty, is not a serialized window at all, was built by a window that holds
    no frames, or whose frames glued out of frames cannot be read.

    Deliberately not a subclass of the contract's own
    :class:`contract.payload.PayloadFormatError`, and deliberately not caught
    from it either: the sandbox is the box agent-authored code is put inside,
    and its vocabulary must not depend on the contract's — a caller that
    catches :class:`SandboxError` gets every refusal of this member without
    also being subscribed to the contract's.  The translation happens once, at
    the seam, so the member's caller never sees a foreign type: the reason
    :class:`infra.security.sandbox_egress` states for its own translation, and
    the reason a shared helper raising another feature's error defeats the
    caller's ``except``.
    """


class ScoreChannelError(SandboxTransferError):
    """The bytes that arrived are not a score vector for the window sent.

    The outbound half of :class:`SandboxTransferError` — the ``which returns
    the resulting score vector over the same channel`` clause, when what came
    back cannot be read as one.  A return that is empty, is not one of the
    channel's messages, carries no scores, or whose scores disagree with the
    window they are supposed to score: a different length, a non-finite value,
    a dtype that cannot be ranked.

    **The length check is the load-bearing one.**  A score vector is
    positional against the window's universe (feature 11's "indexed by symbol"
    is a positional correspondence, and :func:`contract.signal.validate_signal_return`
    says so), so a return of the right shape but the wrong length is a
    misalignment that would travel silently into the cross-sectional reduction
    downstream and poison every number after it.  It is refused here, at the
    seam, naming both lengths — the same "misaligned before any per-symbol
    check could mean anything" judgement the contract's validator makes for a
    live return, applied to one that crossed a channel.

    Every message begins with ``score_channel``
    (:data:`sandbox.transfer.SCORE_CHANNEL_CODE`) so an operator grepping a log
    for the rejection finds it, the discipline feature 157's and 167's codes
    take.  Kept apart from :class:`WindowTransferError` because the two name
    opposite directions of one channel, and a caller reading a failure wants to
    know which leg it was on before it wants the detail.
    """


class SandboxSeedError(SandboxError):
    """The seed contract: the node seed did not reach the invocation.

    app_spec.xml, "Untrusted Code Sandbox", feature 165: *System passes the
    node seed into every sandboxed invocation, persisting that seed on the node
    record.*  The subject is the run's *one source of randomness* — §5.2's
    ``seed=node.seed`` in the call site whose other arguments are the code, the
    payload and the limits — and this class is the refusals that keep it from
    silently going missing.

    **Why a seed deserves its own error when nothing about it can fail.**  The
    seed is not a value the box computes; it is a value the box is *handed*,
    and the failure mode is not a wrong answer but an *absent* one: a launcher
    that spawned a child without the seed would produce a score vector that
    looks exactly like a correct one, from a signal whose ``random.Random(seed)``
    drew from a different stream (or from the interpreter's own entropy) than
    the one the node record says it drew from.  §12's row — "Seeded RNG |
    ``seed`` passed into ``signal()``; stored on the node" — is the whole of the
    determinism contract's randomness clause, and P3 is explicit that a replay
    that is not bit-reproducible makes the replay pool *quietly worthless*:
    "Non-determinism does not announce itself; it just slowly makes every
    conclusion wrong."  So the two places the seed could go missing — the
    invocation that must carry it, and the record that must store it — are
    refusals rather than silent defaults, which is the same stance
    :class:`~sandbox.isolation.GVisorIsolationRequired` takes toward a run's
    declared isolation.

    **Raised rather than returned, unlike the two laws' gates.**  Features
    157's and 167's gates answer *untrusted subjects* — a run, a submission —
    offered thousands of times by an unattended pipeline, so they return
    decisions.  A seed is not offered by untrusted code: it is §5.2's own call
    site, one dispatch by trusted host code, and there is exactly one sensible
    response to "this invocation carries no seed" — do not run, because the run
    that proceeded would be unjustifiable afterwards.  The same split
    :class:`SandboxTransferError` draws for the channel, and for the same
    reason.  The *constructor* of a seedless invocation is therefore not an
    error at all — a caller must be able to build one to be told what is wrong
    with it — and the refusal fires at :meth:`sandbox.seed.SeededInvocation.require`,
    the last line before the spawn.
    """


class InvocationSeedError(SandboxSeedError):
    """The refusal itself: this invocation carries no seed this law can pass.

    Every message begins with ``node_seed_required``
    (:data:`sandbox.seed.SEED_REQUIRED_CODE`), the one spelling a log-grepping
    operator or CI check looks for, and names the offending value *and which
    spelling it was*: absent (the keyword never passed), ``None``, a string
    (``"42"`` — the seed as an environment variable carries it, which is a
    different type in a different place), a ``bool`` (``True`` is not a seed
    anyone meant to write), a negative integer, or one too large for the signed
    64-bit column it is about to be stored in.  The distinction is the point of
    naming them: an operator who sees "absent" looks at the call site, and one
    who sees "negative" looks at whatever minted the seed.

    Deliberately **not** a ``ValueError``, unlike the null oracle's own seed
    refusals.  That member's seed checks guard a *derivation* inside trusted
    arithmetic, where the standard exception is what the surrounding code
    expects; this one guards a value about to be carried into a subprocess by a
    launcher and written to a node row, and a caller that caught the standard
    exception would be subscribing to every other library's value errors along
    with it.  The member's vocabulary is its own for the reason
    :mod:`sandbox.errors`' module docstring gives: the box untrusted code is put
    inside must not carry a dependency whose refusals a caller could confuse
    with its own.
    """


class NodeSeedDocumentError(SandboxSeedError):
    """A stored node record contradicts the seed the invocation would carry.

    The second half of feature 165's sentence — *persisting that seed on the
    node record* — when the record and the run disagree.  A node record whose
    ``seed`` is not a seed at all, and a record whose stored seed is a genuine
    integer that is **not** the seed the invocation carries.

    **The second case is the feature, not a technicality.**  The whole value of
    writing a seed down is that a later reader can re-run the node and get the
    same vector; a record that names a seed other than the one the signal
    actually drew from is worse than no record, because it is a *plausible*
    answer to "what seed was this run?" that no replay would reproduce — the
    §12 failure mode stated as a row rather than as a crash.  So the writer
    refuses rather than overwriting: a record and an invocation are two
    statements about one run, and this law will not write the second while the
    first says something else.

    Messages begin with ``node_seed_mismatch``
    (:data:`sandbox.seed.SEED_MISMATCH_CODE`) and name both values, so the
    reader sees which of the two the disagreement is about rather than being
    told only that they differ.
    """
