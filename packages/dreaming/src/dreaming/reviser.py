"""Feature 271, the revision sweep — the production half of the dreaming loop.

app_spec.xml, "Dreaming Loop & Meta-Selection", feature 271: *System produces M
revisions of the exploration policy source between iterations, which returns
candidate modules.*  docs/alpha-engine-prd.md §C5 states the act this module
performs as the first clause of the loop's middle rung — *"run ``M`` code
revisions of ``π``"* — and §12.1 gives the reason the clause is load-bearing:

    Per outer iteration: hold the replay pool fixed, run ``M`` code revisions
    of ``π``, evaluate each on every stored tree, select the argmax under §7.

This module is the **production** half of that sentence and nothing else.  It
takes the incumbent policy's authored source — the caller already holds it, the
same source feature 230 admitted before the cycle opened — and answers ``M``
candidate modules, one per revision index ``1..M``, each a complete Python
module the replay engine can import and replay (feature 272), with the
incumbent recorded as each candidate's ``parent_version`` so feature 273 can
add ``π^0 = π_t`` back into the candidate set and feature 274 can persist the
argmax's ``module_id`` and ``code_hash`` into ``policy_revision``.  It does
**not** run a policy, score a world, read the pool, keep the incumbent, select
a winner or write a row — those are features 272, 273 and 274, parallel
siblings that *consume* the candidates this module produces, and this module
imports none of them and assumes none of them present.

**A candidate is a value, and its identity is its source.**  A candidate module
is :class:`CandidateModule`, a frozen ``__slots__`` value carrying exactly five
facts: the revised ``source`` (non-empty text), its ``code_hash`` (the sha256
of that source — the identity feature 274 persists to
``policy_revision.code_hash``, migration ``0109``), its ``module_id`` (a version
string derived from the code_hash, the spelling the loop hands to feature 274 as
``policy_version``), its ``parent_version`` (``None`` for a root, the incumbent's
version otherwise — ``π^0``'s own version, which is what lets feature 273 put the
incumbent back) and its ``revision_index`` (a genuine positive integer, ``1..M``).
The value is built only through :func:`candidate_module`, the one spelling of a
candidate, so the sweep and any later feature in this category construct one the
same way — the discipline :func:`dreaming.cycle.pool_commitment` keeps for the
commitment and :func:`dreaming.split.split_replay_pool` for the split.  It is
frozen with hand-written ``__slots__`` and validated at construction, the
member's :class:`~dreaming.cycle.FreezeRecord` stance, so two callers holding one
candidate cannot move each other's source.

**The revision is structure-preserving, and admissible by construction.**  The
default reviser — :func:`default_reviser`, the ``REVISION_BAND`` half-width the
loop's offline tuning replaces, exactly the way feature 277's schedule and
feature 227's ``_PATIENCE_FLOOR`` state a named default the cycle supersedes —
parses the incumbent with :mod:`ast`, jitters **only the numeric-literal values**
by a deterministic bounded factor in ``[1 − REVISION_BAND, 1 + REVISION_BAND]``,
and unparses with ``ast.unparse``.  It changes no identifier, no control-flow
node, no call, no import and no comparison operator: the AST's *skeleton* is
byte-for-byte the incumbent's, and only the magnitudes at its numeric leaves
move.  That is why a candidate descended from an admitted incumbent is
admissible — it carries none of feature 230's four anti-patterns (no absolute
score constant, no hardcoded node id, ``commit()`` reachable on every
terminating path) and none of feature 231's learned component, because those
checks look at *structure* — an identifier, a string, a call, a terminating
path — and the transform alters a magnitude where they do not look.  A zero
constant is jittered **additively** so it is not annihilated to zero, and a bool
literal is left untouched, because a boolean is a branch, not a tunable
magnitude.  The loop screens each produced candidate with policy-runtime's
``screen_policy`` (feature 230, in the policy-runtime member) before replay —
feature 271 produces candidates admissible by construction and feature 230
pronounces admissibility, two acts across two members this module never joins —
but the candidate that crosses the boundary is only ever the source, and a
candidate the gate refuses is the loop's to discard, not this module's to
pre-refuse.

**Deterministic, and therefore reproducible.**  The jitter factor at each
literal site is a pure function of ``(seed, revision_index, site)`` derived via
:func:`hashlib.sha256` — no :mod:`random`, whose stream is not portable across
processes — so the same ``(incumbent source, count, seed)`` answers the same
candidate modules to the last ``code_hash`` in any process, the determinism
contract docs §12 states one level down from the number.  The seed is the
cycle's own act: the loop passes a cycle-derived seed (the iteration id, the way
feature 279 keys its holdout rotation on the cycle's name), so a retried sweep at
the same seed reproduces the same candidates the way feature 279 reproduces the
same holdout.  The seed drives only the draw — it is never stored, and the same
seed reproduces the same candidates.

**Distinctness is a verdict, not a silence.**  :func:`revise_policy` deduplicates
the candidates it produces by ``code_hash`` and, if fewer than ``count`` distinct
candidates remain, **refuses** with :class:`~dreaming.errors.RevisionError`
naming the shortfall — a policy whose authored numeric constants cannot fund
``M`` distinct perturbations names no sweep of that size, and returning
duplicates would collapse feature 274's argmax onto one source.  The default
reviser therefore requires an incumbent carrying perturbable constants; a source
with none is the shortfall's common case and is refused, not padded.  That is a
*production* verdict rather than a malformed ask — the count was legal — so the
repair is the developer's: grow the incumbent's authored constants, or shrink
``M``.

**Pure, and read-side.**  :func:`revise_policy` reads the incumbent source the
caller already holds and opens no database, reads no pool row, resolves no path,
imports nothing that could (no :mod:`sqlite3`, no :mod:`os`, no environment).
``depends_on="270"`` in the spec is the loop-ordering fact — the sweep runs
inside the outer iteration whose pool feature 270 holds fixed — and it is **not**
a code dependency: this module imports nothing from :mod:`dreaming.cycle`, the
way the member's no-cross-member rule requires.  The count is *taken*, not
decided: :func:`revise_policy` accepts the ``count`` it is handed and produces
one candidate per index — it does not cap it (feature 276's ceiling refuses a
too-wide sweep *before* the loop calls this) and does not read the pool to size
it (feature 275's floor is the loop's precondition, checked before the sweep — a
pool too thin to dream on is refused before :func:`revise_policy` is ever called,
so this module mints no thin-pool refusal and imports no ladder).  A pluggable
``reviser`` lets a deployment substitute its own ``(incumbent_source,
revision_index, seed) -> source`` policy-development strategy without moving the
contract.

Stdlib only, and import-cheap: :mod:`ast`, :mod:`hashlib` and this member's own
errors, so the factory's scan — which imports this package to fire its
``@register`` — pays nothing for a module it never composes.
"""

