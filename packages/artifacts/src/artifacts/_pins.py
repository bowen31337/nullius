"""The resident campaign pins — §9.3's hold, feature 175.

app_spec.xml, "Tree & Artifact Persistence", feature 175: *System pins
each loaded campaign array in memory, holding roughly 4 MB per campaign
of 500 nodes.*  docs/nullius-tech-architecture.md §9.3 states the
sentence as the second half of an instruction whose first half feature
174 already built — *"Load each campaign's signal returns once as a
single dense ``float32`` array of shape ``(nodes × T)`` and pin it in
RAM"* — and sizes the hold in the same breath::

    500 nodes × 2000 periods × 4 B  =  4 MB per campaign
    200 campaigns                    =  800 MB resident

A load that answered its array and dropped it (feature 174 alone) would
re-sweep the Parquet on every ask — the ~160 GB-per-cycle bottleneck
§9.3 opens with.  A cache that answered and never let go (feature 176)
would hold the RAM of every replay a process ever ran.  The pin is the
third thing, and it is a **counted hold**: :class:`CampaignPins` loads
the campaign through feature 174's load the *first* time a caller pins
its axis, counts every holder, answers each of them the same resident
object, and drops the buffer the moment the last holder lets go.

**A pin is a hold with a count, and the count is the design.**  §9.3
has replay precompute the book's Cholesky factor once and turn every
candidate into a rank-1 update — which means several consumers within
one replay hold the *same* campaign array at once: the sweep that
revealed the nodes, feature 177's factor, feature 178's updates.  The
count lets each of them pin and release in any order, without any one
of them owning the buffer's lifetime: the array is resident exactly as
long as at least one holder holds it — no shorter (an early release
never drops a buffer another holder is still indexing into) and no
longer (the hold ends as designed as it began: the entry disappears,
the footprint is returned, and the next pin re-loads through the
store, which stays the truth and which feature 174 keeps deterministic
— two loads of one campaign answer the same array).  Nothing is
evicted while held, because the arena has no opinion about which hold
matters; nothing arrives unasked, because an entry appears exactly
when a caller pins its key.

**The hold is measured, not estimated.**  §9.3's sizing is an
observable here, spelled once: :data:`CAMPAIGN_SIZING_NODES` nodes ×
:data:`CAMPAIGN_SIZING_PERIODS` periods × 4 B =
:data:`CAMPAIGN_SIZING_FOOTPRINT_BYTES` — the campaign §9.3 describes
answers exactly ``4_000_000`` bytes from
:attr:`CampaignReturns.footprint_bytes <artifacts.CampaignReturns.
footprint_bytes>` (§9.3's "4 MB" is the decimal megabyte its
arithmetic writes), and the arena's :attr:`CampaignPins.footprint_bytes`
is the *sum* over its residence — so the second line of §9.3's table,
*200 campaigns = 800 MB resident*, is a number an operator reads off
the arena before sizing a box, not a hope.  A refused load pins
nothing, so the footprint counts measurements, not attempts; a
released hold weighs nothing, because the arena no longer holds it.

**Two residences, two policies, one decoder.**  This arena sits beside
feature 176's :class:`~artifacts.ReturnSeriesCache` deliberately: both
load through feature 174's load (there is no second decoder to trust,
so every refusal of the load — a campaign holding no node directories,
a horizon some panel covers no date of, panels from different sealed
worlds — refuses the pin unchanged, in the load's own vocabulary) and
both key their residence by exactly the ask, ``(campaign_id,
horizon)``.  They differ in what they own.  The cache owns the
*content* policy — which value may reside: the return series, never a
marginal information ratio keyed against a canonical book — and its
residence is its own lifetime; it never lets go.  The pins own the
*lifetime* policy — how long a hold lasts, namely while a holder holds
it — and the measurement of what the hold weighs.  A caller that wants
an answer forever holds a cache; a caller — a replay, or any holder
within one — that wants the RAM back when it is done holds pins.

**The handle is honest, in both directions.**  A :class:`CampaignPin`
vouches for its hold, so it stops vouching the moment it is released:
``pin.returns`` refuses after release (a handle that kept answering
would hold the buffer outside the accounting that was the point of
releasing it), a second ``release()`` refuses (the first release
already spent this hold, and a second would subtract one of the
holders that still hold the array), and the ``with`` scope releases
exactly what the block left held, so a caller that releases early
leaves the scope cleanly.  The refusals are
:class:`~artifacts._errors.ArtifactPinError`, this feature's own class
in the member's taxonomy, naming the campaign and the horizon axis
they are about.

**Per-replay state, no lock, and the store stays the truth.**  §9.3
pins arrays per replay and §10.4 pins a replay to a single core, so
the arena takes no lock for the same reason the store's own listings
take none.  The arena is built by the replay that holds it and never
handed to another: two arenas over one store are two residences, and a
fresh arena answers a fresh load — a node published since a hold was
taken is invisible to the resident array (it answers the campaign that
existed when it was pinned, which existed) and visible to the next pin
after the last release.  Both are correct, because both answer a
campaign that existed; the store is the truth each of them loaded.
"""

