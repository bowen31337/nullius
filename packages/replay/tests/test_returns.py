"""Feature 251 — the replay reads campaign returns from the pinned resident
array.

app_spec.xml, "Replay Engine", feature 251: *System reads campaign returns
from the pinned resident array rather than from Parquet on each replay.*
docs/nullius-tech-architecture.md §9.3 states the number the naive reading
costs (*"200 worlds × 40 policy versions done naively is ~160 GB per
dreaming cycle"*) and the instruction this read is the replay-side half of
(*"Load each campaign's signal returns once as a single dense ``float32``
array ... and pin it in RAM"*); §10.4 states the premise the 50 ms target
rests on (*"a replay is pure array arithmetic over cached Parquet"*).

These tests pin the feature as the facts it is made of, in the order a
replay meets them:

* **the refusal** — a read handed a loader is refused *before the campaign
  is validated, before the arena is touched and before the loader is
  called*, because a read that swept Parquet first would have spent the I/O
  it was refusing to spend.  This is the feature's "rather than" and the
  first thing pinned here;
* **the read is resident** — the first read pins through the arena, every
  later read of a held axis shares the one resident object with no second
  sweep, and the read answers that same object for its whole lifetime;
* **the read is a scope** — release ends the hold, the ``with`` block
  releases on exit, and the next read after the last release loads again
  (the store stays the truth);
* **the handle is honest** — a released read refuses to answer, a second
  release refuses, and a spent scope refuses re-entry;
* **the vocabularies are kept straight** — the arena's own refusals arrive
  in this member's vocabulary (catchable as ``ReplayError``, chained to the
  original), a carrier that cannot pin is refused naming the law, and a
  malformed campaign or horizon is refused before the arena is touched;
* **the resident answer is the dense array** — a hold answering a path, a
  bare value or another campaign's array is refused, because each is the
  Parquet side of the seam wearing the resident side's name;
* **the composed component is the same act** — the facade's verb answers
  the same resident object and refuses the same refusal, so there is no
  route to a Parquet read by holding the component;
* **the real cross-member seam** — the artifacts member's own
  ``CampaignPins`` and ``CampaignReturns`` (reached the way a deployment
  reaches them, never imported by the member itself) are read end to end,
  including the proof the answer came from RAM: the campaign's directory
  deleted under the hold, the read still answers, a direct load refuses.

The fixtures below restate the artifacts member's shapes here — the dense
record, the counted hold, the arena — because a member never imports
another member, and the restatement is what makes the duck-typed seam
testable: the doubles count their loads, so "no second sweep" is an
observable, not an assertion about someone else's code.
"""

from __future__ import annotations

import array as _array
import datetime as dt
import shutil
from pathlib import Path
from typing import Any

import pytest
from replay import (
    RESIDENT_READ_POLICY,
    ParquetReadRefused,
    ReplayEngine,
    ReplayError,
    ReplayReturns,
    ReplayReturnsError,
    resident_returns,
)

D1 = dt.date(2026, 1, 5)
D2 = dt.date(2026, 1, 6)
D3 = dt.date(2026, 1, 7)


# ---------------------------------------------------------------------------
# The restated shapes — feature 174's record, 175's hold and arena
# ---------------------------------------------------------------------------


class ForeignPinError(Exception):
    """The hold's own spent-share refusal — a foreign vocabulary on purpose.

    The real pin raises the artifacts member's ``ArtifactPinError``; this
    class is deliberately *not* a ``ReplayError``, so the translation tests
    exercise a genuinely foreign failure crossing the seam rather than one
    the member would catch anyway.
    """


class ForeignLoadError(Exception):
    """The arena's own load refusal — a foreign vocabulary on purpose."""


