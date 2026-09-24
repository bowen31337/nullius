"""The incumbent, put back into the candidate set — feature 273.

app_spec.xml, *Dreaming Loop & Meta-Selection*, feature 273:

    System includes the incumbent policy in the candidate set, which returns a
    selected policy never worse on the fixed history.

docs/alpha-engine-prd.md §C5 states it as the qualifier on the whole dreaming
loop, and states the qualifier as deliberately as the guarantee:

    The paper's selection guarantee carries over unchanged: because the
    candidate set includes ``π^0 = π_t``, the selected policy is no worse than
    the current one *on the fixed replay history*.  Note the qualifier.  It is
    a guarantee about replay score, not about future P&L.

§12.1 leans on the same clause from the other side, as the reason a refused
winner is not a lost cycle — *"the paper's guarantee ``V^{m★} ≥ V^0`` holds on
the *fixed history*"* — and so do three of this feature's neighbours, which is
why this module exists rather than a paragraph somewhere else.
:mod:`dreaming.sweep` (feature 272) disclaims it in as many words: *"It is not
the production, the incumbent's return, the argmax or the bar. … putting
``π^0 = π_t`` back into the candidate set so the selection can never fall below
the current policy is feature 273's."*  :mod:`dreaming.select` (feature 274)
draws the boundary line by line: *"It is not feature 273 either: 273 puts the
incumbent back into the candidate set so the argmax never falls below the
current policy, and this module takes the argmax over whatever candidate set it
is handed — if the loop has run 273 first, the incumbent is one candidate among
the set."*  :mod:`dreaming.bar` (feature 280) grounds its entire refusal on the
clause — *"The repair is the incumbent, and that is what makes the refusal
safe.  The paper's guarantee ``V^{m★} ≥ V^0`` holds *by construction* once the
incumbent is in the candidate set (feature 273's sentence): when nothing clears
the bar, the incumbent *is* the argmax."*  And :mod:`dreaming.reviser`
(feature 271) completes the handshake: a candidate's ``parent_version`` is
``π_t``'s own version, *"which is what lets feature 273 add the incumbent back
into the candidate set"*.

What it is
----------

Two pure spellings in one module, beside feature 270's single ``"dreaming"``
component, the shape the floor, the cap, the ceiling, the split, the rotation,
the bar, the comparison, the transfer and the selector all take.  Neither
opens a database, reads a row, takes a path, consults the pool or touches the
loop's state: the incumbent is a policy the caller is holding, and the
candidate set is one it already has.

**The value —** :func:`incumbent_candidate(source, *, version=None,
parent_version=None)` answers ``π^0`` as a candidate-shaped entry: a frozen
:class:`IncumbentCandidate` carrying the incumbent's own ``source``, its
``code_hash`` and the ``module_id`` the loop knows it by.  It is built through
the member's **one spelling of a candidate's identity** —
:func:`dreaming.reviser._code_hash_of`, the sha256 feature 271's
``candidate_module`` and its deduplication share — imported rather than
respelled, for the reason that function's own docstring gives: *"the one
spelling of a candidate's identity, shared by :func:`candidate_module` and
:func:`revise_policy`'s deduplication so the two cannot disagree on what makes
two revisions the same candidate."*  A caller that names no ``version`` gets
the version the loop would have written for this source when it *was* a
candidate — ``cand-`` prefixed digest of the code hash, the very default
:func:`dreaming.reviser.candidate_module` derives — so a previous cycle's
``policy_revision.policy_version`` is reconstructible from the policy source
alone, and the member suite pins that agreement rather than trusting it.

**The act of including —** :func:`include_incumbent(candidates, source, *,
version=None, parent_version=None)` takes the candidate set feature 271
produced and answers the **widened** set, a tuple with ``π^0`` **first** and
the produced revisions in their own order after it.  First, because the
incumbent is the policy in force and appending it would make the loop's own
report read as though a revision had been added rather than the incumbent
restored; a tuple, because the answer is a value a caller can hold and compare
rather than a generator that pays again each time it is read.  It never
mutates its argument: the produced sequence is read, never consumed in place,
so a caller that still needs the ``M`` it produced holds them.

Why the entry carries no ``revision_index``
-------------------------------------------

:class:`IncumbentCandidate` carries four fields — ``source``, ``code_hash``,
``module_id``, ``parent_version`` — and **deliberately not** the
``revision_index`` feature 271's :class:`~dreaming.reviser.CandidateModule`
carries.  The absence is load-bearing rather than an omission, and feature
272's own candidate reader is where it is admitted: ``_candidate_of`` reads an
index as *"a genuine positive integer **or absent**"*, and its docstring names
this case exactly — *"273's incumbent — put back into the candidate set by a
sibling feature — may well arrive as a different class carrying the same
facts."*  The incumbent is not one of the ``M`` revisions the loop produced;
feature 271 refuses any index below one, so there is no honest index to give
it, and a fabricated ``1`` would mislabel the incumbent as one of the sweep's
own revisions in the plan :class:`~dreaming.sweep.SweepReport` orders.  This
module is a **value of its own** for the same reason: handing the incumbent in
as a :class:`~dreaming.reviser.CandidateModule` would mean inventing an index,
and a class that exists to carry an index cannot be the class for a policy that
has none.

The second clause is a theorem, and this module does not re-implement it
-----------------------------------------------------------------------

*"…which returns a selected policy never worse on the fixed history."*  With
``π^0`` in the set, feature 274's argmax is the maximum over a tournament one
of whose entrants is the current policy, so the selected policy's §7 objective
is **at least the incumbent's whenever a selection is returned at all** — and
every path that could return something lower is feature 274's own refusal (a
tie on the maximum, or a candidate the objectives do not cover).  That is
``V^{m★} ≥ V^0`` by construction, in §12.1's own words, and it is why feature
280 can say a refused winner is not a lost cycle.

Which is why **no function here compares the winner to the incumbent**.  Such
a check would be a second spelling of the argmax's own law, and it would need
the objective figures feature 274 already ranks and feature 280 already judges;
worse, it would be a *test* of a guarantee that holds *by construction*, and a
test that can fail is not the guarantee the paper states.  The one case where
a winner above the incumbent is still refused — §12.1's selection-noise bar —
is feature 280's refusal and not this one.  The theorem is stated here and
pinned in the member suite by running feature 274's real
:func:`~dreaming.select.select_argmax` over the widened set: the winner's score
is at least the incumbent's, over a pool a caller actually holds.

What is deliberately admitted, and what is refused
--------------------------------------------------

An **empty candidate set is admitted**: ``include_incumbent((), source)``
answers the one-member set ``(π^0,)``.  That is §C5's guarantee at its most
literal — the selected policy *is* the incumbent — and it is the very picture
§12.1 draws from the other side (*"when nothing clears the bar, the incumbent
is the argmax"*).  Feature 271 refuses a production shortfall, so an empty set
reaching here is a caller's own construction rather than a policy that could
not fund ``M``, and the whole of this feature is *adding one*; the admission is
the one feature 276's ceiling already states for a zero revision count — *"do
not run any revision is a caller's own business"* — applied one step earlier in
the same loop.

Everything else **refuses rather than silently defaulting**, each naming what
it is about: a source or a version that is not non-empty text; a candidate set
that is a bare string or bytes (Python would iterate its characters, and one
policy source would silently become one candidate per character) or is not
iterable at all; a candidate whose ``module_id`` or ``code_hash`` is not
non-empty text; and — the load-bearing one — an incumbent that is **already in
the set**, caught by its ``module_id`` or by its ``code_hash``, naming the
candidate that carries it.  That last refusal is what makes the sentence's verb
mean anything: *includes* is not *may include*.  A loop that ran this feature
twice has not enlarged its tournament, and a reviser that returned the
incumbent's source verbatim — which feature 271's deduplication cannot catch,
because it compares the revisions to *each other* and never to the incumbent
they descend from — would otherwise hand feature 274 an argmax over two
entrants that are one policy, or a guaranteed tie on the maximum.

One new class, and no code word
-------------------------------

One sibling under :class:`~dreaming.errors.DreamingError`:
:class:`~dreaming.errors.IncumbentRequestError`, the ask's own face.  It is its
own class rather than a face of feature 271's
:class:`~dreaming.errors.RevisionRequestError` (the repair here is *re-consider
the source and the version you handed the inclusion*, against *re-consider the
revision sweep you asked for*), rather than feature 276's
:class:`~dreaming.errors.RevisionCeilingError` (this module refuses no count),
and never feature 275's ``pool_too_thin`` or feature 270's ``pool_frozen``.
**No code word**: feature 275's ``pool_too_thin`` is mandated by its own
sentence, and feature 273's verb is *includes* and mandates none, so every
message opens with its subject — the stance
:class:`~dreaming.errors.CapRequestError`,
:class:`~dreaming.errors.RevisionCeilingError`,
:class:`~dreaming.errors.HoldoutRequestError` and
:class:`~dreaming.errors.TransferRequestError` state for their own pairs.

There is **no store face** either, and that is a fact about the sentence rather
than an unfinished half: *includes* has no store act.  The reading the
incumbent's own score would come from is feature 272's sweep over the widened
set, or a previous cycle's rows already in the pool under the incumbent's own
``policy_version`` — and because feature 270 holds the pool fixed for the
iteration, the two are the same reading.  Which of the two the loop takes is
the caller's fact; both are funded by the widened set this module answers.

No new component — feature 270's single ``"dreaming"`` component is the
member's whole composition, and both functions are reached the way the floor,
the cap, the ceiling, the split, the rotation, the bar, the comparison and the
transfer are: as free functions beside the store.  No seat edit, no table, no
migration.  Stdlib only and import-cheap — ``typing`` and the member's own
``.errors`` and ``.reviser`` (for the one shared hash) at module scope, nothing
else — so the factory's scan, which imports this package to fire its
``@register``, pays nothing for a feature it never composes.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .errors import IncumbentRequestError
from .reviser import _code_hash_of

__all__ = [
    "IncumbentCandidate",
    "include_incumbent",
    "incumbent_candidate",
]

#: How the derived version of an incumbent is spelled when the caller names
#: none — the ``cand-`` prefix and the leading 32 hex digits of the code hash,
#: which is **feature 271's own default** rather than a second one:
#: :func:`dreaming.reviser.candidate_module` derives
#: ``f"cand-{code_hash[:32]}"`` for a produced revision, and a shared default
#: is what makes an incumbent's version reconstructible from its source alone.
#: Spelled as a constant so the agreement is visible in one place, and pinned
#: by the member suite against the owner rather than trusted.
_DERIVED_VERSION_DIGEST = 32


class IncumbentCandidate:
    """The incumbent policy, as a candidate-shaped value — feature 273's entry.

    Built only through :func:`incumbent_candidate`, which computes its
    ``code_hash`` and defaults its ``module_id``; the class validates the four
    facts it is handed and nothing more.  Frozen with hand-written
    ``__slots__`` — the member's :class:`~dreaming.cycle.FreezeRecord` stance —
    so two callers holding one entry cannot move each other's source or
    identity, and a policy reading the widened candidate set twice holds two
    equal frozen values rather than one that moved.  Its four fields are:

    * **``source``** — the incumbent's complete Python source, non-empty text.
      It is the only thing that crosses the boundary to feature 272's replay
      and feature 230's gate, exactly as a revision's does.
    * **``code_hash``** — the sha256 hex of ``source``, computed by the factory
      through the member's one spelling of a candidate's identity
      (:func:`dreaming.reviser._code_hash_of`), never handed in.  It is the
      entry's identity: feature 274 persists it to
      ``policy_revision.code_hash``, and :func:`include_incumbent` refuses an
      incumbent whose hash a produced revision already carries.
    * **``module_id``** — a version string: one the caller names, or the one
      feature 271's ``candidate_module`` would have derived for this source.
      It is the spelling the loop hands to feature 274 as
      ``policy_revision.policy_version``, and what the argmax names its
      entrants by.
    * **``parent_version``** — ``None``, or the version the incumbent descends
      from.  ``None`` is the ordinary case: the incumbent is the policy in
      force, and this iteration's lineage starts at it rather than continuing
      through it.

    It carries **no ``revision_index``**, deliberately, and the class states
    why rather than leaving the absence to be inferred: the incumbent is not
    one of the ``M`` revisions feature 271 produced, and feature 272's own
    candidate reader admits *"a genuine positive integer or absent"* so that a
    sibling feature's incumbent can enter the sweep's plan without being
    mislabelled as one of its revisions.

    Duck-typed at every seam that reads it: feature 272 reads ``module_id``,
    ``code_hash`` and an absent ``revision_index``; feature 274 reads
    ``module_id`` in its argmax and ``code_hash`` with ``parent_version`` when
    it writes the winner.  The value is validated at construction, the stance
    every value type in this member takes, and a refusal here is
    :class:`~dreaming.errors.IncumbentRequestError` — the ask's own vocabulary,
    never feature 271's :class:`~dreaming.reviser.RevisionRequestError`: the
    *rule* that a candidate's source and identity are non-empty text is the
    member's one rule, and the *vocabulary* splits by who was asked.
    """

    __slots__ = ("code_hash", "module_id", "parent_version", "source")

    def __init__(
        self,
        *,
        source: str,
        code_hash: str,
        module_id: str,
        parent_version: str | None,
    ) -> None:
        if not isinstance(source, str) or not source.strip():
            raise IncumbentRequestError(
                f"the incumbent is included by its policy source — got "
                f"{source!r} ({type(source).__name__}); the source is the only "
                "thing the replay engine and the admission gate read, and a "
                "value that is not non-empty text carries no policy to put back "
                "into the candidate set (feature 273)"
            )
        if not isinstance(code_hash, str) or not code_hash.strip():
            raise IncumbentRequestError(
                f"an incumbent candidate's identity is a code hash — got "
                f"{code_hash!r} ({type(code_hash).__name__}); feature 274 "
                "persists it to policy_revision.code_hash and feature 272 files "
                "one pair's evidence under it, so a value that is not non-empty "
                "text names no incumbent (feature 273)"
            )
        if not isinstance(module_id, str) or not module_id.strip():
            raise IncumbentRequestError(
                f"an incumbent candidate is addressed by a module id — got "
                f"{module_id!r} ({type(module_id).__name__}); it is the version "
                "string feature 274 writes as policy_revision.policy_version "
                "and how the enlarged tournament names one of its entrants, and "
                "a value that is not non-empty text addresses no incumbent "
                "(feature 273)"
            )
        if parent_version is not None and (
            not isinstance(parent_version, str) or not parent_version.strip()
        ):
            raise IncumbentRequestError(
                f"an incumbent candidate's parent is None or a non-empty "
                f"version — got {parent_version!r} "
                f"({type(parent_version).__name__}); None is the ordinary case, "
                "because this iteration's lineage starts at the incumbent "
                "rather than continuing through it, and a parent that cannot be "
                "named places the incumbent nowhere (feature 273)"
            )
        self.source = source
        self.code_hash = code_hash
        self.module_id = module_id
        self.parent_version = parent_version

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, IncumbentCandidate):
            return NotImplemented
        return (
            self.source,
            self.code_hash,
            self.module_id,
            self.parent_version,
        ) == (
            other.source,
            other.code_hash,
            other.module_id,
            other.parent_version,
        )

    def __hash__(self) -> int:
        return hash((self.source, self.code_hash, self.module_id, self.parent_version))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"IncumbentCandidate(module_id={self.module_id!r}, "
            f"parent_version={self.parent_version!r}, "
            f"code_hash={self.code_hash[:12]}…)"
        )


def _validated_source(value: Any) -> str:
    """A policy source is non-empty text, or the ask is refused.

    The incumbent's source is the policy in force — the ``π_t`` of §C5's
    ``π^0 = π_t`` — so a value that is not non-empty text names no policy to
    put back into the candidate set.  The refusal is
    :class:`~dreaming.errors.IncumbentRequestError`, this feature's own
    vocabulary, rather than feature 271's ``RevisionRequestError``: a caller
    that included an incumbent must not meet the *reviser's* word for an act
    that revised nothing, the seam discipline the workspace states for error
    vocabularies and :mod:`dreaming.ceiling` applies to its own figures.  A
    non-str source is refused here, before :func:`_code_hash_of` reaches for
    ``.encode()`` — hashing is a fact about a source, and a value that is not
    text has no identity to compute.
    """
    if not isinstance(value, str) or not value.strip():
        raise IncumbentRequestError(
            f"the incumbent is included by its non-empty policy source — got "
            f"{value!r} ({type(value).__name__}); §C5's ``π^0 = π_t`` is the "
            "policy the loop is currently running, and a value that is not "
            "non-empty text puts no such policy back into the candidate set "
            "(feature 273)"
        )
    return value


def _validated_version(value: Any) -> str | None:
    """A named version is ``None`` or non-empty text, or the ask is refused.

    ``None`` means *derive it* — the version feature 271's
    :func:`~dreaming.reviser.candidate_module` would have written for this
    source — and a non-empty string is the version the loop already knows the
    incumbent by.  Anything else (a blank string, a number, an object whose
    ``str`` is a memory address) is refused, because a version that cannot be
    named is the string feature 274 writes as
    ``policy_revision.policy_version`` and addresses no policy at all.
    """
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise IncumbentRequestError(
            f"the incumbent's version is None or a non-empty name — got "
            f"{value!r} ({type(value).__name__}); None derives the version "
            "feature 271's candidate_module would have written for this source, "
            "and a name that is not non-empty text is the string feature 274 "
            "persists as policy_revision.policy_version (feature 273)"
        )
    return value


def _validated_parent(value: Any) -> str | None:
    """A parent is ``None`` or non-empty text, or the ask is refused.

    ``None`` is the ordinary case and not a degenerate one: this iteration's
    lineage starts at the incumbent — the revisions feature 271 produced carry
    *its* version as their ``parent_version`` — so an incumbent descending from
    a further policy is the exception a deployment may record and not the rule.
    A blank string, a number or an object whose ``str`` is a memory address is
    refused, because a parent that cannot be named places the incumbent's
    lineage nowhere.
    """
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise IncumbentRequestError(
            f"the incumbent's parent is None or a non-empty version — got "
            f"{value!r} ({type(value).__name__}); None is the ordinary case, "
            "because the M revisions feature 271 produces descend from the "
            "incumbent rather than the incumbent descending from them, and a "
            "parent that cannot be named places the incumbent's lineage nowhere "
            "(feature 273)"
        )
    return value


def _candidates_of(value: Any) -> tuple[Any, ...]:
    """Read the produced candidate set, or refuse the ask in this module's word.

    A sequence of candidate modules — the value feature 271 produces — read
    duck-typed by ``module_id`` and ``code_hash``, the two facts
    :func:`include_incumbent` must inspect to know whether the incumbent is
    already among them.  It is a *read*, not a re-validation of feature 272's
    or feature 274's laws: an index is not looked at, a candidate's source is
    not read, and nothing about coverage or plurality is judged here.

    A bare string is refused where many candidates belong, and the refusal is
    explicit rather than incidental: Python would iterate a policy source's
    characters, and one candidate module would silently become one candidate
    per character — a tournament nobody produced, over revisions whose
    identities are single letters.  An **empty** set is admitted; it is the
    caller's own construction, and the widened set is then §C5's guarantee at
    its most literal.
    """
    if isinstance(value, (str, bytes)):
        raise IncumbentRequestError(
            f"the incumbent is included beside the candidate set feature 271 "
            f"produced — a sequence of candidate modules — got the single "
            f"{type(value).__name__} {value!r}; iterating a bare policy source "
            "would make one candidate module per character, and the enlarged "
            "set would be a tournament nobody produced (feature 273)"
        )
    if not isinstance(value, Iterable):
        raise IncumbentRequestError(
            f"the incumbent is included beside the candidate set feature 271 "
            f"produced — a sequence of candidate modules — got {value!r} "
            f"({type(value).__name__}); a value that is not a sequence of "
            "candidates names no tournament for the incumbent to enter "
            "(feature 273)"
        )
    ordered = tuple(value)
    for candidate in ordered:
        module_id = getattr(candidate, "module_id", None)
        if (
            isinstance(module_id, bool)
            or not isinstance(module_id, str)
            or not module_id.strip()
        ):
            raise IncumbentRequestError(
                f"a candidate in the set the incumbent joins is addressed by "
                f"its ``module_id`` — got {module_id!r} "
                f"({type(module_id).__name__}) on {candidate!r}; it is the "
                "version feature 274 writes as policy_revision.policy_version "
                "and how the enlarged tournament names its entrants, and a "
                "candidate that cannot be named is one the incumbent's "
                "inclusion cannot be told apart from (feature 273)"
            )
        code_hash = getattr(candidate, "code_hash", None)
        if (
            isinstance(code_hash, bool)
            or not isinstance(code_hash, str)
            or not code_hash.strip()
        ):
            raise IncumbentRequestError(
                f"a candidate in the set the incumbent joins carries a "
                f"``code_hash`` — got {code_hash!r} "
                f"({type(code_hash).__name__}) on {candidate!r}; feature 272 "
                "files one pair's evidence under it and feature 274 persists it "
                "to policy_revision.code_hash, and a candidate whose identity "
                "cannot be read is one the incumbent's inclusion cannot be "
                "checked against (feature 273)"
            )
    return ordered


def incumbent_candidate(
    source: Any,
    *,
    version: Any = None,
    parent_version: Any = None,
) -> IncumbentCandidate:
    """``π^0 = π_t`` as a candidate-shaped entry — feature 273's value.

    The incumbent policy's own source in, and the entry feature 272's sweep and
    feature 274's argmax read a candidate by, out.  Pure: no store, no clock,
    no environment, no ``@register`` component — the shape
    :func:`dreaming.ladder.rejects_thin_pool`, feature 276's ceiling, feature
    278's split, feature 279's rotation and feature 274's argmax take, and a
    caller that only wants *the incumbent as an entrant* asks this and pays for
    nothing.

    The ``code_hash`` is computed here, never handed in, and computed through
    the member's **one spelling of a candidate's identity** —
    :func:`dreaming.reviser._code_hash_of`, the sha256 feature 271's
    ``candidate_module`` and its deduplication share.  A second ``hashlib``
    call here would be a second spelling of what makes two candidates the same,
    which is the failure that function's docstring names, and it is the reason
    the import is a private one: feature 271's ``__all__`` carries the public
    vocabulary, and the hash is shared inside the member the way
    :mod:`dreaming.cap` shares :mod:`dreaming.cycle`'s ``_parsed_instant`` and
    ``_stamp``.

    ``version`` is the module id the loop already knows the incumbent by — a
    previous cycle's ``policy_revision.policy_version`` — and it defaults to
    ``None``, which **derives** the version feature 271's
    :func:`~dreaming.reviser.candidate_module` would have written for this very
    source (``cand-`` prefixed digest of the code hash).  The default is not a
    convenience: a candidate's ``module_id`` is a function of its source, so a
    caller holding only the policy source still addresses the policy the pool's
    rows are keyed by, and the member suite pins this derivation against its
    owner so the two cannot drift.

    ``parent_version`` is ``None`` in the ordinary case, and that is worth
    stating rather than assuming: the ``M`` revisions feature 271 produces
    carry the **incumbent's** version as their ``parent_version``, so the
    lineage of an iteration begins at the incumbent.  A deployment that records
    the incumbent descending from a further policy passes it; a blank name is
    refused, because a parent that cannot be named places the lineage nowhere.

    Refuses, in this order, each naming what it is about
    (:class:`~dreaming.errors.IncumbentRequestError` throughout, because every
    one is a fact about the **ask** and nothing has been read): a ``source``
    that is not non-empty text; a ``version`` that is not ``None`` or non-empty
    text; a ``parent_version`` that is not ``None`` or non-empty text.
    """
    policy_source = _validated_source(source)
    named_version = _validated_version(version)
    parent = _validated_parent(parent_version)
    code_hash = _code_hash_of(policy_source)
    module_id = (
        named_version
        if named_version is not None
        else f"cand-{code_hash[:_DERIVED_VERSION_DIGEST]}"
    )
    return IncumbentCandidate(
        source=policy_source,
        code_hash=code_hash,
        module_id=module_id,
        parent_version=parent,
    )


def include_incumbent(
    candidates: Any,
    source: Any,
    *,
    version: Any = None,
    parent_version: Any = None,
) -> tuple[Any, ...]:
    """Put ``π^0`` back into the candidate set — feature 273's act of including.

    The candidate set feature 271 produced and the incumbent's source in, and
    the **widened** set out: a tuple carrying the incumbent **first** and the
    produced revisions in their own order after it.  Pure — no store, no clock,
    no environment, no ``@register`` component — and it never mutates its
    argument: the produced sequence is read, never consumed in place, so a
    caller that still needs the ``M`` it produced holds them.

    **First, and not appended.**  The incumbent is the policy in force; it is
    ``π^0`` in §C5's ``π^0 = π_t``, the set's opening member by the numbering
    the paper gives it, and appending it would make a loop's own report read as
    though a revision had been added rather than the incumbent restored.  A
    tuple, and not a generator, because the widened set is a value the loop
    hands on — to feature 272's ``plan_sweep``, to feature 274's
    ``select_argmax`` — and a generator that answered a different object each
    time it was read would make *the same set* a claim nobody could check.

    **The second clause of the sentence is a theorem this function makes
    true, not a check it performs.**  With ``π^0`` among the entrants, feature
    274's argmax is the maximum over a tournament containing the policy in
    force, so the selected policy's §7 objective is at least the incumbent's
    whenever a selection is returned at all; every path that could answer
    something lower is feature 274's refusal (a tie on the maximum, or a
    candidate the objectives do not cover).  That is ``V^{m★} ≥ V^0`` by
    construction — *"on the fixed history"*, and §C5's qualifier is not
    softened here: the guarantee is about replay score and never about forward
    P&L.  The one case where a winner that *is* above the incumbent is still
    refused is §12.1's selection-noise bar, which is feature 280's verdict and
    not this module's.

    Refuses, in this order, each naming what it is about
    (:class:`~dreaming.errors.IncumbentRequestError` throughout, because every
    one is a fact about the **ask**): a ``candidates`` that is a bare string or
    bytes, or is not iterable at all; a candidate in the set whose
    ``module_id`` or ``code_hash`` is not non-empty text; a ``source``,
    ``version`` or ``parent_version`` the entry cannot be built from; and an
    incumbent that is **already in the set** — matched by its ``module_id``, or
    by its ``code_hash`` — naming the candidate that carries it.

    The set is read before the entry is built, and that order is the member's
    own: :func:`dreaming.sweep.plan_sweep` and
    :func:`dreaming.select.commit_selection` both validate the candidate set
    first, because the set is the tournament every other figure is read
    against and a malformed one is refused before any other fact is judged.

    That last refusal is the one the sentence turns on.  *Includes* is not *may
    include*: a loop that ran this feature twice has not enlarged its
    tournament, and a reviser that returned the incumbent's source verbatim —
    which feature 271's deduplication cannot catch, because it compares the
    revisions to *each other* and never to the incumbent they descend from —
    would otherwise hand feature 274 an argmax over two entrants that are one
    policy, or a guaranteed tie on the maximum.  The two matches are checked
    separately so the refusal can say *which* identity gave it away, because
    the repairs differ: a version collision is a loop that ran the inclusion
    twice, and a hash collision is a production that did not revise anything.

    An **empty** candidate set is **admitted**: an empty sequence answers the
    one-member set ``(π^0,)``, which is §C5's guarantee at its most literal
    (the selected policy *is* the incumbent) and exactly what §12.1's *"when
    nothing clears the bar, the incumbent is the argmax"* describes from the
    other side.  Feature 274 takes
    the argmax over one candidate without a tie, so the answer is a set a
    selection can be taken over.
    """
    produced = _candidates_of(candidates)
    incumbent = incumbent_candidate(
        source, version=version, parent_version=parent_version
    )
    for candidate in produced:
        if getattr(candidate, "module_id", None) == incumbent.module_id:
            raise IncumbentRequestError(
                f"the incumbent is included in the candidate set — but "
                f"{incumbent.module_id!r} is already one of its members. "
                "*Includes* is not *may include*: the loop has run this "
                "feature's act twice, or handed in a set that already carries "
                "the policy in force, and enlarging it again would give §C5's "
                "argmax two entrants under one version — a tournament that "
                "looks larger and selects nothing new (feature 273)"
            )
        if getattr(candidate, "code_hash", None) == incumbent.code_hash:
            raise IncumbentRequestError(
                f"the incumbent is included in the candidate set — but its "
                f"policy source is already carried by the candidate "
                f"{getattr(candidate, 'module_id', candidate)!r} (code hash "
                f"{incumbent.code_hash[:12]}…). Feature 271's deduplication "
                "compares the revisions to each other and never to the "
                "incumbent they descend from, so a production that returned a "
                "source byte-identical to the incumbent is caught here or "
                "nowhere: including it would make the argmax a tie over two "
                "entrants that are one policy (feature 273)"
            )
    return (incumbent, *produced)
