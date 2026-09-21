"""Feature 165's law: every sandboxed invocation carries the node's seed.

app_spec.xml, "Untrusted Code Sandbox", feature 165: *System passes the node
seed into every sandboxed invocation, persisting that seed on the node
record.*  docs/nullius-tech-architecture.md §5.2 gives the feature its call
site — the one place a run is described — and names the seed inside it::

    result = sandbox.run(
        entrypoint="signal",
        code=node.code,
        payload=window.to_arrow(),        # IPC, zero-copy
        limits=Limits(wall_s=30, cpu_s=30, mem_mb=2048,
                      network=False, filesystem=False, pids=32),
        seed=node.seed,
        env={"OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "PYTHONHASHSEED": "0"},
    )

§12's determinism table gives the seed its own row — ``Seeded RNG | seed passed
into ``signal()``; stored on the node`` — and §5.1's contract gives it its
place in the entrypoint: ``def signal(ctx: MarketWindow, seed: int)``, where
"the window is the only argument that carries data, and the seed is the only
argument that carries randomness."  P3 states what a missing seed costs, and
states it as a property of the whole method rather than of one number: *"Replay
must be bit-reproducible or the method is invalid... Non-determinism does not
announce itself; it just slowly makes every conclusion wrong."*

The sentence decomposes into four claims, each owned here as a seam rather
than a comment:

* **the node seed** — the value, and the reason it is the *node's* seed rather
  than the run's.  A seed drawn per invocation would make two invocations of
  the same node two different experiments, so a node's score would not be a
  fact about the node; §12 stores the seed *on the node* precisely so that
  re-running one node means re-drawing from the same stream.  The value is a
  non-negative integer inside the signed 64-bit range a relational store can
  hold, spelled :data:`SEED_MAX` and checked at both seams — the same bound
  feature 115's ``perm_seed`` derivation takes for the same reason, and the
  reason a seed is an ``int`` here rather than the many things a caller might
  mean by one.

* **passes ... into every sandboxed invocation** — totality, and it is the word
  that decides the reading.  *Every* invocation, not the ones that happen to
  use randomness: a signal that draws from ``random`` on one branch and not on
  another is still a seeded signal, and a launcher that passed the seed only
  where it saw a draw would be making a judgement about untrusted code's
  behaviour from trusted code's guess.  So the seed travels on the *envelope*
  every invocation is described by (:class:`SandboxInvocation`) and is handed
  over by one method every launcher calls
  (:meth:`SandboxSeed.require`), and the box's own child protocol carries it —
  §5.2's ``NULLIUS_SIGNAL_SEED`` spelling, which
  :mod:`evaluator._sandbox` already writes into the child's environment.

* **persisting that seed on the node record** — the second half, and the one
  that makes the first half checkable.  A seed that reached the run but not the
  record leaves no way to ask *which* stream produced a stored score, and a
  seed on the record that disagrees with the one the run carried is worse than
  silence: it is a plausible answer no replay would reproduce.  So
  :func:`seed_record` writes the value onto a record and refuses a record that
  already names a different one (:class:`~sandbox.errors.NodeSeedDocumentError`),
  and :func:`resolve_seed` reads a record back and refuses one that names no
  seed at all.

* **every** — and this is where the feature earns a component rather than a
  helper.  *Every* invocation is a claim a deployment has to be able to audit
  after the fact, which is what :meth:`SandboxSeed.seeded` is for: a launcher
  that dispatched a batch of invocations hands the component the ones it ran
  and gets back the offenders, by name and reason, without re-running anything.
  A law that could only refuse at the call site would leave the question *"did
  the run that produced this score carry a seed?"* unanswerable exactly where
  it matters — months later, over the artifact store.

**Why a seedless invocation is constructible and refused later.**  The
distinction mirrors the one :mod:`sandbox.isolation` draws between compiling a
document and gating a run, and it exists for the same practical reason: the
caller that needs to be told *what* is wrong with an invocation has to be able
to hold the invocation to be told.  So :class:`SandboxInvocation` is a plain
data carrier whose constructor accepts whatever the caller has — including
``None``, or nothing at all — and every refusal fires at
:meth:`SandboxSeed.require` (raised, for the launcher that must not spawn) or
:meth:`SandboxSeed.check` (returned as a :class:`SeedDecision`, for the auditor
reading a batch).  Both reach the same check; a caller never chooses which law
it applies, only which shape it wants the answer in.

**Carrying no seed, and no run.**  The composed component holds no invocation
and no seed of its own — a component shared across runs that carried one would
be a component letting two nodes share a stream, the same property
:class:`sandbox.transfer.SandboxTransfer` states for its channel.  What it
carries is the law: ``mint`` to derive a node's seed from its identity,
``require`` to hand one over as an exception, ``check`` to answer as a
decision, and ``seeded`` to audit a batch.  It also never *mints* on the
caller's behalf at gate time: a node whose record holds no seed has no seed,
and inventing one there would be minting a second answer to a question §12
says was already answered when the node was created.

**Honest limits.**  This module is the seed's *law* — the presence, the shape,
the range and the record — not the enforcement of what a signal does with it.
It cannot see inside ``random.Random(seed)`` and does not try; the modules a
submission may reach at all are feature 167's ceiling and the call-level floor
(``datetime.now``, unseeded draws) is feature 139's law at the search seam.
What holds is that a launcher using this seam cannot spawn without a seed
(:meth:`SandboxSeed.require`), that a stored record cannot be written with a
seed disagreeing with the run's, and that the seed a node's score came from is
a value the record carries and a caller can read (:func:`resolve_seed`) — so
"this score reproduced from that seed" is a fact about the store rather than a
claim in a runbook.

Stdlib-only, like the rest of the member: ``hashlib`` to mint, ``sqlite3``
nowhere (the record this module writes is the *caller's* object or dict, and
the relational column belongs to the tree member's table), and no process,
network or container runtime anywhere.  The module is the law and the caller
supplies the run and the record.
"""