from __future__ import annotations

from types import TracebackType

from ._campaign import CampaignReturns, load_campaign_returns
from ._errors import ArtifactPinError
from ._keys import validate_campaign_id
from ._returns import _validated_horizon
from ._store import ArtifactStore

__all__ = [
    "CAMPAIGN_SIZING_FOOTPRINT_BYTES",
    "CAMPAIGN_SIZING_NODES",
    "CAMPAIGN_SIZING_PERIODS",
    "RESIDENT_PIN_POLICY",
    "CampaignPin",
    "CampaignPins",
]

#: The row count of the campaign §9.3 sizes its residency by — "500
#: nodes per campaign" is the first term of its arithmetic, and the
#: term a deployment's node budget answers to: the sizing is not a
#: ceiling anyone enforces here (the arena holds what its holders pin,
#: and measures it), it is the shape the §9.3 replay is designed
#: around, spelled once so the sizing constant, the docstrings and the
#: tests cannot drift apart on which campaign "roughly 4 MB" describes.
CAMPAIGN_SIZING_NODES = 500

#: The column count of the same sizing — "2000 periods", the T of
#: §9.3's ``(nodes × T)``.  The daily rebalance calendar of the sizing
#: campaign; feature 180's downsample exists because the intraday
#: scaling caveat (``T ≈ 200,000``) multiplies this term by 100, which
#: is the recorded reason that caveat is a *caveat* and not a silent
#: surprise in the footprint.
CAMPAIGN_SIZING_PERIODS = 2000

#: §9.3's sizing as one number — 500 nodes × 2000 periods × 4 B, the
#: "roughly 4 MB per campaign" of the feature's own sentence.  §9.3's
#: "MB" is the decimal megabyte its arithmetic writes (4,000,000 bytes
#: ≈ 3.81 MiB), which is why the sentence says *roughly*: a
#: :class:`~artifacts.CampaignReturns` of exactly the sizing shape
#: answers exactly this from
#: :attr:`~artifacts.CampaignReturns.footprint_bytes`, and 200 of them
#: answer 800,000,000 — §9.3's "800 MB resident" — summed by the
#: arena.
CAMPAIGN_SIZING_FOOTPRINT_BYTES = 4_000_000

#: The arena's hold policy, spelled once the way
#: :data:`~artifacts.CAMPAIGN_LOAD_HORIZON` and
#: :data:`~artifacts.RESIDENT_CACHE_POLICY` spell theirs: a sentence,
#: not a type, because it is the *decision* the feature's sentence
#: pins and every seam that states it (the arena's docstrings, the
#: handle's, the tests) quotes this one spelling of it.
RESIDENT_PIN_POLICY: str = (
    "pin each loaded campaign array in RAM while a holder holds it — "
    "roughly 4 MB per campaign of 500 nodes — and let go when the last "
    "holder does"
)


# -- The arena -----------------------------------------------------------------------


