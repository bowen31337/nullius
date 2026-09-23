"""The promotion block on coverage — feature 285.

app_spec.xml, "Regime Coverage Strata", feature 285: *System rejects a
promotion when the target deployment regime has coverage below the
configured threshold.*  Its declared parent is feature 284 — the ledger
read — and the dependency is the whole shape, the same one feature 289's
verdict and feature 286's warning take: the promotion is judged over a
*reading*, the very :class:`~regime.ledger.CoverageLedger`
:meth:`~regime.coverage.RegimeCoverage.ledger` answers with, and this
module adds to that reading the one act it declines to perform itself.
docs/alpha-engine-prd.md §C7 states the rule the sentence exists to
enforce, and states it as an action taken at the door: *"**Block
promotion** when the regime being deployed into has coverage below
threshold."*  §14's risk table files the hazard that rule answers as
**High** — *"Replay pool is regime-monotone"* — with *"§C7 coverage
ledger with promotion block"* as its stated mitigation, so this module
is the *block*: the ledger feature 283 writes and feature 284 reads,
standing in front of a deployment.

**One stratum's count, not the ledger's shape — the difference from
feature 289.**  :mod:`regime.diversity` and this module are the
category's two judgements over the same reading, and their figures are
different questions.  Feature 289 asks *is the pool spread across
regimes?* and its figure is how many strata hold at least one stored
world — the reading's own :attr:`~regime.ledger.CoverageLedger.covered`
view.  This feature asks *is the regime I am about to deploy into
covered?* and its figure is the stored-world count of **one named
stratum**.  Neither view substitutes for the other and the mistake is
not symmetric: a pool covered across :data:`~regime.coverage.
DEFAULT_STRATA` whole, with the target regime holding none of them,
passes feature 289's claim and is exactly the deployment §C7 says to
block.  So the covered view is *not* this module's figure, ``len`` is
not (naming a stratum is not covering it), the sum of the counts is not
(worlds in *other* regimes are not worlds in this one), and the target's
count is read through the reading's own one-stratum lookup — the verb
:mod:`regime.coverage` reserved for this feature when it wrote that its
``get`` *"exists for the write's read-back and for the caller that holds
one stratum's name (a promotion gate asking after its deployment regime,
feature 285)"*.

**The named-empty row and the never-named absence, kept apart — again,
and here it costs a promotion.**  ``0107`` detail 1 is the load-bearing
distinction under every read in this member, and this seam is where
collapsing it would be most expensive.  A target regime *named and
holding no worlds* is §C7's ``crash: 0``: a row, a count of zero, and a
coverage finding — the promotion is blocked on the *count*.  A target
regime *nobody named* has no row at all: nobody has counted it, so its
coverage is **unknown**, and reporting an unknown as a zero would be
inventing a finding.  The two are therefore refused with different
messages in the one class — the first names the figure and the
threshold, the second names the absence — because their repairs differ:
the first needs *worlds in that regime*, the second needs the stratum
*counted*.  Both are the census's acts (feature 290) and the backfill's
(feature 287); the refusal says so.

**Why one class and not two faces split as feature 289 splits them.**
Feature 289 gathers an *ask* face and a *verdict* face in one class, and
:class:`~regime.errors.CoverageError` gathers three faces for a reason
written down in :mod:`regime.errors`: *"the caller's position is the
same in all three cases."*  That reasoning governs here more than
anywhere else in the member, because this feature's caller is a **gate**
and a gate's one failure mode is silence.  A design that raised a
separate class for a malformed threshold would let a caller whose single
``except PromotionCoverageError`` guards its promotion path miss it —
and the promotion would proceed through the hole.  Every face this
module refuses is therefore a :class:`~regime.errors.
PromotionCoverageError`, ordered so the cheapest check comes first and
each message names what it is about: the reading, the target regime, the
threshold, the absence, the verdict.

**Every face is typed — and that is a boundary, not a blanket.**  The
gathering above is about refusals *the gate itself* makes, and the seam
is written so that no shape of ask or of reading can escape it as a bare
``TypeError``: a reading whose one-stratum lookup takes only a name
(feature 283's own store carries that signature), one that answers by
subscript, and one that answers *no row* by raising ``KeyError`` are all
asked the way they can answer, because an untyped error out of a gate is
the hole the caller's single ``except`` walks through.  What the gate
deliberately does **not** do is widen its ``except`` to ``Exception``: an
error the reading raises out of its own internals — a broken connection,
a bug in a labeler — propagates unwrapped, because laundering it into
this class would be the same silence one layer down.  A caller would read
*the promotion was blocked* where the truth is *the ledger could not be
read*, and the repair for that is not a decision about evidence.  The
member's other seams draw the line in the same place.

**The threshold is required, and it is the deployment's number.**  The
sentence names the figure as *"the configured threshold"* and spells no
number, so the keyword is **required with no default** — the shape
feature 261's ``switch_cost`` takes — and a default here would be this
module legislating a coverage floor no deployment configured, which is
§C7's blindness legislated back in through the configuration.  (Feature
289's floor *may* default because its sentence spells the three; this
sentence spells nothing.)  The comparison is the sentence's own word:
the promotion is rejected when coverage falls *below* the threshold, so
at exactly the threshold it stands and there is no upper edge — the
asymmetry a power floor has, and what a coverage threshold means.

Zero is refused for the same reason 289 refuses a floor of zero:
``world_count >= 0`` is true of every count a ledger can hold, so a
threshold of zero admits every promotion — including one into a regime
holding no worlds at all — which is the exact block §C7 asks for,
legislated away through the configuration.  A one-world threshold is
*degenerate* but honest (it still blocks an uncovered regime, and the
named-empty row below it) and is not this module's to refuse.

**The refusal raises, and that is the point.**  A promotion that clears
the threshold returns ``None``; one that does not **raises**
:class:`~regime.errors.PromotionCoverageError`, because the shape that
blocks a deployment is the caller calling this on its last line — the
stop has to be the function's own act, not a boolean every caller must
remember to branch on, and the caller that forgets is precisely the
monotone-pool promotion §C7 exists to block.

**The verdict rules on the reading it was handed.**  The judgment does
not re-read the table behind the ledger's back: §C6's tripwires excise
worlds, the census and the backfill land counts, and another process may
have moved the pool since the caller took its reading.  A promotion
judged over a stale reading gets that reading's verdict — the honest
behaviour for a caller that *publishes over what it read* — and the
caller deploying *now* reads again and judges the new reading.  The
suite pins both halves.  It writes nothing: a verdict is not a persist,
and the table is exactly what it was whether the promotion stands or
falls.

**The seam is the reading, and it is duck-typed.**  The judgment takes
the ledger value — reached through either of feature 284's spellings,
:meth:`~regime.coverage.RegimeCoverage.ledger` for the caller that holds
a store, :func:`~regime.ledger.read_ledger` for the caller that holds a
URL — and never the store itself.  A store handed in by mistake is
refused with its repair named — read first, then judge — the same refusal
the diversity and warning seams make and for the same reason.  The
reading is duck-read on its one-stratum lookup rather than
``isinstance``-gated, because the module loader imports each member under
a synthetic name and the ledger a composed store hands back is
structurally identical to a direct import's without being the same class
object; a type gate would refuse the very reading composition serves.
What is read is validated — the target's name through feature 283's own
validator and its count through feature 283's own count validator, both
imported rather than re-written, with their
:class:`~regime.errors.CoverageError` translated into this module's class
at the seam so a caller's ``except PromotionCoverageError`` is never
defeated by the count-persist vocabulary for an act that persisted
nothing.

**No component, no table, no seat, no router.**  The member's registered
surface stays feature 283's one store.  A block over a reading resolves
no configuration of its own and composes nothing; feature 283's builder
is the member's only ``@register``, and :mod:`app.modules.regime` still
answers one question.  The promotion plugin's own features (291–300,
including 299's *persisting a blocking reason*) are another member's, and
they reach this refusal the way every cross-member seam in this workspace
is reached — by restating the code word, which is what
:data:`COVERAGE_BELOW_THRESHOLD_CODE` is for.

**Stdlib only, and import-cheap.**  No ``sqlite3``, no third-party import
at module scope, so the factory's scan imports this package for the same
near-nothing it always did and a blocked promotion costs its caller
nothing but the reading it already held.
"""

