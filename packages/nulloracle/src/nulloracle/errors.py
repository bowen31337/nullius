"""The null-oracle plugin's error taxonomy.

One base class (:class:`NullOracleError`) so a caller — the scorer process
holding the sidecar key, a campaign driver, an operator script, a later
feature in this category — can catch every failure of the null-oracle path
with a single ``except``.  The subclasses split by *which contract* was
violated, not by which line of code failed:

* :class:`SidecarError` — the sidecar contract (app_spec.xml feature 109).
  An assignment's identity is malformed (a ``node_id`` that is not a UUID),
  its status is not a genuine bool, its permutation seed is not a
  non-negative integer, or its block length is not a positive integer.  The
  sidecar is the one place in the entire system where a node's null status
  is written down (docs/nullius-tech-architecture.md §7.1: *"There is no
  ``is_null`` column anywhere in the tree store"*), so an assignment that
  cannot state its own status coherently is refused at the write rather than
  sealed into the file as a value no reader could interpret.

* :class:`SidecarKeyError` — the key contract.  The key reference
  ``NULL_SIDECAR_KEY_REF`` names is absent, blank, or not a form this
  member can resolve (a KMS ARN, a ``sops:`` reference, or inline hex).  The
  refusal here is *before* any crypto is attempted, because a key that
  cannot be named is a configuration problem an operator can fix, not a
  decryption failure to escalate.

* :class:`SidecarDecryptionError` — the refusal to serve a sidecar that
  cannot be authenticated.  AES-GCM's tag failed, the file was truncated,
  the nonce was wrong, or the key simply is not the one the file was sealed
  under.  §7's failure table names this the *unrecoverable* one — *"Null
  sidecar key lost → Decrypt failure → Unrecoverable. All FDR history
  becomes uninterpretable"* — so this error is deliberately loud and
  deliberately not caught by anything that would degrade quietly.  A
  sidecar that will not open is never served as "no nulls assigned": an
  empty assignment map and an unreadable one mean opposite things about
  every score the system has ever recorded.

* :class:`SidecarAccessError` — the one-service-account contract.  A read
  of the sidecar was attempted by a process that is not the single service
  account the key is granted to (§7.1: *"readable by ONE service
  account"*; §2's trust table: *"separate IAM role"*).  The check is a
  filesystem-permission gate plus an explicit identity assertion, so the
  refusal meets a caller that reaches for the file directly rather than
  only the ones that go through this package's API.

* :class:`SidecarStoreError` — the store contract.  The sidecar's location
  is misrouted or the write failed.  A store that is *absent* — no
  ``NULL_SIDECAR_PATH`` configured and no lake root found — is not this
  error: it is a supported, discoverable state in which no sidecar
  component composes (see :meth:`nulloracle.sidecar.NullSidecar.resolve`),
  because the factory's stance toward an unconfigured component is to
  degrade, not to break.

* :class:`KsTestError` — the detectability test's contract (app_spec.xml
  feature 123).  A sample handed to §7.4's two-sample Kolmogorov–Smirnov
  test is empty, too small to decide anything, or not made of finite
  scores.  Refused rather than computed, because the p-value this test
  returns is what voids a campaign: a number produced from four nodes, or
  from a sample that silently dropped a ``None``, would enter §7.4's
  ``p < 0.05`` comparison wearing a real statistic's authority.

* :class:`KsGuardError` — the guard's store contract (feature 123's other
  half).  The campaign the p-value belongs to is unknown, the relational
  store cannot be reached or speaks another scheme, or the write of the
  two halves could not be completed.  Distinct from
  :class:`KsTestError` for the same reason :class:`SidecarStoreError` is
  distinct from :class:`SidecarError`: *the measurement was refused* and
  *the measurement could not be recorded* are different facts, and only
  the first is about the numbers.

* :class:`HeterogeneousWorldError` — the homogeneity contract (app_spec.xml
  feature 122).  A campaign plan mixes Type-R and Type-D assignment within
  one tree, and §7.3 forbids that outright: *"Campaigns are homogeneous in
  null type.  Mixed trees make a bad FDR unattributable between selection
  failure and stopping failure."*  Every message this class carries begins
  with the code :data:`nulloracle.plan.HETEROGENEOUS_WORLD`
  (``heterogeneous_world``), the one spelling the spec names, so an
  operator grepping a log for the rejection finds it by the feature's own
  word.  Kept outside :class:`KsGuardError` deliberately: a planner that
  catches this refusal is rejecting a *document*, not handling a broken
  store, and conflating the two would let a mixed world be retried as a
  database hiccup.

* :class:`TargetRouteError` — the route contract (app_spec.xml feature 112,
  docs/nullius-tech-architecture.md §7.2's interface).  A ``POST /target``
  body that cannot say what it is asking for: an identity that is not a
  UUID, a depth that is not a non-negative integer, a horizon outside the
  five the spec aligns, a symbols list that is not a non-empty list of
  names, or a date range that is not a first-to-last pair of calendar
  dates.  Refused before the sidecar is opened, because a malformed ask
  spends no read of the one file in the system worth controlling.  Kept
  apart from the route's *answer* for an unknown node — a 404 is a fact
  about the world the route reports, not a failure — and from the
  sidecar's own errors, which propagate unwrapped: a missing or unopenable
  sidecar is a deployment failure, and dressing it as either a refusal or
  a 404 would read "no such node" off a world the route never saw.

* :class:`TargetPayloadError` — the route's supply contract (app_spec.xml
  feature 113, §7.2's response body).  The node *is* known and the sidecar
  answered for it, but the answer §7.2 promises — ``target_series`` plus
  the opaque ``charges_budget`` — cannot be built without lying: a known
  node the route has no series for at all, a null node with no permutation
  to serve it through, a permutation whose answer sits on a different
  support than the series it permuted, a series covering other symbols than
  the ask named, or a series reaching outside the span the ask named.  Kept
  apart from :class:`TargetRouteError` because the two are refused at
  different points about different things: a route error is a *body* that
  cannot say what it is asking for and is refused before the sidecar is
  opened, where a payload error is a *deployment* that cannot serve what
  the body asked for and is only discoverable after the entry was read.
  A caller that conflated them would retry a working request against a
  broken deployment, or file a missing seam as a client bug.

  This is deliberately not the third option — answering anyway.  Serving
  an empty series on a null branch would hand the evaluator a target
  series measured against nothing while §8 debits no budget for it; and
  serving the *real* series on a null branch would hand the caller real
  signal inside a world planted to have none.  Both read as ordinary
  answers downstream, which is exactly why the refusal must be loud here.

* :class:`IsNullColumnError` — the storage barrier's contract (app_spec.xml
  feature 110, docs/nullius-tech-architecture.md §7.1).  A node column
  proposed for the tree store is named ``is_null``, or the tree store's
  ``node`` table is found carrying one, and §7.1 states the rule as a fact
  about the schema rather than a policy about its use: *"There is no
  ``is_null`` column anywhere in the tree store.  Not hidden, not nulled
  out, not ``SELECT``-excluded.  Absent."*  Every message this class carries
  begins with the code :data:`nulloracle.schemaguard.NULL_COLUMN`
  (``is_null_column``), so an operator grepping a log for the rejection
  finds it by the offender's own name — the same discipline
  :class:`HeterogeneousWorldError` applies to its code.  Kept outside
  :class:`KsGuardError` deliberately: a caller catching this refusal is
  rejecting a *schema* (or learning a barrier is already broken), not
  handling a broken store, and conflating the two would let the one column
  the whole method forbids be retried as a database hiccup.

Every message names the offending value and the contract it broke, in the
same discipline as the ledger member's taxonomy: these errors are
operational signals for a system whose whole FDR claim rests on the labels
this file holds, so a failure of the sidecar path must be *speakable*, not
merely loggable.
"""

