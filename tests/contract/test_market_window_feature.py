"""Feature 9 — ``MarketWindow.feature`` returns exactly the version asked for.

app_spec.xml, "Signal Contract & Market Window", feature 9: *System exposes
MarketWindow.feature taking a name plus an explicit version, which returns
rows for that exact version only.*  docs/nullius-tech-architecture.md §4.4
supplies the reason the version is load-bearing — *"A changed definition gets a
new ``feature_version``; it never overwrites"* — so two versions of one feature
are two different definitions' output, and the whole content of feature 9 is
that the accessor hands back the one that was named.

That gives this suite two halves, and they fail in opposite directions:

* **the version is honoured** — a window carrying v1 and v2 of one name answers
  a v1 request with v1's rows and a v2 request with v2's rows, and never mixes
  them.  The negative half is the one worth having: an accessor that resolved
  "the latest version" would return values here and *pass* a test that only
  checked the values of one version, so the suite pins that a request for a
  version the window does not carry returns **nothing**.  An empty frame cannot
  leak a wrong version's numbers; a fallback silently would.
* **the request is validated** — a malformed name, version or lookback is a
  caller bug and is refused, which is a different fact from "the window does
  not carry that version" (that is the empty answer above).  The two must not
  be collapsed, or every typo reads as a data gap.

Two properties of the encoding are pinned from the side that matters: the frame
name is a *total, collision-free* function of ``(name, version)`` — the
separator is refused inside a component precisely so ``("a:1", "2")`` and
``("a", "1:2")`` cannot both spell one frame — and it is what feature 14's
payload carries across the sandbox boundary, so the version survives the trip
to the sandbox without a version *column* any caller could forget to filter on.

Feature 10 (which this accessor must satisfy) is pinned separately in
``test_market_window_accessors.py``; the last test here re-asserts the one
thing this feature could plausibly have broken — that adding an accessor did
not add a timestamp parameter.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

# pyarrow and polars are declared dependencies of the contract member, so under
# the canonical invocation (which is what the acceptance gate runs) both are
# present.  The guard keeps a partially installed environment from turning a
# missing wheel into a collection error that takes the whole repository suite
# down with it — the same idiom ``test_payload.py`` uses.
pa = pytest.importorskip(
    "pyarrow", reason="the feature-accessor suite requires pyarrow (a declared dependency)"
)
pl = pytest.importorskip(
    "polars", reason="the feature-accessor suite requires polars (a declared dependency)"
)

from contract import (  # noqa: E402
    FEATURE_FRAME_PREFIX,
    FeatureAccessError,
    MarketWindow,
    feature_frame_name,
    feature_frame_names,
    inspect_accessors,
    parse_feature_frame_name,
    select_feature_frame,
    validate_lookback,
)
from contract.features import require_polars  # noqa: E402
from contract.window import _timestamp_param_names  # noqa: E402

T = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
UNIVERSE = ("BTCUSDT", "ETHUSDT")


# --- fixtures ---------------------------------------------------------------


def _versioned_frame(**columns: list) -> "pa.Table":
    return pa.table(columns)


@pytest.fixture
def vol_v1() -> "pa.Table":
    return _versioned_frame(ts=[1, 2, 3], value=[0.1, 0.2, 0.3])


@pytest.fixture
def vol_v2() -> "pa.Table":
    # Deliberately *different values and a different length* from v1: a test
    # that only compared shapes could not tell a version mix-up from a
    # version-aware read.
    return _versioned_frame(ts=[1, 2], value=[9.9, 9.8])


@pytest.fixture
def window(vol_v1, vol_v2) -> MarketWindow:
    """A window carrying two versions of one name, plus an unrelated frame."""
    return MarketWindow(
        T,
        UNIVERSE,
        frames={
            feature_frame_name("vol", "1"): vol_v1,
            feature_frame_name("vol", "2"): vol_v2,
            "bars": _versioned_frame(ts=[1], close=[1.0]),
        },
    )


# --- the version is honoured ------------------------------------------------


def test_feature_returns_the_rows_of_the_version_asked_for(window, vol_v1, vol_v2):
    # The positive half: each version's rows come back as its own.
    assert window.feature("vol", "1").equals(pl.from_arrow(vol_v1))
    assert window.feature("vol", "2").equals(pl.from_arrow(vol_v2))


def test_the_two_versions_do_not_come_back_as_each_other(window):
    # Stated as the failure it prevents, because a values-only check on one
    # version would not catch a mix-up: the two answers are different data.
    assert not window.feature("vol", "1").equals(window.feature("vol", "2"))
    assert window.feature("vol", "1").height == 3
    assert window.feature("vol", "2").height == 2


def test_an_absent_version_returns_nothing_rather_than_the_nearest(window, vol_v2):
    # The load-bearing negative.  A window carrying v1 and v2 answers a v3
    # request with an *empty* frame — never the latest, never the nearest.
    # A fallback here would return v2's values and nothing downstream could
    # tell, which is the silent version-mixing feature 9 exists to forbid.
    answer = window.feature("vol", "3")
    assert answer.height == 0
    assert not answer.equals(pl.from_arrow(vol_v2))


def test_a_version_is_compared_exactly_not_by_prefix(window, vol_v1):
    # "1" must not match "10" any more than "on" matches "one".  A window
    # carrying only v1 answers a v10 request with nothing.
    assert window.feature("vol", "10").height == 0
    assert window.feature("vol", "1").height == vol_v1.num_rows


def test_an_absent_feature_name_returns_nothing(window):
    # The name half of the same rule: an unknown name is a miss, not a
    # fallback to whatever feature the window does carry.
    assert window.feature("momentum", "1").height == 0


def test_a_version_of_another_feature_does_not_stand_in(window, vol_v2):
    # Cross-product correctness: name *and* version both participate.  A
    # window with ("vol","1"), ("vol","2") and ("vol","10") must answer
    # ("vol", "10") with v10's rows and not with v1's or v2's.
    window = MarketWindow(
        T,
        UNIVERSE,
        frames={
            feature_frame_name("vol", "1"): _versioned_frame(v=[1.0]),
            feature_frame_name("vol", "2"): _versioned_frame(v=[2.0]),
            feature_frame_name("vol", "10"): _versioned_frame(v=[10.0]),
        },
    )
    assert window.feature("vol", "10")["v"].to_list() == [10.0]
    assert window.feature("vol", "1")["v"].to_list() == [1.0]


def test_a_window_carrying_no_frames_answers_with_an_empty_frame():
    # A window that has materialized nothing (the legitimate state
    # :attr:`MarketWindow.frames` documents) is still answerable: the accessor
    # reports no rows rather than raising, so a caller probing for a feature
    # before the host has populated it gets a value, not an exception.
    assert MarketWindow(T, UNIVERSE).feature("vol", "1").height == 0


def test_the_accessor_returns_a_polars_dataframe(window):
    # §5.1 declares ``-> pl.DataFrame``; the Arrow table the window stores is
    # an implementation detail of the transport, not the accessor's return
    # type.
    assert isinstance(window.feature("vol", "1"), pl.DataFrame)


def test_the_returned_frame_does_not_alias_the_windows_storage(window, vol_v1):
    # The accessor hands back a *converted* frame, but the conversion is
    # zero-copy (Arrow and Polars share buffers), so the two are views of the
    # same values.  What matters is that neither side can be written through:
    # a window is immutable (feature 4), and a converted Polars frame never
    # writes back into the window's table.
    before = window.feature("vol", "1")["value"].to_list()
    frame = window.feature("vol", "1")
    frame = frame.with_columns(pl.lit(0.0).alias("value"))
    assert window.feature("vol", "1")["value"].to_list() == before


# --- the lookback -----------------------------------------------------------


def test_lookback_none_returns_every_row_the_window_carries(window, vol_v1):
    assert window.feature("vol", "1", None).height == vol_v1.num_rows


def test_lookback_returns_the_trailing_rows(window, vol_v1):
    # "The last N rows" is the recent end of an oldest-first frame — the end
    # nearest the decision time, which is what a lookback means.
    assert window.feature("vol", "1", lookback=2)["value"].to_list() == [0.2, 0.3]
    assert window.feature("vol", "1", lookback=1)["value"].to_list() == [0.3]


def test_a_lookback_larger_than_the_frame_returns_the_whole_frame(window, vol_v1):
    # Not an error, and not an empty frame: "the last 500 rows" of a 3-row
    # frame is those 3 rows.  The alternative — an out-of-range offset — would
    # make a caller's over-long lookback read as "no data".
    assert window.feature("vol", "1", lookback=500).height == vol_v1.num_rows


def test_lookback_zero_is_an_empty_frame_not_the_whole_frame(window):
    # The off-by-one worth pinning: 0 rows means 0 rows.  If this ever
    # returned everything, a caller asking for "no rows" would silently get
    # the window's whole history.
    assert window.feature("vol", "1", lookback=0).height == 0


def test_a_miss_and_an_empty_read_are_distinguishable(window):
    # Two shapes of empty, and the difference is the feature's whole point.
    # A version the window does not carry yields a frame with *no columns* —
    # the window holds no schema for data it was never given.  A version that
    # is present, read down to nothing, yields 0 rows *with that version's
    # columns*.  So a caller that sees an empty answer can still tell "this
    # version was never computed" from "this version had no rows in the
    # slice" — which is what keeps a miss from being read as a data gap, and
    # vice versa.
    miss = window.feature("vol", "3")
    empty_read = window.feature("vol", "1", lookback=0)

    assert miss.height == 0 and empty_read.height == 0
    assert miss.columns == []
    assert empty_read.columns == ["ts", "value"]


def test_a_missing_version_reports_as_a_missing_column_not_a_silent_zero(window):
    # The consequence of the shape above, stated as the caller experiences it:
    # asking a miss for its column raises rather than handing back something
    # that could be summed into a zero.  A "helpful" empty frame with invented
    # columns would let a signal compute on absent data and produce a
    # plausible number, which is worse than an exception at the call site.
    with pytest.raises(pl.exceptions.ColumnNotFoundError):
        window.feature("vol", "3")["value"]


def test_a_feature_named_after_another_frame_does_not_collide():
    # The prefix is what keeps feature 9's namespace separate from the
    # window's other frames: a feature literally called "bars" gets its own
    # frame, and the real "bars" frame is untouched.  Without the prefix, a
    # feature name would collide with whatever else the host materialized.
    window = MarketWindow(
        T,
        UNIVERSE,
        frames={
            "bars": _versioned_frame(close=[1.0, 2.0]),
            feature_frame_name("bars", "1"): _versioned_frame(close=[9.0]),
        },
    )
    assert window.frames["bars"].num_rows == 2
    assert window.feature("bars", "1")["close"].to_list() == [9.0]
    assert window.feature("bars", "2").shape == (0, 0)


def test_a_lookback_on_an_absent_version_is_still_empty(window):
    # Validation and lookup are independent: the miss stays a miss.
    assert window.feature("vol", "3", lookback=2).height == 0


def test_a_negative_lookback_is_refused(window):
    # Refused rather than clamped: a negative count means the caller's
    # arithmetic went wrong, and clamping would hide it behind a plausible
    # answer.  A ValueError, because it is a caller bug at the accessor.
    with pytest.raises(FeatureAccessError):
        window.feature("vol", "1", lookback=-1)


def test_a_boolean_lookback_is_refused(window):
    # ``True`` is an ``int`` in Python and would silently mean "the last one
    # row" — a wrong answer that looks like a right one, which is the failure
    # mode this whole module is built against.
    with pytest.raises(FeatureAccessError):
        window.feature("vol", "1", lookback=True)


def test_a_non_integer_lookback_is_refused(window):
    for bad in ("2", 2.0, [2]):
        with pytest.raises(FeatureAccessError):
            window.feature("vol", "1", lookback=bad)


# --- the request is validated -----------------------------------------------


def test_an_empty_or_padded_name_is_refused(window):
    for bad in ("", " vol", "vol "):
        with pytest.raises(FeatureAccessError):
            window.feature(bad, "1")


def test_an_empty_or_padded_version_is_refused(window):
    # An empty version is the one default feature 9 does *not* have: a caller
    # that does not know the version must be told, not handed a guess.
    for bad in ("", " 1", "1 "):
        with pytest.raises(FeatureAccessError):
            window.feature("vol", bad)


def test_a_non_string_name_or_version_is_refused(window):
    for bad in (1, None, ["vol"]):
        with pytest.raises(FeatureAccessError):
            window.feature(bad, "1")
        with pytest.raises(FeatureAccessError):
            window.feature("vol", bad)


def test_a_malformed_request_is_reported_even_against_an_empty_window():
    # Ordering, pinned: the *question* is validated before the window is
    # consulted, so a typo against a window carrying nothing still reports the
    # typo rather than reading as "no rows for that version".
    empty = MarketWindow(T, UNIVERSE)
    with pytest.raises(FeatureAccessError):
        empty.feature("vol", "")


# --- the encoding -----------------------------------------------------------


def test_the_frame_name_encodes_both_components():
    assert feature_frame_name("vol", "1") == f"{FEATURE_FRAME_PREFIX}:vol:1"
    assert feature_frame_name("vol", "1") != feature_frame_name("vol", "2")
    assert feature_frame_name("vol", "1") != feature_frame_name("vol2", "1")


def test_the_frame_name_round_trips():
    assert parse_feature_frame_name(feature_frame_name("vol", "v2")) == ("vol", "v2")


def test_round_tripping_holds_for_the_parts_of_a_stored_key():
    # The realistic shapes a version arrives in: a numeric stamp, a "v"
    # stamp, dotted numerics (feature 15's ``0.10.0``), a hyphenated name.
    for name, version in (
        ("realized_vol", "1"),
        ("realized_vol", "v2"),
        ("cross_sectional_dispersion", "0.10.0"),
        ("vol-of-vol", "2026-09-01"),
    ):
        assert parse_feature_frame_name(feature_frame_name(name, version)) == (
            name,
            version,
        )


def test_the_separator_is_refused_inside_a_component():
    # The collision this refusal prevents, stated directly: without it,
    # ("a:1", "2") and ("a", "1:2") would both spell "feature:a:1:2" — two
    # distinct feature versions addressing one frame, which *is* the silent
    # version-mixing feature 9 forbids, arriving through the encoding rather
    # than the lookup.
    with pytest.raises(FeatureAccessError):
        feature_frame_name("a:1", "2")
    with pytest.raises(FeatureAccessError):
        feature_frame_name("a", "1:2")


def test_path_unsafe_components_are_refused():
    # A frame name travels into a payload manifest and, on the materialisation
    # side, toward a filesystem — the same reason :mod:`feature_store.keys`
    # refuses these in a key component.
    for bad in ("a/b", "a\\b", "a\0b", "a\nb"):
        with pytest.raises(FeatureAccessError):
            feature_frame_name(bad, "1")


def test_encodable_names_are_a_collision_free_domain():
    # The property the refusal buys, over a sample grid: distinct pairs give
    # distinct frame names.  Injective, so the frame name is a faithful
    # address and not merely a label.
    pairs = [
        (name, version)
        for name in ("a", "b", "vol_1", "vol:1".replace(":", ""), "1")
        for version in ("1", "2", "10", "v1", "0.1.0")
    ]
    names = [feature_frame_name(name, version) for name, version in pairs]
    assert len(set(names)) == len(pairs)
    assert [parse_feature_frame_name(name) for name in names] == pairs


def test_parsing_a_non_feature_frame_is_none_not_an_error():
    # Enumeration has to be answerable over a mapping that holds other frames
    # too, so a non-feature frame is reported as "not one of mine" rather than
    # raising.
    for other in ("bars", "trades", "scores", "", "feature", "feature:vol",
                  "feature:vol:1:extra", "notfeature:vol:1", 7, None, object()):
        assert parse_feature_frame_name(other) is None


def test_parsing_is_the_inverse_of_encoding_over_a_real_window(window):
    # The property as a caller exercises it: every feature frame the window
    # carries is enumerated back as the pair that named it, and the
    # non-feature frame is not.
    assert feature_frame_names(window.frames) == (("vol", "1"), ("vol", "2"))


def test_feature_frame_names_is_sorted_and_deduplicated():
    frames = {
        feature_frame_name("b", "1"): object(),
        feature_frame_name("a", "2"): object(),
        feature_frame_name("a", "1"): object(),
    }
    assert feature_frame_names(frames) == (("a", "1"), ("a", "2"), ("b", "1"))


def test_select_is_the_exact_match_the_accessor_uses(window, vol_v1):
    # The pure core, exercised apart from the DataFrame conversion: it
    # returns the stored table itself, and ``None`` — not a neighbour — for a
    # version the mapping does not carry.
    assert select_feature_frame(window.frames, "vol", "1") is window.frames[
        feature_frame_name("vol", "1")
    ]
    assert select_feature_frame(window.frames, "vol", "3") is None
    assert select_feature_frame(window.frames, "nope", "1") is None


# --- validation core --------------------------------------------------------


def test_validate_lookback_accepts_none_and_non_negative_ints():
    assert validate_lookback(None) is None
    assert validate_lookback(0) == 0
    assert validate_lookback(7) == 7


def test_validate_lookback_refuses_everything_else():
    for bad in (-1, True, False, 1.0, "1", [1]):
        with pytest.raises(FeatureAccessError):
            validate_lookback(bad)


# --- the version survives the payload channel (feature 14) ------------------


def test_the_version_travels_with_the_payload(vol_v1, vol_v2):
    # Why the version lives in the *frame name* and not in a column: the
    # sandbox holds no filesystem and obtains its window only as Arrow IPC
    # bytes (feature 14, §5.2), and frame names are what the payload manifest
    # records.  So a window that crossed the channel still answers the exact
    # version — no version column a caller could forget to filter on, and no
    # re-resolution against a registry the sandbox does not have.
    window = MarketWindow(
        T,
        UNIVERSE,
        frames={
            feature_frame_name("vol", "1"): vol_v1,
            feature_frame_name("vol", "2"): vol_v2,
        },
    )
    rebuilt = window.to_arrow().materialize()
    assert rebuilt.feature("vol", "2").equals(window.feature("vol", "2"))
    assert rebuilt.feature("vol", "1").equals(window.feature("vol", "1"))
    assert rebuilt.feature("vol", "3").height == 0
    assert feature_frame_names(rebuilt.frames) == (("vol", "1"), ("vol", "2"))


# --- feature 10 still holds -------------------------------------------------


def test_the_new_accessor_takes_no_timestamp_argument():
    # Feature 10's requirement, re-asserted over the surface *this* feature
    # changed: adding an accessor is exactly the edit that could have
    # reintroduced a widening parameter, and `lookback` — an amount of data,
    # not an instant — must not be flagged as one.
    assert _timestamp_param_names(MarketWindow.feature) == ()
    assert "feature" in inspect_accessors()


def test_require_polars_returns_the_real_module():
    # The lazy import seam, pinned directly: it resolves, and it is polars.
    assert require_polars() is pl