from __future__ import annotations

from typing import Any

from .coverage import _validated_stratum, _validated_world_count
from .errors import CoverageError, PromotionCoverageError

__all__ = [
    "COVERAGE_BELOW_THRESHOLD_CODE",
    "rejects_undercovered_promotion",
]

#: The one word that names the finding — ``coverage_below_threshold`` —
#: opening every verdict this module raises so it is greppable by the word
#: an operator would search for, the convention ``pool_too_thin`` (feature
#: 275), ``full_history_fit`` (290), ``no_origin`` (288),
#: ``not_regime_diverse`` (289) and ``empty_stratum`` (286) already follow
#: in this workspace.  The word names the *finding*, not the act: the
#: promotion pointed at a regime, and the pool does not cover it.  The
#: promotion plugin's own features (291–300) restate this literal rather
#: than import it — no member imports another — and feature 299's
#: *blocking reason* is the persisted record of exactly this finding.
COVERAGE_BELOW_THRESHOLD_CODE = "coverage_below_threshold"

#: The sentinel :func:`rejects_undercovered_promotion` passes as the
#: default of the reading's own lookup, so *the ledger holds no row for
#: this regime* is distinguishable from *the row says zero*.
#:
#: The distinction is ``0107`` detail 1 and it is load-bearing here: a
#: regime named and holding no worlds is §C7's ``crash: 0`` — a coverage
#: finding the promotion is blocked on — while a regime nobody named has
#: never been counted, and its coverage is *unknown*.  A plain ``None``
#: default would work against every lookup this workspace ships, and is
#: deliberately not used: a ledger whose answer for an absent row was
#: itself ``None`` would turn an unknown into an absence of answer, and
#: the two refusals below could not be told apart.  An object identity
#: no row can carry is the only spelling that cannot be forged by data.
_ABSENT: Any = object()


