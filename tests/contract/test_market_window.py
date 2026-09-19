"""The MarketWindow decision-time contract.

Feature 4 of app_spec.xml: "System defines a MarketWindow class whose
constructor persists a decision time t as a read-only attribute that no caller
can reassign".  This suite pins that guarantee from every direction a caller
could approach it from:

* the value ``t`` is the one the constructor was given, and it is an exact
  instant in UTC;
* every attempt to reassign or delete it fails — via the attribute protocol,
  inside a signal, from a factory, from a subclass, and by re-invoking the
  constructor on a live window;
* the underlying storage is not reachable as a writable hook either — setting
  the private slot directly fails just as loudly, so the guard is not merely a
  property with a different name to look up.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from contract import MarketWindow

#: The decision time used across this suite.  An aware UTC instant, which is
#: how every timestamp in this system is stored.
T = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)

UNIVERSE = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


def test_constructor_persists_decision_time():
    window = MarketWindow(T)
    assert window.t == T


def test_decision_time_is_utc_and_timezone_aware():
    # Point-in-time comparisons are only sound against an unambiguous instant.
    window = MarketWindow(T)
    assert window.t.tzinfo is not None
    assert window.t.utcoffset() == timedelta(0)


def test_aware_decision_time_in_another_zone_is_the_same_instant():
    plus_two = timezone(timedelta(hours=2))
    window = MarketWindow(datetime(2026, 9, 1, 14, 0, 0, tzinfo=plus_two))
    assert window.t == T


def test_naive_decision_time_is_read_as_utc():
    # Naive means UTC by convention here, so a naive value must land on the
    # same instant as the equivalent aware one, not be shifted by local time.
    window = MarketWindow(datetime(2026, 9, 1, 12, 0, 0))
    assert window.t == T
    assert window.t.tzinfo is not None


def test_iso_string_decision_time_is_accepted():
    # The boundary representation: the window travels as JSON/Arrow IPC.
    assert MarketWindow("2026-09-01T12:00:00+00:00").t == T


def test_unparseable_decision_time_is_rejected():
    with pytest.raises(ValueError):
        MarketWindow("not-a-timestamp")


def test_non_datetime_decision_time_is_rejected():
    for bad in (1234567890, None, ["2026-09-01"]):
        with pytest.raises(TypeError):
            MarketWindow(bad)


def test_a_bare_date_is_rejected():
    # `date` names a calendar day, not an instant, and is ambiguous exactly
    # where point-in-time correctness matters. Note datetime subclasses date,
    # so this is not free — the check must be isinstance(t, datetime).
    with pytest.raises(TypeError):
        MarketWindow(date(2026, 9, 1))


def test_callers_cannot_reassign_decision_time():
    window = MarketWindow(T)
    with pytest.raises(AttributeError):
        window.t = T + timedelta(days=1)
    # And the failed write left the original instant untouched.
    assert window.t == T


def test_callers_cannot_reassign_lookback_forward_either():
    # The narrower failure mode: an attempt to push `t` *earlier* is still a
    # reassignment, and still refused.
    window = MarketWindow(T)
    with pytest.raises(AttributeError):
        window.t = T - timedelta(days=1)
    assert window.t == T


def test_callers_cannot_delete_decision_time():
    window = MarketWindow(T)
    with pytest.raises(AttributeError):
        del window.t
    assert window.t == T


def test_no_caller_can_grow_new_attributes():
    # __slots__ plus the __setattr__ guard: there is no shadow channel either.
    window = MarketWindow(T)
    with pytest.raises(AttributeError):
        window.fake_future = "anything"
    assert not hasattr(window, "fake_future")


def test_private_slot_is_not_a_writable_hook():
    # Reaching for the backing slot by name must fail exactly as loudly as
    # reaching for the property, or the guard is theatre.
    window = MarketWindow(T)
    with pytest.raises(AttributeError):
        window._t = T + timedelta(days=1)
    assert window.t == T


def test_reassignment_is_refused_from_inside_a_signal():
    # The threat model, stated directly: untrusted LLM-authored code runs with
    # this object in hand and tries to widen its own window.
    window = MarketWindow(T, UNIVERSE)

    def signal(ctx: MarketWindow, seed: int):
        ctx.t = ctx.t + timedelta(days=365)
        return None

    with pytest.raises(AttributeError):
        signal(window, 0)
    assert window.t == T


def test_reassignment_is_refused_from_a_subclass():
    # A subclass cannot reintroduce a setter that the contract forbids: the
    # guard lives on the base __setattr__ and is inherited, not overridden by
    # the mere act of subclassing.
    class WideningWindow(MarketWindow):
        pass

    window = WideningWindow(T)
    with pytest.raises(AttributeError):
        window.t = T + timedelta(days=1)
    assert window.t == T


def test_decision_time_is_not_writable_via_object_setattr_on_the_property():
    # object.__setattr__ bypasses __setattr__, so this is the one call that
    # could punch through the guard.  It does not, because `t` is a property
    # with no setter — the descriptor protocol refuses the write.
    window = MarketWindow(T)
    with pytest.raises(AttributeError):
        object.__setattr__(window, "t", T + timedelta(days=1))
    assert window.t == T


def test_decision_time_property_has_no_setter():
    # The structural reason the test above passes, pinned directly.
    assert isinstance(MarketWindow.t, property)
    assert MarketWindow.t.fset is None


def test_object_setattr_through_the_backing_slot_is_the_documented_limit():
    # Honest scope boundary, asserted rather than glossed: object.__setattr__
    # on the *private slot* does write.  No pure-Python guard can stop it —
    # object.__setattr__ is the primitive defined to skip guards.  The threat
    # this class is built against (`ctx.t = ...` from untrusted signal code)
    # is fully covered by the tests above; an in-process escape of this shape
    # is the sandbox's job (architecture §5.2), not this class's.
    #
    # This test exists so the limit is recorded in the suite: if a future
    # change makes this raise, the class got stronger and this test should be
    # tightened to match — not deleted.
    window = MarketWindow(T)
    object.__setattr__(window, "_t", T + timedelta(days=1))
    assert window.t == T + timedelta(days=1)


def test_reinvoking_the_constructor_cannot_move_t():
    # The constructor binds `t` through object.__setattr__ — the sanctioned
    # writer — so a caller re-invoking it on a live window (`window.__init__(
    # later_t)`) would rebind the decision time through the front door.  The
    # spec says *no* caller can reassign, and this is a public method any
    # caller can call, so the constructor is single-shot.  The refusal fires
    # before any bind, so the window is exactly as it was afterwards.
    window = MarketWindow(T, universe=UNIVERSE)
    later = T + timedelta(days=1)
    with pytest.raises(TypeError, match="already initialized"):
        window.__init__(later, universe=("ADAUSDT",))
    assert window.t == T
    assert window.universe == UNIVERSE


def test_copy_and_pickle_rebuild_through_the_constructor():
    # A window is a value that travels (host to sandbox payload channel), so
    # copy/deepcopy/pickle must work — but the default slots restore path
    # writes with plain setattr, which the immutability guard refuses.  The
    # class therefore rebuilds copies through its constructor: the copy path
    # and the construction path cannot disagree about what a window is.
    import copy
    import pickle

    window = MarketWindow(T, universe=UNIVERSE)
    for rebuilt in (
        copy.copy(window),
        copy.deepcopy(window),
        pickle.loads(pickle.dumps(window)),
    ):
        assert rebuilt is not window
        assert rebuilt == window
        assert rebuilt.t == T
        assert rebuilt.universe == UNIVERSE
        # And the rebuilt window is exactly as immutable as the original.
        with pytest.raises(AttributeError):
            rebuilt.t = T + timedelta(days=1)


def test_universe_is_persisted_as_a_tuple():
    window = MarketWindow(T, UNIVERSE)
    assert isinstance(window.universe, tuple)
    assert window.universe == UNIVERSE


def test_universe_defaults_to_empty():
    assert MarketWindow(T).universe == ()


def test_universe_is_read_only():
    window = MarketWindow(T, UNIVERSE)
    with pytest.raises(AttributeError):
        window.universe = ("DOGEUSDT",)
    with pytest.raises(AttributeError):
        del window.universe
    assert window.universe == UNIVERSE


def test_universe_preserves_order_and_deduplicates():
    window = MarketWindow(T, ["ETHUSDT", "BTCUSDT", "ETHUSDT"])
    assert window.universe == ("ETHUSDT", "BTCUSDT")


def test_a_bare_string_universe_is_rejected():
    # Iterating "BTCUSDT" would yield one symbol per character — plausible
    # enough to survive review and silently wrong.
    with pytest.raises(TypeError):
        MarketWindow(T, "BTCUSDT")


def test_non_string_universe_member_is_rejected():
    with pytest.raises(TypeError):
        MarketWindow(T, ["BTCUSDT", 42])


def test_windows_with_the_same_decision_time_are_equal():
    assert MarketWindow(T, UNIVERSE) == MarketWindow(T, UNIVERSE)


def test_windows_at_different_decision_times_are_not_equal():
    assert MarketWindow(T, UNIVERSE) != MarketWindow(T + timedelta(seconds=1), UNIVERSE)


def test_window_is_hashable():
    # Immutability is what makes this sound; it is also what lets a window be
    # a dict key or set member in the evaluator.
    assert len({MarketWindow(T, UNIVERSE), MarketWindow(T, UNIVERSE)}) == 1
