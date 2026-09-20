"""Persisting the perturbation-stability figures — feature 129's persistence half.

app_spec.xml, "Leakage Tripwires", feature 129: *"System re-runs a candidate
against a 20 percent universe subsample, persisting the subsample stability
figure."*  :mod:`tripwires.subsample` states the figure; this module is where it
becomes a fact about the node.  Feature 127's sentence (*"rejects the node when
degradation exceeds the configured threshold"*) names no persistence at all, and
the contrast is the point: 127 hands its verdict to feature 131, while this
feature's own sentence says *persisting*, so the write is this feature's.

**Why a table of its own, and why the primary key is the whole design.**
``node.perturb_stability`` exists — 0114 creates it, feature 130's sentence is
*"persisting perturbation_stability as a node metric"* — and this module
deliberately does **not** write it.  The reason is that §C6 declares *four*
perturbation axes (a different seed, a different window offset, a different
universe subsample, a different lookback) and a single ``REAL`` column holds
one number: whichever axis ran last would overwrite the others, and an operator
asking *which perturbation moved this candidate?* would be reading the
scheduler's order rather than the candidate's behaviour.  So
:data:`~tripwires.layout.STABILITY_TABLE` is keyed by ``(node_id, axis)`` — one
row per node per perturbation, the four figures comparable side by side — and
the node column stays feature 130's to fill, exactly as 0114's own docstring
leaves it.

**Accepting a passing verdict is the feature, not a loosening of it.**  Feature
131's store refuses a verdict that did not reject, and rightly: there is nothing
to poison, and a mark on a branch that passed would excise scores nothing
condemned.  This store is the opposite case and the *reason* the spec's sentence
says persist rather than reject.  A stability figure is the input to a triage
decision — feature 134 computes the AUC of this family separating planted nulls
from real signals — and an AUC needs both classes: a store that kept only the
rejections would leave every figure that was *supposed* to be small out of the
data the triage number is computed from, and the discriminator would be trained
on the tail it is meant to detect.  So a passing verdict is written, with
``rejected = 0``, and that is the row the triage reads.

What the store refuses is a verdict that disagrees with itself.  The record's
own constructor enforces that already (``stability`` recomputes from the two
statistics and the bar, ``stability_rejected`` is the comparison the configured
bar makes, ``rejected`` is the disjunction of the three causes), so the check
here is *structural* — by the field names, for the reason feature 131's own
validator gives at length: the factory's scan imports this member twice, so
``isinstance`` cannot hold across the two copies of one source file — plus the
one thing a persistence feature must not take on trust, which is that the
outcome word is the verdict's own translation of its bit.  A hand-built record
claiming ``rejected=True`` beside ``outcome="ok"`` would classify a pass at the
ledger as a failure, and a row is what survives the in-memory value.

**Stdlib only, and import-cheap.**  ``sqlite3``, ``datetime`` and the same
``urllib.parse`` translation every store in this member uses; no third-party
import at module scope, so the factory's scan — which imports this package to
fire its ``@register`` — pays nothing for this module.  Construction performs no
I/O (the path is resolved on first use), so composing an application never opens
a database.

**What this module does not do.**  It does not re-run anything (that is
:mod:`tripwires.subsample`, a pure function of mappings that carries no store),
poison a subtree (131), excise a pool (132), or write the node column feature
130 owns.  It writes one row per ``(node_id, axis)`` and reads it back.
"""

from __future__ import annotations

import datetime as dt
import math
import os
import sqlite3
from collections.abc import Mapping, Sequence
from contextlib import closing
from pathlib import Path
from typing import Any

from .errors import TripwirePoisonError, TripwireStabilityError
from .layout import (
    DATABASE_URL_ENV,
    STABILITY_COLUMNS,
    dialect_of,
    node_bootstrap_schema,
    parsed_instant,
    sqlite_path,
    stability_bootstrap_schema,
    validated_instant,
    validated_node_id,
)
from .seed_rerun import PERTURBATION_STABILITY_NAME
from .subsample import SubsampleRerunVerdict, subsample_figure

__all__ = [
    "COMPONENT_NAME",
    "STABILITY_TABLE",
    "StabilityRecord",
    "StabilityStore",
    "record_stability",
    "stability_of",
]

#: The component name this member registers its stability store under — a
#: fourth name rather than a fourth component under ``"tripwires"``, the
#: convention :mod:`tripwires.poison` states for its own: the probe answers
#: *what is the composed tripwire suite?* while this answers *what is the
#: composed store a stability figure is persisted to?*, and a caller asking for
#: one must not be handed the other.
COMPONENT_NAME = "tripwires-stability"

#: The table this store writes — restated from :mod:`tripwires.layout` where its
#: DDL lives, so the store and the bootstrap cannot drift apart on the name.
STABILITY_TABLE = "tripwire_stability"

