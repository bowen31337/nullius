"""Feature 251 — the replay's campaign-returns read: resident, never re-swept.

app_spec.xml, "Replay Engine", feature 251: *System reads campaign returns
from the pinned resident array rather than from Parquet on each replay.*  It
declares ``depends_on=245``, and it is the read-path rule of the family the
transition's docstring names — never the evaluator (246), never the sandbox
(247), never a Parquet sweep per replay (this feature) — because §10.4's
performance target states its own premise: *"A replay is pure array
arithmetic over cached Parquet. Target: under 50 ms per (policy, world) on a
single core."*  §9.3 puts the number the naive reading costs:

    The real cost is I/O. A replay revealing 100 nodes reads ~20 MB of
    Parquet; 200 worlds × 40 policy versions done naively is ~160 GB per
    dreaming cycle.

and the instruction this feature is the replay-side half of:

    Load each campaign's signal returns once as a single dense ``float32``
    array of shape ``(nodes × T)`` and pin it in RAM.

The artifacts member built the halves below this seam — the load (feature
174), the counted hold (feature 175), the resident cache (176), the Cholesky
factor (177) and the rank-1 update (178).  This module is the replay path's
one act on top of them: **a replay reads a campaign's returns by pinning the
campaign's ``(campaign_id, horizon)`` axis through a resident pin arena and
answering the array the arena holds** — one read per replay, resident for
the read's lifetime, released when the replay lets go.

**The refusal is the feature's other half, and it sits on the verb a Parquet
read would arrive through.**  :func:`resident_returns` accepts a ``load``
argument — the callable shape of the Parquet sweep, feature 174's
``load_campaign_returns(store, campaign, horizon=...)`` being its spelling —
and **refuses it** with :class:`~replay.ParquetReadRefused` *before the
campaign is validated, before the arena is touched and before the loader is
called*.  The order is feature 245's (and 146's before it): a refusal that
swept Parquet first and raised afterwards would have spent the very I/O it
was refusing to spend.  The parameter rather than a missing one is the
design point, exactly as it is for the transition's ``generator``: the
replay path's driver never passes one, so a runtime that wanted to re-read
would have to write ``load=...`` at a call site whose keyword is the
refusal's name — one verb, one seam, one place to look.

**The arena arrives as an argument, duck-typed, because a member never
imports another member.**  The resident pin arena is the artifacts member's
``CampaignPins``, and feature 175 deliberately registered **no component**
for it — the arena is per-replay state, built by the round that holds it —
so there is nothing to compose and nothing to resolve: the caller that built
the arena hands it in, the same way a caller that holds a tree hands the
tree to the transition.  The seam validates what it *reads* — the carrier's
``pin`` verb, the hold's ``returns`` and ``release``, the resident array's
identity (its campaign, its axes, its contiguous buffer) — rather than
``isinstance``-ing any of them, because the module loader imports a member
under a synthetic name and re-executes it, so an ``isinstance`` would refuse
the very arena composition would hand out.  Every failure is translated
into this member's own vocabulary (:class:`~replay.ReplayReturnsError`), so
a caller's single ``except ReplayError`` catches every way a read can fail —
the rule :mod:`replay.transition` states for the tree's failures, restated
for the residence's.

**One read per replay.**  The resident array is read off the hold **once**,
at construction, and that one object is the answer for the read's whole
lifetime: :attr:`ReplayReturns.returns` answers the same object on every
access, so a replay's hundred score-time reads of its campaign are a
hundred answers of one resident array, not a hundred asks of anything.
Whether the pin underneath loaded or hit residence is the arena's business
(feature 175's law: one load per axis per arena, the same resident object
to every holder) — which is the precise sense of the feature's sentence:
the *replay's* acts touch RAM only.  This member never reads Parquet at
all, not even once; even an axis's first load is the arena's act, through
feature 174's load — the one decoder the arena trusts — and never the
replay's.

**The read is a scope.**  A hold is per-replay state: it begins when the
read opens (the pin), it answers while it is live, and it ends when the
replay lets go (:meth:`ReplayReturns.release`, or the ``with`` block's
exit) — the counted share is returned to the arena exactly then, so the
last release of an axis drops the buffer and the RAM §9.3 prices comes
back.  A released read refuses to answer and a second release refuses, in
this member's vocabulary, mirroring the handle's own honesty in the member
that owns it: a read that kept answering after release would be indexing a
buffer outside the accounting that releasing exists to keep honest.

**Per-replay state, not a component.**  :class:`ReplayReturns` is the
episode's object the way :class:`~replay.ReplayTransition` is — built by
the replay that holds it, never ``@register``-ed — and the composed
component (:class:`~replay.ReplayEngine`) gains the verb
:meth:`~replay.ReplayEngine.returns` rather than a second component: one
component per member name, the law the package ``__init__`` states, kept by
adding behaviour to the facade instead of a ``replay-``prefixed sibling the
spec does not ask for.

**What this module deliberately does not do.**  It does not score — the
array it answers is the thing features 249, 250 and 255 measure, over the
book and the epoch — and it does not time the read (252's measurement, 253's
``recomputation_suspected`` alert and 254's percentiles are the timing shadow
of the law this module *is*).  It adds no second decoder (the arena loads;
this member decodes nothing), no eviction or content policy (the pins own
the lifetime, the cache — feature 176 — the content; a replay holds pins
because a replay ends), and no axes of its own: the resident record's nodes
and periods are the campaign's identity, read as found, never restated.
Stdlib only — the typing that names the seam, the date kind the column axis
carries, and nothing else — so importing this member on every factory scan
costs composition nothing, per §12's rule that the replay path may not grow
a numerical stack.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from types import TracebackType
from typing import Any

from .errors import ParquetReadRefused, ReplayError, ReplayReturnsError

__all__ = [
    "RESIDENT_READ_POLICY",
    "ReplayReturns",
    "resident_returns",
]

#: The read policy, spelled once the way the artifacts member spells
#: :data:`~artifacts.RESIDENT_PIN_POLICY` and
#: :data:`~artifacts.RESIDENT_CACHE_POLICY`: a sentence, not a type, because
#: it is the *decision* the feature's sentence pins and every seam that
#: states it (this module's docstrings, the error vocabulary's, the tests)
#: quotes this one spelling of it.
RESIDENT_READ_POLICY: str = (
    "read campaign returns from the pinned resident array on each replay — "
    "never a Parquet sweep per replay"
)


# -- the read -----------------------------------------------------------------------------


def resident_returns(
    pins: Any,
    campaign_id: Any,
    *,
    horizon: int | None = None,
    load: Any = None,
) -> ReplayReturns:
    """Open a replay's resident read of one campaign axis — feature 251.

    The replay path's one campaign-returns act: pin ``(campaign_id,
    horizon)`` through the resident pin arena (feature 175's ``CampaignPins``,
    handed in duck-typed — the arena is per-replay state, built by the round
    that holds it, so it arrives as an argument exactly as the tree arrives
    at the transition) and answer the resident array the arena holds.  One
    read per replay: the object answered at construction is the answer for
    the read's lifetime, released when the replay lets go.

    **The refusal, and it fires first.**  ``load`` is the callable shape of
    the Parquet sweep — a function that would answer the campaign's returns
    by reading the store, feature 174's ``load_campaign_returns`` being its
    spelling.  Handing one in is *the Parquet read per replay* that
    app_spec.xml feature 251 replaces, and it is refused with
    :class:`~replay.ParquetReadRefused` **before the campaign is validated,
    before the arena is touched and before the loader is called** — the
    ordering of feature 245's generator refusal, for its reason: a refusal
    that read first and raised afterwards would have spent the I/O it was
    refusing to spend.  There is no second verb, no ``sweep`` spelling and
    no flag that turns the seam off.

    ``campaign_id`` must be a non-empty string and ``horizon`` either
    ``None`` (the policy axis) or a positive period count — both refused in
    this member's vocabulary **before the arena is touched**, because a
    malformed ask is the caller's to repair and the arena should never see
    it.  The arena's own refusals — whatever class it raises — are
    translated into :class:`~replay.ReplayReturnsError` naming the campaign
    and the axis, chained to the original, so a caller's single ``except
    ReplayError`` catches a campaign no replay can read.
    """
    if load is not None:
        raise ParquetReadRefused(_parquet_message(campaign_id, load))
    campaign = _campaign_id_of(campaign_id)
    pinned = None if horizon is None else _horizon_of(horizon)
    hold = _pinned(pins, campaign, pinned)
    resident = _held_array(hold, campaign, pinned)
    return ReplayReturns(campaign, pinned, hold, resident)


class ReplayReturns:
    """One replay's resident read of one campaign axis — feature 251.

    What :func:`resident_returns` answers: the voucher, not the value.  The
    object holds the replay's counted share of the axis's resident array
    (the duck-typed pin the arena minted) and the **one resident array read
    off it at construction** — :attr:`returns` answers that object on every
    access for the read's whole lifetime, so a replay's score-time reads are
    answers of one resident array rather than asks of anything.  Released
    (explicitly, or by leaving the ``with`` scope), the read vouches for
    nothing: :attr:`returns` refuses rather than answering a buffer outside
    the hold's accounting, and a second :meth:`release` refuses rather than
    subtracting a share this read already spent.

    Usable as a context manager — ``with resident_returns(pins, campaign)
    as array:`` — because a read is a scope: the block pins, the block's
    exit releases what the block left held, and a caller that released
    early inside the block leaves the scope cleanly rather than tripping
    the double-release refusal on the way out.

    Per-replay state, not a component and not ``@register``-ed: it belongs
    to the replay that opened it, the same stance
    :class:`~replay.ReplayTransition` takes, and for the same reason — a
    second replay starts its own read at the arena again.
    """

    __slots__ = ("_campaign_id", "_horizon", "_hold", "_live", "_resident")

    def __init__(
        self,
        campaign_id: str,
        horizon: int | None,
        hold: Any,
        resident: Any,
    ) -> None:
        # Minted by `resident_returns`, which has validated the hold and the
        # resident array as it read them; the constructor is the seam's own
        # spelling, for a caller that already holds a validated pin.
        self._campaign_id = campaign_id
        self._horizon = horizon
        self._hold = hold
        self._resident = resident
        self._live = True

    @property
    def campaign_id(self) -> str:
        """The campaign this read is on — the ask's first key."""
        return self._campaign_id

    @property
    def horizon(self) -> int | None:
        """The horizon axis this read is on — the ask's own spelling.

        ``None`` for the policy axis (the load resolved the horizon policy),
        the pinned horizon otherwise; the *resolved* horizon is always
        ``read.returns.horizon``.  Carried so a caller juggling several
        reads can say which axis of which campaign a refusal is about.
        """
        return self._horizon

    @property
    def released(self) -> bool:
        """Whether this read has spent its hold."""
        return not self._live

    @property
    def returns(self) -> Any:
        """The resident campaign array this read holds a share of.

        The same object on every access — the one array read off the pin at
        construction, which is the feature's own sentence made structural:
        *every* read of the replay's campaign returns is this resident
        object, so nothing downstream can accidentally become a second,
        Parquet-backed ask.  Refuses once released:
        :class:`~replay.ReplayReturnsError`, naming the campaign and the
        axis, because a read that kept answering would be holding the
        buffer outside the count that releasing exists to keep honest.
        """
        if not self._live:
            raise ReplayReturnsError(
                f"this read on campaign {self._campaign_id!r} "
                f"({self._axis_spelling}) was released, and a released read "
                "vouches for no array — the hold's accounting stopped "
                "counting this replay when it let go; open a fresh read "
                "(resident_returns) for a hold that is live"
            )
        return self._resident

    @property
    def _axis_spelling(self) -> str:
        """The horizon axis as a message names it."""
        return (
            "the policy axis"
            if self._horizon is None
            else f"horizon {self._horizon}"
        )

    def release(self) -> None:
        """Let go — spend this replay's hold on the resident array.

        Delegates to the hold's own release (the counted share returns to
        the arena; if other holders remain the array stays resident for
        them, and if this was the last the arena drops the entry and its
        footprint — feature 175's law).  A second release refuses, in this
        member's vocabulary, because the first already spent this read's
        share and a second would subtract one of the holders that still
        hold.
        """
        if not self._live:
            raise ReplayReturnsError(
                f"this read on campaign {self._campaign_id!r} "
                f"({self._axis_spelling}) was already released; a read is "
                "released exactly once — the release that already happened "
                "spent this hold, and a second would subtract one of the "
                "holders that still hold the array"
            )
        self._live = False
        try:
            self._hold.release()
        except ReplayReturnsError:
            raise
        except Exception as exc:  # the hold's own refusal belongs to the
            # member that minted it; a caller catching this member's base
            # class must catch the release failing too.
            raise ReplayReturnsError(
                f"the resident hold on campaign {self._campaign_id!r} "
                f"({self._axis_spelling}) refused its release: "
                f"{exc!r}. A read's release returns its counted share to "
                "the arena (feature 175's law — the last release drops the "
                "buffer), so a hold that cannot let go is a residence no "
                "replay can end cleanly (feature 251)"
            ) from exc

    def __enter__(self) -> Any:
        """The scope's binding — the resident array, while the read is live.

        Refuses on a released read (re-entering a spent scope is the
        use-after-release refusal, not a fresh hold), and answers the same
        object :attr:`returns` does.
        """
        return self.returns

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """The scope's exit — release what the block left held.

        Releases only if this read is still live, so a caller that released
        inside the block leaves the scope cleanly; never suppresses
        (returns ``None``), because a hold is a resource, not an error
        boundary.
        """
        if self._live:
            self.release()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        # Deliberately reads no hold and no array: a repr is a debugging
        # aid, and one that could refuse (a released pin's property, a
        # broken residence) would raise a *second* refusal while an operator
        # was already looking at the first, which is the worst moment for it.
        return (
            f"ReplayReturns(campaign={self._campaign_id!r}, "
            f"axis={self._horizon!r}, released={not self._live})"
        )