class ResidentArray:
    """The dense resident record — feature 174's ``CampaignReturns``, restated.

    Carries exactly what the seam reads: the campaign it names, the two
    axes, and the contiguous float32 buffer §9.3 sizes.  Nothing downstream
    of the seam may care about more, which is the point of restating it.
    """

    __slots__ = ("campaign_id", "horizon", "node_ids", "periods", "values")

    def __init__(
        self,
        campaign_id: str,
        node_ids: tuple[str, ...],
        periods: tuple[dt.date, ...],
        horizon: int = 1,
    ) -> None:
        self.campaign_id = campaign_id
        self.horizon = horizon
        self.node_ids = node_ids
        self.periods = periods
        self.values = _array.array("f", [0.0] * (len(node_ids) * len(periods)))


class HeldShare:
    """One holder's counted share — feature 175's ``CampaignPin``, restated.

    ``returns`` refuses once released with its *own* class (the handle's
    honesty in the member that owns it), so a seam that leaked the hold's
    refusal would hand a caller a foreign error — which is precisely what
    the translation tests refuse to let happen.
    """

    __slots__ = ("_arena", "_axis", "_live", "_returns")

    def __init__(
        self, arena: PinArena, axis: tuple[str, int | None], returns: Any
    ) -> None:
        self._arena = arena
        self._axis = axis
        self._returns = returns
        self._live = True

    @property
    def returns(self) -> Any:
        if not self._live:
            raise ForeignPinError(f"the pin on {self._axis!r} was released")
        return self._returns

    def release(self) -> None:
        if not self._live:
            raise ForeignPinError(
                f"the pin on {self._axis!r} was already released"
            )
        self._live = False
        self._arena._spend(self._axis)


class PinArena:
    """The resident pin arena — feature 175's ``CampaignPins``, restated.

    The shape the seam promises (``pin(campaign_id, *, horizon=None)`` and
    the counted residence behind it), plus the observables these tests
    need: ``loads`` counts the first-pin sweeps (the Parquet reads the
    feature refuses to repeat) and ``pin_calls`` counts every ask, so
    "the arena was never touched" and "no second sweep" are both facts the
    tests read off the double rather than trust.
    """

    def __init__(self) -> None:
        self._resident: dict[tuple[str, int | None], ResidentArray] = {}
        self._holders: dict[tuple[str, int | None], int] = {}
        #: How many first-pin loads this arena has run — one per axis.
        self.loads = 0
        #: How many ``pin`` asks reached this arena, refused or not.
        self.pin_calls = 0
        #: Set to make the next first-pin load refuse with a foreign error.
        self.refusal: Exception | None = None

    def pin(
        self, campaign_id: str, *, horizon: int | None = None
    ) -> HeldShare:
        self.pin_calls += 1
        axis = (campaign_id, horizon)
        resident = self._resident.get(axis)
        if resident is None:
            if self.refusal is not None:
                raise self.refusal
            self.loads += 1
            resident = ResidentArray(
                campaign_id, ("node-a", "node-b"), (D1, D2, D3)
            )
            self._resident[axis] = resident
        self._holders[axis] = self._holders.get(axis, 0) + 1
        return HeldShare(self, axis, resident)

    def holds(self, campaign_id: str, *, horizon: int | None = None) -> bool:
        return self._holders.get((campaign_id, horizon), 0) > 0

    def pin_count(
        self, campaign_id: str, *, horizon: int | None = None
    ) -> int:
        return self._holders.get((campaign_id, horizon), 0)

    def resident_of(
        self, campaign_id: str, *, horizon: int | None = None
    ) -> Any:
        """The arena's own resident object for an axis — the identity oracle."""
        return self._resident.get((campaign_id, horizon))

    def _spend(self, axis: tuple[str, int | None]) -> None:
        self._holders[axis] -= 1
        if self._holders[axis] == 0:
            del self._holders[axis]
            del self._resident[axis]


@pytest.fixture
def arena() -> PinArena:
    """A resident pin arena holding nothing — the replay's resident side."""
    return PinArena()


@pytest.fixture
def campaign_id() -> str:
    """A campaign id — §9.2's first key, spelled as the store spells it."""
    return "0e0e0e0e-1111-4aaa-8bbb-cccddd000001"


# ---------------------------------------------------------------------------
# The refusal — feature 251's "rather than"
# ---------------------------------------------------------------------------