from __future__ import annotations

import ast
import hashlib
from collections.abc import Callable
from typing import Any

from .errors import RevisionError, RevisionRequestError

__all__ = [
    "REVISION_BAND",
    "CandidateModule",
    "candidate_module",
    "default_reviser",
    "revise_policy",
]

#: The jitter half-width the default reviser applies to each numeric literal —
#: a revised constant lands in ``value · [1 − REVISION_BAND, 1 + REVISION_BAND]``.
#:
#: A named default the dreaming loop's offline tuning replaces, exactly the way
#: feature 277's schedule states ``FULL_DREAMING_WORLDS`` and feature 227 states
#: ``_PATIENCE_FLOOR``: the band is a property of the sweep's exploration
#: strategy, not a law of the candidate value, so the cycle that runs the sweep
#: is the one that sets it.  Kept small and symmetric so a revision is a
#: perturbation of the incumbent rather than a rewrite — the multiple-testing
#: problem §12.1 names is a reason to keep the candidates close to ``π_t``.
REVISION_BAND: float = 0.1

#: The seed a caller that names none gets — a constant, so a sweep asked for
#: with no seed is reproducible, but a loop that runs more than one cycle must
#: pass a cycle-derived seed (the iteration id, the way feature 279 keys its
#: rotation) or every cycle would reproduce the previous one's candidates.
DEFAULT_SEED: int = 0

#: A reviser turns the incumbent and a revision index into a revised source.
#: The contract is narrow on purpose: ``(incumbent_source, revision_index,
#: seed) -> source``, so a deployment can substitute its own policy-development
#: strategy — a structural rewrite, a threshold re-derivation — without moving
#: anything :func:`revise_policy` guarantees about the candidate set it returns.
Reviser = Callable[[str, int, Any], str]