#: The fields a persistence feature reads off a verdict, checked **structurally**
#: rather than by ``isinstance``.  This is a *different* list from feature 131's
#: ``_VERDICT_FIELDS``, and that is the seam rather than an oversight: the two
#: stores persist two different records, and a list shared between them would
#: have to be the union — which is precisely the check that would let a
#: time-shuffle verdict through here, or a subsample re-run through there.
#:
#: ``node_id``, ``tripwire``, ``axis``, ``rejected`` and ``outcome`` are the
#: identity and the decision; the rest are the terms the row carries so the
#: figure is re-derivable from it.  ``stability`` and ``stability_threshold``
#: are named rather than ``surviving_sharpe``/``threshold`` on purpose: those two
#: names belong to feature 125's verdict, and a producer exposing them is a
#: different record being persisted by the wrong store.
_STABILITY_FIELDS = (
    "node_id",
    "tripwire",
    "axis",
    "rejected",
    "outcome",
    "stability",
    "stability_threshold",
    "reference_sharpe",
    "rerun_sharpe",
    "reference_threshold",
    "seed",
    "subsample_seed",
    "subsample_fraction",
    "horizon",
    "dates",
)


def _validate_record(verdict: Any) -> Any:
    """Hold a stability verdict to everything a persistence must not take on trust.

    Checked *structurally* — by the field names the row is built from — rather
    than by ``isinstance``, and that is not a shortcut.  The factory's scan
    imports this member under a synthetic module name
    (``_nullius_scanned_tripwires``), so a suite that also imported ``tripwires``
    canonically holds two distinct ``SubsampleRerunVerdict`` classes for one
    source file and ``isinstance`` cannot hold across them; feature 131's own
    validator states the argument, and this function makes it a second time
    because it is a *different* field list.

    Adds the two things the record's constructor cannot do for a persistence
    feature: the shape (a producer that is not a stability verdict has no terms
    to store, and the refusal names the missing fields rather than an attribute
    error three frames deeper), and the §8 outcome word — ``tripwire_fail``
    exactly when ``rejected``, so a row's classification agrees with the
    decision it carries.

    The decision itself is **not** re-derived here, unlike feature 131's check,
    and the asymmetry is deliberate rather than an omission.  Feature 131
    re-derives because a poisoning is *irreversible* and an invented cause
    cannot be repaired by running it again.  A stability row is neither: it is a
    measurement persisted beside others, a re-run of the feature refreshes it
    on its key, and the record's own constructor has already made it impossible
    to build a ``SubsampleRerunVerdict`` whose bit disagrees with its terms.  A
    second spelling of that arithmetic here would be a second implementation of
    :func:`~tripwires.subsample.subsample_figure` — the thing this member's
    one-provenance rule forbids — so the check stops at the shape and the word.
    """
    missing = [field for field in _STABILITY_FIELDS if not hasattr(verdict, field)]
    if missing:
        raise TripwireStabilityError(
            f"a stability figure is persisted from a perturbation-stability "
            f"verdict, and {type(verdict).__name__} carries none of "
            f"{', '.join(missing)}; the row's arithmetic comes from the "
            "verdict, and a producer whose terms the store cannot read would "
            "leave it storing a measurement it cannot check"
        )
    if verdict.tripwire != PERTURBATION_STABILITY_NAME:
        raise TripwireStabilityError(
            f"a stability figure is persisted from the "
            f"{PERTURBATION_STABILITY_NAME!r} probe, and this verdict names "
            f"{verdict.tripwire!r}; feature 125's probe states a *detection* and "
            "feature 131 persists it as a poisoning — a detection written into "
            "the stability table would enter the triage figure as a "
            "perturbation measurement that was never taken"
        )
    if not isinstance(verdict.rejected, bool):
        raise TripwireStabilityError(
            f"a stability verdict's rejected is a boolean, got "
            f"{verdict.rejected!r}"
        )
    expected_outcome = "tripwire_fail" if verdict.rejected else "ok"
    if verdict.outcome != expected_outcome:
        raise TripwireStabilityError(
            f"the stability verdict says rejected={verdict.rejected!r} but "
            f"carries outcome {verdict.outcome!r}; the outcome word is the "
            "decision's own translation into §8's vocabulary, and the row is "
            "what survives the in-memory value — a row whose word disagreed "
            "with its bit would classify a pass at the ledger as a failure"
        )
    return verdict


# -- The shared parsers, under this module's error ---------------------------------
#
# The three functions below are the *only* places this module reads or
# normalizes a value through :mod:`tripwires.layout`, and every one of them is a
# thin translation rather than a second implementation: the check itself is
# shared, so this member cannot hold two opinions about what a node id or a
# stored instant is.  Only the *vocabulary* differs, for the reason
# :mod:`tripwires.excise` states for its own three wrappers — a caller in the
# evaluation loop catches :class:`~tripwires.TripwireStabilityError` because the
# stability figure is what it asked to persist, and a `DATABASE_URL` this member
# cannot speak, a node id that cannot join the tree's key, or an unparseable
# stamp arriving as :class:`~tripwires.TripwirePoisonError` is precisely the case
# that caller did not catch.  Feature 131 *owns* those refusals — they are
# written in its vocabulary and its suite pins them — so the fix belongs here at
# the seam, not by widening 131's error to cover a feature it knows nothing
# about.