def _validated_threshold(threshold: Any) -> int:
    """Check that ``threshold`` is a count of worlds, or refuse it.

    The one spelling of what the threshold must be, shared by
    :func:`rejects_undercovered_promotion`.  A coverage threshold is a
    count of *stored worlds* — the unit §C7's ledger is drawn in — so it
    is a positive whole number, and a value that is not one would
    silently admit or block a promotion on a number that is not a count
    of anything.  A ``bool`` is refused where a count belongs, for the
    reason every count validator in this workspace refuses one: ``True``
    is ``1`` in Python, so a flag where a threshold belongs would read as
    the weakest possible coverage bar, which is not what a caller
    passing a flag meant.

    Zero is refused rather than allowed, and this is the one count in the
    member where zero is refused from below rather than from *at*: a
    coverage threshold of zero is ``world_count >= 0``, which is true of
    every count a ledger can hold, so it admits every promotion —
    including one into a regime holding no worlds at all.  That is the
    exact block §C7 asks for legislated away through the configuration,
    the same argument :func:`regime.diversity._validated_floor` makes for
    a diversity floor of zero.  A threshold of one is *degenerate* but
    honest (it still blocks an uncovered regime) and is not this module's
    to refuse.
    """
    if isinstance(threshold, bool) or not isinstance(threshold, int):
        raise PromotionCoverageError(
            f"{COVERAGE_BELOW_THRESHOLD_CODE}: the coverage threshold is a "
            f"count of stored worlds — got {threshold!r} "
            f"({type(threshold).__name__}); feature 285's sentence blocks a "
            "promotion when the target deployment regime's coverage falls "
            "below the configured threshold, and a value that is not a "
            "whole number names no threshold a promotion can be judged "
            "against (a truthy flag is not a count of worlds, and a "
            "fractional world is not a world)"
        )
    if threshold < 1:
        raise PromotionCoverageError(
            f"{COVERAGE_BELOW_THRESHOLD_CODE}: the coverage threshold is at "
            f"least one stored world — got {threshold!r}; a threshold below "
            "one admits every promotion, including one into a regime "
            "holding no worlds at all, and the one thing §C7's promotion "
            "block exists to stop is a deployment into a regime the pool "
            "does not cover"
        )
    return threshold