def test_a_loader_is_refused(arena: PinArena, campaign_id: str) -> None:
    # app_spec.xml feature 251: "System reads campaign returns from the
    # pinned resident array rather than from Parquet on each replay."  The
    # read's one verb is where a Parquet sweep could enter — a `load` is
    # the callable shape of the sweep (feature 174's
    # load_campaign_returns(store, campaign, horizon=...) being its
    # spelling) — and handing one in is that read.
    with pytest.raises(ParquetReadRefused):
        resident_returns(arena, campaign_id, load=lambda store, c: None)


def test_the_refusal_fires_before_anything(
    arena: PinArena, campaign_id: str
) -> None:
    # The order is the feature, and it is feature 245's ordering for the
    # same reason: a read that swept Parquet first and raised afterwards
    # would have spent the I/O it was refusing to spend.  Pinned three ways
    # at once — the loader is never called, the arena is never touched, and
    # even a malformed campaign id does not get its own refusal first
    # (the Parquet refusal is the one that names the broken *call*).
    calls: list[str] = []

    def loader(*args: Any, **kwargs: Any) -> None:  # pragma: no cover
        calls.append("the loader ran")

    with pytest.raises(ParquetReadRefused):
        resident_returns(arena, "   ", load=loader)
    assert calls == []
    assert arena.pin_calls == 0
    assert arena.loads == 0


def test_the_refusal_names_the_law_and_the_repair(
    arena: PinArena, campaign_id: str
) -> None:
    # The caller who reached for a loader is the caller who has to move the
    # read, not retry it: the message names §9.3's instruction, the number
    # the naive reading costs, the repair (pin through a resident arena) and
    # the loader it refuses, so an operator reading it knows which knob
    # turned wrong.
    with pytest.raises(ParquetReadRefused) as raised:
        resident_returns(arena, campaign_id, load=load_campaign_returns_shaped)
    message = str(raised.value)
    assert campaign_id in message
    assert "load_campaign_returns_shaped" in message
    assert "pinned resident array" in message
    assert "160 GB" in message
    assert "feature 251" in message


def load_campaign_returns_shaped(*args: Any, **kwargs: Any) -> None:
    """A loader named the way feature 174's own load is — for the message."""
    raise AssertionError("never called")  # pragma: no cover


def test_the_refusal_is_not_a_resident_failure(
    arena: PinArena, campaign_id: str
) -> None:
    # The non-nesting is load-bearing, the same way
    # ChildGenerationRefused's is: a dreaming loop that catches
    # ReplayReturnsError to skip an unreadable campaign must not silently
    # skip the refusal that says the replay path has no Parquet spelling at
    # all — that one is not a fact about the campaign, and the skip would
    # hide a broken caller from every campaign in the pool.
    assert not issubclass(ParquetReadRefused, ReplayReturnsError)
    assert issubclass(ParquetReadRefused, ReplayError)
    with pytest.raises(ParquetReadRefused):
        try:
            resident_returns(arena, campaign_id, load=dict)
        except ReplayReturnsError:  # pragma: no cover - the wrong catch
            pytest.fail("the Parquet refusal escaped as a resident failure")


# ---------------------------------------------------------------------------
# The read is resident
# ---------------------------------------------------------------------------


def test_the_first_read_pins_through_the_arena(
    arena: PinArena, campaign_id: str
) -> None:
    # The affirmative half of the sentence: the replay's campaign-returns
    # read pins the campaign's axis through the resident arena — one load
    # on the first ask, and the array answered is the arena's own resident
    # object, not a copy and not a second decode.
    read = resident_returns(arena, campaign_id)
    assert isinstance(read, ReplayReturns)
    assert arena.loads == 1
    assert read.returns is arena.resident_of(campaign_id)
    assert read.returns.campaign_id == campaign_id