class CampaignPins:
    """§9.3's pin arena: each loaded campaign array, held while held.

    The object a replay holds for the duration of its run.  ``pin`` is
    the whole grammar: the first pin of a ``(campaign, horizon)`` axis
    loads through feature 174's
    :func:`~artifacts.load_campaign_returns` (the only decoder this
    arena trusts), every pin of that axis while it is resident answers
    the *same* :class:`~artifacts.CampaignReturns` object with no
    second sweep, and the last :meth:`CampaignPin.release` drops the
    entry — the hold, its footprint and all — so the RAM is returned
    exactly when the holders are done with it.

    The residence is observable and honest: :meth:`holds` and
    :meth:`pin_count` answer from the residence alone (no store touch,
    no load), :meth:`resident_campaigns` lists the held campaigns
    sorted each once across the pinned axes, and
    :attr:`footprint_bytes` is the sum of what the held arrays weigh —
    the §9.3 arithmetic an operator reads before sizing a box.  A load
    that refuses pins nothing, and a hold that ended weighs nothing.

    The arena is per-replay state, not a composed component and not a
    correction of the store: no ``@register`` builder (composition must
    be safe in any environment, and a pin arena is built by the replay
    that holds it), no lock (§10.4 pins a replay to a single core), and
    no eviction policy (nothing is dropped while a holder holds it;
    nothing arrives but a ``pin``).
    """

    def __init__(self, store: ArtifactStore) -> None:
        if not isinstance(store, ArtifactStore):
            raise ArtifactPinError(
                "a resident campaign pin arena is bound to one "
                f"ArtifactStore — got {type(store).__name__} {store!r}; the "
                "arena loads campaigns through the store's read side and "
                "feature 174's load (there is no second decoder to trust), "
                "so an arena without that store is an arena nothing can be "
                "pinned in"
            )
        self._store = store
        #: The residence: ``(campaign_id, horizon)`` → the resident
        #: array and its holder count.  Private for the same reason the
        #: cache's is: a caller who could reach this mapping could hold
        #: a buffer outside the accounting that releasing is.
        self._resident: dict[tuple[str, int | None], _PinnedArray] = {}

    @property
    def store(self) -> ArtifactStore:
        """The store this arena loads through — the truth it holds from."""
        return self._store

    def pin(
        self, campaign_id: str, *, horizon: int | None = None
    ) -> CampaignPin:
        """Pin one campaign axis — load once, answer resident while held.

        The first pin of ``(campaign_id, horizon)`` runs feature 174's
        :func:`~artifacts.load_campaign_returns` over the bound store —
        the only decoder this arena trusts, so every refusal of the
        load (a campaign holding no node directories, a node without
        its grid, panels from different sealed worlds, a horizon some
        panel covers no date of) refuses this pin unchanged, exactly as
        a direct load would answer it, and pins nothing.  Every pin of
        the axis while it is resident — including the very next one —
        answers the same resident object with no second Parquet sweep:
        that residence, not the load, is what the returned
        :class:`CampaignPin` vouches for.

        ``horizon`` is feature 174's own knob with its own meaning:
        ``None`` (the default) is the policy axis
        :data:`~artifacts.CAMPAIGN_LOAD_HORIZON` resolves; an explicit
        horizon pins another axis, its own resident entry, held under
        its own key — the same key spelling the resident cache uses,
        because the ask is the same ask.
        """
        campaign = validate_campaign_id(campaign_id)
        pinned = None if horizon is None else _validated_horizon(horizon)
        key = (campaign, pinned)
        entry = self._resident.get(key)
        if entry is None:
            # The entry appears only after the load answered, so a load
            # that refuses leaves the residence exactly what it was —
            # the arena holds measurements, not attempts.
            entry = _PinnedArray(
                load_campaign_returns(self._store, campaign, horizon=pinned)
            )
            self._resident[key] = entry
        entry.holders += 1
        return CampaignPin(self, campaign, pinned, entry.returns)

    def holds(
        self, campaign_id: str, *, horizon: int | None = None
    ) -> bool:
        """Whether the ``(campaign_id, horizon)`` axis is currently held.

        Answered from the residence alone: ``False`` touches no store
        and loads nothing, and means no live holder holds the axis —
        either it was never pinned or the last holder released, and
        both are "not held" to a caller deciding whether to pin.
        """
        campaign = validate_campaign_id(campaign_id)
        pinned = None if horizon is None else _validated_horizon(horizon)
        return (campaign, pinned) in self._resident

    def pin_count(
        self, campaign_id: str, *, horizon: int | None = None
    ) -> int:
        """How many handles hold the ``(campaign_id, horizon)`` axis.

        The count behind the hold: one per live :class:`CampaignPin`,
        so a holder deciding whether its release will drop the array —
        or a test deciding whether the arena is honest about one —
        reads it here.  ``0`` for an axis nothing holds, exactly like
        an axis never pinned.
        """
        campaign = validate_campaign_id(campaign_id)
        pinned = None if horizon is None else _validated_horizon(horizon)
        entry = self._resident.get((campaign, pinned))
        return 0 if entry is None else entry.holders

    def resident_campaigns(self) -> tuple[str, ...]:
        """The campaigns this arena holds, sorted, each campaign once.

        The operator's listing, the cache's own discipline: the
        campaign axis of the residence, deduplicated across the horizon
        axes the holders pinned, in sorted order — the order of a
        listing is part of what it is being used *for*, and an operator
        comparing listings across replays compares content, never
        iteration order.
        """
        return tuple(sorted({campaign for campaign, _ in self._resident}))

    @property
    def footprint_bytes(self) -> int:
        """What the residence weighs — the sum of the held arrays.

        §9.3's second line made observable: each held campaign answers
        its own :attr:`CampaignReturns.footprint_bytes
        <artifacts.CampaignReturns.footprint_bytes>` (cells × 4 B), and
        this is their sum — ``0`` for an arena nothing holds, 4 MB per
        held campaign of §9.3's sizing, 800 MB for the 200 §9.3 prices
        a dreaming cycle's pool at.  Released holds stop counting the
        moment they release, because the residence is what is measured,
        not what was ever pinned.
        """
        return sum(
            entry.returns.footprint_bytes for entry in self._resident.values()
        )

    def _release(self, campaign_id: str, horizon: int | None) -> None:
        """Spend one holder of the axis — drop the entry at zero.

        The handle's release, spelled on the arena that owns the
        residence: decrement the count, and when it reaches zero delete
        the entry so the buffer and its footprint are the garbage
        collector's to take — the hold ended, and the arena no longer
        vouches for the array.  Only a live handle reaches here (the
        handle refuses its own second release), so the count is always
        the number of live handles.
        """
        entry = self._resident[(campaign_id, horizon)]
        entry.holders -= 1
        if entry.holders == 0:
            del self._resident[(campaign_id, horizon)]


