"""The census that assigns each stored world a stratum — feature 290.

app_spec.xml, "Regime Coverage Strata", feature 290: *System rejects a
full-history regime fit, assigning each stored world to a stratum with the
causal rolling-window labeler.*  docs/alpha-engine-prd.md §C7 is the
doctrine the whole category serves — the replay pool grows monotonically
with calendar time, and *"run six months in low-vol chop and your entire
pool is low-vol chop"* — and the ledger feature 283's store persists is
the remedy's counting half.  This module is the half that makes the
number: it walks the pool's stored worlds, asks a labeler for each one's
stratum, and writes the counts through the store.  The PRD's leakage
table states the one law the sentence hangs its first clause on
(docs/alpha-engine-prd.md, "regime labeler"): *"Rolling-window fit only.
Fitting an HMM on full history and then finding that signal X works in
regime 2 is leakage, because regime 2 was labeled with future data."*

**Why the counting half needs its own copy of feature 58's law.**  The
labeler (:mod:`feature_store.regime_labeler`, feature 58) already refuses
a full-history fit at its own two seams — a ``window`` that is not a
finite positive integer at construction, a ``window`` at least as long as
the usable series at fit time.  But the census is a *third* seam, and a
seam the labeler cannot see: the census is where the labeler's output
becomes the ledger's input, the point at which a stratum stops being a
date's cluster and starts being a *count a promotion gate reads*
(§C7's block, feature 285).  A full-history fit that slipped through here
would not merely mislabel a date — it would stock the ledger with strata
carved by the pool's own future, so the coverage number that gates a
deployment would itself be leakage.  The census therefore states the law
again, in its own vocabulary, over the two things it can actually see:
the fit span the labeler *states* (its ``window``), and the span each
world *offers* (its usable feature rows).  What it cannot see is the
labeler's internals — whether a duck-typed labeler secretly fits the
whole series behind a stated window of 63 is feature 58's to police in
the labeler it built; this seam validates what it reads, the discipline
feature 228's conditioning seam states, and refuses a span it can name
rather than a motive it cannot.

**Both guards, in this member's words.**  A :class:`StratumAssignmentError`
opens with :data:`FULL_HISTORY_FIT_CODE` (``full_history_fit``) — the
greppable one word that names the refusal, the convention
``pool_frozen`` (feature 270) and ``illegal_theme`` (feature 241) already
follow — and fires in the two places feature 58's own guards do:

* **the configuration face** — a labeler whose ``window`` is ``None``
  (the spelling of an unbounded span, which *is* a full-history fit), or
  otherwise not a finite positive integer, is refused before any world is
  read.  A labeler that states no ``window`` at all is refused as the
  same face: at this seam a span that cannot be read and a span that is
  unbounded are indistinguishable, and the one thing the census must not
  do is guess.
* **the degeneracy face** — a ``window`` that spans all of a world's
  usable feature vectors would make the one fit behind that world's
  stratum a fit over its entire history, which is the full-history fit
  wearing a finite number; refused per world, naming the world and both
  numbers.

The refusal is deliberately **not** the labeler's
``FullHistoryFitError``.  :mod:`regime.errors` states the law for this
exact seam: the labeler refuses a fit (feature 58's vocabulary), the
member refuses in its own, and a caller's ``except StratumAssignmentError``
must not be defeated by another member's class it never imported — the
error-vocabulary rule every member seam in this workspace restates.  The
census also refuses *first*: the degeneracy face is checked against the
world's rows before the labeler is called, so the real labeler's own
guard never needs to fire through this path, and the cross-member suite
pins that the error a caller actually sees is this member's.

**The seam, and why everything on it is duck-typed.**  The workspace
contract is that no member imports another, so the labeler —
feature 58's — and the worlds — the replay pool's — arrive as the
caller's values, exactly as :mod:`regime.coverage` promised when it said
the count *"crosses between them as a value the caller carries."*  What
the census asks of each is the surface it calls through:

* a **labeler** carries ``k`` (the label space's size, checked against
  the vocabulary below), ``window`` (the fit span, the feature's whole
  subject) and ``label_features(rows)`` (the causal act itself — for
  each dated row, a cluster index or ``None`` where no trailing window
  was full).  Duck-typed rather than ``isinstance`` for the reason
  feature 184's question states: the module loader imports a member
  under a synthetic name and re-executes it, so the labeler a composed
  application serves is a *second* ``RegimeLabeler`` class object, and a
  type gate here would refuse the very labeler the composition seam
  hands out.
* a **world** carries ``world_id`` (the pool's own identity for it —
  ``bootstrap_world``'s key, the id ``replay_score`` joins on) and
  ``regime_rows`` (its dated regime feature vectors, in date order,
  every column finite — the usable rows :func:`feature_store.
  regime_labeler.regime_feature_matrix` builds from a panel; the
  panel-to-rows conversion is the feature store's, so the caller carries
  it across the seam as a value).  A bootstrap world — a seed's
  synthetic regression dataset — carries no market history, and the
  worlds this census bins are the ones that do: the replay epochs
  §C7's *"indexed by calendar time"* is about.

**One world, one stratum — and it is the closing one.**  The ledger
counts worlds, not world-days, so the census needs exactly one label per
world, and the honest one is the label of the world's **last dated
row**: every label the labeler answers is a date's regime judged by a
trailing-window fit ending at that date, so the final label is the
world's *closing* regime — the state its own history ends in, judged by
a fit that saw nothing after it.  A whole-series aggregate (the modal
label, a weighted vote) would be the census describing a world by a
statistic over its entire span, which is the full-history smell this
feature exists to refuse — the one number the census publishes must
itself be causal.  Determinism is free: no tie-break rule to state, no
arbitrary seed to trust, just the last of the labeler's own answers.

**The vocabulary is open, and it is checked against the label space.**
:data:`DEFAULT_STRATA` is the default vocabulary, and names outside it
are persisted as given — the openness :mod:`regime.coverage` argues from
the feature's own *"such as"* and ``0107``'s *"the migration stores
whatever names the plugin writes."*  What is refused is a vocabulary the
labeler's label space cannot be checked against: a count of names that
differs from ``k`` (a labeler carving four clusters would label worlds
no ledger stratum holds; a ledger naming two could not bin the third
cluster's worlds — the agreement ``packages/regime/tests/
test_cross_member.py`` pins from the data side), a duplicate name (the
ledger's identity is one row per name, and a vocabulary naming one twice
would count it twice), or a name that cannot be one (blank, non-text).
A label the labeler answers outside ``0 .. k-1`` is refused naming the
world — a label the vocabulary cannot name is a stratum no row holds.

**The count is the caller's, the persisting is the store's, and
validation is total before the first write.**  :func:`assign_strata` is
the pure half — worlds and a labeler in, one assignment per world out,
sorted by ``world_id`` (the pool's own total order), a pure function of
its inputs with no arithmetic of its own beyond counting.
:func:`census_coverage` is the persisting half: it assigns first, then
writes **one row per named stratum, zeros included** — §C7's example
ledger writes ``crash: 0``, and a vocabulary stratum no world landed in
is the named-empty row feature 286's warning fires on — in vocabulary
order, through :meth:`~regime.coverage.RegimeCoverage.record` on the
store it is handed, answering with the rows the table holds.  Because
every refusal the assignment can raise fires before the first write, a
refused census leaves the ledger untouched — the only failures that can
land mid-census are the store's own (an unspeakable address, a corrupt
row read back), and those propagate **unwrapped**: the persisting
half's refusals are the store's vocabulary, and re-wrapping a
:class:`~regime.errors.CoverageError` that already names its stratum
would put a second message in front of the one an operator needs.  A
re-run is idempotent by the store's own law (a re-issued count lands
the standing row), and a *lower* count is persisted, not refused — §C6's
excision removes worlds from the pool, and the census records what is
true now.

Stdlib only, and import-cheap: ``math``, ``collections`` and
``dataclasses``; no third-party import at module scope, so the factory's
scan — which imports this package to fire its ``@register`` — pays
nothing for the census, and a composed application that never counts
its pool never runs one.  The census registers no component of its own:
it is a function of evidence the factory does not hold (the worlds, the
labeler), which is the argument :mod:`regime`'s own docstring makes for
every feature in this category past the ledger.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from .coverage import DEFAULT_STRATA, CoverageCount, RegimeCoverage
from .errors import CoverageError, StratumAssignmentError

__all__ = [
    "FULL_HISTORY_FIT_CODE",
    "StratumAssignment",
    "assign_strata",
    "census_coverage",
]

#: The one word that opens every full-history refusal this census raises,
#: so the rejection is greppable by the name the feature's own sentence
#: gives it — the convention ``pool_frozen`` (feature 270) and
#: ``illegal_theme`` (feature 241) already follow in this workspace.  The
#: labeler's own module spells its refusal with a class name; this member
#: spells its with a code because the class a caller catches is this
#: member's, and the code is what an operator greps a log for.
FULL_HISTORY_FIT_CODE = "full_history_fit"


# -- Validation -------------------------------------------------------------------


def _validated_world_id(value: Any) -> str:
    """Return ``value`` as a world id, or refuse what cannot be one.

    Non-empty text, stripped — the pool's own key (``bootstrap_world``'s
    ``world_id``, the column ``replay_score`` joins on), and the same
    near-miss rule the ledger's stratum names take: an id with a trailing
    newline would be a *second* identity for one world against a census
    that must count each world exactly once.
    """
    if not isinstance(value, str) or not value.strip():
        raise StratumAssignmentError(
            f"a stored world's world_id must be non-empty text — got "
            f"{value!r} ({type(value).__name__}); the census counts each "
            "world once under the pool's own key, and a world that names "
            "itself with nothing cannot be counted (feature 290)"
        )
    return value.strip()


def _validated_strata(strata: Any, k: int) -> tuple[str, ...]:
    """Return ``strata`` as the vocabulary, or refuse what cannot be one.

    The set stays open — names outside :data:`DEFAULT_STRATA` are
    persisted as given, the openness the coverage store argues from the
    feature's own *"such as"*.  What is refused is a vocabulary the
    census cannot count into: a bare string (one name, not a vocabulary),
    a name that cannot be one, a duplicate (the ledger's identity is one
    row per name), and — the check that keeps the labeler's clusters and
    the ledger's rows the same count — a vocabulary whose length differs
    from the label space it is checked against.
    """
    if isinstance(strata, str) or not isinstance(strata, Iterable):
        raise StratumAssignmentError(
            f"the stratum vocabulary is a sequence of names — got "
            f"{strata!r} ({type(strata).__name__}); the census counts "
            "worlds into one name per cluster the labeler carves, and a "
            "single name is not a vocabulary to count into (feature 290)"
        )
    names = tuple(strata)
    seen: set[str] = set()
    for name in names:
        if not isinstance(name, str) or not name.strip():
            raise StratumAssignmentError(
                f"a stratum name must be non-empty text — got {name!r} "
                f"({type(name).__name__}); the ledger's identity is one "
                "row per named stratum, and a vocabulary that cannot name "
                "a row cannot have a world counted into it (feature 290)"
            )
        stripped = name.strip()
        if stripped in seen:
            raise StratumAssignmentError(
                f"the stratum vocabulary names {stripped!r} twice; the "
                "ledger's identity is one row per name, and a census "
                "counting into a repeated name would double-count every "
                "world that landed in it (feature 290)"
            )
        seen.add(stripped)
    if len(names) != k:
        raise StratumAssignmentError(
            f"the stratum vocabulary names {len(names)} strata and the "
            f"labeler carves {k}; the labeler's clusters are the strata "
            "the ledger counts worlds into, so the two must agree in "
            "number — a labeler carving four clusters would label worlds "
            "no ledger row holds, and a vocabulary naming two could not "
            "bin the third cluster's worlds (feature 290)"
        )
    return tuple(name.strip() for name in names)


#: Sentinel for "the attribute is absent" — a value the labeler cannot
#: legally carry (an ``int`` window is the only legal carrying type), so
#: ``getattr(labeler, "window", _NO_WINDOW)`` can tell *absent* apart
#: from a stated ``None``: the two are the same refusal, but the message
#: names which one it was.
_NO_WINDOW = object()


def _labeler_surface(labeler: Any) -> tuple[int, int, Any]:
    """Read the fit span and label space off the labeler, or refuse.

    The three things the census calls through — ``k``, ``window`` and
    ``label_features`` — read once, before any world is, so a labeler
    refused for its shape is refused before the census has asked it for
    a single stratum.  Duck-typed rather than ``isinstance`` for the
    reason feature 184's question states: the module loader imports a
    member under a synthetic name and re-executes it, so the labeler a
    composed application serves is a second class object of the same
    shape, and a type gate would refuse the very labeler the composition
    seam hands out.

    The ``window`` read is feature 290's configuration guard.  ``None``
    is refused as the full-history spelling before any type question,
    exactly as the labeler's own constructor refuses it — ``None`` names
    an unbounded span, and an unbounded span *is* a full-history fit.  A
    labeler with no ``window`` to read is refused as the same face: at
    this seam a span that cannot be read and a span that is unbounded
    are indistinguishable, and the one thing the census must not do is
    guess which one it was handed.
    """
    k = getattr(labeler, "k", None)
    if isinstance(k, bool) or not isinstance(k, int):
        raise StratumAssignmentError(
            "the census asks its labeler for the size of the label space "
            f"it carves — got {labeler!r} ({type(labeler).__name__}), "
            "whose ``k`` is not an integer; the vocabulary the census "
            "counts into is checked against that number, and a labeler "
            "that cannot state it cannot be checked (feature 290)"
        )
    if k < 2:
        raise StratumAssignmentError(
            f"the labeler's ``k`` must be at least 2, got {k}; a single "
            "regime is not a labelling — every date would carry the same "
            "stratum — and a census over one stratum would answer that "
            "the pool is covered by every world it holds (feature 290, "
            "restating the labeler's own construction law at this seam "
            "because the census reads the value off an object it did not "
            "construct)"
        )
    window = getattr(labeler, "window", _NO_WINDOW)
    if window is None:
        raise StratumAssignmentError(
            f"{FULL_HISTORY_FIT_CODE}: the labeler's fit window is "
            "``None`` — the spelling of an unbounded span, which is a "
            "full-history fit; a stratum assigned by a labeler that fit "
            "the whole series would be a cluster carved with the pool's "
            "own future in view, and the census refuses to count it "
            "(feature 290)"
        )
    if window is _NO_WINDOW:
        raise StratumAssignmentError(
            f"{FULL_HISTORY_FIT_CODE}: the labeler states no fit window "
            f"— got {labeler!r} ({type(labeler).__name__}), which has no "
            "``window`` to read; a span that cannot be read and a span "
            "that is unbounded are indistinguishable at this seam, and "
            "the census refuses both rather than guess which one it was "
            "handed (feature 290)"
        )
    if isinstance(window, bool) or not isinstance(window, int):
        raise StratumAssignmentError(
            f"{FULL_HISTORY_FIT_CODE}: the labeler's fit window must be "
            f"a finite positive integer — got {window!r} "
            f"({type(window).__name__}); the window is the whole subject "
            "of a causal rolling-window fit, and a span that is not a "
            "number of trailing rows is a span the census cannot vouch "
            "for (feature 290)"
        )
    if window < 1:
        raise StratumAssignmentError(
            f"{FULL_HISTORY_FIT_CODE}: the labeler's fit window must be "
            f"at least 1, got {window!r}; a non-positive window has no "
            "trailing span to fit on, and a labeler that fit on nothing "
            "would be naming a stratum rather than measuring one "
            "(feature 290)"
        )
    label_features = getattr(labeler, "label_features", None)
    if not callable(label_features):
        raise StratumAssignmentError(
            "the census asks its labeler to label each world's dated "
            f"rows — got {labeler!r} ({type(labeler).__name__}), which "
            "has no callable ``label_features``; a labeler that cannot "
            "label cannot assign a stratum, and a census that invented "
            "the assignment itself would be the full-history fit this "
            "feature refuses, wearing this member's name (feature 290)"
        )
    return k, window, label_features


def _validated_rows(rows: Any, world_id: str) -> tuple[tuple[float, ...], ...]:
    """Return ``rows`` as one world's usable feature vectors, or refuse.

    The contract the labeler's own ``label_features`` states for its
    argument — *"the usable feature vectors in date order (every column
    finite — the caller has already dropped the un-computable ones)"* —
    restated as a check, because the rows arrive as the caller's values
    across a seam this member cannot type-check.  A sequence (the
    labeler revisits the window at every date, so a one-pass iterable
    would be exhausted by the second date); every row a non-empty
    sequence of genuine finite real numbers, all the same width (the
    k-means zips each row against a centre, and a ragged or empty vector
    is not a point in the feature space); ``nan`` and infinities refused
    because a cluster index computed over a stand-in is a stratum
    wearing a number; ``bool`` refused because ``True`` is an ``int`` in
    Python, and a flag is not a volatility.
    """
    if isinstance(rows, (str, bytes)) or not isinstance(rows, Sequence):
        raise StratumAssignmentError(
            f"world {world_id!r} carries no usable regime feature rows — "
            f"got {rows!r} ({type(rows).__name__}); the labeler fits a "
            "k-means over each date's trailing window of rows, so the "
            "world's features arrive as a sequence in date order, and "
            "anything else is a world this census cannot bin (feature 290)"
        )
    if not rows:
        raise StratumAssignmentError(
            f"world {world_id!r} carries an empty regime history; a "
            "world with no dated feature rows has no trailing window to "
            "fit on and no closing regime to read, and a census that "
            "binned it would be naming a stratum rather than measuring "
            "one (feature 290)"
        )
    width: int | None = None
    for row in rows:
        if isinstance(row, (str, bytes)) or not isinstance(row, Sequence):
            raise StratumAssignmentError(
                f"world {world_id!r} carries a feature row that is not a "
                f"feature vector — got {row!r} ({type(row).__name__}); "
                "the labeler clusters points in the feature space, and a "
                "row of text or a bare number is not a point in it "
                "(feature 290)"
            )
        if width is None:
            width = len(row)
        elif len(row) != width:
            raise StratumAssignmentError(
                f"world {world_id!r} carries a ragged regime history — "
                f"rows of width {width} and width {len(row)}; the "
                "labeler's arithmetic pairs every row against a centre "
                "of one width, and a world of two widths is not a series "
                "in one feature space (feature 290)"
            )
        if width == 0:
            raise StratumAssignmentError(
                f"world {world_id!r} carries feature vectors with no "
                "features; a point in a space of no dimensions is every "
                "point at once, and a cluster over such points is a "
                "stratum the data did not draw (feature 290)"
            )
    if width is None:  # pragma: no cover - ``rows`` non-empty is checked above
        raise StratumAssignmentError(
            f"world {world_id!r} carries no rows to validate (feature 290)"
        )
    for row in rows:
        for cell in row:
            if isinstance(cell, bool) or not isinstance(cell, (int, float)):
                raise StratumAssignmentError(
                    f"world {world_id!r} carries a regime feature that is "
                    f"not a real number — got {cell!r} "
                    f"({type(cell).__name__}); the features are the "
                    "market's measured volatilities, and a value that is "
                    "not one is a stand-in wearing a cluster's "
                    "confidence (feature 290)"
                )
            if not math.isfinite(cell):
                raise StratumAssignmentError(
                    f"world {world_id!r} carries a regime feature that is "
                    f"not finite — got {cell!r}; the usable-row contract "
                    "drops un-computable values before they arrive, so a "
                    "nan or an infinity that survived it is a value "
                    "nobody computed, and a stratum read off it is a "
                    "number the market never printed (feature 290)"
                )
    return tuple(tuple(float(cell) for cell in row) for row in rows)


def _world_surface(
    world: Any, window: int
) -> tuple[str, tuple[tuple[float, ...], ...]]:
    """Read one world's identity and history, or refuse what it cannot give.

    The world seam is two attributes — ``world_id`` and ``regime_rows``
    — and nothing more, the discipline feature 189's labeling states:
    ask the surface the act needs, not the object that holds it.  The
    fit-span guard rides here, on the world that offered the span: a
    ``window`` that spans all the world's usable vectors makes the one
    fit behind its stratum a fit over its entire history, which is the
    full-history fit wearing a finite number, and it is refused here —
    before the labeler is called — so the refusal is this member's, in
    this member's vocabulary, naming the world it is about.
    """
    world_id = _validated_world_id(getattr(world, "world_id", None))
    rows = _validated_rows(getattr(world, "regime_rows", None), world_id)
    if window >= len(rows):
        raise StratumAssignmentError(
            f"{FULL_HISTORY_FIT_CODE}: the fit window spans all "
            f"{len(rows)} usable feature vectors of world {world_id!r} "
            f"(window={window}); a causal rolling-window labeler must "
            "fit on a trailing span strictly shorter than the series, "
            "never the world's whole history — the label behind this "
            "census's count would have been drawn with the pool's own "
            "future in view (feature 290)"
        )
    return world_id, rows


def _final_label(
    labels: Any, n_rows: int, world_id: str, k: int
) -> int:
    """Return the world's stratum index — the label of its last dated row.

    The one label the census keeps, per the module's argument: every
    label the labeler answers is a date's regime judged by a trailing
    fit ending at that date, and the last is the world's *closing*
    regime, the state its own history ends in, judged causally.  The
    answer is validated because a duck-typed labeler is a caller's
    object: a sequence parallel to the rows (the labeler's own
    contract), a genuine integer at the end (``None`` is the labeler's
    spelling of *no trailing window was full* — refused here because
    the census pre-checked that one was), inside the label space the
    vocabulary was checked against.
    """
    if isinstance(labels, (str, bytes)) or not isinstance(labels, Sequence):
        raise StratumAssignmentError(
            f"the labeler answered {labels!r} ({type(labels).__name__}) "
            f"for world {world_id!r}; ``label_features`` answers a "
            "sequence of labels parallel to the rows it was handed, and "
            "a census that read a stratum out of anything else would be "
            "reading one the labeler never assigned (feature 290)"
        )
    if len(labels) != n_rows:
        raise StratumAssignmentError(
            f"the labeler answered {len(labels)} labels for world "
            f"{world_id!r}'s {n_rows} dated rows; the labels are "
            "parallel to the rows or they are not the rows' labels, and "
            "a census that binned the world anyway would be choosing a "
            "stratum the fit did not name (feature 290)"
        )
    final = labels[-1]
    if final is None:
        raise StratumAssignmentError(
            f"world {world_id!r} ends with no stratum — the labeler "
            "answered ``None`` for its last dated row; the closing label "
            "is the one label this census keeps, and a world whose "
            "history never reached a full fit window has no closing "
            "regime to count (feature 290)"
        )
    if isinstance(final, bool) or not isinstance(final, int):
        raise StratumAssignmentError(
            f"the labeler answered {final!r} ({type(final).__name__}) as "
            f"world {world_id!r}'s closing label; a stratum index is a "
            "cluster the labeler carved, numbered — not a flag, not a "
            "name, not a fraction of a cluster (feature 290)"
        )
    if not 0 <= final < k:
        raise StratumAssignmentError(
            f"the labeler answered cluster {final} for world "
            f"{world_id!r}, outside the {k}-stratum label space the "
            "vocabulary was checked against; a label the vocabulary "
            "cannot name is a stratum no ledger row holds, and counting "
            "it would be publishing coverage the ledger cannot show "
            "(feature 290)"
        )
    return final


# -- The record -------------------------------------------------------------------


@dataclass(frozen=True)
class StratumAssignment:
    """One stored world, assigned to one named stratum — feature 290's noun.

    The two fields are the census's whole answer for one world: the
    pool's own identity for it, and the name the causal labeler's
    closing cluster was mapped into.  Frozen, for the same reason
    :class:`~regime.coverage.CoverageCount` is frozen: this value is the
    record of where a world was binned, and a caller who could edit it
    in memory could re-type the pool's coverage without touching the
    ledger the gates read.

    Validated in :meth:`__post_init__` rather than only through the
    census, because ``dataclasses.replace`` and unpickling both rebuild
    instances past a factory's nose — the argument
    :class:`~regime.coverage.CoverageCount` states for its own fields.
    """

    #: The world's identity — the pool's own key, stripped of nothing it
    #: did not already carry except surrounding whitespace.
    world_id: str
    #: The stratum's name — one of the vocabulary the census counted into.
    stratum: str

    def __post_init__(self) -> None:
        # ``object.__setattr__`` because the dataclass is frozen; the
        # strips below are normalization of the value into the record,
        # the only write this object ever takes.
        object.__setattr__(self, "world_id", _validated_world_id(self.world_id))
        object.__setattr__(self, "stratum", _validated_stratum_name(self.stratum))

    def row(self) -> dict[str, Any]:
        """The assignment as a mapping — a fresh dict per call.

        Keyed by the two field names, the discipline
        :meth:`~regime.coverage.CoverageCount.row` states: a rendered
        mapping names the same things the same way the record does.
        """
        return {"world_id": self.world_id, "stratum": self.stratum}

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"{type(self).__name__}(world_id={self.world_id!r}, "
            f"stratum={self.stratum!r})"
        )


def _validated_stratum_name(value: Any) -> str:
    """Return ``value`` as a stratum name — the ledger's own near-miss rule.

    A second spelling of :func:`regime.coverage._validated_stratum`'s
    check in this module's vocabulary, because the private helper is the
    store's to own and the rule is the same: non-empty text, stripped,
    nothing else normalised.
    """
    if not isinstance(value, str) or not value.strip():
        raise StratumAssignmentError(
            f"a stratum name must be non-empty text — got {value!r} "
            f"({type(value).__name__}); an assignment names a row of the "
            "ledger, and a name that states nothing names no row a world "
            "could be counted into (feature 290)"
        )
    return value.strip()


# -- The acts ---------------------------------------------------------------------


def assign_strata(
    worlds: Iterable[Any],
    labeler: Any,
    *,
    strata: Sequence[str] = DEFAULT_STRATA,
) -> tuple[StratumAssignment, ...]:
    """Assign each stored world a stratum — feature 290's pure half.

    The worlds in (each carrying ``world_id`` and ``regime_rows``), the
    causal labeler in (carrying ``k``, ``window`` and
    ``label_features``), one assignment per world out — sorted by
    ``world_id``, the pool's own total order, so the census is a pure
    function of the *set* of worlds it was handed rather than of the
    order they arrived in.  Each world's stratum is the label of its
    last dated row: its closing regime, judged by a trailing-window fit
    that saw nothing after it.

    Refuses, in this order, each naming what it is about:

    1. a labeler that cannot state its fit — no ``k``, a ``k`` the
       vocabulary cannot be checked against, a ``window`` that is
       ``None`` or absent or not a finite positive integer (the
       ``full_history_fit`` configuration face), no ``label_features``
       to call — and a vocabulary that cannot be counted into (a bare
       string, a name that cannot be one, a duplicate, a count that
       differs from the label space), all before any world is read;
    2. a world that cannot be binned — no ``world_id``, no usable
       ``regime_rows``, a fit window that spans its whole usable series
       (the ``full_history_fit`` degeneracy face), a label answer the
       vocabulary cannot name, or a ``world_id`` already assigned —
       naming the world it is about.

    Nothing is persisted and nothing is opened: the persisting half is
    :func:`census_coverage`, and a caller that wants only the
    assignments (a report, a dry run before the ledger is written) pays
    no database for them.
    """
    k, window, label_features = _labeler_surface(labeler)
    names = _validated_strata(strata, k)
    assignments: list[StratumAssignment] = []
    seen: set[str] = set()
    for world in worlds:
        world_id, rows = _world_surface(world, window)
        if world_id in seen:
            raise StratumAssignmentError(
                f"the census was handed world {world_id!r} twice; each "
                "stored world is counted exactly once — the pool's key "
                "is its identity, and a census that counted one world "
                "twice would report coverage the pool does not hold "
                "(feature 290)"
            )
        seen.add(world_id)
        index = _final_label(label_features(rows), len(rows), world_id, k)
        assignments.append(
            StratumAssignment(world_id=world_id, stratum=names[index])
        )
    return tuple(sorted(assignments, key=lambda assignment: assignment.world_id))


def census_coverage(
    worlds: Iterable[Any],
    labeler: Any,
    store: RegimeCoverage | Any,
    *,
    strata: Sequence[str] = DEFAULT_STRATA,
) -> tuple[CoverageCount, ...]:
    """Count the pool into the ledger — feature 290's persisting half.

    :func:`assign_strata`'s act, then one :meth:`~regime.coverage.
    RegimeCoverage.record` per named stratum, **zeros included**, in
    vocabulary order — §C7's example ledger writes ``crash: 0``, the
    named-empty row feature 286's warning fires on, and a vocabulary
    stratum no world landed in is exactly that state.  The answer is
    the rows the table holds, read back by the store, the discipline
    every write in this member states: the row is the record.

    Because every refusal the assignment can raise fires before the
    first write, a refused census leaves the ledger untouched — a
    world that cannot be binned is discovered with the ledger exactly
    as it was, and the census can be re-run once the ask is corrected.
    The only failures that can land mid-census are the store's own (an
    address it cannot speak, a row too corrupt to read back), and those
    propagate **unwrapped**: a :class:`~regime.errors.CoverageError`
    already names the stratum and the fact, and the census does not put
    a second message in front of the one an operator needs.  An object
    with no ``record`` to call is refused in the store's vocabulary for
    the same reason — it is a fault about the store, not about the
    assignment.

    A re-run is idempotent by the store's own law, and a *lower* count
    is persisted, not refused: §C6's excision removes worlds from the
    pool between censuses, and the ledger records what is true now.
    """
    names = _validated_strata(strata, _labeler_surface(labeler)[0])
    record = getattr(store, "record", None)
    if not callable(record):
        raise CoverageError(
            "the census writes its counts through the coverage store — "
            f"got {store!r} ({type(store).__name__}), which has no "
            "callable ``record``; the counts it makes are ledger rows, "
            "and an object that cannot persist one is not a ledger to "
            "write them into (feature 290)"
        )
    assignments = assign_strata(worlds, labeler, strata=strata)
    counted = Counter(assignment.stratum for assignment in assignments)
    return tuple(record(name, counted.get(name, 0)) for name in names)
