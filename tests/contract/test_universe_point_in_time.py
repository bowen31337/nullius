"""The window universe is resolved as of the decision time, not the wall clock.

Feature 13 of app_spec.xml: "System exposes ``MarketWindow.universe`` as a
tuple, which returns symbols tradable as of the decision time rather than as
of the current wall clock".  The tuple half of that sentence is pinned by
``test_market_window.py``; this suite pins the half that actually matters,
because a tuple is equally happy to hold today's roster.

The failure mode has two directions and both are silent, which is why each
gets its own test rather than one "point-in-time works" assertion:

* a symbol **delisted after** the decision time must still appear — it was
  tradable then, and dropping it is the survivorship pruning that flatters
  every result computed downstream;
* a symbol **listed after** the decision time must not appear — it was not
  tradable then, and returning it is look-ahead.

A test that only checked one direction would pass against a resolver that
returned every symbol it had ever heard of, or none of them.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from contract import MarketWindow, resolve_universe

#: The decision time these tests resolve at.  A fixed instant, never
#: ``datetime.now()`` — a test written against the wall clock would assert
#: something different every day it ran, and would drift into the delisting
#: it is supposed to catch.
T = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)


def _interval(symbol: str, valid_from: date, valid_to: date | None = None):
    """A membership row in the shape the universe member actually emits.

    Deliberately a stand-in with the same two attributes rather than an
    imported ``universe.membership.MembershipInterval``: ``contract`` is Z0
    and must not depend on the ``universe`` member, and importing it here
    would hide a layering inversion behind a test-only import.  The real
    class is exercised against this seam in
    ``test_the_real_membership_interval_satisfies_the_seam`` below.
    """

    class _Row:
        def __init__(self) -> None:
            self.symbol = symbol
            self.valid_from = valid_from
            self.valid_to = valid_to

    return _Row()


#: A roster with a delisting and a listing straddling ``T`` (2026-06-15):
#: BTC listed long before and still open; ETH delisted in May, before T;
#: SOL delisted in September, so it was tradable at T and leaves afterwards;
#: DOGE listed in July, so it was not tradable at T.
MEMBERSHIPS = (
    _interval("BTCUSDT", date(2020, 1, 1)),
    _interval("ETHUSDT", date(2020, 1, 1), date(2026, 5, 1)),
    _interval("SOLUSDT", date(2021, 8, 1), date(2026, 9, 1)),
    _interval("DOGEUSDT", date(2026, 7, 1)),
)


def test_a_symbol_delisted_after_the_decision_time_is_still_returned():
    # SOL delisted 2026-09-01, three months AFTER T.  It was tradable at T, so
    # it belongs in the window.  A current-roster view (or one resolved at the
    # wall clock once SOL is delisted) would drop it, and every cross-sectional
    # result computed over the shrunken roster would be quietly optimistic.
    assert "SOLUSDT" in resolve_universe(T, MEMBERSHIPS)


def test_a_symbol_listed_after_the_decision_time_is_not_returned():
    # DOGE listed 2026-07-01, AFTER T.  Including it is look-ahead: at T the
    # signal could not have traded it.
    assert "DOGEUSDT" not in resolve_universe(T, MEMBERSHIPS)


def test_a_symbol_delisted_before_the_decision_time_is_not_returned():
    # ETH's interval closed 2026-05-01, before T.  Both directions matter, and
    # this is the third: a resolver that returned every symbol it had ever
    # seen would pass the two tests above.
    assert "ETHUSDT" not in resolve_universe(T, MEMBERSHIPS)


def test_resolution_returns_exactly_the_roster_tradable_at_the_decision_time():
    assert resolve_universe(T, MEMBERSHIPS) == ("BTCUSDT", "SOLUSDT")


def test_an_open_interval_covers_the_decision_time():
    # ``valid_to is None`` is the horizon: the newest build still admits the
    # symbol and no later build exists to close it.
    assert "BTCUSDT" in resolve_universe(T, MEMBERSHIPS)


def test_valid_from_is_inclusive_and_valid_to_is_exclusive():
    # The boundary convention the universe member derives its intervals under
    # (see universe/membership.py): membership holds when
    # ``valid_from <= t < valid_to``.  Pinned here because the two packages
    # meet at this seam and must agree exactly — an off-by-one day is a symbol
    # appearing a day before it listed, or vanishing on the day it delisted.
    start = date(2026, 6, 1)
    end = date(2026, 6, 30)
    rows = [_interval("XUSDT", start, end)]
    assert resolve_universe(start, rows) == ("XUSDT",)  # inclusive at from
    assert resolve_universe(date(2026, 6, 29), rows) == ("XUSDT",)
    assert resolve_universe(end, rows) == ()  # exclusive at to
    assert resolve_universe(date(2026, 5, 31), rows) == ()


def test_a_symbol_outside_its_listed_period_is_absent_on_both_sides():
    # A delisted symbol is retained with its full history (feature 43), which
    # means the resolver is asked about times outside its interval routinely.
    # Before the listing and after the delisting must both be empty.
    rows = [_interval("ETHUSDT", date(2020, 1, 1), date(2026, 5, 1))]
    assert resolve_universe(date(2019, 12, 31), rows) == ()
    assert resolve_universe(date(2026, 5, 1), rows) == ()
    assert resolve_universe(date(2026, 5, 2), rows) == ()


# -- the window couples its universe to its own decision time --------------


def test_a_window_resolves_its_universe_as_of_its_own_decision_time():
    # The structural guarantee: from_memberships takes the membership rows and
    # the decision time together, so the roster a window reports and the
    # instant it is sliced at cannot disagree.  There is no clock argument to
    # get wrong, because there is no clock argument.
    window = MarketWindow.from_memberships(T, MEMBERSHIPS)
    assert window.universe == ("BTCUSDT", "SOLUSDT")
    assert window.t == T


def test_the_window_universe_is_a_tuple():
    # The first half of feature 13, re-pinned at the point-in-time entry point
    # so the resolution path cannot quietly start returning a list.
    window = MarketWindow.from_memberships(T, MEMBERSHIPS)
    assert isinstance(window.universe, tuple)


def test_the_window_universe_is_read_only():
    window = MarketWindow.from_memberships(T, MEMBERSHIPS)
    with pytest.raises(AttributeError):
        window.universe = ("DOGEUSDT",)
    assert window.universe == ("BTCUSDT", "SOLUSDT")


def test_two_windows_at_different_decision_times_see_different_rosters():
    # The clearest statement of the feature: same membership table, two
    # decision times, two genuinely different universes.  If resolution read
    # the wall clock, both windows would report the same roster and this test
    # could not distinguish them at all.
    at_t = MarketWindow.from_memberships(T, MEMBERSHIPS)
    later = MarketWindow.from_memberships(
        datetime(2026, 8, 1, tzinfo=timezone.utc), MEMBERSHIPS
    )
    assert at_t.universe == ("BTCUSDT", "SOLUSDT")
    assert later.universe == ("BTCUSDT", "DOGEUSDT", "SOLUSDT")


def test_a_window_at_a_time_before_a_listing_does_not_see_it():
    at_t = MarketWindow.from_memberships(T, MEMBERSHIPS)
    assert "DOGEUSDT" not in at_t.universe
    after = MarketWindow.from_memberships(
        datetime(2026, 7, 15, tzinfo=timezone.utc), MEMBERSHIPS
    )
    assert "DOGEUSDT" in after.universe


# -- purity and determinism ------------------------------------------------


def test_resolution_does_not_read_the_wall_clock():
    # Resolving for a time far in the past must give the past's roster no
    # matter when the test runs.  This is the direct negation of the feature's
    # "rather than as of the current wall clock": a wall-clock-reading
    # implementation cannot answer a 2020 question differently from a 2026 one
    # that happens to cover the same symbols.
    ancient = datetime(2020, 6, 15, tzinfo=timezone.utc)
    assert resolve_universe(ancient, MEMBERSHIPS) == ("BTCUSDT", "ETHUSDT")


def test_resolution_is_stable_across_input_order():
    # Feature 46: every resolution returns a stable ordering so downstream
    # reductions stay bit-reproducible.  Input order must not leak through.
    forward = resolve_universe(T, MEMBERSHIPS)
    backward = resolve_universe(T, tuple(reversed(MEMBERSHIPS)))
    assert forward == backward == ("BTCUSDT", "SOLUSDT")


def test_resolution_is_deduplicated():
    # A symbol can hold more than one interval (a gap in its admitted months
    # starts a second one), and more than one row may cover the same instant.
    # The roster is a set of symbols, not of rows.
    rows = [
        _interval("BTCUSDT", date(2020, 1, 1), date(2026, 1, 1)),
        _interval("BTCUSDT", date(2026, 2, 1)),
        _interval("BTCUSDT", date(2026, 2, 1)),
    ]
    assert resolve_universe(T, rows) == ("BTCUSDT",)


def test_an_empty_membership_resolves_to_an_empty_tuple():
    assert resolve_universe(T, ()) == ()
    assert MarketWindow.from_memberships(T, ()).universe == ()


def test_resolution_accepts_a_plain_triple():
    # The second accepted shape: ``(symbol, valid_from, valid_to)``.  The host
    # may hold rows as tuples straight from a query rather than as interval
    # objects, and neither shape should require reformatting to be resolved.
    rows = [
        ("BTCUSDT", date(2020, 1, 1), None),
        ("DOGEUSDT", date(2026, 7, 1), None),
    ]
    assert resolve_universe(T, rows) == ("BTCUSDT",)


def test_resolution_accepts_mapping_rows_and_iso_date_strings():
    # The membership table's bounds are DATE columns; a row read back through
    # a driver arrives as a mapping of strings more often than as an object.
    rows = [
        {"symbol": "BTCUSDT", "valid_from": "2020-01-01", "valid_to": None},
        {"symbol": "DOGEUSDT", "valid_from": "2026-07-01", "valid_to": None},
    ]
    window = MarketWindow.from_memberships(T, rows)
    assert window.universe == ("BTCUSDT",)


def test_resolution_accepts_a_when_string():
    # ``t`` travels as ISO-8601 across the REST and Arrow-IPC boundaries, and
    # from_memberships passes the caller's ``t`` straight through, so the
    # resolver sees whatever the constructor accepts.
    assert resolve_universe("2026-06-15T12:00:00+00:00", MEMBERSHIPS) == (
        "BTCUSDT",
        "SOLUSDT",
    )


def test_a_triple_whose_interval_is_empty_resolves_to_nothing():
    # An interval with valid_from == valid_to covers no date at all under the
    # ``from <= t < to`` convention.  Guarded because the degenerate case is
    # exactly where an inclusive-both-ends bug hides.
    rows = [("XUSDT", date(2026, 6, 1), date(2026, 6, 1))]
    assert resolve_universe(date(2026, 6, 1), rows) == ()


# -- refusals --------------------------------------------------------------


def test_a_bare_string_is_not_a_membership_collection():
    # Iterating a string yields one "row" per character; the error must name
    # what was actually wrong rather than failing obscurely deeper in.
    with pytest.raises(TypeError, match="not a single"):
        resolve_universe(T, "BTCUSDT")


def test_a_row_with_no_symbol_is_rejected():
    with pytest.raises(TypeError):
        resolve_universe(T, [object()])


def test_a_row_with_no_valid_from_is_rejected():
    # A membership that starts nowhere covers every instant, which is a silent
    # point-in-time violation rather than a harmless default.
    class _NoStart:
        symbol = "BTCUSDT"
        valid_from = None
        valid_to = None

    with pytest.raises(TypeError, match="valid_from"):
        resolve_universe(T, [_NoStart()])


def test_a_non_date_bound_is_rejected():
    with pytest.raises(TypeError):
        resolve_universe(T, [("BTCUSDT", 20200101, None)])


def test_an_unparseable_date_string_is_rejected():
    with pytest.raises(ValueError):
        resolve_universe(T, [("BTCUSDT", "the first of January", None)])


# -- the seam against the real universe member -----------------------------


def test_the_real_membership_interval_satisfies_the_seam():
    """The stand-ins above share a shape with the real row; prove it.

    ``contract`` must not import ``universe`` (Z0 is the boundary everything
    else sits behind), so the acceptance is structural and this test is what
    keeps that honest: it imports the real
    :class:`universe.membership.MembershipInterval` and resolves it through
    the same seam.  If the universe member ever changes its row's field names
    the stand-ins above would keep passing while production broke — this test
    is the one that would fail.
    """
    MembershipInterval = pytest.importorskip(
        "universe.membership",
        reason="the universe member is a separate plugin; the seam is checked where it is present",
    ).MembershipInterval

    rows = (
        MembershipInterval(symbol="BTCUSDT", valid_from=date(2020, 1, 1)),
        MembershipInterval(
            symbol="ETHUSDT",
            valid_from=date(2020, 1, 1),
            valid_to=date(2026, 5, 1),
            delist_reason="not admitted to the 2026-05 universe",
        ),
        MembershipInterval(
            symbol="SOLUSDT", valid_from=date(2021, 8, 1), valid_to=date(2026, 9, 1)
        ),
    )
    assert resolve_universe(T, rows) == ("BTCUSDT", "SOLUSDT")
    assert MarketWindow.from_memberships(T, rows).universe == ("BTCUSDT", "SOLUSDT")