class CandidateModule:
    """One revised policy, as a value — feature 271's candidate module.

    Built only through :func:`candidate_module`, which computes its
    ``code_hash`` and defaults its ``module_id``; the class validates the five
    facts it is handed and nothing more.  Frozen with hand-written
    ``__slots__`` — the member's :class:`~dreaming.cycle.FreezeRecord` stance —
    so two callers holding one candidate cannot move each other's source, and a
    policy reading a candidate twice holds two equal frozen values rather than
    one that moved.  Its five fields are:

    * **``source``** — the revised policy's complete Python source, non-empty
      text.  It is the only thing that crosses the boundary to feature 272's
      replay and feature 230's gate; a blank or non-str source is refused.
    * **``code_hash``** — the sha256 hex of ``source``, computed by the factory,
      never handed in.  It is the candidate's identity: feature 274 persists it
      to ``policy_revision.code_hash`` (migration ``0109``), and
      :func:`revise_policy` deduplicates on it, so two revisions that jitter the
      incumbent into the same text are one candidate.
    * **``module_id``** — a version string derived from the code_hash (a
      ``cand-``-prefixed digest by default, or one the caller names), the
      spelling the loop hands to feature 274 as ``policy_revision.policy_version``.
    * **``parent_version``** — ``None`` for a root, the incumbent's version
      otherwise.  It is ``π^0 = π_t``'s own version, which is what lets feature
      273 add the incumbent back into the candidate set so the argmax never
      falls below the current policy.
    * **``revision_index``** — a genuine positive integer, ``1..M``.  A bool is
      not an index; the sweep's ordering is a fact about which of the ``M``
      revisions this is, and a malformed index would mislabel it.

    The value is validated at construction, the stance every value type in this
    member takes (:class:`~dreaming.cycle.FreezeRecord`,
    :class:`~dreaming.cap.CapRecord`, :class:`~scoring.AggregatedObjective`):
    the two text identities are non-empty, the parent version is None or a
    non-empty name, the index is a non-negative non-bool integer, and a refusal
    here is :class:`~dreaming.errors.RevisionRequestError`, the ask's own
    vocabulary.
    """

    __slots__ = ("code_hash", "module_id", "parent_version", "revision_index", "source")

    def __init__(
        self,
        *,
        source: str,
        code_hash: str,
        module_id: str,
        parent_version: str | None,
        revision_index: int,
    ) -> None:
        if not isinstance(source, str) or not source.strip():
            raise RevisionRequestError(
                f"a candidate module carries the revised policy source — got "
                f"{source!r} ({type(source).__name__}); the source is the only "
                "thing the replay engine and the admission gate read, and a "
                "value that is not non-empty text carries no policy to replay "
                "(feature 271)"
            )
        if not isinstance(code_hash, str) or not code_hash.strip():
            raise RevisionRequestError(
                f"a candidate module's identity is a code hash — got "
                f"{code_hash!r} ({type(code_hash).__name__}); feature 274 "
                "persists it to policy_revision.code_hash and revise_policy "
                "deduplicates on it, so a value that is not non-empty text "
                "names no candidate (feature 271)"
            )
        if not isinstance(module_id, str) or not module_id.strip():
            raise RevisionRequestError(
                f"a candidate module is addressed by a module id — got "
                f"{module_id!r} ({type(module_id).__name__}); it is the version "
                "string feature 274 writes as policy_revision.policy_version, "
                "and a value that is not non-empty text addresses no revision "
                "(feature 271)"
            )
        if parent_version is not None and (
            not isinstance(parent_version, str) or not parent_version.strip()
        ):
            raise RevisionRequestError(
                f"a candidate module's parent is None or a non-empty version — "
                f"got {parent_version!r} ({type(parent_version).__name__}); it "
                "is the incumbent feature 273 adds back to the candidate set, "
                "and a parent that cannot be named places the revision nowhere "
                "(feature 271)"
            )
        if isinstance(revision_index, bool) or not isinstance(revision_index, int):
            raise RevisionRequestError(
                f"a candidate module's revision index is a genuine integer — "
                f"got {revision_index!r} ({type(revision_index).__name__}); it "
                "is which of the M revisions this is, in order, and a bool or a "
                "non-integer would mislabel the sweep (feature 271)"
            )
        if revision_index < 1:
            raise RevisionRequestError(
                f"a candidate module's revision index is a positive integer — "
                f"got {revision_index}; the sweep is indexed 1..M, and an index "
                "below one names a revision the sweep does not run (feature 271)"
            )
        self.source = source
        self.code_hash = code_hash
        self.module_id = module_id
        self.parent_version = parent_version
        self.revision_index = revision_index

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CandidateModule):
            return NotImplemented
        return (
            self.source,
            self.code_hash,
            self.module_id,
            self.parent_version,
            self.revision_index,
        ) == (
            other.source,
            other.code_hash,
            other.module_id,
            other.parent_version,
            other.revision_index,
        )

    def __hash__(self) -> int:
        return hash(
            (
                self.source,
                self.code_hash,
                self.module_id,
                self.parent_version,
                self.revision_index,
            )
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"CandidateModule(module_id={self.module_id!r}, "
            f"revision_index={self.revision_index}, "
            f"parent_version={self.parent_version!r}, "
            f"code_hash={self.code_hash[:12]}…)"
        )


