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

There is deliberately no error for *"the run was not admitted"* beyond
:class:`GVisorIsolationRequired`.  Feature 157's failure mode is one thing —
a run configuration that is not gVisor's — and splitting it into an error per
spelling (absent block, ``runc``, a micro-VM, an empty string) would let a
caller catch the spellings it happened to think of and miss the one the
deployment actually configured.
"""

from __future__ import annotations

__all__ = [
    "GVisorIsolationRequired",
    "IsolationDocumentError",
    "SandboxError",
    "SandboxIsolationError",
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