# -- the reads ---------------------------------------------------------------------------


def _pinned(pins: Any, campaign: str, horizon: int | None) -> Any:
    """Pin one axis through the resident arena — the duck-typed seam read.

    The one place the arena is touched: its ``pin`` verb is looked up,
    called, and whatever it answers is handed back for :func:`_held_array`
    to read.  A carrier that cannot pin is refused here naming what
    arrived, and the arena's own refusal — whatever class it raised, the
    artifacts member's vocabulary included — is translated here into this
    member's, chained to the original, because a caller catching
    ``ReplayError`` must catch a campaign no replay can read; letting the
    sibling's class escape would defeat the single ``except`` the member's
    whole error vocabulary exists to give.
    """
    pin_verb = getattr(pins, "pin", None)
    if not callable(pin_verb):
        raise ReplayReturnsError(
            f"the replay's campaign returns are read through a resident pin "
            f"arena — got {pins!r} ({type(pins).__name__}), which has no "
            "pin(); the arena is the resident half of docs §9.3's "
            "instruction ('load each campaign's signal returns once ... and "
            "pin it in RAM' — feature 175's CampaignPins), the replay path "
            "never reads Parquet itself (not even once, feature 251), and a "
            "carrier that cannot pin an axis names no resident array a "
            "replay could read. Hand the arena, and let it load"
        )
    try:
        return pin_verb(campaign, horizon=horizon)
    except ReplayError:
        raise
    except Exception as exc:
        raise ReplayReturnsError(
            f"the resident arena could not pin campaign {campaign!r} "
            f"({_axis_name(horizon)}): its pin() raised {exc!r}. A replay "
            "reads campaign returns from the pinned resident array, and the "
            "pin is where the residence begins — feature 175's arena loading "
            "through feature 174's load, the one decoder it trusts — so a "
            "pin that refuses is a campaign this replay cannot read; the "
            "repair is the store's (the original refusal is chained), never "
            "a loader handed to the read (feature 251)"
        ) from exc


