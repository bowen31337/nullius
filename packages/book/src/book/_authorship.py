"""The authorship guard — feature 306: human-authored, version-controlled.

app_spec.xml, "Portfolio Book Construction", feature 306: *System keeps book
construction human-authored and version-controlled, which rejects any
agent-authored modification to it.*  docs/alpha-engine-prd.md states the rule
twice, and both statements are this module's terms.  §C8 — the section this
whole category implements — closes with it:

    Signal book → IR-weighted combination with shrinkage → volatility
    targeting → position and concentration limits → orders.
    Version-controlled, human-authored, explicitly outside the search space.
    Changing it is a human decision with a changelog entry, not a discovery.

And §2.2's first non-goal says it from the other side: *"Not a strategy
optimizer.  Entries, exits, sizing, and portfolio construction are fixed,
hand-built, version-controlled, and explicitly **outside** the search
space."*

**Why the boundary needs a guard at all.**  This system already contains a
lawful automated author.  The dreaming reviser revises *policy* source
(feature 271), and the sweep commits its selections to ``policy_revision``
(feature 274) — that is the discovery loop working as designed, and it is
the loop this repository exists to run.  The one thing that machinery may
never touch is the construction that weights what it finds: a search
allowed to improve its own weighting function has stopped being measured by
it, which is §C8's *"explicitly outside the search space"* and NG1's *"not
a strategy optimizer"* said as a refusal.  So the boundary is not a
comment in a document — it is this module, and a modification to the
construction is admitted only when a human authored it under version
control.

This module applies §C8's line in three spellings of one act:

* :class:`BookConstructionChange` — the modification as its carrier states
  it: a frozen record of exactly four fields (the subject, the author, the
  author kind, the commit).  The record is the sentence's
  *version-controlled* half made structural — construction refuses a
  revision that is not the full commit id, so **a change that names no
  commit cannot be stated at all**;
* :func:`is_agent_authored` — the read-only spelling: the fact without the
  refusal, the shape :func:`dreaming.bar.selection_bar` takes for its own
  figure (validate the ask, answer a fact);
* :func:`rejects_agent_authored_modification` — the **rejects** of the
  sentence, the verdict shape the workspace's other refusals-of-a-fact take
  (:func:`dreaming.ceiling.rejects_uncapped_sweep`, feature 308's
  :func:`book.rejects_overleveraged_target`): it **raises** when the
  change's author kind is not the human one, so a caller that routes
  construction changes through it on the write path is stopped before an
  agent's edit lands.

**The authorship is judged on a closed vocabulary, and the vocabulary is a
prohibition rather than an allowlist.**  :data:`HUMAN_AUTHOR_KIND` is the
one admitted kind; :data:`AGENT_AUTHOR_KINDS` is the declared set of this
system's own automated authors, each name greppable to where the system
itself mints it — ``agent`` (the phrase
``policy_runtime`` uses for the authoring process), ``discovery``
(§C8: *"not a discovery"*), ``dreaming`` (the reviser that authors code
revisions), ``optimizer`` (NG1: *"Not a strategy optimizer"*), ``worker``
(the batch pool that writes on the loop's behalf); and
:data:`AUTHOR_KINDS` is their union with the human one.  A kind not in the
vocabulary — a near-miss like ``"Human"`` or a novel one like
``"ci-bot"`` — is refused **at the ask**, as the change record's own fact,
for feature 241's reason: a near-miss is refused rather than mapped, so a
caller that misnames its author is told *what to fix* rather than told its
change was refused as an agent's.  And the judgment refuses every declared
agent kind, so nothing outside the one human kind is admitted by any
route — declared, near-missed or novel.  That fail-closed property is the
sentence's own word, *any*, and it is the shape features 246/247 state for
their dependency wall: a prohibition, not an allowlist.

**The kinds are a constant, not a knob.**  No verb below accepts an
``admitted_kinds=`` parameter, an ``allow=`` parameter, or any other
spelling of the question *which authors may edit the construction?* — for
the same reason feature 301's weighting and feature 308's quarter are
constants: a deployment that could widen the admitted set could opt an
agent in, and a guard whose boundary its caller could move is not one.
Widening the vocabulary is a change to this module — which is to say, a
human decision with a changelog entry, which is the very act this module
exists to describe.

**The version-controlled half is the commit, and the commit is spelled
one way.**  A revision is the full commit id —
:data:`REVISION_HEX_LENGTH` lowercase hexadecimal characters, the
spelling ``git rev-parse HEAD`` answers in this repository — and anything
else names no version-controlled state: a branch, a tag or ``HEAD`` is a
*mutable pointer* (the canary lockfile refuses versions and tags for
exactly this reason — a pointer can be moved to different bytes while
keeping its name), a short id is an *ambiguous* one, and an absent
revision is a working-tree edit, which is precisely the un-versioned
thing this feature exists to refuse.  The record carries no clock of its
own for the same reason: the commit a change names *is* its timestamp,
and a record that re-derived time beside it would state a fact version
control already holds better.

**The ask settles before the judgment.**  The four fields are validated
in declaration order — subject, author, author kind, revision — as
:class:`~book.errors.BookChangeRequestError`, and only a wholly
well-stated change is judged.  So an agent-authored change with a broken
revision meets the ask's class first and is told *name the commit*, not
*an agent authored this*; and a human-authored change that names its
commit runs, which is §C8's admitted path — changing the construction is
a human decision, and this module is where that decision is seen to be
one.

**Two refusal classes, because the repairs differ.**  The ask's own facts
— a field that cannot be part of a stated change — are refused with
:class:`~book.errors.BookChangeRequestError` and carry no code, for the
reason :class:`~book.errors.LeverageRequestError` gives: a malformed ask
names its subject in its first words.  The one judgment the sentence
mints — a well-stated change authored by an agent — is refused with
:class:`~book.errors.AgentAuthoredModificationError`, opening with
:data:`AGENT_MODIFICATION_CODE` and naming the subject, the author, the
kind and the revision.  Both are subclasses of feature 301's
:class:`~book.errors.BookConstructionError`, so the caller that already
refuses the whole book surface with a single ``except`` goes on doing
exactly that, and a caller that must react differently to *the search
reached for the construction* and *your change named no commit* can still
tell them apart — an agent-authored change is refusable though perfectly
well stated, and a mis-stated change is refusable though a human wrote
it, so the two facts are genuinely different.

**What this module does not do.**  It validates no changelog entry — that
is feature 307's sentence, and it builds on exactly this record.  It
judges no content — the policy admission gates (features 230/231) judge a
*policy's* source, and what a construction change *says* is none of this
module's business; authorship and version control are.  It installs no
filesystem hook and sweeps no state — the canary lockfile states the pair
(a guard seam plus a nightly sweep) and this feature's sentence mints
only the guard: the deployment's wiring delivers construction changes
through the verdict the way ``policy_runtime``'s commit verb is wired,
and a change that bypasses the seam is a wiring bug, not a fact this
module could have measured from inside itself.  It opens no database,
reads no environment and consults no clock.

**No new component, and the layering note.**  The guard is a free
function beside the combiner, the way feature 308's cap sits and feature
276's ceiling sits beside feature 270's freeze: its whole input is the
record the caller already holds, so there is nothing for the factory to
compose and nothing for a deployment to configure.  No ``@register``, no
table, no endpoint, no migration, no seat edit, and no third-party
import — ``dataclasses``, ``typing`` and the member's own ``.errors`` —
so the factory's scan, which imports this package on every
``create_app()`` to fire its ``@register``, pays nothing for the guard
beyond the import it already paid for the combiner.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .errors import AgentAuthoredModificationError, BookChangeRequestError

__all__ = [
    "AGENT_AUTHOR_KINDS",
    "AGENT_MODIFICATION_CODE",
    "AUTHOR_KINDS",
    "HUMAN_AUTHOR_KIND",
    "REVISION_HEX_LENGTH",
    "BookConstructionChange",
    "is_agent_authored",
    "rejects_agent_authored_modification",
]

#: The one author kind admitted onto the construction's change path —
#: §C8's *"human-authored"*.  Spelled as a constant because it is the whole
#: boundary: :func:`rejects_agent_authored_modification` admits exactly this
#: kind and refuses every other, declared or not, so the word is the guard.
#: Not a parameter of any verb — a deployment that could widen the admitted
#: set could opt an agent in, and a guard whose boundary its caller could
#: move is not one (feature 301's stance on the weighting, feature 308's on
#: the quarter, and this module's on the author).
HUMAN_AUTHOR_KIND = "human"

#: The declared set of this system's own automated authors — the kinds a
#: change record may honestly carry when no human made it.  Each name is
#: greppable to where the system itself mints it: ``agent`` is the phrase
#: the policy-runtime member uses for the authoring process, ``discovery``
#: is §C8's own word (*"not a discovery"*), ``dreaming`` is the reviser
#: that lawfully revises policy source (the exact mechanism that would
#: otherwise reach for the construction), ``optimizer`` is §2.2 NG1's
#: (*"Not a strategy optimizer"*), and ``worker`` is the batch pool that
#: writes on the loop's behalf.  A closed set for feature 241's reason —
#: near-misses are refused at the ask rather than mapped — and a refusal
#: set for the sentence's reason: every one of them is judged
#: agent-authored, whatever it promises.
AGENT_AUTHOR_KINDS = frozenset(
    {"agent", "discovery", "dreaming", "optimizer", "worker"}
)

#: The whole authorship vocabulary — the human one plus the declared agent
#: kinds, and nothing else.  A change record's ``author_kind`` must be one
#: of these to be *stated*; which side of the boundary it lands on is then
#: the one comparison :func:`is_agent_authored` and
#: :func:`rejects_agent_authored_modification` spell.
AUTHOR_KINDS = frozenset({HUMAN_AUTHOR_KIND}) | AGENT_AUTHOR_KINDS

#: The length of a revision — the full commit id, the spelling
#: ``git rev-parse HEAD`` answers in this repository.  One spelling, so a
#: revision a caller hands this guard and one a deployment's log reads agree
#: on every character; the canary lockfile pins its digests to one spelling
#: for the same reason.
REVISION_HEX_LENGTH = 40

#: The code an *agent-authored* refusal opens with — a change to the book
#: construction was authored by an automated author — so the rejection is
#: greppable by the word that names it.  Feature 306's sentence mandates no
#: token (it names its subject in prose), so the code is this module's own,
#: minted on the ``pool_too_thin`` / ``leverage_above_quarter_kelly``
#: convention the workspace states for the one refusal an operator greps a
#: deployment log for: *why was this change refused?*  The ask's own facts
#: carry no code, for the reason
#: :class:`~book.errors.BookChangeRequestError` gives — a malformed change
#: names its subject in its first words, and a token there would hand a
#: reader a developer's word for a fact they can simply fix.
AGENT_MODIFICATION_CODE = "agent_authored_modification"

#: The hexadecimal alphabet a revision is spelled over — lowercase, like
#: every digest spelling in this workspace (the canary lockfile's
#: ``sha256:<64 lowercase hex>``, the reviser's ``code_hash``).
_HEX = frozenset("0123456789abcdef")

#: Sentinel for "attribute not present" when reading a change's surface, so
#: a record that omits ``author_kind`` entirely is distinguished from one
#: present-and-``None`` — a change that carries no author kind is an
#: unstatable ask, not a change that declared itself authorless.  The
#: combiner's own ``_MISSING`` discipline, read on this feature's surface.
_MISSING = object()


def _validated_subject(value: Any) -> str:
    """Check that ``value`` names the construction asset being changed.

    The subject is the *what* of the change — the information-ratio
    weighting, the shrinkage, the volatility target, the leverage cap — a
    free name, because the sentence guards the construction whole and no
    module of this member owns a closed list of its assets.  A non-empty
    string is all the guard needs: the subject is what the refusal names so
    the operator can see *what the search reached for*, and a change that
    names no subject guards nothing.  Stripped and stored stripped, so the
    refusal and the record's equality read one spelling of the name.
    """
    if not isinstance(value, str) or not value.strip():
        raise BookChangeRequestError(
            f"a book construction change names its subject — got {value!r} "
            f"({type(value).__name__}); the subject is the construction "
            "asset being changed (the information-ratio weighting, the "
            "shrinkage, the volatility target, the leverage cap), and a "
            "change that names no subject guards nothing"
        )
    return value.strip()


def _validated_author(value: Any) -> str:
    """Check that ``value`` names who authored the change.

    The author is the *who* the whole guard judges, and it is a free name
    for the same reason the subject is: the boundary runs between humans
    and the system's automated authors, and it is the *kind* that states
    which side of it the author stands on — this field carries the name a
    refusal can say aloud.  A non-empty string, stripped and stored
    stripped; the judgment names it, the ask refuses its absence.
    """
    if not isinstance(value, str) or not value.strip():
        raise BookChangeRequestError(
            f"a book construction change names its author — got {value!r} "
            f"({type(value).__name__}); authorship is the whole fact this "
            "guard judges (docs/alpha-engine-prd.md §C8: \"Version-"
            "controlled, human-authored, explicitly outside the search "
            "space\"), and a change that states no author cannot be judged "
            "human- or agent-authored"
        )
    return value.strip()


def _validated_kind(value: Any) -> str:
    """Check that ``value`` is one of the declared authorship vocabulary.

    The closed vocabulary is feature 241's stance read on authorship: a
    near-miss is refused rather than mapped, so ``"Human"``, ``"human "``
    and ``"HUMAN"`` are refused *here, at the ask* — a caller that misnames
    its author is told what to fix — while a declared agent kind passes the
    ask and meets the judgment, and an unknown kind like ``"ci-bot"`` is
    refused at the ask too.  Either way nothing outside
    :data:`HUMAN_AUTHOR_KIND` is admitted, which is the sentence's *any*
    made structural: fail closed on every route, known or novel.  The
    spelling is exact (no case-folding, no stripping) because the
    vocabulary is a law, not a guess at what was meant.
    """
    if not isinstance(value, str) or value not in AUTHOR_KINDS:
        raise BookChangeRequestError(
            f"an author_kind is one of the declared vocabulary "
            f"{sorted(AUTHOR_KINDS)} — got {value!r} "
            f"({type(value).__name__}); the vocabulary is closed "
            "(docs/alpha-engine-prd.md §C8 keeps the book construction "
            "\"human-authored ... explicitly outside the search space\", "
            "so one kind names the human who may change it and the others "
            "name this system's own automated authors). An unknown or "
            "mis-spelled kind is refused here, at the ask, rather than "
            "judged agent-authored — fix the spelling; the judgment is "
            "reserved for a change that states its author honestly"
        )
    return value


def _validated_revision(value: Any) -> str:
    """Check that ``value`` is the commit the change arrives under.

    The revision is the sentence's *version-controlled* half, and a commit
    id is the one spelling that names a version-controlled state —
    :data:`REVISION_HEX_LENGTH` lowercase hexadecimal characters, what
    ``git rev-parse HEAD`` answers in this repository.  Everything else a
    caller might hand is refused, each for its own reason:

    * a branch, a tag or ``HEAD`` is a **mutable pointer** — it can be
      moved to different bytes while keeping its name, which is the canary
      lockfile's own reason for refusing versions and tags as lock
      entries;
    * a short id is an **ambiguous** one — unique in a small repository,
      and a promise nothing keeps once the repository grows;
    * an uppercase spelling is a near-miss of the one spelling, refused
      rather than folded (the vocabulary's own stance, applied to the
      commit);
    * an absent revision — ``None``, empty, or a working-tree marker like
      ``"dirty"`` — names no state at all: it is an un-committed edit,
      which is precisely the un-version-controlled thing this feature
      exists to refuse.

    The spelling is exact and unstripped: whitespace around a commit id is
    a caller's formatting, not part of the state it names.
    """
    if not isinstance(value, str):
        raise BookChangeRequestError(
            f"a version-controlled change carries its commit — got "
            f"{value!r} ({type(value).__name__}); the revision is the "
            f"full commit id, {REVISION_HEX_LENGTH} lowercase hexadecimal "
            "characters (the spelling `git rev-parse HEAD` answers in "
            "this repository), and a value that is not one names no "
            "version-controlled state"
        )
    if len(value) != REVISION_HEX_LENGTH or not _HEX.issuperset(value):
        spelled = "absent" if not value.strip() else repr(value)
        raise BookChangeRequestError(
            f"a version-controlled change carries its commit — got "
            f"{spelled}; the revision is the full commit id, "
            f"{REVISION_HEX_LENGTH} lowercase hexadecimal characters (the "
            "spelling `git rev-parse HEAD` answers in this repository), "
            "and anything else names no version-controlled state: a "
            "branch, a tag or HEAD is a mutable pointer (the canary "
            "lockfile refuses the same spellings for the same reason), a "
            "short id is an ambiguous one, and a working-tree marker is "
            "an un-committed edit — the un-version-controlled thing "
            "docs/alpha-engine-prd.md §C8's \"Version-controlled, "
            "human-authored\" exists to refuse"
        )
    return value


@dataclass(frozen=True)
class BookConstructionChange:
    """A modification to the book construction, as its carrier states it.

    Feature 306's subject is not a figure but an act — *changing the
    construction* — and this record is that act stated in the four facts
    the guard judges:

    * **``subject``** — the construction asset being changed (the
      information-ratio weighting, the shrinkage, the volatility target,
      the leverage cap), a non-empty name;
    * **``author``** — who authored the change, a non-empty name the
      refusal can say aloud;
    * **``author_kind``** — one of :data:`AUTHOR_KINDS`: the human kind
      or one of the declared agent kinds, and the one field the verdict
      turns on;
    * **``revision``** — the commit the change arrives under, the full id
      (:data:`REVISION_HEX_LENGTH` lowercase hex).

    Frozen, for the same reason :class:`~book.PromotedSignal` and
    :class:`~book.CompositeBook` are: a change record is the record of a
    decision, and a caller who could edit its author or its commit in
    memory could re-author the construction's history without the human
    decision §C8 demands.  Subject and author are stripped (a free name
    has one spelling worth storing); kind and revision are exact (a law
    has one spelling, period).

    The record is the sentence's *version-controlled* half made
    structural — construction refuses a revision that is not the commit,
    so **a change that names no commit cannot be stated at all** — and it
    deliberately carries nothing else: no clock (the commit is the
    change's timestamp), no payload and no changelog entry (what the
    change *says* is feature 307's sentence, built on exactly this
    record, and the admission gates' business is policy source, not
    construction records).
    """

    #: The construction asset being changed — a non-empty name.
    subject: str
    #: Who authored the change — a non-empty name the refusal says aloud.
    author: str
    #: Which of the declared vocabulary authored the change — the one
    #: field the verdict turns on.
    author_kind: str
    #: The commit the change arrives under — the full id, lowercase hex.
    revision: str

    def __post_init__(self) -> None:
        # object.__setattr__ where the frozen constructor would normalize:
        # the two free names strip, the two laws spell exactly — the value
        # validates and freezes, like PromotedSignal and CompositeBook.
        object.__setattr__(self, "subject", _validated_subject(self.subject))
        object.__setattr__(self, "author", _validated_author(self.author))
        object.__setattr__(self, "author_kind", _validated_kind(self.author_kind))
        object.__setattr__(self, "revision", _validated_revision(self.revision))


def _is_agent_kind(kind: str) -> bool:
    """The one comparison the guard is — everything else is spelling.

    Not ``kind in AGENT_AUTHOR_KINDS`` but ``kind != HUMAN_AUTHOR_KIND``:
    the boundary is the human kind, and everything that is not it is
    agent-authored.  Over a validated ``kind`` the two spellings answer the
    same fact (the vocabulary is closed), but this spelling is the one
    that stays true if the vocabulary ever widens — a new declared agent
    lands on the refused side without anyone having to remember to add it
    there, which is the prohibition-not-allowlist shape features 246/247
    state for their own wall.
    """
    return kind != HUMAN_AUTHOR_KIND


def _judged_change(change: Any) -> tuple[str, str, str, str]:
    """Read a change's four-field surface and settle the ask, in order.

    The surface is read duck-typed — ``subject``, ``author``,
    ``author_kind``, ``revision`` — with :data:`_MISSING` distinguishing an
    absent attribute from a present-``None`` one, the combiner's own
    discipline: the loader imports members under synthetic names and
    re-executes them, so a record this process composed may be a second
    class object, and a stand-in carrying the four attributes is judged
    identically to the member's own :class:`BookConstructionChange`.

    The four validators fire in declaration order — subject, author,
    kind, revision — so the ask settles whole before any authorship is
    judged: a caller that handed a broken record is told *what to fix*,
    never *an agent authored this*, however agent-authored the change
    meant to be.
    """
    raw_subject = getattr(change, "subject", _MISSING)
    if raw_subject is _MISSING:
        raise BookChangeRequestError(
            "a book construction change names its subject — the change "
            f"carries no subject at all ({type(change).__name__}); the "
            "subject is the construction asset being changed, and a "
            "change that names no subject guards nothing"
        )
    subject = _validated_subject(raw_subject)
    raw_author = getattr(change, "author", _MISSING)
    if raw_author is _MISSING:
        raise BookChangeRequestError(
            "a book construction change names its author — the change "
            f"carries no author at all ({type(change).__name__}); "
            "authorship is the whole fact this guard judges, and a change "
            "that states no author cannot be judged human- or "
            "agent-authored"
        )
    author = _validated_author(raw_author)
    raw_kind = getattr(change, "author_kind", _MISSING)
    if raw_kind is _MISSING:
        raise BookChangeRequestError(
            f"a book construction change states its author_kind — the "
            f"change carries none at all ({type(change).__name__}); the "
            f"kind is one of the declared vocabulary "
            f"{sorted(AUTHOR_KINDS)}, and it is the one fact the guard "
            "judges"
        )
    kind = _validated_kind(raw_kind)
    raw_revision = getattr(change, "revision", _MISSING)
    if raw_revision is _MISSING:
        raise BookChangeRequestError(
            f"a version-controlled change carries its commit — the change "
            f"carries no revision at all ({type(change).__name__}); an "
            "unstated revision is a working-tree edit, the "
            "un-version-controlled thing docs/alpha-engine-prd.md §C8's "
            "\"Version-controlled, human-authored\" exists to refuse"
        )
    revision = _validated_revision(raw_revision)
    return subject, author, kind, revision


def _refusal(subject: str, author: str, kind: str, revision: str) -> str:
    """The refusal's own sentence — the facts, the rule, and the one repair.

    Spelled once so :func:`rejects_agent_authored_modification` raises one
    message, and every branch of it states the same facts the same way.
    The repair has exactly one spelling because the sentence leaves one: a
    human makes the change.  There is deliberately no relabelling repair —
    *re-state the author_kind* would be an instruction to talk the guard
    out of its own boundary — and no routing repair either, except the
    true one: a finding the search believes in enters the book through
    the promotion path, as a promoted signal, where feature 301's
    weighting decides what it is worth.
    """
    return (
        f"{AGENT_MODIFICATION_CODE}: a change to the book construction "
        f"was authored by an automated author — subject {subject!r}, "
        f"author {author!r}, author_kind {kind!r}, revision {revision!r}. "
        "docs/alpha-engine-prd.md §C8 states what the construction is: "
        "\"Version-controlled, human-authored, explicitly outside the "
        "search space. Changing it is a human decision with a changelog "
        "entry, not a discovery\" — and §2.2 NG1 says it from the other "
        "side: this system is \"Not a strategy optimizer\", and entries, "
        "exits, sizing and portfolio construction are \"explicitly "
        "outside the search space\". The search's business is signals: a "
        "finding it believes in enters the book through the promotion "
        "path as a promoted signal, where the information-ratio "
        "weighting decides what it is worth — never as an edit to the "
        "construction that weights it, because a search allowed to "
        "improve its own weighting function has stopped being measured "
        "by it. The repair is the sentence's own, and there is exactly "
        "one: a human makes this change — the same subject, decided by "
        "a person, committed under version control, with the changelog "
        "entry feature 307 requires accompanying it"
    )


def is_agent_authored(change: Any) -> bool:
    """Answer whether the change was authored by an agent — the fact alone.

    The read-only spelling of feature 306's judgment: the same ask
    validation, the same one comparison, and no refusal.  ``True``
    exactly when the change's ``author_kind`` is not
    :data:`HUMAN_AUTHOR_KIND`; ``False`` for the human kind — the path
    §C8 names, where changing the construction is a human decision.

    The shape :func:`dreaming.bar.selection_bar` takes for its own
    figure: validate the ask, answer a fact, and let the caller decide
    what to do with it.  A caller that wants the refusal calls
    :func:`rejects_agent_authored_modification`; a caller that only wants
    to *know* (a report, an audit line, a test) calls this, and the two
    cannot disagree because they spell the comparison once, in
    :func:`_is_agent_kind`.

    Refuses what the verdict refuses, in the same order, with the same
    class: the ask's own facts, before the fact is answered.
    """
    _, _, kind, _ = _judged_change(change)
    return _is_agent_kind(kind)


def rejects_agent_authored_modification(change: Any) -> None:
    """Refuse an agent's edit to the construction — feature 306's call.

    The one judgment for feature 306's sentence: the change record in, and
    either the change proceeds down the human path or it is refused.  It
    reads the record's four-field surface duck-typed (an
    :class:`~book.BookConstructionChange`, or any object exposing the same
    ``subject`` / ``author`` / ``author_kind`` / ``revision`` surface —
    the loader's synthetic-name copies and a test's stand-in alike),
    settles the ask whole, and **raises**
    :class:`~book.errors.AgentAuthoredModificationError` when the author
    kind is not the human one — so a caller that routes construction
    changes through it on the write path is stopped before an agent's
    edit lands.  A human-authored change returns without raising: that is
    §C8's admitted path, a human decision under version control, and the
    changelog entry that accompanies it is feature 307's to demand.

    **The refusal is over *any* agent-authored modification.**  Every
    declared agent kind lands here — the loop, the reviser, the pool, the
    optimizer, the authoring agent itself — and nothing outside the one
    human kind is admitted by any route: the kinds are a closed
    vocabulary refused at the ask when mis-spelled, and a prohibition
    rather than an allowlist when declared.  A guard that admitted an
    agent on a technicality would be a search that had found one, which
    is the outcome the sentence exists to make impossible.

    The shape is the workspace's other verdicts exactly (feature 308's
    :func:`book.rejects_overleveraged_target`,
    :func:`dreaming.ceiling.rejects_uncapped_sweep`): a judgment over
    facts the caller already holds, which never opens a database, never
    reads an environment, consults no clock and re-derives nothing — the
    authorship and the commit arrive in the record, because a verdict is
    not a measurement and cannot interrogate its subject.

    Refuses, in this order, each naming what it is about:

    1. a subject, author, ``author_kind`` or ``revision`` that cannot be
       part of a stated change — the ask's own facts, refused before any
       authorship is judged (:class:`~book.errors.BookChangeRequestError`);
    2. an author kind that is not the human one — the one refusal this
       sentence mints
       (:class:`~book.errors.AgentAuthoredModificationError`), opening
       with :data:`AGENT_MODIFICATION_CODE`, stating the subject, the
       author, the kind and the revision, citing §C8 and NG1, and naming
       the one repair.  A human-authored change is not refused.
    """
    subject, author, kind, revision = _judged_change(change)
    if _is_agent_kind(kind):
        raise AgentAuthoredModificationError(_refusal(subject, author, kind, revision))