from __future__ import annotations

import enum
import hashlib
from collections.abc import Iterable, Mapping
from typing import Any, Final

from .errors import (
    InvocationSeedError,
    NodeSeedDocumentError,
)

__all__ = [
    "ENV_SIGNAL_SEED",
    "MINT_SALT",
    "SEED_COMPONENT_NAME",
    "SEED_MAX",
    "SEED_MISMATCH_CODE",
    "SEED_REQUIRED_CODE",
    "SandboxInvocation",
    "SandboxSeed",
    "SeedDecision",
    "SeedReason",
    "SeedRecord",
    "check_invocation",
    "mint_node_seed",
    "resolve_seed",
    "sandbox_seed",
    "seed_record",
]

#: The component name this law registers under — beside feature 157's
#: ``sandbox``, feature 167's ``sandbox-imports`` and feature 166's
#: ``sandbox-transfer``, not instead of any of them: the factory's registry is
#: keyed by name and a later registration of the same name *replaces* the
#: earlier one, so a member carrying four controls carries four components,
#: each answering its own feature's question.
SEED_COMPONENT_NAME: Final[str] = "sandbox-seed"

#: The greppable code every seedless-invocation refusal carries — feature 165's
#: own subject written as a token, the discipline
#: :data:`sandbox.isolation.ISOLATION_REQUIRED_CODE` (``gvisor_isolation_required``)
#: and :data:`sandbox.imports.DISALLOWED_IMPORT_CODE` (``disallowed_import``)
#: apply to their features.  An operator grepping a log for the rejection finds
#: it by the feature's own words.
SEED_REQUIRED_CODE: Final[str] = "node_seed_required"

#: The greppable code carried when a *stored record* and the run disagree —
#: the second half of the feature's sentence, whose failure is a plausible
#: answer rather than an absent one and therefore wants its own token: an
#: operator looking for "a run went out unseeded" is asking a different
#: question from one looking for "a record names the wrong seed".
SEED_MISMATCH_CODE: Final[str] = "node_seed_mismatch"

#: The largest seed this law passes: ``2**63 - 1``, the top of the signed
#: 64-bit range.  The bound is not arithmetic caution — every seed Python's
#: ``random.Random`` accepts is far larger — it is *storability*: §12 requires
#: the seed be stored on the node, so a seed that cannot land in a ``BIGINT``
#: column is a run whose randomness could never be written down, and the
#: refusal belongs at the seam rather than at the write.  Feature 115's
#: ``perm_seed`` derivation takes the same ceiling for the same reason
#: ("63 bits keeps the value inside the signed 64-bit range a relational store
#: can hold if the seed is ever mirrored beside the bit").
SEED_MAX: Final[int] = 2**63 - 1

#: The environment variable §5.2's child protocol carries the seed in — the one
#: spelling :mod:`evaluator._sandbox` already writes (``env["NULLIUS_SIGNAL_SEED"]``)
#: and the child runner reads back out.  Restated here as a constant rather than
#: imported from the evaluator, because the sandbox member depends on no other
#: member: the two spellings must agree, and the member's tests pin that they
#: do — the same one-provenance discipline the category's other vocabularies
#: take.
ENV_SIGNAL_SEED: Final[str] = "NULLIUS_SIGNAL_SEED"

#: The domain separator :func:`mint_node_seed` derives a node's seed under.
#: Salted so the digest cannot collide with a seed another feature derives from
#: the same identity — feature 115 derives a ``perm_seed`` from
#: ``"<campaign>\x00<node>"`` under no salt at all, and the two must not produce
#: one number for one node: a permutation seed and a run seed answer different
#: questions about the same node, and a deployment that had them coincide would
#: have one value doing two jobs.
MINT_SALT: Final[str] = "nullius.sandbox.node-seed"

#: The fields a node record must carry for this law to read a seed from it —
#: the *name* the seed is persisted under, in the shapes §9.1's ``node`` table
#: and the members' own record objects both spell it.  A record that names the
#: seed under none of these has no seed, which is a refusal rather than a
#: default.
_SEED_FIELDS: Final[tuple[str, ...]] = ("seed", "node_seed", "signal_seed")

