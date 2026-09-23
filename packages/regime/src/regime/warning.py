"""The ledger's named-empty report — feature 286.

app_spec.xml, "Regime Coverage Strata", feature 286: *System emits an
``empty_stratum`` warning when any named regime stratum holds 0 stored
worlds.*  Its declared parent is feature 284 — the ledger read — and the
dependency is the whole shape, the same one feature 289's verdict takes:
the warning is read off a *reading*, the very
:class:`~regime.ledger.CoverageLedger`
:meth:`~regime.coverage.RegimeCoverage.ledger` answers with, and this
module adds to that reading the one act it declines to perform itself.

**Why a warning, and why that word is the whole design.**  The spec's
emission family — the corruption alert (feature 192), the
``unrecoverable_state`` alert (450), the ``determinism_broken`` alert
(552) and the ``recomputation_suspected`` alert (253) — says *alert*
every time, and every one of them stops its caller: the emission is a
typed raise, loud because the state it names is a failure (corruption,
an unrecoverable state, a broken determinism constant, a broken cost
model).  This feature is the spec's one *warning*, and the state it
names is not a failure at all: §C7's own example ledger *writes the
zero* — ``{high-vol trend: 2, low-vol chop: 14, crash: 0, …}`` — the
census (feature 290) writes one row per named stratum **zeros
included**, and :meth:`~regime.coverage.RegimeCoverage.name_stratum`
lands the named-empty row on purpose.  A named stratum holding no
worlds is an expected, by-design state of a pool that has not yet
traded in that regime, and the feature's sentence asks the system to
*report* it — visible, greppable and non-fatal — not to stop anything on
it.  The refusing siblings are the ones that halt: the promotion block
(feature 285) and the diversity refusal (289) both stop a caller over
these counts; this module is the category's *report*, and a report that
raised would make the expected state exceptional — every census of a
pool that has not yet seen a crash would be an ``except`` block, and the
caller that forgot to catch would lose the report *and* the count.

**The emission is ``warnings.warn``, and the category is the record.**
:func:`warnings.warn` is Python's own warning mechanism and the one
spelling of *emit a warning* that does not stop the caller: visible by
default, filterable by an operator (``-W`` can silence it or escalate
it to an error), deduplicated per location by the machinery, and — the
property that decides the design — non-fatal by construction, so the
emission cannot become the gate this feature's sentence never asked
for.  The thing warned is an :class:`EmptyStratumWarning`, a
:class:`Warning` subclass that **is** the finding: the machinery
dispatches on its category, a test or a filter catches it by type, and
the instance still carries the structured record — the names, on
:attr:`EmptyStratumWarning.strata` — so a caller that catches the
warning to keep going holds everything a log line, a ticket or a
dashboard needs.  That is feature 253's lesson (*"catching the alert by
type still leaves the record on the error"*) restated for the machinery
this feature uses: catching the warning by category still leaves the
names on the warning.

**Named-empty fires; never-named never does.**  ``0107`` detail 1 is the
load-bearing law at this seam, and four docstrings in this member
already promise this module will keep it: a stratum *named and holding
no worlds* is a row with ``world_count = 0``, and a stratum *nobody
named* is the absence of a row — a different fact with its own spelling
(:meth:`~regime.ledger.CoverageLedger.holes`, a question the caller asks
a vocabulary it holds).  This module reads the reading's own
:attr:`~regime.ledger.CoverageLedger.empty` view and never consults a
vocabulary, so the warning fires on §C7's ``crash: 0`` and never on a
stratum nobody configured — a caller that wants the never-named finding
asks ``holes()`` and gets :class:`~regime.ledger.CoverageHole` values
for exactly the names it declared.  A ledger holding no rows at all
warns nothing: a database where no census has run has no stratum that
is *named* and empty, and an empty pool is the promotion gate's and the
diversity verdict's finding, not this module's.

**Two spellings, the pair feature 253 set.**
:func:`empty_stratum_warning` is the pure question — the warning a
reading warrants, as a value, or ``None`` when every named stratum
holds worlds; it emits nothing, opens no database, and is the spelling
a caller that renders the finding itself (a dashboard, a report)
reaches for.  :func:`emit_empty_stratum_warning` is the sentence's own
act — build that warning and, when there is one, hand it to
:func:`warnings.warn` — and it returns what it emitted (``None`` when
nothing), so a caller that logs as well as warns holds one value for
both.  Each takes the reading; neither ever re-reads the table behind
it: §C6's tripwires excise worlds, the census and the backfill land
counts, and a warning emitted over a reading reports *that reading's*
pool — the caller warning about the pool *now* reads again, exactly as
the verdict's caller does.

**The seam is duck-typed, and what it reads is validated.**  The
warning takes the ledger value — reached through either of feature
284's spellings, the store's ``ledger()`` verb or
:func:`~regime.ledger.read_ledger` — and reads its ``empty`` view
structurally rather than ``isinstance``-gating it, for the reason every
seam in this workspace duck-reads: the module loader imports each
member under a synthetic name, so the reading a composed store hands
back is structurally identical to a direct import's without being the
same class object, and a type gate would refuse the very reading
composition serves.  What is read is checked: each empty row's name
goes through feature 283's own validator, imported rather than
re-written, with its :class:`~regime.errors.CoverageError` translated
into this module's vocabulary at the seam — the diversity module's
argument, restated: an ask refused here must not surface as a
count-persist refusal a caller's ``except EmptyStratumWarningError``
can miss.  And each row is checked against its own count, the
self-consistency discipline feature 253 states for a carrier whose flag
disagrees with its own duration: the ``empty`` view is *defined* as the
rows holding ``world_count = 0``, so a view naming a stratum whose own
row says three is a carrier lying about its own state, and believing it
would warn *crash holds no worlds* about a row that contradicts the
warning — a phantom an operator would chase.  Refused, not believed.

**The ask refuses; the finding never does.**  A caller that hands the
emission nothing, a string, a view that cannot be read, or the store
where the reading belongs is refused with
:class:`~regime.errors.EmptyStratumWarningError` naming the repair —
feature 284's verb — because a caller whose emission failed quietly
would read a warning-less log as *every stratum holds worlds*, which is
the exact blindness §C7's ledger exists to cure.  But the finding
itself is never raised, never refused, never handed back as an error:
a named stratum holding no worlds is §C7's ``crash: 0``, and this
module's whole act is to say so where an operator can see it and let
the caller proceed.  :class:`~regime.errors.EmptyStratumWarningError`
therefore has no ``empty_stratum``-found spelling to catch by accident
— the same argument :class:`~regime.errors.DiversityClaimError`'s
no-``admitted`` paragraph makes, one act over.

**No component, no store, and import-cheap.**  The member's
``__init__`` states the law this module keeps: the ``empty_stratum``
warning *is a fact about a row this store already holds* —
``world_count == 0`` is what
:attr:`~regime.coverage.CoverageCount.empty` answers — so the warning
is a free function over the reading the composed store serves, and the
member's registered surface stays feature 283's one store, reached
exactly as :mod:`regime.__init__` documents.  Stdlib only —
:mod:`warnings` and the two validators imported from the writer — no
``sqlite3``, no third-party import at module scope, so the factory's
scan imports this package for the same near-nothing it always did and
an emission costs a caller nothing but the reading it already held.
"""