def _code_hash_of(source: str) -> str:
    """The sha256 hex identity of a policy source — the candidate's identity.

    The one spelling of a candidate's identity, shared by :func:`candidate_module`
    and :func:`revise_policy`'s deduplication so the two cannot disagree on what
    makes two revisions the same candidate — the failure a second spelling of
    the hash would invite, and the property feature 274 relies on when it writes
    ``code_hash`` back to ``policy_revision``.
    """
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def candidate_module(
    source: str,
    *,
    parent_version: str | None = None,
    revision_index: int = 1,
    module_id: str | None = None,
) -> CandidateModule:
    """Build one candidate module — the one spelling of a candidate.

    Takes the revised source, the incumbent it descends from and which revision
    of the sweep it is, computes the ``code_hash`` (never handed in — it is a
    fact about the source, and a caller that supplied one could lie about a
    candidate's identity), and defaults ``module_id`` to a ``cand-``-prefixed
    digest of that hash when the caller names none — the version string feature
    274 persists as ``policy_revision.policy_version``.  A caller-named
    ``module_id`` is honoured verbatim, so a deployment that addresses its
    revisions some other way reaches the same value.  Validation is the class's,
    so a blank source, a malformed id, a non-integer index or a parent that
    cannot be named is refused with :class:`~dreaming.errors.RevisionRequestError`,
    the ask's own vocabulary.  A non-str source is refused here, before
    :func:`_code_hash_of` hashes it — hashing is a fact about a source, and a
    value that is not text has no identity to compute, so the refusal is the
    ask's (RevisionRequestError) rather than an ``AttributeError`` from a hash
    that reached for ``.encode()``.
    """
    if not isinstance(source, str):
        raise RevisionRequestError(
            f"a candidate module carries the revised policy source — got "
            f"{source!r} ({type(source).__name__}); the source is the only "
            "thing the replay engine and the admission gate read, and a value "
            "that is not text carries no policy to hash or to replay (feature 271)"
        )
    code_hash = _code_hash_of(source)
    resolved_id = module_id if module_id is not None else f"cand-{code_hash[:32]}"
    return CandidateModule(
        source=source,
        code_hash=code_hash,
        module_id=resolved_id,
        parent_version=parent_version,
        revision_index=revision_index,
    )


def _jitter_factor(seed: Any, revision_index: int, lineno: int, col: int, band: float) -> float:
    """The deterministic bounded multiplier for one literal site.

    A pure function of ``(seed, revision_index, site)`` — the site being the
    literal's ``(lineno, col_offset)`` — derived via
    :func:`hashlib.sha256` rather than :mod:`random`, whose stream is not
    portable across processes: the same inputs answer the same factor in any
    process, which is docs §12's determinism contract read one literal down.
    The factor lands in ``[1 − band, 1 + band]``, symmetric about one, so a
    revision is a perturbation of the incumbent rather than a rewrite — the
    multiple-testing problem §12.1 names is a reason to keep the candidates
    close to ``π_t``.
    """
    material = f"{seed}\n{revision_index}\n{lineno}\n{col}\n".encode()
    span = (int(hashlib.sha256(material).hexdigest()[:8], 16) / 0xFFFFFFFF) * 2.0 - 1.0
    return 1.0 + span * band