#: The types this law refuses *by name* because they look like a seed at a call
#: site without being one — a tuple rather than a frozenset because it is spent
#: as the second argument to :func:`isinstance`, and the membership is what the
#: guard asks rather than a set it iterates.  ``bool`` is listed even though
#: Python's ``bool`` *is* an ``int`` subclass: ``True`` is not a seed anyone
#: meant to write, the same exclusion
#: :func:`nulloracle.assignment._validated_perm_seed` states for the oracle's
#: own field.  The list is not exhaustive on purpose — the guard also refuses
#: any type that is simply not an ``int`` — so it names the *near misses*, the
#: ones whose refusal gets its own sentence in :func:`_shape_consequence`.
_NOT_A_SEED: Final[tuple[type, ...]] = (bool, float, str, bytes)


def _refusal(value: Any, spelling: str, *, consequence: str) -> str:
    """The operator-facing sentence for a seed this law will not pass.

    One body rather than five literals: every refusal this module raises says
    the same three things in the same order — what was found, which spelling of
    it that was, and what the run would have cost — and a caller that had to
    read five differently-worded messages to learn the same fact would be
    reading prose rather than reading a code.
    """
    return (
        f"{SEED_REQUIRED_CODE}: a sandboxed invocation was offered with "
        f"{spelling} (got {value!r}, {type(value).__name__}). {consequence}"
    )


def _missing_consequence() -> str:
    """The consequence for an invocation that carries no seed at all."""
    return (
        "§5.2's call site passes ``seed=node.seed`` because §5.1's entrypoint "
        "declares ``signal(ctx, seed)`` and 'the seed is the only argument that "
        "carries randomness'; a run that reached the box without one would draw "
        "from the interpreter's own entropy, so its score vector would be "
        "unreproducible and — worse — would look exactly like a correct one. "
        "P3: 'Replay must be bit-reproducible or the method is invalid.' The "
        "invocation is refused before it is spawned (feature 165)."
    )


def _shape_consequence(value: Any) -> str:
    """The consequence for a seed of the wrong type."""
    kind = type(value).__name__
    if kind == "str":
        extra = (
            " A seed that arrived as text — the spelling an environment "
            "variable or a JSON document carries it in — is a different type "
            "in a different place from the integer ``signal()`` is called "
            "with, and coercing it here would hide which side of that "
            "boundary the conversion was missing from."
        )
    elif kind == "bool":
        extra = (
            " ``True`` is an ``int`` in Python and is deliberately not a "
            "seed: it is not a value anyone meant to write, and accepting it "
            "would make a flag and a stream indistinguishable."
        )
    elif kind == "float":
        extra = (
            " A float is refused even when integral (``42.0``): the seed is "
            "stored on the node as an integer, and a store that had to "
            "tolerate both spellings would be one where two records can say "
            "the same seed differently."
        )
    else:
        extra = ""
    return (
        "The seed is one non-negative integer, because §12 stores it on the "
        f"node record as one number with one meaning.{extra} The invocation is "
        "refused rather than coerced (feature 165)."
    )


def _range_consequence(value: Any) -> str:
    """The consequence for an integer outside the seed's range."""
    return (
        f"A seed must be a non-negative integer at or below {SEED_MAX} "
        f"(2**63 - 1). The upper bound is storability rather than arithmetic: "
        f"§12 requires the seed be written on the node record, so a seed that "
        f"cannot land in the signed 64-bit column that holds it is a run whose "
        f"randomness could never be written down — and the refusal belongs "
        f"here, at the seam, rather than at a write that would fail later with "
        f"less to say. The invocation is refused (feature 165)."
    )


def _classify(value: Any) -> tuple[int | None, SeedReason, str]:
    """Classify ``value`` as a seed, returning ``(seed, reason, sentence)``.

    ``(None, reason, sentence)`` means refused, and the tuple is how
    :class:`SeedDecision`, :class:`~sandbox.errors.InvocationSeedError` and the
    record write stay one implementation: all three read the same
    classification, so a decision and an exception can never disagree about
    whether a value was a seed, and there is one body of prose per reason
    rather than a literal at each seam.

    The order of the checks is the order a reader would want them in, and it is
    deliberately *not* the order of feature 165's sentence: the type is settled
    before the range, because ``-1.5``'s problem is that it is not an integer
    rather than that it is negative, and a refusal that named the range first
    would send an operator looking for a bound when the value never had the
    right type to be bounded by one.
    """
    if value is None:
        return None, SeedReason.WITHOUT_SEED, _refusal(
            value, "no seed at all", consequence=_missing_consequence()
        )
    if isinstance(value, _NOT_A_SEED) or not isinstance(value, int):
        return None, SeedReason.MALFORMED_SEED, _refusal(
            value,
            "a seed that is not an integer",
            consequence=_shape_consequence(value),
        )
    if value < 0 or value > SEED_MAX:
        return None, SeedReason.OUT_OF_RANGE, _refusal(
            value,
            "a seed outside the storable range",
            consequence=_range_consequence(value),
        )
    return value, SeedReason.BY_SEED, ""


def _seed_value(value: Any) -> int | None:
    """The seed ``value`` is, or ``None`` — the membership question alone.

    The shorter spelling for the two callers that only have to decide *did this
    yield a seed* — :func:`_validated_record_seed` reading a record and
    :func:`seed_record` validating its argument — where unpacking a reason and a
    sentence they are not going to use would be noise.  The full classification
    is :func:`_classify`, and this is one call into it rather than a second
    opinion about what a seed is.
    """
    seed, _reason, _detail = _classify(value)
    return seed