# -- The handle ----------------------------------------------------------------------


class CampaignPin:
    """One holder's hold on one resident campaign array.

    What :meth:`CampaignPins.pin` answers: the voucher, not the value.
    While it is live, :attr:`returns` is the resident
    :class:`~artifacts.CampaignReturns` this handle holds a counted
    share of — the same object every other holder of the axis holds —
    and :attr:`footprint_bytes` is what that share keeps resident.
    Released (explicitly, or by leaving the ``with`` scope), the pin
    vouches for nothing: :attr:`returns` refuses rather than answering
    a buffer outside the accounting, and a second :meth:`release`
    refuses rather than subtracting a hold this handle already spent.

    Usable as a context manager — ``with pins.pin(campaign) as array:``
    — because a hold is a scope: the block pins, the block's exit
    releases what the block left held, and a caller that released
    early inside the block leaves the scope cleanly rather than
    tripping the double-release refusal on the way out.
    """

    __slots__ = ("_arena", "_campaign_id", "_horizon", "_live", "_returns")

    def __init__(
        self,
        arena: CampaignPins,
        campaign_id: str,
        horizon: int | None,
        returns: CampaignReturns,
    ) -> None:
        self._arena = arena
        self._campaign_id = campaign_id
        self._horizon = horizon
        self._returns = returns
        self._live = True

    @property
    def campaign_id(self) -> str:
        """The campaign this hold is on — the first key of the ask."""
        return self._campaign_id

    @property
    def horizon(self) -> int | None:
        """The horizon axis this hold is on — the ask's own spelling.

        ``None`` for the policy axis (the load resolved
        :data:`~artifacts.CAMPAIGN_LOAD_HORIZON`), the pinned horizon
        otherwise; the *resolved* horizon is always
        ``pin.returns.horizon``.  Carried so a holder juggling several
        pins can say which axis of which campaign a refusal is about.
        """
        return self._horizon

    @property
    def released(self) -> bool:
        """Whether this handle has spent its hold."""
        return not self._live

    @property
    def returns(self) -> CampaignReturns:
        """The resident campaign array this handle holds a share of.

        The same object every live holder of the axis holds, and the
        object the arena loaded once — resident, so it answers even
        after the campaign's directory is deleted under it, which is
        the whole point of pinning.  Refuses once released:
        :class:`~artifacts._errors.ArtifactPinError`, naming the
        campaign and axis, because a handle that kept answering would
        be holding the buffer outside the count that releasing exists
        to keep honest.
        """
        if not self._live:
            raise ArtifactPinError(
                f"this pin on campaign {self._campaign_id!r} "
                f"({self._axis_spelling}) was released, and a released pin "
                "vouches for no hold — the arena's accounting stopped "
                "counting this handle when it let go; pin the axis again "
                "(CampaignPins.pin) for a hold that is live"
            )
        return self._returns

    @property
    def footprint_bytes(self) -> int:
        """What this hold keeps resident — the array's own footprint.

        Delegates to :attr:`CampaignReturns.footprint_bytes
        <artifacts.CampaignReturns.footprint_bytes>` (cells × 4 B, the
        §9.3 arithmetic), and refuses once released for the same reason
        :attr:`returns` does: a hold that ended weighs nothing, and a
        handle that kept quoting a footprint would be pretending it
        still held one.
        """
        return self.returns.footprint_bytes

    @property
    def _axis_spelling(self) -> str:
        """The horizon axis as a message names it."""
        return (
            "the policy axis" if self._horizon is None
            else f"horizon {self._horizon}"
        )

    def release(self) -> None:
        """Let go — spend this handle's hold on the resident array.

        Decrements the axis's holder count; if other holders remain,
        the array stays resident for them (an early release never drops
        a buffer someone else is still indexing into); if this was the
        last, the arena drops the entry and its footprint — the RAM is
        returned exactly when the holders are done.  A second release
        refuses, because the first one already spent this hold and a
        second would subtract one of the holders that still hold.
        """
        if not self._live:
            raise ArtifactPinError(
                f"this pin on campaign {self._campaign_id!r} "
                f"({self._axis_spelling}) was already released; a pin is "
                "released exactly once — the release that already happened "
                "spent this hold, and a second would subtract one of the "
                "holders that still hold the array"
            )
        self._live = False
        self._arena._release(self._campaign_id, self._horizon)

    def __enter__(self) -> CampaignReturns:
        """The scope's binding — the resident array, while the pin is live.

        Refuses on a released pin (re-entering a spent scope is the
        use-after-release refusal, not a fresh hold), and answers the
        same object :attr:`returns` does.
        """
        return self.returns

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """The scope's exit — release what the block left held.

        Releases only if this handle is still live, so a caller that
        released inside the block leaves the scope cleanly; never
        suppresses (returns ``None``), because a hold is a resource,
        not an error boundary.
        """
        if self._live:
            self.release()


# -- The residence entry ---------------------------------------------------------------


class _PinnedArray:
    """One resident campaign array and the count of handles holding it.

    The arena's private entry: the loaded :class:`CampaignReturns` and
    ``holders``, the number of live :class:`CampaignPin` handles on its
    axis.  An entry exists exactly while ``holders ≥ 1`` — it is
    created by the first pin and deleted by the last release — so its
    presence in the residence *is* the hold.
    """

    __slots__ = ("holders", "returns")

    def __init__(self, returns: CampaignReturns) -> None:
        self.returns = returns
        self.holders = 0