def _stability_path(database_url: str) -> Path:
    """The file ``database_url`` names, under *this* module's error.

    :func:`~tripwires.layout.sqlite_path` refuses a URL this member cannot speak
    with :class:`~tripwires.TripwirePoisonError`.  A stability store handed one
    of those has to answer in its own vocabulary: the store's docstring promises
    that ``resolve`` returning ``None`` means *a deployment without a relational
    store*, and a caller that writes ``except TripwireStabilityError`` around the
    persistence half — the one thing that catches "the perturbation figure was
    not stored" — would miss a misrouted ``DATABASE_URL`` entirely and take the
    process down with an error from the poisoning feature.

    Resolved through here in :meth:`StabilityStore.path`, which is the point the
    store first touches the URL, so every read and write below it is reached
    only once the URL has been answered for in this module's terms.
    """
    try:
        return sqlite_path(database_url)
    except TripwirePoisonError as exc:
        raise TripwireStabilityError(
            f"the stability store could not be addressed: {exc}"
        ) from exc


def _stability_node_id(value: Any) -> str:
    """Validate a node id — :func:`~tripwires.layout.validated_node_id`, here.

    The member has exactly one node-id normalization and this is not a second
    one.  Every id a stability row carries joins a UUID column — the row's own
    key, and the node the figure was measured for — so the validation is not
    optional; a mixed-case spelling of one node would read as two nodes in the
    set the triage figure groups by, and feature 134's AUC would separate
    planted nulls from real signals across a split that does not exist.
    """
    try:
        return validated_node_id(value)
    except TripwirePoisonError as exc:
        raise TripwireStabilityError(
            f"a stability row could not name its node: {exc}"
        ) from exc


def _stability_instant(value: Any) -> dt.datetime:
    """Validate a measurement stamp, refusing one that is not usable.

    :func:`~tripwires.layout.validated_instant` under this module's error.  That
    function's own messages say *a poisoning instant*, which is right where it
    was written and wrong here: the instant this module validates is when a
    **measurement** was taken, and a caller told its stability figure was
    refused because of a *poisoning* would go looking in the wrong feature.  The
    validation is shared; the sentence is not.
    """
    try:
        return validated_instant(value)
    except TripwirePoisonError as exc:
        raise TripwireStabilityError(
            f"a stability figure's recorded-at is not a usable instant: {exc}"
        ) from exc


def _stability_stored_instant(value: Any) -> dt.datetime:
    """Parse a stored instant, under this module's error.

    :func:`~tripwires.layout.parsed_instant` under
    :class:`~tripwires.TripwireStabilityError`, for the reason above: a row read
    back from the table is read by a caller in the persistence path, and an
    unparseable stamp surfacing as a poisoning error would send it to the wrong
    module for the cause.  The parser is shared, so this store and feature 131's
    cannot disagree about what a stored instant is.
    """
    try:
        return parsed_instant(value)
    except TripwirePoisonError as exc:
        raise TripwireStabilityError(
            f"a stored stability instant could not be parsed: {exc}"
        ) from exc


def _optional_int(value: Any, field: str) -> int | None:
    """An integer or ``None`` — the split every axis-dependent column makes.

    ``rerun_seed`` and ``subsample_seed`` are nullable because an axis whose
    perturbation is not that knob has none: this axis leaves ``rerun_seed``
    ``NULL`` and carries ``subsample_seed``, while feature 128's window offset
    has neither.  ``NULL`` means *this axis perturbs no such knob* and nothing
    else, the absent-versus-zero distinction the member's schemas keep
    throughout — a zero would read as a real seed.
    """
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TripwireStabilityError(
            f"a stability row's {field} is an integer or absent, got "
            f"{value!r} ({type(value).__name__}); an axis that perturbs no such "
            "knob writes NULL, and a non-integer would read as a real value"
        )
    return value