def _held_array(hold: Any, campaign: str, horizon: int | None) -> Any:
    """The resident array off the hold — validated as it is read.

    Reads the two things the read needs for its lifetime — the hold's
    ``returns`` (the array this replay will answer on every access) and its
    ``release`` (how the scope ends) — and validates that what it read is
    the dense resident array §9.3 pins: the campaign it names, its two
    axes, and a contiguous buffer and not a Parquet spelling wearing one.
    The checks are the seam's own reads and nothing deeper: the load's
    internal laws (the typecode, the cells-by-axes arithmetic, the NaN
    policy) are feature 174's, validated at that member's construction, and
    a second statement of them here would be a second thing to drift.
    """
    release = getattr(hold, "release", None)
    if not callable(release):
        raise ReplayReturnsError(
            f"a resident hold is a counted share with a release — got "
            f"{hold!r} ({type(hold).__name__}), which has no release(); a "
            "replay's read is a scope (it pins at the start and lets go at "
            "the end, returning the RAM §9.3 prices), so a hold that cannot "
            "let go is a residence no replay can end cleanly (feature 251)"
        )
    try:
        resident = hold.returns
    except ReplayError:
        raise
    except Exception as exc:
        raise ReplayReturnsError(
            f"the resident hold on campaign {campaign!r} "
            f"({_axis_name(horizon)}) could not answer its array: its "
            f"returns raised {exc!r}. A replay reads the pinned resident "
            "array off the hold exactly once (feature 251), so a hold with "
            "no answer names no campaign this replay could read"
        ) from exc
    _is_dense_resident(resident, campaign, horizon)
    return resident