from __future__ import annotations

__all__ = [
    "HeterogeneousWorldError",
    "IsNullColumnError",
    "KsGuardError",
    "KsTestError",
    "NullOracleError",
    "SidecarAccessError",
    "SidecarDecryptionError",
    "SidecarError",
    "SidecarKeyError",
    "SidecarStoreError",
    "TargetPayloadError",
    "TargetRouteError",
]


class NullOracleError(Exception):
    """Base class for every failure of the null-oracle path."""


class SidecarError(NullOracleError):
    """A null assignment's identity, status or perm parameters are malformed.

    Raised at the write, where the cause can still be named: a ``node_id``
    that is not a UUID cannot be joined to the tree store later, so it is
    refused before it is sealed into the sidecar; an ``is_null`` that is
    not a genuine bool (a string ``"false"``, an int ``0``, ``None``) is
    refused rather than coerced, because the whole transfer to a null world
    hangs on this one bit and a truthy-looking non-bool is exactly the
    value that would silently plant the wrong world; a ``perm_seed`` that
    is not a non-negative integer or a ``block_days`` that is not a
    positive integer is refused for the same reason — feature 115's block
    permutation is only reproducible from a stored seed and block length
    that mean one thing.
    """


class SidecarKeyError(NullOracleError):
    """The sidecar key reference is absent, blank, or unresolvable.

    Raised when ``NULL_SIDECAR_KEY_REF`` names nothing, names an empty or
    whitespace-only value, or names a form this member cannot resolve.  A
    key that cannot be named is a *configuration* failure, refused before
    any ciphertext is touched — the same distinction the cost-model member
    draws between a missing parser and a malformed document.  Feature 111
    is the feature that answers *where the key comes from*; this error is
    the refusal that feature resolves *from*.
    """