def test_a_second_read_of_a_held_axis_shares_the_resident_object(
    arena: PinArena, campaign_id: str
) -> None:
    # "Rather than from Parquet on each replay" made observable: two reads
    # over one arena and one held axis answer the *same* resident object —
    # identity, not an equal copy — and the arena loaded once.  The naive
    # reading (a sweep per replay) would show loads == 2 here.
    first = resident_returns(arena, campaign_id)
    second = resident_returns(arena, campaign_id)
    assert second.returns is first.returns
    assert arena.loads == 1
    assert arena.pin_count(campaign_id) == 2


def test_the_read_answers_one_object_for_its_lifetime(
    arena: PinArena, campaign_id: str
) -> None:
    # The replay's hundred score-time reads are a hundred answers of one
    # resident array: `.returns` answers the object read off the pin once,
    # at construction, so nothing downstream can drift into becoming a
    # second, Parquet-backed ask — and the arena is not asked again between
    # reads (pin_calls is frozen after the one pin that opened the read).
    read = resident_returns(arena, campaign_id)
    pins_after_open = arena.pin_calls
    resident = read.returns
    for _ in range(100):
        assert read.returns is resident
    assert arena.pin_calls == pins_after_open


def test_two_axes_are_two_reads_two_holds(
    arena: PinArena, campaign_id: str
) -> None:
    # The key is exactly the ask — (campaign, horizon) — so the policy axis
    # and a pinned horizon are two residences held independently, the same
    # spelling the arena and the resident cache key by.  A read that
    # answered one array for both axes would be collapsing the ask.
    policy = resident_returns(arena, campaign_id)
    pinned = resident_returns(arena, campaign_id, horizon=5)
    assert policy.horizon is None
    assert pinned.horizon == 5
    assert policy.returns is not pinned.returns
    assert arena.loads == 2
    policy.release()
    assert arena.holds(campaign_id, horizon=5)
    assert arena.pin_count(campaign_id) == 0


def test_two_campaigns_are_two_residences(
    arena: PinArena, campaign_id: str
) -> None:
    # §9.2's first key is the campaign, and the residence keys by it: two
    # campaigns pinned in one arena are two arrays and two loads — a
    # replay reading both worlds reads both campaigns' RAM, and never
    # confuses one world's rows with the other's.
    other = "0e0e0e0e-1111-4aaa-8bbb-cccddd000002"
    first = resident_returns(arena, campaign_id)
    second = resident_returns(arena, other)
    assert first.returns is not second.returns
    assert first.returns.campaign_id == campaign_id
    assert second.returns.campaign_id == other
    assert arena.loads == 2


# ---------------------------------------------------------------------------
# The read is a scope
# ---------------------------------------------------------------------------


def test_release_ends_the_hold_and_the_next_read_loads_again(
    arena: PinArena, campaign_id: str
) -> None:
    # The hold ends at release: the counted share returns to the arena (a
    # second holder would keep the array resident — pinned below elsewhere
    # — and the last release drops it), and the next read after the last
    # release loads again, because the store stays the truth (feature 175's
    # law, observed through this seam rather than assumed from it).  The
    # first read's object is captured before its release, because a
    # released read vouches for no array — the honesty pinned below.
    read = resident_returns(arena, campaign_id)
    first_object = read.returns
    assert arena.holds(campaign_id)
    read.release()
    assert read.released
    assert not arena.holds(campaign_id)
    again = resident_returns(arena, campaign_id)
    assert arena.loads == 2
    assert again.returns is not first_object


def test_an_early_release_never_drops_a_buffer_another_holder_holds(
    arena: PinArena, campaign_id: str
) -> None:
    # The count is the design (§9.3: several consumers within one replay
    # share the array): the sweep, the factor and the updates each hold a
    # share, let go in any order, and the array stays resident for whoever
    # remains — read through two ReplayReturns, the shapes this member
    # hands those consumers.
    sweep = resident_returns(arena, campaign_id)
    factor = resident_returns(arena, campaign_id)
    sweep.release()
    assert arena.holds(campaign_id)
    assert factor.returns is arena.resident_of(campaign_id)
    factor.release()
    assert not arena.holds(campaign_id)