class StabilityRecord:
    """One row of :data:`STABILITY_TABLE` — a node's stability under one axis.

    A frozen value carrying the persisted figure and every term it is
    re-derivable from: both statistics, the bar the figure is measured in, the
    configured bar it was judged against, the decision, and the axis whose
    perturbation produced it.  Deliberately *not* the verdict type: the reading
    half of a store must not depend on the producing half being in memory, and a
    ``stability_of`` call has a database row, not a verdict.

    ``rerun_seed`` and ``subsample_seed`` are ``None`` for axes that perturb no
    such knob — see :func:`_optional_int`.  ``subsample_fraction`` is ``None``
    for every axis but this one, and for the same reason.
    """

    __slots__ = (
        "_axis",
        "_horizon",
        "_measured_dates",
        "_node_id",
        "_outcome",
        "_recorded_at",
        "_reference_sharpe",
        "_reference_threshold",
        "_rejected",
        "_rerun_seed",
        "_rerun_sharpe",
        "_seed",
        "_stability",
        "_stability_threshold",
        "_subsample_fraction",
        "_subsample_seed",
        "_tripwire",
    )

    def __init__(
        self,
        *,
        node_id: Any,
        axis: str,
        tripwire: str,
        outcome: str,
        rejected: bool,
        stability: float,
        stability_threshold: float,
        reference_sharpe: float,
        rerun_sharpe: float,
        reference_threshold: float,
        seed: int,
        rerun_seed: int | None,
        subsample_fraction: float | None,
        subsample_seed: int | None,
        horizon: int,
        measured_dates: int,
        recorded_at: Any,
    ) -> None:
        object.__setattr__(self, "_node_id", _stability_node_id(node_id))
        for name, value in (("axis", axis), ("tripwire", tripwire)):
            if not isinstance(value, str) or not value.strip():
                raise TripwireStabilityError(
                    f"a stability row's {name} must be a non-empty name, got "
                    f"{value!r}; the row says *which* perturbation produced the "
                    "figure, and a blank one is an uninterpretable measurement"
                )
            object.__setattr__(self, f"_{name}", value)
        if outcome != "tripwire_fail" and outcome != "ok":
            raise TripwireStabilityError(
                f"a stability row's outcome is §8's 'ok' or 'tripwire_fail', "
                f"got {outcome!r}; a figure is persisted whether or not its bar "
                "was exceeded, and any other word would classify the "
                "measurement as something it is not"
            )
        object.__setattr__(self, "_outcome", outcome)
        if not isinstance(rejected, bool):
            raise TripwireStabilityError(
                f"a stability row's rejected is a boolean, got {rejected!r}"
            )
        object.__setattr__(self, "_rejected", rejected)
        if rejected != (outcome == "tripwire_fail"):
            raise TripwireStabilityError(
                f"a stability row says rejected={rejected!r} and outcome "
                f"{outcome!r}; the two spellings of one fact cannot disagree, "
                "and the row is what a triage reads after the verdict is gone"
            )
        for name, value in (
            ("stability", stability),
            ("stability_threshold", stability_threshold),
            ("reference_sharpe", reference_sharpe),
            ("rerun_sharpe", rerun_sharpe),
            ("reference_threshold", reference_threshold),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TripwireStabilityError(
                    f"a stability row's {name} must be a number, got {value!r}"
                )
            if not math.isfinite(float(value)):
                raise TripwireStabilityError(
                    f"a stability row's {name} is not finite ({value!r}); a NaN "
                    "or ±inf would reach the triage figure dressed as a "
                    "measurement"
                )
            object.__setattr__(self, f"_{name}", float(value))
        for name, value in (
            ("seed", seed),
            ("horizon", horizon),
            ("measured_dates", measured_dates),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TripwireStabilityError(
                    f"a stability row's {name} must be an integer, got {value!r}"
                )
            object.__setattr__(self, f"_{name}", value)
        object.__setattr__(self, "_rerun_seed", _optional_int(rerun_seed, "rerun_seed"))
        object.__setattr__(
            self, "_subsample_seed", _optional_int(subsample_seed, "subsample_seed")
        )
        if subsample_fraction is None:
            object.__setattr__(self, "_subsample_fraction", None)
        else:
            if isinstance(subsample_fraction, bool) or not isinstance(
                subsample_fraction, (int, float)
            ):
                raise TripwireStabilityError(
                    f"a stability row's subsample_fraction is a number or "
                    f"absent, got {subsample_fraction!r}"
                )
            object.__setattr__(
                self, "_subsample_fraction", float(subsample_fraction)
            )
        if self._reference_threshold <= 0.0:
            raise TripwireStabilityError(
                f"a stability row's reference threshold is positive, got "
                f"{self._reference_threshold!r}; the figure is standardized by "
                "it, and a bar of zero would make every stored figure "
                "unrecomputable"
            )
        object.__setattr__(self, "_recorded_at", _stability_instant(recorded_at))

    @property
    def node_id(self) -> str:
        """The node the figure was measured for, canonical UUID text."""
        return self._node_id

    @property
    def axis(self) -> str:
        """Which perturbation produced the figure — ``universe-subsample`` here."""
        return self._axis

    @property
    def tripwire(self) -> str:
        """The probe that fired — always ``perturbation-stability``."""
        return self._tripwire

    @property
    def outcome(self) -> str:
        """§8's word for the decision — ``ok`` or ``tripwire_fail``.

        Both are persisted, and that is the feature: a stability figure is the
        input to the triage decision (feature 134), and an AUC needs the figures
        that were *supposed* to be small as much as the ones that were not.
        """
        return self._outcome

    @property
    def rejected(self) -> bool:
        """Whether the figure exceeded its configured bar."""
        return self._rejected

    @property
    def stability(self) -> float:
        """The figure itself — the number this feature's sentence names."""
        return self._stability

    @property
    def stability_threshold(self) -> float:
        """The configured bar it was judged against."""
        return self._stability_threshold

    @property
    def reference_sharpe(self) -> float:
        """The full-universe surviving Sharpe — the number under test."""
        return self._reference_sharpe

    @property
    def rerun_sharpe(self) -> float:
        """The subsample's surviving Sharpe — the same measurement, thinner."""
        return self._rerun_sharpe

    @property
    def reference_threshold(self) -> float:
        """The bar the figure is measured in — ``Φ⁻¹(1 − level/2)/√dates``."""
        return self._reference_threshold

    @property
    def seed(self) -> int:
        """The shuffle seed both runs drew their derangement from."""
        return self._seed

    @property
    def rerun_seed(self) -> int | None:
        """The second shuffle seed, or ``None`` for an axis that draws none.

        ``None`` for this axis deliberately: it holds the derangement fixed, so
        there is no second seed — feature 127's axis is what moves that knob.
        """
        return self._rerun_seed

    @property
    def subsample_fraction(self) -> float | None:
        """The fraction of the universe the re-run kept, or ``None``."""
        return self._subsample_fraction

    @property
    def subsample_seed(self) -> int | None:
        """The seed the subsample was drawn under, or ``None``."""
        return self._subsample_seed

    @property
    def horizon(self) -> int:
        """The target series both runs probed."""
        return self._horizon

    @property
    def measured_dates(self) -> int:
        """The ``T`` behind the reference threshold."""
        return self._measured_dates

    @property
    def recorded_at(self) -> dt.datetime:
        """When the figure was persisted, UTC — not when it was measured."""
        return self._recorded_at

    def recomputes(self) -> float:
        """The figure recomputed from the row's own terms — the audit check.

        ``|rerun_sharpe − reference_sharpe| / reference_threshold``, taken the
        way :func:`~tripwires.subsample.subsample_figure` takes it, so a reader
        holding only a stored row can ask whether the number it carries is the
        number its own terms produce — the property that makes a persisted
        figure auditable rather than merely recorded.  A *delegation* and not a
        second implementation: the arithmetic lives in that function, and this
        method is what a row offers a caller who has no verdict to hand it.
        """
        return subsample_figure(
            self._reference_sharpe,
            self._rerun_sharpe,
            threshold=self._reference_threshold,
        )

    def to_payload(self) -> dict[str, Any]:
        """The row as a plain mapping, for a log line or a triage input."""
        return {
            "node_id": self._node_id,
            "axis": self._axis,
            "tripwire": self._tripwire,
            "outcome": self._outcome,
            "rejected": self._rejected,
            "stability": self._stability,
            "stability_threshold": self._stability_threshold,
            "reference_sharpe": self._reference_sharpe,
            "rerun_sharpe": self._rerun_sharpe,
            "reference_threshold": self._reference_threshold,
            "seed": self._seed,
            "rerun_seed": self._rerun_seed,
            "subsample_fraction": self._subsample_fraction,
            "subsample_seed": self._subsample_seed,
            "horizon": self._horizon,
            "measured_dates": self._measured_dates,
            "recorded_at": self._recorded_at.isoformat(),
        }

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, StabilityRecord):
            return NotImplemented
        return all(
            getattr(self, slot) == getattr(other, slot) for slot in self.__slots__
        )

    def __hash__(self) -> int:
        return hash(
            (
                self._node_id,
                self._axis,
                self._tripwire,
                self._outcome,
                self._rejected,
                self._stability,
                self._stability_threshold,
                self._reference_sharpe,
                self._rerun_sharpe,
                self._reference_threshold,
                self._seed,
                self._rerun_seed,
                self._subsample_fraction,
                self._subsample_seed,
                self._horizon,
                self._measured_dates,
                self._recorded_at,
            )
        )

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"StabilityRecord(node={self._node_id!r}, axis={self._axis!r}, "
            f"stability={self._stability:.4f} against "
            f"{self._stability_threshold:.4f}, outcome={self._outcome!r})"
        )


