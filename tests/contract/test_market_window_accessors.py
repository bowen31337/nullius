"""The MarketWindow accessor contract — no accessor takes a timestamp.

Feature 10 of app_spec.xml: "System rejects any MarketWindow accessor that
receives a timestamp argument, because no timestamp a caller passes may widen
the window."  The read-only ``t`` guard (feature 4) covers the *assignment*
path — ``ctx.t = ...`` — but assignment is only one of the two ways a window
could be widened.  The other is an accessor that takes a time:
``ctx.bars("1m", as_of=tomorrow)`` would return rows the window was sliced to
exclude, which is look-ahead bias entering through a *signature* rather than a
reassignment (architecture §5.1).

Feature 10 closes that second path, and it closes it *structurally*, at
class-definition time: :class:`contract.window._EnforceNoTimestampAccessor` is
the window's metaclass, so any window — or a subclass added by a later feature
module — that declares an accessor taking a timestamp is refused the instant
it is written, before any window carrying it can be built.  This suite pins
that guarantee from both directions:

* the window's real surface is enumerated and reported, and every accessor on
  it is free of a timestamp parameter;
* the refusal is not theatre — the moment an accessor is given a timestamp
  parameter, by any of the spellings a caller would reach for, the class is
  rejected; and the guarantee is honest about its own scope, leaving the one
  place a timestamp legitimately belongs (the ``from_memberships`` constructor)
  untouched.
"""

from __future__ import annotations

import copy
import inspect
import pickle
from datetime import datetime, timezone

import pytest

from contract import MarketWindow, inspect_accessors
from contract.window import (
    _EnforceNoTimestampAccessor,
    _timestamp_param_names,
    _widening_accessors,
)


#: The decision time, only ever a constructor argument here — never something
#: an accessor is handed.
T = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)


# --- the surface -----------------------------------------------------------


def test_inspect_accessors_reports_the_window_surface():
    # The enumeration returns the accessor names it inspected, so a caller
    # learns what the surface is, not merely that nothing was rejected.  The
    # window exposes its three read-only properties, its serialization method,
    # and the feature accessor feature 9 adds — which takes a name, a version
    # and a lookback, and no time.
    assert set(inspect_accessors()) == {
        "t",
        "universe",
        "frames",
        "to_arrow",
        "feature",
    }


def test_no_accessor_takes_a_timestamp_argument():
    # The property feature 10 asserts: enumerated over the real class, no
    # accessor declares a parameter that reads as a time, and the surface is
    # non-empty.
    names = inspect_accessors()
    assert names
    for name in names:
        assert _timestamp_param_names(getattr(MarketWindow, name)) == ()


def test_the_window_uses_the_enforcement_metaclass():
    # The guarantee is structural, not advisory: the class is built with the
    # metaclass that refuses a widening accessor at definition time.
    assert type(MarketWindow) is _EnforceNoTimestampAccessor


# --- the enumeration core --------------------------------------------------


def test_timestamp_parameter_names_are_detected_by_spelling():
    # The check is a signature check: it names the parameters a caller *could*
    # use to pass a time.  Each of these spellings is a widening slot.
    def bars(self, freq, lookback, as_of=None):
        ...

    def trades(self, lookback_s, timestamp=None):
        ...

    def bookfeat(self, name, lookback, at=None):
        ...

    def borrow(self, lookback, when=None):
        ...

    def feature(self, name, version, lookback, end=None):
        ...

    assert _timestamp_param_names(bars) == ("as_of",)
    assert _timestamp_param_names(trades) == ("timestamp",)
    assert _timestamp_param_names(bookfeat) == ("at",)
    assert _timestamp_param_names(borrow) == ("when",)
    assert _timestamp_param_names(feature) == ("end",)


def test_a_bare_t_parameter_is_detected():
    # The most direct widening: an accessor whose first real argument is ``t``.
    def accessor(self, t):
        ...

    assert _timestamp_param_names(accessor) == ("t",)


def test_non_timestamp_parameters_are_not_flagged():
    # The accessors the architecture actually allows (bars/trades/…) take a
    # frequency, a lookback, a name, a version — never a time.  Those names
    # must not be mistaken for timestamps, or the check would reject the very
    # accessors feature 10 is meant to coexist with.
    def bars(self, freq, lookback):
        ...

    def trades(self, lookback_s):
        ...

    def bookfeat(self, name, lookback):
        ...

    def feature(self, name, version, lookback):
        ...

    assert _timestamp_param_names(bars) == ()
    assert _timestamp_param_names(trades) == ()
    assert _timestamp_param_names(bookfeat) == ()
    assert _timestamp_param_names(feature) == ()


def test_a_catch_all_is_not_a_timestamp_slot():
    # A *args/**kwargs catch-all is not a named slot a caller fills with a
    # time; it is not the surface feature 10 forbids, so it is not flagged.
    def accessor(self, freq, *args, **kwargs):
        ...

    assert _timestamp_param_names(accessor) == ()