def test_the_with_scope_pins_and_releases(
    arena: PinArena, campaign_id: str
) -> None:
    # A read is a scope: the block pins, the block's exit releases what the
    # block left held, and the binding is the resident array itself — the
    # object a score-time consumer indexes, with no second spelling to keep
    # in sync.
    with resident_returns(arena, campaign_id) as resident:
        assert arena.holds(campaign_id)
        assert resident is arena.resident_of(campaign_id)
    assert not arena.holds(campaign_id)


def test_an_early_release_inside_the_scope_leaves_it_cleanly(
    arena: PinArena, campaign_id: str
) -> None:
    # The scope releases only what the block left held: a caller that
    # releases inside the block leaves the `with` cleanly rather than
    # tripping the double-release refusal on the way out — the CampaignPin
    # pattern, kept by this member's own spelling of the handle.
    read = resident_returns(arena, campaign_id)
    with read:
        read.release()
    assert read.released
    assert not arena.holds(campaign_id)


# ---------------------------------------------------------------------------
# The handle is honest
# ---------------------------------------------------------------------------


def test_a_released_read_refuses_to_answer(
    arena: PinArena, campaign_id: str
) -> None:
    # A handle that kept answering after release would be holding the
    # buffer outside the accounting that releasing exists to keep honest.
    # The refusal is this member's own (the hold's foreign refusal never
    # crosses the seam) and names the campaign and the axis it is about.
    read = resident_returns(arena, campaign_id)
    read.release()
    with pytest.raises(ReplayReturnsError) as raised:
        read.returns
    message = str(raised.value)
    assert campaign_id in message
    assert "policy axis" in message


def test_a_second_release_refuses(
    arena: PinArena, campaign_id: str
) -> None:
    # The first release already spent this read's share; a second would
    # subtract one of the holders that still hold.  Refused in this
    # member's vocabulary before the hold is touched, so the arena's own
    # double-release refusal (a foreign class) is never the one a caller
    # meets here.
    read = resident_returns(arena, campaign_id)
    read.release()
    with pytest.raises(ReplayReturnsError):
        read.release()
    assert arena.pin_count(campaign_id) == 0


def test_a_released_scope_refuses_re_entry(
    arena: PinArena, campaign_id: str
) -> None:
    # Re-entering a spent scope is the use-after-release refusal, not a
    # fresh hold: the `with` statement asks for the binding, and a released
    # read must refuse to hand one over rather than mint a second hold the
    # caller never asked the arena for.
    read = resident_returns(arena, campaign_id)
    read.release()
    with pytest.raises(ReplayReturnsError):
        with read:  # pragma: no cover - refuses on entry
            pass


def test_the_repr_reads_nothing_it_could_fail_on(
    arena: PinArena, campaign_id: str
) -> None:
    # A repr is a debugging aid, and one that re-read the hold or the
    # array could raise a *second* refusal while an operator was already
    # looking at the first — the worst moment for it.  Pinned positively
    # (a released read still reprs) and by content (it names the campaign
    # and the axis).
    read = resident_returns(arena, campaign_id)
    assert campaign_id in repr(read)
    read.release()
    assert "released=True" in repr(read)


# ---------------------------------------------------------------------------
# The vocabularies — this member's, the arena's, and the seam between them
# ---------------------------------------------------------------------------


def test_the_arenas_refusal_arrives_in_this_members_vocabulary(
    arena: PinArena, campaign_id: str
) -> None:
    # The arena's own load refusal belongs to the member that owns the
    # load, but a caller catching this member's base class must catch a
    # campaign no replay can read — so the seam translates whatever the
    # arena raised, chains the original (the operator still sees it), and
    # names the campaign and the axis.  A seam that let the foreign class
    # escape would defeat the single `except ReplayError` the member's
    # whole error vocabulary exists to give.
    arena.refusal = ForeignLoadError("no such campaign in the store")
    with pytest.raises(ReplayReturnsError) as raised:
        resident_returns(arena, campaign_id)
    assert isinstance(raised.value, ReplayError)
    assert campaign_id in str(raised.value)
    assert isinstance(raised.value.__cause__, ForeignLoadError)
    # And nothing was pinned: the arena holds measurements, not attempts.
    assert not arena.holds(campaign_id)