def _row_from_stored(values: Sequence[Any]) -> StabilityRecord:
    """One stored row, as a :class:`StabilityRecord`.

    Positional unpacking driven by :data:`~tripwires.layout.STABILITY_COLUMNS`,
    which is why that tuple is spelled once: the write and this read must not be
    able to drift apart on a column order.  The stored instant is parsed rather
    than handed back as text, for the reason
    :func:`~tripwires.layout.parsed_instant` gives — a caller comparing a string
    against a datetime would find them unequal always, and an ordering nobody
    can check is worse than one that stops.
    """
    return StabilityRecord(
        node_id=values[0],
        axis=values[1],
        tripwire=values[2],
        outcome=values[3],
        rejected=bool(values[4]),
        stability=values[5],
        stability_threshold=values[6],
        reference_sharpe=values[7],
        rerun_sharpe=values[8],
        reference_threshold=values[9],
        seed=values[10],
        rerun_seed=values[11],
        subsample_fraction=values[12],
        subsample_seed=values[13],
        horizon=values[14],
        measured_dates=values[15],
        recorded_at=_stability_stored_instant(values[16]),
    )


def _utc_now() -> dt.datetime:
    """The current UTC instant, truncated to the second.

    Truncated because the column is a *record of a write* — the same precision
    feature 131's stamps carry — and sub-second digits would make two runs of
    one persistence differ in a field no reader consults at that resolution.
    """
    return dt.datetime.now(dt.UTC).replace(microsecond=0)