def _target_regime(regime: Any) -> str:
    """Return ``regime`` as the target stratum's name, or refuse what is not.

    The feature's own sentence says *the target deployment regime*, so the
    judgment's second argument is a stratum name and nothing else — a
    labeler's configuration value, read from whatever the promotion
    carries.  The check is feature 283's own validator, imported rather
    than re-written, so the gate cannot drift from the writer on what a
    stratum is: a name the ledger could never hold is a name no row was
    ever written under, and refusing it *here* means the caller learns its
    target is not a stratum rather than that the ledger happens not to
    have counted one.  The refusal is translated into this module's class
    at the seam so a caller's ``except PromotionCoverageError`` is never
    defeated by the count-persist vocabulary for an act that persisted
    nothing.
    """
    try:
        return _validated_stratum(regime)
    except CoverageError as exc:
        raise PromotionCoverageError(
            f"{COVERAGE_BELOW_THRESHOLD_CODE}: the target deployment regime "
            f"is a stratum name — got {regime!r} ({type(regime).__name__}); "
            "feature 285's sentence blocks a promotion on the coverage of "
            "the regime being deployed into, and a target that is not a "
            f"name names no stratum whose coverage could be read: {exc}"
        ) from exc


def _reading(ledger: Any) -> Any:
    """Return ``ledger``'s one-stratum lookup, or refuse what carries none.

    The judgment's first check, so the caller learns which of its three
    arguments the gate cannot get past — an object that is not a reading
    cannot be asked about any regime or threshold, and refusing it last
    would report a malformed threshold about a call whose real problem is
    that nothing handed it a ledger.

    Duck-typed rather than ``isinstance``-gated (the loader's
    synthetic-name copies make ``isinstance`` refuse the very reading
    composition serves), and the store's read verb is checked **first** —
    which is where this seam differs from its siblings and why the order
    is load-bearing.  Feature 283's store carries a one-stratum read of
    its own (:meth:`~regime.coverage.RegimeCoverage.get`, the write's
    read-back for a caller *holding a name*), so checking for a lookup
    before checking for the store would accept a live store here and then
    ask it a two-argument question it does not answer.  The store is
    therefore identified the way every sibling seam identifies it — by the
    read verb it alone carries — and refused *by its repair*: call
    ``ledger()`` on it first and hand the judgment the fixed reading that
    answers with, because a verdict over a live store is a verdict about a
    pool that can move under it.  Only then is the reading's own lookup
    read, and it is the *Mapping*-shaped one: a reading answers for a name
    the ledger does not hold the way a mapping does, which is what lets
    this module tell *the row says zero* from *there is no row*.

    The lookup is returned as one wrapper whatever shape it arrived in, so
    the caller below never has to know which it was handed and *no shape
    of reading can escape this gate as a bare* ``TypeError`` — a
    two-argument question asked of a one-argument ``get`` (feature 283's
    own store signature) is asked the way it can answer, a subscript-only
    reading is asked by subscript, and a reading that answers *no row* by
    raising ``KeyError`` has that read as the absence rather than
    propagated.  That third case is a mapping-shaped reading's own right —
    it is what ``__getitem__`` does — and the whole point of the wrapper.
    Errors the lookup raises out of its own internals are *not* caught:
    those propagate, per the module docstring's boundary.
    """
    if callable(getattr(ledger, "ledger", None)):
        raise PromotionCoverageError(
            f"{COVERAGE_BELOW_THRESHOLD_CODE}: a promotion is judged over a "
            f"reading, and {ledger!r} is the store — call its ``ledger()`` "
            "verb (feature 284's read, either spelling) and hand the "
            "judgment the CoverageLedger it answers with; a verdict over a "
            "live store would be a verdict about a pool that can move "
            "under it"
        )
    if isinstance(ledger, (str, bytes)):
        raise PromotionCoverageError(
            f"{COVERAGE_BELOW_THRESHOLD_CODE}: a promotion is judged over a "
            f"coverage ledger — got {ledger!r} ({type(ledger).__name__}); a "
            "string is not a reading of anything, and the reading feature "
            "284's verb answers with is the evidence the promotion is "
            "blocked on"
        )
    lookup = getattr(ledger, "get", None)
    if callable(lookup) or hasattr(ledger, "__getitem__"):
        # One spelling of the lookup, whatever the reading answers with.
        # A reading that answers by subscript rather than by ``get`` is
        # still a reading — the same question, with ``KeyError`` as the
        # mapping protocol's own spelling of *no row for that name*, which
        # is the absence this module keeps apart from a zero — and a
        # reading whose ``get`` takes only a name (feature 283's own store
        # carries exactly that signature, for the caller holding a name) is
        # still askable.  The wrapper exists so the caller below never has
        # to know which shape it was handed, and so a lookup that refuses
        # the sentinel argument is asked the way it *can* answer rather
        # than crashing through this gate as an untyped ``TypeError`` — the
        # one outcome a gate must not have, because the caller's single
        # ``except PromotionCoverageError`` would not catch it and the
        # promotion would proceed through the hole.
        def _by_name(name: str, default: Any = _ABSENT) -> Any:
            if callable(lookup):
                try:
                    return lookup(name, default)
                except TypeError:
                    # A one-argument ``get``: ask it the way it answers,
                    # and read its own *no row* answer (``None``, or a
                    # raised ``KeyError``) as the absence the judgment
                    # reports.  Feature 283's store is the shape this
                    # covers.
                    try:
                        found = lookup(name)
                    except KeyError:
                        return default
                    return default if found is None else found
                except KeyError:
                    # A ``get`` that answers *no row* by raising, which a
                    # mapping-shaped reading is entitled to do (it is what
                    # ``__getitem__`` does, and a reader that implemented
                    # ``get`` as a thin wrapper over one would inherit it).
                    return default
            try:
                return ledger[name]
            except KeyError:
                return default

        return _by_name
    raise PromotionCoverageError(
        f"{COVERAGE_BELOW_THRESHOLD_CODE}: a promotion is judged over a "
        f"coverage ledger — got {ledger!r} ({type(ledger).__name__}), which "
        "cannot be asked for one stratum's row; the reading feature 284's "
        "verb answers with is the evidence the promotion is blocked on, and "
        "something that is not that reading names no coverage to judge"
    )