class SeedReason(enum.StrEnum):
    """Why an invocation was admitted or refused — the audit vocabulary.

    One enumeration carries the acceptance and the refusals, for the reason
    :class:`sandbox.isolation.RunReason` does: a decision's reason is one fact
    with two polarities and the audit line should read the same either way —
    ``by-seed`` names the value the invocation was admitted on, and the
    refusals name what was found instead.
    """

    #: Admitted: the invocation carries a non-negative integer inside the
    #: storable range, and — when a record was consulted — the record names the
    #: same one.
    BY_SEED = "by-seed"

    #: Refused: the invocation carries no seed at all.  The keyword was never
    #: passed, or it was passed as ``None`` — the two spellings of the same
    #: absence, and deliberately not split apart: "there is no seed here" is one
    #: fact whether the caller omitted it or wrote ``None`` explicitly, and a
    #: caller forced to catch both would miss the one its launcher produced.
    WITHOUT_SEED = "without-node-seed"

    #: Refused: a value was offered and it is not a seed — a string, a float, a
    #: ``bool``, any other type.  Split from :attr:`WITHOUT_SEED` because the
    #: repair is different: an absent seed is looked for at the call site, a
    #: mistyped one at whatever produced it.
    MALFORMED_SEED = "malformed-seed"

    #: Refused: a genuine integer outside ``[0, SEED_MAX]``.  Its own reason
    #: rather than a spelling of the last one, because a negative or oversized
    #: integer *is* a seed-shaped value with a value-shaped problem, and an
    #: operator reading ``malformed-seed`` would go looking for a type bug.
    OUT_OF_RANGE = "out-of-range-seed"

    #: Refused: the invocation carries a good seed and the node record it is to
    #: be persisted on names a *different* one.  The second half of the
    #: feature's sentence, and the only reason here that is about the record
    #: rather than about the run.
    RECORD_MISMATCH = "node-seed-mismatch"


class SandboxInvocation:
    """One sandboxed invocation, as described to the seeder.

    Feature 165's sentence is about *every sandboxed invocation*, and §5.2
    describes one as a call: the code, the payload, the limits, the seed, the
    env.  This models exactly the half of that call this law has a claim
    about — the seed, the node it belongs to and the env the seed travels in —
    and deliberately does not model the rest: the limits are features 162's and
    163's, the payload is feature 166's, and a boundary that also modelled them
    would be a second, divergent copy of ``evaluator._sandbox``'s call shape,
    the mistake :class:`sandbox.isolation.SandboxRun` names for itself.

    **Its constructor refuses nothing.**  A caller holding an invocation that
    is missing its seed is the caller that most needs to be told so, and it
    cannot be told about an object it was never allowed to build.  So every
    field is taken as given — including ``seed=None``, which is what
    ``getattr(node, "seed", None)`` returns for a node record that has none —
    and the refusals live at :meth:`SandboxSeed.require` and
    :meth:`SandboxSeed.check`.  The one thing the constructor *does* do is copy
    ``env``, so a caller that mutates the mapping it passed cannot change what
    an invocation carries after the fact.

    **The env is where the seed actually crosses.**  §5.2's call passes
    ``seed=node.seed`` as an argument *and* §12's BLAS rows pass their values in
    ``env``; the child protocol
    :mod:`evaluator._sandbox` implements crosses the seed in the environment
    (:data:`ENV_SIGNAL_SEED`), so :meth:`with_seed` writes it there and the
    env is read back by :meth:`SeedDecision.seed_env`.  The seed is one value
    written in two places — the argument and the child's environment — and this
    object is where the two are made to agree rather than left to.
    """

    __slots__ = ("component", "env", "node_id", "seed")

    def __init__(
        self,
        *,
        node_id: str,
        seed: Any = None,
        component: str = "",
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.node_id = node_id
        self.seed = seed
        self.component = component
        self.env = dict(env) if env is not None else {}
        # The seed's own crossing: an invocation that carries one carries it in
        # the child's environment too, because that is the spelling the box
        # reads.  A string env value that disagrees with the integer carried
        # here is corrected rather than refused — the argument is the
        # authority, and the env is the transport.
        if seed is not None:
            self.env[ENV_SIGNAL_SEED] = str(seed)

    def with_seed(self, seed: Any) -> SandboxInvocation:
        """A copy of this invocation carrying ``seed`` — the setter that can.

        Returns a new object rather than mutating: an invocation is a
        description of a run that either happened or did not, and a launcher
        that re-seeded one in place would leave two callers holding two
        descriptions of two runs that are the same object.
        """
        return SandboxInvocation(
            node_id=self.node_id,
            seed=seed,
            component=self.component,
            env=self.env,
        )

    def with_record(self, record: Any) -> SandboxInvocation:
        """A copy whose seed comes from ``record`` — the read half, at the seam.

        The convenience for the launcher that holds a node record and wants the
        invocation described from it: :func:`resolve_seed` reads the record
        (refusing one that names no seed), and the copy carries what it found.
        Deliberately *not* a fallback — a record with no seed is refused by
        :func:`resolve_seed` rather than silently leaving this invocation as it
        was, because "the record had none so the run kept its own" is exactly
        the two-statements-disagreeing state this feature exists to rule out.
        """
        return self.with_seed(resolve_seed(record))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"SandboxInvocation(node_id={self.node_id!r}, "
            f"seed={self.seed!r}, component={self.component!r})"
        )