class StabilityStore:
    """Feature 129's persistence: the figure a re-run measured, per axis.

    Constructed with the database URL it writes to; :meth:`record` upserts one
    node's figure for one axis; :meth:`figures` reads a node's rows back;
    :meth:`axes` reads which perturbations have been measured for it.  The class
    resolves its path lazily, so constructing one performs no I/O —
    composition-time work must not touch the disk, the contract every store in
    this workspace states.

    **It does not require the node to exist, and that is the second difference
    from feature 131's store.**  A poisoning is a fact about a node's *place in
    a tree* — the subtree is the transitive closure of ``parent_id`` — so a node
    the tree does not hold has no branch to mark, and 131 refuses it.  A
    stability figure is a fact about a *candidate's measurement*, and it is
    legitimately known before the node's row is written: §6.1 puts step 10 after
    the metrics and before the trial is debited, so a caller can hold a figure
    for a node the tree has not yet been handed.  Refusing here would force the
    two writes into an order the pipeline does not have, so this store writes
    the row and leaves the join to whoever wants it — the ``node`` table is
    still bootstrapped, because a store that left its database without the table
    the rest of the member reads would be surprising in a different way.
    """

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise TripwireStabilityError(
                f"{DATABASE_URL_ENV} must be a non-empty database URL"
            )
        self._database_url = database_url.strip()
        # Resolved on first use rather than at construction: building the store
        # is composition-time work and must not touch the disk.
        self._path: Path | None = None

    # -- Construction ---------------------------------------------------------

    @classmethod
    def resolve(cls, env: Mapping[str, str] | None = None) -> StabilityStore | None:
        """The store ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset.  Absent is not an
        error: it is a deployment without a relational store, which composes no
        stability component — a discoverable state, not an exception — while the
        evaluation loop that must persist §C6's stability figures is the caller
        that must not find itself in it.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The database URL this store writes to."""
        return self._database_url

    @property
    def path(self) -> Path:
        """The SQLite file backing this store, resolved on first use."""
        if self._path is None:
            self._path = _stability_path(self._database_url)
        return self._path

    def ensure_schema(self) -> None:
        """Bring the database to the shape this store reads and writes, idempotently.

        Public for the reason :meth:`~tripwires.poison.PoisonStore.ensure_schema`
        is: an operator pointing this member at a database the orchestrator has
        not migrated yet runs it once, and a test seeds a node into exactly the
        schema the store will read.

        It bootstraps ``node`` as well, and that is inherited rather than
        needed: this store writes no column on that table and requires no row in
        it, but it shares a database with feature 131's store and 132's pool,
        and a shared bootstrap that created only *this* feature's table would
        make the schema depend on which store happened to run first.  Every
        statement is ``IF NOT EXISTS``, so the three agree and none undoes
        another.
        """
        with closing(sqlite3.connect(self.path)) as connection, connection:
            self._apply_schema(connection)

    def _apply_schema(self, connection: sqlite3.Connection) -> None:
        """The DDL itself, on a connection the caller already holds open."""
        connection.executescript(node_bootstrap_schema(dialect_of(connection)))
        connection.executescript(stability_bootstrap_schema(dialect_of(connection)))

    def _connect(self) -> sqlite3.Connection:
        """Open the database, bringing it to this store's shape first.

        The caller owns the connection; use it as a context manager to commit.
        """
        self.ensure_schema()
        return sqlite3.connect(self.path)

    # -- Feature 129: the figure ----------------------------------------------

    def record(
        self,
        verdict: SubsampleRerunVerdict,
        *,
        recorded_at: dt.datetime | None = None,
    ) -> StabilityRecord:
        """Persist the verdict's stability figure — feature 129's own sentence.

        The whole of the persistence half in one call: the verdict is checked to
        be a perturbation-stability record whose outcome word is its own
        decision, its node id is normalized, and one row is upserted into
        :data:`~tripwires.layout.STABILITY_TABLE` on ``(node_id, axis)``.

        **A passing verdict is written**, and that is the feature rather than a
        loosening: a stability figure is the input to a triage decision
        (feature 134 computes the AUC of this family separating planted nulls
        from real signals), an AUC needs both classes, and a store keeping only
        the rejections would train the discriminator on the tail it is meant to
        detect.  So ``ok`` and ``tripwire_fail`` rows both land, told apart by
        ``rejected``.

        ``recorded_at`` defaults to the current UTC instant truncated to the
        second.  It is a parameter at all so a replay can stamp the instant the
        measurement *happened* rather than the instant the retry ran — the same
        reason feature 131's ``poisoned_at`` is one, and the same reason it is
        validated: a naive datetime would place a measurement hours from the
        trial that produced it and nothing would look wrong.

        Re-running it over the same verdict is a **refresh**, not a second row:
        the axis is the key's second half precisely so that a re-measurement of
        the same perturbation replaces the figure it supersedes, and a branch of
        the table showing three figures for one axis would make *which
        perturbation moved this candidate?* unanswerable.

        Refuses, in this order, and each refusal names what it is about:

        1. a producer the store cannot read — a missing field list, or a
           ``tripwire`` that is not the perturbation-stability probe
           (:class:`~tripwires.TripwireStabilityError`);
        2. an outcome word that disagrees with the verdict's own ``rejected``;
        3. a node id that cannot join the tree's key, or a table this member
           cannot write.
        """
        checked = _validate_record(verdict)
        node = _stability_node_id(checked.node_id)
        stamp = (
            _utc_now() if recorded_at is None else _stability_instant(recorded_at)
        )
        row = StabilityRecord(
            node_id=node,
            axis=checked.axis,
            tripwire=checked.tripwire,
            outcome=checked.outcome,
            rejected=checked.rejected,
            stability=checked.stability,
            stability_threshold=checked.stability_threshold,
            reference_sharpe=checked.reference_sharpe,
            rerun_sharpe=checked.rerun_sharpe,
            reference_threshold=checked.reference_threshold,
            seed=checked.seed,
            rerun_seed=getattr(checked, "rerun_seed", None),
            subsample_fraction=getattr(checked, "subsample_fraction", None),
            subsample_seed=getattr(checked, "subsample_seed", None),
            horizon=checked.horizon,
            measured_dates=checked.dates,
            recorded_at=stamp,
        )
        with closing(self._connect()) as connection, connection:
            self._write(connection, row)
        return row

    @staticmethod
    def _write(connection: sqlite3.Connection, row: StabilityRecord) -> None:
        """Upsert one row, on the key the table is designed around.

        ``ON CONFLICT(node_id, axis) DO UPDATE`` rather than a delete-then-
        insert: the row is replaced in one statement, so a crash cannot leave
        the table holding neither the old figure nor the new one — the
        half-written state :meth:`~tripwires.poison.PoisonStore._mark`'s single
        ``UPDATE`` exists to avoid for the same reason.

        ``rejected`` is stored as an integer because that is what SQLite's
        ``INTEGER`` affinity holds, and it is read back through ``bool()`` at
        the one place a row becomes a value — not coerced anywhere else, since a
        ``bool()`` applied twice to a value that already is one is the reflex
        that hides a column written by something else.
        """
        placeholders = ", ".join("?" for _ in STABILITY_COLUMNS)
        connection.execute(
            f"""
            INSERT INTO {STABILITY_TABLE} ({', '.join(STABILITY_COLUMNS)})
            VALUES ({placeholders})
            ON CONFLICT(node_id, axis) DO UPDATE SET
                tripwire            = excluded.tripwire,
                outcome             = excluded.outcome,
                rejected            = excluded.rejected,
                stability           = excluded.stability,
                stability_threshold = excluded.stability_threshold,
                reference_sharpe    = excluded.reference_sharpe,
                rerun_sharpe        = excluded.rerun_sharpe,
                reference_threshold = excluded.reference_threshold,
                seed                = excluded.seed,
                rerun_seed          = excluded.rerun_seed,
                subsample_fraction  = excluded.subsample_fraction,
                subsample_seed      = excluded.subsample_seed,
                horizon             = excluded.horizon,
                measured_dates      = excluded.measured_dates,
                recorded_at         = excluded.recorded_at
            """,
            (
                row.node_id,
                row.axis,
                row.tripwire,
                row.outcome,
                1 if row.rejected else 0,
                row.stability,
                row.stability_threshold,
                row.reference_sharpe,
                row.rerun_sharpe,
                row.reference_threshold,
                row.seed,
                row.rerun_seed,
                row.subsample_fraction,
                row.subsample_seed,
                row.horizon,
                row.measured_dates,
                row.recorded_at.isoformat(),
            ),
        )

    def figures(self, node_id: Any) -> tuple[StabilityRecord, ...]:
        """Every stability figure persisted for ``node_id``, axis by axis.

        Ordered by axis so two reads of one node return the same tuple in the
        same order: the figures are a *set* compared side by side, and a read
        whose order depended on the row order the database happened to return
        would make cross-run comparison of a whole node a comparison of two
        orderings.

        Returns an empty tuple for a node with no figures rather than refusing:
        "nothing has been measured for this node yet" is a legitimate and common
        state — the node may be mid-pipeline — and it is *not* the same claim as
        "this node is stable".  A caller that needs those told apart reads the
        length.
        """
        node = _stability_node_id(node_id)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"SELECT {', '.join(STABILITY_COLUMNS)} FROM {STABILITY_TABLE} "
                f"WHERE node_id = ? ORDER BY axis",
                (node,),
            ).fetchall()
        return tuple(_row_from_stored(row) for row in rows)

    def stability_of(self, node_id: Any, *, axis: str) -> StabilityRecord:
        """One node's figure for one axis, or a refusal naming the absence.

        The single-axis read, and it **refuses** where :meth:`figures` returns
        empty — deliberately, and the split is the one feature 132's excision
        makes: "this node's subsample figure is X" and "this node has no
        subsample figure" are different sentences, and a caller handed a default
        for the second would record a measurement nobody took.  A caller
        checking *whether* a figure exists asks :meth:`figures` or :meth:`axes`.
        """
        if not isinstance(axis, str) or not axis.strip():
            raise TripwireStabilityError(
                f"a stability figure is read by axis, got {axis!r}; the axis is "
                "half the row's key, and a blank one names no figure"
            )
        node = _stability_node_id(node_id)
        with closing(self._connect()) as connection:
            row = connection.execute(
                f"SELECT {', '.join(STABILITY_COLUMNS)} FROM {STABILITY_TABLE} "
                f"WHERE node_id = ? AND axis = ?",
                (node, axis),
            ).fetchone()
        if row is None:
            raise TripwireStabilityError(
                f"no stability figure is persisted for node {node!r} on axis "
                f"{axis!r}; the node may not have been re-run on that "
                "perturbation at all, which is a different state from one whose "
                "figure was measured and found small — a caller handed a "
                "default here would record a measurement nobody took"
            )
        return _row_from_stored(row)

    def axes(self, node_id: Any) -> tuple[str, ...]:
        """Which perturbations have a persisted figure for ``node_id``.

        The question feature 134's triage asks before computing anything: the
        AUC of this family is over the axes that were actually measured, and a
        node with two of §C6's four is a different amount of evidence from one
        with all four.  Drawn from the same read :meth:`figures` makes rather
        than a second query, so the two cannot disagree about what exists.
        """
        return tuple(record.axis for record in self.figures(node_id))