def _target_count(lookup: Any, regime: str) -> Any:
    """Read the target regime's count through ``lookup``, or say it is absent.

    The verdict's whole evidence, gathered in one place: the stored-world
    count the reading holds for one named stratum.  It is read through the
    reading's **own** one-stratum lookup rather than re-derived from
    ``rows``, because that lookup is the ledger's named spelling of
    exactly this question and a judgment that walked the rows itself would
    be the drift the verb exists to prevent — and because ``rows`` is not
    even required to be present on a duck-typed reading, while the lookup
    is the seam this module documents.

    Two answers, each kept distinct on purpose:

    * **the absence** — the reading holds no row for the regime, answered
      as :data:`_ABSENT` rather than refused here, because *never named*
      is a finding about the pool this module refuses in its own words a
      line further on, with the repair the caller needs.  Returning it as
      a value keeps the two faces apart in the caller's message instead of
      collapsing them into a lookup default.
    * **the count** — a row it *did* find goes through feature 283's own
      count validator, imported rather than re-written, so a corrupt
      stored ``world_count`` is refused rather than compared.  SQLite's
      columns are dynamically typed, so a raw ``INSERT`` from another tool
      can land anything in this table; a gate that compared it would
      admit or block a deployment on a number nobody wrote.  The refusal
      names the regime and the cause, translated into this module's class
      at the seam.
    """
    found = lookup(regime, _ABSENT)
    if found is _ABSENT:
        return _ABSENT
    try:
        return _validated_world_count(getattr(found, "world_count", None))
    except CoverageError as exc:
        raise PromotionCoverageError(
            f"{COVERAGE_BELOW_THRESHOLD_CODE}: the ledger's row for "
            f"{regime!r} could not be read as a coverage count: {exc}"
        ) from exc