class _JitterLiterals(ast.NodeTransformer):
    """Rewrite only the numeric-literal values of a parsed policy — nothing else.

    The whole of the default reviser's transform.  It visits each
    :class:`ast.Constant` and, for an ``int`` or ``float`` leaf, rescales its
    value by :func:`_jitter_factor`; every other node — identifiers, control
    flow, calls, imports, comparisons, string literals — is returned untouched,
    so ``ast.unparse`` of the result is the incumbent with its skeleton intact
    and only its magnitudes moved.  That is what "admissible by construction"
    rests on: feature 230's four anti-patterns and feature 231's learned
    component are all *structural* — an identifier, a string, a call, a
    terminating path — and this transformer alters a magnitude where none of
    them look.

    Two deliberate exceptions, both structural rather than magnitude:

    * a **bool** literal is left untouched, because a boolean is a branch, not a
      tunable magnitude — jittering ``True`` to ``1.0`` would be a rewrite of a
      control decision, exactly the kind of change the transform must not make;
    * a **zero** constant is jittered *additively* rather than multiplicatively,
      because any factor times zero is zero, and a zero threshold left at zero
      would be a constant the sweep never perturbed.
    """

    __slots__ = ("_band", "_index", "_seed")

    def __init__(self, seed: Any, revision_index: int, band: float) -> None:
        self._seed = seed
        self._index = revision_index
        self._band = band

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        value = node.value
        if isinstance(value, bool):
            return node
        if isinstance(value, (int, float)):
            lineno = getattr(node, "lineno", 0)
            col = getattr(node, "col_offset", 0)
            if value == 0:
                span = (
                    int(
                        hashlib.sha256(
                            f"{self._seed}\n{self._index}\n{lineno}\n{col}\n".encode()
                        ).hexdigest()[:8],
                        16,
                    )
                    / 0xFFFFFFFF
                ) * 2.0 - 1.0
                node.value = value + span * self._band
            else:
                node.value = value * _jitter_factor(
                    self._seed, self._index, lineno, col, self._band
                )
        return node


def default_reviser(incumbent_source: str, revision_index: int, seed: Any) -> str:
    """The default policy-development strategy — a seeded magnitude perturbation.

    The ``(incumbent_source, revision_index, seed) -> source`` transform
    :func:`revise_policy` runs when the caller names no ``reviser``: parse the
    incumbent, rescale each numeric literal by :func:`_jitter_factor`, and
    unparse.  It is the ``REVISION_BAND`` default the loop's offline tuning
    replaces, and it is admissible by construction for the reason
    :class:`_JitterLiterals` states — it moves magnitudes and leaves structure
    alone, so a candidate descended from an admitted incumbent carries none of
    feature 230's anti-patterns nor feature 231's learned component.

    A non-str or blank incumbent is refused with
    :class:`~dreaming.errors.RevisionRequestError` — the ask's own vocabulary,
    since a source that is not text carries no policy to revise — and an
    incumbent that does not parse is refused with
    :class:`~dreaming.errors.RevisionError`, because a source the transform
    cannot read is a production that cannot proceed.  A revised source always
    parses when the incumbent did, since the transform changes no structure; a
    *custom* reviser that returns unparseable text meets the same
    :class:`~dreaming.errors.RevisionError` at :func:`revise_policy`'s
    parse-check, which is the loop's verb over the produced source, not this
    module's to pre-refuse.
    """
    if not isinstance(incumbent_source, str) or not incumbent_source.strip():
        raise RevisionRequestError(
            f"the default reviser revises a policy source — got "
            f"{incumbent_source!r} ({type(incumbent_source).__name__}); the "
            "source is what the replay engine and the admission gate read, and "
            "a value that is not non-empty text carries no policy to revise "
            "(feature 271)"
        )
    try:
        tree = ast.parse(incumbent_source)
    except SyntaxError as refusal:
        raise RevisionError(
            f"the incumbent source does not parse, so the sweep has nothing to "
            f"revise: {refusal}. A revision is a transform of the incumbent's "
            "source, and a source that is not valid Python names no policy to "
            "perturb — the loop hands revise_policy a source feature 230 has "
            "already admitted, and this transform assumes it parses (feature 271)"
        ) from refusal
    return ast.unparse(_JitterLiterals(seed, revision_index, REVISION_BAND).visit(tree))