from __future__ import annotations

import warnings
from collections.abc import Iterable
from typing import Any

from .coverage import _validated_stratum, _validated_world_count
from .errors import CoverageError, EmptyStratumWarningError

__all__ = [
    "EMPTY_STRATUM_CODE",
    "EmptyStratumWarning",
    "emit_empty_stratum_warning",
    "empty_stratum_warning",
]

#: The one word that names the finding — ``empty_stratum`` — opening
#: every message this module emits so it is greppable by the word an
#: operator would search for, the convention ``not_regime_diverse``
#: (feature 289), ``pool_too_thin`` (275), ``full_history_fit`` (290),
#: ``no_origin`` (288) and ``recomputation_suspected`` (253) already
#: follow in this workspace.  The spec's own spelling, verbatim — the
#: word is what an operator greps for and what a filter dispatches on,
#: so a warning a reader cannot find by the name the spec gave it is a
#: warning the spec did not get.
EMPTY_STRATUM_CODE = "empty_stratum"


def _message(names: tuple[str, ...]) -> str:
    """The warning's message — the finding, §C7, and the way out.

    The same shape feature 289's refusal message takes, because an
    operator reading either deserves the same three things: the finding
    stated in counts and names, the §C7 hazard the finding is an early
    glimpse of, and the repair — the acts that bring stored worlds into
    an empty stratum, which are the category's own (the census that
    counts the pool, the backfill that replays stored trees against
    epochs they never saw).  A gate whose message does not name the
    door out is a dead end rather than a finding; a warning has the
    same obligation, because a warning is what an operator reads
    *instead of* being stopped.
    """
    noun, verb = ("stratum", "holds") if len(names) == 1 else ("strata", "hold")
    named = ", ".join(repr(name) for name in names)
    return (
        f"{EMPTY_STRATUM_CODE}: {len(names)} named {noun} {verb} no stored "
        f"worlds ({named}); docs/alpha-engine-prd.md §C7 maintains the "
        "coverage ledger precisely so a named regime holding nothing "
        "stays visible — the replay pool grows monotone with calendar "
        "time, and run six months in low-vol chop the entire pool is "
        "low-vol chop. Bring stored worlds into the empty stratum: the "
        "census (feature 290) and the backfill (feature 287) are the "
        "acts that do, and this warning stops the day one of them does"
    )