class SeedDecision:
    """The gate's whole answer: admitted or not, why, and in what words.

    ``admitted`` is the one field a caller must check, and it is *computed*
    from the classified seed rather than set by a constant — the same
    "computed, never assumed" stance :class:`sandbox.isolation.RunDecision`
    takes for a run.  ``detail`` is the operator-facing sentence, and
    ``seed`` is the value the invocation was admitted on — ``None`` for every
    refusal, so a caller reading ``decision.seed`` after checking ``admitted``
    has the integer rather than a sentinel.
    """

    __slots__ = ("admitted", "detail", "node_id", "reason", "seed")

    def __init__(
        self,
        *,
        admitted: bool,
        reason: SeedReason,
        detail: str,
        node_id: str,
        seed: int | None = None,
    ) -> None:
        self.admitted = admitted
        self.reason = reason
        self.detail = detail
        self.node_id = node_id
        self.seed = seed

    def require(self) -> int:
        """Return the seed, or raise :class:`~sandbox.errors.InvocationSeedError`.

        The bridge between the gate's returned answer and the exception a
        launcher wants on its last line before spawning: a decision that
        admitted the invocation returns its seed, so a caller can write
        ``seed = seed_law.require(invocation)`` and have the law enforced there
        rather than remembered.  A refusal raises the same error type the
        direct :meth:`SandboxSeed.require` raises — one law, two shapes.
        """
        if not self.admitted:
            raise InvocationSeedError(self.detail)
        return int(self.seed)  # type: ignore[arg-type]

    def seed_env(self, base: Mapping[str, str] | None = None) -> dict[str, str]:
        """The child environment carrying this decision's seed.

        The seed's *transport*, in the spelling §5.2's call site and the box's
        child protocol use (:data:`ENV_SIGNAL_SEED`): ``base`` copied, never
        mutated, with the variable written onto the copy — the same
        copy-then-write discipline
        :meth:`evaluator._sandbox.SignalSandbox._child_env` applies to the
        determinism variables, so two invocations built from one environment do
        not fight over it.  Refused for a decision that admitted nothing: an
        unseeded environment is not a transport of anything, and handing one
        back would let a spawn proceed with the law's answer silently dropped.
        """
        if not self.admitted:
            raise InvocationSeedError(self.detail)
        env = dict(base) if base is not None else {}
        env[ENV_SIGNAL_SEED] = str(self.seed)
        return env

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"SeedDecision(admitted={self.admitted}, reason={self.reason!r}, "
            f"node_id={self.node_id!r})"
        )


class SeedRecord:
    """One node's seed as it is persisted — the write's receipt.

    ``seed`` is the value written; ``superseded`` is the value it replaced, or
    ``None`` for a first write.  The history is carried for the reason
    :mod:`tripwires.node_metric` states for its own column write: a *record*
    holds one seed — that is what §12's row asks for — so the receipt is where
    the fact "this was re-seeded" survives, for a caller that needs to say how
    far a node's stream moved.  A refresh to the *same* value is not a
    supersession and reports ``None``: rewriting one seed over itself is not
    news, and reporting it as a change would make every idempotent write look
    like a re-seed.
    """

    __slots__ = ("node_id", "seed", "superseded")

    def __init__(
        self, *, node_id: str, seed: int, superseded: int | None = None
    ) -> None:
        self.node_id = node_id
        self.seed = seed
        self.superseded = superseded

    @property
    def reseeded(self) -> bool:
        """Whether this write replaced a different seed."""
        return self.superseded is not None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"SeedRecord(node_id={self.node_id!r}, seed={self.seed!r}, "
            f"superseded={self.superseded!r})"
        )


def mint_node_seed(node_id: Any) -> int:
    """Derive a node's seed from its identity — the value §5.2 calls ``node.seed``.

    A node's seed has to come from *somewhere*, and the two candidates are a
    draw and a derivation.  A draw makes the seed a fact about when the node was
    created rather than about the node: two campaigns planned over the same tree
    would seed the same node differently, and a node copied into a second
    campaign would carry a stream nobody could re-derive.  A derivation makes
    the seed a *function of the node's identity*, so "what seed was this node
    run under?" is answerable from the identity alone — the property
    :func:`nulloracle.selection.perm_seed_for` takes for the permutation seed
    and states at length.

    ``sha256`` rather than :func:`hash`, for the reason feature 138 pins
    ``PYTHONHASHSEED``: the builtin is salted per process, so a seed derived
    with it would change between two runs of the same pipeline and the node's
    stored seed would be wrong by the second invocation.  The digest's first
    eight bytes, read big-endian and shifted down one bit, land inside
    ``[0, SEED_MAX]`` — always non-negative, always storable, which is what
    lets the value this mints pass :func:`check_invocation` by construction.

    A node id that is not a non-empty string is refused by name: a seed derived
    from an identity that cannot join the tree store's ``node.id`` names no node
    whose run it could reproduce.
    """
    if not isinstance(node_id, str) or not node_id.strip():
        raise InvocationSeedError(
            f"{SEED_REQUIRED_CODE}: a node seed cannot be minted for "
            f"{node_id!r} ({type(node_id).__name__}). This derivation is keyed "
            f"on the node's identity — that is the whole reason it is a "
            f"derivation rather than a draw — and an identity that is not a "
            f"non-empty string names no node whose stream it could reproduce "
            f"(feature 165)."
        )
    digest = hashlib.sha256(f"{MINT_SALT}\x00{node_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") >> 1