def test_a_carrier_that_cannot_pin_is_refused_naming_the_law(
    campaign_id: str,
) -> None:
    # The resident side of the seam is an arena — feature 175's CampaignPins
    # — and the Parquet side is the store it loads through.  A caller that
    # hands the store (or anything else without a `pin`) is refused with
    # the law in the message, because the honest repair is "hand the
    # arena", not "the replay will sweep the store for you".
    store_like = type("ArtifactStore", (), {})()
    with pytest.raises(ReplayReturnsError) as raised:
        resident_returns(store_like, campaign_id)
    message = str(raised.value)
    assert "pin" in message
    assert "resident" in message
    with pytest.raises(ReplayReturnsError):
        resident_returns("not-an-arena", campaign_id)


def test_a_malformed_campaign_is_refused_before_the_arena(
    arena: PinArena,
) -> None:
    # A malformed ask is the caller's to repair and the arena should never
    # see it: a blank or non-string campaign id names no axis to pin, and
    # is refused in this member's vocabulary with the arena untouched
    # (pinned by the double's own counters).
    for bad in ("   ", "", 51, None):
        with pytest.raises(ReplayReturnsError):
            resident_returns(arena, bad)
    assert arena.pin_calls == 0


def test_a_malformed_horizon_is_refused_before_the_arena(
    arena: PinArena, campaign_id: str
) -> None:
    # The ask's axis spelling: None is the policy axis and an explicit
    # horizon is a positive period count — a boolean is not one (it is a
    # flag wearing an int), zero and negatives name no forward period, and
    # a string is not a count at all.
    for bad in (0, -1, True, "5"):
        with pytest.raises(ReplayReturnsError):
            resident_returns(arena, campaign_id, horizon=bad)
    assert arena.pin_calls == 0


# ---------------------------------------------------------------------------
# The resident answer is the dense array — validated as it is read
# ---------------------------------------------------------------------------


def _hold_over(answer: Any) -> Any:
    """An arena whose next pin answers a hold carrying ``answer``.

    The seam reads the hold's array exactly once, so the double lets a test
    substitute what it answers — the lying spellings the load's own
    construction refuses are exactly the ones a broken arena could still
    hand a replay.
    """

    class LyingArena:
        #: How many ``pin`` asks reached this arena.
        pin_calls = 0

        def pin(
            self, campaign_id: str, *, horizon: int | None = None
        ) -> Any:
            self.pin_calls += 1
            return type(
                "Hold",
                (),
                {"returns": answer, "release": lambda self_: None},
            )()

    return LyingArena()


def test_a_hold_answering_a_path_is_refused(campaign_id: str) -> None:
    # The naive read wearing the pin's name: a hold that answers a Parquet
    # *file path* is the per-replay sweep dressed as residence, and scoring
    # off it would be reading Parquet on each replay — the exact act the
    # feature replaces.  Refused naming the campaign.
    lying = _hold_over(
        "artifacts/campaign/node-a/signal_returns.parquet"
    )
    with pytest.raises(ReplayReturnsError) as raised:
        resident_returns(lying, campaign_id)
    assert campaign_id in str(raised.value)


def test_a_hold_answering_no_array_is_refused(campaign_id: str) -> None:
    # A hold with no answer names no campaign this replay could read —
    # None is not a dense array, and a read that returned it would hand
    # every downstream score an AttributeError dressed as a measurement.
    for answer in (None, object()):
        lying = _hold_over(answer)
        with pytest.raises(ReplayReturnsError):
            resident_returns(lying, campaign_id)