def rejects_undercovered_promotion(
    ledger: Any,
    *,
    regime: Any,
    threshold: int,
) -> None:
    """Refuse a promotion the target regime's coverage does not carry.

    The one judgment for feature 285's sentence: a coverage ledger, the
    stratum being deployed into, and the deployment's own threshold in —
    and either the promotion proceeds or it is refused.  It decides
    whether the target deployment regime's stored-world count reaches the
    configured threshold — *"rejects a promotion when the target
    deployment regime has coverage below the configured threshold"* — and
    **raises** :class:`~regime.errors.PromotionCoverageError` when it does
    not, so the caller that calls it on its last line is stopped before
    the promotion is published.  A promotion into a regime whose coverage
    meets the threshold returns without raising — at exactly the
    threshold it stands, because the sentence rejects *below*, and there
    is no upper edge: more worlds in the target regime only strengthen
    the case for deploying into it.

    The figure is the **target stratum's own count**, honored through the
    reading's one-stratum lookup.  Deliberately not feature 289's figure:
    that judgment's ``covered`` view counts *how many strata hold worlds*,
    a pool covered across three regimes one of which is not the target
    passes it, and deploying into the uncovered one is exactly what §C7's
    block exists to stop.  Deliberately not ``len(ledger)`` (naming a
    stratum is not covering it) and deliberately not the sum of the counts
    (worlds in other regimes are not worlds in this one — §C7's opening
    sentence is a pool that is *entirely* one regime, and a target regime
    holding none of it is the unresolvable case).

    ``threshold`` is required and has no default: the sentence names
    *"the configured threshold"* and spells no number, so the number
    belongs to the deployment and a default here would be this module
    inventing a coverage floor nobody configured.

    The judgment rules on the reading it was handed and never re-reads the
    table behind it: a promotion over a stale reading gets that reading's
    verdict, and the caller deploying *now* reads again and judges the new
    reading.  It writes nothing — a verdict is not a persist, and the
    table is exactly what it was whether the promotion stands or falls.

    Refuses, in this order, each naming what it is about:

    1. a ledger carrying no readable one-stratum lookup — nothing handed
       in, a string, an object that cannot be asked; a store handed in
       where the reading belongs is refused with its repair named (call
       ``ledger()`` on it first — feature 284's verb);
    2. a ``regime`` that is not a stratum name — the target deployment
       regime has to be a name the ledger could have been written under;
    3. a ``threshold`` that is not a positive whole count of worlds — a
       threshold below one admits every promotion, which is the block this
       feature exists to keep shut;
    4. the target regime **absent from the ledger** — no row at all, so
       nobody has counted it and its coverage is unknown rather than zero.
       Refused separately from the verdict below because the repair
       differs: this regime has to be *named*, which is the census's act;
    5. the verdict — the target regime's stored-world count falls below
       the threshold, refused with a message that opens with
       ``coverage_below_threshold``, states the figure, the regime and the
       threshold, names §C7, and states the repair: grow the coverage in
       the regime being deployed into, or deploy into a regime the pool
       does cover — the census (feature 290) and the backfill
       (feature 287) are the acts that do the first.
    """
    # The reading's shape is checked first, so the caller is told which of
    # its three arguments is the gate's problem: an object that is not a
    # reading cannot be asked about any regime or threshold, and refusing
    # it last would report a malformed threshold about a call whose real
    # problem is that nothing handed it a ledger.
    lookup = _reading(ledger)
    target = _target_regime(regime)
    minimum = _validated_threshold(threshold)
    count = _target_count(lookup, target)
    if count is _ABSENT:
        raise PromotionCoverageError(
            f"{COVERAGE_BELOW_THRESHOLD_CODE}: the target deployment regime "
            f"{target!r} is not named by the ledger — no row holds a count "
            "for it, so its coverage has never been counted and is unknown "
            "rather than zero; docs/alpha-engine-prd.md §C7's ledger keeps a "
            "regime named and holding no worlds (``crash: 0``, a count of "
            "zero) apart from a regime nobody named (no row at all), and a "
            "promotion blocked on an unknown would be inventing a figure "
            "the pool never produced. Name the stratum and count it: the "
            "census (feature 290) assigns stored worlds to strata and "
            "writes the count, and the backfill (feature 287) replays "
            "stored trees against epochs they never saw to bring worlds "
            "into it"
        )
    if count >= minimum:
        return
    raise PromotionCoverageError(
        f"{COVERAGE_BELOW_THRESHOLD_CODE}: the target deployment regime "
        f"{target!r} holds {count} stored "
        f"{'world' if count == 1 else 'worlds'}, below the configured "
        f"coverage threshold of {minimum}; docs/alpha-engine-prd.md §C7 "
        "blocks a promotion when the regime being deployed into has "
        "coverage below threshold, because the replay pool grows monotone "
        "with calendar time — run six months in low-vol chop and your "
        "entire pool is low-vol chop, the meta-policy learns a "
        "chop-optimal search policy, and you find out when the regime "
        "breaks. Grow the coverage in the regime being deployed into, or "
        "deploy into a regime the pool does cover: the census (feature "
        "290) assigns stored worlds to strata and writes the count, and "
        "the backfill (feature 287) replays stored trees against epochs "
        "they never saw — and the promotion stands over the reading that "
        "follows"
    )