def check_invocation(invocation: SandboxInvocation) -> SeedDecision:
    """Answer one invocation: admitted only when it carries a seed this law passes.

    The gate, and the one place the law is actually applied — every other verb
    in this module (:meth:`SandboxSeed.require`, :meth:`SeedDecision.require`,
    :meth:`SandboxSeed.seeded`) reaches this function rather than re-checking.
    Nothing is raised here, for the reason features 157's and 167's gates raise
    nothing: the pipeline offers thousands of invocations and *"this one has no
    seed"* must reach an operator as a fact about a run rather than as a crashed
    evaluator, while a caller that must not spawn turns the answer into an
    exception with :meth:`SeedDecision.require`.
    """
    node = getattr(invocation, "node_id", None)
    value = getattr(invocation, "seed", None)
    seed, reason, detail = _classify(value)

    if seed is None:
        return SeedDecision(
            admitted=False,
            reason=reason,
            node_id=node,
            detail=detail,
        )

    return SeedDecision(
        admitted=True,
        reason=SeedReason.BY_SEED,
        node_id=node,
        seed=seed,
        detail=(
            f"invocation of component {getattr(invocation, 'component', '')!r} "
            f"for node {node!r} admitted: it carries node seed {seed} — a "
            f"non-negative integer inside the range [0, {SEED_MAX}] a node "
            f"record can store. §5.2's call site passes ``seed=node.seed`` into "
            f"``signal(ctx, seed)``, and §12's determinism row is 'Seeded RNG | "
            f"seed passed into signal(); stored on the node' (feature 165)."
        ),
    )


def _validated_record_seed(record: Any, *, node_id: str) -> int | None:
    """Read the seed a node record names, or ``None`` when it names none.

    Reads a mapping or an object, because the two shapes both occur in this
    repository: §9.1's ``node`` row arrives from a relational driver as a
    mapping, while the members' own record objects
    (``snapshot._recomputation.NodeRecord``, the evaluator's dataclasses) carry
    the field as an attribute.  A record of neither shape names no seed, which
    is the honest answer rather than a type error: the caller asked *what seed
    does this hold?* and "this holds none" answers it.
    """
    for field in _SEED_FIELDS:
        if isinstance(record, Mapping):
            value = record.get(field, None)
            present = field in record
        else:
            present = hasattr(record, field)
            value = getattr(record, field, None) if present else None
        if not present:
            continue
        if value is None:
            continue
        seed = _seed_value(value)
        if seed is None:
            raise NodeSeedDocumentError(
                f"{SEED_MISMATCH_CODE}: the node record for {node_id!r} carries "
                f"{field} = {value!r} ({type(value).__name__}), which is not a "
                f"seed this law can persist or read back. §12 stores the seed a "
                f"run drew from on the node *as one integer with one meaning*; "
                f"a record whose seed is a string, a float or a negative number "
                f"is one no replay could draw from, and the record is refused "
                f"rather than the field skipped — a caller told 'no seed' would "
                f"go on to mint a second one and overwrite the evidence "
                f"(feature 165)."
            )
        return seed
    return None


def resolve_seed(record: Any, *, node_id: str | None = None) -> int:
    """Read the seed a node record persisted, refusing one that names none.

    The read half of *persisting that seed on the node record*, for the two
    callers that need it: a launcher describing an invocation from a node it
    loaded, and an auditor asking which stream a stored score came from.  A
    record that names no seed raises rather than returning ``None``, because
    every caller of this function has already decided it *has* a node and wants
    its seed — and a ``None`` would travel one frame further before becoming an
    unexplainable absence, the "absence that reads as a result" failure this
    member's transfer law states for its own missing vector.
    """
    node = node_id if node_id is not None else _record_node_id(record)
    seed = _validated_record_seed(record, node_id=node)
    if seed is None:
        raise NodeSeedDocumentError(
            f"{SEED_MISMATCH_CODE}: the node record for {node!r} names no seed "
            f"(looked for {list(_SEED_FIELDS)!r} on a "
            f"{type(record).__name__}). Feature 165's second half is "
            f"*persisting that seed on the node record*, and §12's determinism "
            f"row is the reason it is half the feature: without the stored "
            f"value there is no way to ask which stream a node's score came "
            f"from, so a score produced by a seedless run and one produced by a "
            f"seeded run are indistinguishable in the artifact store. Refused "
            f"by name rather than answered with a None, and deliberately not "
            f"filled in with a minted replacement — minting here would write a "
            f"second answer over a question that was settled when the node was "
            f"created (feature 165)."
        )
    return seed