class SidecarDecryptionError(NullOracleError):
    """The sidecar could not be authenticated and was therefore not served.

    AES-GCM's authentication tag failed: the file was tampered with, it was
    truncated, it was sealed under a different key, or its nonce is not the
    one the file carries.  All four are one refusal here, deliberately,
    because distinguishing them for a caller would be an oracle of its own —
    and because §7's failure table treats every one of them the same way:
    *unrecoverable*, all recorded calibration becomes uninterpretable.

    Never swallowed on the read path.  A sidecar that will not open must
    not read as "no node is null", because that reading would hand the
    caller a world where every planted null looks real, and the system
    would report an FDR computed over nothing.
    """


class SidecarAccessError(NullOracleError):
    """The sidecar was read by a process that is not the granted account.

    §7.1 seals the sidecar *"readable by ONE service account"* and §2 gives
    the key *"separate IAM role"*.  The check behind this error is
    deliberately two-layered: the file is written with owner-only mode bits
    so the operating system refuses a foreign read, and the read path
    asserts the process's own service-account identity against the one the
    sidecar records, so the refusal holds even where the mode bits have
    been loosened (a copied file, a permissive mount, a root-owned
    backup).  Filesystem permissions are the enforcement; this error is
    what the caller sees when they hold.
    """


class SidecarStoreError(NullOracleError):
    """The sidecar's location is misrouted, or its write failed.

    A configured path this member cannot use (a directory where a file
    belongs), or a seal whose bytes could not be written.  Raised rather
    than swallowed because a sidecar that silently failed to persist is
    exactly the state feature 109 exists to prevent: a campaign would then
    run against a world whose null assignments nobody recorded, and the
    resulting FDR would be computed over a design that was never applied.
    """


class KsTestError(NullOracleError):
    """A sample handed to §7.4's two-sample KS test cannot support a verdict.

    app_spec.xml feature 123 is the test; §7.4 is what it decides with:

    .. code-block:: text

        if ks_pvalue < 0.05:
            campaign.calibration_status = VOID

    So a p-value from this path is not a diagnostic — it is the number that
    voids a campaign, halts dreaming and removes the campaign from the
    replay pool (feature 124).  A sample that cannot support such a verdict
    must therefore be *refused*, never quietly computed over: an empty
    sample (a campaign where nothing was scored on one side), a sample of
    one (a KS statistic that is degenerate by construction), a score that
    is not a finite real (a ``None`` that a caller's ``if score:`` dropped,
    or a ``nan`` that survived a mean), or a distribution that is not a
    mapping of node to score at all.

    Refusing is the same discipline :class:`SidecarDecryptionError` states
    for the labels: the failure mode this taxonomy exists to prevent is a
    *plausible-looking number* standing in for a fact nobody measured, and
    the campaign that would be voided on it would be voided for the wrong
    reason.
    """