def _is_dense_resident(resident: Any, campaign: str, horizon: int | None) -> None:
    """Refuse an answer that is not the dense resident array — as it is read.

    The duck-typed shape feature 174's :class:`~artifacts.CampaignReturns`
    ships, checked by the reads this seam performs and nothing more: the
    campaign it names (agreeing with the ask — a hold answering another
    campaign's array is the arena's bug, and a replay scoring one campaign
    off another's rows would be measuring the wrong world), the row axis
    (a non-empty sequence of node ids), the column axis (a non-empty
    sequence of dates) and the buffer (a contiguous resident value with a
    cell width and a length — the spelling a Parquet *file path*, a lazy
    reader or a bare mapping all lack, which is the point: a hold that
    answers one of those is the naive read wearing the pin's name).
    """
    if resident is None or isinstance(resident, (str, bytes)):
        raise ReplayReturnsError(
            f"the resident hold on campaign {campaign!r} ({_axis_name(horizon)}) "
            f"answered {resident!r} ({type(resident).__name__}) in place of "
            "the dense resident array. The replay reads a pinned "
            "(nodes × periods) float32 buffer (§9.3, feature 174's load, "
            "feature 175's pin) — a value that is not one is the Parquet "
            "side of the seam wearing the resident side's name, and scoring "
            "off it would be the per-replay sweep feature 251 refuses"
        )
    named = getattr(resident, "campaign_id", None)
    if not isinstance(named, str) or not named.strip():
        raise ReplayReturnsError(
            f"the resident array of campaign {campaign!r} names its own "
            f"campaign — got {named!r}; §9.3's array is one campaign's "
            "returns as one sealed snapshot measured them, and an array "
            "that cannot say which campaign it is an array of is one no "
            "replay can score (feature 251)"
        )
    if named != campaign:
        raise ReplayReturnsError(
            f"the resident hold asked for campaign {campaign!r} "
            f"({_axis_name(horizon)}) answered the array of {named!r}: a "
            "replay scores the campaign it asked for — an arena that hands "
            "one campaign's rows out for another's ask is broken at the "
            "residence, and the replay must refuse rather than measure the "
            "wrong world (feature 251)"
        )
    node_ids = getattr(resident, "node_ids", None)
    if (
        isinstance(node_ids, (str, bytes))
        or not isinstance(node_ids, Sequence)
        or not node_ids
        or any(
            not isinstance(node, str) or not node.strip() for node in node_ids
        )
    ):
        raise ReplayReturnsError(
            f"the resident array of campaign {campaign!r} carries its row "
            f"axis — the campaign's node ids, sorted; got {node_ids!r}. "
            "A replay addresses a node's T-vector by its row, so an axis "
            "that names no rows is an array no walk could index (feature 251)"
        )
    periods = getattr(resident, "periods", None)
    if (
        isinstance(periods, (str, bytes))
        or not isinstance(periods, Sequence)
        or not periods
        or any(not isinstance(day, dt.date) for day in periods)
    ):
        raise ReplayReturnsError(
            f"the resident array of campaign {campaign!r} carries its "
            f"column axis — the rebalance dates the panels priced; got "
            f"{periods!r}. The market calendar is the axis ir_marginal "
            "sits on (§9.3), and an axis that is not one is an array no "
            "metric is defined over (feature 251)"
        )
    values = getattr(resident, "values", None)
    itemsize = getattr(values, "itemsize", None)
    if (
        values is None
        or not isinstance(itemsize, int)
        or itemsize <= 0
        or not hasattr(values, "__len__")
    ):
        raise ReplayReturnsError(
            f"the resident array of campaign {campaign!r} carries its "
            "buffer — a contiguous, cell-addressable float32 value (§9.3's "
            f"(nodes × T) × 4 B payload); got {values!r} "
            f"({type(values).__name__}). The buffer is what makes a replay "
            "'array indexing plus a rank-1 update' (§9.3) rather than an "
            "I/O per read, and any other spelling of it is not the thing "
            "§9.3 says to pin (feature 251)"
        )