# -- The record --------------------------------------------------------------------


class EmptyStratumWarning(Warning):
    """One reading's ``empty_stratum`` finding — feature 286's record.

    Built by :func:`empty_stratum_warning` and handed to
    :func:`warnings.warn` by :func:`emit_empty_stratum_warning`, so the
    thing the machinery dispatches on and the thing a caller catches by
    type *is* the finding — the shape feature 253's
    :class:`~replay.alert.RecomputationSuspected` record states for the
    raise side of the same family (*"catching the alert by type still
    leaves the record on the error"*), restated for ``warnings``:
    catching this warning by category still leaves the names on the
    warning.

    A :class:`Warning` subclass rather than a plain frozen value because
    the machinery requires one: ``warnings.warn`` dispatches on the
    category, an operator's ``-W`` filter names it, and a test catches
    it with ``pytest.warns(EmptyStratumWarning)`` — and being the
    category and carrying the record in one object is what keeps the
    emission non-fatal *and* structured at once, the feature's whole
    ask.  The full operator message is carried in the standard
    exception ``args``, so ``str(warning)`` is display-ready and the
    machinery's default rendering needs nothing from this class.

    :attr:`strata` is the payload an operator acts on — the names of
    the strata the reading says are named and hold no stored worlds, in
    the reading's own order (the ledger's rows are name-ordered, so the
    warning names them in the order an operator reading the ledger
    would).  The counts are not carried because they are the finding's
    one value: every stratum in the warning holds zero, and a field
    that could only ever hold ``0`` is a number nobody reads.

    The constructor **defends its own consistency**, the discipline
    feature 253's record states: a warning naming no stratum is not a
    finding any reading produced, and a warning naming one stratum
    twice would report the emptiness twice — both refused, along with
    any name that cannot be a stratum (validated through feature 283's
    own validator, with its refusal translated into this module's
    vocabulary at the seam).  Usable as the answer
    :func:`empty_stratum_warning` produces and constructible directly
    by a caller that holds the names and wants a record — the two
    spellings of one record, the same pair feature 253 ships.
    """

    __slots__ = ("_strata",)

    def __init__(self, strata: Iterable[str]) -> None:
        names = _validated_names(strata)
        # ``Warning.__init__`` with the message, so ``str()`` of the
        # record is the operator message and the machinery's default
        # rendering shows it verbatim — the one thing a warning must be
        # is readable where it lands.
        super().__init__(_message(names))
        self._strata = names

    @property
    def strata(self) -> tuple[str, ...]:
        """The named-empty strata, in the reading's own order."""
        return self._strata

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"{type(self).__name__}(strata={self._strata!r})"