def test_a_hold_answering_another_campaigns_array_is_refused(
    campaign_id: str,
) -> None:
    # The one identity check the seam performs on the value: a hold asked
    # for one campaign answering another campaign's array is the arena's
    # bug, and a replay that scored it would measure the wrong world —
    # the failure §9.3's one-world-per-array rule exists to prevent.
    other = "0e0e0e0e-1111-4aaa-8bbb-cccddd000099"
    resident = ResidentArray(other, ("node-a",), (D1,))
    lying = _hold_over(resident)
    with pytest.raises(ReplayReturnsError) as raised:
        resident_returns(lying, campaign_id)
    assert other in str(raised.value)


def test_the_resident_axes_and_buffer_are_read_as_found(
    arena: PinArena, campaign_id: str
) -> None:
    # What the seam validates about the array is what it reads — the
    # campaign, the row axis, the column axis, a cell-addressable buffer —
    # and no more: the load's internal laws (the typecode, the
    # cells-by-axes arithmetic, the NaN policy) are feature 174's, checked
    # at that member's construction, and a second statement of them here
    # would be a second thing to drift.  Pinned positively: the honest
    # record's own axes are the answer's axes, untouched.
    read = resident_returns(arena, campaign_id)
    resident = read.returns
    assert resident.node_ids == ("node-a", "node-b")
    assert resident.periods == (D1, D2, D3)
    assert len(resident.values) == 6
    assert resident.values.itemsize == 4


# ---------------------------------------------------------------------------
# The composed component — a spelling, not a second implementation
# ---------------------------------------------------------------------------


def test_the_facade_verb_is_the_same_act(
    arena: PinArena, campaign_id: str
) -> None:
    # A caller holding the composed component reaches the same resident
    # read with no import of the member: same arena, same axis, same
    # resident object — and the arena still loaded once.
    direct = resident_returns(arena, campaign_id)
    via_component = ReplayEngine().returns(arena, campaign_id)
    assert via_component.returns is direct.returns
    assert arena.loads == 1


def test_the_facade_refuses_what_the_verb_refuses(
    arena: PinArena, campaign_id: str
) -> None:
    # There is no route to a Parquet read by holding the component: the
    # facade's verb carries the same seam, so a runtime that wrote
    # `load=...` against the composed engine meets the same refusal at the
    # same keyword — one verb, one seam, one place to look.
    with pytest.raises(ParquetReadRefused):
        ReplayEngine().returns(arena, campaign_id, load=dict)
    assert arena.pin_calls == 0


def test_the_policy_sentence_is_one_spelling() -> None:
    # RESIDENT_READ_POLICY is the decision the feature's sentence pins,
    # spelled once the way the artifacts member spells its own resident
    # policies — the seam's docstrings and these tests quote it rather
    # than paraphrasing it, so the law cannot drift between statements.
    assert "pinned resident array" in RESIDENT_READ_POLICY
    assert "never a Parquet sweep per replay" in RESIDENT_READ_POLICY


# ---------------------------------------------------------------------------
# The real cross-member seam — the artifacts member's own arena and array
# ---------------------------------------------------------------------------

artifacts = pytest.importorskip(
    "artifacts", reason="the resident side is the artifacts member's own"
)
pytest.importorskip(
    "pyarrow", reason="the arena loads through feature 174's Parquet read"
)

from artifacts import (  # noqa: E402
    ARTIFACT_ROOT_ENV,
    ArtifactNotFoundError,
    ArtifactStore,
    CampaignPins,
    ReturnRow,
    SignalReturns,
    load_campaign_returns,
    persist_signal_returns,
)


@pytest.fixture
def real_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> ArtifactStore:
    """A real artifact store under this test's isolated root."""
    monkeypatch.setenv(ARTIFACT_ROOT_ENV, str(tmp_path / "artifacts"))
    return ArtifactStore.from_env()