def _record_node_id(record: Any) -> str:
    """The node id a record names — for a refusal's message, not for a key.

    Best-effort by design: this is read while building an error message, and a
    record that names no id must still produce a readable refusal rather than a
    second failure inside the first.  Every identifier field the repository's
    node shapes use is tried, and an unidentified record is reported as such.
    """
    for field in ("node_id", "id", "node"):
        if isinstance(record, Mapping):
            value = record.get(field, None)
        else:
            value = getattr(record, field, None)
        if isinstance(value, str) and value.strip():
            return value
    return "<unidentified node>"


def seed_record(record: Any, seed: Any, *, node_id: str | None = None) -> SeedRecord:
    """Persist ``seed`` onto a node record, refusing a contradicting one.

    Feature 165's second half, as one verb.  Given a mutable mapping or object
    — §9.1's ``node`` row, a member's own record — this writes the seed under
    :data:`_SEED_FIELDS`\\ [0] (``seed``, the name §5.2's call site uses) and
    returns the :class:`SeedRecord` that says what was written and what it
    replaced.

    **A record naming a different seed is refused, not overwritten.**  This is
    the one judgement in the module that could reasonably have gone the other
    way, and it goes this way for a reason worth stating: a record and an
    invocation are two statements about *one* run.  Silently overwriting means a
    node that was run under seed ``7`` and later described under seed ``9`` ends
    up with a record saying ``9`` and an artifact produced from ``7`` — a
    replayed score that disagrees with its own node and no trace of why.  So the
    write refuses and names both values.  Re-persisting the *same* seed is not a
    contradiction and is idempotent; it reports ``superseded=None``, because an
    idempotent write is not news.

    The seed itself is validated the same way an invocation's is — one check,
    two seams — so a caller cannot get an unvalidated value into the record by
    taking this path instead of that one.
    """
    node = node_id if node_id is not None else _record_node_id(record)
    checked, _reason, detail = _classify(seed)
    if checked is None:
        raise InvocationSeedError(detail)

    existing = _validated_record_seed(record, node_id=node)
    if existing is not None and existing != checked:
        raise NodeSeedDocumentError(
            f"{SEED_MISMATCH_CODE}: the node record for {node!r} already names "
            f"seed {existing}, and the invocation to be persisted carries seed "
            f"{checked}. A record and an invocation are two statements about "
            f"one run, and §12 stores the seed on the node so that a stored "
            f"score can be re-run from the stream it actually drew from — a "
            f"record overwritten to {checked} beside an artifact produced from "
            f"{existing} is a node whose score no replay reproduces and whose "
            f"record says otherwise, which is worse than a record with no seed "
            f"at all because it is a plausible answer. Refused rather than "
            f"overwritten; re-persist the same seed, or re-run the node "
            f"(feature 165)."
        )

    _write_record_seed(record, checked)
    return SeedRecord(
        node_id=node,
        seed=checked,
        superseded=existing if existing is not None and existing != checked else None,
    )


def _write_record_seed(record: Any, seed: int) -> None:
    """Write ``seed`` onto a record under the canonical field name.

    A mapping takes the key; an object with a ``seed`` slot or attribute is set
    the way the object allows — ``setattr`` for the plain dataclasses this
    repository's stores return, and a refusal by name for anything else, since
    a record this law cannot write is a record whose seed will not be persisted
    and a caller has to hear that rather than infer it from a silent no-op.
    """
    field = _SEED_FIELDS[0]
    if isinstance(record, dict):
        record[field] = seed
        return
    if isinstance(record, Mapping):
        try:
            record[field] = seed  # type: ignore[index]
            return
        except TypeError as exc:
            raise NodeSeedDocumentError(
                f"{SEED_MISMATCH_CODE}: the node record is an immutable "
                f"mapping ({type(record).__name__}), so seed {seed} cannot be "
                f"persisted on it. Feature 165's second half writes the seed "
                f"down; a record that refuses the write would report a "
                f"persistence that never happened (feature 165)."
            ) from exc
    try:
        setattr(record, field, seed)
    except (AttributeError, TypeError) as exc:
        raise NodeSeedDocumentError(
            f"{SEED_MISMATCH_CODE}: the node record ({type(record).__name__}) "
            f"cannot carry a persisted seed — it takes neither a {field!r} key "
            f"nor a {field!r} attribute. The seed has to land *on the node "
            f"record* for §12's determinism row to be checkable, and this law "
            f"refuses to report a persistence it could not perform "
            f"(feature 165)."
        ) from exc