def _validated_names(strata: Any) -> tuple[str, ...]:
    """Return ``strata`` as the warning's content, or refuse what is not.

    The record's one gate, so a warning built by :func:`empty_stratum_warning`
    and one constructed directly by a caller are validated the same way —
    the stance :class:`~regime.ledger.CoverageLedger` states for its own
    constructor.  Three things are checked, each because a warning that
    did not check it would misreport:

    * **the shape** — the argument is an iterable of names.  A single
      string is refused rather than iterated into characters, the same
      refusal :func:`regime.ledger._validated_vocabulary` makes of one.
    * **the names** — each goes through feature 283's own validator,
      imported rather than re-written, so the warning cannot drift from
      the writer on what a stratum is; its refusal is translated into
      this module's vocabulary at the seam, so a caller's ``except
      EmptyStratumWarningError`` is never defeated by the count-persist
      vocabulary for an act that persisted nothing.
    * **the identity** — no name twice.  The ledger itself refuses
      duplicate rows (``stratum`` is the table's whole primary key), so
      a duplicate arriving here is a carrier this module cannot vouch
      for, and a warning naming one stratum twice would report one
      emptiness twice.
    """
    if isinstance(strata, (str, bytes)) or not isinstance(strata, Iterable):
        raise EmptyStratumWarningError(
            f"{EMPTY_STRATUM_CODE}: the warning's strata are an iterable "
            f"of names — got {strata!r} ({type(strata).__name__}); a "
            "single string is a sequence of its characters, which is not "
            "a set of strata, and something that is not a collection "
            "names no finding (feature 286)"
        )
    names: list[str] = []
    seen: set[str] = set()
    for name in strata:
        try:
            validated = _validated_stratum(name)
        except CoverageError as exc:
            raise EmptyStratumWarningError(
                f"{EMPTY_STRATUM_CODE}: a warned stratum could not be "
                f"read as a name — got {name!r}: {exc}"
            ) from exc
        if validated in seen:
            raise EmptyStratumWarningError(
                f"{EMPTY_STRATUM_CODE}: the warning names stratum "
                f"{validated!r} twice; the ledger's identity is one row "
                "per name, so one emptiness is one finding, and a "
                "warning naming a stratum twice reports it twice "
                "(feature 286)"
            )
        seen.add(validated)
        names.append(validated)
    if not names:
        # The record's own arithmetic, defended at construction: an
        # ``empty_stratum`` warning exists *because* a named stratum
        # holds none, and a warning naming no stratum is the finding's
        # absence spelled as the finding — the caller that wants silence
        # is the caller :func:`empty_stratum_warning` answers with
        # ``None``, not one this record mislabels.
        raise EmptyStratumWarningError(
            f"{EMPTY_STRATUM_CODE}: the warning names at least one "
            "stratum — got none; a named regime holding no stored worlds "
            "is the state this warning reports, and a warning carrying "
            "no names is not that finding but its absence wearing it "
            "(feature 286)"
        )
    return tuple(names)


# -- The seam ----------------------------------------------------------------------


def _empty_strata(ledger: Any) -> tuple[str, ...]:
    """Read the named-empty names off ``ledger``, or refuse what carries none.

    The emission's whole evidence, gathered in one place: the names of
    the strata the reading says are named and hold no stored worlds, in
    the reading's own order.  The finding is the names and the message
    is built from them — the two things this seam reads — and nothing
    else on the ledger is consulted, because the ``empty`` view is the
    ledger's own named spelling of exactly this state and a warning that
    re-derived it from ``rows`` would be the drift that view exists to
    prevent.

    Duck-typed on ``empty`` (the loader's synthetic-name copies make
    ``isinstance`` refuse the very reading composition serves), and each
    empty row is checked twice: its name through feature 283's own
    validator — imported, not re-written — and its own ``world_count``
    through the same validator, then pinned to zero.  The zero is the
    self-consistency check, feature 253's discipline for a carrier
    whose flag disagrees with its own duration: the view is *defined*
    as the rows holding no worlds, so a row the view carries whose own
    count says otherwise is a carrier lying about its own state, and a
    warning that believed it would name a stratum as empty about a row
    that contradicts it.  Both refusals are translated into this
    module's vocabulary at the seam, so a caller's ``except
    EmptyStratumWarningError`` is never defeated by the count-persist
    vocabulary for an act that persisted nothing.
    """
    empty = getattr(ledger, "empty", None)
    if empty is None:
        # The store carries its own read verb and no ``empty`` view, so
        # a store handed in where the reading belongs is refusable *by
        # its repair*: read first (feature 284's verb), then warn — the
        # same refusal, for the same reason, the diversity seam makes.
        if callable(getattr(ledger, "ledger", None)):
            raise EmptyStratumWarningError(
                f"{EMPTY_STRATUM_CODE}: the warning is emitted over a "
                f"reading, and {ledger!r} is the store — call its "
                "``ledger()`` verb (feature 284's read, either spelling) "
                "and hand the emission the CoverageLedger it answers "
                "with; a warning over a live store would be a warning "
                "about a pool that can move under it"
            )
        raise EmptyStratumWarningError(
            f"{EMPTY_STRATUM_CODE}: the warning is emitted over a "
            f"coverage ledger — got {ledger!r} "
            f"({type(ledger).__name__}), which carries no ``empty`` "
            "view; the reading feature 284's verb answers with is the "
            "evidence the warning is read off, and something that is "
            "not that reading names no strata to warn about"
        )
    if isinstance(empty, (str, bytes)) or not isinstance(empty, Iterable):
        raise EmptyStratumWarningError(
            f"{EMPTY_STRATUM_CODE}: a ledger's ``empty`` view is a "
            f"collection of the rows that hold no stored worlds — got "
            f"{empty!r} ({type(empty).__name__}); the finding is which "
            "named strata that view carries, and something that cannot "
            "be read names no finding"
        )
    names: list[str] = []
    for row in empty:
        try:
            name = _validated_stratum(getattr(row, "stratum", None))
        except CoverageError as exc:
            raise EmptyStratumWarningError(
                f"{EMPTY_STRATUM_CODE}: an empty row could not be read "
                f"as a stratum — got {row!r}: {exc}"
            ) from exc
        try:
            count = _validated_world_count(getattr(row, "world_count", None))
        except CoverageError as exc:
            raise EmptyStratumWarningError(
                f"{EMPTY_STRATUM_CODE}: the empty row for {name!r} could "
                f"not be read as a count: {exc}"
            ) from exc
        if count != 0:
            raise EmptyStratumWarningError(
                f"{EMPTY_STRATUM_CODE}: the reading's ``empty`` view "
                f"names {name!r}, whose own world_count is {count} and "
                "not 0; the view is the ledger's spelling of the rows "
                "that hold no worlds, so a carrier whose view disagrees "
                "with its own rows is refused rather than believed — "
                "the warning would name a stratum as holding no worlds "
                "about a row that says otherwise, and that is a phantom "
                "an operator would chase (feature 286)"
            )
        names.append(name)
    return tuple(names)