def _campaign_id_of(value: Any) -> str:
    """A campaign id, validated — or refused naming what carried it.

    A non-empty string and nothing else: the id is the first key of the
    axis a read pins and the name every refusal of the read carries, so a
    value that cannot be an id is refused here — before the arena is
    touched — rather than being pinned and silently answering nothing.
    """
    if not isinstance(value, str) or not value.strip():
        raise ReplayReturnsError(
            f"a campaign id is a non-empty string — got {value!r} "
            f"({type(value).__name__}), which names no campaign in the "
            "store. A replay's returns read pins the campaign's "
            "(campaign, horizon) axis, and an id that is not one names no "
            "axis to pin (feature 251)"
        )
    return value


def _horizon_of(value: Any) -> int:
    """A pinned horizon, validated — a positive period count or a refusal.

    The ask's own spelling: ``None`` (checked by the caller) is the policy
    axis, and an explicit horizon is a period count of at least one — the
    evaluator's own horizon grammar, refused here before the arena is
    touched so a malformed ask never becomes the arena's refusal to
    translate.
    """
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 1
    ):
        raise ReplayReturnsError(
            f"a pinned horizon is a positive period count — got {value!r} "
            f"({type(value).__name__}); horizon=None pins the policy axis "
            "(the load resolves the horizon policy) and an explicit "
            "horizon pins another axis of the same campaign, which a "
            "period count of at least one names (feature 251)"
        )
    return value