class SandboxSeed:
    """Feature 165's law, as the value a composed application carries.

    A stateless facade over this module — the same shape
    :class:`sandbox.SandboxIsolation` gives feature 157,
    :class:`sandbox.SandboxImports` gives feature 167 and
    :class:`sandbox.SandboxTransfer` gives feature 166 — so a caller holding
    the composed component can ask the feature's question, *does this
    invocation carry the node's seed, and is it the one the record names?*,
    without importing the member's submodules by name.

    It carries nothing: no invocation, no seed, no store.  A seed belongs to
    one node and a component shared across runs that carried one would let two
    nodes share a stream — the property :class:`sandbox.transfer.SandboxTransfer`
    states for its channel, restated here because the failure is the same one
    in a different quantity.

    **``require`` is the verb the launcher wants, and it returns the seed.**
    :meth:`check` answers as a value for a caller that wants to branch, and
    :meth:`require` turns a refusal into
    :class:`~sandbox.errors.InvocationSeedError` — while *returning* the
    integer when it does not, which is what lets a launcher write one line::

        seed = law.require(SandboxInvocation(node_id=node.id, seed=node.seed))
        sandbox.run(code, window, seed=seed)

    A verb that returned ``None`` on success would make the caller read the
    seed off the invocation a second time, and the two readings are exactly the
    pair that can drift.

    **The delegation is deliberately thin** — each verb is one call into this
    module — because a second implementation of the range check or the record
    comparison here would be a second thing to keep in sync, and the member's
    one-provenance rule exists so that cannot happen.
    """

    __slots__ = ()

    def check(
        self, invocation: SandboxInvocation, *, record: Any = None
    ) -> SeedDecision:
        """Answer whether ``invocation`` carries a seed this law passes.

        With ``record`` given, the answer also covers feature 165's second
        half: a record that names a *different* seed is refused with
        :attr:`SeedReason.RECORD_MISMATCH`, because the seed about to be
        persisted and the seed already on the node are two statements about one
        run.  A record naming no seed at all is not a mismatch — it is an
        unpersisted node, which this law's write half exists to fill in — so
        only a genuine disagreement refuses.
        """
        decision = check_invocation(invocation)
        if not decision.admitted or record is None:
            return decision

        existing = _validated_record_seed(record, node_id=decision.node_id)
        if existing is not None and existing != decision.seed:
            return SeedDecision(
                admitted=False,
                reason=SeedReason.RECORD_MISMATCH,
                node_id=decision.node_id,
                detail=(
                    f"{SEED_MISMATCH_CODE}: the invocation for node "
                    f"{decision.node_id!r} carries seed {decision.seed}, and "
                    f"the node record already names seed {existing}. §12 stores "
                    f"the seed on the node so a stored score can be re-run from "
                    f"the stream it actually drew from; an invocation dispatched "
                    f"under one seed and persisted beside a record naming "
                    f"another produces a node whose score no replay reproduces "
                    f"and whose record says otherwise. Refused before the spawn "
                    f"(feature 165)."
                ),
            )
        return decision

    def require(
        self, invocation: SandboxInvocation, *, record: Any = None
    ) -> int:
        """Return the invocation's seed, or raise the refusal.

        The launcher's verb: one call, the invocation, and either the integer to
        pass to the box or
        :class:`~sandbox.errors.InvocationSeedError` carrying the gate's own
        operator-facing sentence.  Put on the last line before the spawn, it
        makes *"every sandboxed invocation carries the node's seed"* enforced
        there rather than remembered.
        """
        return self.check(invocation, record=record).require()

    def seeded(
        self, invocations: Iterable[SandboxInvocation], *, records: Any = None
    ) -> tuple[SeedDecision, ...]:
        """The refusals among a batch — *every* invocation, audited.

        Feature 165's totality word, made checkable after the fact: a launcher
        that dispatched a batch hands over what it ran and gets back the
        invocations that did not carry a seed (or contradicted their record), in
        order, each with its own reason and sentence.  An empty tuple is the
        audit's pass — and deliberately an empty tuple rather than ``True``,
        because the useful audit output is *which* runs failed, not whether any
        did, and a caller that only wanted the boolean reads ``not law.seeded(...)``.

        ``records`` is the matching sequence of node records, when the caller
        has them: passed, each invocation is checked against its own record as
        :meth:`check` does.  A batch is refused whole rather than partially when
        the two sequences disagree in length, because an audit that silently
        paired invocation *i* with record *j* would answer a question nobody
        asked.
        """
        items = list(invocations)
        pairs: list[Any]
        if records is None:
            pairs = [None] * len(items)
        else:
            record_list = list(records)
            if len(record_list) != len(items):
                raise InvocationSeedError(
                    f"{SEED_REQUIRED_CODE}: an audit was handed "
                    f"{len(items)} invocation(s) and {len(record_list)} node "
                    f"record(s). The second sequence is what each invocation's "
                    f"seed is checked *against*, so a batch of two different "
                    f"lengths has no pairing that means anything — and an audit "
                    f"that silently zipped the shorter against the longer would "
                    f"report on runs that were never checked (feature 165)."
                )
            pairs = record_list

        refusals: list[SeedDecision] = []
        for invocation, record in zip(items, pairs):
            decision = self.check(invocation, record=record)
            if not decision.admitted:
                refusals.append(decision)
        return tuple(refusals)


def sandbox_seed() -> SandboxSeed:
    """The seed law, for a caller that wants it directly.

    Not a component and not registered: a component whose builder *ran* the law
    would have nothing to run it *on*, since the law needs an invocation to
    answer for.  This is the module-level convenience the member's own tests and
    any operator script reach, and it is the same call
    :func:`sandbox.build_sandbox_seed` makes minus the composition.
    """
    return SandboxSeed()