# -- The two spellings -------------------------------------------------------------


def empty_stratum_warning(ledger: Any) -> EmptyStratumWarning | None:
    """Build the ``empty_stratum`` warning a reading warrants — or ``None``.

    The pure question, and the spelling a caller that renders the
    finding itself reaches for: the ledger value in — the reading
    feature 284's verb answers with — and either the warning that
    reading warrants or ``None``.  ``None`` is an *answer*, not a
    fallback: it says every stratum this ledger names holds at least
    one stored world, or that the ledger names nothing at all — both
    states a dashboard renders as coverage, neither a fault.

    Emits nothing, opens no database, writes no row: the emission is
    :func:`emit_empty_stratum_warning`'s act, and keeping the two apart
    is what lets a caller ask for the finding without paying for the
    report — the same pair feature 253 ships as
    :func:`~replay.alert.suspected_recomputation` (the record) and
    :func:`~replay.alert.emit_recomputation_suspected` (the emission).

    Refuses, in this module's vocabulary, on the ask only — a ledger
    carrying no readable ``empty`` view, a store where the reading
    belongs (its repair named: call ``ledger()`` on it first), a row
    the view carries that cannot be read or that contradicts its own
    count.  The finding itself never refuses: a named stratum holding
    no worlds is returned as the warning, never raised as an error.
    """
    names = _empty_strata(ledger)
    if not names:
        return None
    return EmptyStratumWarning(names)


def emit_empty_stratum_warning(ledger: Any) -> EmptyStratumWarning | None:
    """Emit the ``empty_stratum`` warning a reading warrants — feature
    286's sentence as one call.

    The emission: build the warning the reading warrants — through
    :func:`empty_stratum_warning`, the one spelling of the question —
    and, when there is one, hand it to :func:`warnings.warn`.  Returns
    what it emitted, ``None`` when nothing, so a caller that logs as
    well as warns holds one value for both.

    **Non-fatal by construction, and that is the point.**  The call
    returns whether or not the warning fired: the caller proceeds past
    an empty stratum — the promotion gate (feature 285) and the
    diversity verdict (289) are the callers that stop, and they stop on
    their own sentences — while the finding lands where Python's
    warning machinery puts it, visible by default, filterable by an
    operator, deduplicated per location.  ``stacklevel=2`` attributes
    the warning to *this call's caller* rather than to this module's
    line: a warning's location is its traceback, and the line an
    operator needs is the line that read the pool, not the line that
    reported it.

    A caller whose emission cannot be made honestly — no reading handed
    in, a store where the reading belongs, a carrier that disagrees with
    its own rows — is refused with
    :class:`~regime.errors.EmptyStratumWarningError` rather than
    silently warned nothing, because a caller that read the silence as
    *every stratum holds worlds* would be the blindness §C7's ledger
    exists to cure, reintroduced by the report.  Never re-reads the
    table behind the ledger it was handed, and writes nothing: a report
    is not a persist, and the table is exactly what it was whether the
    warning fired or not.
    """
    warning = empty_stratum_warning(ledger)
    if warning is not None:
        warnings.warn(warning, stacklevel=2)
    return warning