class KsGuardError(NullOracleError):
    """The KS guard's p-value could not be recorded against its campaign.

    Feature 123's store half: the campaign is unknown, the relational store
    is unreachable or speaks a scheme this member cannot read, or the
    two halves of the write — §7.4's ``ks_pvalue`` and the campaign row it
    joins to — could not both be completed.

    Kept distinct from :class:`KsTestError` deliberately.  "The measured
    distributions cannot support a test" is a statement about a campaign's
    data; "the number could not be written down" is a statement about the
    deployment, and a caller that conflated them would investigate the
    wrong one.  The distinction is the same one :class:`SidecarStoreError`
    draws beside :class:`SidecarError`, and the one
    :class:`~nulloracle.errors.SidecarKeyError` draws beside
    :class:`SidecarDecryptionError`.
    """


class HeterogeneousWorldError(NullOracleError):
    """A campaign plan mixes Type-R and Type-D assignment within one tree.

    app_spec.xml feature 122 is the gate, and docs/nullius-tech-
    architecture.md §7.3 states the rule it enforces in one sentence:
    *"Campaigns are **homogeneous in null type**.  Mixed trees make a bad
    FDR unattributable between selection failure and stopping failure."*
    The two regimes keep their null-ness in different places — a Type-R
    node's is a root selection sealed in §7.1's sidecar and inherited by
    the subtree (feature 118), a Type-D node's is a flip depth on the
    branch (feature 119) resolved by feature 121's depth rule — so a tree
    carrying both would hold nulls no single read path serves: the sidecar
    would answer for some nodes and the depth rule for others, and a
    campaign that scored badly could blame neither failure mode.

    Every message begins with the code ``heterogeneous_world``
    (:data:`nulloracle.plan.HETEROGENEOUS_WORLD`), the spec's own word for
    the rejection, so the failure is greppable by the feature that defines
    it — the same discipline :data:`contract.violation.CONTRACT_VIOLATION`
    applies to the outcome it names.

    Kept outside :class:`KsGuardError` deliberately.  A planner catching
    this refusal is rejecting a *plan* — a document it wrote or a world it
    found — and a caller that caught the store's error instead would treat
    a heterogeneous world as a deployment fault to retry rather than a
    design to fix.
    """


class TargetRouteError(NullOracleError):
    """A ``POST /target`` request could not be answered as §7.2 shapes it.

    app_spec.xml feature 112 is the route — *System exposes POST /target
    accepting node_id, campaign_id, depth, horizon, symbols and a date
    range* — and this refusal is the route's own half of that sentence: a
    body whose six terms are malformed.  An identity that is not a UUID
    cannot be joined to the tree store's ``node.id``; a depth that is not
    a genuine non-negative integer is a claim nobody placed the node at; a
    horizon outside {1, 2, 5, 10, 20} is a question no evaluation asks; a
    symbols value that is not a non-empty list of names is an ask with
    nobody to answer for; and a date range that is not a first-to-last
    pair of calendar dates bounds nothing.

    Refused before the sidecar is opened — a malformed ask spends no read
    of the one file in the system worth controlling.

    Deliberately neither of the two answers this class is *not*:

    * an unknown node is not this error.  §7.2's route answers 404 for a
      node the sidecar does not hold, a fact about the world rather than a
      failure of the route, and a caller that had to catch to discover it
      would retry the world and escalate the deployment;
    * a broken sidecar is not this error either.  :class:`SidecarStoreError`
      and :class:`SidecarDecryptionError` propagate out of the route
      unwrapped, because a deployment failure dressed as a malformed body
      would be investigated as a client bug.

    Kept beside :class:`SidecarError` for the same reason the guard's two
    errors are kept apart: *the request was malformed* and *the store
    could not be read* are different facts, and only the first is about
    the caller.
    """