def _axis_name(horizon: int | None) -> str:
    """The horizon axis as a refusal names it."""
    return "the policy axis" if horizon is None else f"horizon {horizon}"


def _parquet_message(campaign_id: Any, load: Any) -> str:
    """The refusal for a handed-in loader — feature 251's one sentence.

    Spelled once, so the seam's refusal and any later reading of it agree.
    Names §9.3's number and the repair, because the caller who reached for
    a loader is the caller who has to move the read rather than retry it:
    the arena is where the load belongs (once per axis, feature 174's own
    decoder), and the replay reads what it pinned.
    """
    name = getattr(load, "__name__", None)
    if not isinstance(name, str) or not name.strip():
        name = type(load).__name__
    return (
        f"a replay was asked to read the campaign returns of {campaign_id!r} "
        f"from Parquet: it was handed a loader ({name}). The replay path "
        "reads campaign returns from the pinned resident array — docs §9.3: "
        "'Load each campaign's signal returns once as a single dense "
        "float32 array ... and pin it in RAM', and '200 worlds × 40 policy "
        "versions done naively is ~160 GB per dreaming cycle' — and §10.4's "
        "50 ms target premised the replay on 'pure array arithmetic over "
        "cached Parquet', so a Parquet sweep per replay is the bottleneck "
        "the resident arrays exist to remove and feature 253's "
        "recomputation_suspected alert exists to catch. Pin the campaign's "
        "axis in a resident pin arena (feature 175's CampaignPins, loading "
        "once through feature 174's load) and hand the arena to the "
        "replay's read (feature 251)"
    )