def _published_campaign(store: ArtifactStore, campaign_id: str) -> None:
    """Publish the two-node campaign the 174/175 suites load — one world.

    Two nodes, ragged panels (three dates in the union), one sealed
    snapshot and one fee pair: the smallest campaign whose dense load is
    honest — the same shape `test_pins.py` loads, restated here because a
    member's tests never import another member's helpers.
    """
    for node_id, rows in (
        (
            "node-a",
            (
                ReturnRow(
                    rebalance_date=D1,
                    horizon=1,
                    symbol="AAA",
                    charge=0.001,
                    post_cost_return=0.010,
                ),
                ReturnRow(
                    rebalance_date=D1,
                    horizon=1,
                    symbol="BBB",
                    charge=0.002,
                    post_cost_return=-0.004,
                ),
                ReturnRow(
                    rebalance_date=D2,
                    horizon=1,
                    symbol="AAA",
                    charge=0.001,
                    post_cost_return=-0.020,
                ),
            ),
        ),
        (
            "node-b",
            (
                ReturnRow(
                    rebalance_date=D2,
                    horizon=1,
                    symbol="AAA",
                    charge=0.001,
                    post_cost_return=-0.010,
                ),
                ReturnRow(
                    rebalance_date=D3,
                    horizon=1,
                    symbol="BBB",
                    charge=0.002,
                    post_cost_return=0.008,
                ),
            ),
        ),
    ):
        panel = SignalReturns(
            node_id=node_id,
            snapshot_name="snap-2026-01",
            venue="binance",
            version="v3",
            rows=rows,
        )
        persist_signal_returns(store, campaign_id, node_id, panel)
        store.commit(campaign_id, node_id)


def test_the_read_walks_the_members_real_pin_arena(
    real_store: ArtifactStore, campaign_id: str
) -> None:
    # The one place the real cross-member residence is exercised: the
    # artifacts member's own CampaignPins, reached the way a deployment
    # reaches it (constructed by the round that holds it, never imported by
    # this member), pinned through this seam — and the array answered is
    # feature 174's own load: same axes, same resolved horizon, same bytes.
    _published_campaign(real_store, campaign_id)
    arena = CampaignPins(real_store)
    read = resident_returns(arena, campaign_id)
    direct = load_campaign_returns(real_store, campaign_id)
    assert read.returns.node_ids == direct.node_ids == ("node-a", "node-b")
    assert read.returns.periods == direct.periods == (D1, D2, D3)
    assert read.returns.horizon == direct.horizon == 1
    assert read.returns.values.tobytes() == direct.values.tobytes()
    # And the second read over the same arena shares the resident object —
    # the real arena's residence, observed through this member's seam.
    again = resident_returns(arena, campaign_id)
    assert again.returns is read.returns
    assert arena.pin_count(campaign_id) == 2
    read.release()
    again.release()


def test_a_read_answers_from_ram_not_parquet(
    real_store: ArtifactStore, campaign_id: str
) -> None:
    # The honest proof of the feature's sentence: with the campaign's
    # directory deleted under the hold, the read still answers its array —
    # a direct load refuses (ArtifactNotFoundError), so the answer can only
    # have come from RAM.  This is §9.3's whole answer to the replay
    # bottleneck, observed at the replay path's own seam.
    _published_campaign(real_store, campaign_id)
    arena = CampaignPins(real_store)
    read = resident_returns(arena, campaign_id)
    held_bytes = read.returns.values.tobytes()
    shutil.rmtree(real_store.root / campaign_id)
    assert read.returns.values.tobytes() == held_bytes  # still answers, from RAM
    with pytest.raises(ArtifactNotFoundError):
        load_campaign_returns(real_store, campaign_id)  # the store is empty
    read.release()


def test_the_real_arenas_refusal_arrives_in_this_members_vocabulary(
    real_store: ArtifactStore, campaign_id: str
) -> None:
    # The real arena's real refusal — a campaign the store does not hold —
    # crosses the seam translated: catchable by this member's base class,
    # chained to the artifacts member's own error, naming the campaign.
    # This is the error-vocabulary rule the two members' suites both
    # state, pinned here against the arena that actually raises.
    arena = CampaignPins(real_store)
    with pytest.raises(ReplayReturnsError) as raised:
        resident_returns(arena, campaign_id)
    assert isinstance(raised.value, ReplayError)
    assert campaign_id in str(raised.value)
    assert isinstance(raised.value.__cause__, ArtifactNotFoundError)
    assert not arena.holds(campaign_id)