# -- The two module-level entry points -------------------------------------------


def record_stability(
    verdict: SubsampleRerunVerdict,
    *,
    database_url: str | None = None,
    store: StabilityStore | None = None,
    recorded_at: dt.datetime | None = None,
) -> StabilityRecord:
    """Persist ``verdict`` as its node's stability figure on its axis — feature 129.

    The module-level spelling of :meth:`StabilityStore.record`, for a caller that
    has a verdict and wants the feature rather than an object: it composes a
    store from ``DATABASE_URL`` (or the URL handed to it) and records the figure.
    A ``store`` may be handed in instead, which is what the composed component
    is and what a test passes to pin the database it wrote to.

    Refuses a call that names no store — neither a ``store`` nor a
    ``database_url`` nor a ``DATABASE_URL`` in the environment — with
    :class:`~tripwires.TripwireStabilityError` rather than silently doing
    nothing.  That is the stance :func:`~tripwires.poison.poison_node` takes and
    it is the right one here for the same reason: the feature's sentence is
    *"persisting"*, and a no-op that returned successfully would report a figure
    persisted by a deployment that has nowhere to persist it.
    """
    resolved = store if store is not None else _store_for(database_url)
    if resolved is None:
        raise TripwireStabilityError(
            f"a stability figure is persisted to a relational store, and "
            f"nothing names one: pass a store, a database_url, or set "
            f"{DATABASE_URL_ENV}. A no-op here would report the feature's own "
            "sentence — 'persisting the subsample stability figure' — as "
            "satisfied by a deployment that has nowhere to write it"
        )
    return resolved.record(verdict, recorded_at=recorded_at)


def _store_for(database_url: str | None) -> StabilityStore | None:
    """A store from an explicit URL or the environment, or ``None``."""
    if database_url is not None:
        return StabilityStore(database_url)
    return StabilityStore.resolve()


def stability_of(
    node_id: Any, *, axis: str, database_url: str | None = None
) -> StabilityRecord:
    """Read one persisted stability figure — the module-level spelling.

    The read half of :func:`record_stability`, and the one a triage or an
    operator reaches for: it composes a store the same way and returns the
    record, refusing by name when the node has no figure on that axis (see
    :meth:`StabilityStore.stability_of`).  Symmetric with the write on purpose —
    a feature whose sentence says persist must have a way to read what it
    persisted, or the sentence is unverifiable from outside this process.
    """
    store = _store_for(database_url)
    if store is None:
        raise TripwireStabilityError(
            f"a stability figure is read from a relational store, and nothing "
            f"names one: pass a database_url or set {DATABASE_URL_ENV}"
        )
    return store.stability_of(node_id, axis=axis)