def _validated_source(value: Any) -> str:
    """A policy source is non-empty text, or the ask is refused.

    The ask's own face: a source that is not text, or is blank, carries no
    policy to revise, and the repair is to re-consider what was handed in —
    :class:`~dreaming.errors.RevisionRequestError`, never the production verdict
    :class:`~dreaming.errors.RevisionError`.  It does not parse here — whether
    the source is valid Python is the production's concern, and a source the
    transform cannot read is :func:`default_reviser`'s refusal, not this one's.
    """
    if not isinstance(value, str) or not value.strip():
        raise RevisionRequestError(
            f"revise_policy revises a policy source — got {value!r} "
            f"({type(value).__name__}); the source is the incumbent the loop "
            "holds and the only thing the candidates descend from, and a value "
            "that is not non-empty text is no policy at all (feature 271)"
        )
    return value


def _validated_count(value: Any) -> int:
    """A revision count is a genuine positive integer, or the ask is refused.

    The sweep is indexed ``1..count`` and produces one candidate per index, so
    the count must be a real integer of at least one: a bool (a branch, not a
    number), a float, a string or a value below one is refused with
    :class:`~dreaming.errors.RevisionRequestError`, naming what was wrong.  The
    count is **taken, not decided** — this module does not cap it (feature 276's
    ceiling refuses a too-wide sweep before the loop calls here) and does not
    read the pool to size it (feature 275's floor is checked before the sweep) —
    so the only thing validated is that the figure names a sweep at all.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise RevisionRequestError(
            f"a revision count is a genuine integer — got {value!r} "
            f"({type(value).__name__}); revise_policy produces one candidate per "
            "index 1..count, and a count that is not an integer names no sweep "
            "(feature 271)"
        )
    if value < 1:
        raise RevisionRequestError(
            f"a revision count is a positive integer — got {value}; the sweep "
            "runs 1..count and produces a candidate per index, and a count below "
            "one runs no revisions at all (feature 271)"
        )
    return value


def _validated_seed(value: Any) -> Any:
    """A seed is text or an integer — the draw's only input, validated.

    The seed fixes the deterministic jitter and nothing else; it is never stored
    and the same seed reproduces the same candidates.  It is accepted as text or
    an integer (an ``f``-string renders both to the same material, so ``42`` and
    ``"42"`` are the same seed), and refused with
    :class:`~dreaming.errors.RevisionRequestError` for anything else — a mapping,
    a float, an object whose ``str`` is a memory address — because a seed that
    cannot be rendered to stable text cannot reproduce across processes, which
    is the determinism docs §12 requires.
    """
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise RevisionRequestError(
            f"a revision seed is text or an integer — got {value!r} "
            f"({type(value).__name__}); the seed fixes the deterministic jitter "
            "and must render to stable text so the same seed reproduces the "
            "same candidates in any process (docs §12), and a value that does "
            "not names no reproducible sweep (feature 271)"
        )
    return value


def _validated_parent(value: Any) -> str | None:
    """The parent version is None or a non-empty name, or the ask is refused.

    ``None`` is the root — a revision with no recorded incumbent — and a
    non-empty string is the incumbent's version, which feature 273 adds back to
    the candidate set.  Anything else (a blank string, a number, an object whose
    ``str`` is a memory address) is refused with
    :class:`~dreaming.errors.RevisionRequestError`, because a parent that cannot
    be named places the revision's lineage nowhere (feature 271).
    """
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise RevisionRequestError(
            f"a revision's parent is None or a non-empty version — got "
            f"{value!r} ({type(value).__name__}); it is the incumbent feature "
            "273 adds back to the candidate set, and a parent that cannot be "
            "named places the revision's lineage nowhere (feature 271)"
        )
    return value


def revise_policy(
    incumbent_source: str,
    count: int,
    *,
    seed: Any = DEFAULT_SEED,
    incumbent_version: str | None = None,
    reviser: Reviser | None = None,
) -> tuple[CandidateModule, ...]:
    """Produce ``M`` revisions of the exploration policy source — feature 271's call.

    Takes the incumbent policy's authored source — the caller already holds it,
    the same source feature 230 admitted before the cycle opened — and the
    number of revisions to run, and answers ``count`` candidate modules, one per
    index ``1..count``, each a complete Python module the replay engine can
    import and replay (feature 272).  Each candidate records ``incumbent_version``
    as its ``parent_version`` (``π^0 = π_t``'s own version, so feature 273 can
    add the incumbent back and feature 274 can persist the argmax), and the whole
    production is deterministic in ``(source, count, seed)`` — the same inputs
    answer the same candidate modules to the last ``code_hash`` in any process,
    docs §12's determinism contract.

    The transform is the pluggable ``reviser`` — :func:`default_reviser`, the
    seeded magnitude perturbation, when none is given — run once per index.  The
    count is **taken, not decided**: this module produces one candidate per index
    and does not cap the count (feature 276's ceiling refuses a too-wide sweep
    *before* the loop calls here) nor read the pool to size it (feature 275's
    floor is the loop's precondition, checked before the sweep — a pool too thin
    to dream on is refused before :func:`revise_policy` is ever called).  It
    reads the source the caller holds and opens no database, reads no pool row,
    resolves no path and imports nothing that could — ``depends_on="270"`` is the
    loop-ordering fact (the sweep runs inside the outer iteration whose pool
    feature 270 holds fixed), not a code dependency, and this module imports
    nothing from :mod:`dreaming.cycle`.

    Refuses, in this order, each naming what it is about:

    1. an ``incumbent_source`` that is not non-empty text, a ``count`` that is
       not a genuine positive integer, a ``seed`` that is neither text nor an
       integer, or an ``incumbent_version`` that is not None or non-empty text —
       the ask's own facts, refused before anything is produced
       (:class:`~dreaming.errors.RevisionRequestError`);
    2. a revised source that does not parse — a *custom* reviser that returned
       garbage, since the default reviser changes no structure and always parses
       a valid incumbent — or fewer than ``count`` **distinct** candidates
       remaining after deduplication by ``code_hash`` — a policy whose authored
       numeric constants cannot fund ``count`` distinct perturbations names no
       sweep of that size (:class:`~dreaming.errors.RevisionError`).

    The second is a production verdict, not a malformed ask: the count was legal,
    and the repair is the developer's — grow the incumbent's authored constants,
    or shrink ``M`` — rather than a corrected re-ask.  A candidate that fails
    feature 230's admission gate is the loop's to discard, not this module's to
    pre-refuse: feature 271 produces candidates admissible by construction and
    feature 230 pronounces admissibility, two acts this module never joins.
    """
    source = _validated_source(incumbent_source)
    n = _validated_count(count)
    seed_value = _validated_seed(seed)
    parent = _validated_parent(incumbent_version)
    produce = reviser if reviser is not None else default_reviser

    candidates: list[CandidateModule] = []
    seen: set[str] = set()
    for index in range(1, n + 1):
        revised = produce(source, index, seed_value)
        try:
            ast.parse(revised)
        except SyntaxError as refusal:
            raise RevisionError(
                f"revision {index} produced a source that does not parse: "
                f"{refusal}. A revision is a transform of the incumbent's source, "
                "and a transform that yields invalid Python yields no policy to "
                "replay — the loop screens each candidate with feature 230's gate "
                "after this, but a source that does not parse is refused here, "
                "before a candidate is ever built from it (feature 271)"
            ) from refusal
        candidate = candidate_module(
            revised, parent_version=parent, revision_index=index
        )
        if candidate.code_hash in seen:
            continue
        seen.add(candidate.code_hash)
        candidates.append(candidate)

    if len(candidates) < n:
        raise RevisionError(
            f"revise_policy produced {len(candidates)} distinct candidate(s) but "
            f"was asked for {n}: after deduplicating by code_hash, the sweep is "
            f"short by {n - len(candidates)}. A policy whose authored numeric "
            "constants cannot fund that many distinct perturbations names no "
            "sweep of that size, and returning duplicates would collapse the "
            "argmax onto one source. Grow the incumbent's authored constants, or "
            "shrink M — the count was legal, and this is a production verdict, "
            "not a malformed ask (feature 271)"
        )
    return tuple(candidates)