class TargetPayloadError(NullOracleError):
    """A known node's §7.2 payload could not be served coherently.

    app_spec.xml feature 113 is the payload — *System returns a target series
    plus a charges_budget directive from POST /target, never which returns
    is_null in any form* — and this refusal is the route's supply half: the
    sidecar holds the node, so the answer is not a 404, but the series §7.2
    promises cannot be built from what the deployment supplied.

    Five ways that happens, and each of them is a *lie avoided* rather than a
    bug reported:

    * a node the sidecar holds and the route has no series for at all — no
      ``targets`` seam composed, or a seam that answered nothing for this ask;
      a 200 over an empty series would measure the evaluation against nothing
      while §8 charged it nothing either;
    * a null node with no permutation to serve it through — the entry's stored
      ``perm_seed`` and ``block_days`` are only parameters, and a parameter is
      not a mechanism, so serving the real series in their place would hand
      the caller real signal inside a world planted to have none;
    * a permutation whose answer carries a different set of dates than the
      series it permuted — §7.2's permutation moves a series' day blocks and
      never adds or drops one, so a series on a different support has been
      recomputed rather than rearranged, and its support alone would mark the
      branch;
    * a series that does not cover the cross-section the request named —
      neither §7.2 branch can answer for a symbol that was not asked about, so
      such a series arrived by some other path than this route;
    * a series whose dates fall outside the span the request's ``date_range``
      named — an answer reaching past the window the ask stated is an answer
      to a different ask.

    What is deliberately *not* among them is an identity permutation: see the
    route module's docstring — a refusal that could only fire on the null
    branch would itself be the branch oracle §7.2 forbids.

    Distinct from :class:`TargetRouteError`, which is refused *before* the
    sidecar is opened and is about the caller's body; this one is only
    discoverable *after* the entry was read and is about the deployment's
    supply.  Distinct too from the sidecar's own errors, which propagate
    unwrapped: a sidecar that will not open is not a payload that cannot be
    built, and a caller that conflated the two would go looking for a missing
    seam when the key was wrong.
    """


class IsNullColumnError(NullOracleError):
    """A node column named ``is_null`` was proposed, or found, on the tree store.

    app_spec.xml feature 110 is the rule — *System keeps ``is_null`` absent
    from the tree store entirely, which rejects any proposed node column
    named ``is_null``* — and docs/nullius-tech-architecture.md §7.1 states it
    as a fact about the schema rather than a policy about its use: *"There is
    no ``is_null`` column anywhere in the tree store.  Not hidden, not nulled
    out, not ``SELECT``-excluded.  Absent.  The only way to learn a node's
    status is to hold the sidecar key."*  The refusal exists because the
    column is the one leak that pays for itself: §1's priority list puts it
    second — *"`is_null` is not a column in the tree store.  It lives in an
    encrypted sidecar whose key is held by one process.  A leak here silently
    voids every calibration number the system has ever produced, and you
    would not notice."*

    Two moments, one class:

    * **a proposal** — :func:`nulloracle.schemaguard.review_node_columns` and
      :func:`nulloracle.schemaguard.review_ddl` refuse a column list or a
      migration's DDL that names ``is_null`` for the ``node`` table, *before*
      anything is applied, so the column never lands;
    * **the standing audit** —
      :meth:`nulloracle.schemaguard.TreeStoreGuard.audit` reads the live
      store's declared columns and refuses when one is present, because
      *"keeps absent"* is a maintained state, not a one-time claim, and a
      column can arrive by a path that skipped the review (a hand-run
      ``ALTER``, a store written by an older deployment).

    Every message begins with the code ``is_null_column``
    (:data:`nulloracle.schemaguard.NULL_COLUMN`) and names the offending
    spelling, so the failure is greppable by the offender's own name — an
    uppercase ``IS_NULL`` lands identically in SQLite (column names are
    case-insensitive there), so the comparison is casefolded and a message
    that only ever said ``is_null`` would hide which spelling to drop.

    Kept outside :class:`KsGuardError` for the same reason
    :class:`HeterogeneousWorldError` is: a caller catching the store's error
    is investigating a *row* or a *connection*, and a caller catching this
    one is rejecting a *schema* — or learning the barrier is already broken,
    which is a fact no retry changes.  A migration runner that retried the
    forbidden column as a transient failure would plant exactly the leak
    §1 says nobody would notice.
    """