def test_spelling_match_is_case_insensitive():
    # ``AsOf``-style spellings are still timestamp arguments; the match is
    # case-insensitive so a caller cannot slip one past by casing.
    def accessor(self, freq, AsOf=None):
        ...

    assert _timestamp_param_names(accessor) == ("AsOf",)


def test_widening_accessors_enumerates_only_the_offenders():
    # The shared enumeration core, exercised in isolation: it reports exactly
    # the accessors that widen, with the parameter names, and nothing else.
    class Sample:
        def bars(self, freq):  # conforming
            return None

        def trades(self, lookback_s, as_of=None):  # widening
            return None

        @property
        def t(self):  # a property, never a widening accessor
            return None

        @classmethod
        def from_memberships(cls, t, rows):  # a constructor, excluded
            return None

    assert _widening_accessors(Sample) == (("trades", ("as_of",)),)


# --- the metaclass enforcement ---------------------------------------------


def test_a_subclass_with_a_widening_accessor_is_rejected_at_definition():
    # The refusal itself, made concrete: subclass the real window, give an
    # accessor a timestamp parameter, and the class never comes into being.
    # The error names the accessor and the parameter, so it is actionable.
    with pytest.raises(TypeError, match=r"bars.*as_of"):

        class WideningWindow(MarketWindow):
            def bars(self, freq, lookback, as_of=None):
                return None


def test_a_widening_accessor_with_any_spelling_is_rejected():
    # The metaclass fires regardless of how the timestamp parameter is spelled.
    with pytest.raises(TypeError, match="timestamp"):

        class TradesWindow(MarketWindow):
            def trades(self, lookback_s, timestamp=None):
                return None


def test_a_plain_class_with_a_widening_accessor_is_rejected():
    # The metaclass is the window's, not just its subclasses': even a
    # would-be window built directly with the metaclass is refused.
    with pytest.raises(TypeError, match="as_of"):

        class StandaloneWindow(metaclass=_EnforceNoTimestampAccessor):
            def bars(self, freq, as_of=None):
                return None


def test_a_subclass_without_a_widening_accessor_is_allowed():
    # The guarantee forbids widening accessors, not extension: a subclass that
    # adds a conforming accessor (no timestamp) defines cleanly.  The subclass
    # inherits the guard, so it too would be refused a widening accessor — but
    # a conforming one is fine.
    class ExtendedWindow(MarketWindow):
        def regime(self, lookback):
            return None

    assert ExtendedWindow is not MarketWindow
    assert type(ExtendedWindow) is _EnforceNoTimestampAccessor
    assert _widening_accessors(ExtendedWindow) == ()


# --- the sanctioned exception: the constructor -----------------------------


def test_from_memberships_is_not_an_accessor_and_is_excluded():
    # The one place a timestamp legitimately belongs is the *constructor*
    # ``from_memberships(t, ...)`` — feature 13's point-in-time resolution
    # path, which resolves the universe as of the window's own frozen ``t``.
    # A constructor is not an accessor a signal calls on ``ctx``, so the
    # enumeration excludes classmethods and never reports ``from_memberships``
    # as an accessor.
    assert "from_memberships" not in inspect_accessors()
    # from_memberships does take `t` — correct for a constructor.  The
    # guarantee is that no *accessor* (instance method) does.
    assert _timestamp_param_names(MarketWindow.from_memberships) == ("t",)


def test_a_subclass_may_add_a_classmethod_taking_t():
    # The honest scope boundary, pinned directly: a subclass that adds a
    # classmethod constructor taking ``t`` is allowed, because constructors
    # are excluded.  If the metaclass ever widened to cover classmethods, this
    # test would fail — and so would feature 13's construction path — which is
    # exactly the regression it records.
    class ConstructingWindow(MarketWindow):
        @classmethod
        def build(cls, t, rows):
            return cls(t)

    assert _widening_accessors(ConstructingWindow) == ()


# --- the guarantee does not weaken the window ------------------------------


def test_copy_and_pickle_still_work_with_the_metaclass():
    # The metaclass is a definition-time guard, not a runtime one, so it must
    # not interfere with the window's value semantics.  A window still copies,
    # deep-copies and pickles into an equally immutable, equally guarded window.
    window = MarketWindow(T, universe=("BTCUSDT", "ETHUSDT"))
    for rebuilt in (
        copy.copy(window),
        copy.deepcopy(window),
        pickle.loads(pickle.dumps(window)),
    ):
        assert rebuilt == window
        assert rebuilt.t == T
        assert rebuilt.universe == ("BTCUSDT", "ETHUSDT")
        # The rebuilt window is the same class, still carrying the guard.
        assert type(rebuilt) is MarketWindow
        assert type(MarketWindow) is _EnforceNoTimestampAccessor
        with pytest.raises(AttributeError):
            rebuilt.t = T  # still immutable


def test_check_is_clock_free_and_repeatable():
    # A self-check that read the wall clock could not pin a point-in-time
    # guarantee.  inspect_accessors reads only the class definition, so it
    # returns the same surface on every call, at any time of day.
    assert inspect_accessors() == inspect_accessors()
