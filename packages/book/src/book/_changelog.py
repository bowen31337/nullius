"""The changelog-entry companion — feature 307: every change accompanied.

app_spec.xml, "Portfolio Book Construction", feature 307: *System requires a
changelog entry accompanying every book construction change, which returns a
validation failure when absent.*  docs/alpha-engine-prd.md §C8 states the rule
in its own closing words — the section this whole category implements closes
with it:

    Signal book → IR-weighted combination with shrinkage → volatility
    targeting → position and concentration limits → orders.
    Version-controlled, human-authored, explicitly outside the search space.
    Changing it is a human decision with a changelog entry, not a discovery.

Feature 306 made the construction's *version-controlled, human-authored* half
structural: a modification is admitted only when a human authored it under a
commit.  Feature 307 makes the sentence's remaining clause structural —
*"with a changelog entry"* — and it builds on exactly feature 306's record: a
:class:`~book.BookConstructionChange` already carries the subject, the author,
the author kind and the commit, and this module adds the fifth fact §C8 names,
the changelog entry, and the refusal that enforces that it *accompanies* the
change.

**Why the companion needs the change to name.**  The refusal this sentence
mints is not *an entry is absent* in the abstract — it is *this change, the one
a caller means to land, has no entry beside it*.  So the verdict reads the
change's four-field surface — the subject, the author, the kind, the revision —
to say aloud *which change* is unaccompanied, the way feature 306's refusal
names the change it refuses.  It reads that surface, it does not re-judge it:
whether the change is agent-authored is feature 306's verdict, whether its
revision is a full commit is feature 306's ask, and this module re-derives
neither — a companion that re-litigated the change's authorship would be
answering a question about the guard from inside the entry's path.

This module applies §C8's clause in three spellings of one act:

* :class:`ChangelogEntry` — the entry as its carrier states it: a frozen record
  of exactly two fields (the subject the entry documents, the body the entry's
  prose).  The record is the sentence's *changelog entry* made structural — a
  change that names no entry cannot be accompanied by one — and it carries
  nothing else: the entry is the human's own document, not a projection of the
  change's four fields, so its subject is a free name and its body a free
  string, and neither is re-derived from the change;
* :func:`is_missing_changelog_entry` — the read-only spelling: the fact without
  the refusal, the shape :func:`book.is_agent_authored` takes for its own fact
  (validate the ask, answer a fact);
* :func:`requires_changelog_entry` — the **requires** of the sentence, the
  verdict shape the workspace's other refusals-of-a-fact take
  (:func:`book.rejects_agent_authored_modification`, feature 308's
  :func:`book.rejects_overleveraged_target`): it **raises** when a change is
  present and its entry is absent, so a caller that routes construction changes
  through it on the write path is stopped before a change lands unaccompanied.

**The boundary is presence, not content, and deliberately.**  This package
validates no changelog prose — what the entry *says* is none of this module's
business (the authorship guard judges authorship and version control, and the
admission gates' business is policy source, not construction records), so the
entry is admitted as *present* when it is a well-stated :class:`ChangelogEntry`
and refused as *absent* when it is not there at all — a ``None``, an omitted
field, or a value that could not be stated.  The refusal is the sentence's
*absent*, and it is the one this module enforces.  The two are kept apart by the
sentinel discipline the combiner states: an entry that *omits* its ``body``
attribute is absent (the entry could not be stated), distinct from an entry that
*carries* a blank body (the entry was stated, and stated badly) — the latter is
the ask's own fact, refused before any absence is judged.

**The ask settles before the judgment.**  A present entry's two fields are
validated in declaration order — subject, body — as
:class:`~book.errors.ChangelogEntryRequestError`, and only a wholly well-stated
entry is judged present or absent.  So a caller that handed a broken entry is
told *state the entry*, never *the entry is missing*; and an absent change is
refused as the ask's own fact too, because a companion cannot say *which change*
is unaccompanied when no change was handed.  The ordering is the one every
verdict in this workspace states: the ask settles whole before any judgment is
formed.

**Two refusal classes, because the repairs differ.**  The ask's own facts — a
subject or body that cannot be part of a stated entry — are refused with
:class:`~book.errors.ChangelogEntryRequestError` and carry no code, for the
reason :class:`~book.errors.BookChangeRequestError` gives: a malformed entry
names its subject in its first words.  The one judgment the sentence mints — a
present change with no entry beside it — is refused with
:class:`~book.errors.MissingChangelogEntryError`, opening with
:data:`MISSING_CHANGELOG_ENTRY_CODE` and naming the change.  Both are subclasses
of the base with the same consequence, and the same reason to be siblings
rather than aliases: an absent entry is refusable though the entry field was
perfectly well formed (it was simply not handed), and a mis-stated entry is
refusable though an entry was handed, so the two facts are genuinely different.

**What this module does not do.**  It judges no content — the entry's body need
only be a non-empty string, and what it says is none of this module's business.
It validates no authorship — that is feature 306's sentence, and it builds on
the same change record.  It installs no filesystem hook, writes no changelog
file and sweeps no state — the canary lockfile states the pair (a guard seam
plus a nightly sweep) and this feature's sentence mints only the seam: the
deployment's wiring delivers the change and its entry through the verdict, and
an entry that bypasses the seam is a wiring bug, not a fact this module could
have measured from inside itself.  It opens no database, reads no environment,
consults no clock and re-derives neither the change nor the entry.

**No new component, and the layering note.**  The companion is a free function
beside the combiner, the way feature 306's guard sits and feature 308's cap
sits: its whole input is two records the caller already holds, so there is
nothing for the factory to compose and nothing for a deployment to configure.
No ``@register``, no table, no endpoint, no migration, no seat edit, and no
third-party import — ``dataclasses``, ``typing`` and the member's own
``.errors`` — so the factory's scan, which imports this package on every
``create_app()`` to fire its ``@register``, pays nothing for the companion
beyond the import it already paid for the combiner and the guard.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .errors import ChangelogEntryRequestError, MissingChangelogEntryError

__all__ = [
    "MISSING_CHANGELOG_ENTRY_CODE",
    "ChangelogEntry",
    "is_missing_changelog_entry",
    "requires_changelog_entry",
]

#: The code a *missing-entry* refusal opens with — a book construction change
#: was handed without the changelog entry §C8 requires — so the refusal is
#: greppable by the word that names it.  Feature 307's sentence mandates no
#: token (it names its subject in prose), so the code is this module's own,
#: minted on the ``agent_authored_modification`` / ``leverage_above_quarter_kelly``
#: convention the workspace states for the one refusal an operator greps a
#: deployment log for: *why was this change refused?*  The ask's own facts
#: carry no code, for the reason
#: :class:`~book.errors.ChangelogEntryRequestError` gives — a malformed entry
#: names its subject in its first words, and a token there would hand a reader
#: a developer's word for a fact they can simply state.
MISSING_CHANGELOG_ENTRY_CODE = "missing_changelog_entry"

#: Sentinel for "attribute not present" when reading a record's surface, so a
#: record that omits ``body`` entirely is distinguished from one that carries
#: ``body=None`` — an entry that omits its body is *absent* (it could not be
#: stated), not an entry that stated its body as nothing.  The combiner's and
#: the guard's own ``_MISSING`` discipline, read on this feature's entry.
_MISSING = object()


def _validated_subject(value: Any) -> str:
    """Check that ``value`` names the asset the entry documents.

    The subject is the *what* the changelog entry is about — the construction
    asset the entry documents — a free name, because the entry is the human's
    own document and no module of this member owns a closed list of what a
    changelog may document.  A non-empty string is all the entry needs: the
    subject is what the refusal and the record's equality read, and an entry
    that names no subject documents nothing.  Stripped and stored stripped, so
    the refusal and the record's equality read one spelling of the name.
    """
    if not isinstance(value, str) or not value.strip():
        raise ChangelogEntryRequestError(
            f"a changelog entry names its subject — got {value!r} "
            f"({type(value).__name__}); the subject is the construction asset "
            "the entry documents (the information-ratio weighting, the "
            "shrinkage, the volatility target, the leverage cap), and an entry "
            "that names no subject documents nothing"
        )
    return value.strip()


def _validated_body(value: Any) -> str:
    """Check that ``value`` is the entry's own prose.

    The body is the *what changed and why* — the prose a human writes when they
    change the construction, the record §C8's *"with a changelog entry"*
    demands.  A non-empty string, stripped and stored stripped; the entry
    records it, the ask refuses its absence.  What the body *says* is none of
    this module's business — only that it is stated.
    """
    if not isinstance(value, str) or not value.strip():
        raise ChangelogEntryRequestError(
            f"a changelog entry carries its body — got {value!r} "
            f"({type(value).__name__}); the body is the entry's own prose — "
            "what the human recorded about the change (docs/alpha-engine-prd.md "
            '§C8: "Changing it is a human decision with a changelog entry, not '
            'a discovery"), and an entry with no body records nothing'
        )
    return value.strip()


@dataclass(frozen=True)
class ChangelogEntry:
    """A changelog entry, as its carrier states it.

    Feature 307's subject is the entry, and this record is the entry stated in
    the two facts the companion judges:

    * **``subject``** — the construction asset the entry documents (the
      information-ratio weighting, the shrinkage, the volatility target, the
      leverage cap), a non-empty name;
    * **``body``** — the entry's own prose, the *what changed and why* a human
      writes, a non-empty string.

    Frozen, for the same reason :class:`~book.BookConstructionChange`,
    :class:`~book.PromotedSignal` and :class:`~book.CompositeBook` are: a
    changelog entry is the record of a decision, and a caller who could edit
    its subject or its body in memory could rewrite what the change was
    documented to say without the human decision §C8 demands.  Both fields are
    stripped (a free name and a free string have one spelling worth storing).

    The record is the sentence's *changelog entry* made structural — a change
    that names no entry cannot be accompanied by one — and it deliberately
    carries nothing else: the entry is the human's own document, **not** a
    projection of the change's four fields, so its subject is a free name (the
    asset it documents, which need not equal the change's subject) and its body
    a free string, and neither is re-derived from the change it accompanies.
    """

    #: The construction asset the entry documents — a non-empty name.
    subject: str
    #: The entry's own prose — the what-changed-and-why, a non-empty string.
    body: str

    def __post_init__(self) -> None:
        # object.__setattr__ where the frozen constructor would normalize:
        # both free strings strip — the value validates and freezes, like
        # BookConstructionChange, PromotedSignal and CompositeBook.
        object.__setattr__(self, "subject", _validated_subject(self.subject))
        object.__setattr__(self, "body", _validated_body(self.body))


def _change_fields(change: Any) -> tuple[Any, Any, Any, Any]:
    """Read the change's four-field surface for naming, duck-typed.

    The verdict names *which change* is unaccompanied, so it reads the change's
    ``subject`` / ``author`` / ``author_kind`` / ``revision`` — the surface
    feature 306's :class:`~book.BookConstructionChange` carries.  Read
    duck-typed, with ``None`` standing in for an absent attribute, because this
    module *names* the change rather than *re-judging* it: whether the change
    is agent-authored is feature 306's verdict, whether its revision is a full
    commit is feature 306's ask, and this companion re-derives neither — it
    reads the four fields the caller's change already states and says them
    aloud in the refusal.
    """
    return (
        getattr(change, "subject", None),
        getattr(change, "author", None),
        getattr(change, "author_kind", None),
        getattr(change, "revision", None),
    )


def _presence(
    entry: Any,
) -> tuple[bool, tuple[str, str] | None]:
    """Settle the entry's ask, and answer whether it is present.

    The one comparison the companion makes, everything else being spelling.
    An entry is *present* only when it carries both a ``subject`` and a
    ``body`` attribute — the sentinel distinguishing an *omitted* field (the
    entry could not be stated, so it is *absent*) from a *present-and-blank*
    one (the entry was stated, and stated badly, which is the ask's own fact).
    A present entry's two fields are validated in declaration order — the ask
    settles whole before any absence is judged — so a caller handed a broken
    entry meets :class:`~book.errors.ChangelogEntryRequestError`, never the
    judgment.  Returns ``(present, validated_fields_or_None)``.
    """
    if entry is None:
        return False, None
    raw_subject = getattr(entry, "subject", _MISSING)
    raw_body = getattr(entry, "body", _MISSING)
    if raw_subject is _MISSING or raw_body is _MISSING:
        # A field the entry omits is an entry that could not be stated — the
        # entry is absent, not broken.  The sentinel keeps that distinct from
        # a present-and-blank field, which the ask below refuses.
        return False, None
    return True, (_validated_subject(raw_subject), _validated_body(raw_body))


def _refusal(subject: Any, author: Any, kind: Any, revision: Any) -> str:
    """The refusal's own sentence — the change, the rule, and the one repair.

    Spelled once so :func:`requires_changelog_entry` raises one message.  It
    names the change the entry was meant to accompany (the subject, the author,
    the kind, the revision the change carries), cites §C8's own words, and
    states the one repair that exists — a human accompanies the change with the
    entry it requires.  There is deliberately no fabrication repair — *write an
    entry for it* would be this module inventing the human's own document — and
    the repair names the human, because the entry is the human decision §C8
    demands, made legible.
    """
    return (
        f"{MISSING_CHANGELOG_ENTRY_CODE}: a book construction change was handed "
        f"without the changelog entry §C8 requires — subject {subject!r}, "
        f"author {author!r}, author_kind {kind!r}, revision {revision!r}. "
        "docs/alpha-engine-prd.md §C8 states what the construction is: "
        "\"Version-controlled, human-authored, explicitly outside the search "
        "space. Changing it is a human decision with a changelog entry, not a "
        'discovery" — and the changelog entry is the change\'s own companion, '
        "the record a human writes when they change the construction, "
        "documenting what changed and why. A change without it is not yet the "
        "§C8 path: the repair is the sentence's own, and there is exactly one — "
        "a human accompanies this change with the changelog entry it requires, "
        "the same subject decided by a person, committed under version control, "
        "with the entry that documents it"
    )


def is_missing_changelog_entry(change: Any, entry: Any) -> bool:
    """Answer whether the change is unaccompanied — the fact alone.

    The read-only spelling of feature 307's requirement: the same ask
    validation, the same presence comparison, and no refusal.  ``True`` exactly
    when a change is present and the entry that should accompany it is absent
    (a ``None``, an omitted field, or a value that could not be stated);
    ``False`` when a well-stated entry accompanies the change — the path §C8
    names, where changing the construction is a human decision *with a
    changelog entry*.

    The shape :func:`book.is_agent_authored` takes for its own fact: validate
    the ask, answer a fact, and let the caller decide what to do with it.  A
    caller that wants the refusal calls :func:`requires_changelog_entry`; a
    caller that only wants to *know* (a report, an audit line, a test) calls
    this, and the two cannot disagree because they settle the ask and the
    presence once, in :func:`_presence`.

    Refuses what the verdict refuses, in the same order, with the same class:
    an absent change is refused as the ask's own fact before any presence is
    answered.
    """
    present, _ = _presence_after_change(change, entry)
    return not present


def requires_changelog_entry(change: Any, entry: Any) -> None:
    """Refuse a change that lands without its changelog entry — feature 307's call.

    The one judgment for feature 307's sentence: the change and the entry that
    should accompany it in, and either the change proceeds down the accompanied
    path or it is refused.  It reads the change's four-field surface duck-typed
    to name the change, settles the entry's ask whole first, and **raises**
    :class:`~book.errors.MissingChangelogEntryError` when a change is present
    and its entry is absent — so a caller that routes construction changes
    through it on the write path is stopped before a change lands
    unaccompanied.  A change with a well-stated entry beside it returns without
    raising: that is §C8's admitted path, a human decision under version
    control *with a changelog entry*.

    **The refusal is over a present change with no entry beside it.**  A
    ``None`` entry, an entry that omits a field, or a value that could not be
    stated all land here — the entry is absent, whatever the change promised —
    and the refusal names the change (its subject, its author, its kind, its
    revision) so the operator can see *which change* the search, or a caller,
    meant to land without its record.

    The shape is the workspace's other verdicts exactly (feature 306's
    :func:`book.rejects_agent_authored_modification`, feature 308's
    :func:`book.rejects_overleveraged_target`): a judgment over facts the caller
    already holds, which never opens a database, never reads an environment,
    consults no clock and re-derives nothing — the change and the entry arrive
    in the records, because a verdict is not a measurement and cannot
    interrogate its subject.

    Refuses, in this order, each naming what it is about:

    1. an absent change, or an entry whose subject or body cannot be part of a
       stated entry — the ask's own facts, refused before any presence is
       judged (:class:`~book.errors.ChangelogEntryRequestError`);
    2. a present change with no entry beside it — the one refusal this sentence
       mints (:class:`~book.errors.MissingChangelogEntryError`), opening with
       :data:`MISSING_CHANGELOG_ENTRY_CODE`, naming the change, citing §C8, and
       stating the one repair.  A change with a well-stated entry is not
       refused.
    """
    present, _ = _presence_after_change(change, entry)
    if not present:
        raise MissingChangelogEntryError(_refusal(*_change_fields(change)))


def _presence_after_change(change: Any, entry: Any) -> tuple[bool, tuple[str, str] | None]:
    """Require a change to accompany, then settle the entry's presence.

    The ordering the sentence demands: an absent change is refused as the ask's
    own fact — a companion cannot say which change is unaccompanied when no
    change was handed — and only a present change meets the entry's presence.
    Shared by both public spellings so the predicate and the verdict cannot
    disagree about the order.
    """
    if change is None:
        raise ChangelogEntryRequestError(
            "a changelog entry accompanies a book construction change — the "
            f"change is absent (got entry {entry!r}); the companion names the "
            "change the entry was meant to accompany, and a change that is not "
            "handed cannot be accompanied (docs/alpha-engine-prd.md §C8: a "
            "change is a human decision with a changelog entry — both must be "
            "present)"
        )
    return _presence(entry)
